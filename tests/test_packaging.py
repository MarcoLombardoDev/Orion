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


@pytest.mark.parametrize(
    "module, reason",
    [
        ("readline", "links libreadline, GPL-3.0-or-later with no linking exception"),
        ("rlcompleter", "imports readline and exists for nothing else"),
    ],
)
def test_the_gpl3_readline_chain_is_excluded(spec_source, module, reason):
    """The exclusion that v1.0.0 was missing.

    PyInstaller collects the standard library's optional readline extension by
    default, and it links libreadline — GPL-3.0-or-later with no linking
    exception. That put a GPL-3 library inside an archive
    COMMERCIAL-LICENSE.md offers for redistribution in closed-source products,
    which is the one combination the commercial tier cannot survive.
    THIRD-PARTY-LICENSES.md recorded it the whole time; nobody read the row.

    libpython does not link it. Only that module does, and Orion never reads a
    line from an interactive prompt.
    """
    assert f'"{module}"' in spec_source, (
        f"{module} is not excluded from the bundle — {reason}"
    )


def test_the_readline_exclusion_says_why():
    """A bare name in an exclusion list is deleted by the next person who tidies
    it, because nothing tells them what it is for.
    """
    assert "GPL-3.0-or-later, with no linking exception" in SPEC_PATH.read_text(
        encoding="utf-8"
    )


class TestApplicationIcon:
    """One letter, black, on white, in a serif face — the same drawing in all
    four products, differing only in the letter.

    Committed rather than generated during the build: a release that depended
    on which fonts a runner happened to have would produce a different icon
    depending on the machine, or none.
    """

    ICO = REPO / "resources/icons/orion.ico"
    PNG = REPO / "resources/icons/orion.png"

    def test_both_files_are_in_the_repository(self):
        assert self.ICO.is_file(), f"{self.ICO} is missing"
        assert self.PNG.is_file(), f"{self.PNG} is missing"

    def test_the_ico_carries_every_size_windows_asks_for(self):
        """An .ico with only one frame makes Windows scale it, and a 256-pixel
        letter scaled to 16 is a grey smudge on the taskbar.
        """
        Image = pytest.importorskip("PIL.Image", reason="Pillow reads the icon")
        with Image.open(self.ICO) as icon:
            sizes = {size[0] for size in icon.info["sizes"]}
        assert {16, 24, 32, 48, 64, 128, 256} <= sizes, f"only {sorted(sizes)}"

    def test_the_png_is_big_enough_for_a_retina_dock(self):
        Image = pytest.importorskip("PIL.Image", reason="Pillow reads the icon")
        with Image.open(self.PNG) as png:
            assert png.size == (512, 512)

    def test_the_frame_is_there_at_every_size(self):
        """The four products draw their window icon from different sources —
        Qt scales the 512-pixel PNG, Tk picks the matching frame out of the
        .ico — so a rule that dropped the frame at small sizes made one
        product look like two and the four look like four families. Reported
        exactly that way: one had a black border and another did not.
        """
        Image = pytest.importorskip("PIL.Image", reason="Pillow reads the icon")
        with Image.open(self.ICO) as icon:
            sizes = sorted(icon.info["sizes"])
            for size in sizes:
                icon.size = size
                frame = icon.copy().convert("L")
                width, height = frame.size
                edge = (
                    [frame.getpixel((x, 0)) for x in range(width)]
                    + [frame.getpixel((x, height - 1)) for x in range(width)]
                    + [frame.getpixel((0, y)) for y in range(height)]
                    + [frame.getpixel((width - 1, y)) for y in range(height)]
                )
                dark = sum(1 for value in edge if value < 128)
                assert dark > len(edge) * 0.8, (
                    f"the {width}px frame is missing or too faint "
                    f"({dark} of {len(edge)} edge pixels are dark)"
                )

    def test_it_is_black_on_white(self):
        """Not a check of taste: an icon that came out mostly transparent, or
        inverted, still opens and still looks like a file.
        """
        Image = pytest.importorskip("PIL.Image", reason="Pillow reads the icon")
        with Image.open(self.PNG) as png:
            pixels = list(png.convert("L").getdata())
        white = sum(1 for value in pixels if value > 200)
        black = sum(1 for value in pixels if value < 60)
        assert white > black, "the icon is mostly dark; the background should be white"
        assert black > len(pixels) // 100, "there is almost no ink; is the letter there?"

    def test_the_small_frames_are_uncompressed(self):
        """DIB below 256 pixels, PNG only for the 256.

        Windows has accepted PNG-compressed frames since Vista, but the format
        every icon editor produces — and the one the shell has always read —
        is an uncompressed DIB at the small sizes. Explorer showing a stale or
        generic icon for an executable whose resources are demonstrably
        correct is exactly the shape of problem that convention avoids.
        """
        import struct

        data = self.ICO.read_bytes()
        _, _, count = struct.unpack("<HHH", data[:6])
        png_magic = b"\x89PNG\r\n\x1a\x0a"
        for index in range(count):
            entry = 6 + index * 16
            width, _h, _c, _r, _p, _b, size, offset = struct.unpack(
                "<BBBBHHII", data[entry:entry + 16]
            )
            width = width or 256
            is_png = data[offset:offset + 8] == png_magic
            if width >= 256:
                assert is_png, "the 256 frame should be PNG; it is the one worth compressing"
            else:
                assert not is_png, f"the {width}px frame is PNG-compressed"

    def test_every_frame_reads_back_at_its_declared_size(self):
        """The .ico is assembled by hand, so a wrong header length or a
        bottom-up row order would produce a file that still opens and is
        quietly wrong.
        """
        Image = pytest.importorskip("PIL.Image", reason="Pillow reads the icon")
        with Image.open(self.ICO) as icon:
            sizes = sorted(icon.info["sizes"])
            for size in sizes:
                icon.size = size
                frame = icon.copy().convert("L")
                pixels = list(frame.get_flattened_data()
                              if hasattr(frame, "get_flattened_data") else frame.getdata())
                assert len(pixels) == size[0] * size[1]
                assert any(value < 60 for value in pixels), f"{size[0]}px has no ink"
                assert any(value > 200 for value in pixels), f"{size[0]}px has no ground"

    def test_the_generator_is_kept_with_them(self):
        """So the next one can be drawn the same way rather than guessed at."""
        assert (REPO / "tools" / "make_icon.py").is_file()
