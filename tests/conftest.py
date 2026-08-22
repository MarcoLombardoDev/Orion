"""Shared fixtures.  The model/engine tests need no display server."""

from __future__ import annotations

import os
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
    import pymupdf

    path = tmp_path / "sample.pdf"
    doc = pymupdf.open()
    for index in range(3):
        page = doc.new_page(width=400, height=600)
        page.insert_text((50, 100), f"PAGE {index + 1} NEEDLE", fontsize=18)
    doc.save(path)
    doc.close()
    return path


@pytest.fixture
def sample_image(tmp_path: Path) -> Path:
    from PIL import Image

    path = tmp_path / "swatch.png"
    Image.new("RGB", (40, 20), (0, 128, 255)).save(path)
    return path


def render_page(path: Path, index: int = 0, dpi: int = 72):
    """Rasterise a saved PDF page for pixel assertions."""
    import pymupdf

    with pymupdf.open(path) as doc:
        return doc.load_page(index).get_pixmap(dpi=dpi)


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


@pytest.fixture(scope="session")
def qapp():
    """A single offscreen QApplication for the whole GUI test session."""
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    yield app


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
    win.deleteLater()
    qapp.processEvents()


def pump(qapp, times: int = 20) -> None:
    """Let queued Qt events (including finished renders) run."""
    for _ in range(times):
        qapp.processEvents()
