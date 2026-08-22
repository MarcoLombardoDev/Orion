"""Regression tests for the coordinate system (spec §28).

These deliberately *render* the written PDF and assert where pixels land, so a
behaviour change in PyMuPDF's rotation handling fails loudly here instead of
silently misplacing every object in the application.
"""

from __future__ import annotations

import pymupdf
import pytest

from orion.document.document import Document, DocumentSource
from orion.document.objects import ShapeKind, ShapeObject
from orion.document.page import Page, PageSource
from orion.pdf import writer
from orion.pdf.coordinates import content_angle, from_pdf_rect, pdf_morph_angle, to_pdf_rect
from orion.utils.geometry import Point, Rect, Size, rotate_point, rotated_bounds
from tests.conftest import find_color_bbox, is_red

MARKER = Rect.from_xywh(10.0, 10.0, 100.0, 50.0)
#: Kept clear of the page edges so a rotated bounding box is never clipped.
CENTRED_MARKER = Rect.from_xywh(120.0, 150.0, 100.0, 50.0)


def _rotated_source(tmp_path, rotation: int):
    path = tmp_path / f"rot{rotation}.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=400, height=600)
    if rotation:
        page.set_rotation(rotation)
    doc.save(path)
    doc.close()
    return path


def _document_with_marker(
    path, rotation: int, *, angle: float = 0.0, marker: Rect = MARKER
) -> Document:
    with pymupdf.open(path) as src:
        rect = src.load_page(0).rect
        source_rotation = int(src.load_page(0).rotation)
    source = DocumentSource.for_path(path)
    page = Page(
        base_size=Size(rect.width, rect.height),
        source=PageSource(source.key, 0),
        source_rotation=source_rotation,
    )
    page.add_object(
        ShapeObject(
            rect=marker,
            shape=ShapeKind.RECTANGLE,
            stroke_color=(1.0, 0.0, 0.0),
            fill_color=(1.0, 0.0, 0.0),
            rotation=angle,
        )
    )
    return Document(pages=[page], sources=[source], path=path)


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_object_lands_where_the_user_placed_it(tmp_path, rotation):
    """An object at base-space (10,10) must render at (10,10) of the page."""
    source = _rotated_source(tmp_path, rotation)
    document = _document_with_marker(source, rotation)
    out = tmp_path / f"out{rotation}.pdf"
    writer.save_document(document, out)

    with pymupdf.open(out) as doc:
        page = doc.load_page(0)
        assert page.rotation == rotation
        pixmap = page.get_pixmap(dpi=72)

    bbox = find_color_bbox(pixmap, is_red)
    assert bbox is not None, "the marker was not rendered at all"
    x0, y0, x1, y1 = bbox
    assert x0 == pytest.approx(MARKER.x0, abs=2)
    assert y0 == pytest.approx(MARKER.y0, abs=2)
    assert x1 == pytest.approx(MARKER.x1, abs=2)
    assert y1 == pytest.approx(MARKER.y1, abs=2)


@pytest.mark.parametrize("page_rotation", [0, 90])
@pytest.mark.parametrize("angle", [30.0, 90.0])
def test_object_rotation_matches_the_model(tmp_path, page_rotation, angle):
    """A rotated object's rendered bounds must match ``rotated_bounds``."""
    source = _rotated_source(tmp_path, page_rotation)
    document = _document_with_marker(
        source, page_rotation, angle=angle, marker=CENTRED_MARKER
    )
    out = tmp_path / f"rot-obj-{page_rotation}-{angle}.pdf"
    writer.save_document(document, out)

    with pymupdf.open(out) as doc:
        pixmap = doc.load_page(0).get_pixmap(dpi=72)

    bbox = find_color_bbox(pixmap, is_red)
    assert bbox is not None
    expected = rotated_bounds(CENTRED_MARKER, angle)
    assert bbox[0] == pytest.approx(expected.x0, abs=3)
    assert bbox[1] == pytest.approx(expected.y0, abs=3)
    assert bbox[2] == pytest.approx(expected.x1, abs=3)
    assert bbox[3] == pytest.approx(expected.y1, abs=3)


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_rect_conversion_round_trips(tmp_path, rotation):
    source = _rotated_source(tmp_path, rotation)
    with pymupdf.open(source) as doc:
        page = doc.load_page(0)
        content = to_pdf_rect(page, MARKER)
        back = from_pdf_rect(page, content)
    assert back.as_tuple() == pytest.approx(MARKER.as_tuple(), abs=1e-6)


def test_pymupdf_matrix_still_rotates_counter_clockwise():
    """Guards assumption #2 in ``orion/pdf/coordinates.py``."""
    doc = pymupdf.open()
    page = doc.new_page(width=400, height=400)
    centre = pymupdf.Point(200, 200)
    page.draw_rect(
        pymupdf.Rect(100, 100, 140, 140),
        color=(1, 0, 0),
        fill=(1, 0, 0),
        morph=(centre, pymupdf.Matrix(pdf_morph_angle(90.0))),
    )
    pixmap = page.get_pixmap(dpi=72)
    doc.close()
    bbox = find_color_bbox(pixmap, is_red)
    assert bbox is not None
    # Orion angle +90 is clockwise: the up-left marker must move to up-right.
    expected = rotate_point(Point(120, 120), Point(200, 200), 90.0)
    cx = (bbox[0] + bbox[2]) / 2.0
    cy = (bbox[1] + bbox[3]) / 2.0
    assert cx == pytest.approx(expected.x, abs=3)
    assert cy == pytest.approx(expected.y, abs=3)


def test_pymupdf_content_api_ignores_page_rotation():
    """Guards assumption #1: ``draw_rect`` uses unrotated mediabox space."""
    doc = pymupdf.open()
    page = doc.new_page(width=400, height=600)
    page.set_rotation(90)
    page.draw_rect(pymupdf.Rect(10, 10, 110, 60), color=(1, 0, 0), fill=(1, 0, 0))
    pixmap = page.get_pixmap(dpi=72)
    doc.close()
    bbox = find_color_bbox(pixmap, is_red)
    assert bbox is not None
    # If PyMuPDF became rotation-aware the marker would sit at the top-left.
    assert bbox[0] > 400, "PyMuPDF changed: it now honours /Rotate in draw_rect"


def test_content_angle_and_morph_angle_are_consistent():
    assert content_angle(30.0, 0) == 30.0
    assert content_angle(30.0, 90) == -60.0
    # No page-rotation term: to_pdf_rect already carries it (see the docstring).
    assert pdf_morph_angle(30.0) == -30.0
    assert pdf_morph_angle(0.0) == 0.0


def test_page_display_mapping_is_invertible():
    page = Page(base_size=Size(400.0, 600.0))
    for rotation in (0, 90, 180, 270):
        page.rotation = rotation
        for point in (Point(0, 0), Point(400, 600), Point(37.5, 211.25)):
            mapped = page.base_to_display(point)
            assert page.display_to_base(mapped).as_tuple() == pytest.approx(point.as_tuple())
        size = page.display_size
        assert size.as_tuple() == pytest.approx(
            (600.0, 400.0) if rotation % 180 else (400.0, 600.0)
        )
