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
