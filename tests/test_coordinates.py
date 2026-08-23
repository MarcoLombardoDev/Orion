#!/usr/bin/env python
# Orion — PDF Editor for Desktop
# Copyright (C) 2026 Marco Lombardo
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# Distributed WITHOUT ANY WARRANTY; see LICENSE for the full terms.
# A commercial licence, without the AGPL's obligations, is available for use
# in proprietary or closed-source products — see COMMERCIAL-LICENSE.md.

"""Regression tests for the coordinate system (spec §28).

These deliberately *render* the written PDF and assert where pixels land. A
coordinate bug is invisible in a unit test that checks one conversion against
another — both can be wrong in the same direction — and completely obvious the
moment something is drawn in the wrong corner of a page.

They are also the tests that survived the engine change unaltered, which is
the point of writing them this way: the assertions are about where ink ends up
on a page, which is a property of the product, not of whichever library put it
there.
"""

from __future__ import annotations

import io

import pytest
from reportlab.pdfgen import canvas as rl_canvas

from orion.document.document import Document, DocumentSource
from orion.document.objects import ShapeKind, ShapeObject, TextObject
from orion.document.page import Page, PageSource
from orion.pdf import writer
from orion.pdf.coordinates import (
    PageGeometry,
    content_angle,
    from_pdf_point,
    from_pdf_rect,
    to_pdf_point,
    to_pdf_rect,
)
from orion.utils.geometry import Point, Rect, Size, rotated_bounds
from tests.conftest import find_color_bbox, is_red, render_page

MARKER = Rect.from_xywh(10.0, 10.0, 100.0, 50.0)
#: Kept clear of the page edges so a rotated bounding box is never clipped.
CENTRED_MARKER = Rect.from_xywh(120.0, 150.0, 100.0, 50.0)

SOURCE_WIDTH, SOURCE_HEIGHT = 400.0, 600.0


def _rotated_source(tmp_path, rotation: int):
    """An empty page carrying ``/Rotate rotation``."""
    from pypdf import PdfWriter

    path = tmp_path / f"rot{rotation}.pdf"
    out = PdfWriter()
    out.add_blank_page(SOURCE_WIDTH, SOURCE_HEIGHT)
    if rotation:
        out.pages[0].rotate(rotation)
    with open(path, "wb") as handle:
        out.write(handle)
    return path


def _display_size(rotation: int) -> Size:
    if rotation % 180:
        return Size(SOURCE_HEIGHT, SOURCE_WIDTH)
    return Size(SOURCE_WIDTH, SOURCE_HEIGHT)


def _document_with(tmp_path, rotation: int, obj) -> Document:
    path = _rotated_source(tmp_path, rotation)
    source = DocumentSource.for_path(path)
    page = Page(
        base_size=_display_size(rotation),
        source=PageSource(source.key, 0),
        source_rotation=rotation,
    )
    page.add_object(obj)
    return Document(pages=[page], sources=[source], path=path)


def _marker(angle: float = 0.0, rect: Rect = MARKER) -> ShapeObject:
    return ShapeObject(
        rect=rect,
        shape=ShapeKind.RECTANGLE,
        stroke_color=(1.0, 0.0, 0.0),
        fill_color=(1.0, 0.0, 0.0),
        rotation=angle,
    )


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_object_lands_where_the_user_placed_it(tmp_path, rotation):
    """An object at base-space (10,10) must render at (10,10) of the page."""
    document = _document_with(tmp_path, rotation, _marker())
    out = tmp_path / f"out{rotation}.pdf"
    writer.save_document(document, out)

    pixmap = render_page(out, dpi=72)
    bbox = find_color_bbox(pixmap, is_red)
    assert bbox is not None, "the marker was not rendered at all"
    x0, y0, x1, y1 = bbox
    assert x0 == pytest.approx(MARKER.x0, abs=2)
    assert y0 == pytest.approx(MARKER.y0, abs=2)
    assert x1 == pytest.approx(MARKER.x1, abs=2)
    assert y1 == pytest.approx(MARKER.y1, abs=2)


@pytest.mark.parametrize("page_rotation", [0, 90, 180, 270])
@pytest.mark.parametrize("angle", [30.0, 90.0])
def test_object_rotation_matches_the_model(tmp_path, page_rotation, angle):
    """A rotated object's rendered bounds must match ``rotated_bounds``.

    Both terms of the conversion are exercised here: the object turns by its
    own angle, on a page that is itself turned. Applying the page rotation to
    the object as well — the easy mistake — passes at ``page_rotation=0`` and
    fails every other row.
    """
    document = _document_with(
        tmp_path, page_rotation, _marker(angle=angle, rect=CENTRED_MARKER)
    )
    out = tmp_path / f"rot-obj-{page_rotation}-{angle}.pdf"
    writer.save_document(document, out)

    pixmap = render_page(out, dpi=72)
    bbox = find_color_bbox(pixmap, is_red)
    assert bbox is not None
    expected = rotated_bounds(CENTRED_MARKER, angle)
    assert bbox[0] == pytest.approx(expected.x0, abs=3)
    assert bbox[1] == pytest.approx(expected.y0, abs=3)
    assert bbox[2] == pytest.approx(expected.x1, abs=3)
    assert bbox[3] == pytest.approx(expected.y1, abs=3)


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_text_stays_upright_on_a_rotated_page(tmp_path, rotation):
    """Text the user typed horizontally must be saved horizontally.

    This is a regression test for a real bug, found while porting the writer.
    The engine that came before wrote text into content space without turning
    it to match the page's own ``/Rotate``, so a text box on a page carrying
    ``/Rotate 90`` was drawn horizontally in the *unrotated* mediabox — which
    the reader then turned, and the user saw their sentence running down the
    page. It reproduced on 90, 180 and 270, and not on 0, which is why nothing
    caught it: an upright page is the only one anybody tests by hand.

    Rendering the saved file gives the shape of the ink, and a line of text is
    much wider than it is tall unless something has turned it.
    """
    document = _document_with(
        tmp_path,
        rotation,
        TextObject(
            rect=Rect.from_xywh(40.0, 150.0, 220.0, 60.0),
            text="Hello Orion",
            font_size=24.0,
            color=(1.0, 0.0, 0.0),
        ),
    )
    out = tmp_path / f"text{rotation}.pdf"
    writer.save_document(document, out)

    bbox = find_color_bbox(render_page(out, dpi=72), is_red)
    assert bbox is not None, "the text was not rendered at all"
    width = bbox[2] - bbox[0]
    height = bbox[3] - bbox[1]
    assert width > height * 2, (
        f"the text is running down the page, not across it: {width}x{height}"
    )


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_rect_conversion_round_trips(rotation):
    geometry = PageGeometry(SOURCE_WIDTH, SOURCE_HEIGHT, rotation)
    content = to_pdf_rect(geometry, MARKER)
    back = from_pdf_rect(geometry, content)
    assert back.as_tuple() == pytest.approx(MARKER.as_tuple(), abs=1e-6)


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_point_conversion_round_trips(rotation):
    geometry = PageGeometry(SOURCE_WIDTH, SOURCE_HEIGHT, rotation)
    for point in (Point(0, 0), Point(37.5, 211.25), Point(*geometry.display_size.as_tuple())):
        assert from_pdf_point(geometry, to_pdf_point(geometry, point)).as_tuple() == (
            pytest.approx(point.as_tuple(), abs=1e-9)
        )


@pytest.mark.parametrize(
    "rotation, corner",
    [
        # The top-left of the *displayed* page, and where it sits in the
        # unrotated mediabox. Reading these off a rotated sheet of paper is
        # the whole derivation, and getting one wrong puts every object on
        # that page in the wrong corner.
        (0, (0.0, SOURCE_HEIGHT)),
        (90, (0.0, 0.0)),
        (180, (SOURCE_WIDTH, 0.0)),
        (270, (SOURCE_WIDTH, SOURCE_HEIGHT)),
    ],
)
def test_the_display_origin_maps_to_the_expected_corner(rotation, corner):
    geometry = PageGeometry(SOURCE_WIDTH, SOURCE_HEIGHT, rotation)
    assert to_pdf_point(geometry, Point(0.0, 0.0)) == pytest.approx(corner)


@pytest.mark.parametrize("rotation", [90, 270])
def test_a_quarter_turn_transposes_a_rectangle(rotation):
    geometry = PageGeometry(SOURCE_WIDTH, SOURCE_HEIGHT, rotation)
    x0, y0, x1, y1 = to_pdf_rect(geometry, MARKER)
    assert (x1 - x0, y1 - y0) == pytest.approx((MARKER.height, MARKER.width))


def test_pdfium_still_rotates_a_rendered_page_clockwise():
    """Guards the assumption the renderer rests on.

    Orion's rotations are clockwise-positive. If pdfium ever flipped the sign
    of ``render(rotation=...)``, every page the user rotated would come out
    turned the wrong way, and nothing else in the suite would say so.
    """
    import pypdfium2 as pdfium

    buffer = io.BytesIO()
    pdf = rl_canvas.Canvas(buffer, pagesize=(400.0, 600.0))
    pdf.setFillColorRGB(1.0, 0.0, 0.0)
    # A marker in the top-left corner as displayed.
    pdf.rect(20.0, 600.0 - 60.0, 60.0, 40.0, stroke=0, fill=1)
    pdf.showPage()
    pdf.save()

    document = pdfium.PdfDocument(buffer.getvalue())
    try:
        image = document[0].render(scale=1.0, rotation=90, rev_byteorder=True).to_pil()
    finally:
        document.close()

    pixels = image.load()
    width, height = image.size
    found = next(
        (
            (x, y)
            for y in range(0, height, 4)
            for x in range(0, width, 4)
            if is_red(pixels[x, y])
        ),
        None,
    )
    assert found is not None
    assert found[0] > width / 2, "pdfium changed: rotation is no longer clockwise"
    assert found[1] < height / 2


def test_reportlab_still_rotates_counter_clockwise():
    """Guards the other half: the writer negates Orion's angle for a reason."""
    buffer = io.BytesIO()
    pdf = rl_canvas.Canvas(buffer, pagesize=(400.0, 400.0))
    pdf.translate(200.0, 200.0)
    pdf.rotate(90.0)
    pdf.setFillColorRGB(1.0, 0.0, 0.0)
    pdf.rect(50.0, 0.0, 40.0, 20.0, stroke=0, fill=1)
    pdf.showPage()
    pdf.save()

    import pypdfium2 as pdfium

    document = pdfium.PdfDocument(buffer.getvalue())
    try:
        image = document[0].render(scale=1.0, rev_byteorder=True).to_pil()
    finally:
        document.close()
    pixels = image.load()
    found = next(
        (
            (x, y)
            for y in range(0, image.size[1], 2)
            for x in range(0, image.size[0], 2)
            if is_red(pixels[x, y])
        ),
        None,
    )
    assert found is not None
    # +x rotated by +90 in PDF space points up, which on screen is upwards:
    # counter-clockwise. If this ever renders below the centre, every rotated
    # object in every saved file is mirrored.
    assert found[1] < 200, "reportlab changed: canvas.rotate is no longer counter-clockwise"


def test_content_angle_carries_both_terms():
    """The object's own angle is negated; the page's is added."""
    assert content_angle(30.0, 0) == -30.0
    assert content_angle(0.0, 90) == 90.0
    assert content_angle(30.0, 90) == 60.0
    assert content_angle(0.0, 0) == 0.0


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
