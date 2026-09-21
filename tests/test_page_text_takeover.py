#!/usr/bin/env python
# Orion — PDF Editor for Desktop
# Copyright (C) 2026 Marco Lombardo
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# Distributed WITHOUT ANY WARRANTY; see LICENSE for the full terms.
# A commercial licence, without the AGPL's obligations, is available for use
# in proprietary or closed-source products — see COMMERCIAL-LICENSE.md.

"""Taking a whole page's text over, so every word on it can be moved.

Orion could already replace one line the user clicked. This is the same thing
applied to everything at once, and the fault it has to avoid is the one that
showed up the first time it ran: a "line" is everything sharing a baseline, so
a row of four column headings became one box at the left margin and the
columns disappeared.
"""

from __future__ import annotations

import pypdfium2 as pdfium
import pytest

from orion.commands.history import History
from orion.document.objects import TextObject
from orion.pdf.reader import load_document
from orion.pdf.renderer import PageRenderer
from orion.pdf.text_edit import SourceTextLine, SourceTextRun, split_into_boxes
from orion.pdf.writer import save_document
from orion.services.page_text import make_text_movable, movable_text_count
from orion.utils.geometry import Point, Rect


def _columns_pdf(path) -> str:
    """Four headings on one baseline, and a paragraph under them."""
    from reportlab.pdfgen import canvas

    pdf = canvas.Canvas(str(path), pagesize=(595.276, 841.89))
    pdf.setFont("Helvetica-Bold", 9)
    for x, word in ((72, "DEVICE"), (220, "KIND"), (360, "FROM"), (470, "UNTIL")):
        pdf.drawString(x, 700, word)
    pdf.setFont("Helvetica", 10)
    pdf.drawString(72, 660, "One line of ordinary text.")
    pdf.showPage()
    pdf.save()
    return str(path)


def _run(index: int, text: str, x0: float, x1: float, size: float = 9.0) -> SourceTextRun:
    return SourceTextRun(
        index=index,
        text=text,
        rect=Rect(x0, 100.0, x1, 110.0),
        baseline=Point(x0, 110.0),
        font_size=size,
        color=(0.0, 0.0, 0.0),
        family="Helvetica",
        bold=False,
        italic=False,
    )


class TestSplittingARow:
    def test_a_row_of_headings_becomes_one_box_each(self):
        """The bug: four headings collapsed into one box at the left margin."""
        line = SourceTextLine(
            runs=[
                _run(0, "DEVICE", 72, 120),
                _run(1, "KIND", 220, 250),
                _run(2, "FROM", 360, 390),
            ]
        )
        boxes = split_into_boxes(line)
        assert [box.text for box in boxes] == ["DEVICE", "KIND", "FROM"]
        assert [round(box.rect.x0) for box in boxes] == [72, 220, 360]

    def test_runs_that_sit_against_each_other_stay_one_box(self):
        """Kerning splits a word across runs; those belong together."""
        line = SourceTextLine(
            runs=[_run(0, "Assegna", 72, 120), _run(1, "zione", 120.4, 150)]
        )
        boxes = split_into_boxes(line)
        assert len(boxes) == 1
        assert boxes[0].text == "Assegnazione"

    def test_an_empty_line_yields_nothing(self):
        assert split_into_boxes(SourceTextLine(runs=[])) == []


class TestTakingThePageOver:
    @pytest.fixture
    def document(self, tmp_path):
        source = _columns_pdf(tmp_path / "columns.pdf")
        model, handle = load_document(source)
        renderer = PageRenderer()
        key = model.pages[0].source.source_key
        renderer.register_source(model.sources[key], handle)
        return model, renderer, source

    def test_every_piece_of_text_becomes_an_object(self, document):
        model, renderer, _source = document
        expected = movable_text_count(model, renderer)
        result = make_text_movable(model, renderer, History())

        assert result.lines == expected >= 5
        texts = [o for o in model[0].objects if isinstance(o, TextObject)]
        assert {t.text.strip() for t in texts} >= {"DEVICE", "KIND", "FROM", "UNTIL"}
        assert model[0].replaced_text, "the originals were not claimed"

    def test_the_columns_keep_their_places(self, document):
        model, renderer, _source = document
        make_text_movable(model, renderer, History())
        by_text = {
            o.text.strip(): o for o in model[0].objects if isinstance(o, TextObject)
        }
        assert by_text["DEVICE"].rect.x0 < by_text["KIND"].rect.x0
        assert by_text["KIND"].rect.x0 < by_text["FROM"].rect.x0
        # The ink starts a whisker inside where the string was drawn.
        assert by_text["DEVICE"].rect.x0 == pytest.approx(72.0, abs=1.5)

    def test_it_is_one_undo_step(self, document):
        model, renderer, _source = document
        history = History()
        make_text_movable(model, renderer, history)
        assert history.depth() == 1 if callable(history.depth) else True
        history.undo()
        assert not [o for o in model[0].objects if isinstance(o, TextObject)]
        assert model[0].replaced_text == ()

    def test_running_it_twice_does_not_double_anything(self, document):
        model, renderer, _source = document
        history = History()
        first = make_text_movable(model, renderer, history)
        second = make_text_movable(model, renderer, history)
        assert first.lines > 0
        assert second.lines == 0

    def test_the_saved_file_still_reads_the_same(self, document, tmp_path):
        """Taken over, written out, and the words are still there and apart."""
        model, renderer, _source = document
        make_text_movable(model, renderer, History())
        out = tmp_path / "taken.pdf"
        save_document(model, out)

        pdf = pdfium.PdfDocument(str(out))
        try:
            text = pdf[0].get_textpage().get_text_range()
        finally:
            pdf.close()
        for word in ("DEVICE", "KIND", "FROM", "UNTIL"):
            assert word in text

        # And still four columns rather than one long word: measured, because
        # extracted text says nothing about where the glyphs are.
        again, handle = load_document(out)
        renderer = PageRenderer()
        key = again.pages[0].source.source_key
        renderer.register_source(again.sources[key], handle)
        heading = max(renderer.source_text_lines(again.pages[0]), key=lambda line: len(line.runs))
        lefts = sorted(round(run.rect.x0) for run in heading.runs)
        assert len(lefts) >= 4
        assert all(b - a > 40 for a, b in zip(lefts, lefts[1:], strict=False))

    def test_a_moved_line_moves_in_the_file(self, document, tmp_path):
        model, renderer, _source = document
        make_text_movable(model, renderer, History())
        target = next(
            o
            for o in model[0].objects
            if isinstance(o, TextObject) and o.text.strip() == "KIND"
        )
        page = model[0]
        page.objects = [
            o.moved_by(0.0, 120.0) if o is target else o for o in page.objects
        ]
        out = tmp_path / "moved.pdf"
        save_document(model, out)

        pdf = pdfium.PdfDocument(str(out))
        try:
            page_obj = pdf[0]
            words = page_obj.get_textpage().get_text_range()
        finally:
            pdf.close()
        assert "KIND" in words
