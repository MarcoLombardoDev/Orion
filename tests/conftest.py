# Orion — PDF Editor for Desktop
# Copyright (C) 2026 Marco Lombardo
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# Distributed WITHOUT ANY WARRANTY; see LICENSE for the full terms.
# A commercial licence, without the AGPL's obligations, is available for use
# in proprietary or closed-source products — see COMMERCIAL-LICENSE.md.

"""Shared fixtures.  The model/engine tests need no display server."""

from __future__ import annotations

import io
import os
from contextlib import suppress
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="session", autouse=True)
def _isolated_home(tmp_path_factory) -> Path:
    """Keep the test-suite out of the developer's real config/cache folders."""
    home = tmp_path_factory.mktemp("orion-home")
    os.environ["ORION_HOME"] = str(home)
    return home


@pytest.fixture
def sample_pdf(tmp_path: Path) -> Path:
    """A three-page PDF with distinct, searchable text on each page."""
    from reportlab.pdfgen import canvas

    path = tmp_path / "sample.pdf"
    pdf = canvas.Canvas(str(path), pagesize=(400, 600))
    for index in range(3):
        pdf.setFont("Helvetica", 18)
        # reportlab measures from the bottom; the old fixture placed this
        # baseline 100pt below the top, and the search tests know where it is.
        pdf.drawString(50, 600 - 100, f"PAGE {index + 1} NEEDLE")
        pdf.showPage()
    pdf.save()
    return path


@pytest.fixture
def sample_image(tmp_path: Path) -> Path:
    from PIL import Image

    path = tmp_path / "swatch.png"
    Image.new("RGB", (40, 20), (0, 128, 255)).save(path)
    return path


def render_page(path: Path, index: int = 0, dpi: int = 72):
    """Rasterise a saved PDF page for pixel assertions."""
    import pypdfium2 as pdfium

    document = pdfium.PdfDocument(str(path))
    try:
        image = (
            document[index]
            .render(scale=dpi / 72.0, rev_byteorder=True)
            .to_pil()
            .convert("RGB")
        )
    finally:
        document.close()
    return _Pixmap(image)


class _Pixmap:
    """A rendered page with the handful of accessors the tests use.

    The tests were written against a pixmap object with ``width``, ``height``
    and ``pixel(x, y)``, and they are the most valuable tests in the suite —
    they assert where ink actually lands. Wrapping the new renderer to keep
    that shape means the assertions did not have to be rewritten along with
    the engine, so they still mean what they meant before.
    """

    def __init__(self, image) -> None:
        self._image = image
        self._pixels = image.load()
        self.width, self.height = image.size

    def pixel(self, x: int, y: int) -> tuple[int, int, int]:
        return tuple(self._pixels[x, y])[:3]


def find_color_bbox(pixmap, predicate) -> tuple[int, int, int, int] | None:
    """Bounding box of pixels satisfying *predicate*, or ``None``."""
    xs: list[int] = []
    ys: list[int] = []
    for y in range(pixmap.height):
        for x in range(pixmap.width):
            if predicate(pixmap.pixel(x, y)):
                xs.append(x)
                ys.append(y)
    if not xs:
        return None
    return (min(xs), min(ys), max(xs), max(ys))


def is_red(px) -> bool:
    return px[0] > 180 and px[1] < 90 and px[2] < 90


#: Held for the lifetime of the process.  A QApplication that is destroyed
#: while Python is tearing down takes the interpreter with it, so this one is
#: deliberately never released — exactly as a real Qt program leaves it alive
#: until the process exits.
_QAPP = None


@pytest.fixture(scope="session")
def qapp():
    """A single offscreen QApplication for the whole GUI test session."""
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    global _QAPP
    if _QAPP is None:
        _QAPP = QApplication.instance() or QApplication([])
        _QAPP.setStyle("Fusion")
    return _QAPP


@pytest.fixture
def window(qapp, _isolated_home):
    """A real MainWindow, closed cleanly after each test."""
    from orion.services.settings import Settings
    from orion.ui.main_window import MainWindow

    settings = Settings(_isolated_home / "settings.json")
    win = MainWindow(settings)
    win.resize(1100, 760)
    # Shown so Qt actually paints: page rasterisation is driven from paint().
    win.show()
    qapp.processEvents()
    yield win
    win._autosave_timer.stop()
    win._detach_session()
    win.close()  # closeEvent releases the system clipboard, as on a real quit
    qapp.processEvents()
    # Free the C++ object now.  deleteLater only queues a DeferredDelete event,
    # which processEvents does not reliably deliver; a widget that survives to
    # interpreter shutdown is destroyed after Qt has gone, which segfaults.
    import shiboken6

    if shiboken6.isValid(win):
        shiboken6.delete(win)
    qapp.processEvents()


def pump(qapp, times: int = 20) -> None:
    """Let queued Qt events (including finished renders) run."""
    for _ in range(times):
        qapp.processEvents()


def wait_until(qapp, predicate, timeout: float = 10.0) -> bool:
    """Pump Qt events until *predicate* holds, or *timeout* seconds pass.

    Counting processEvents iterations is not a wait: they return immediately,
    so a fixed count can elapse in microseconds while a worker thread has not
    even started.  On a slow CI runner that reads as a failure.  This waits on
    the clock instead.
    """
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        qapp.processEvents()
        time.sleep(0.01)
    return predicate()


# ---------------------------------------------------------------------------
# Reading a written file back
# ---------------------------------------------------------------------------
class PdfProbe:
    """What a reader that is *not* Orion's writer sees in a written file.

    The point of a read-back assertion is that some other program can make
    sense of the output — that a highlight really is a `/Highlight` and the
    stamped text really is text. Asserting that through the same code that
    produced the file proves nothing, so this deliberately goes through the
    rendering engine and the parser rather than through the writer.
    """

    def __init__(self, source) -> None:
        import pypdfium2 as pdfium
        from pypdf import PdfReader

        if isinstance(source, (bytes, bytearray)):
            self._document = pdfium.PdfDocument(bytes(source))
            self._reader = PdfReader(io.BytesIO(bytes(source)))
        else:
            self._document = pdfium.PdfDocument(str(source))
            self._reader = PdfReader(str(source))

    # -- lifecycle
    def __enter__(self) -> PdfProbe:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        with suppress(Exception):
            self._document.close()

    # -- geometry
    @property
    def page_count(self) -> int:
        return len(self._document)

    def size(self, index: int = 0) -> tuple[float, float]:
        """The page as displayed, so a quarter turn reports its axes swapped."""
        return tuple(self._document[index].get_size())

    def rotation(self, index: int = 0) -> int:
        return int(self._document[index].get_rotation())

    # -- content
    def text(self, index: int = 0) -> str:
        return self._document[index].get_textpage().get_text_range()

    def find(self, needle: str, index: int = 0) -> int:
        """How many times *needle* occurs, as a searching reader would count."""
        textpage = self._document[index].get_textpage()
        searcher = textpage.search(needle)
        count = 0
        while searcher.get_next() is not None:
            count += 1
        return count

    def search_rects(self, needle: str, index: int = 0) -> list[tuple[float, float, float, float]]:
        """Hit rectangles in top-left coordinates, as the editor thinks of them."""
        page = self._document[index]
        _width, height = page.get_size()
        textpage = page.get_textpage()
        searcher = textpage.search(needle)
        rects = []
        while True:
            found = searcher.get_next()
            if found is None:
                break
            start, count = found
            for i in range(textpage.count_rects(start, count)):
                left, bottom, right, top = textpage.get_rect(i)
                rects.append((left, height - top, right, height - bottom))
        return rects

    def has_images(self, index: int = 0) -> bool:
        """Whether the page's resources actually carry an embedded image."""
        resources = self._reader.pages[index].get("/Resources") or {}
        xobjects = (resources.get_object().get("/XObject") or {}) if resources else {}
        for entry in (xobjects.get_object() or {}).values():
            with suppress(Exception):
                if str(entry.get_object().get("/Subtype")) == "/Image":
                    return True
        return False

    def annotation_subtypes(self, index: int = 0) -> set[str]:
        page = self._reader.pages[index]
        found = set()
        for annotation in page.get("/Annots") or []:
            with suppress(Exception):
                found.add(str(annotation.get_object()["/Subtype"]).lstrip("/"))
        return found

    def render(self, index: int = 0, dpi: int = 72):
        image = (
            self._document[index]
            .render(scale=dpi / 72.0, rev_byteorder=True, draw_annots=True)
            .to_pil()
            .convert("RGB")
        )
        return _Pixmap(image)


def make_pdf(path, pages, *, rotation: int = 0):
    """Write a PDF fixture: *pages* is a list of ``(width, height, text)``."""
    from pypdf import PdfReader, PdfWriter
    from reportlab.pdfgen import canvas

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer)
    for width, height, text in pages:
        pdf.setPageSize((width, height))
        if text:
            pdf.setFont("Helvetica", 18)
            pdf.drawString(50, height - 100, text)
        pdf.showPage()
    pdf.save()

    buffer.seek(0)
    out = PdfWriter(clone_from=PdfReader(buffer))
    if rotation:
        for page in out.pages:
            page.rotate(rotation)
    with open(path, "wb") as handle:
        out.write(handle)
    return path


def make_marker_pdf(path, width=400.0, height=600.0, marker=(0.0, 0.0, 80.0, 40.0)):
    """A page with a red rectangle at *marker*, given in top-left coordinates."""
    from reportlab.pdfgen import canvas

    x0, y0, x1, y1 = marker
    pdf = canvas.Canvas(str(path), pagesize=(width, height))
    pdf.setFillColorRGB(1.0, 0.0, 0.0)
    pdf.rect(x0, height - y1, x1 - x0, y1 - y0, stroke=0, fill=1)
    pdf.showPage()
    pdf.save()
    return path


def make_encrypted_pdf(path, password: str, width=200.0, height=200.0):
    """A password-protected fixture, encrypted with RC4.

    RC4 rather than AES because pypdf needs the ``cryptography`` package to
    write AES, and Orion only ever *reads* encrypted files — adding a
    dependency so that a test fixture can be encrypted more strongly than the
    test needs would be paying for it in every install. pdfium reports the same
    password error either way, which is the whole of what is being tested.
    """
    from pypdf import PdfWriter

    out = PdfWriter()
    out.add_blank_page(width, height)
    out.encrypt(password, algorithm="RC4-128")
    with open(path, "wb") as handle:
        out.write(handle)
    return path
