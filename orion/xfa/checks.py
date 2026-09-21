# Orion — PDF Editor for Desktop
# Copyright (C) 2026 Marco Lombardo
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# Distributed WITHOUT ANY WARRANTY; see LICENSE for the full terms.
# A commercial licence, without the AGPL's obligations, is available for use
# in proprietary or closed-source products — see COMMERCIAL-LICENSE.md.

"""Looking at the laid-out form before it is drawn, and saying what is wrong.

The converter cannot see its own output, and the ways an XFA layout goes wrong
are visual: two fields on top of each other, a label wider than the space
reserved for it, something pushed off the edge of the page. Each of those was
found once by opening the result and looking at it, which does not scale and
does not run in a test.

So the layout is measured here instead. Nothing is corrected — a converter
that quietly moved a field would be inventing a document nobody designed — but
everything found is counted and said out loud, so the summary reports a form
that came out overlapping rather than announcing a clean conversion.
"""

from __future__ import annotations

from dataclasses import dataclass

from orion.xfa.layout import LaidOutForm, PlacedPage, rect_to_pdf
from orion.xfa.model import XfaFont, XfaRect

__all__ = ["LayoutIssue", "check_layout"]

#: Two boxes touching at the edge is normal — a table's cells do it by
#: design. This much of the smaller one covered is not.
OVERLAP_FRACTION = 0.35

#: A whisker past the page edge is rounding; more is a misplacement.
EDGE_TOLERANCE = 2.0


@dataclass(frozen=True, slots=True)
class LayoutIssue:
    """One thing measured, in words the report can pass straight on."""

    #: ``overlap``, ``off_page`` or ``overflow``.
    kind: str
    message: str
    subject: str = ""


def check_layout(form: LaidOutForm) -> list[LayoutIssue]:
    """Every problem the finished layout can be caught at."""
    issues: list[LayoutIssue] = []
    for index, page in enumerate(form.pages, start=1):
        issues.extend(_overlapping_fields(page, index))
        issues.extend(_off_page(page, index))
        issues.extend(_overflowing_text(page, index))
    return issues


def _area(rect: XfaRect) -> float:
    return max(rect.width, 0.0) * max(rect.height, 0.0)


def _intersection(a: XfaRect, b: XfaRect) -> float:
    left = max(a.x, b.x)
    right = min(a.x + a.width, b.x + b.width)
    top = max(a.y, b.y)
    bottom = min(a.y + a.height, b.y + b.height)
    return max(right - left, 0.0) * max(bottom - top, 0.0)


def _overlapping_fields(page: PlacedPage, number: int) -> list[LayoutIssue]:
    """Two fields over one another: the shape a collapsed layout takes.

    Only fields are compared. Draws overlap on purpose all the time — a
    heading sits on its coloured band — whereas two fields in the same place
    means one of them cannot be clicked, and is how a misread flow announces
    itself.
    """
    issues: list[LayoutIssue] = []
    live = [f for f in page.fields if _area(f.rect) > 0]
    for first in range(len(live)):
        for second in range(first + 1, len(live)):
            one, other = live[first], live[second]
            shared = _intersection(one.rect, other.rect)
            if not shared:
                continue
            smaller = min(_area(one.rect), _area(other.rect))
            if smaller and shared / smaller >= OVERLAP_FRACTION:
                issues.append(
                    LayoutIssue(
                        "overlap",
                        f"This field sits on top of '{other.name or other.som}' "
                        f"on page {number}, so one of the two cannot be used.",
                        one.som or one.name,
                    )
                )
    return issues


def _off_page(page: PlacedPage, number: int) -> list[LayoutIssue]:
    """Anything placed outside the paper it is supposed to be on."""
    issues: list[LayoutIssue] = []
    for item in [*page.fields, *page.buttons]:
        rect = item.rect
        if _area(rect) <= 0:
            continue
        if (
            rect.x < -EDGE_TOLERANCE
            or rect.y < -EDGE_TOLERANCE
            or rect.x + rect.width > page.width + EDGE_TOLERANCE
            or rect.y + rect.height > page.height + EDGE_TOLERANCE
        ):
            issues.append(
                LayoutIssue(
                    "off_page",
                    f"This field falls outside page {number} and may not be "
                    "reachable.",
                    getattr(item, "som", "") or getattr(item, "name", ""),
                )
            )
    return issues


def _overflowing_text(page: PlacedPage, number: int) -> list[LayoutIssue]:
    """Text that needs more room than its box has, and will be cut off."""
    issues: list[LayoutIssue] = []
    for drawn in page.draws:
        if drawn.kind != "text" or not drawn.text:
            continue
        needed = _text_height(drawn.text, drawn.rect.width, drawn.font)
        if needed > drawn.rect.height + 1.0 and drawn.rect.height > 0:
            issues.append(
                LayoutIssue(
                    "overflow",
                    f"“{drawn.text[:40]}” needs more room than the form gave "
                    f"it on page {number} and will be cut short.",
                    drawn.text[:40],
                )
            )
    return issues


def _text_height(text: str, width: float, font: XfaFont) -> float:
    """How tall this text comes out once wrapped to *width*.

    Measured with the same font and the same line height the converter draws
    with, so the check agrees with the drawing rather than approximating it.
    """
    from reportlab.pdfbase.pdfmetrics import stringWidth

    from orion.xfa.converter import _font_name

    name = _font_name(font)
    limit = max(width, 1.0)
    lines = 1
    current = ""
    for word in text.split():
        candidate = f"{current} {word}".strip()
        if stringWidth(candidate, name, font.size) <= limit or not current:
            current = candidate
        else:
            lines += 1
            current = word
    return (lines - 1) * font.size * 1.2 + font.size


def rect_on_page(rect: XfaRect, page: PlacedPage) -> tuple[float, float, float, float]:
    """The same box in PDF coordinates — handy when reporting a position."""
    return rect_to_pdf(rect, page.height)
