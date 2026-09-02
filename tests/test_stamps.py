#!/usr/bin/env python
# Orion — PDF Editor for Desktop
# Copyright (C) 2026 Marco Lombardo
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# Distributed WITHOUT ANY WARRANTY; see LICENSE for the full terms.
# A commercial licence, without the AGPL's obligations, is available for use
# in proprietary or closed-source products — see COMMERCIAL-LICENSE.md.

"""Watermarks and page numbers.

Both are ordinary text objects, which is the design and also what these check:
they land in the right place, they say the right thing, and — because they are
text rather than a picture of text — they come out of the saved file as words
a reader can select and a search can find.
"""

from __future__ import annotations

import pypdfium2 as pdfium
import pytest
from pypdf import PdfWriter as PyPdfWriter

from orion.document.document import Document, DocumentSource
from orion.document.objects import Align, TextObject
from orion.document.page import Page, PageSource
from orion.pdf import writer as pdf_writer
from orion.pdf.stamps import (
    Corner,
    PageNumberSpec,
    WatermarkSpec,
    format_page_number,
    page_number_for,
    page_numbers_for,
    watermark_for,
)
from orion.utils.geometry import Size

PAGE = Size(400.0, 600.0)


def _page() -> Page:
    return Page(base_size=PAGE)


# -- watermarks -----------------------------------------------------------
def test_a_watermark_is_centred_on_the_page():
    obj = watermark_for(_page(), WatermarkSpec(font_size=60.0))
    assert obj.rect.center.y == pytest.approx(PAGE.height / 2.0)
    assert obj.rect.center.x == pytest.approx(PAGE.width / 2.0)
    assert obj.align is Align.CENTER


def test_the_box_is_measured_to_the_words():
    """A page-wide box breaks a long word in half and swings it off centre.

    Text wraps inside its box, and the box turns about its own middle. Both
    faults look the same on the page and both go away when the box is the
    width of the line it holds.
    """
    from orion.pdf.fonts import FontRequest
    from orion.pdf.text_layout import measure

    spec = WatermarkSpec(text="CONFIDENTIAL", font_size=24.0)
    obj = watermark_for(_page(), spec)
    words = measure(spec.text, FontRequest(spec.font_family), obj.font_size)
    # A whisker wider, so the layout does not wrap the last letter.
    assert words < obj.rect.width <= words + 4.0


def test_a_watermark_too_wide_for_the_page_is_shrunk_to_fit():
    """Level, because that is the orientation with the least room.

    "CONFIDENTIAL" at sixty points measures about 440 points, which does not
    fit across a 400-point page — turned diagonally it would, which is the
    point of the next test.
    """
    spec = WatermarkSpec(text="CONFIDENTIAL", font_size=60.0, rotation=0.0)
    obj = watermark_for(_page(), spec)
    assert obj.font_size < spec.font_size
    assert obj.rect.width <= PAGE.width


def test_a_watermark_that_already_fits_is_left_alone():
    spec = WatermarkSpec(text="OK", font_size=40.0)
    assert watermark_for(_page(), spec).font_size == pytest.approx(40.0)


def test_turning_it_buys_room():
    """A diagonal line has more space on a rectangle than a level one."""
    from orion.pdf.stamps import fitted_font_size

    page = _page()
    spec = WatermarkSpec(text="CONFIDENTIAL", font_size=60.0)
    flat = fitted_font_size(WatermarkSpec(text=spec.text, font_size=60.0, rotation=0.0), page)
    diagonal = fitted_font_size(spec, page)
    assert diagonal > flat


def test_the_watermark_box_is_one_line_tall():
    """A taller box would push the words above centre.

    Text is laid out from the top of its box downwards, so a box the height of
    the page would put a single line near the top of it — which looks like a
    bug and is really an arithmetic slip about where the first baseline goes.
    """
    spec = WatermarkSpec(font_size=60.0)
    obj = watermark_for(_page(), spec)
    assert obj.rect.height < spec.font_size * 2.0


def test_the_watermark_carries_its_style():
    spec = WatermarkSpec(
        text="CONFIDENTIAL", font_size=48.0, color=(0.8, 0.0, 0.0), opacity=0.4, rotation=-30.0
    )
    obj = watermark_for(_page(), spec)
    assert obj.text == "CONFIDENTIAL"
    assert obj.font_size == pytest.approx(48.0)
    assert obj.color == pytest.approx((0.8, 0.0, 0.0))
    assert obj.opacity == pytest.approx(0.4)
    assert obj.rotation == pytest.approx(-30.0)


def test_a_watermark_fits_a_landscape_page_too():
    page = Page(base_size=Size(842.0, 595.0))
    obj = watermark_for(page, WatermarkSpec())
    assert obj.rect.center.x == pytest.approx(842.0 / 2.0)
    assert obj.rect.center.y == pytest.approx(595.0 / 2.0)
    assert obj.rect.width <= 842.0


# -- page numbers ---------------------------------------------------------
@pytest.mark.parametrize(
    "corner, at_top, align",
    [
        (Corner.TOP_LEFT, True, Align.LEFT),
        (Corner.TOP_CENTRE, True, Align.CENTER),
        (Corner.TOP_RIGHT, True, Align.RIGHT),
        (Corner.BOTTOM_LEFT, False, Align.LEFT),
        (Corner.BOTTOM_CENTRE, False, Align.CENTER),
        (Corner.BOTTOM_RIGHT, False, Align.RIGHT),
    ],
)
def test_every_corner_lands_on_the_right_edge(corner, at_top, align):
    obj = page_number_for(_page(), PageNumberSpec(corner=corner), 0, 1)
    assert obj.align is align
    if at_top:
        assert obj.rect.y0 < PAGE.height / 2.0
    else:
        assert obj.rect.y1 > PAGE.height / 2.0
    assert obj.rect.y0 >= 0.0 and obj.rect.y1 <= PAGE.height


@pytest.mark.parametrize(
    "template, position, total, expected",
    [
        ("{n}", 0, 3, "1"),
        ("{n}", 2, 3, "3"),
        ("Page {n} of {total}", 1, 3, "Page 2 of 3"),
        ("- {n} -", 0, 1, "- 1 -"),
        ("no placeholder", 0, 1, "no placeholder"),
    ],
)
def test_the_template_is_filled_in(template, position, total, expected):
    assert format_page_number(PageNumberSpec(template=template), position, total) == expected


def test_a_broken_template_puts_the_braces_on_the_page():
    """It comes from a text field, so a stray brace must not stop the job."""
    assert format_page_number(PageNumberSpec(template="{oops}"), 0, 1) == "{oops}"
    assert format_page_number(PageNumberSpec(template="{"), 0, 1) == "{"


def test_numbering_can_start_anywhere():
    spec = PageNumberSpec(start_at=7)
    assert [page_number_for(_page(), spec, i, 3).text for i in range(3)] == ["7", "8", "9"]


def test_the_pages_are_numbered_in_the_order_they_were_chosen():
    """Skipping a cover page means the numbering starts on the next one.

    Which is why ``start_at`` is a pure offset rather than a page index: the
    caller decides which pages are in, and they are numbered one after another
    from there.
    """
    pages = [_page() for _ in range(3)]
    numbers = page_numbers_for(pages, PageNumberSpec(template="{n} of {total}"))
    assert [obj.text for obj in numbers] == ["1 of 3", "2 of 3", "3 of 3"]


# -- the round trip -------------------------------------------------------
def _saved_text(tmp_path, *objects) -> str:
    blank = tmp_path / "blank.pdf"
    out = PyPdfWriter()
    out.add_blank_page(PAGE.width, PAGE.height)
    with open(blank, "wb") as handle:
        out.write(handle)

    source = DocumentSource.for_path(blank)
    page = Page(base_size=PAGE, source=PageSource(source.key, 0))
    for obj in objects:
        page.add_object(obj)
    document = Document(pages=[page], sources=[source], path=blank)
    saved = tmp_path / "out.pdf"
    pdf_writer.save_document(document, saved)

    pdf = pdfium.PdfDocument(str(saved))
    try:
        return pdf[0].get_textpage().get_text_range()
    finally:
        pdf.close()


def test_a_watermark_is_real_text_in_the_saved_file(tmp_path):
    """Not a picture of a word: it stays selectable and searchable."""
    obj = watermark_for(_page(), WatermarkSpec(text="CONFIDENTIAL"))
    assert "CONFIDENTIAL" in _saved_text(tmp_path, obj)


def test_page_numbers_reach_the_saved_file(tmp_path):
    obj = page_number_for(_page(), PageNumberSpec(template="Page {n} of {total}"), 4, 9)
    assert "Page 5 of 9" in _saved_text(tmp_path, obj)


def test_a_stamp_is_an_ordinary_object_afterwards():
    """The reason they are text objects: everything else already works.

    Moving, restyling, deleting and undo come for free, and a page number that
    lands on top of a footer can be dragged rather than regenerated.
    """
    obj = watermark_for(_page(), WatermarkSpec())
    assert isinstance(obj, TextObject)
    assert not obj.locked
    restored = TextObject.from_dict(obj.to_dict())
    assert restored.text == obj.text
    assert restored.rotation == pytest.approx(obj.rotation)
    assert restored.opacity == pytest.approx(obj.opacity)


# -- what Qt does to a str enum -------------------------------------------
def test_a_corner_arrives_by_name_as_readily_as_by_member():
    """``Corner`` is a ``str`` enum, and Qt hands one back as a plain string.

    A combo box stores its data in a ``QVariant``, which sees something that
    *is* a string and keeps the string; the member is gone by the time
    ``currentData`` returns. Every position the page-number dialog offered
    crashed on ``.at_top`` because of it.
    """
    spec = PageNumberSpec(corner="top_right")
    assert spec.corner is Corner.TOP_RIGHT
    assert spec.corner.at_top


@pytest.mark.parametrize("corner", list(Corner))
def test_every_position_survives_the_round_trip(corner):
    """Pinned for all six, since all six came through the same combo box."""
    spec = PageNumberSpec(corner=corner.value)
    obj = page_number_for(_page(), spec, 0, 1)
    assert obj.align is corner.align


def test_a_corner_that_is_not_one_still_raises():
    """Coercion is for Qt's flattening, not for hiding a typo."""
    with pytest.raises(ValueError):
        PageNumberSpec(corner="middle_of_nowhere")
