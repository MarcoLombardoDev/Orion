# Orion — PDF Editor for Desktop
# Copyright (C) 2026 Marco Lombardo
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# Distributed WITHOUT ANY WARRANTY; see LICENSE for the full terms.
# A commercial licence, without the AGPL's obligations, is available for use
# in proprietary or closed-source products — see COMMERCIAL-LICENSE.md.

"""Toolbar and menu icons, drawn in code.

Icons are described as a handful of primitives in a normalised 0..1 box and
painted with ``QPainter``.  Keeping them procedural means the repository has no
binary assets to review, icons stay crisp at any device pixel ratio, and they
recolour automatically when the theme changes (spec §31).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

from orion.ui.theme import Theme

__all__ = ["icon", "set_icon_theme", "available_icons"]


# --------------------------------------------------------------------------
# Primitive drawing operations
# --------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class Line:
    x1: float
    y1: float
    x2: float
    y2: float


@dataclass(frozen=True, slots=True)
class Poly:
    points: tuple[tuple[float, float], ...]
    closed: bool = False
    filled: bool = False


@dataclass(frozen=True, slots=True)
class Box:
    x: float
    y: float
    w: float
    h: float
    filled: bool = False
    radius: float = 0.0


@dataclass(frozen=True, slots=True)
class Oval:
    x: float
    y: float
    w: float
    h: float
    filled: bool = False


@dataclass(frozen=True, slots=True)
class Dot:
    x: float
    y: float
    r: float = 0.07


Shape = Line | Poly | Box | Oval | Dot

_R = 0.12  # standard rounded-corner radius

#: Every icon Orion uses, keyed by the name callers pass to :func:`icon`.
ICONS: dict[str, tuple[Shape, ...]] = {
    # -- file --------------------------------------------------------------
    "open": (
        Poly(((0.08, 0.78), (0.08, 0.25), (0.40, 0.25), (0.48, 0.36), (0.86, 0.36)), closed=True),
        Poly(((0.08, 0.78), (0.22, 0.46), (0.98, 0.46), (0.84, 0.78)), closed=True),
    ),
    "save": (
        Box(0.14, 0.16, 0.72, 0.68, radius=_R),
        Box(0.30, 0.16, 0.40, 0.26, filled=True),
        Box(0.28, 0.54, 0.44, 0.30),
    ),
    "save_as": (
        Box(0.10, 0.16, 0.62, 0.68, radius=_R),
        Box(0.24, 0.16, 0.34, 0.24, filled=True),
        Line(0.62, 0.72, 0.94, 0.40),
        Poly(((0.94, 0.40), (0.90, 0.56), (0.78, 0.56)), closed=True, filled=True),
    ),
    "new": (
        Poly(((0.20, 0.10), (0.62, 0.10), (0.80, 0.30), (0.80, 0.90), (0.20, 0.90)), closed=True),
        Line(0.62, 0.10, 0.62, 0.30),
        Line(0.62, 0.30, 0.80, 0.30),
    ),
    "close": (Line(0.24, 0.24, 0.76, 0.76), Line(0.76, 0.24, 0.24, 0.76)),
    "merge": (
        Box(0.08, 0.14, 0.34, 0.32, radius=0.06),
        Box(0.08, 0.54, 0.34, 0.32, radius=0.06),
        Line(0.46, 0.30, 0.66, 0.50),
        Line(0.46, 0.70, 0.66, 0.50),
        Box(0.66, 0.34, 0.28, 0.32, radius=0.06),
    ),
    "split": (
        Box(0.06, 0.34, 0.28, 0.32, radius=0.06),
        Line(0.36, 0.50, 0.56, 0.30),
        Line(0.36, 0.50, 0.56, 0.70),
        Box(0.58, 0.14, 0.34, 0.32, radius=0.06),
        Box(0.58, 0.54, 0.34, 0.32, radius=0.06),
    ),
    # -- edit --------------------------------------------------------------
    "undo": (
        Poly(((0.18, 0.44), (0.34, 0.28), (0.34, 0.60)), closed=True, filled=True),
        Poly(((0.30, 0.44), (0.62, 0.44), (0.78, 0.58), (0.70, 0.76)), closed=False),
    ),
    "redo": (
        Poly(((0.82, 0.44), (0.66, 0.28), (0.66, 0.60)), closed=True, filled=True),
        Poly(((0.70, 0.44), (0.38, 0.44), (0.22, 0.58), (0.30, 0.76)), closed=False),
    ),
    "copy": (Box(0.12, 0.12, 0.52, 0.52, radius=0.08), Box(0.36, 0.36, 0.52, 0.52, radius=0.08)),
    "cut": (
        Line(0.28, 0.14, 0.66, 0.66),
        Line(0.72, 0.14, 0.34, 0.66),
        Oval(0.16, 0.66, 0.22, 0.22),
        Oval(0.62, 0.66, 0.22, 0.22),
    ),
    "paste": (
        Box(0.16, 0.18, 0.68, 0.70, radius=0.08),
        Box(0.34, 0.08, 0.32, 0.18, filled=True, radius=0.05),
        Line(0.32, 0.48, 0.68, 0.48),
        Line(0.32, 0.64, 0.68, 0.64),
    ),
    "delete": (
        Line(0.16, 0.26, 0.84, 0.26),
        Poly(((0.26, 0.26), (0.32, 0.86), (0.68, 0.86), (0.74, 0.26))),
        Box(0.38, 0.12, 0.24, 0.14),
    ),
    "duplicate": (
        Box(0.12, 0.12, 0.50, 0.50, radius=0.08),
        Box(0.38, 0.38, 0.50, 0.50, radius=0.08),
        Line(0.63, 0.50, 0.63, 0.76),
        Line(0.50, 0.63, 0.76, 0.63),
    ),
    # -- view --------------------------------------------------------------
    "zoom_in": (
        Oval(0.10, 0.10, 0.58, 0.58),
        Line(0.62, 0.62, 0.90, 0.90),
        Line(0.26, 0.39, 0.52, 0.39),
        Line(0.39, 0.26, 0.39, 0.52),
    ),
    "zoom_out": (
        Oval(0.10, 0.10, 0.58, 0.58),
        Line(0.62, 0.62, 0.90, 0.90),
        Line(0.26, 0.39, 0.52, 0.39),
    ),
    "fit_page": (
        Box(0.16, 0.10, 0.68, 0.80, radius=0.06),
        Poly(((0.30, 0.34), (0.30, 0.24), (0.42, 0.24))),
        Poly(((0.70, 0.66), (0.70, 0.76), (0.58, 0.76))),
    ),
    "fit_width": (
        Box(0.10, 0.20, 0.80, 0.60, radius=0.06),
        Poly(((0.28, 0.40), (0.20, 0.50), (0.28, 0.60))),
        Poly(((0.72, 0.40), (0.80, 0.50), (0.72, 0.60))),
    ),
    "search": (Oval(0.14, 0.14, 0.54, 0.54), Line(0.60, 0.60, 0.90, 0.90)),
    "sidebar": (
        Box(0.10, 0.16, 0.80, 0.68, radius=0.06),
        Line(0.38, 0.16, 0.38, 0.84),
    ),
    "properties": (
        Line(0.16, 0.30, 0.84, 0.30),
        Line(0.16, 0.70, 0.84, 0.70),
        Dot(0.38, 0.30, 0.10),
        Dot(0.64, 0.70, 0.10),
    ),
    # -- navigation --------------------------------------------------------
    "first_page": (Line(0.28, 0.16, 0.28, 0.84), Poly(((0.78, 0.18), (0.40, 0.50), (0.78, 0.82)))),
    "prev_page": (Poly(((0.66, 0.16), (0.32, 0.50), (0.66, 0.84))),),
    "next_page": (Poly(((0.34, 0.16), (0.68, 0.50), (0.34, 0.84))),),
    "last_page": (Line(0.72, 0.16, 0.72, 0.84), Poly(((0.22, 0.18), (0.60, 0.50), (0.22, 0.82)))),
    # -- tools -------------------------------------------------------------
    "select": (
        Poly(
            ((0.26, 0.14), (0.26, 0.78), (0.42, 0.63), (0.53, 0.88), (0.66, 0.82), (0.55, 0.58), (0.76, 0.55)),
            closed=True,
            filled=True,
        ),
    ),
    "hand": (
        Poly(
            ((0.30, 0.86), (0.22, 0.56), (0.28, 0.50), (0.36, 0.60), (0.36, 0.22),
             (0.44, 0.16), (0.50, 0.22), (0.50, 0.44), (0.56, 0.18), (0.64, 0.16),
             (0.68, 0.24), (0.66, 0.46), (0.74, 0.30), (0.82, 0.34), (0.78, 0.62),
             (0.72, 0.86)),
            closed=True,
        ),
    ),
    "text": (Line(0.18, 0.20, 0.82, 0.20), Line(0.50, 0.20, 0.50, 0.84), Line(0.34, 0.84, 0.66, 0.84)),
    "image": (
        Box(0.10, 0.18, 0.80, 0.64, radius=0.06),
        Dot(0.32, 0.36, 0.08),
        Poly(((0.16, 0.74), (0.40, 0.48), (0.58, 0.66), (0.68, 0.56), (0.84, 0.74))),
    ),
    "rectangle": (Box(0.14, 0.24, 0.72, 0.52, radius=0.04),),
    "ellipse": (Oval(0.12, 0.24, 0.76, 0.52),),
    "line": (Line(0.16, 0.82, 0.84, 0.18),),
    "arrow": (
        Line(0.16, 0.84, 0.78, 0.22),
        Poly(((0.86, 0.14), (0.56, 0.22), (0.78, 0.44)), closed=True, filled=True),
    ),
    "highlight": (
        Box(0.12, 0.62, 0.76, 0.22, filled=True, radius=0.04),
        Poly(((0.24, 0.56), (0.52, 0.14), (0.72, 0.28), (0.44, 0.56)), closed=True),
    ),
    "underline": (
        Line(0.20, 0.82, 0.80, 0.82),
        Poly(((0.28, 0.16), (0.28, 0.44), (0.50, 0.62), (0.72, 0.44), (0.72, 0.16))),
    ),
    "strikeout": (
        Line(0.14, 0.50, 0.86, 0.50),
        Poly(((0.28, 0.18), (0.72, 0.18), (0.72, 0.28))),
        Poly(((0.30, 0.82), (0.70, 0.82))),
    ),
    "freehand": (
        Poly(((0.14, 0.74), (0.30, 0.36), (0.46, 0.70), (0.62, 0.28), (0.86, 0.60))),
    ),
    "comment": (
        Poly(
            ((0.12, 0.20), (0.88, 0.20), (0.88, 0.66), (0.46, 0.66), (0.28, 0.86), (0.28, 0.66), (0.12, 0.66)),
            closed=True,
        ),
    ),
    "sticky_note": (
        Poly(((0.16, 0.14), (0.84, 0.14), (0.84, 0.62), (0.60, 0.86), (0.16, 0.86)), closed=True),
        Poly(((0.84, 0.62), (0.60, 0.62), (0.60, 0.86))),
    ),
    # -- pages -------------------------------------------------------------
    "page_add": (
        Box(0.14, 0.12, 0.50, 0.66, radius=0.06),
        Line(0.74, 0.56, 0.74, 0.86),
        Line(0.59, 0.71, 0.89, 0.71),
    ),
    "page_delete": (
        Box(0.14, 0.12, 0.50, 0.66, radius=0.06),
        Line(0.60, 0.60, 0.88, 0.88),
        Line(0.88, 0.60, 0.60, 0.88),
    ),
    "rotate_left": (
        Poly(((0.20, 0.32), (0.20, 0.14), (0.38, 0.14)), closed=True, filled=True),
        Poly(((0.20, 0.22), (0.52, 0.18), (0.78, 0.42), (0.74, 0.74), (0.44, 0.86), (0.20, 0.72))),
    ),
    "rotate_right": (
        Poly(((0.80, 0.32), (0.80, 0.14), (0.62, 0.14)), closed=True, filled=True),
        Poly(((0.80, 0.22), (0.48, 0.18), (0.22, 0.42), (0.26, 0.74), (0.56, 0.86), (0.80, 0.72))),
    ),
    "extract": (
        Box(0.10, 0.20, 0.44, 0.62, radius=0.06),
        Line(0.58, 0.50, 0.90, 0.50),
        Poly(((0.90, 0.50), (0.76, 0.40), (0.76, 0.60)), closed=True, filled=True),
    ),
    "import": (
        Box(0.46, 0.20, 0.44, 0.62, radius=0.06),
        Line(0.10, 0.50, 0.42, 0.50),
        Poly(((0.42, 0.50), (0.28, 0.40), (0.28, 0.60)), closed=True, filled=True),
    ),
    "bring_front": (Box(0.10, 0.10, 0.52, 0.52), Box(0.34, 0.34, 0.56, 0.56, filled=True, radius=0.04)),
    "send_back": (Box(0.34, 0.34, 0.56, 0.56), Box(0.10, 0.10, 0.52, 0.52, filled=True, radius=0.04)),
    "info": (Oval(0.12, 0.12, 0.76, 0.76), Dot(0.50, 0.30, 0.07), Line(0.50, 0.44, 0.50, 0.76)),
}

_theme: Theme | None = None
_cache: dict[tuple[str, int, str], QIcon] = {}


def set_icon_theme(theme: Theme) -> None:
    """Recolour every icon.  Called whenever the application theme changes."""
    global _theme
    _theme = theme
    _cache.clear()


def available_icons() -> Sequence[str]:
    return tuple(ICONS)


def icon(name: str, size: int = 20, color: QColor | None = None) -> QIcon:
    """Return a themed :class:`QIcon`, or an empty one for an unknown name."""
    shapes = ICONS.get(name)
    if shapes is None:
        return QIcon()

    tint = color or (_theme.color("text") if _theme else QColor("#1c1f24"))
    key = (name, size, tint.name())
    cached = _cache.get(key)
    if cached is not None:
        return cached

    result = QIcon()
    for scale in (1, 2):
        result.addPixmap(_render(shapes, size * scale, tint, scale))

    # A second drawing, in the colour that reads on the accent, for the states
    # Qt paints with the accent behind them: a checked toolbar button, and a
    # selected row. Without it the icon stays the text colour -- a dark line
    # drawing on a dark blue fill, which is the same as no icon at all.
    #
    # Qt asks for State.On on anything checkable and Mode.Selected on a
    # selected item, and falls back to the pixmaps above everywhere else, so
    # adding these takes nothing away.
    on_tint = _theme.color("accent_text") if _theme else QColor("#ffffff")
    for scale in (1, 2):
        pixmap = _render(shapes, size * scale, on_tint, scale)
        result.addPixmap(pixmap, QIcon.Mode.Normal, QIcon.State.On)
        result.addPixmap(pixmap, QIcon.Mode.Active, QIcon.State.On)
        result.addPixmap(pixmap, QIcon.Mode.Selected, QIcon.State.On)
        result.addPixmap(pixmap, QIcon.Mode.Selected, QIcon.State.Off)

    _cache[key] = result
    return result


def _render(shapes: Sequence[Shape], pixels: int, color: QColor, scale: int) -> QPixmap:
    pixmap = QPixmap(QSize(pixels, pixels))
    pixmap.setDevicePixelRatio(float(scale))
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    pen = QPen(color)
    pen.setWidthF(max(1.0, pixels * 0.085))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)

    for shape in shapes:
        _paint(painter, shape, pixels, color)
    painter.end()
    return pixmap


def _paint(painter: QPainter, shape: Shape, size: int, color: QColor) -> None:
    brush = color if getattr(shape, "filled", False) else Qt.BrushStyle.NoBrush
    painter.setBrush(brush)

    if isinstance(shape, Line):
        painter.drawLine(
            QPointF(shape.x1 * size, shape.y1 * size),
            QPointF(shape.x2 * size, shape.y2 * size),
        )
    elif isinstance(shape, Box):
        rect = QRectF(shape.x * size, shape.y * size, shape.w * size, shape.h * size)
        if shape.radius:
            painter.drawRoundedRect(rect, shape.radius * size, shape.radius * size)
        else:
            painter.drawRect(rect)
    elif isinstance(shape, Oval):
        painter.drawEllipse(QRectF(shape.x * size, shape.y * size, shape.w * size, shape.h * size))
    elif isinstance(shape, Dot):
        painter.setBrush(color)
        painter.drawEllipse(QPointF(shape.x * size, shape.y * size), shape.r * size, shape.r * size)
    elif isinstance(shape, Poly):
        path = QPainterPath()
        first, *rest = shape.points
        path.moveTo(first[0] * size, first[1] * size)
        for point in rest:
            path.lineTo(point[0] * size, point[1] * size)
        if shape.closed:
            path.closeSubpath()
        painter.drawPath(path)
