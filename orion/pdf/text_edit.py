# Orion — PDF Editor for Desktop
# Copyright (C) 2026 Marco Lombardo
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# Distributed WITHOUT ANY WARRANTY; see LICENSE for the full terms.
# A commercial licence, without the AGPL's obligations, is available for use
# in proprietary or closed-source products — see COMMERCIAL-LICENSE.md.

"""Reading the content that is already on a page, so it can be changed.

Mostly the text — finding the line under the cursor so it can be rewritten —
and, for redaction, any drawing operation at all that falls inside an area.

A PDF has no notion of an editable paragraph. What it has is a content stream
of drawing operations, some of which put glyphs at coordinates, and "the line
you clicked" is a group of those that happen to share a baseline. This module
finds that group, reads back everything needed to redraw it — the string, the
size, the colour, where the baseline sits — and says which content objects it
came from, so the writer can take them out.

**Replacing rather than editing in place.** pdfium does have an in-place
setter, ``FPDFText_SetText``, and it does work — on embedded subsets too,
extending the font with glyphs the subset never had, accents included. It is
not used, and the reason is what it cannot do rather than what it cannot
draw. It sets a string on one text object: it has nothing to say about a line
that is three objects, about the text being longer than the space it had,
about a different size or colour, or about wrapping. All of that already
exists for an Orion text object, along with the properties panel, undo, and a
canvas that shows what the file will contain. Replacing the line with one of
those gets the whole editor; setting the string in place would get a second,
poorer text path beside it.

The cost is real and the user is told rather than left to find out: the
replacement is drawn in one of Orion's fonts, so a line whose original face is
not installed here comes back looking different. An in-place fast path for the
narrow case — one text object, only the string changed — would avoid that, and
is the obvious thing to add if it turns out to matter.

**On pdfium handles.** Every function below takes the page handle from the
caller and never opens its own. A ``PdfPage`` wrapper frees its page when it is
collected, so asking a document for the same page twice and letting one copy go
is a double free — a segmentation fault at some later, unrelated moment,
usually when the document is closed. :class:`~orion.pdf.reader.OpenedPdf` holds
one handle per page for exactly this reason.
"""

from __future__ import annotations

import ctypes
import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass, field

import pypdfium2.raw as pdfium_raw

from orion.pdf.coordinates import PageGeometry, from_pdf_point, from_pdf_rect
from orion.pdf.fonts import BASE14_MAP, FontRequest, available_families, resolve
from orion.utils.geometry import Point, Rect

log = logging.getLogger(__name__)

__all__ = [
    "SourceTextRun",
    "SourceTextLine",
    "read_text_lines",
    "line_at",
    "content_objects_in",
]

#: Subset prefixes look like ``ABCDEF+`` and say nothing about the typeface.
_SUBSET_PREFIX = re.compile(r"^[A-Z]{6}\+")

#: Flags in a PDF font descriptor that survive into pdfium's report.
_FLAG_FIXED_PITCH = 1 << 0
_FLAG_SERIF = 1 << 1
_FLAG_ITALIC = 1 << 6

#: Two runs belong to the same line when their vertical spans overlap by at
#: least this much of the shorter one. Generous, because a line can mix sizes.
_LINE_OVERLAP = 0.5


@dataclass(frozen=True, slots=True)
class SourceTextRun:
    """One text-drawing object in the page's content stream."""

    index: int
    text: str
    #: Ink bounds, in base page space.
    rect: Rect
    #: Where the glyphs sit on, in base page space. The rect is the ink; this
    #: is what the replacement has to line up with.
    baseline: Point
    font_size: float
    color: tuple[float, float, float]
    family: str
    bold: bool
    italic: bool


@dataclass(slots=True)
class SourceTextLine:
    """The runs that share a baseline, and what it takes to redraw them."""

    runs: list[SourceTextRun] = field(default_factory=list)

    @property
    def indices(self) -> tuple[int, ...]:
        """The content objects this line is made of, in page order."""
        return tuple(sorted(run.index for run in self.runs))

    @property
    def text(self) -> str:
        return "".join(run.text for run in self._ordered)

    @property
    def _ordered(self) -> list[SourceTextRun]:
        return sorted(self.runs, key=lambda run: run.rect.x0)

    @property
    def rect(self) -> Rect:
        bounds = self.runs[0].rect
        for run in self.runs[1:]:
            bounds = bounds.united(run.rect)
        return bounds

    @property
    def baseline(self) -> float:
        """The lowest baseline in the line, which is the one to sit on."""
        return max(run.baseline.y for run in self.runs)

    @property
    def font_size(self) -> float:
        """The largest size on the line: the one that sets its height."""
        return max(run.font_size for run in self.runs)

    @property
    def hit_box(self) -> Rect:
        """The line as a reader sees it, which is what a click has to find.

        The ink alone is too small a target and, worse, the wrong shape: a
        line with no descenders stops at the baseline, so clicking just under
        the words — where the line plainly still is — misses it. On an 18pt
        line the ink is under 14pt tall, and at a normal zoom that is a few
        pixels of slack in each direction.

        The box is the one the replacement will occupy, from the font's own
        ascender to its descender about the baseline, united with the ink so a
        tall glyph is never left outside. Bands of neighbouring lines can
        overlap slightly at close leading; :func:`line_at` breaks the tie by
        baseline, which is the line the eye would pick too.
        """
        run = self.dominant_run
        font = resolve(FontRequest(run.family, run.bold, run.italic))
        size = self.font_size
        base = self.baseline
        return self.rect.united(
            Rect(
                self.rect.x0,
                base - font.ascender * size,
                self.rect.x1,
                base - font.descender * size,
            )
        )

    @property
    def dominant_run(self) -> SourceTextRun:
        """The run whose colour and face the replacement takes.

        A line is often several runs and they do not have to agree: "Amount:"
        in bold red followed by a figure in plain black is one line and two
        styles, and the replacement can only have one. The run with the most
        characters is the one that decides, because it is the one most of the
        line already looks like. Ties go to the leftmost.

        Losing the second style is the honest cost of replacing a line rather
        than editing it in place, and the same trade every simple PDF editor
        makes. A user who needs both can replace the two halves separately.
        """
        return max(self._ordered, key=lambda run: len(run.text))


# --------------------------------------------------------------------------
# ctypes plumbing
# --------------------------------------------------------------------------
def _object_text(obj, textpage) -> str:
    size = pdfium_raw.FPDFTextObj_GetText(obj, textpage, None, 0)
    if size <= 2:  # just the terminator
        return ""
    buffer = ctypes.create_string_buffer(size)
    pdfium_raw.FPDFTextObj_GetText(
        obj, textpage, ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ushort)), size
    )
    return buffer.raw[: size - 2].decode("utf-16-le", errors="replace")


def _object_bounds(obj) -> tuple[float, float, float, float]:
    left, bottom, right, top = (ctypes.c_float() for _ in range(4))
    pdfium_raw.FPDFPageObj_GetBounds(
        obj, *(ctypes.byref(value) for value in (left, bottom, right, top))
    )
    return left.value, bottom.value, right.value, top.value


def _object_origin(obj) -> tuple[float, float]:
    """The text matrix's translation, which is the baseline start."""
    matrix = pdfium_raw.FS_MATRIX()
    if not pdfium_raw.FPDFPageObj_GetMatrix(obj, ctypes.byref(matrix)):
        return 0.0, 0.0
    return matrix.e, matrix.f


def _object_colour(obj) -> tuple[float, float, float]:
    channels = [ctypes.c_uint() for _ in range(4)]
    if not pdfium_raw.FPDFPageObj_GetFillColor(
        obj, *(ctypes.byref(value) for value in channels)
    ):
        return (0.0, 0.0, 0.0)
    red, green, blue, _alpha = (value.value for value in channels)
    return (red / 255.0, green / 255.0, blue / 255.0)


def _object_font_size(obj) -> float:
    size = ctypes.c_float()
    if not pdfium_raw.FPDFTextObj_GetFontSize(obj, ctypes.byref(size)):
        return 12.0
    return abs(size.value) or 12.0


def _object_font(obj) -> tuple[str, bool, bool]:
    """``(family, bold, italic)`` for one text object, in Orion's terms."""
    font = pdfium_raw.FPDFTextObj_GetFont(obj)
    if not font:
        return ("Helvetica", False, False)

    buffer = ctypes.create_string_buffer(128)
    length = pdfium_raw.FPDFFont_GetBaseFontName(font, buffer, 128)
    raw_name = buffer.value.decode("latin-1") if length else ""
    flags = int(pdfium_raw.FPDFFont_GetFlags(font) or 0)
    weight = int(pdfium_raw.FPDFFont_GetWeight(font) or 0)
    angle = ctypes.c_int()
    if not pdfium_raw.FPDFFont_GetItalicAngle(font, ctypes.byref(angle)):
        angle.value = 0
    return _match_family(raw_name, flags, weight, float(angle.value))


def _match_family(
    raw_name: str, flags: int, weight: int, italic_angle: float
) -> tuple[str, bool, bool]:
    """A PDF base font name -> a family Orion can actually draw with.

    The name in the file is a PostScript one — ``ABCDEF+LiberationSerif-Bold``
    — carrying a subset prefix that means nothing and a style suffix that means
    a great deal. Strip the first, read the second, and look for what is left
    among the fonts installed here. When there is no match the choice falls
    back to the descriptor flags, which is the whole reason they exist: serif,
    fixed pitch, or neither.
    """
    name = _SUBSET_PREFIX.sub("", raw_name)
    style = ""
    for separator in ("-", ","):
        if separator in name:
            name, _, style = name.partition(separator)
            break

    lowered = style.lower()
    bold = "bold" in lowered or "black" in lowered or "heavy" in lowered or weight >= 600
    italic = (
        "italic" in lowered
        or "oblique" in lowered
        or bool(flags & _FLAG_ITALIC)
        or italic_angle < -1.0
    )

    wanted = name.replace(" ", "").lower()
    for family in available_families():
        if family.replace(" ", "").lower() == wanted:
            return (family, bold, italic)

    if flags & _FLAG_FIXED_PITCH:
        return ("Courier", bold, italic)
    if flags & _FLAG_SERIF:
        return ("Times", bold, italic)
    return ("Helvetica", bold, italic)


# --------------------------------------------------------------------------
# Reading a page
# --------------------------------------------------------------------------
def read_text_lines(page_handle, textpage_handle, geometry: PageGeometry) -> list[SourceTextLine]:
    """Every line of the page's own text, in base page space.

    *page_handle* and *textpage_handle* are raw pdfium handles owned by the
    caller — see the note about handles in the module docstring.
    """
    runs: list[SourceTextRun] = []
    count = int(pdfium_raw.FPDFPage_CountObjects(page_handle))
    for index in range(count):
        obj = pdfium_raw.FPDFPage_GetObject(page_handle, index)
        if not obj or pdfium_raw.FPDFPageObj_GetType(obj) != pdfium_raw.FPDF_PAGEOBJ_TEXT:
            continue
        text = _object_text(obj, textpage_handle)
        if not text.strip():
            continue
        left, bottom, right, top = _object_bounds(obj)
        family, bold, italic = _object_font(obj)
        origin_x, origin_y = _object_origin(obj)
        runs.append(
            SourceTextRun(
                index=index,
                text=text,
                rect=from_pdf_rect(geometry, (left, bottom, right, top)),
                baseline=from_pdf_point(geometry, (origin_x, origin_y)),
                font_size=_object_font_size(obj),
                color=_object_colour(obj),
                family=family,
                bold=bold,
                italic=italic,
            )
        )
    return _group_into_lines(runs)


def content_objects_in(page_handle, geometry: PageGeometry, area: Rect) -> tuple[int, ...]:
    """Every drawing operation on the page that *touches* ``area``.

    Used by redaction, and the choice of "touches" rather than "is inside" is
    the whole of what makes it redaction. A run of text that crosses the edge
    of the box has some of its glyphs under the box and some outside; keeping
    it would leave the covered words in the file, still selectable, still
    found by search, with a black rectangle painted over them — which is the
    failure this feature exists to prevent, and an invisible one.

    So anything the box touches goes, and the cost is visible instead:
    redacting one word can take the rest of its run with it. Over-removal is
    something the user can see and undo. Under-removal is something nobody
    sees until it matters.
    """
    covered: list[int] = []
    count = int(pdfium_raw.FPDFPage_CountObjects(page_handle))
    for index in range(count):
        obj = pdfium_raw.FPDFPage_GetObject(page_handle, index)
        if not obj:
            continue
        left, bottom, right, top = _object_bounds(obj)
        bounds = from_pdf_rect(geometry, (left, bottom, right, top))
        if bounds.intersects(area):
            covered.append(index)
    return tuple(covered)


def _group_into_lines(runs: list[SourceTextRun]) -> list[SourceTextLine]:
    """Put runs that share a baseline together.

    A line of a real document is rarely one drawing operation: a change of
    weight, of colour, or just the writer's whim splits it, and a form or an
    invoice can put every field in its own. Grouping by vertical overlap is
    what makes "click the line" mean the line rather than the fragment under
    the cursor.

    Overlap rather than an equal baseline, because a superscript or an inline
    logo sits on its own and still belongs to the sentence around it.
    """
    lines: list[SourceTextLine] = []
    for run in sorted(runs, key=lambda item: (item.rect.y0, item.rect.x0)):
        for line in lines:
            if _shares_a_line(line.rect, run.rect):
                line.runs.append(run)
                break
        else:
            lines.append(SourceTextLine([run]))
    return lines


def _shares_a_line(first: Rect, second: Rect) -> bool:
    overlap = min(first.y1, second.y1) - max(first.y0, second.y0)
    shorter = min(first.height, second.height)
    return shorter > 0 and overlap >= shorter * _LINE_OVERLAP


def _bands(lines: Sequence[SourceTextLine]) -> list[tuple[SourceTextLine, float, float]]:
    """``(line, top, bottom)`` for each line, covering the whole row it owns.

    The em box is the floor, and each band then reaches toward its neighbours
    as far as the midpoint between the two baselines — which is what a reader
    means by "this line" and includes the leading that the glyphs do not. The
    bands cannot overlap, because two of them stop at the same midpoint, and
    they cannot shrink below the em box either, so the first and last lines
    keep theirs.

    A two-column page interleaves the columns by baseline, which makes some
    midpoints fall inside an em box; taking the wider of the two is why that
    costs nothing, and the horizontal test in :func:`line_at` is what tells
    the columns apart.
    """
    ordered = sorted(lines, key=lambda line: line.baseline)
    bands: list[tuple[SourceTextLine, float, float]] = []
    for index, line in enumerate(ordered):
        box = line.hit_box
        top, bottom = box.y0, box.y1
        if index:
            top = min(top, (ordered[index - 1].baseline + line.baseline) / 2.0)
        if index + 1 < len(ordered):
            bottom = max(bottom, (ordered[index + 1].baseline + line.baseline) / 2.0)
        bands.append((line, top, bottom))
    return bands


def line_at(lines: Sequence[SourceTextLine], point: Point) -> SourceTextLine | None:
    """The line under *point*, or the nearest one on the same row.

    Three things in order, because each is a way the obvious version feels
    unreliable. The row is the band from :func:`_bands` rather than the ink,
    so a click in the space between the lines belongs to one of them instead
    of to nothing — matching the ink was the reported "I can't edit the text",
    since on an 18pt line it is under 14pt tall and, without descenders, stops
    dead at the baseline. A click past the end of the text counts, because the
    line is plainly still there. And where bands still overlap, the nearest
    baseline wins, which is the line the eye was pointing at.
    """
    on_the_row = [
        (line, top, bottom)
        for line, top, bottom in _bands(lines)
        if top <= point.y <= bottom
    ]
    if not on_the_row:
        return None
    inside = [
        entry
        for entry in on_the_row
        if entry[0].hit_box.x0 <= point.x <= entry[0].hit_box.x1
    ]
    candidates = [entry[0] for entry in (inside or on_the_row)]
    if len(candidates) == 1:
        return candidates[0]
    return min(
        candidates,
        key=lambda line: (
            abs(point.y - line.baseline),
            min(abs(point.x - line.rect.x0), abs(point.x - line.rect.x1)),
        ),
    )


def is_editable_family(family: str) -> bool:
    """Whether Orion can redraw text in *family* without substituting."""
    return family in BASE14_MAP or family in available_families()
