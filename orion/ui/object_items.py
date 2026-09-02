# Orion — PDF Editor for Desktop
# Copyright (C) 2026 Marco Lombardo
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# Distributed WITHOUT ANY WARRANTY; see LICENSE for the full terms.
# A commercial licence, without the AGPL's obligations, is available for use
# in proprietary or closed-source products — see COMMERCIAL-LICENSE.md.

"""Graphics items for the objects the user adds (spec §8, §9, §10, §11, §13).

Everything selectable on the canvas derives from :class:`ObjectItem`, which
owns the shared behaviour: the bounding box, eight resize handles, the rotation
handle, and turning a completed gesture into exactly one undo command.

Object items live inside :class:`~orion.ui.page_item.ContentLayer`, so their
local coordinates *are* base page space and no conversion happens here.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from enum import Enum
from typing import TYPE_CHECKING

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
)
from PySide6.QtWidgets import (
    QGraphicsItem,
    QGraphicsSceneMouseEvent,
    QStyleOptionGraphicsItem,
    QWidget,
)

from orion.commands.object_commands import MoveObjectsCommand, TransformObjectsCommand
from orion.document.annotations import AnnotationKind, AnnotationObject
from orion.document.objects import (
    MIN_OBJECT_SIZE,
    ImageObject,
    PageObject,
    RedactionObject,
    ShapeKind,
    ShapeObject,
    TextObject,
)
from orion.pdf.fonts import FontRequest, resolve
from orion.pdf.text_layout import layout_text
from orion.utils.geometry import Point, Rect, rotate_point

if TYPE_CHECKING:  # pragma: no cover - typing only
    from orion.ui.page_item import PageItem

__all__ = ["ObjectItem", "create_item", "Handle"]

#: Size of a resize handle, in device pixels (kept constant under zoom).
HANDLE_PIXELS = 8.0
#: Distance of the rotation handle above the object, in device pixels.
ROTATION_OFFSET_PIXELS = 22.0


class Handle(Enum):
    NONE = -1
    TOP_LEFT = 0
    TOP = 1
    TOP_RIGHT = 2
    RIGHT = 3
    BOTTOM_RIGHT = 4
    BOTTOM = 5
    BOTTOM_LEFT = 6
    LEFT = 7
    ROTATE = 8

    @property
    def is_corner(self) -> bool:
        return self in (Handle.TOP_LEFT, Handle.TOP_RIGHT, Handle.BOTTOM_RIGHT, Handle.BOTTOM_LEFT)


#: Cursor for each handle, before the object's own rotation is taken into account.
_HANDLE_CURSORS = {
    Handle.TOP_LEFT: Qt.CursorShape.SizeFDiagCursor,
    Handle.TOP: Qt.CursorShape.SizeVerCursor,
    Handle.TOP_RIGHT: Qt.CursorShape.SizeBDiagCursor,
    Handle.RIGHT: Qt.CursorShape.SizeHorCursor,
    Handle.BOTTOM_RIGHT: Qt.CursorShape.SizeFDiagCursor,
    Handle.BOTTOM: Qt.CursorShape.SizeVerCursor,
    Handle.BOTTOM_LEFT: Qt.CursorShape.SizeBDiagCursor,
    Handle.LEFT: Qt.CursorShape.SizeHorCursor,
    Handle.ROTATE: Qt.CursorShape.CrossCursor,
}


#: The Qt families that stand in for the base-14 ones on screen. Those names
#: are PDF's rather than the desktop's, and asking Qt for "Helvetica" gets
#: whatever substitution the platform happens to make. Arial and Times New
#: Roman are the metric-compatible ones, so a line wraps on screen where it
#: wraps in the file.
BASE14_ON_SCREEN = {
    "Helvetica": "Arial",
    "Times": "Times New Roman",
    "Courier": "Courier New",
}


def qt_font(obj: TextObject, point_size: float) -> QFont:
    """The ``QFont`` that matches what the writer will put in the file.

    Bold and italic come from the **resolved** font rather than straight off
    the object, so the canvas slants text only when the saved file will. A
    family that ships no italic hands its upright face to the writer, and Qt
    would cheerfully fake the slant on screen — a difference nobody sees until
    the document is opened somewhere else.

    Shared with the inline editor, which has to agree with the painted text
    exactly: the editor is what replaces it while the user types, and any
    disagreement shows up as the text jumping when editing starts or ends.
    """
    resolved = resolve(FontRequest(obj.font_family, obj.bold, obj.italic))
    font = QFont(BASE14_ON_SCREEN.get(obj.font_family, obj.font_family))
    font.setStyleHint(
        QFont.StyleHint.Courier if obj.font_family == "Courier" else
        QFont.StyleHint.Serif if obj.font_family == "Times" else
        QFont.StyleHint.SansSerif
    )
    font.setPointSizeF(max(0.5, point_size))
    font.setBold(resolved.bold)
    font.setItalic(resolved.italic)
    return font


def scene_font(obj: TextObject, dpi: float) -> QFont:
    """A ``QFont`` whose em is *exactly* ``obj.font_size`` scene units.

    One scene unit is one PDF point, but Qt sizes a point against the paint
    device's logical DPI — so at the 96 dpi a desktop usually reports, asking
    for twelve points gets an em of sixteen units. Converting back is what
    keeps the canvas honest about where the glyphs will land.

    Both the painted text and the inline editor go through here, and they have
    to: they are the same words a moment apart, and any disagreement is a jump
    in size the instant the caret appears.
    """
    return qt_font(obj, obj.font_size * 72.0 / max(dpi, 1.0))


class ObjectItem(QGraphicsItem):
    """Base class: selection chrome, move/resize/rotate, undo integration."""

    def __init__(self, obj: PageObject, page_item: PageItem, canvas) -> None:
        super().__init__(page_item.content)
        self._object = obj
        self._page_item = page_item
        self._canvas = canvas
        self._lod = 1.0
        self._active_handle = Handle.NONE
        self._gesture_start: dict[str, tuple[Rect, float]] = {}
        self._gesture_origin = QPointF()
        self._gesture_kind = ""

        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsFocusable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemUsesExtendedStyleOption, True)
        self.setAcceptHoverEvents(True)
        self.sync_from_model()

    # -- model synchronisation -------------------------------------------
    @property
    def object(self) -> PageObject:
        return self._object

    @property
    def page_index(self) -> int:
        return self._page_item.index

    def sync_from_model(self) -> None:
        """Re-read geometry from the model (after undo, a paste, a property edit)."""
        self.prepareGeometryChange()
        obj = self._object
        rect = obj.rect
        self.setPos(rect.x0, rect.y0)
        self.setTransformOriginPoint(rect.width / 2.0, rect.height / 2.0)
        self.setRotation(obj.rotation)
        self.setOpacity(max(0.05, obj.opacity))
        movable = not obj.locked
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, movable)
        self.setToolTip(obj.display_name)
        self.update()

    def _write_geometry(self, rect: Rect, rotation: float | None = None) -> None:
        """Push geometry from the item back into the model."""
        self._object.rect = rect
        if rotation is not None:
            self._object.rotation = rotation
        self.sync_from_model()

    # -- geometry ---------------------------------------------------------
    def local_rect(self) -> QRectF:
        size = self._object.rect.size
        return QRectF(0.0, 0.0, max(size.width, 0.1), max(size.height, 0.1))

    def content_margin(self) -> float:
        """Extra room the drawn content needs beyond ``local_rect``."""
        return 0.0

    def boundingRect(self) -> QRectF:  # noqa: N802 - Qt naming
        margin = self.content_margin() + (self._chrome_margin() if self.isSelected() else 1.0)
        return self.local_rect().adjusted(-margin, -margin, margin, margin)

    def shape(self) -> QPainterPath:
        path = QPainterPath()
        path.addRect(self.local_rect().adjusted(-2, -2, 2, 2))
        return path

    def _chrome_margin(self) -> float:
        return (ROTATION_OFFSET_PIXELS + HANDLE_PIXELS) / max(self._lod, 0.05)

    # -- capabilities -----------------------------------------------------
    @property
    def can_resize(self) -> bool:
        return not self._object.locked

    @property
    def can_rotate(self) -> bool:
        return not self._object.locked

    @property
    def keeps_aspect(self) -> bool:
        return False

    # -- painting ---------------------------------------------------------
    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionGraphicsItem,
        widget: QWidget | None = None,
    ) -> None:
        self._lod = max(option.levelOfDetailFromTransform(painter.worldTransform()), 0.05)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.paint_content(painter, option, widget)
        if self.isSelected():
            self.paint_selection(painter)

    def paint_content(
        self, painter: QPainter, option: QStyleOptionGraphicsItem, widget: QWidget | None
    ) -> None:  # pragma: no cover - overridden
        raise NotImplementedError

    def paint_selection(self, painter: QPainter) -> None:
        theme = self._canvas.theme
        rect = self.local_rect()
        scale = self._lod

        painter.save()
        pen = QPen(theme.color("selection"))
        pen.setCosmetic(True)
        pen.setWidthF(1.4)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(rect)

        if self.can_rotate:
            top = QPointF(rect.center().x(), rect.top())
            handle = QPointF(top.x(), top.y() - ROTATION_OFFSET_PIXELS / scale)
            painter.drawLine(top, handle)
            self._draw_handle(painter, handle, theme, round_handle=True)

        if self.can_resize:
            for handle in self._resize_handles():
                self._draw_handle(painter, self._handle_point(handle), theme)
        painter.restore()

    def _draw_handle(
        self, painter: QPainter, centre: QPointF, theme, *, round_handle: bool = False
    ) -> None:
        size = HANDLE_PIXELS / self._lod
        rect = QRectF(centre.x() - size / 2, centre.y() - size / 2, size, size)
        pen = QPen(theme.color("handle_border"))
        pen.setCosmetic(True)
        pen.setWidthF(1.2)
        painter.setPen(pen)
        painter.setBrush(QBrush(theme.color("handle")))
        if round_handle:
            painter.drawEllipse(rect)
        else:
            painter.drawRect(rect)

    # -- handles ----------------------------------------------------------
    def _resize_handles(self) -> Sequence[Handle]:
        if self.keeps_aspect:
            return (Handle.TOP_LEFT, Handle.TOP_RIGHT, Handle.BOTTOM_RIGHT, Handle.BOTTOM_LEFT)
        return tuple(h for h in Handle if h not in (Handle.NONE, Handle.ROTATE))

    def _handle_point(self, handle: Handle) -> QPointF:
        rect = self.local_rect()
        centre = rect.center()
        return {
            Handle.TOP_LEFT: QPointF(rect.left(), rect.top()),
            Handle.TOP: QPointF(centre.x(), rect.top()),
            Handle.TOP_RIGHT: QPointF(rect.right(), rect.top()),
            Handle.RIGHT: QPointF(rect.right(), centre.y()),
            Handle.BOTTOM_RIGHT: QPointF(rect.right(), rect.bottom()),
            Handle.BOTTOM: QPointF(centre.x(), rect.bottom()),
            Handle.BOTTOM_LEFT: QPointF(rect.left(), rect.bottom()),
            Handle.LEFT: QPointF(rect.left(), centre.y()),
            Handle.ROTATE: QPointF(centre.x(), rect.top() - ROTATION_OFFSET_PIXELS / self._lod),
        }[handle]

    def handle_at(self, position: QPointF) -> Handle:
        if not self.isSelected():
            return Handle.NONE
        tolerance = (HANDLE_PIXELS * 0.9) / self._lod
        candidates: list[Handle] = []
        if self.can_rotate:
            candidates.append(Handle.ROTATE)
        if self.can_resize:
            candidates.extend(self._resize_handles())
        for handle in candidates:
            point = self._handle_point(handle)
            if (
                abs(point.x() - position.x()) <= tolerance
                and abs(point.y() - position.y()) <= tolerance
            ):
                return handle
        return Handle.NONE

    # -- interaction ------------------------------------------------------
    def hoverMoveEvent(self, event) -> None:  # noqa: N802 - Qt naming
        handle = self.handle_at(event.pos())
        if handle is Handle.NONE:
            self.unsetCursor()
        else:
            self.setCursor(_HANDLE_CURSORS[handle])
        super().hoverMoveEvent(event)

    def hoverLeaveEvent(self, event) -> None:  # noqa: N802 - Qt naming
        self.unsetCursor()
        super().hoverLeaveEvent(event)

    def mousePressEvent(self, event: QGraphicsSceneMouseEvent) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton or self._object.locked:
            super().mousePressEvent(event)
            return

        handle = self.handle_at(event.pos())
        self._snapshot_gesture()
        self._gesture_origin = event.scenePos()

        if handle is Handle.ROTATE:
            self._active_handle = handle
            self._gesture_kind = "Rotate"
            event.accept()
            return
        if handle is not Handle.NONE:
            self._active_handle = handle
            self._gesture_kind = "Resize"
            event.accept()
            return

        self._active_handle = Handle.NONE
        self._gesture_kind = "Move"
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QGraphicsSceneMouseEvent) -> None:  # noqa: N802
        if self._active_handle is Handle.ROTATE:
            self._rotate_to(event)
            event.accept()
            return
        if self._active_handle is not Handle.NONE:
            self._resize_to(event)
            event.accept()
            return
        super().mouseMoveEvent(event)
        self._sync_position_to_model()

    def mouseReleaseEvent(self, event: QGraphicsSceneMouseEvent) -> None:  # noqa: N802
        kind, handle = self._gesture_kind, self._active_handle
        self._active_handle = Handle.NONE
        self._gesture_kind = ""
        if handle is Handle.NONE:
            super().mouseReleaseEvent(event)
        else:
            event.accept()
        if kind:
            self._commit_gesture(kind)

    def mouseDoubleClickEvent(self, event: QGraphicsSceneMouseEvent) -> None:  # noqa: N802
        super().mouseDoubleClickEvent(event)

    # -- gesture bookkeeping ---------------------------------------------
    def _snapshot_gesture(self) -> None:
        """Record the geometry of the whole selection before a gesture starts."""
        self._gesture_start = {
            item.object.id: (item.object.rect, item.object.rotation)
            for item in self._canvas.selected_items()
        }
        self._gesture_start.setdefault(self._object.id, (self._object.rect, self._object.rotation))

    def _sync_position_to_model(self) -> None:
        """While dragging, keep the model in step with the item."""
        for item in self._canvas.selected_items():
            rect = item.object.rect
            item.object.rect = Rect.from_xywh(item.x(), item.y(), rect.width, rect.height)
            item.after_geometry_changed()

    def _commit_gesture(self, kind: str) -> None:
        """Turn the finished gesture into exactly one undo entry."""
        if not self._gesture_start:
            return
        before = self._gesture_start
        self._gesture_start = {}

        page = self._canvas.document.page_at(self.page_index)
        if page is None:
            return
        after = {
            object_id: (obj.rect, obj.rotation)
            for object_id in before
            if (obj := page.find_object(object_id)) is not None
        }
        if not after or all(after[k] == before[k] for k in after):
            return

        if kind == "Move":
            first = next(iter(after))
            dx = after[first][0].x0 - before[first][0].x0
            dy = after[first][0].y0 - before[first][0].y0
            command = MoveObjectsCommand(
                self._canvas.document,
                self.page_index,
                list(after),
                dx,
                dy,
                allow_merge=False,
            )
        else:
            command = TransformObjectsCommand(
                self._canvas.document,
                self.page_index,
                before,
                after,
                text=kind,
                allow_merge=False,
            )
        # The change is already applied on screen and in the model, so the
        # command is recorded without re-executing it.
        self._canvas.history.push(command, execute=False)
        self._canvas.document.set_modified(True)
        self._canvas.object_geometry_committed.emit()

    # -- transforms -------------------------------------------------------
    def _resize_to(self, event: QGraphicsSceneMouseEvent) -> None:
        start_rect, rotation = self._gesture_start[self._object.id]
        # Work in the object's own unrotated frame so a resize of a rotated
        # object still follows the handle the user grabbed.
        pivot = start_rect.center
        cursor = self._scene_to_base(event.scenePos())
        local = rotate_point(cursor, pivot, -rotation)

        x0, y0, x1, y1 = start_rect.as_tuple()
        handle = self._active_handle
        if handle in (Handle.TOP_LEFT, Handle.LEFT, Handle.BOTTOM_LEFT):
            x0 = min(local.x, x1 - MIN_OBJECT_SIZE)
        if handle in (Handle.TOP_RIGHT, Handle.RIGHT, Handle.BOTTOM_RIGHT):
            x1 = max(local.x, x0 + MIN_OBJECT_SIZE)
        if handle in (Handle.TOP_LEFT, Handle.TOP, Handle.TOP_RIGHT):
            y0 = min(local.y, y1 - MIN_OBJECT_SIZE)
        if handle in (Handle.BOTTOM_LEFT, Handle.BOTTOM, Handle.BOTTOM_RIGHT):
            y1 = max(local.y, y0 + MIN_OBJECT_SIZE)

        rect = Rect(x0, y0, x1, y1)
        lock_aspect = self.keeps_aspect or event.modifiers() & Qt.KeyboardModifier.ShiftModifier
        if lock_aspect and handle.is_corner:
            rect = _constrain_aspect(rect, start_rect, handle)

        if rotation:
            # Rotation happens about the centre, so keep the *rotated* position
            # of the anchor corner fixed while the centre moves.
            old_centre = rotate_point(start_rect.center, pivot, rotation)
            new_centre = rotate_point(rect.center, pivot, rotation)
            rect = rect.translated(old_centre.x - new_centre.x, old_centre.y - new_centre.y)

        self._write_geometry(rect)
        self.after_geometry_changed()
        self._canvas.notify_object_changed(self.page_index, self._object)

    def _rotate_to(self, event: QGraphicsSceneMouseEvent) -> None:
        start_rect, _ = self._gesture_start[self._object.id]
        centre = start_rect.center
        cursor = self._scene_to_base(event.scenePos())
        angle = math.degrees(math.atan2(cursor.y - centre.y, cursor.x - centre.x)) + 90.0
        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            angle = round(angle / 15.0) * 15.0
        self._write_geometry(start_rect, angle % 360.0)
        self._canvas.notify_object_changed(self.page_index, self._object)

    def _scene_to_base(self, scene_point: QPointF) -> Point:
        local = self._page_item.content.mapFromScene(scene_point)
        return Point(local.x(), local.y())

    def after_geometry_changed(self) -> None:
        """Hook for items whose content geometry follows the rect."""
        return None

    # -- selection --------------------------------------------------------
    def itemChange(self, change, value):  # noqa: N802 - Qt naming
        if change == QGraphicsItem.GraphicsItemChange.ItemSelectedHasChanged:
            self.prepareGeometryChange()
        return super().itemChange(change, value)


def _constrain_aspect(rect: Rect, reference: Rect, handle: Handle) -> Rect:
    """Force *rect* to the aspect ratio of *reference*, anchored opposite *handle*."""
    aspect = reference.size.aspect or 1.0
    width, height = rect.width, rect.height
    if width / max(height, 1e-6) > aspect:
        width = height * aspect
    else:
        height = width / aspect
    if handle in (Handle.TOP_LEFT, Handle.BOTTOM_LEFT):
        x0, x1 = rect.x1 - width, rect.x1
    else:
        x0, x1 = rect.x0, rect.x0 + width
    if handle in (Handle.TOP_LEFT, Handle.TOP_RIGHT):
        y0, y1 = rect.y1 - height, rect.y1
    else:
        y0, y1 = rect.y0, rect.y0 + height
    return Rect(x0, y0, x1, y1)


def _qcolor(color, opacity: float = 1.0) -> QColor:
    if color is None:
        return QColor(Qt.GlobalColor.transparent)
    result = QColor.fromRgbF(*color)
    if opacity < 1.0:
        result.setAlphaF(max(0.0, min(1.0, opacity)))
    return result


# --------------------------------------------------------------------------
# Text
# --------------------------------------------------------------------------
class TextObjectItem(ObjectItem):
    """A text box, laid out with the *same* engine the PDF writer uses.

    Line breaking comes from :mod:`orion.pdf.text_layout`, which measures with
    the metrics of the base-14 font the text will be written with — so what is
    on the canvas is where the glyphs land in the saved file.
    """

    def __init__(self, obj: TextObject, page_item: PageItem, canvas) -> None:
        super().__init__(obj, page_item, canvas)
        self._editor = None

    @property
    def text_object(self) -> TextObject:
        return self._object  # type: ignore[return-value]

    def paint_content(self, painter, option, widget) -> None:
        obj = self.text_object
        rect = self.local_rect()

        if self._editor is not None:
            return  # the inline editor is drawing instead

        if not obj.text:
            self._paint_empty_hint(painter, rect)
            return

        layout = layout_text(
            obj.text,
            Rect(0.0, 0.0, rect.width(), rect.height()),
            font=FontRequest(obj.font_family, obj.bold, obj.italic),
            font_size=obj.font_size,
            align=obj.align,
            line_spacing=obj.line_spacing,
        )

        painter.save()
        painter.setClipRect(rect.adjusted(-1, -1, 1, 1))
        painter.setPen(QPen(_qcolor(obj.color)))
        painter.setFont(self._qfont(painter))
        for line in layout.lines:
            for segment in line.segments:
                if segment.text:
                    painter.drawText(QPointF(segment.x, line.baseline), segment.text)
        if obj.underline:
            for x0, y, x1, thickness in layout.underline_spans():
                pen = QPen(_qcolor(obj.color))
                pen.setWidthF(thickness)
                painter.setPen(pen)
                painter.drawLine(QPointF(x0, y), QPointF(x1, y))
        painter.restore()

        if layout.overflows:
            self._paint_overflow_marker(painter, rect)

    def _qfont(self, painter: QPainter) -> QFont:
        device = painter.device()
        dpi = float(device.logicalDpiY()) if device is not None else 72.0
        return scene_font(self.text_object, dpi)

    def _paint_empty_hint(self, painter: QPainter, rect: QRectF) -> None:
        theme = self._canvas.theme
        pen = QPen(theme.color("text_muted"))
        pen.setStyle(Qt.PenStyle.DashLine)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(rect)

    def _paint_overflow_marker(self, painter: QPainter, rect: QRectF) -> None:
        """Warn that the text does not fit: it would be clipped in the PDF too."""
        theme = self._canvas.theme
        pen = QPen(theme.color("danger"))
        pen.setCosmetic(True)
        pen.setWidthF(1.5)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        size = 6.0 / self._lod
        corner = QPointF(rect.right(), rect.bottom())
        painter.drawLine(corner - QPointF(size, 0), corner)
        painter.drawLine(corner - QPointF(0, size), corner)

    # -- inline editing ---------------------------------------------------
    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if not self._object.locked:
            self.begin_editing()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    @property
    def is_editing(self) -> bool:
        return self._editor is not None

    def begin_editing(self) -> None:
        """Edit the text in place (spec §9 "la modifica deve essere intuitiva")."""
        if self._editor is not None:
            return
        from orion.ui.text_editor import InlineTextEditor

        self._editor = InlineTextEditor(self)
        self._canvas.editing_started.emit(self)

    def end_editing(self, *, commit: bool = True) -> None:
        editor = self._editor
        if editor is None:
            return
        self._editor = None
        editor.finish(commit=commit)
        self.update()
        self._canvas.editing_finished.emit(self)


# --------------------------------------------------------------------------
# Image
# --------------------------------------------------------------------------
class ImageObjectItem(ObjectItem):
    """A raster image; the decoded pixmap is cached per item."""

    def __init__(self, obj: ImageObject, page_item: PageItem, canvas) -> None:
        self._pixmap: QPixmap | None = None
        super().__init__(obj, page_item, canvas)

    @property
    def image_object(self) -> ImageObject:
        return self._object  # type: ignore[return-value]

    @property
    def keeps_aspect(self) -> bool:
        return self.image_object.keep_aspect

    def sync_from_model(self) -> None:
        super().sync_from_model()
        self._pixmap = None  # data may have changed; decode lazily

    def _ensure_pixmap(self) -> QPixmap | None:
        if self._pixmap is not None:
            return self._pixmap
        data = self.image_object.data
        if not data:
            return None
        image = QImage()
        if not image.loadFromData(data):
            return None
        self._pixmap = QPixmap.fromImage(image)
        return self._pixmap

    def paint_content(self, painter, option, widget) -> None:
        rect = self.local_rect()
        pixmap = self._ensure_pixmap()
        if pixmap is None:
            self._paint_missing(painter, rect)
            return
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.drawPixmap(rect, pixmap, QRectF(pixmap.rect()))

    def _paint_missing(self, painter: QPainter, rect: QRectF) -> None:
        theme = self._canvas.theme
        painter.fillRect(rect, theme.color("surface_alt"))
        pen = QPen(theme.color("danger"))
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.drawRect(rect)
        painter.drawLine(rect.topLeft(), rect.bottomRight())
        painter.drawLine(rect.topRight(), rect.bottomLeft())


# --------------------------------------------------------------------------
# Shapes
# --------------------------------------------------------------------------
class ShapeObjectItem(ObjectItem):
    """Rectangle, ellipse, line or arrow."""

    @property
    def shape_object(self) -> ShapeObject:
        return self._object  # type: ignore[return-value]

    def content_margin(self) -> float:
        obj = self.shape_object
        return max(obj.stroke_width, obj.arrow_size * 1.5 if obj.shape is ShapeKind.ARROW else 0.0)

    def paint_content(self, painter, option, widget) -> None:
        obj = self.shape_object
        rect = self.local_rect()

        pen = QPen(_qcolor(obj.stroke_color)) if obj.stroke_color else QPen(Qt.PenStyle.NoPen)
        if obj.stroke_color:
            pen.setWidthF(max(obj.stroke_width, 0.1))
            pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
            pen.setCapStyle(Qt.PenCapStyle.FlatCap)
        painter.setPen(pen)
        painter.setBrush(
            QBrush(_qcolor(obj.fill_color)) if obj.fill_color else Qt.BrushStyle.NoBrush
        )

        if obj.shape is ShapeKind.RECTANGLE:
            painter.drawRect(rect)
        elif obj.shape is ShapeKind.ELLIPSE:
            painter.drawEllipse(rect)
        else:
            self._paint_line(painter, rect, obj)

    def _paint_line(self, painter: QPainter, rect: QRectF, obj: ShapeObject) -> None:
        start = QPointF(rect.width() * obj.line_start[0], rect.height() * obj.line_start[1])
        end = QPointF(rect.width() * obj.line_end[0], rect.height() * obj.line_end[1])
        painter.drawLine(start, end)
        if obj.shape is not ShapeKind.ARROW:
            return

        size = max(obj.arrow_size, obj.stroke_width * 2.5)
        dx, dy = end.x() - start.x(), end.y() - start.y()
        length = math.hypot(dx, dy)
        if length <= 1e-6:
            return
        ux, uy = dx / length, dy / length
        back = QPointF(end.x() - ux * size * 2.2, end.y() - uy * size * 2.2)
        left = QPointF(back.x() - uy * size, back.y() + ux * size)
        right = QPointF(back.x() + uy * size, back.y() - ux * size)
        painter.drawLine(end, left)
        painter.drawLine(end, right)


# --------------------------------------------------------------------------
# Annotations
# --------------------------------------------------------------------------
#: Footprint of a note icon on the page, in points.
NOTE_SIZE = 20.0


class AnnotationObjectItem(ObjectItem):
    """Highlight, underline, strikeout, freehand ink, comment or sticky note."""

    @property
    def annotation(self) -> AnnotationObject:
        return self._object  # type: ignore[return-value]

    @property
    def can_resize(self) -> bool:
        return self.annotation.can_resize and not self._object.locked

    @property
    def can_rotate(self) -> bool:
        return self.annotation.can_rotate and not self._object.locked

    def content_margin(self) -> float:
        return self.annotation.stroke_width if self.annotation.strokes else 0.0

    def paint_content(self, painter, option, widget) -> None:
        obj = self.annotation
        kind = obj.annotation
        if kind.is_text_markup:
            self._paint_markup(painter, obj)
        elif kind is AnnotationKind.INK:
            self._paint_ink(painter, obj)
        else:
            self._paint_note(painter, obj)

    def _local_rects(self, rects) -> list[QRectF]:
        """Quads are stored in base space; the item's origin is the rect corner."""
        origin = self._object.rect
        return [
            QRectF(r.x0 - origin.x0, r.y0 - origin.y0, r.width, r.height) for r in rects
        ]

    def _paint_markup(self, painter: QPainter, obj: AnnotationObject) -> None:
        colour = _qcolor(obj.color)
        rects = self._local_rects(obj.quads) or [self.local_rect()]
        kind = obj.annotation

        if kind is AnnotationKind.HIGHLIGHT:
            colour.setAlphaF(0.42)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(colour)
            for rect in rects:
                painter.drawRect(rect)
            return

        pen = QPen(colour)
        pen.setWidthF(max(obj.stroke_width, 0.8))
        painter.setPen(pen)
        for rect in rects:
            if kind is AnnotationKind.UNDERLINE:
                y = rect.bottom() - rect.height() * 0.08
            else:
                y = rect.center().y()
            painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))

    def _paint_ink(self, painter: QPainter, obj: AnnotationObject) -> None:
        origin = obj.rect
        pen = QPen(_qcolor(obj.color))
        pen.setWidthF(max(obj.stroke_width, 0.4))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for stroke in obj.strokes:
            if len(stroke) < 2:
                continue
            polygon = QPolygonF(
                [QPointF(p.x - origin.x0, p.y - origin.y0) for p in stroke]
            )
            painter.drawPolyline(polygon)

    def _paint_note(self, painter: QPainter, obj: AnnotationObject) -> None:
        rect = self.local_rect()
        colour = _qcolor(obj.color)
        pen = QPen(colour.darker(150))
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(colour)

        if obj.annotation is AnnotationKind.STICKY_NOTE:
            fold = rect.width() * 0.32
            path = QPainterPath()
            path.moveTo(rect.topLeft())
            path.lineTo(rect.topRight())
            path.lineTo(rect.right(), rect.bottom() - fold)
            path.lineTo(rect.right() - fold, rect.bottom())
            path.lineTo(rect.bottomLeft())
            path.closeSubpath()
            painter.drawPath(path)
        else:
            path = QPainterPath()
            body = QRectF(rect.left(), rect.top(), rect.width(), rect.height() * 0.78)
            path.addRoundedRect(body, rect.width() * 0.15, rect.width() * 0.15)
            tail = QPolygonF(
                [
                    QPointF(rect.left() + rect.width() * 0.22, body.bottom()),
                    QPointF(rect.left() + rect.width() * 0.22, rect.bottom()),
                    QPointF(rect.left() + rect.width() * 0.50, body.bottom()),
                ]
            )
            path.addPolygon(tail)
            painter.drawPath(path.simplified())

        pen = QPen(colour.darker(220))
        pen.setCosmetic(True)
        painter.setPen(pen)
        inset = rect.width() * 0.22
        for index in range(2):
            y = rect.top() + rect.height() * (0.32 + index * 0.22)
            painter.drawLine(QPointF(rect.left() + inset, y), QPointF(rect.right() - inset, y))

    def after_geometry_changed(self) -> None:
        """Ink follows its bounding box when the object is resized."""
        obj = self.annotation
        if obj.annotation is not AnnotationKind.INK or not obj.strokes:
            return
        current = obj.recompute_rect()
        target = obj.rect
        if current.is_empty or target.is_empty:
            return
        sx = target.width / current.width
        sy = target.height / current.height
        if abs(sx - 1.0) < 1e-6 and abs(sy - 1.0) < 1e-6:
            return
        obj.strokes = [
            [
                Point(
                    target.x0 + (p.x - current.x0) * sx,
                    target.y0 + (p.y - current.y0) * sy,
                )
                for p in stroke
            ]
            for stroke in obj.strokes
        ]

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if self.annotation.annotation.is_note:
            self._canvas.request_note_edit(self)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class RedactionObjectItem(ObjectItem):
    """An opaque box, drawn as it will be saved.

    Deliberately identical on screen and in the file: a redaction that looked
    translucent while editing would invite the assumption that the content
    under it is merely covered, and the whole point is that by the time the
    file is written it is not there any more. The dashed outline appears only
    while it is selected, which is the one moment the user needs to see the
    boundary rather than the result.
    """

    def paint_content(self, painter: QPainter, option, widget) -> None:
        obj = self.redaction
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(_qcolor(obj.fill_color))
        painter.drawRect(self.local_rect())

    @property
    def redaction(self) -> RedactionObject:
        return self._object  # type: ignore[return-value]


# --------------------------------------------------------------------------
# Factory
# --------------------------------------------------------------------------
_ITEM_TYPES = {
    TextObject: TextObjectItem,
    ImageObject: ImageObjectItem,
    ShapeObject: ShapeObjectItem,
    AnnotationObject: AnnotationObjectItem,
    RedactionObject: RedactionObjectItem,
}


def create_item(obj: PageObject, page_item: PageItem, canvas) -> ObjectItem:
    """Build the right item for *obj*.  New object types register here."""
    for model_type, item_type in _ITEM_TYPES.items():
        if isinstance(obj, model_type):
            return item_type(obj, page_item, canvas)
    raise TypeError(f"No canvas item for {type(obj).__name__}")
