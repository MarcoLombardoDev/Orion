# Orion — PDF Editor for Desktop
# Copyright (C) 2026 Marco Lombardo
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# Distributed WITHOUT ANY WARRANTY; see LICENSE for the full terms.
# A commercial licence, without the AGPL's obligations, is available for use
# in proprietary or closed-source products — see COMMERCIAL-LICENSE.md.

"""Putting the same thing on many pages: watermarks and page numbers.

Both produce ordinary :class:`~orion.document.objects.TextObject`\\ s, one per
page, and that is the whole design. A stamp applied at save time would be
invisible until the file was written, unmovable when it landed in the wrong
place, and would need its own code in the writer; a text object is already
drawn on the canvas, already selectable, already undoable, already saved as
real searchable text, and already adjustable afterwards — a page number that
collides with a footer can simply be dragged.

It lives beside the writer rather than with the model because sizing a
watermark needs the font's real metrics, and those are the PDF layer's to
know. Nothing here imports Qt or touches a file: it computes where the text
goes and what it says, and the caller turns that into commands.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum

from orion.document.objects import Align, Color, TextObject
from orion.document.page import Page
from orion.pdf.fonts import FontRequest
from orion.pdf.text_layout import measure
from orion.utils.geometry import Rect

__all__ = [
    "Corner",
    "WatermarkSpec",
    "PageNumberSpec",
    "watermark_for",
    "fitted_font_size",
    "page_number_for",
    "format_page_number",
]

#: Distance from the page edge for a page number, in points.
MARGIN = 28.0


class Corner(str, Enum):
    """Where on the page a page number sits."""

    TOP_LEFT = "top_left"
    TOP_CENTRE = "top_centre"
    TOP_RIGHT = "top_right"
    BOTTOM_LEFT = "bottom_left"
    BOTTOM_CENTRE = "bottom_centre"
    BOTTOM_RIGHT = "bottom_right"

    @property
    def at_top(self) -> bool:
        return self.value.startswith("top")

    @property
    def align(self) -> Align:
        if self.value.endswith("left"):
            return Align.LEFT
        if self.value.endswith("right"):
            return Align.RIGHT
        return Align.CENTER

    @property
    def label(self) -> str:
        return self.value.replace("_", " ").capitalize()


@dataclass(frozen=True, slots=True)
class WatermarkSpec:
    """A diagonal word across the middle of a page."""

    text: str = "DRAFT"
    font_family: str = "Helvetica"
    font_size: float = 60.0
    color: Color = (0.5, 0.5, 0.5)
    opacity: float = 0.25
    #: Degrees, clockwise-positive like every other angle in the model. The
    #: default runs bottom-left to top-right, which is the way a watermark is
    #: read and the way it fits a portrait page.
    rotation: float = -45.0


@dataclass(frozen=True, slots=True)
class PageNumberSpec:
    """Numbers along an edge, on some or all of the pages."""

    #: ``{n}`` is the page's number and ``{total}`` the count. Anything else
    #: is kept, so "Page {n} of {total}" and "- {n} -" both work.
    template: str = "{n}"
    corner: Corner = Corner.BOTTOM_CENTRE
    font_family: str = "Helvetica"
    font_size: float = 10.0
    color: Color = (0.0, 0.0, 0.0)
    #: What the first stamped page is called. A cover page that should not be
    #: numbered is left out of the range instead, so this stays a pure offset.
    start_at: int = 1


def format_page_number(spec: PageNumberSpec, position: int, total: int) -> str:
    """Fill in the template for the *position*-th stamped page (0-based).

    Unknown placeholders are left alone rather than raising: the template comes
    from a text field, and a stray brace should put a brace on the page, not
    stop the operation.
    """
    number = spec.start_at + position
    try:
        return spec.template.format(n=number, total=total)
    except (KeyError, IndexError, ValueError):
        return spec.template


def fitted_font_size(spec: WatermarkSpec, page: Page) -> float:
    """The largest size at or below the asked-for one that stays on the page.

    A watermark that runs off the edge, or breaks onto a second line, reads as
    a mistake rather than as a mark — and "CONFIDENTIAL" at sixty points is
    wider than a portrait page, so the defaults would do exactly that.

    Turning it buys room, which is why the diagonal is not only a convention:
    a line of length L at angle t spans ``L·cos t`` across the page and
    ``L·sin t`` down it, so it fits while both are inside. Forty-five degrees
    is the angle with the most room on a rectangle.
    """
    if not spec.text:
        return spec.font_size
    size = page.base_size
    width = measure(spec.text, FontRequest(spec.font_family), spec.font_size)
    if width <= 0.0:
        return spec.font_size

    radians = math.radians(spec.rotation)
    across, down = abs(math.cos(radians)), abs(math.sin(radians))
    room = min(
        size.width / across if across > 1e-6 else math.inf,
        size.height / down if down > 1e-6 else math.inf,
    ) * 0.92  # a margin, so it never touches the edges
    if width <= room:
        return spec.font_size
    return max(6.0, spec.font_size * room / width)


def watermark_for(page: Page, spec: WatermarkSpec) -> TextObject:
    """The watermark object for one page, centred and turned.

    The box is measured to the text rather than given the page's width, and
    the two reasons show up as the same symptom. Text wraps inside its box, so
    a long word in a page-wide box breaks in half; and the box turns about its
    own centre, so a box wider than the words would swing them off to one
    side. Fitting the box to the line puts the pivot in the middle of the
    words, which is where it looks right.

    It is one line tall for a related reason: text is laid out from the top of
    its box downwards, so an oversized box would sit the words above centre.
    """
    font_size = fitted_font_size(spec, page)
    size = page.base_size
    # A whisker wider than the words. The layout wraps at the box edge, so a
    # box measured to exactly the text breaks the last letter onto its own
    # line as soon as rounding goes the wrong way — which it did.
    width = max(measure(spec.text, FontRequest(spec.font_family), font_size) + 2.0, 1.0)
    height = font_size * 1.4
    return TextObject(
        rect=Rect.from_xywh(
            (size.width - width) / 2.0,
            (size.height - height) / 2.0,
            width,
            height,
        ),
        text=spec.text,
        font_family=spec.font_family,
        font_size=font_size,
        color=spec.color,
        align=Align.CENTER,
        opacity=spec.opacity,
        rotation=spec.rotation,
    )


def page_number_for(page: Page, spec: PageNumberSpec, position: int, total: int) -> TextObject:
    """The page-number object for one page."""
    size = page.base_size
    height = spec.font_size * 1.6
    top = MARGIN if spec.corner.at_top else size.height - MARGIN - height
    return TextObject(
        rect=Rect.from_xywh(MARGIN, top, max(size.width - 2 * MARGIN, 1.0), height),
        text=format_page_number(spec, position, total),
        font_family=spec.font_family,
        font_size=spec.font_size,
        color=spec.color,
        align=spec.corner.align,
    )


def page_numbers_for(
    pages: Sequence[Page], spec: PageNumberSpec, total: int | None = None
) -> list[TextObject]:
    """One numbered object per page, in the order given."""
    count = len(pages) if total is None else total
    return [
        page_number_for(page, spec, position, count)
        for position, page in enumerate(pages)
    ]
