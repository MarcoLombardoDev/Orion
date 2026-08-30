#!/usr/bin/env python
# Orion — PDF Editor for Desktop
# Copyright (C) 2026 Marco Lombardo
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# Distributed WITHOUT ANY WARRANTY; see LICENSE for the full terms.
# A commercial licence, without the AGPL's obligations, is available for use
# in proprietary or closed-source products — see COMMERCIAL-LICENSE.md.

"""Reading a PDF's own annotations back into the model, and writing them out.

The bug these were written for: an annotation was editable only until the file
was closed. Orion wrote it correctly, every other reader showed it, and
reopening the document turned it into scenery — drawn by pdfium, backed by
nothing the user could click. So the tests that matter here are the round
trips, not the conversions: mark up, save, reopen, and the highlight must
still be an object; delete it, save, and it must be gone from the file.
"""

from __future__ import annotations

import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import (
    ArrayObject,
    DictionaryObject,
    FloatObject,
    NameObject,
    NumberObject,
    TextStringObject,
)

from orion.document.annotations import AnnotationKind, AnnotationObject
from orion.document.document import Document
from orion.pdf import reader as pdf_reader
from orion.pdf import writer as pdf_writer
from orion.pdf.annotation_import import import_annotations
from orion.pdf.coordinates import PageGeometry
from orion.utils.geometry import Point, Rect

PAGE_WIDTH, PAGE_HEIGHT = 400.0, 600.0


def _annotation(subtype: str, **entries) -> DictionaryObject:
    entry = DictionaryObject()
    entry[NameObject("/Type")] = NameObject("/Annot")
    entry[NameObject("/Subtype")] = NameObject(subtype)
    for key, value in entries.items():
        entry[NameObject(f"/{key}")] = value
    return entry


def _floats(values) -> ArrayObject:
    return ArrayObject([FloatObject(float(v)) for v in values])


def _link(x0=50.0, y0=300.0, x1=150.0, y1=320.0) -> DictionaryObject:
    """A URI link — something Orion has no business importing or deleting."""
    action = DictionaryObject()
    action[NameObject("/S")] = NameObject("/URI")
    action[NameObject("/URI")] = TextStringObject("https://example.invalid/")
    return _annotation("/Link", Rect=_floats([x0, y0, x1, y1]), A=action)


def _source_with(tmp_path, *annotations, rotation: int = 0, name: str = "src.pdf"):
    """A one-page PDF carrying *annotations*, in file order."""
    out = PdfWriter()
    out.add_blank_page(PAGE_WIDTH, PAGE_HEIGHT)
    if rotation:
        out.pages[0][NameObject("/Rotate")] = NumberObject(rotation)
    for entry in annotations:
        out.add_annotation(0, entry)
    path = tmp_path / name
    with open(path, "wb") as handle:
        out.write(handle)
    return path


def _highlight(x0=50.0, y0=500.0, x1=200.0, y1=520.0) -> DictionaryObject:
    """A highlight over one line, written the way the specification says."""
    return _annotation(
        "/Highlight",
        QuadPoints=_floats([x0, y1, x1, y1, x0, y0, x1, y0]),
        Rect=_floats([x0, y0, x1, y1]),
        C=_floats([1.0, 0.9, 0.2]),
        Contents=TextStringObject("from another editor"),
        T=TextStringObject("Someone Else"),
    )


def _open(path):
    document, opened = pdf_reader.load_document(path)
    opened.close()
    return document


# -- importing -----------------------------------------------------------
def test_a_highlight_becomes_an_editable_object(tmp_path):
    document = _open(_source_with(tmp_path, _highlight()))
    objects = document[0].objects
    assert len(objects) == 1
    obj = objects[0]
    assert isinstance(obj, AnnotationObject)
    assert obj.annotation is AnnotationKind.HIGHLIGHT
    assert obj.contents == "from another editor"
    assert obj.author == "Someone Else"
    assert obj.color == pytest.approx((1.0, 0.9, 0.2))
    # Base page space: y measured down from the top of the displayed page.
    assert obj.quads[0].as_tuple() == pytest.approx((50.0, 80.0, 200.0, 100.0))
    assert document[0].imported_annotations == (0,)


@pytest.mark.parametrize(
    "subtype, expected",
    [
        ("/Highlight", AnnotationKind.HIGHLIGHT),
        ("/Underline", AnnotationKind.UNDERLINE),
        ("/StrikeOut", AnnotationKind.STRIKEOUT),
    ],
)
def test_every_markup_kind_is_imported(tmp_path, subtype, expected):
    entry = _highlight()
    entry[NameObject("/Subtype")] = NameObject(subtype)
    document = _open(_source_with(tmp_path, entry, name=f"{expected.value}.pdf"))
    assert document[0].objects[0].annotation is expected


def test_ink_keeps_its_strokes_and_width(tmp_path):
    entry = _annotation(
        "/Ink",
        InkList=ArrayObject([_floats([40.0, 560.0, 60.0, 540.0, 90.0, 560.0])]),
        Rect=_floats([38.0, 538.0, 92.0, 562.0]),
        C=_floats([1.0, 0.0, 0.0]),
        BS=_border(3.5),
    )
    obj = _open(_source_with(tmp_path, entry))[0].objects[0]
    assert obj.annotation is AnnotationKind.INK
    assert obj.stroke_width == pytest.approx(3.5)
    assert [p.as_tuple() for p in obj.strokes[0]] == pytest.approx(
        [(40.0, 40.0), (60.0, 60.0), (90.0, 40.0)]
    )


def _border(width: float) -> DictionaryObject:
    border = DictionaryObject()
    border[NameObject("/W")] = FloatObject(width)
    return border


def test_a_sticky_note_is_told_apart_from_a_comment(tmp_path):
    note = _annotation(
        "/Text", Rect=_floats([100.0, 400.0, 120.0, 420.0]), Name=NameObject("/Note")
    )
    comment = _annotation(
        "/Text", Rect=_floats([200.0, 400.0, 220.0, 420.0]), Name=NameObject("/Comment")
    )
    kinds = [o.annotation for o in _open(_source_with(tmp_path, note, comment))[0].objects]
    assert kinds == [AnnotationKind.STICKY_NOTE, AnnotationKind.COMMENT]


def test_unowned_annotations_are_left_alone(tmp_path):
    """A link is not something Orion can edit, so it must not become an object.

    Importing one would put an invisible, movable rectangle on the page, and
    — because the writer deletes what it imported — would destroy the link on
    the next save.
    """
    document = _open(_source_with(tmp_path, _link(), _highlight()))
    assert len(document[0].objects) == 1
    assert document[0].imported_annotations == (1,), "the index must be the file's"


def test_a_markup_annotation_without_quads_is_not_imported(tmp_path):
    """It has nothing to attach to, and must stay in the file untouched.

    Falling back to ``/Rect`` would paint a block of colour across a paragraph
    the user never marked, and taking ownership of it would then delete the
    original on save.
    """
    entry = _annotation("/Highlight", Rect=_floats([50.0, 500.0, 200.0, 520.0]))
    document = _open(_source_with(tmp_path, entry))
    assert document[0].objects == []
    assert document[0].imported_annotations == ()


def test_a_damaged_annotation_does_not_stop_the_file_opening(tmp_path):
    broken = _annotation("/Highlight", QuadPoints=TextStringObject("not an array"))
    document = _open(_source_with(tmp_path, broken, _highlight()))
    assert len(document[0].objects) == 1, "the readable highlight must still arrive"


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_the_import_undoes_what_the_writer_did(tmp_path, rotation):
    """Round trip through the coordinate conversion, on every page rotation.

    Writing and reading are separate code paths through
    :mod:`orion.pdf.coordinates`, and a sign error in one of them is invisible
    until they are put back to back.
    """
    quad = Rect.from_xywh(40.0, 70.0, 150.0, 20.0)
    geometry = PageGeometry(PAGE_WIDTH, PAGE_HEIGHT, rotation)
    source = tmp_path / f"rot{rotation}.pdf"
    out = PdfWriter()
    out.add_blank_page(PAGE_WIDTH, PAGE_HEIGHT)
    if rotation:
        out.pages[0][NameObject("/Rotate")] = NumberObject(rotation)
    with open(source, "wb") as handle:
        out.write(handle)

    document = _open(source)
    page = document[0]
    page.add_object(
        AnnotationObject(
            rect=quad, annotation=AnnotationKind.HIGHLIGHT, quads=[quad], color=(1.0, 0.9, 0.2)
        )
    )
    saved = tmp_path / f"saved{rotation}.pdf"
    pdf_writer.save_document(document, saved)

    reopened = _open(saved)[0].objects
    assert len(reopened) == 1
    assert reopened[0].quads[0].as_tuple() == pytest.approx(quad.as_tuple(), abs=0.01)
    assert geometry.display_size.as_tuple() == pytest.approx(page.base_size.as_tuple())


# -- writing back --------------------------------------------------------
def _subtypes(path) -> list[str]:
    annots = PdfReader(str(path)).pages[0].get("/Annots") or []
    return [str(a.get_object().get("/Subtype")) for a in annots]


def test_saving_an_untouched_import_does_not_duplicate_it(tmp_path):
    source = _source_with(tmp_path, _highlight())
    document = _open(source)
    out = tmp_path / "out.pdf"
    pdf_writer.save_document(document, out)
    assert _subtypes(out) == ["/Highlight"]
    # And it is still one object, not two, on the way back in.
    assert len(_open(out)[0].objects) == 1


def test_deleting_an_imported_annotation_removes_it_from_the_file(tmp_path):
    """The point of the whole exercise."""
    document = _open(_source_with(tmp_path, _highlight()))
    page = document[0]
    page.remove_object(page.objects[0].id)
    out = tmp_path / "out.pdf"
    pdf_writer.save_document(document, out)
    assert _subtypes(out) == []


def test_editing_an_imported_annotation_reaches_the_file(tmp_path):
    document = _open(_source_with(tmp_path, _highlight()))
    obj = document[0].objects[0]
    obj.color = (0.0, 1.0, 0.0)
    obj.contents = "edited by Orion"
    out = tmp_path / "out.pdf"
    pdf_writer.save_document(document, out)

    entry = PdfReader(str(out)).pages[0]["/Annots"][0].get_object()
    assert [float(v) for v in entry["/C"]] == pytest.approx([0.0, 1.0, 0.0])
    assert str(entry["/Contents"]) == "edited by Orion"


def test_a_link_survives_a_save_that_deletes_a_highlight(tmp_path):
    """The two halves of ownership, in one file."""
    document = _open(_source_with(tmp_path, _link(), _highlight()))
    page = document[0]
    page.remove_object(page.objects[0].id)
    out = tmp_path / "out.pdf"
    pdf_writer.save_document(document, out)
    assert _subtypes(out) == ["/Link"]


def test_repeated_round_trips_are_stable(tmp_path):
    """Open, save, open, save: one annotation, still one, five times over.

    An off-by-one in the ownership indices would show up as growth here long
    before anybody noticed it by hand.
    """
    current = _source_with(tmp_path, _highlight())
    for generation in range(5):
        document = _open(current)
        assert len(document[0].objects) == 1, f"generation {generation}"
        current = tmp_path / f"gen{generation}.pdf"
        pdf_writer.save_document(document, current)
    assert _subtypes(current) == ["/Highlight"]


def test_pypdf_preserves_annotation_order_across_a_copy(tmp_path):
    """Guards the assumption the ownership indices rest on.

    The writer deletes imported annotations from the copied page *by index*.
    If pypdf ever reordered ``/Annots`` while appending pages, that would
    delete the wrong ones — silently, and only in files that mix owned and
    unowned annotations.
    """
    source = _source_with(
        tmp_path,
        _highlight(),
        _link(0.0, 0.0, 10.0, 10.0),
        _annotation("/Underline", QuadPoints=_floats([0, 10, 10, 10, 0, 0, 10, 0])),
    )
    reader = PdfReader(str(source))
    out = PdfWriter()
    out.append(reader, pages=(0, 1))
    copied = [str(a.get_object()["/Subtype"]) for a in out.pages[0]["/Annots"]]
    assert copied == ["/Highlight", "/Link", "/Underline"]


# -- page import ---------------------------------------------------------
def test_pages_imported_from_another_file_bring_their_annotations(tmp_path):
    """Inserting somebody else's page must not flatten its markup."""
    source = _source_with(tmp_path, _highlight())
    opened = pdf_reader.open_pdf(source)
    try:
        pages = pdf_reader.build_pages(opened, "other", [0])
    finally:
        opened.close()
    assert len(pages[0].objects) == 1
    assert pages[0].imported_annotations == (0,)


def test_a_duplicated_page_keeps_its_ownership(tmp_path):
    """Both copies own the same source annotation, and neither duplicates it."""
    document = _open(_source_with(tmp_path, _highlight()))
    copy = document[0].duplicate()
    assert copy.imported_annotations == (0,)
    document.pages.append(copy)
    out = tmp_path / "twice.pdf"
    pdf_writer.save_document(document, out)
    for index in (0, 1):
        annots = PdfReader(str(out)).pages[index].get("/Annots") or []
        assert len(annots) == 1


# -- units ---------------------------------------------------------------
def test_quad_corners_are_read_as_an_extent_not_positionally(tmp_path):
    """Writers disagree about the corner order; the extent is right for all.

    The specification says upper-left, upper-right, lower-left, lower-right.
    Plenty of real files wind them like a polygon instead. Reading the four
    corners positionally gets one of the two wrong, and a highlight ends up
    somewhere else on the page.
    """
    geometry = PageGeometry(PAGE_WIDTH, PAGE_HEIGHT, 0)
    spec_order = _annotation(
        "/Highlight", QuadPoints=_floats([50, 520, 200, 520, 50, 500, 200, 500])
    )
    polygon_order = _annotation(
        "/Highlight", QuadPoints=_floats([50, 520, 200, 520, 200, 500, 50, 500])
    )

    class _Page(dict):
        mediabox = type("Box", (), {"left": 0.0, "bottom": 0.0})()

    for entry in (spec_order, polygon_order):
        page = _Page({"/Annots": [entry]})
        imported = import_annotations(page, geometry)
        assert imported.objects[0].quads[0].as_tuple() == pytest.approx(
            (50.0, 80.0, 200.0, 100.0)
        )


def test_a_cropped_mediabox_is_taken_off_the_coordinates(tmp_path):
    """A page whose mediabox does not start at the origin — a scanner crop."""
    geometry = PageGeometry(PAGE_WIDTH, PAGE_HEIGHT, 0)

    class _Page(dict):
        mediabox = type("Box", (), {"left": 20.0, "bottom": 30.0})()

    entry = _annotation(
        "/Highlight", QuadPoints=_floats([70, 530, 220, 530, 70, 530, 220, 510])
    )
    imported = import_annotations(_Page({"/Annots": [entry]}), geometry)
    # x: 70 - 20 = 50.  y: 510..530 minus 30 is 480..500 above the corner,
    # which on a 600pt page is 100..120 measured down from the top.
    assert imported.objects[0].quads[0].as_tuple() == pytest.approx((50.0, 100.0, 200.0, 120.0))


def test_a_document_with_no_annotations_costs_nothing(tmp_path, monkeypatch):
    """The pypdf parse is skipped entirely when pdfium counted none.

    Opening a large file must not get slower for a feature it never uses.
    """
    source = _source_with(tmp_path, name="plain.pdf")
    import pypdf

    opened_with_pypdf = False
    real = pypdf.PdfReader

    def spy(*args, **kwargs):
        nonlocal opened_with_pypdf
        opened_with_pypdf = True
        return real(*args, **kwargs)

    monkeypatch.setattr(pypdf, "PdfReader", spy)
    _open(source)
    assert not opened_with_pypdf


def test_an_imported_annotation_survives_being_serialised(tmp_path):
    """Autosave and the session file carry ownership too.

    Without this the recovery copy of a document would, on the next save,
    duplicate every annotation it had imported.
    """
    document = _open(_source_with(tmp_path, _highlight()))
    restored = Document.from_dict(document.to_dict())
    assert restored[0].imported_annotations == (0,)
    assert len(restored[0].objects) == 1


def test_the_document_opens_unmodified(tmp_path):
    """Importing must not make an untouched file look edited.

    Otherwise every document would ask to be saved on close, having changed
    nothing.
    """
    document = _open(_source_with(tmp_path, _highlight()))
    assert not document.modified


def test_ink_bounds_include_the_stroke_width(tmp_path):
    entry = _annotation(
        "/Ink",
        InkList=ArrayObject([_floats([100.0, 500.0, 140.0, 500.0])]),
        BS=_border(6.0),
    )
    obj = _open(_source_with(tmp_path, entry))[0].objects[0]
    assert obj.rect.width == pytest.approx(40.0 + 12.0)
    assert obj.rect.contains_point(Point(120.0, 100.0))
