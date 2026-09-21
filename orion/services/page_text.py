# Orion — PDF Editor for Desktop
# Copyright (C) 2026 Marco Lombardo
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# Distributed WITHOUT ANY WARRANTY; see LICENSE for the full terms.
# A commercial licence, without the AGPL's obligations, is available for use
# in proprietary or closed-source products — see COMMERCIAL-LICENSE.md.

"""Turning a page's own words into objects that can be picked up.

Orion could already replace **one** line of a PDF's text: click it, type over
it, and the original glyphs are dropped from the saved file while a text box
takes their place. Everything else on the page stayed where the document put
it — which is right for a scanned contract and wrong for a form Orion itself
has just drawn, where every caption is something the user may want to nudge.

So the same machinery is offered wholesale: every line of a page becomes a
text object in one undoable step. The objects are placed on the ink, in the
face and colour the line already had, and the lines they stand for are
recorded as replaced, so nothing is drawn twice and nothing is left behind in
the saved file.

It is not free, and the cost is worth stating plainly: a line taken over is
re-laid-out by Orion when the file is written, in one of the base-14 fonts,
with Orion's line breaking rather than the original's. For text Orion drew
itself from an XFA template that is a round trip; for somebody else's
typesetting it is a change. That is why this is something the user asks for
rather than something that happens to every document that opens.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from orion.commands.history import History
from orion.commands.object_commands import ReplacePageTextCommand
from orion.document.document import Document
from orion.pdf.text_edit import split_into_boxes, text_object_for

log = logging.getLogger(__name__)

__all__ = ["TextTakeover", "make_text_movable", "movable_text_count"]

def _worth_taking(line) -> bool:
    """A line of nothing but spaces has no ink to move and no words to edit."""
    return bool(line.text.strip()) and line.rect.width > 0.5 and line.font_size > 0.5


@dataclass(frozen=True, slots=True)
class TextTakeover:
    """What one run of :func:`make_text_movable` did."""

    lines: int = 0
    pages: int = 0

    @property
    def happened(self) -> bool:
        return self.lines > 0


def movable_text_count(document: Document, renderer) -> int:
    """How many lines could be taken over, without taking any over."""
    total = 0
    for page in document.pages:
        claimed = set(page.replaced_text)
        for line in renderer.source_text_lines(page):
            for piece in split_into_boxes(line):
                if _worth_taking(piece) and not claimed.intersection(piece.indices):
                    total += 1
    return total


def make_text_movable(
    document: Document, renderer, history: History, *, text: str = "Make Text Movable"
) -> TextTakeover:
    """Turn every line of the document's own text into a text object.

    One undo step for the whole document: a user who tries this and does not
    like it wants their document back, not forty presses of Ctrl+Z.

    Lines already taken over are skipped, so running it twice is not a way to
    end up with two boxes over one line.
    """
    plans: list[tuple[int, object, tuple[int, ...]]] = []
    for index, page in enumerate(document.pages):
        claimed = set(page.replaced_text)
        try:
            lines = renderer.source_text_lines(page)
        except Exception:  # pragma: no cover - a page whose text cannot be read
            log.warning("Could not read the text of page %d", index + 1, exc_info=True)
            continue
        for line in lines:
            for piece in split_into_boxes(line):
                if not _worth_taking(piece) or claimed.intersection(piece.indices):
                    continue
                try:
                    plans.append((index, text_object_for(piece), piece.indices))
                except Exception:  # pragma: no cover - one unreadable piece
                    log.warning(
                        "Could not take over a line of page %d", index + 1, exc_info=True
                    )

    if not plans:
        return TextTakeover()

    history.begin_macro(text)
    try:
        for index, obj, indices in plans:
            history.push(ReplacePageTextCommand(document, index, obj, indices, text=text))
    except Exception:  # pragma: no cover - defensive
        history.abort_macro()
        raise
    history.end_macro()

    return TextTakeover(lines=len(plans), pages=len({index for index, _, _ in plans}))
