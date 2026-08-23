# Orion — PDF Editor for Desktop
# Copyright (C) 2026 Marco Lombardo
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# Distributed WITHOUT ANY WARRANTY; see LICENSE for the full terms.
# A commercial licence, without the AGPL's obligations, is available for use
# in proprietary or closed-source products — see COMMERCIAL-LICENSE.md.

"""Geometry primitives and the *only* place coordinate maths is written.

Everything here is plain Python (no Qt, no PyMuPDF) and uses a **y-down,
top-left origin** convention, matching both Qt and PyMuPDF's page API.

Rotation angles are **degrees, clockwise-positive**, matching
``QGraphicsItem.setRotation``.  PyMuPDF uses the opposite sign; that single
conversion lives in :mod:`orion.pdf.coordinates` and nowhere else.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

__all__ = [
    "Point",
    "Size",
    "Rect",
    "rotate_point",
    "rotated_bounds",
    "fit_size",
    "clamp",
    "almost_equal",
]

EPSILON = 1e-9


def clamp(value: float, low: float, high: float) -> float:
    """Constrain *value* to the inclusive range ``[low, high]``."""
    if low > high:
        low, high = high, low
    return low if value < low else (high if value > high else value)


def almost_equal(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) <= tol


@dataclass(frozen=True, slots=True)
class Point:
    x: float = 0.0
    y: float = 0.0

    def __post_init__(self) -> None:
        # Coerce once here so every downstream consumer (JSON, Qt, PyMuPDF)
        # sees floats and never an int/float mix.
        object.__setattr__(self, "x", float(self.x))
        object.__setattr__(self, "y", float(self.y))

    def __add__(self, other: Point) -> Point:
        return Point(self.x + other.x, self.y + other.y)

    def __sub__(self, other: Point) -> Point:
        return Point(self.x - other.x, self.y - other.y)

    def __mul__(self, factor: float) -> Point:
        return Point(self.x * factor, self.y * factor)

    __rmul__ = __mul__

    def distance_to(self, other: Point) -> float:
        return math.hypot(self.x - other.x, self.y - other.y)

    def as_tuple(self) -> tuple[float, float]:
        return (self.x, self.y)

    @classmethod
    def from_tuple(cls, values: Sequence[float]) -> Point:
        return cls(float(values[0]), float(values[1]))


@dataclass(frozen=True, slots=True)
class Size:
    width: float = 0.0
    height: float = 0.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "width", float(self.width))
        object.__setattr__(self, "height", float(self.height))

    @property
    def is_empty(self) -> bool:
        return self.width <= EPSILON or self.height <= EPSILON

    @property
    def aspect(self) -> float:
        return self.width / self.height if self.height > EPSILON else 1.0

    def swapped(self) -> Size:
        return Size(self.height, self.width)

    def scaled(self, factor: float) -> Size:
        return Size(self.width * factor, self.height * factor)

    def as_tuple(self) -> tuple[float, float]:
        return (self.width, self.height)

    @classmethod
    def from_tuple(cls, values: Sequence[float]) -> Size:
        return cls(float(values[0]), float(values[1]))


@dataclass(frozen=True, slots=True)
class Rect:
    """An axis-aligned rectangle given by two corners, y growing downwards."""

    x0: float = 0.0
    y0: float = 0.0
    x1: float = 0.0
    y1: float = 0.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "x0", float(self.x0))
        object.__setattr__(self, "y0", float(self.y0))
        object.__setattr__(self, "x1", float(self.x1))
        object.__setattr__(self, "y1", float(self.y1))

    # -- construction ----------------------------------------------------
    @classmethod
    def from_xywh(cls, x: float, y: float, width: float, height: float) -> Rect:
        return cls(x, y, x + width, y + height)

    @classmethod
    def from_center(cls, center: Point, size: Size) -> Rect:
        return cls(
            center.x - size.width / 2.0,
            center.y - size.height / 2.0,
            center.x + size.width / 2.0,
            center.y + size.height / 2.0,
        )

    @classmethod
    def from_points(cls, points: Iterable[Point]) -> Rect:
        pts = list(points)
        if not pts:
            return cls()
        xs = [p.x for p in pts]
        ys = [p.y for p in pts]
        return cls(min(xs), min(ys), max(xs), max(ys))

    @classmethod
    def from_tuple(cls, values: Sequence[float]) -> Rect:
        return cls(float(values[0]), float(values[1]), float(values[2]), float(values[3]))

    # -- accessors -------------------------------------------------------
    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def height(self) -> float:
        return self.y1 - self.y0

    @property
    def size(self) -> Size:
        return Size(self.width, self.height)

    @property
    def center(self) -> Point:
        return Point((self.x0 + self.x1) / 2.0, (self.y0 + self.y1) / 2.0)

    @property
    def top_left(self) -> Point:
        return Point(self.x0, self.y0)

    @property
    def bottom_right(self) -> Point:
        return Point(self.x1, self.y1)

    @property
    def corners(self) -> tuple[Point, Point, Point, Point]:
        return (
            Point(self.x0, self.y0),
            Point(self.x1, self.y0),
            Point(self.x1, self.y1),
            Point(self.x0, self.y1),
        )

    @property
    def is_empty(self) -> bool:
        return self.width <= EPSILON or self.height <= EPSILON

    def as_tuple(self) -> tuple[float, float, float, float]:
        return (self.x0, self.y0, self.x1, self.y1)

    # -- derivations -----------------------------------------------------
    def normalized(self) -> Rect:
        """Return an equivalent rectangle with ``x0 <= x1`` and ``y0 <= y1``."""
        x0, x1 = (self.x0, self.x1) if self.x0 <= self.x1 else (self.x1, self.x0)
        y0, y1 = (self.y0, self.y1) if self.y0 <= self.y1 else (self.y1, self.y0)
        return Rect(x0, y0, x1, y1)

    def translated(self, dx: float, dy: float) -> Rect:
        return Rect(self.x0 + dx, self.y0 + dy, self.x1 + dx, self.y1 + dy)

    def moved_to(self, top_left: Point) -> Rect:
        return Rect.from_xywh(top_left.x, top_left.y, self.width, self.height)

    def resized(self, size: Size) -> Rect:
        return Rect.from_xywh(self.x0, self.y0, size.width, size.height)

    def scaled(self, factor: float) -> Rect:
        return Rect(self.x0 * factor, self.y0 * factor, self.x1 * factor, self.y1 * factor)

    def expanded(self, margin: float) -> Rect:
        return Rect(self.x0 - margin, self.y0 - margin, self.x1 + margin, self.y1 + margin)

    def united(self, other: Rect) -> Rect:
        return Rect(
            min(self.x0, other.x0),
            min(self.y0, other.y0),
            max(self.x1, other.x1),
            max(self.y1, other.y1),
        )

    def intersects(self, other: Rect) -> bool:
        return not (
            self.x1 <= other.x0
            or other.x1 <= self.x0
            or self.y1 <= other.y0
            or other.y1 <= self.y0
        )

    def contains_point(self, point: Point) -> bool:
        return self.x0 <= point.x <= self.x1 and self.y0 <= point.y <= self.y1

    def contains_rect(self, other: Rect) -> bool:
        return (
            self.x0 <= other.x0
            and self.y0 <= other.y0
            and self.x1 >= other.x1
            and self.y1 >= other.y1
        )

    def clamped_to(self, bounds: Rect) -> Rect:
        """Translate (never resize) so the rectangle stays inside *bounds*."""
        dx = dy = 0.0
        if self.x0 < bounds.x0:
            dx = bounds.x0 - self.x0
        elif self.x1 > bounds.x1:
            dx = bounds.x1 - self.x1
        if self.y0 < bounds.y0:
            dy = bounds.y0 - self.y0
        elif self.y1 > bounds.y1:
            dy = bounds.y1 - self.y1
        return self.translated(dx, dy)

    def with_min_size(self, minimum: float) -> Rect:
        w = max(self.width, minimum)
        h = max(self.height, minimum)
        return Rect.from_xywh(self.x0, self.y0, w, h)

    def lerp_point(self, fx: float, fy: float) -> Point:
        """Point at normalised position ``(fx, fy)`` inside the rectangle."""
        return Point(self.x0 + self.width * fx, self.y0 + self.height * fy)


def rotate_point(point: Point, pivot: Point, degrees: float) -> Point:
    """Rotate *point* around *pivot* by *degrees*, clockwise on screen."""
    if abs(degrees) <= EPSILON:
        return point
    rad = math.radians(degrees)
    cos_a, sin_a = math.cos(rad), math.sin(rad)
    dx, dy = point.x - pivot.x, point.y - pivot.y
    return Point(
        pivot.x + dx * cos_a - dy * sin_a,
        pivot.y + dx * sin_a + dy * cos_a,
    )


def rotated_bounds(rect: Rect, degrees: float, pivot: Point | None = None) -> Rect:
    """Axis-aligned bounding box of *rect* after rotating it by *degrees*."""
    if abs(degrees % 360.0) <= EPSILON:
        return rect
    origin = pivot if pivot is not None else rect.center
    return Rect.from_points(rotate_point(c, origin, degrees) for c in rect.corners)


def fit_size(source: Size, bounds: Size, *, enlarge: bool = True) -> Size:
    """Scale *source* to fit inside *bounds* while preserving its aspect ratio."""
    if source.is_empty or bounds.is_empty:
        return source
    factor = min(bounds.width / source.width, bounds.height / source.height)
    if not enlarge:
        factor = min(factor, 1.0)
    return source.scaled(factor)
