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
