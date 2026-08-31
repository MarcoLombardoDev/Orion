#!/usr/bin/env python
# Orion — PDF Editor for Desktop
# Copyright (C) 2026 Marco Lombardo
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# Distributed WITHOUT ANY WARRANTY; see LICENSE for the full terms.
# A commercial licence, without the AGPL's obligations, is available for use
# in proprietary or closed-source products — see COMMERCIAL-LICENSE.md.

"""Rewriting the text a PDF already contains.

Three of these are worth reading before the rest.

The round trip on an **embedded** font, because a font that is only in the
file and not on the machine is the normal case in a real document, and it is
the one where a mistake would be invisible in a suite built on Helvetica.

The handle-ordering test, which guards a trap rather than a feature. Asking
pypdfium2 for the same page twice hands out two wrappers over one handle;
whichever is collected first frees it for both. Depending on when that
happens the result is either a segmentation fault at some later, unrelated
moment, or — worse — an edit quietly made against a page that no longer
exists, so the save writes the original and nothing says a word.

And the one that records what ``FPDFText_SetText`` really does, because the
first measurement of it here said the opposite for exactly that reason.
"""

from __future__ import annotations

import io

import pypdfium2 as pdfium
import pytest
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as rl_canvas

from orion.commands.history import History
from orion.commands.object_commands import ReplacePageTextCommand
from orion.document.objects import TextObject
from orion.pdf import reader as pdf_reader
from orion.pdf import writer as pdf_writer
from orion.pdf.fonts import FontRequest, available_families, resolve
from orion.pdf.renderer import PageRenderer
from orion.pdf.text_edit import _match_family, line_at
from orion.utils.geometry import Point, Rect

PAGE_SIZE = (400.0, 300.0)
LINES = (
    (240.0, "Dear Mr Rossi,"),
    (200.0, "The amount is EUR 1.234,00"),
    (160.0, "Keep this line untouched"),
)


def _embedded_font(family: str) -> str:
    """Register *family* under a name of this test's own, and return it.

    The family comes from the ``latin_system_family`` fixture rather than from
    whatever the scan happened to list first: a font has to be able to write
    the words these tests look for, and not every installed one can.
    """
    from orion.pdf import fonts

    styles = fonts._index()[family]
    face = styles.get((False, False)) or next(iter(styles.values()))
    name = f"Test:{family}"
    pdfmetrics.registerFont(TTFont(name, str(face.path), subfontIndex=face.index))
    return name


def _source(tmp_path, font: str = "Helvetica"):
    path = tmp_path / f"src-{font.replace(':', '_')}.pdf"
    pdf = rl_canvas.Canvas(str(path), pagesize=PAGE_SIZE)
    pdf.setFont(font, 16)
    for y, text in LINES:
        pdf.drawString(40.0, y, text)
    pdf.showPage()
    pdf.save()
    return path


@pytest.fixture
def opened(tmp_path):
    """A document, its renderer, and the lines of its page text."""

    def _open(path):
        document, handle = pdf_reader.load_document(path)
        renderer = PageRenderer()
        key = document.pages[0].source.source_key
        renderer.register_source(document.sources[key], handle)
        return document, renderer

    return _open


def _replace(document, renderer, click: Point, replacement: str) -> TextObject:
    """Do what the canvas does when the tool is clicked on a line."""
    page = document.pages[0]
    line = line_at(renderer.source_text_lines(page), click)
    assert line is not None, "no line was found under the click"
    run = line.dominant_run
    resolved = resolve(FontRequest(run.family, run.bold, run.italic))
    obj = TextObject(
        rect=Rect.from_xywh(
            line.rect.x0,
            line.baseline - resolved.ascender * line.font_size,
            line.rect.width * 1.15,
            line.font_size * (resolved.ascender - resolved.descender) + 2.0,
        ),
        text=replacement,
        font_family=run.family,
        font_size=line.font_size,
        bold=run.bold,
        italic=run.italic,
        color=run.color,
    )
    History().push(ReplacePageTextCommand(document, 0, obj, line.indices))
    return obj


def _text_of(path) -> str:
    pdf = pdfium.PdfDocument(str(path))
    try:
        return pdf[0].get_textpage().get_text_range()
    finally:
        pdf.close()


# -- reading the page's text ---------------------------------------------
def test_the_lines_of_a_page_are_found(tmp_path, opened):
    document, renderer = opened(_source(tmp_path))
    try:
        lines = renderer.source_text_lines(document.pages[0])
        assert [line.text for line in lines] == [text for _y, text in LINES]
        assert all(line.font_size == pytest.approx(16.0) for line in lines)
    finally:
        renderer.close_all()


def test_runs_that_share_a_baseline_become_one_line(tmp_path, opened):
    """A line of a real document is rarely one drawing operation.

    A change of weight or colour splits it, and an invoice can put every field
    in its own. Clicking has to select the line, not the fragment under the
    cursor.
    """
    path = tmp_path / "runs.pdf"
    pdf = rl_canvas.Canvas(str(path), pagesize=PAGE_SIZE)
    pdf.setFont("Helvetica-Bold", 14)
    pdf.setFillColorRGB(0.8, 0.0, 0.0)
    pdf.drawString(40.0, 200.0, "Amount: ")
    pdf.setFont("Helvetica", 14)
    pdf.setFillColorRGB(0.0, 0.0, 0.0)
    pdf.drawString(105.0, 200.0, "EUR 1.234,00")
    pdf.showPage()
    pdf.save()

    document, renderer = opened(path)
    try:
        lines = renderer.source_text_lines(document.pages[0])
        assert len(lines) == 1
        assert lines[0].text == "Amount: EUR 1.234,00"
        assert len(lines[0].indices) == 2
        # The longer run decides the style, so the line looks like most of it.
        assert lines[0].dominant_run.text == "EUR 1.234,00"
        assert not lines[0].dominant_run.bold
    finally:
        renderer.close_all()


def test_clicking_past_the_end_of_a_line_still_finds_it(tmp_path, opened):
    """Otherwise the feature reads as unreliable."""
    document, renderer = opened(_source(tmp_path))
    try:
        lines = renderer.source_text_lines(document.pages[0])
        middle = lines[1]
        far_right = Point(390.0, (middle.rect.y0 + middle.rect.y1) / 2.0)
        assert line_at(lines, far_right) is middle
    finally:
        renderer.close_all()


def test_clicking_empty_space_finds_nothing(tmp_path, opened):
    document, renderer = opened(_source(tmp_path))
    try:
        lines = renderer.source_text_lines(document.pages[0])
        assert line_at(lines, Point(200.0, 20.0)) is None
    finally:
        renderer.close_all()


@pytest.mark.parametrize(
    "name, flags, weight, angle, expected",
    [
        ("Helvetica", 0, 400, 0.0, ("Helvetica", False, False)),
        ("ABCDEF+Times-Bold", 2, 700, 0.0, ("Times", True, False)),
        ("Courier-Oblique", 1, 400, -12.0, ("Courier", False, True)),
        ("Unknown", 2, 400, 0.0, ("Times", False, False)),
        ("Unknown", 1, 400, 0.0, ("Courier", False, False)),
        ("Unknown", 0, 400, 0.0, ("Helvetica", False, False)),
    ],
)
def test_a_pdf_font_name_becomes_a_family_orion_can_draw(
    name, flags, weight, angle, expected
):
    """The name in the file is PostScript's, not the picker's.

    A subset prefix means nothing and has to go; the style suffix means a great
    deal. When the family is not one this machine has, the descriptor flags
    decide — serif, fixed pitch, or neither — which is what they are for.
    """
    assert _match_family(name, flags, weight, angle) == expected


def test_an_installed_family_is_matched_through_its_postscript_name():
    extras = [f for f in available_families() if " " in f]
    if not extras:
        pytest.skip("no multi-word system family installed to test the match")
    family = extras[0]
    postscript = family.replace(" ", "")
    assert _match_family(f"ABCDEF+{postscript}-Bold", 0, 700, 0.0) == (
        family,
        True,
        False,
    )


# -- the round trip -------------------------------------------------------
def test_replacing_a_line_removes_the_original_from_the_file(tmp_path, opened):
    document, renderer = opened(_source(tmp_path))
    try:
        _replace(document, renderer, Point(120.0, 100.0), "The amount is EUR 5.678,00")
        out = tmp_path / "out.pdf"
        pdf_writer.save_document(document, out)
    finally:
        renderer.close_all()

    text = _text_of(out)
    assert "1.234,00" not in text, "the original text is still in the file"
    assert "5.678,00" in text
    assert "Dear Mr Rossi," in text and "Keep this line untouched" in text


def test_it_works_on_an_embedded_font(tmp_path, opened, latin_system_family):
    """A font that lives only in the file is the normal case in real documents.

    A suite built on Helvetica would never touch the path where the glyphs
    have to be found inside the PDF rather than in the reader.
    """
    font = _embedded_font(latin_system_family)
    document, renderer = opened(_source(tmp_path, font))
    try:
        _replace(document, renderer, Point(120.0, 100.0), "Replaced")
        out = tmp_path / "embedded.pdf"
        pdf_writer.save_document(document, out)
    finally:
        renderer.close_all()

    text = _text_of(out)
    assert "1.234,00" not in text
    assert "Replaced" in text


def test_pdfium_can_set_text_in_place_but_it_is_not_what_is_wanted(latin_system_family):
    """Records what the alternative really does, since it is easy to misjudge.

    ``FPDFText_SetText`` works, on embedded subsets included: it extends the
    font with glyphs the subset never had, accents and all. What it cannot do
    is a line that is three text objects, text longer than the space it had, a
    different size or colour, or wrapping — all of which an Orion text object
    already has. That, not a drawing failure, is why the line is replaced.

    Worth having as a test because the first measurement of this said the
    opposite: the page handle had been let go before the call, so the edit was
    made against a page that no longer existed and the save quietly wrote the
    original. Whoever revisits this should start from a green test rather than
    from that experiment.
    """
    import ctypes

    import pypdfium2.raw as raw

    font = _embedded_font(latin_system_family)

    buffer = io.BytesIO()
    pdf = rl_canvas.Canvas(buffer, pagesize=PAGE_SIZE)
    pdf.setFont(font, 16)
    pdf.drawString(40.0, 200.0, "abc")
    pdf.showPage()
    pdf.save()

    document = pdfium.PdfDocument(buffer.getvalue())
    page = document[0]  # held: letting it go invalidates the edit below
    try:
        obj = raw.FPDFPage_GetObject(page.raw, 0)
        wide = ctypes.cast(
            ctypes.create_string_buffer("città\0".encode("utf-16-le")),
            ctypes.POINTER(ctypes.c_ushort),
        )
        assert raw.FPDFText_SetText(obj, wide)
        raw.FPDFPage_GenerateContent(page.raw)
        out = io.BytesIO()
        document.save(out)
    finally:
        del page
        document.close()

    changed = pdfium.PdfDocument(out.getvalue())
    try:
        assert changed[0].get_textpage().get_text_range().strip() == "città"
    finally:
        changed.close()


def test_the_replacement_lands_where_the_original_was(tmp_path, opened):
    """Rendered rows, not coordinates: the line must not shift up or down.

    Orion places a text box's first baseline at ``top + ascender * size``, so
    the box has to start that far above the original baseline. Getting it
    wrong puts the new line a few points low, which is exactly the kind of
    thing that looks fine in a unit test and obvious on paper.
    """
    source = _source(tmp_path)
    before = _ink_rows(source)

    document, renderer = opened(source)
    try:
        _replace(document, renderer, Point(120.0, 100.0), "The amount is EUR 5.678,00")
        out = tmp_path / "placed.pdf"
        pdf_writer.save_document(document, out)
    finally:
        renderer.close_all()

    after = _ink_rows(out)
    assert len(before) == 3
    # The middle band is the replaced line; it must still cover the same rows.
    assert after[0] == before[0]
    assert abs(after[1][0] - before[1][0]) <= 2
    assert abs(after[1][1] - before[1][1]) <= 2


def _ink_rows(path) -> list[tuple[int, int]]:
    """The bands of rows that have any dark pixel, top to bottom."""
    pdf = pdfium.PdfDocument(str(path))
    try:
        image = pdf[0].render(scale=1, rev_byteorder=True).to_pil().convert("L")
    finally:
        pdf.close()
    pixels = image.load()
    width, height = image.size
    bands: list[tuple[int, int]] = []
    start: int | None = None
    for y in range(height):
        dark = any(pixels[x, y] < 128 for x in range(width))
        if dark and start is None:
            start = y
        elif not dark and start is not None:
            bands.append((start, y - 1))
            start = None
    if start is not None:
        bands.append((start, height - 1))
    return _merge_adjacent(bands)


def _merge_adjacent(bands: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Join bands split by a blank row inside one line of type."""
    merged: list[tuple[int, int]] = []
    for band in bands:
        if merged and band[0] - merged[-1][1] <= 3:
            merged[-1] = (merged[-1][0], band[1])
        else:
            merged.append(band)
    return merged


def test_undo_puts_the_original_text_back(tmp_path, opened):
    """Both halves have to come back, or a line vanishes from the document.

    Undoing only the object would leave the page still marked as owning the
    original, and the next save would delete it with nothing drawn in its
    place.
    """
    document, renderer = opened(_source(tmp_path))
    history = History()
    try:
        page = document.pages[0]
        line = line_at(renderer.source_text_lines(page), Point(120.0, 100.0))
        obj = TextObject(rect=Rect.from_xywh(40.0, 90.0, 200.0, 20.0), text="new")
        history.push(ReplacePageTextCommand(document, 0, obj, line.indices))
        assert page.replaced_text == line.indices
        assert len(page.objects) == 1

        history.undo()
        assert page.replaced_text == ()
        assert page.objects == []

        out = tmp_path / "undone.pdf"
        pdf_writer.save_document(document, out)
    finally:
        renderer.close_all()
    assert "1.234,00" in _text_of(out), "undo lost the original line"


def test_replacing_twice_does_not_ask_for_two_removals(tmp_path, opened):
    document, renderer = opened(_source(tmp_path))
    try:
        page = document.pages[0]
        line = line_at(renderer.source_text_lines(page), Point(120.0, 100.0))
        for _ in range(2):
            obj = TextObject(rect=Rect.from_xywh(40.0, 90.0, 200.0, 20.0), text="x")
            History().push(ReplacePageTextCommand(document, 0, obj, line.indices))
        assert page.replaced_text == line.indices
    finally:
        renderer.close_all()


def test_a_duplicated_page_keeps_its_own_replacement(tmp_path, opened):
    """The reason the removal happens after assembly, not to the source file.

    Patching the source would take the line out of both copies. Output pages
    are one to one with the document's, so each copy keeps what was done to it.
    """
    document, renderer = opened(_source(tmp_path))
    try:
        copy = document.pages[0].duplicate()
        _replace(document, renderer, Point(120.0, 100.0), "Only on the first")
        document.pages.append(copy)
        out = tmp_path / "duplicated.pdf"
        pdf_writer.save_document(document, out)
    finally:
        renderer.close_all()

    pdf = pdfium.PdfDocument(str(out))
    try:
        first = pdf[0].get_textpage().get_text_range()
        second = pdf[1].get_textpage().get_text_range()
    finally:
        pdf.close()
    assert "1.234,00" not in first and "Only on the first" in first
    assert "1.234,00" in second, "the untouched copy lost its text too"


def test_a_document_with_no_replacements_skips_the_extra_pass(tmp_path, opened, monkeypatch):
    """It costs a serialise and a parse of the whole file; do not pay it."""
    called = False

    def spy(*args, **kwargs):
        nonlocal called
        called = True
        return None

    monkeypatch.setattr(pdf_writer, "_remove_page_objects", spy)
    document, renderer = opened(_source(tmp_path))
    try:
        pdf_writer.save_document(document, tmp_path / "plain.pdf")
    finally:
        renderer.close_all()
    assert not called


def test_annotations_survive_the_removal_pass(tmp_path, opened):
    """The pass rewrites the whole document, and annotations are indexed.

    The writer removes imported annotations from a copied page by position, so
    if pdfium's save reordered ``/Annots`` the wrong ones would go — silently,
    and only in files that have both an annotation and an edited line.
    """
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import ArrayObject, DictionaryObject, FloatObject, NameObject

    plain = _source(tmp_path)
    marked = tmp_path / "marked.pdf"
    out_writer = PdfWriter(clone_from=str(plain))
    entry = DictionaryObject()
    entry[NameObject("/Type")] = NameObject("/Annot")
    entry[NameObject("/Subtype")] = NameObject("/Highlight")
    entry[NameObject("/QuadPoints")] = ArrayObject(
        [FloatObject(v) for v in (40, 175, 200, 175, 40, 160, 200, 160)]
    )
    entry[NameObject("/Rect")] = ArrayObject([FloatObject(v) for v in (40, 160, 200, 175)])
    out_writer.add_annotation(0, entry)
    with open(marked, "wb") as handle:
        out_writer.write(handle)

    document, renderer = opened(marked)
    try:
        assert len(document.pages[0].objects) == 1, "the highlight was not imported"
        _replace(document, renderer, Point(120.0, 100.0), "Rewritten")
        out = tmp_path / "both.pdf"
        pdf_writer.save_document(document, out)
    finally:
        renderer.close_all()

    annots = PdfReader(str(out)).pages[0].get("/Annots") or []
    assert [str(a.get_object()["/Subtype"]) for a in annots] == ["/Highlight"]
    assert "Rewritten" in _text_of(out)


def test_one_page_handle_at_a_time(tmp_path):
    """Guards the trap that cost an afternoon.

    pypdfium2's page wrapper frees its handle when collected. Two wrappers over
    one page means whichever goes first frees it for both, and the crash lands
    later — usually at ``close`` — with nothing pointing at the cause. This
    does the same sequence the writer does, and a regression here is a
    segmentation fault rather than a failure, so it is worth having as the
    thing that runs before the rest of the suite does.
    """
    import gc

    source = _source(tmp_path)
    data = source.read_bytes()
    result = pdf_writer._remove_page_objects(data, {0: (1,)})
    gc.collect()
    assert result is not None
    reopened = pdfium.PdfDocument(result)
    try:
        text = reopened[0].get_textpage().get_text_range()
    finally:
        reopened.close()
    assert "1.234,00" not in text
    assert "Dear Mr Rossi," in text


def test_an_index_that_is_no_longer_there_is_survived(tmp_path):
    """The source could have been replaced on disk since the document opened."""
    result = pdf_writer._remove_page_objects(_source(tmp_path).read_bytes(), {0: (99,)})
    assert result is not None
    reopened = pdfium.PdfDocument(result)
    try:
        assert "Dear Mr Rossi," in reopened[0].get_textpage().get_text_range()
    finally:
        reopened.close()
