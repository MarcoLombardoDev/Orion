# Orion — PDF Editor for Desktop
# Copyright (C) 2026 Marco Lombardo
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# Distributed WITHOUT ANY WARRANTY; see LICENSE for the full terms.
# A commercial licence, without the AGPL's obligations, is available for use
# in proprietary or closed-source products — see COMMERCIAL-LICENSE.md.

"""Tests for orion.spec, the PyInstaller build description.

One of these guards a licensing mistake rather than a bug. PyInstaller's
``excludes`` only drops *Python* modules; the native Qt libraries and plugins
its hooks pull in come along regardless. That is how a build of Orion came to
ship Qt Virtual Keyboard — which Qt licenses under **GPLv3 or commercial, not
LGPL** — inside a binary that is also offered under a commercial licence.

Nothing in Orion has ever used a virtual keyboard. It arrived on its own, and
it would arrive again the moment the filter in orion.spec is edited without
this test noticing.
"""

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SPEC_PATH = REPO / "orion.spec"

#: Components that must never reach the bundle, and why.
FORBIDDEN = {
    "virtualkeyboard": "Qt licenses it under GPLv3 or commercial, never LGPL",
    "platforminputcontexts": "the plugin that loads the virtual keyboard",
}

#: Unused, but a size and obligation concern rather than a licence conflict.
UNWANTED = ("qt6quick", "qtquick", "qt6qml", "qtqml", "eglfs")

#: Qt PDF, Qt Network and the plugins that link them. Orion imports QtCore,
#: QtGui and QtWidgets; the ``qpdf`` image-format plugin pulled a whole second
#: PDF engine along behind them, and Qt Network pulled the Kerberos stack.
UNREACHABLE = (
    "imageformats/libqpdf",
    "qt6pdf",
    "plugins/tls",
    "plugins/networkinformation",
    "qt6network",
    "qtnetwork",
)

#: Orphaned once Qt Network leaves: nothing outside this chain links it.
ORPHANS = ("libgssapi_krb5", "libkrb5", "libk5crypto", "libcom_err", "libkeyutils")


@pytest.fixture(scope="module")
def spec_source() -> str:
    assert SPEC_PATH.exists(), "orion.spec is missing"
    return SPEC_PATH.read_text(encoding="utf-8")


def test_the_spec_filters_collected_binaries_and_data(spec_source):
    """The filter has to be applied, not merely defined."""
    assert "analysis.binaries = _drop_unused(analysis.binaries)" in spec_source
    assert "analysis.datas = _drop_unused(analysis.datas)" in spec_source


@pytest.mark.parametrize("component,reason", sorted(FORBIDDEN.items()))
def test_gpl_only_components_are_excluded(spec_source, component, reason):
    filter_list = _filter_list(spec_source)
    assert component in filter_list, (
        f"{component!r} must stay in UNUSED_QT_COMPONENTS: {reason}. "
        "Shipping it puts GPLv3 code in a binary sold under a commercial licence."
    )


@pytest.mark.parametrize("component", UNWANTED)
def test_unused_components_are_excluded(spec_source, component):
    assert component in _filter_list(spec_source)


@pytest.mark.parametrize("component", UNREACHABLE)
def test_unreachable_qt_modules_are_excluded(spec_source, component):
    """Qt PDF is a second PDF engine, shipped for a plugin nothing calls.

    Orion renders with MuPDF. libQt6Pdf reached the v1.0.0 archives only
    because Qt's ``qpdf`` *image-format* plugin links it, and it embeds PDFium
    and its own third-party dependencies — a second engine, and a second set of
    licence obligations, for a code path that never executes.
    """
    assert component in _filter_list(spec_source)


@pytest.mark.parametrize("library", ORPHANS)
def test_the_kerberos_chain_leaves_with_qt_network(spec_source, library):
    """Removing a library without its dependants leaves them in the archive.

    PyInstaller resolved these during Analysis, before the filter runs, so
    dropping libQt6Network does not drop what libQt6Network dragged in. They
    have to be named. libcom_err is the reason this matters beyond size: its
    licence is disputed between Ubuntu's copyright file and upstream
    e2fsprogs, and not shipping it settles the question.
    """
    start = spec_source.index("ORPHANED_BY_REMOVAL = (")
    end = spec_source.index(")", start)
    assert library in spec_source[start:end]


def test_orphans_are_actually_filtered(spec_source):
    """A second list that the filter never consults would be decoration."""
    assert "ORPHANED_BY_REMOVAL" in spec_source.split("def _drop_unused")[1]


def test_licence_texts_are_added_to_the_bundle(spec_source):
    """The v1.0.0 archives shipped without a single licence file in them.

    LGPL-3.0 §4 wants a copy of the licence to accompany the object code, and
    every BSD and MIT library in the bundle wants its notice reproduced. A
    THIRD-PARTY-LICENSES.md in the repository does not satisfy either: the
    person who downloads a zip never sees it.
    """
    assert "collect_licences(" in spec_source
    assert 'str(Path("licenses")' in spec_source, (
        "the collected texts must land in the bundle as licenses/"
    )


def test_licences_are_collected_after_the_filter_runs(spec_source):
    """Order matters: the system copyright records are read from the binaries
    that survive, so collecting first would document libraries that were then
    removed — and miss none that stayed."""
    assert spec_source.index("analysis.binaries = _drop_unused") < spec_source.index(
        "collect_licences("
    )


def test_qt_own_libraries_are_not_caught_by_the_gtk_filter(spec_source):
    """The GTK filter must not take libraries Qt links itself.

    ``ldd`` over the built bundle shows libglib, libgobject, libgio, libfreetype,
    libharfbuzz, libgcrypt and libsystemd are linked by libQt6Gui, libQt6Widgets,
    libQt6DBus and most Qt plugins. They look like part of the GTK stack and are
    not; removing them breaks Qt rather than saving space.
    """
    stack = _gtk_stack(spec_source)
    for library in ("libglib", "libgobject", "libgio", "libfreetype",
                    "libharfbuzz", "libgcrypt", "libsystemd"):
        assert library not in stack, (
            f"{library} is linked by Qt itself, not only by GTK"
        )


def test_the_gtk_platform_theme_plugin_is_excluded(spec_source):
    """Leaving the plugin in while removing its libraries would ship a plugin
    that fails to load, which is worse than either shipping or dropping both."""
    assert "qgtk3" in _filter_list(spec_source)
    assert "libgtk-3" in _gtk_stack(spec_source)


def test_wayland_is_not_excluded(spec_source):
    """Wayland is the default session on current Linux desktops.

    It is genuinely used, unlike the components above, so a filter that caught
    it would be a functional regression rather than a cleanup.
    """
    assert "wayland" not in _filter_list(spec_source)
    assert "wayland" not in _gtk_stack(spec_source)


def test_the_filter_matches_case_insensitively(spec_source):
    """File names differ per platform: libQt6VirtualKeyboard.so, Qt6VirtualKeyboard.dll,
    QtVirtualKeyboard.framework. Matching has to be lower-cased to catch all three."""
    assert ".lower()" in spec_source


def _gtk_stack(spec_source: str) -> str:
    start = spec_source.index("GTK_STACK = (")
    end = spec_source.index(")", start)
    return spec_source[start:end].lower()


def _filter_list(spec_source: str) -> str:
    start = spec_source.index("UNUSED_QT_COMPONENTS = (")
    end = spec_source.index(")", start)
    return spec_source[start:end].lower()
