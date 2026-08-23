# Orion — PDF Editor for Desktop
# Copyright (C) 2026 Marco Lombardo
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# Distributed WITHOUT ANY WARRANTY; see LICENSE for the full terms.
# A commercial licence, without the AGPL's obligations, is available for use
# in proprietary or closed-source products — see COMMERCIAL-LICENSE.md.

"""Conversions between Orion's base page space and PDF content space.

**This is the only module allowed to know about PyMuPDF's coordinate quirks.**
Two behaviours were verified experimentally against PyMuPDF 1.28 and are
re-verified by ``tests/test_coordinates.py`` on every test run:

1. PyMuPDF's content API (``draw_*``, ``insert_text``, ``insert_image``,
   ``add_*_annot``, ``search_for``) works in the **unrotated mediabox space**.
   It is *not* rotation aware — only ``page.rect`` and ``get_pixmap()`` are.
2. ``pymupdf.Matrix(a)`` rotates **counter-clockwise** on screen, whereas Orion
   (like ``QGraphicsItem.setRotation``) uses clockwise-positive angles.

Orion's *base page space* is the source page as displayed, i.e. with the source
file's own ``/Rotate`` already applied: origin top-left, y downwards, points.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import TYPE_CHECKING

from orion.utils.geometry import Point, Rect

if TYPE_CHECKING:  # pragma: no cover - typing only
    import pymupdf

__all__ = [
    "to_pdf_rect",
    "to_pdf_point",
    "from_pdf_rect",
    "from_pdf_point",
    "pdf_morph_angle",
    "pdf_rotate_steps",
    "content_angle",
    "quad_points",
    "polyline_to_pdf",
]


def to_pdf_point(page: pymupdf.Page, point: Point) -> pymupdf.Point:
    """Base page space -> PDF content (unrotated mediabox) space."""
    import pymupdf

    return pymupdf.Point(point.x, point.y) * page.derotation_matrix


def to_pdf_rect(page: pymupdf.Page, rect: Rect) -> pymupdf.Rect:
    """Base page space -> PDF content space, as an axis-aligned rectangle.

    For 90/270 page rotations this correctly transposes the rectangle: a
    100x50 box in base space becomes a 50x100 box in content space.
    """
    import pymupdf

    return (pymupdf.Rect(*rect.as_tuple()) * page.derotation_matrix).normalize()


def from_pdf_point(page: pymupdf.Page, point: pymupdf.Point) -> Point:
    """PDF content space -> base page space (used for text search results)."""
    mapped = point * page.rotation_matrix
    return Point(mapped.x, mapped.y)


def from_pdf_rect(page: pymupdf.Page, rect: pymupdf.Rect) -> Rect:
    """PDF content space -> base page space (used for text search results)."""
    mapped = (rect * page.rotation_matrix).normalize()
    return Rect(mapped.x0, mapped.y0, mapped.x1, mapped.y1)


def content_angle(orion_angle: float, page_rotation: int) -> float:
    """Orion clockwise angle in base space -> clockwise angle in content space.

    Only needed where the rotation cannot be expressed as a transform of an
    axis-aligned rectangle — i.e. ``insert_image``, which rotates the raster
    itself.  Derotating by the page's ``/Rotate`` turns the object by
    ``-page_rotation``, so the object's own angle absorbs that.
    """
    return orion_angle - page_rotation


def pdf_rotate_steps(orion_angle: float, page_rotation: int = 0) -> int:
    """``rotate=`` argument for ``insert_image`` (multiples of 90 only).

    ``insert_image`` rotates counter-clockwise, Orion clockwise.
    """
    return int(round(-content_angle(orion_angle, page_rotation) / 90.0)) * 90 % 360


def pdf_morph_angle(orion_angle: float) -> float:
    """Angle to hand to ``pymupdf.Matrix`` for a ``morph=`` transformation.

    Note there is **no page-rotation term** here.  :func:`to_pdf_rect` already
    maps the object's axis-aligned rectangle through the derotation matrix,
    which for the 90-degree steps a PDF page can carry *is* the page rotation;
    2-D rotations commute, so the object's own angle is simply negated for
    PyMuPDF's counter-clockwise convention.  Adding the page rotation again
    here would apply it twice — see ``tests/test_coordinates.py``.
    """
    return -orion_angle


def quad_points(page: pymupdf.Page, rects: Iterable[Rect]) -> list[pymupdf.Quad]:
    """Convert base-space rectangles into content-space quads for markup annots."""
    return [to_pdf_rect(page, rect).quad for rect in rects]


def polyline_to_pdf(page: pymupdf.Page, points: Sequence[Point]) -> list[tuple[float, float]]:
    """Convert an ink stroke from base space into content space.

    ``add_ink_annot`` insists on plain float pairs, not ``pymupdf.Point``.
    """
    return [tuple(to_pdf_point(page, p)) for p in points]
