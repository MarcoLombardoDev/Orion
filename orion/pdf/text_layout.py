# Orion — PDF Editor for Desktop
# Copyright (C) 2026 Marco Lombardo
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# Distributed WITHOUT ANY WARRANTY; see LICENSE for the full terms.
# A commercial licence, without the AGPL's obligations, is available for use
# in proprietary or closed-source products — see COMMERCIAL-LICENSE.md.

"""Text layout shared by the canvas and the PDF writer.

Line breaking is done **once**, here, using the metrics of the base-14 PDF font
the text will actually be written with.  Both the on-screen renderer and the
PDF writer consume the same :class:`TextLayout`, so what the user sees on the
canvas is where the glyphs land in the saved file — no second, divergent
wrapping implementation.

The base-14 fonts are the fourteen every PDF reader is required to provide, so
their metrics are fixed constants rather than something to read out of a font
file. Widths come from reportlab's AFM tables; ascender and descender are the
table below.

Those two numbers deserve a note, because they are not the same quantity every
library means by the words. reportlab reports the *typographic* ascent from the
AFM — 0.718 for Helvetica — while the table below holds the font **bounding
box** extent, 1.075. Orion positions its first baseline at
``top + ascender * font_size``, and has always done so against the bounding-box
figure: adopting reportlab's would lift the first line of every text box in
every document a user has already saved. The numbers are therefore captured
rather than recomputed, and ``tests/test_text_layout.py`` pins them.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from functools import lru_cache

from reportlab.pdfbase import pdfmetrics

from orion.document.objects import Align
from orion.utils.geometry import Rect

__all__ = [
    "TextSegment",
    "TextLine",
    "TextLayout",
    "layout_text",
    "measure",
    "font_metrics",
    "reportlab_name",
]

#: Orion's base-14 identifiers mapped to the names reportlab knows them by.
#: The identifiers are the ones the document model stores, so they are part of
#: the saved-file format and cannot be renamed.
REPORTLAB_NAMES: dict[str, str] = {
    "helv": "Helvetica",
    "hebo": "Helvetica-Bold",
    "heit": "Helvetica-Oblique",
    "hebi": "Helvetica-BoldOblique",
    "tiro": "Times-Roman",
    "tibo": "Times-Bold",
    "tiit": "Times-Italic",
    "tibi": "Times-BoldItalic",
    "cour": "Courier",
    "cobo": "Courier-Bold",
    "coit": "Courier-Oblique",
    "cobi": "Courier-BoldOblique",
}

#: ``(ascender, descender)`` as fractions of the font size — the font bounding
#: box, not the typographic ascent. See the module docstring for why.
_BBOX_METRICS: dict[str, tuple[float, float]] = {
    "helv": (1.075, -0.299),
    "hebo": (1.070, -0.307),
    "heit": (1.070, -0.284),
    "hebi": (1.073, -0.309),
    "tiro": (1.053, -0.281),
    "tibo": (1.044, -0.341),
    "tiit": (0.951, -0.270),
    "tibi": (0.972, -0.324),
    "cour": (0.932, -0.317),
    "cobo": (1.007, -0.393),
    "coit": (0.920, -0.317),
    "cobi": (0.997, -0.393),
}

DEFAULT_FONT = "helv"


def reportlab_name(fontname: str) -> str:
    """Orion's font identifier -> the name reportlab draws with."""
    return REPORTLAB_NAMES.get(fontname, REPORTLAB_NAMES[DEFAULT_FONT])


@lru_cache(maxsize=32)
def font_metrics(fontname: str) -> tuple[float, float]:
    """``(ascender, descender)`` as fractions of the font size."""
    return _BBOX_METRICS.get(fontname, _BBOX_METRICS[DEFAULT_FONT])


def measure(text: str, fontname: str, font_size: float) -> float:
    """Width of *text* in points."""
    if not text:
        return 0.0
    return float(pdfmetrics.stringWidth(text, reportlab_name(fontname), font_size))


@dataclass(frozen=True, slots=True)
class TextSegment:
    """A run of text placed at an absolute x position on its line."""

    text: str
    x: float
    width: float


@dataclass(frozen=True, slots=True)
class TextLine:
    segments: tuple[TextSegment, ...]
    baseline: float
    width: float

    @property
    def text(self) -> str:
        return "".join(s.text for s in self.segments)


@dataclass(slots=True)
class TextLayout:
    lines: list[TextLine] = field(default_factory=list)
    font_size: float = 12.0
    line_height: float = 14.4
    ascender: float = 1.0
    descender: float = -0.2
    content_height: float = 0.0
    overflows: bool = False

    @property
    def is_empty(self) -> bool:
        return not self.lines

    def underline_spans(
        self, thickness_ratio: float = 0.06
    ) -> list[tuple[float, float, float, float]]:
        """``(x0, y, x1, thickness)`` for one underline per non-empty line."""
        offset = self.font_size * 0.12
        thickness = max(0.4, self.font_size * thickness_ratio)
        spans: list[tuple[float, float, float, float]] = []
        for line in self.lines:
            if not line.text.strip():
                continue
            x0 = min(s.x for s in line.segments)
            x1 = max(s.x + s.width for s in line.segments)
            spans.append((x0, line.baseline + offset, x1, thickness))
        return spans


def _split_words(paragraph: str) -> list[str]:
    """Split on spaces, keeping the trailing space with each word."""
    words: list[str] = []
    current = ""
    for char in paragraph:
        current += char
        if char == " ":
            words.append(current)
            current = ""
    if current:
        words.append(current)
    return words


def _break_long_word(word: str, fontname: str, font_size: float, max_width: float) -> list[str]:
    """Hard-break a word that cannot fit on a line by itself."""
    parts: list[str] = []
    current = ""
    for char in word:
        candidate = current + char
        if current and measure(candidate, fontname, font_size) > max_width:
            parts.append(current)
            current = char
        else:
            current = candidate
    if current:
        parts.append(current)
    return parts or [word]


def _wrap_paragraph(
    paragraph: str, fontname: str, font_size: float, max_width: float
) -> list[list[str]]:
    """Wrap one paragraph into a list of lines, each a list of words."""
    if not paragraph:
        return [[]]
    lines: list[list[str]] = []
    current: list[str] = []
    for word in _split_words(paragraph):
        candidate = "".join(current) + word
        if current and measure(candidate.rstrip(), fontname, font_size) > max_width:
            lines.append(current)
            current = []
        if measure(word.rstrip(), fontname, font_size) > max_width and not current:
            pieces = _break_long_word(word.rstrip(), fontname, font_size, max_width)
            lines.extend([[piece] for piece in pieces[:-1]])
            current = [pieces[-1]]
            continue
        current.append(word)
    lines.append(current)
    return lines


def layout_text(
    text: str,
    rect: Rect,
    *,
    fontname: str = "helv",
    font_size: float = 12.0,
    align: Align = Align.LEFT,
    line_spacing: float = 1.2,
) -> TextLayout:
    """Lay *text* out inside *rect* (base page space, y downwards)."""
    ascender, descender = font_metrics(fontname)
    line_height = max(font_size * line_spacing, font_size * 0.5)
    max_width = max(1.0, rect.width)

    layout = TextLayout(
        font_size=font_size,
        line_height=line_height,
        ascender=ascender,
        descender=descender,
    )
    if not text:
        layout.content_height = 0.0
        return layout

    paragraphs = text.split("\n")
    wrapped: list[tuple[list[str], bool]] = []
    for paragraph in paragraphs:
        para_lines = _wrap_paragraph(paragraph, fontname, font_size, max_width)
        for line_index, words in enumerate(para_lines):
            is_last_of_paragraph = line_index == len(para_lines) - 1
            wrapped.append((words, is_last_of_paragraph))

    top = rect.y0
    for index, (words, last_of_paragraph) in enumerate(wrapped):
        baseline = top + ascender * font_size + index * line_height
        content = "".join(words).rstrip()
        width = measure(content, fontname, font_size)

        if align is Align.JUSTIFY and not last_of_paragraph and len(words) > 1:
            segments = _justify(words, rect.x0, max_width, fontname, font_size)
            layout.lines.append(TextLine(tuple(segments), baseline, max_width))
            continue

        if align is Align.CENTER:
            x = rect.x0 + (max_width - width) / 2.0
        elif align is Align.RIGHT:
            x = rect.x0 + max_width - width
        else:
            x = rect.x0
        layout.lines.append(TextLine((TextSegment(content, x, width),), baseline, width))

    layout.content_height = (len(wrapped) - 1) * line_height + font_size * (ascender - descender)
    layout.overflows = layout.content_height > rect.height + 0.5
    return layout


def _justify(
    words: Sequence[str], x0: float, max_width: float, fontname: str, font_size: float
) -> list[TextSegment]:
    stripped = [w.rstrip() for w in words]
    stripped = [w for w in stripped if w]
    if len(stripped) < 2:
        text = "".join(stripped)
        return [TextSegment(text, x0, measure(text, fontname, font_size))]
    widths = [measure(w, fontname, font_size) for w in stripped]
    gap = (max_width - sum(widths)) / (len(stripped) - 1)
    segments: list[TextSegment] = []
    cursor = x0
    for word, width in zip(stripped, widths, strict=True):
        segments.append(TextSegment(word, cursor, width))
        cursor += width + gap
    return segments
