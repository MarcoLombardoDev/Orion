#!/usr/bin/env python
# Orion — PDF Editor for Desktop
# Copyright (C) 2026 Marco Lombardo
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# Distributed WITHOUT ANY WARRANTY; see LICENSE for the full terms.
# A commercial licence, without the AGPL's obligations, is available for use
# in proprietary or closed-source products — see COMMERCIAL-LICENSE.md.

"""System fonts: finding them, measuring them, embedding them.

Two things are worth guarding here, and they are not the parsing. The first is
that the base-14 path is completely unchanged — every metric and every width
is what it was, because a document saved before this existed must open looking
exactly the same. The second is the round trip: a text box in a system font
has to come out of the file as real text, in that font, wrapped where the
canvas wrapped it.

The tests build their own font files where they can, and skip where the
machine has nothing installed to embed — a bare container is a legitimate
place to run the suite, and a test that demands Arial is a test that fails for
the wrong reason.
"""

from __future__ import annotations

import io
import struct
from pathlib import Path

import pytest
from reportlab.pdfbase import pdfmetrics

from orion.document.objects import BASE14_MAP, TextObject
from orion.pdf import fonts
from orion.pdf.fonts import FontRequest, available_families, resolve
from orion.pdf.text_layout import layout_text, measure
from orion.utils.geometry import Rect


@pytest.fixture
def a_system_family(latin_system_family) -> str:
    """A family installed here that Orion can embed and write words in.

    ``latin_system_family`` earns its keep in ``conftest``: the first family
    alphabetically is not a safe choice, and CI proved it twice over.
    """
    return latin_system_family


# -- the base-14 path must not have moved --------------------------------
@pytest.mark.parametrize("family", sorted(BASE14_MAP))
@pytest.mark.parametrize("bold, italic", [(False, False), (True, False), (True, True)])
def test_the_built_in_families_are_not_embedded(family, bold, italic):
    resolved = resolve(FontRequest(family, bold, italic))
    assert not resolved.embedded, "a base-14 font must never be embedded"
    assert not resolved.substituted
    assert resolved.bold is bold and resolved.italic is italic


def test_the_base14_metrics_are_the_ones_documents_were_saved_against():
    """These position the first baseline, so they are part of the format.

    They are the font *bounding box*, not the typographic ascent reportlab
    reports — 1.075 against 0.718 for Helvetica. Adopting reportlab's number
    would lift the first line of every text box in every document anyone has
    already saved, which is why they are a table rather than a lookup.
    """
    assert resolve(FontRequest("Helvetica")).ascender == pytest.approx(1.075)
    assert resolve(FontRequest("Helvetica")).descender == pytest.approx(-0.299)
    assert resolve(FontRequest("Times")).ascender == pytest.approx(1.053)
    assert resolve(FontRequest("Courier", bold=True)).ascender == pytest.approx(1.007)
    assert pdfmetrics.getFont("Helvetica").face.ascent == pytest.approx(718, abs=1)


def test_the_built_in_families_come_first():
    families = available_families()
    assert families[:3] == ("Helvetica", "Times", "Courier")
    assert len(set(families)) == len(families), "a family is offered twice"


def test_widths_still_match_the_base14_tables():
    """The wrapping of an existing document must not shift by a hair."""
    assert measure("Hello Orion", FontRequest("Helvetica"), 12.0) == pytest.approx(
        pdfmetrics.stringWidth("Hello Orion", "Helvetica", 12.0)
    )
    assert measure("Hello Orion", FontRequest("Times", bold=True), 12.0) == pytest.approx(
        pdfmetrics.stringWidth("Hello Orion", "Times-Bold", 12.0)
    )


# -- system fonts ---------------------------------------------------------
def test_a_system_family_is_embedded_and_measured_with_its_own_metrics(a_system_family):
    """The metrics have to come from the font, not from the fallback.

    Asserting a *range* was the first attempt and it was wrong: "DejaVu Math
    TeX Gyre" is a real, installed, perfectly valid font whose bounding box is
    two and a half ems tall, because it has to hold an integral sign. A number
    plucked from what Helvetica happens to look like is not an invariant. What
    is one: the box has a top above the baseline and a bottom below it, and it
    is not Helvetica's.
    """
    resolved = resolve(FontRequest(a_system_family))
    assert resolved.embedded
    assert not resolved.substituted
    assert resolved.ascender > 0.0 > resolved.descender
    helvetica = resolve(FontRequest("Helvetica"))
    assert (resolved.ascender, resolved.descender) != (
        helvetica.ascender,
        helvetica.descender,
    ), "the fallback's metrics were used for an embedded font"
    assert measure("Hello Orion", FontRequest(a_system_family), 12.0) > 0.0


def test_a_missing_family_falls_back_and_says_so():
    """Silence would be the wrong answer: the file would not match the screen."""
    resolved = resolve(FontRequest("Definitely Not Installed Sans"))
    assert resolved.substituted
    assert resolved.name == "Helvetica"
    assert not resolved.embedded


def test_a_style_a_family_does_not_ship_is_reported(a_system_family, monkeypatch):
    """The resolved face says what it really is, so the canvas can agree.

    Qt will happily fake a slant on screen for a family that has no italic.
    The writer cannot, so the saved file would be upright — and the difference
    only shows when the document is opened somewhere else.
    """
    only_regular = {
        a_system_family: {(False, False): fonts._index()[a_system_family][(False, False)]}
    }
    monkeypatch.setattr(fonts, "_system_fonts", only_regular)
    resolve.cache_clear()
    try:
        resolved = resolve(FontRequest(a_system_family, bold=True, italic=True))
        assert resolved.embedded
        assert not resolved.bold and not resolved.italic
    finally:
        resolve.cache_clear()


def test_bold_is_kept_before_italic_when_only_one_is_available():
    """Losing the slant changes a paragraph less than losing the weight."""
    face = fonts._Face("Test", bold=True, italic=False, path=Path("x"), index=0)
    styles = {(True, False): face}
    assert fonts._closest(styles, bold=True, italic=True) is face
    assert fonts._closest(styles, bold=False, italic=False) is face


# -- reading font files ---------------------------------------------------
def test_only_embeddable_fonts_are_offered():
    """A font reportlab cannot embed must not reach the picker.

    Offering one is worse than leaving it out: the failure would arrive at
    save time, on a document the user has already written.
    """
    for family, styles in fonts._index().items():
        face = next(iter(styles.values()))
        assert face.path.suffix.lower() in fonts.FONT_SUFFIXES, family


@pytest.mark.parametrize(
    "content",
    [
        b"this is not a font at all, not even nearly",
        b"",
        b"\x00\x01\x00\x00truncated after the header",
        b"ttcf\x00\x01\x00\x00\x00\x00\x00\x09",  # a collection of nine that is not there
    ],
)
def test_a_file_that_is_not_a_usable_font_yields_nothing(tmp_path, content):
    """Whether it raises or simply parses to nothing, no face may come out.

    ``_scan`` catches the parse errors, so a file that quietly produced a
    garbage face would be worse than one that failed loudly: it would reach
    the picker and fail at save time instead.
    """
    junk = tmp_path / "notafont.ttf"
    junk.write_bytes(content)
    try:
        faces = fonts._faces_in_file(junk)
    except (ValueError, OSError, struct.error):
        faces = []  # what the scan does with it, and equally acceptable
    assert faces == []


def test_apples_hidden_fonts_are_not_offered():
    """macOS ships private fonts whose names begin with a dot.

    CoreText keeps them out of every picker on the platform, and they are
    often partial: ".ADT Slab Numeric" has the digits and hardly any letters,
    so a document set in it loses most of its text. Alphabetical order put it
    first in the list, which made it the worst possible default — and is how
    CI found it.
    """
    assert not [name for name in available_families() if name.startswith(".")]
    assert not [name for name in fonts._index() if name.startswith(".")]


def test_the_scan_survives_a_directory_of_rubbish(tmp_path, monkeypatch):
    """One bad file must not stop the others being found."""
    (tmp_path / "broken.ttf").write_bytes(b"\x00\x01\x00\x00truncated")
    (tmp_path / "empty.otf").write_bytes(b"")
    monkeypatch.setattr(fonts, "font_directories", lambda: [tmp_path])
    assert fonts._scan() == {}


def test_font_directories_are_all_absolute_and_existing():
    for path in fonts.font_directories():
        assert path.is_absolute() and path.is_dir()


# -- the round trip -------------------------------------------------------
def _written_text(document_font: str, tmp_path) -> tuple[str, bytes]:
    """Save a one-page document with one text box, and read it back."""
    import pypdfium2 as pdfium
    from pypdf import PdfWriter as PyPdfWriter

    from orion.document.document import Document, DocumentSource
    from orion.document.page import Page, PageSource
    from orion.pdf import writer
    from orion.utils.geometry import Size

    source_path = tmp_path / "blank.pdf"
    blank = PyPdfWriter()
    blank.add_blank_page(400.0, 600.0)
    with open(source_path, "wb") as handle:
        blank.write(handle)

    source = DocumentSource.for_path(source_path)
    page = Page(base_size=Size(400.0, 600.0), source=PageSource(source.key, 0))
    page.add_object(
        TextObject(
            rect=Rect.from_xywh(40.0, 60.0, 300.0, 120.0),
            text="Embedded Orion text",
            font_family=document_font,
            font_size=18.0,
        )
    )
    document = Document(pages=[page], sources=[source], path=source_path)
    out = tmp_path / "out.pdf"
    writer.save_document(document, out)

    data = out.read_bytes()
    pdf = pdfium.PdfDocument(io.BytesIO(data))
    try:
        return pdf[0].get_textpage().get_text_range(), data
    finally:
        pdf.close()


def test_text_in_a_system_font_stays_real_text(a_system_family, tmp_path):
    """The whole point of writing text rather than a picture of it."""
    text, data = _written_text(a_system_family, tmp_path)
    assert "Embedded Orion text" in text
    assert b"FontFile2" in data, "the font was not embedded"


def test_text_in_a_built_in_font_embeds_nothing(tmp_path):
    text, data = _written_text("Helvetica", tmp_path)
    assert "Embedded Orion text" in text
    assert b"FontFile" not in data, "a base-14 font must not be embedded"


def test_a_system_font_makes_a_bigger_file_than_a_built_in_one(
    a_system_family, tmp_path
):
    """Worth stating plainly: embedding is the cost of the feature."""
    first, second = tmp_path / "a", tmp_path / "b"
    first.mkdir()
    second.mkdir()
    _, plain = _written_text("Helvetica", first)
    _, embedded = _written_text(a_system_family, second)
    assert len(embedded) > len(plain)


def test_the_layout_uses_the_font_it_is_given(a_system_family):
    """Different fonts wrap differently, which is the reason to measure at all."""
    rect = Rect.from_xywh(0.0, 0.0, 90.0, 200.0)
    words = "The quick brown fox jumps over the lazy dog"
    built_in = layout_text(words, rect, font=FontRequest("Courier"), font_size=12.0)
    system = layout_text(words, rect, font=FontRequest(a_system_family), font_size=12.0)
    assert built_in.lines and system.lines
    assert built_in.ascender != system.ascender or len(built_in.lines) != len(
        system.lines
    ), "the layout ignored the font"


def test_the_default_font_is_still_helvetica():
    layout = layout_text("x", Rect.from_xywh(0, 0, 100, 100), font_size=12.0)
    assert layout.ascender == pytest.approx(1.075)


def test_refreshing_picks_up_a_newly_installed_font(tmp_path, monkeypatch):
    """Installing a font while Orion is open should not need a restart."""
    before = available_families()
    monkeypatch.setattr(fonts, "font_directories", lambda: [tmp_path])
    fonts.refresh_system_fonts()
    try:
        assert available_families() == fonts.BASE14_FAMILIES
    finally:
        monkeypatch.undo()
        fonts.refresh_system_fonts()
    assert available_families() == before
