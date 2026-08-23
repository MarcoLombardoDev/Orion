# Orion — PDF Editor for Desktop
# Copyright (C) 2026 Marco Lombardo
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# Distributed WITHOUT ANY WARRANTY; see LICENSE for the full terms.
# A commercial licence, without the AGPL's obligations, is available for use
# in proprietary or closed-source products — see COMMERCIAL-LICENSE.md.

"""Conversions between Orion's base page space and PDF content space.

**This is the only module allowed to know how the two spaces differ.**
Everything above it works in base page space and never thinks about /Rotate,
and everything below it — the reportlab canvas, pypdf's annotation
dictionaries, pdfium's text rectangles — is handed coordinates that are
already correct.

Two spaces, and they disagree about almost everything:

*Base page space* is the source page **as displayed**: the file's own
``/Rotate`` already applied, origin at the top-left, y increasing downwards,
measured in points. It is what the canvas draws and what every object in the
document model stores. Angles are degrees, clockwise-positive, matching
``QGraphicsItem.setRotation``.

*PDF content space* is the page's **unrotated** mediabox: origin at the
bottom-left, y increasing upwards. Rotation is counter-clockwise-positive.
This is what actually gets written to the file.

So the map between them reverses the y axis (and, for quarter-turn pages,
swaps the axes outright). Reversing an axis reverses the sense of rotation,
which is why every angle changes sign on the way down.

Deriving the four cases is easier than it looks. Write the unrotated page in
top-left coordinates, ``(ux, uy)``, and note that displaying it means rotating
that image clockwise by ``/Rotate``. Rotating an image 90 degrees clockwise
sends its top-left corner to its top-right, so ``bx = H - uy`` and
``by = ux``; invert that, then convert ``uy`` to a y-up ``py = H - uy``. Doing
the same for the other three turns gives the table in :func:`to_pdf_point`.
Every one of them is checked against a rendered pixel in
``tests/test_coordinates.py`` rather than trusted.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from orion.utils.geometry import Point, Rect, Size

__all__ = [
    "PageGeometry",
    "to_pdf_rect",
    "to_pdf_point",
    "from_pdf_rect",
    "from_pdf_point",
    "content_angle",
    "quad_points",
    "polyline_to_pdf",
    "rotated_pivot",
]


@dataclass(frozen=True, slots=True)
class PageGeometry:
    """Everything the conversions need to know about one page.

    ``width`` and ``height`` are the **unrotated** mediabox, in points;
    ``rotation`` is the page's own ``/Rotate``, normalised to one of
    0, 90, 180, 270.

    This replaces passing a live PDF page object around. A page object ties
    the conversions to whichever library opened it, and they were then only
    testable by opening a file; a value object can be constructed in a test in
    one line, which is why every case below actually has a test.
    """

    width: float
    height: float
    rotation: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "width", float(self.width))
        object.__setattr__(self, "height", float(self.height))
        object.__setattr__(self, "rotation", int(self.rotation) % 360 // 90 * 90)

    @property
    def display_size(self) -> Size:
        """The page as the user sees it — axes swapped on a quarter turn."""
        if self.rotation in (90, 270):
            return Size(self.height, self.width)
        return Size(self.width, self.height)


def to_pdf_point(geometry: PageGeometry, point: Point) -> tuple[float, float]:
    """Base page space -> PDF content space."""
    x, y = point.x, point.y
    width, height = geometry.width, geometry.height
    if geometry.rotation == 90:
        return (y, x)
    if geometry.rotation == 180:
        return (width - x, y)
    if geometry.rotation == 270:
        return (width - y, height - x)
    return (x, height - y)


def from_pdf_point(geometry: PageGeometry, point: Sequence[float]) -> Point:
    """PDF content space -> base page space, the inverse of the above."""
    x, y = float(point[0]), float(point[1])
    width, height = geometry.width, geometry.height
    if geometry.rotation == 90:
        return Point(y, x)
    if geometry.rotation == 180:
        return Point(width - x, y)
    if geometry.rotation == 270:
        return Point(height - y, width - x)
    return Point(x, height - y)


def to_pdf_rect(geometry: PageGeometry, rect: Rect) -> tuple[float, float, float, float]:
    """Base page space -> PDF content space, as ``(x0, y0, x1, y1)``.

    Returned normalised, with ``x0 <= x1`` and ``y0 <= y1``: the corners swap
    roles under a y flip or an axis swap, and every consumer downstream — a
    /Rect entry, a reportlab rectangle — wants them the right way round. On a
    quarter-turn page this correctly transposes the box, so a 100x50 rectangle
    in base space becomes 50x100 in content space.
    """
    first = to_pdf_point(geometry, Point(rect.x0, rect.y0))
    second = to_pdf_point(geometry, Point(rect.x1, rect.y1))
    return (
        min(first[0], second[0]),
        min(first[1], second[1]),
        max(first[0], second[0]),
        max(first[1], second[1]),
    )


def from_pdf_rect(geometry: PageGeometry, rect: Sequence[float]) -> Rect:
    """PDF content space -> base page space, normalised the same way.

    Used for text search hits and word boxes, which pdfium reports in the
    unrotated mediabox regardless of how the page is displayed.
    """
    first = from_pdf_point(geometry, (rect[0], rect[1]))
    second = from_pdf_point(geometry, (rect[2], rect[3]))
    return Rect(
        min(first.x, second.x),
        min(first.y, second.y),
        max(first.x, second.x),
        max(first.y, second.y),
    )


def content_angle(orion_angle: float, page_rotation: int = 0) -> float:
    """Orion's clockwise base-space angle -> counter-clockwise content angle.

    Both terms are real, and getting either wrong is invisible until something
    is rotated on a rotated page.

    The sign flips because the base-to-content map reverses an axis, and a
    reflection turns a rotation into its inverse. The ``page_rotation`` term is
    there because the map does more than flip on a quarter turn: it swaps the
    axes, so a horizontal object in base space is a *vertical* one in content
    space. Taking the base-space direction ``(cos t, sin t)``, mapping it, and
    reading its angle back off gives ``page_rotation - t`` for all four turns.
    """
    return page_rotation - orion_angle


def quad_points(geometry: PageGeometry, rects: Iterable[Rect]) -> list[float]:
    """Base-space rectangles -> a flat ``/QuadPoints`` array.

    The PDF specification orders the corners of each quad upper-left,
    upper-right, lower-left, lower-right — which is *not* the order the corners
    come out of a normalised rectangle, and not the winding order anyone
    guesses first. Readers disagree about how much they tolerate; Acrobat
    renders a wrongly wound quad as nothing at all.
    """
    corners: list[float] = []
    for rect in rects:
        x0, y0, x1, y1 = to_pdf_rect(geometry, rect)
        corners.extend((x0, y1, x1, y1, x0, y0, x1, y0))
    return corners


def polyline_to_pdf(
    geometry: PageGeometry, points: Sequence[Point]
) -> list[float]:
    """An ink stroke, base space -> the flat ``/InkList`` entry for one stroke."""
    flat: list[float] = []
    for point in points:
        x, y = to_pdf_point(geometry, point)
        flat.extend((x, y))
    return flat


def rotated_pivot(geometry: PageGeometry, rect: Rect) -> tuple[float, float]:
    """The content-space point an object rotates about: its own centre."""
    return to_pdf_point(geometry, rect.center)
