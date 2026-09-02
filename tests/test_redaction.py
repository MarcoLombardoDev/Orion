#!/usr/bin/env python
# Orion — PDF Editor for Desktop
# Copyright (C) 2026 Marco Lombardo
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# Distributed WITHOUT ANY WARRANTY; see LICENSE for the full terms.
# A commercial licence, without the AGPL's obligations, is available for use
# in proprietary or closed-source products — see COMMERCIAL-LICENSE.md.

"""Redaction: the content under the box has to be gone, not covered.

Every test here asks the saved file what text it still contains, because that
is the only question that matters and the only one a black rectangle cannot
answer. A redaction that merely paints over a name leaves it selectable,
searchable and one copy-and-paste from whoever was not meant to read it — and
looks completely correct on screen, which is what makes it worth testing this
way rather than by rendering.
"""

from __future__ import annotations

import pypdfium2 as pdfium
import pytest
from pypdf import PdfWriter as PyPdfWriter
from reportlab.pdfgen import canvas as rl_canvas

from orion.document.document import Document, DocumentSource
from orion.document.objects import RedactionObject, ShapeKind, ShapeObject, TextObject
from orion.document.page import Page, PageSource
from orion.pdf import writer as pdf_writer
from orion.utils.geometry import Rect, Size

PAGE_SIZE = (400.0, 300.0)
#: ``(y from the bottom, text)`` — the fixture, in reportlab's coordinates.
LINES = (
    (240.0, "Public heading"),
    (200.0, "Name: Mario Rossi"),
    (160.0, "Tax code: RSSMRA80A01H501U"),
    (120.0, "This line stays"),
)


def _source(tmp_path, name: str = "src.pdf"):
    path = tmp_path / name
    pdf = rl_canvas.Canvas(str(path), pagesize=PAGE_SIZE)
    pdf.setFont("Helvetica", 14)
    for y, text in LINES:
        pdf.drawString(40.0, y, text)
    pdf.showPage()
    pdf.save()
    return path


def _document(tmp_path, *objects, name: str = "src.pdf"):
    source = DocumentSource.for_path(_source(tmp_path, name))
    page = Page(base_size=Size(*PAGE_SIZE), source=PageSource(source.key, 0))
    for obj in objects:
        page.add_object(obj)
    return Document(pages=[page], sources=[source], path=source.path)


def _saved_text(document, tmp_path, name: str = "out.pdf") -> str:
    out = tmp_path / name
    pdf_writer.save_document(document, out)
    pdf = pdfium.PdfDocument(str(out))
    try:
        return pdf[0].get_textpage().get_text_range()
    finally:
        pdf.close()


#: Base page space, y downwards: the "Name:" baseline sits 100pt from the top.
NAME_LINE = Rect.from_xywh(38.0, 88.0, 200.0, 16.0)


def test_the_redacted_text_is_gone_from_the_file(tmp_path):
    """The whole point. A box over the name is not a redaction."""
    document = _document(tmp_path, RedactionObject(rect=NAME_LINE))
    text = _saved_text(document, tmp_path)
    assert "Mario Rossi" not in text
    assert "Name" not in text


def test_everything_else_survives(tmp_path):
    """Over-removal is safe; removing the whole page is not."""
    document = _document(tmp_path, RedactionObject(rect=NAME_LINE))
    text = _saved_text(document, tmp_path)
    assert "Public heading" in text
    assert "RSSMRA80A01H501U" in text
    assert "This line stays" in text


def test_the_box_is_painted_where_the_content_was(tmp_path):
    """A hole in a page reads as damage; a solid block reads as a decision."""
    document = _document(tmp_path, RedactionObject(rect=NAME_LINE))
    out = tmp_path / "painted.pdf"
    pdf_writer.save_document(document, out)

    pdf = pdfium.PdfDocument(str(out))
    try:
        image = pdf[0].render(scale=1, rev_byteorder=True).to_pil().convert("L")
    finally:
        pdf.close()
    pixels = image.load()
    dark = sum(
        1
        for y in range(int(NAME_LINE.y0) + 2, int(NAME_LINE.y1) - 2)
        for x in range(int(NAME_LINE.x0) + 2, int(NAME_LINE.x1) - 2)
        if pixels[x, y] < 60
    )
    area = (NAME_LINE.height - 4) * (NAME_LINE.width - 4)
    assert dark > area * 0.9, "the redacted area is not filled"


def test_a_white_redaction_removes_without_announcing_it(tmp_path):
    document = _document(
        tmp_path, RedactionObject(rect=NAME_LINE, fill_color=(1.0, 1.0, 1.0))
    )
    out = tmp_path / "white.pdf"
    pdf_writer.save_document(document, out)

    pdf = pdfium.PdfDocument(str(out))
    try:
        text = pdf[0].get_textpage().get_text_range()
        image = pdf[0].render(scale=1, rev_byteorder=True).to_pil().convert("L")
    finally:
        pdf.close()
    assert "Mario Rossi" not in text
    pixels = image.load()
    assert pixels[int(NAME_LINE.x0) + 20, int(NAME_LINE.y0) + 8] > 200


def test_a_run_the_box_only_clips_goes_too(tmp_path):
    """"Touches" rather than "contains", and the reason is the failure mode.

    Keeping a run that crosses the edge would leave its covered words in the
    file with a rectangle painted over them — invisible, and exactly what this
    feature exists to prevent. Over-removal is visible and undoable instead.
    """
    clipping = Rect.from_xywh(38.0, 88.0, 40.0, 16.0)  # only over "Name:"
    document = _document(tmp_path, RedactionObject(rect=clipping))
    text = _saved_text(document, tmp_path)
    assert "Mario Rossi" not in text, "part of a clipped run survived"


def test_a_redaction_that_covers_nothing_changes_nothing(tmp_path):
    document = _document(
        tmp_path, RedactionObject(rect=Rect.from_xywh(300.0, 250.0, 60.0, 20.0))
    )
    text = _saved_text(document, tmp_path)
    for _y, line in LINES:
        assert line in text


def test_several_redactions_on_one_page(tmp_path):
    document = _document(
        tmp_path,
        RedactionObject(rect=NAME_LINE),
        RedactionObject(rect=Rect.from_xywh(38.0, 128.0, 220.0, 16.0)),
    )
    text = _saved_text(document, tmp_path)
    assert "Mario Rossi" not in text
    assert "RSSMRA80A01H501U" not in text
    assert "Public heading" in text


def test_it_removes_an_image_as_readily_as_text(tmp_path):
    """Anything drawn is content: a scanned signature is the obvious case."""
    from PIL import Image

    picture = tmp_path / "mark.png"
    Image.new("RGB", (40, 20), (200, 30, 30)).save(picture)

    path = tmp_path / "with-image.pdf"
    pdf = rl_canvas.Canvas(str(path), pagesize=PAGE_SIZE)
    pdf.drawImage(str(picture), 60.0, 60.0, width=80.0, height=40.0)
    pdf.showPage()
    pdf.save()

    source = DocumentSource.for_path(path)
    page = Page(base_size=Size(*PAGE_SIZE), source=PageSource(source.key, 0))
    page.add_object(RedactionObject(rect=Rect.from_xywh(55.0, 195.0, 90.0, 50.0)))
    document = Document(pages=[page], sources=[source], path=path)

    out = tmp_path / "no-image.pdf"
    pdf_writer.save_document(document, out)
    reopened = pdfium.PdfDocument(str(out))
    try:
        image = reopened[0].render(scale=1, rev_byteorder=True).to_pil().convert("RGB")
    finally:
        reopened.close()
    pixels = image.load()
    assert not [
        1
        for y in range(200, 240)
        for x in range(60, 140)
        if pixels[x, y][0] > 150 and pixels[x, y][1] < 100
    ], "the image is still there under the box"


def test_the_redaction_object_round_trips(tmp_path):
    """Autosave and the session file have to carry it, like anything else."""
    restored = Document.from_dict(
        _document(tmp_path, RedactionObject(rect=NAME_LINE)).to_dict()
    )
    obj = restored[0].objects[0]
    assert isinstance(obj, RedactionObject)
    assert obj.rect.as_tuple() == pytest.approx(NAME_LINE.as_tuple())


def test_moving_the_box_moves_what_it_removes(tmp_path):
    """What a redaction covers is resolved at save time, not when it is drawn.

    A box dragged onto a different line has to take that line instead, which
    is only true if the content it covers is worked out from where it ends up.
    """
    redaction = RedactionObject(rect=NAME_LINE)
    document = _document(tmp_path, redaction)
    redaction.rect = Rect.from_xywh(38.0, 128.0, 220.0, 16.0)  # the tax code line
    text = _saved_text(document, tmp_path)
    assert "Mario Rossi" in text, "it removed where the box started"
    assert "RSSMRA80A01H501U" not in text, "it did not remove where the box is"


def test_it_leaves_orion_objects_alone(tmp_path):
    """A redaction removes the *page's* content, not the user's own overlay.

    Those are drawn after the removal pass, so a box over one must not eat it
    — and, since the overlay is stamped on top, a shape under a redaction is
    covered rather than deleted.
    """
    document = _document(
        tmp_path,
        ShapeObject(
            rect=Rect.from_xywh(250.0, 40.0, 80.0, 40.0),
            shape=ShapeKind.RECTANGLE,
            stroke_color=(0.0, 0.6, 0.0),
        ),
        RedactionObject(rect=NAME_LINE),
        TextObject(
            rect=Rect.from_xywh(250.0, 200.0, 120.0, 30.0),
            text="added by me",
            font_size=11.0,
        ),
    )
    text = _saved_text(document, tmp_path)
    assert "Mario Rossi" not in text
    assert "added by me" in text, "the user's own text was removed"


def test_a_blank_page_is_survived(tmp_path):
    """There is no source content to walk, and that must not be an error."""
    blank = tmp_path / "blank.pdf"
    out = PyPdfWriter()
    out.add_blank_page(*PAGE_SIZE)
    with open(blank, "wb") as handle:
        out.write(handle)

    source = DocumentSource.for_path(blank)
    page = Page(base_size=Size(*PAGE_SIZE), source=PageSource(source.key, 0))
    page.add_object(RedactionObject(rect=NAME_LINE))
    document = Document(pages=[page], sources=[source], path=blank)
    assert _saved_text(document, tmp_path, "blank-out.pdf").strip() == ""
