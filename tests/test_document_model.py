# Orion — PDF Editor for Desktop
# Copyright (C) 2026 Marco Lombardo
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# Distributed WITHOUT ANY WARRANTY; see LICENSE for the full terms.
# A commercial licence, without the AGPL's obligations, is available for use
# in proprietary or closed-source products — see COMMERCIAL-LICENSE.md.

"""Document model, page geometry and serialisation tests (spec §27)."""

from __future__ import annotations

import pytest

from orion.document.annotations import AnnotationKind, AnnotationObject
from orion.document.document import Document, DocumentSource
from orion.document.objects import (
    Align,
    ImageObject,
    ShapeKind,
    ShapeObject,
    TextObject,
    create_object,
)
from orion.document.page import Page
from orion.document.serialization import (
    document_from_json,
    document_to_json,
    objects_from_json,
    objects_to_json,
)
from orion.utils.geometry import Point, Rect, Size


def _populated() -> Document:
    document = Document.blank(page_count=2)
    document[0].add_object(
        TextObject(
            rect=Rect.from_xywh(10, 10, 200, 40),
            text="Hello Orion\nSecond line",
            bold=True,
            italic=True,
            underline=True,
            align=Align.CENTER,
            color=(0.1, 0.2, 0.3),
        )
    )
    document[0].add_object(
        ShapeObject(
            rect=Rect.from_xywh(50, 80, 100, 60),
            shape=ShapeKind.ARROW,
            stroke_color=(1.0, 0.0, 0.0),
            fill_color=None,
            rotation=33.0,
        )
    )
    document[1].add_object(
        AnnotationObject(
            rect=Rect.from_xywh(0, 0, 10, 10),
            annotation=AnnotationKind.INK,
            strokes=[[Point(1, 2), Point(3, 4)]],
        )
    )
    document[1].add_object(
        ImageObject(
            rect=Rect.from_xywh(20, 20, 80, 40),
            data=b"\x89PNG-not-really",
            natural_size=Size(160, 80),
        )
    )
    return document


# -- objects -------------------------------------------------------------
def test_object_clone_is_independent():
    original = AnnotationObject(
        rect=Rect.from_xywh(0, 0, 10, 10),
        annotation=AnnotationKind.INK,
        strokes=[[Point(0, 0), Point(5, 5)]],
    )
    copy = original.clone(offset=(3.0, 4.0))
    assert copy.id != original.id
    assert copy.strokes[0][0] == Point(3, 4)
    assert original.strokes[0][0] == Point(0, 0)


def test_text_base14_font_selection():
    text = TextObject()
    assert text.base14_name == "helv"
    text.bold = True
    assert text.base14_name == "hebo"
    text.italic = True
    assert text.base14_name == "hebi"
    text.font_family = "Times"
    assert text.base14_name == "tibi"


def test_image_aspect_completion():
    image = ImageObject(natural_size=Size(200, 100))
    assert image.size_for_aspect(width=50).height == pytest.approx(25.0)
    assert image.size_for_aspect(height=50).width == pytest.approx(100.0)


def test_shape_line_endpoints_follow_the_rect():
    shape = ShapeObject(rect=Rect.from_xywh(10, 20, 100, 50), shape=ShapeKind.LINE)
    assert shape.start_point() == Point(10, 20)
    assert shape.end_point() == Point(110, 70)
    shape.line_start, shape.line_end = (0.0, 1.0), (1.0, 0.0)
    assert shape.start_point() == Point(10, 70)


def test_visual_bounds_include_rotation():
    shape = ShapeObject(rect=Rect.from_xywh(0, 0, 100, 50), rotation=90.0)
    bounds = shape.visual_bounds
    assert bounds.width == pytest.approx(50.0)
    assert bounds.height == pytest.approx(100.0)


def test_create_object_rejects_unknown_kinds():
    with pytest.raises(ValueError):
        create_object({"kind": "hologram"})


# -- pages ---------------------------------------------------------------
def test_page_object_z_order_operations():
    page = Page()
    a, b, c = (ShapeObject(rect=Rect.from_xywh(i, 0, 5, 5)) for i in range(3))
    for obj in (a, b, c):
        page.add_object(obj)
    page.raise_object(a.id)
    assert [o.id for o in page] == [b.id, a.id, c.id]
    page.lower_object(c.id, to_bottom=True)
    assert [o.id for o in page] == [c.id, b.id, a.id]
    page.raise_object(c.id, to_top=True)
    assert [o.id for o in page] == [b.id, a.id, c.id]


def test_object_at_respects_rotation():
    page = Page()
    shape = ShapeObject(rect=Rect.from_xywh(0, 0, 100, 20), rotation=90.0)
    page.add_object(shape)
    # After a 90 degree turn the bar is vertical about its centre (50, 10).
    assert page.object_at(Point(50, 55)) is shape
    assert page.object_at(Point(95, 10)) is None


def test_page_duplicate_is_deep():
    page = Page()
    page.add_object(ShapeObject(rect=Rect.from_xywh(0, 0, 5, 5)))
    copy = page.duplicate()
    assert copy.id != page.id
    assert copy.objects[0].id != page.objects[0].id
    copy.objects[0].rect = Rect.from_xywh(99, 99, 5, 5)
    assert page.objects[0].rect.x0 == 0


def test_total_rotation_combines_source_and_orion_rotation():
    page = Page(source_rotation=90, rotation=270)
    assert page.total_rotation == 0
    page.rotation = 180
    assert page.total_rotation == 270


# -- document ------------------------------------------------------------
def test_document_page_operations_mark_it_modified():
    document = Document.blank(page_count=1)
    assert not document.modified
    document.append_page(Page())
    assert document.modified
    assert document.page_count == 2


def test_set_page_order_validates_the_permutation():
    document = Document.blank(page_count=3)
    assert not document.set_page_order([0, 1])
    assert document.set_page_order([2, 1, 0])


def test_prune_sources_drops_unreferenced_files():
    document = Document.blank(page_count=1)
    document.add_source(DocumentSource(key="ghost"))
    document.prune_sources()
    assert "ghost" not in document.sources


def test_locate_object_finds_the_page():
    document = _populated()
    target = document[1].objects[0]
    located = document.locate_object(target.id)
    assert located is not None and located[0] == 1


def test_modified_event_fires_once_per_transition():
    document = Document.blank(page_count=1)
    seen: list[bool] = []
    document.modified_changed.connect(seen.append)
    document.set_modified(True)
    document.set_modified(True)
    document.set_modified(False)
    assert seen == [True, False]


# -- serialisation -------------------------------------------------------
def test_document_json_round_trip_is_stable():
    document = _populated()
    once = document_to_json(document)
    twice = document_to_json(document_from_json(once))
    assert once == twice


def test_round_trip_preserves_every_property():
    document = _populated()
    restored = document_from_json(document_to_json(document))
    text = restored[0].objects[0]
    assert isinstance(text, TextObject)
    assert text.text == "Hello Orion\nSecond line"
    assert (text.bold, text.italic, text.underline) == (True, True, True)
    assert text.align is Align.CENTER
    assert text.color == pytest.approx((0.1, 0.2, 0.3))

    arrow = restored[0].objects[1]
    assert isinstance(arrow, ShapeObject) and arrow.shape is ShapeKind.ARROW
    assert arrow.rotation == pytest.approx(33.0)
    assert arrow.fill_color is None

    ink = restored[1].objects[0]
    assert isinstance(ink, AnnotationObject) and ink.strokes == [[Point(1, 2), Point(3, 4)]]

    image = restored[1].objects[1]
    assert isinstance(image, ImageObject) and image.data == b"\x89PNG-not-really"


def test_clipboard_payload_round_trip():
    objects = list(_populated()[0])
    restored = objects_from_json(objects_to_json(objects))
    assert [type(o) for o in restored] == [type(o) for o in objects]


def test_clipboard_ignores_foreign_payloads():
    assert objects_from_json("not json") == []
    assert objects_from_json('{"type": "something-else"}') == []
