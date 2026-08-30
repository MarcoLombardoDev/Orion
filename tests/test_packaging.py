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

import pathlib
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

    def test_regenerating_them_reproduces_what_is_committed(self, tmp_path):
        """The committed files are the generator's output, and stay that way.

        This is the check that makes "regenerate and diff" a usable answer to
        "is the icon still the one the script draws". It is also the check that
        would have caught the way the arguments used to work: the letter and
        the file name came from one argument, so the only way to write the
        right file name here was to pass the wrong letter, and doing exactly
        that redrew this product's icons with someone else's initial on them.

        Skipped where the serif face is not installed: the drawing depends on
        it, so on a machine without it the comparison would be measuring the
        font rather than the generator.
        """
        import subprocess
        import sys

        pytest.importorskip("PIL", reason="Pillow draws the icons")
        sys.path.insert(0, str(REPO / "tools"))
        try:
            import make_icon
        finally:
            sys.path.pop(0)
        if not any(pathlib.Path(p).exists() for p in make_icon.FONT_CANDIDATES):
            pytest.skip("no serif font installed; the drawing would differ")

        run = subprocess.run(
            [sys.executable, str(REPO / "tools" / "make_icon.py"),
             "Orion", str(tmp_path), "orion"],
            capture_output=True, text=True,
        )
        assert run.returncode == 0, run.stderr

        for suffix in (".png", ".ico", ".icns"):
            committed = REPO / "resources/icons" / f"orion{suffix}"
            if not committed.exists():
                # The generator writes all three for everybody; only the
                # products that build a macOS application bundle have any
                # use for the .icns, and the rest do not carry one.
                assert suffix == ".icns", f"{committed.name} is missing"
                continue
            fresh = (tmp_path / "orion").with_suffix(suffix)
            assert fresh.read_bytes() == committed.read_bytes(), (
                f"{committed.name} is not what tools/make_icon.py draws today"
            )

    def test_the_generator_is_kept_with_them(self):
        """So the next one can be drawn the same way rather than guessed at."""
        assert (REPO / "tools" / "make_icon.py").is_file()


class TestLooksLikeTheOthers:
    """Orion carries the palette Iris and Proteus get from ttkbootstrap.

    Those two are Tk applications and this one is Qt, so the library cannot be
    shared — only the numbers can, and they are the numbers that matter. If
    the three drift apart, it will be here, in a hex code nobody thought to
    change twice.
    """

    SHEET = REPO / "resources" / "styles" / "orion.qss"

    #: flatly, which is what the other two resolve to. Same values, written
    #: out rather than imported, because there is nothing to import across a
    #: repository boundary.
    PALETTE = {
        "ground": "#ffffff",
        "text": "#212529",
        "primary": "#2c3e50",
        "muted": "#95a5a6",
        "rule": "#dee2e6",
    }

    def test_the_stylesheet_is_in_the_repository(self):
        assert self.SHEET.is_file(), f"{self.SHEET} is missing"

    def test_it_carries_the_shared_palette(self):
        sheet = self.SHEET.read_text(encoding="utf-8")
        for name, colour in self.PALETTE.items():
            assert colour in sheet, f"the {name} colour ({colour}) is not in the sheet"

    def test_its_braces_balance(self):
        """Qt discards a stylesheet it cannot parse, silently as far as the
        interface is concerned: the application simply comes up looking like
        it did before.
        """
        sheet = self.SHEET.read_text(encoding="utf-8")
        assert sheet.count("{") == sheet.count("}")

    def test_it_is_applied_at_start_up(self):
        source = (REPO / "orion" / "main.py").read_text(encoding="utf-8")
        assert "_apply_stylesheet(app)" in source

    def test_it_travels_with_the_build(self):
        """It lives under resources/, which the spec ships whole. A stylesheet
        left behind would make the frozen build the odd one out.
        """
        spec = (REPO / "orion.spec").read_text(encoding="utf-8")
        assert 'datas=[(str(BUILD_DIR / "resources"), "resources")]' in spec

    def test_qt_accepts_it(self):
        """Parsed by Qt itself rather than by eye. A rule Qt rejects takes the
        whole sheet with it.
        """
        pytest.importorskip("PySide6", reason="Qt is not installed here")
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance() or QApplication([])
        previous = app.styleSheet()
        try:
            app.setStyleSheet(self.SHEET.read_text(encoding="utf-8"))
            assert self.PALETTE["primary"] in app.styleSheet(), (
                "Qt did not keep the stylesheet"
            )
        finally:
            app.setStyleSheet(previous)


class TestMacOSIcon:
    """The container macOS will accept, and nothing else.

    PyInstaller's BUNDLE() takes an .icns and only an .icns. Handed a PNG it
    converts on the fly *if* Pillow is installed in the build environment, and
    raises "not in the correct format" if it is not — after the whole build has
    already succeeded, on the last line of the spec. The v1.0.0 macOS job of
    the product that does not depend on Pillow failed exactly there, with
    Windows and Linux already published.

    An icon committed as a file cannot fail that way, so the .icns is drawn by
    tools/make_icon.py alongside the .ico and the .png, and these check that
    what was committed is a real one.
    """

    ICNS = REPO / "resources" / "icons" / "orion.icns"

    def test_it_is_in_the_repository(self):
        assert self.ICNS.is_file(), f"{self.ICNS} is missing"

    def test_it_is_a_real_icns_container(self):
        """Parsed rather than trusted: the header carries the total length, so
        a truncated or mis-assembled file says so at the first chunk.
        """
        import struct

        raw = self.ICNS.read_bytes()
        assert raw[:4] == b"icns", f"wrong magic: {raw[:4]!r}"
        declared = struct.unpack(">I", raw[4:8])[0]
        assert declared == len(raw), f"header says {declared}, file is {len(raw)}"

        position, seen = 8, []
        while position < len(raw):
            kind = raw[position:position + 4]
            length = struct.unpack(">I", raw[position + 4:position + 8])[0]
            assert length >= 8, f"{kind!r} declares {length} bytes"
            assert position + length <= len(raw), f"{kind!r} runs past the end"
            seen.append(kind)
            position += length
        assert position == len(raw), "the chunks do not add up to the file"
        assert len(seen) >= 5, f"only {len(seen)} entries"

    def test_it_carries_the_sizes_the_finder_asks_for(self):
        """Including the retina pairs: without ic11 and ic12 a retina Finder
        scales a 16-pixel drawing instead of using a 32-pixel one.
        """
        import struct

        raw = self.ICNS.read_bytes()
        position, kinds = 8, set()
        while position < len(raw):
            kinds.add(raw[position:position + 4])
            position += struct.unpack(">I", raw[position + 4:position + 8])[0]
        for required in (b"ic07", b"ic08", b"ic09", b"ic11", b"ic12"):
            assert required in kinds, f"no {required.decode()} entry"

    def test_every_entry_decodes_to_the_size_it_claims(self):
        """A chunk type is a promise about pixel dimensions, and nothing in the
        container enforces it.
        """
        import io
        import struct

        Image = pytest.importorskip("PIL.Image", reason="Pillow reads the entries")
        expected = {
            b"icp4": 16, b"icp5": 32, b"ic11": 32, b"ic12": 64,
            b"ic07": 128, b"ic13": 256, b"ic08": 256, b"ic14": 512, b"ic09": 512,
        }
        raw = self.ICNS.read_bytes()
        position = 8
        while position < len(raw):
            kind = raw[position:position + 4]
            length = struct.unpack(">I", raw[position + 4:position + 8])[0]
            blob = raw[position + 8:position + length]
            with Image.open(io.BytesIO(blob)) as frame:
                assert frame.format == "PNG", f"{kind.decode()} is {frame.format}"
                if kind in expected:
                    assert frame.size == (expected[kind], expected[kind]), (
                        f"{kind.decode()} holds {frame.size}"
                    )
            position += length

    def test_macos_is_given_the_icns_and_not_the_png(self):
        """The spec line that failed. A PNG here builds everything and then
        raises on the last statement of the file.

        Checked in two places because the two products resolve the icon
        differently: one maps the platform to a file name, the other picks a
        constant. What both have to be true of is that macOS gets the .icns
        and that the bundle is never handed the PNG.
        """
        spec = (REPO / "orion.spec").read_text(encoding="utf-8")
        mapped = [
            line for line in spec.splitlines()
            if "darwin" in line and "icns" in line.lower()
        ]
        assert mapped, "nothing in the spec maps macOS to the .icns"

        # Anchored on the assignment, not on the word: the comment above it
        # mentions BUNDLE() by name, and a search for that found the comment
        # and then read the EXE's icon line instead. The first version of this
        # test passed against a spec with the PNG put back.
        bundle = spec[spec.index("= BUNDLE("):]
        icon_line = next(
            line for line in bundle.splitlines() if line.strip().startswith("icon=")
        )
        assert "PNG" not in icon_line and ".png" not in icon_line, icon_line


class TestLicenceHeader:
    """Every source file opens with the same seven lines.

    A file copied out of this repository has to say what it is and what may be
    done with it, which is the whole reason the header exists. That it is
    *present* was checked when it was added; that it is still one unbroken
    block at the top was not — and in one of these products an automated edit
    inserted an import between the product name and the copyright line, where
    it sat unnoticed because every check only looked for the SPDX line
    somewhere in the file.
    """

    #: The shape, not the wording: the product line differs per repository and
    #: the year will move.
    SHAPE = (
        "# Orion",
        "# Copyright (C)",
        "#",
        "# SPDX-License-Identifier: AGPL-3.0-or-later",
        "# Distributed WITHOUT ANY WARRANTY; see LICENSE for the full terms.",
        "# A commercial licence, without the AGPL's obligations, is available for use",
        "# in proprietary or closed-source products — see COMMERCIAL-LICENSE.md.",
    )

    def sources(self):
        for root in ("orion", "tests", "tools"):
            for path in sorted((REPO / root).rglob("*.py")):
                if "__pycache__" in path.parts or ".venv" in path.parts:
                    continue
                yield path

    def test_there_is_something_to_check(self):
        assert list(self.sources()), "no source files found; the roots are wrong"

    def test_every_file_opens_with_the_unbroken_header(self):
        wrong = []
        for path in self.sources():
            lines = path.read_text(encoding="utf-8").splitlines()
            # A shebang, where a file has one, stays on the first line.
            if lines and lines[0].startswith("#!"):
                lines = lines[1:]
            for offset, expected in enumerate(self.SHAPE):
                if offset >= len(lines) or not lines[offset].startswith(expected):
                    got = lines[offset] if offset < len(lines) else "<end of file>"
                    wrong.append(
                        f"{path.relative_to(REPO)} line {offset + 1}: "
                        f"expected {expected!r}, found {got!r}"
                    )
                    break
        assert not wrong, "the licence header is broken in:\n  " + "\n  ".join(wrong)
