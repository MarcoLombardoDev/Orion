# Orion — PDF Editor for Desktop
# Copyright (C) 2026 Marco Lombardo
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# Distributed WITHOUT ANY WARRANTY; see LICENSE for the full terms.
# A commercial licence, without the AGPL's obligations, is available for use
# in proprietary or closed-source products — see COMMERCIAL-LICENSE.md.

"""The PDF canvas (spec §8, §13, §28).

A single ``QGraphicsScene`` holds every page laid out in a continuous vertical
strip.  Scene units are **PDF points at 100% zoom**, so the view's transform is
the zoom factor and nothing else in the application has to think about pixels.

Object items are children of each page's content layer, which means their local
coordinates *are* base page space — the conversion chain lives in exactly two
places (this module's layout and ``PageItem``'s transform) and nowhere else.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from enum import Enum

from PySide6.QtCore import QPoint, QPointF, QRectF, QSizeF, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPen,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QGraphicsItem,
    QGraphicsPathItem,
    QGraphicsScene,
    QGraphicsView,
)

from orion.commands.history import History
from orion.commands.object_commands import AddObjectCommand
from orion.document.annotations import AnnotationKind, AnnotationObject
from orion.document.document import Document
from orion.document.objects import (
    MIN_OBJECT_SIZE,
    PageObject,
    ShapeObject,
    TextObject,
)
from orion.pdf.renderer import RenderedPage, RenderRequest
from orion.ui.object_items import ObjectItem, TextObjectItem, create_item
from orion.ui.page_item import PageItem
from orion.ui.render_bridge import RenderService
from orion.ui.theme import LIGHT, Theme
from orion.ui.tools import Tool, ToolState
from orion.utils.geometry import Point, Rect, Size

log = logging.getLogger(__name__)

__all__ = ["PdfCanvas", "ZoomMode", "PAGE_GAP", "ZOOM_STEPS"]

#: Gap between pages in the continuous view, in points.
PAGE_GAP = 16.0
#: Margin around the whole page strip.
STRIP_MARGIN = 24.0

ZOOM_STEPS = (0.25, 0.33, 0.5, 0.67, 0.75, 1.0, 1.25, 1.5, 2.0, 3.0, 4.0, 6.0, 8.0)
MIN_ZOOM, MAX_ZOOM = 0.05, 12.0

#: Default size of a text box created by a single click.
DEFAULT_TEXT_SIZE = Size(220.0, 48.0)
#: On-page footprint of a comment or sticky note icon.
NOTE_SIZE = 20.0


class ZoomMode(str, Enum):
    CUSTOM = "custom"
    FIT_PAGE = "fit_page"
    FIT_WIDTH = "fit_width"


class PdfCanvas(QGraphicsView):
    """Displays and edits the document."""

    # -- signals ----------------------------------------------------------
    current_page_changed = Signal(int)
    zoom_changed = Signal(float, str)
    selection_changed = Signal(list)
    object_geometry_committed = Signal()
    editing_started = Signal(object)
    editing_finished = Signal(object)
    note_edit_requested = Signal(object)
    image_requested = Signal(int, object)  # (page_index, Point in base space)
    status_message = Signal(str)
    tool_finished = Signal()
    files_dropped = Signal(list, int, object)  # (paths, page_index, base Point)
    #: Right-click on the page area, with the position to open the menu at.
    #: The canvas has already settled what is selected by the time it fires.
    context_menu_requested = Signal(QPoint)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)

        self._document: Document | None = None
        self._history: History | None = None
        self._render_service: RenderService | None = None
        self._theme: Theme = LIGHT
        self._tool_state = ToolState()

        self._page_items: list[PageItem] = []
        self._item_index: dict[str, ObjectItem] = {}
        self._current_page = 0
        self._zoom = 1.0
        self._zoom_mode = ZoomMode.FIT_WIDTH

        self._draft: QGraphicsPathItem | None = None
        self._draft_origin: QPointF | None = None
        self._draft_page: PageItem | None = None
        self._ink_points: list[Point] = []
        self._panning = False
        self._pan_anchor = QPointF()
        self._space_pan = False

        self.setRenderHints(
            QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing
        )
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setRubberBandSelectionMode(Qt.ItemSelectionMode.IntersectsItemShape)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.SmartViewportUpdate)
        self.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAcceptDrops(True)

        self._scene.selectionChanged.connect(self._on_selection_changed)
        self.verticalScrollBar().valueChanged.connect(self._update_current_page)
        self.apply_theme(LIGHT)

    # ------------------------------------------------------------------
    # Session
    # ------------------------------------------------------------------
    @property
    def document(self) -> Document:
        if self._document is None:
            raise RuntimeError("No document is open")
        return self._document

    @property
    def has_document(self) -> bool:
        return self._document is not None

    @property
    def history(self) -> History:
        assert self._history is not None
        return self._history

    @property
    def render_service(self) -> RenderService:
        assert self._render_service is not None
        return self._render_service

    @property
    def theme(self) -> Theme:
        return self._theme

    @property
    def tool_state(self) -> ToolState:
        return self._tool_state

    @property
    def tool(self) -> Tool:
        return self._tool_state.tool

    def set_session(self, session) -> None:
        """Attach a :class:`~orion.services.file_service.DocumentSession`."""
        self.close_session()
        self._document = session.document
        self._history = session.history
        self._render_service = RenderService(session.renderer, self)
        self._render_service.rendered.connect(self._on_rendered)
        self._render_service.failed.connect(self._on_render_failed)

        self._document.pages_changed.connect(self._on_pages_changed)
        self._document.page_content_changed.connect(self._on_content_changed)

        self.rebuild()
        self.set_zoom_mode(self._zoom_mode)

    def close_session(self) -> None:
        if self._render_service is not None:
            self._render_service.shutdown()
            self._render_service = None
        self._cancel_draft()
        self._scene.clear()
        self._page_items.clear()
        self._item_index.clear()
        self._document = None
        self._history = None
        self._current_page = 0

    # ------------------------------------------------------------------
    # Theme
    # ------------------------------------------------------------------
    def apply_theme(self, theme: Theme) -> None:
        self._theme = theme
        self.setBackgroundBrush(QBrush(theme.color("canvas")))
        self._scene.update()

    # ------------------------------------------------------------------
    # Building the scene
    # ------------------------------------------------------------------
    def rebuild(self) -> None:
        """Recreate every page item.  Used on open and after page reordering."""
        selected = {item.object.id for item in self.selected_items()}
        anchor = self._reading_anchor()
        self._cancel_draft()
        self._scene.clear()
        self._page_items.clear()
        self._item_index.clear()
        if self._document is None:
            return

        for index, page in enumerate(self._document.pages):
            item = PageItem(page, index, self)
            self._scene.addItem(item)
            self._page_items.append(item)
            for obj in page.objects:
                self._add_object_item(obj, item)

        self.relayout()
        for object_id in selected:
            item = self._item_index.get(object_id)
            if item is not None:
                item.setSelected(True)
        self._restore_reading_anchor(anchor)

    def _reading_anchor(self) -> tuple[str, float] | None:
        """Where the user is reading: ``(page id, fraction down that page)``.

        Rebuilding the scene otherwise throws the reader back to the top, which
        is jarring after something as small as rotating a page.
        """
        if not self._page_items:
            return None
        centre_y = self.mapToScene(self.viewport().rect().center()).y()
        item = self._page_item(self._current_page) or self._page_items[0]
        rect = item.sceneBoundingRect()
        height = rect.height() or 1.0
        return (item.page.id, (centre_y - rect.top()) / height)

    def _restore_reading_anchor(self, anchor: tuple[str, float] | None) -> None:
        if anchor is None or not self._page_items:
            return
        page_id, fraction = anchor
        for item in self._page_items:
            if item.page.id == page_id:
                rect = item.sceneBoundingRect()
                self.centerOn(rect.center().x(), rect.top() + rect.height() * fraction)
                self._current_page = item.index
                self.current_page_changed.emit(item.index)
                return

    def relayout(self) -> None:
        """Stack the pages vertically and centre them."""
        if not self._page_items:
            self._scene.setSceneRect(QRectF())
            return
        width = max(item.page.display_size.width for item in self._page_items)
        y = STRIP_MARGIN
        for item in self._page_items:
            size = item.page.display_size
            item.setPos((width - size.width) / 2.0 + STRIP_MARGIN, y)
            y += size.height + PAGE_GAP
        total_height = y - PAGE_GAP + STRIP_MARGIN
        self._scene.setSceneRect(0.0, 0.0, width + 2 * STRIP_MARGIN, total_height)

    def _add_object_item(self, obj: PageObject, page_item: PageItem) -> ObjectItem:
        item = create_item(obj, page_item, self)
        self._item_index[obj.id] = item
        return item

    # ------------------------------------------------------------------
    # Model change handling
    # ------------------------------------------------------------------
    def _on_pages_changed(self, _document: Document) -> None:
        self.rebuild()
        self._update_current_page()

    def _on_content_changed(self, page_index: int, object_id: str | None) -> None:
        page_item = self._page_item(page_index)
        if page_item is None:
            return
        page = page_item.page
        model_ids = {obj.id for obj in page.objects}

        # Remove items whose objects are gone.
        for item in list(page_item.content.childItems()):
            if isinstance(item, ObjectItem) and item.object.id not in model_ids:
                self._item_index.pop(item.object.id, None)
                self._scene.removeItem(item)

        # Add or refresh the rest, preserving z-order.
        for z, obj in enumerate(page.objects):
            item = self._item_index.get(obj.id)
            if item is None or item.scene() is None:
                item = self._add_object_item(obj, page_item)
            else:
                item.sync_from_model()
            item.setZValue(float(z))

        self._emit_selection()

    def notify_object_changed(self, page_index: int, obj: PageObject) -> None:
        """Called by items during a live gesture (no history entry yet)."""
        item = self._item_index.get(obj.id)
        if item is not None:
            item.sync_from_model()
        self.selection_changed.emit(self.selected_objects())

    def refresh_object(self, object_id: str) -> None:
        item = self._item_index.get(object_id)
        if item is not None:
            item.sync_from_model()

    def refresh_page(self, page_index: int) -> None:
        page_item = self._page_item(page_index)
        if page_item is None:
            return
        page_item.update_transform()
        page_item.invalidate_raster()
        self.relayout()

    # ------------------------------------------------------------------
    # Rendering callbacks
    # ------------------------------------------------------------------
    def _on_rendered(self, request: RenderRequest, page: RenderedPage) -> None:
        for item in self._page_items:
            if item.page.id == request.page_id:
                item.deliver(request, page)
                return

    def _on_render_failed(self, _request: RenderRequest, message: str) -> None:
        self.status_message.emit(message)

    # ------------------------------------------------------------------
    # Pages and navigation
    # ------------------------------------------------------------------
    def _page_item(self, index: int) -> PageItem | None:
        if 0 <= index < len(self._page_items):
            return self._page_items[index]
        return None

    @property
    def page_count(self) -> int:
        return len(self._page_items)

    @property
    def current_page(self) -> int:
        return self._current_page

    def go_to_page(self, index: int, *, top: bool = True) -> None:
        item = self._page_item(index)
        if item is None:
            return
        rect = item.sceneBoundingRect()
        if top:
            self.centerOn(
                rect.center().x(),
                rect.top() + self.viewport().height() / (2 * self._zoom),
            )
        else:
            self.centerOn(rect.center())
        self._set_current_page(index)

    def _set_current_page(self, index: int) -> None:
        if index != self._current_page and 0 <= index < len(self._page_items):
            self._current_page = index
            self.current_page_changed.emit(index)

    def _update_current_page(self) -> None:
        """The current page is the one covering the middle of the viewport."""
        if not self._page_items:
            return
        centre = self.mapToScene(self.viewport().rect().center())
        best, best_distance = self._current_page, float("inf")
        for item in self._page_items:
            rect = item.sceneBoundingRect()
            if rect.top() <= centre.y() <= rect.bottom():
                best = item.index
                break
            distance = min(abs(rect.top() - centre.y()), abs(rect.bottom() - centre.y()))
            if distance < best_distance:
                best, best_distance = item.index, distance
        self._set_current_page(best)

    def page_item_at(self, scene_pos: QPointF) -> PageItem | None:
        for item in self._page_items:
            if item.sceneBoundingRect().contains(scene_pos):
                return item
        return None

    def nearest_page_item(self, scene_pos: QPointF) -> PageItem | None:
        exact = self.page_item_at(scene_pos)
        if exact is not None:
            return exact
        return self._page_item(self._current_page)

    # ------------------------------------------------------------------
    # Zoom
    # ------------------------------------------------------------------
    @property
    def zoom(self) -> float:
        return self._zoom

    @property
    def zoom_mode(self) -> ZoomMode:
        return self._zoom_mode

    def set_zoom(self, zoom: float, *, mode: ZoomMode = ZoomMode.CUSTOM) -> None:
        zoom = max(MIN_ZOOM, min(MAX_ZOOM, zoom))
        if abs(zoom - self._zoom) > 1e-4 or mode != self._zoom_mode:
            self._zoom = zoom
            self._zoom_mode = mode
            self.setTransform(self.transform().fromScale(zoom, zoom))
            if self._render_service is not None:
                self._render_service.invalidate()
            self.zoom_changed.emit(zoom, mode.value)

    def zoom_in(self) -> None:
        self.set_zoom(_next_step(self._zoom, 1))

    def zoom_out(self) -> None:
        self.set_zoom(_next_step(self._zoom, -1))

    def set_zoom_mode(self, mode: ZoomMode) -> None:
        if mode is ZoomMode.CUSTOM:
            self.set_zoom(self._zoom, mode=mode)
            return
        self._zoom_mode = mode
        self._apply_fit()

    def _apply_fit(self) -> None:
        item = self._page_item(self._current_page) or self._page_item(0)
        if item is None:
            return
        size = item.page.display_size
        viewport = self.viewport().size()
        available_width = viewport.width() - 2 * STRIP_MARGIN
        if self._zoom_mode is ZoomMode.FIT_WIDTH:
            zoom = available_width / max(size.width, 1.0)
        elif self._zoom_mode is ZoomMode.FIT_PAGE:
            zoom = min(
                available_width / max(size.width, 1.0),
                (viewport.height() - 2 * STRIP_MARGIN) / max(size.height, 1.0),
            )
        else:
            return
        self.set_zoom(zoom, mode=self._zoom_mode)

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().resizeEvent(event)
        if self._zoom_mode in (ZoomMode.FIT_WIDTH, ZoomMode.FIT_PAGE):
            self._apply_fit()

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802 - Qt naming
        zoom_modifiers = (
            Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier
        )
        if event.modifiers() & zoom_modifiers:
            delta = event.angleDelta().y()
            if delta:
                self.set_zoom(self._zoom * (1.0015 ** delta))
            event.accept()
            return
        super().wheelEvent(event)

    # ------------------------------------------------------------------
    # Selection
    # ------------------------------------------------------------------
    def selected_items(self) -> list[ObjectItem]:
        return [item for item in self._scene.selectedItems() if isinstance(item, ObjectItem)]

    def selected_objects(self) -> list[PageObject]:
        return [item.object for item in self.selected_items()]

    def selection_by_page(self) -> dict[int, list[str]]:
        """Selected object ids grouped by page.

        A rubber band can cross a page boundary in the continuous view, so any
        command built from the selection has to be built per page.
        """
        grouped: dict[int, list[str]] = {}
        for item in self.selected_items():
            grouped.setdefault(item.page_index, []).append(item.object.id)
        return grouped

    def select_objects(self, object_ids: Iterable[str]) -> None:
        self._scene.clearSelection()
        for object_id in object_ids:
            item = self._item_index.get(object_id)
            if item is not None:
                item.setSelected(True)

    def select_all_on_current_page(self) -> None:
        page = self.document.page_at(self._current_page)
        if page is None:
            return
        self.select_objects(obj.id for obj in page.objects)

    def clear_selection(self) -> None:
        self._scene.clearSelection()

    def _on_selection_changed(self) -> None:
        items = self.selected_items()
        if items:
            self._set_current_page(items[0].page_index)
        self._emit_selection()

    def _emit_selection(self) -> None:
        self.selection_changed.emit(self.selected_objects())

    # ------------------------------------------------------------------
    # Tools
    # ------------------------------------------------------------------
    def set_tool(self, tool: Tool) -> None:
        self._finish_text_editing()
        self._cancel_draft()
        self._tool_state.tool = tool
        if tool is Tool.HAND:
            self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        elif tool is Tool.SELECT:
            self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        else:
            self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self._update_cursor()
        self._set_items_interactive(tool is Tool.SELECT)

    def _set_items_interactive(self, interactive: bool) -> None:
        """Only the Select tool may grab existing objects."""
        for item in self._item_index.values():
            item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, interactive)
            item.setFlag(
                QGraphicsItem.GraphicsItemFlag.ItemIsMovable,
                interactive and not item.object.locked,
            )
            item.setAcceptedMouseButtons(
                Qt.MouseButton.LeftButton if interactive else Qt.MouseButton.NoButton
            )

    def _update_cursor(self) -> None:
        tool = self.tool
        if self._space_pan or tool is Tool.HAND:
            self.viewport().setCursor(Qt.CursorShape.OpenHandCursor)
        elif tool is Tool.SELECT:
            self.viewport().setCursor(Qt.CursorShape.ArrowCursor)
        elif tool is Tool.TEXT:
            self.viewport().setCursor(Qt.CursorShape.IBeamCursor)
        else:
            self.viewport().setCursor(Qt.CursorShape.CrossCursor)

    # ------------------------------------------------------------------
    # Mouse handling
    # ------------------------------------------------------------------
    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt naming
        if self._document is None:
            return

        if event.button() == Qt.MouseButton.MiddleButton or (
            self._space_pan and event.button() == Qt.MouseButton.LeftButton
        ):
            self._begin_pan(event)
            return

        tool = self.tool
        if tool in (Tool.SELECT, Tool.HAND) or event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return

        scene_pos = self.mapToScene(event.position().toPoint())
        page_item = self.nearest_page_item(scene_pos)
        if page_item is None:
            return
        base = self._to_base(page_item, scene_pos)

        if tool is Tool.IMAGE:
            self.image_requested.emit(page_item.index, base)
            event.accept()
            return
        if tool in (Tool.COMMENT, Tool.STICKY_NOTE):
            self._create_note(page_item, base, tool)
            event.accept()
            return
        if tool is Tool.FREEHAND:
            self._begin_ink(page_item, base)
            event.accept()
            return

        self._begin_draft(page_item, scene_pos)
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt naming
        if self._panning:
            self._continue_pan(event)
            return
        if self._draft_page is not None:
            scene_pos = self.mapToScene(event.position().toPoint())
            if self.tool is Tool.FREEHAND:
                self._extend_ink(scene_pos)
            else:
                self._update_draft(scene_pos, event.modifiers())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt naming
        if self._panning:
            self._end_pan()
            return
        if self._draft_page is not None and event.button() == Qt.MouseButton.LeftButton:
            self._commit_draft(self.mapToScene(event.position().toPoint()))
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt naming
        super().mouseDoubleClickEvent(event)

    def contextMenuEvent(self, event) -> None:  # noqa: N802 - Qt naming
        """Right-click: settle the selection, then ask for a menu.

        Deciding *what* the click is about belongs here, because only the
        canvas knows what is under the cursor; deciding what can be done to it
        belongs to the window, which owns the actions. So this sets the
        selection and emits, and builds nothing.

        Right-clicking an object that is not already selected selects it —
        which is what every editor does, and what makes the menu that follows
        about the thing the user pointed at rather than about whatever was
        selected beforehand. Right-clicking inside an existing multiple
        selection leaves it alone, so "delete these six" still works.
        """
        if self._document is None:
            return
        scene_pos = self.mapToScene(event.pos())
        item = self._object_item_at(scene_pos)
        if item is None:
            self.clear_selection()
        elif not item.isSelected():
            # Bypasses the item flags on purpose: a right-click offers the menu
            # whatever tool is active, and outside Select the items are not
            # accepting mouse buttons at all.
            self.select_objects([item.object.id])
        page_item = self.page_item_at(scene_pos)
        if page_item is not None:
            self._set_current_page(page_item.index)
        self.context_menu_requested.emit(event.globalPos())
        event.accept()

    def _object_item_at(self, scene_pos: QPointF) -> ObjectItem | None:
        """The topmost object under *scene_pos*, ignoring the page beneath."""
        for candidate in self._scene.items(scene_pos):
            if isinstance(candidate, ObjectItem):
                return candidate
        return None

    # -- panning ----------------------------------------------------------
    def _begin_pan(self, event: QMouseEvent) -> None:
        self._panning = True
        self._pan_anchor = event.position()
        self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
        event.accept()

    def _continue_pan(self, event: QMouseEvent) -> None:
        delta = event.position() - self._pan_anchor
        self._pan_anchor = event.position()
        self.horizontalScrollBar().setValue(
            self.horizontalScrollBar().value() - int(delta.x())
        )
        self.verticalScrollBar().setValue(self.verticalScrollBar().value() - int(delta.y()))
        event.accept()

    def _end_pan(self) -> None:
        self._panning = False
        self._update_cursor()

    # ------------------------------------------------------------------
    # Object creation
    # ------------------------------------------------------------------
    def _to_base(self, page_item: PageItem, scene_pos: QPointF) -> Point:
        local = page_item.content.mapFromScene(scene_pos)
        return Point(local.x(), local.y())

    def _begin_draft(self, page_item: PageItem, scene_pos: QPointF) -> None:
        self._draft_page = page_item
        self._draft_origin = scene_pos
        path_item = QGraphicsPathItem()
        pen = QPen(self._theme.color("selection"))
        pen.setCosmetic(True)
        pen.setStyle(Qt.PenStyle.DashLine)
        path_item.setPen(pen)
        path_item.setZValue(1000)
        self._scene.addItem(path_item)
        self._draft = path_item

    def _update_draft(self, scene_pos: QPointF, modifiers) -> None:
        if self._draft is None or self._draft_origin is None:
            return
        rect = QRectF(self._draft_origin, scene_pos).normalized()
        if modifiers & Qt.KeyboardModifier.ShiftModifier and self.tool not in (
            Tool.LINE,
            Tool.ARROW,
        ):
            side = max(rect.width(), rect.height())
            rect = QRectF(rect.topLeft(), QSizeF(side, side))
        path = self._draft.path()
        path.clear()
        if self.tool in (Tool.LINE, Tool.ARROW):
            path.moveTo(self._draft_origin)
            path.lineTo(scene_pos)
        else:
            path.addRect(rect)
        self._draft.setPath(path)

    def _cancel_draft(self) -> None:
        if self._draft is not None and self._draft.scene() is not None:
            self._scene.removeItem(self._draft)
        self._draft = None
        self._draft_origin = None
        self._draft_page = None
        self._ink_points = []

    def _commit_draft(self, scene_pos: QPointF) -> None:
        page_item, origin = self._draft_page, self._draft_origin
        tool = self.tool
        if tool is Tool.FREEHAND:
            self._commit_ink()
            return
        draft_rect = self._draft.path().boundingRect() if self._draft is not None else None
        self._cancel_draft()
        if page_item is None or origin is None:
            return

        start = self._to_base(page_item, origin)
        end = self._to_base(page_item, scene_pos)
        if draft_rect is not None and tool not in (Tool.LINE, Tool.ARROW):
            # Use the preview's rectangle so a Shift-constrained square is kept.
            top_left = self._to_base(page_item, draft_rect.topLeft())
            bottom_right = self._to_base(page_item, draft_rect.bottomRight())
            rect = Rect.from_points([top_left, bottom_right]).normalized()
        else:
            rect = Rect.from_points([start, end]).normalized()

        if tool.is_markup:
            self._create_markup(page_item, rect, tool)
            return
        if tool is Tool.TEXT:
            if rect.width < MIN_OBJECT_SIZE * 3 or rect.height < MIN_OBJECT_SIZE * 2:
                rect = Rect.from_xywh(
                    start.x, start.y, DEFAULT_TEXT_SIZE.width, DEFAULT_TEXT_SIZE.height
                )
            self._create_text(page_item, rect)
            return
        if rect.width < MIN_OBJECT_SIZE and rect.height < MIN_OBJECT_SIZE:
            return
        self._create_shape(page_item, rect, start, end, tool)

    # -- concrete creators ------------------------------------------------
    def _push_new_object(
        self, page_item: PageItem, obj: PageObject, text: str
    ) -> ObjectItem | None:
        self.history.push(AddObjectCommand(self.document, page_item.index, obj, text=text))
        item = self._item_index.get(obj.id)
        if item is not None:
            self.select_objects([obj.id])
        self.tool_finished.emit()
        return item

    def _create_text(self, page_item: PageItem, rect: Rect) -> None:
        state = self._tool_state
        obj = TextObject(
            rect=rect,
            text="",
            font_family=state.font_family,
            font_size=state.font_size,
            bold=state.bold,
            italic=state.italic,
            underline=state.underline,
            color=state.text_color,
            align=state.align,
        )
        item = self._push_new_object(page_item, obj, "Add Text")
        if isinstance(item, TextObjectItem):
            item.begin_editing()

    def _create_shape(
        self, page_item: PageItem, rect: Rect, start: Point, end: Point, tool: Tool
    ) -> None:
        state = self._tool_state
        kind = tool.shape_kind
        if kind is None:
            return
        rect = rect.with_min_size(MIN_OBJECT_SIZE)
        obj = ShapeObject(
            rect=rect,
            shape=kind,
            stroke_color=state.stroke_color,
            stroke_width=state.stroke_width,
            fill_color=state.fill_color if not kind.is_linear else None,
            opacity=state.opacity,
        )
        if kind.is_linear:
            # Store the drag direction as normalised endpoints so the line can
            # point any way while still using the generic rect machinery.
            obj.line_start = _fraction(start, rect)
            obj.line_end = _fraction(end, rect)
        self._push_new_object(page_item, obj, f"Add {kind.value.capitalize()}")

    def _create_markup(self, page_item: PageItem, rect: Rect, tool: Tool) -> None:
        kind = tool.annotation_kind
        if kind is None:
            return
        quads = self.render_service.renderer.text_lines_in(page_item.page, rect)
        if not quads:
            self.status_message.emit("No selectable text was found in that area.")
            self.tool_finished.emit()
            return
        obj = AnnotationObject(
            rect=rect,
            annotation=kind,
            color=self._tool_state.color_for(kind),
            quads=quads,
            author=self._tool_state.author,
        )
        obj.rect = obj.recompute_rect()
        self._push_new_object(page_item, obj, f"Add {kind.value.capitalize()}")

    def _create_note(self, page_item: PageItem, base: Point, tool: Tool) -> None:
        kind = tool.annotation_kind
        if kind is None:
            return
        obj = AnnotationObject(
            rect=Rect.from_xywh(base.x, base.y, NOTE_SIZE, NOTE_SIZE),
            annotation=kind,
            color=self._tool_state.color_for(kind),
            author=self._tool_state.author,
        )
        item = self._push_new_object(page_item, obj, f"Add {kind.value.replace('_', ' ').title()}")
        if item is not None:
            self.note_edit_requested.emit(item)

    # -- freehand ---------------------------------------------------------
    def _begin_ink(self, page_item: PageItem, base: Point) -> None:
        self._draft_page = page_item
        self._ink_points = [base]
        path_item = QGraphicsPathItem()
        pen = QPen(QColor.fromRgbF(*self._tool_state.color_for(AnnotationKind.INK)))
        pen.setWidthF(self._tool_state.ink_width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        path_item.setPen(pen)
        path_item.setZValue(1000)
        path_item.setParentItem(page_item.content)
        self._draft = path_item

    def _extend_ink(self, scene_pos: QPointF) -> None:
        if self._draft is None or self._draft_page is None:
            return
        base = self._to_base(self._draft_page, scene_pos)
        if self._ink_points and base.distance_to(self._ink_points[-1]) < 0.6:
            return
        self._ink_points.append(base)
        path = self._draft.path()
        if path.elementCount() == 0:
            path.moveTo(self._ink_points[0].x, self._ink_points[0].y)
        path.lineTo(base.x, base.y)
        self._draft.setPath(path)

    def _commit_ink(self) -> None:
        page_item, points = self._draft_page, list(self._ink_points)
        if self._draft is not None:
            self._draft.setParentItem(None)
            if self._draft.scene() is not None:
                self._scene.removeItem(self._draft)
        self._draft = None
        self._draft_page = None
        self._ink_points = []

        if page_item is None or len(points) < 2:
            return
        obj = AnnotationObject(
            rect=Rect.from_points(points),
            annotation=AnnotationKind.INK,
            color=self._tool_state.color_for(AnnotationKind.INK),
            stroke_width=self._tool_state.ink_width,
            strokes=[points],
            author=self._tool_state.author,
        )
        obj.rect = obj.recompute_rect()
        self._push_new_object(page_item, obj, "Add Freehand")

    # ------------------------------------------------------------------
    # Editing helpers
    # ------------------------------------------------------------------
    def request_note_edit(self, item: ObjectItem) -> None:
        self.note_edit_requested.emit(item)

    def edit_selected_text(self) -> bool:
        for item in self.selected_items():
            if isinstance(item, TextObjectItem):
                item.begin_editing()
                return True
        return False

    def edit_selected_note(self) -> bool:
        """Open the note dialog for the selected annotation, if there is one."""
        for item in self.selected_items():
            if isinstance(item.object, AnnotationObject):
                self.request_note_edit(item)
                return True
        return False

    def _finish_text_editing(self) -> None:
        for item in self._item_index.values():
            if isinstance(item, TextObjectItem) and item.is_editing:
                item.end_editing(commit=True)

    @property
    def is_editing_text(self) -> bool:
        return any(
            isinstance(item, TextObjectItem) and item.is_editing
            for item in self._item_index.values()
        )

    # ------------------------------------------------------------------
    # Search overlay
    # ------------------------------------------------------------------
    def set_search_hits(
        self, hits: dict[int, list[Rect]], current: tuple[int, int] | None = None
    ) -> None:
        for item in self._page_items:
            page_hits = hits.get(item.index, [])
            index = current[1] if current is not None and current[0] == item.index else -1
            item.set_search_hits(page_hits, index)

    def clear_search_hits(self) -> None:
        for item in self._page_items:
            item.clear_search_hits()

    def reveal_rect(self, page_index: int, rect: Rect) -> None:
        """Scroll a base-space rectangle into view."""
        page_item = self._page_item(page_index)
        if page_item is None:
            return
        top_left = page_item.content.mapToScene(QPointF(rect.x0, rect.y0))
        bottom_right = page_item.content.mapToScene(QPointF(rect.x1, rect.y1))
        self.ensureVisible(QRectF(top_left, bottom_right).normalized(), 80, 80)
        self._set_current_page(page_index)

    # ------------------------------------------------------------------
    # Keyboard
    # ------------------------------------------------------------------
    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 - Qt naming
        key = event.key()
        if key == Qt.Key.Key_Space and not event.isAutoRepeat() and not self.is_editing_text:
            self._space_pan = True
            self._update_cursor()
            event.accept()
            return
        if key == Qt.Key.Key_Escape:
            if self._draft_page is not None:
                self._cancel_draft()
            elif self.is_editing_text:
                self._finish_text_editing()
            else:
                self.clear_selection()
            event.accept()
            return
        if key in (Qt.Key.Key_Return, Qt.Key.Key_F2) and self.edit_selected_text():
            event.accept()
            return
        if key in (
            Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Up, Qt.Key.Key_Down
        ) and self._nudge_selection(event):
            event.accept()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event: QKeyEvent) -> None:  # noqa: N802 - Qt naming
        if event.key() == Qt.Key.Key_Space and not event.isAutoRepeat():
            self._space_pan = False
            self._update_cursor()
            event.accept()
            return
        super().keyReleaseEvent(event)

    def _nudge_selection(self, event: QKeyEvent) -> bool:
        """Arrow keys move the selection; Shift makes the step larger."""
        items = self.selected_items()
        if not items or self.is_editing_text:
            return False
        step = 10.0 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1.0
        dx = dy = 0.0
        key = event.key()
        if key == Qt.Key.Key_Left:
            dx = -step
        elif key == Qt.Key.Key_Right:
            dx = step
        elif key == Qt.Key.Key_Up:
            dy = -step
        else:
            dy = step

        from orion.commands.object_commands import MoveObjectsCommand

        page_index = items[0].page_index
        ids = [item.object.id for item in items if item.page_index == page_index]
        self.history.push(MoveObjectsCommand(self.document, page_index, ids, dx, dy))
        return True

    # ------------------------------------------------------------------
    # Drag and drop
    # ------------------------------------------------------------------
    def dragEnterEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:  # noqa: N802 - Qt naming
        urls = event.mimeData().urls() if event.mimeData().hasUrls() else []
        if not urls:
            super().dropEvent(event)
            return
        event.acceptProposedAction()
        scene_pos = self.mapToScene(event.position().toPoint())
        page_item = self.nearest_page_item(scene_pos)
        self.files_dropped.emit(
            [url.toLocalFile() for url in urls if url.isLocalFile()],
            page_item.index if page_item else self._current_page,
            self._to_base(page_item, scene_pos) if page_item else Point(),
        )


def _fraction(point: Point, rect: Rect) -> tuple[float, float]:
    """Normalised position of *point* inside *rect* (used for line endpoints)."""
    width = rect.width or 1.0
    height = rect.height or 1.0
    return (
        max(0.0, min(1.0, (point.x - rect.x0) / width)),
        max(0.0, min(1.0, (point.y - rect.y0) / height)),
    )


def _next_step(zoom: float, direction: int) -> float:
    """Move to the next preset zoom level in *direction*."""
    if direction > 0:
        for step in ZOOM_STEPS:
            if step > zoom + 1e-4:
                return step
        return min(MAX_ZOOM, zoom * 1.25)
    for step in reversed(ZOOM_STEPS):
        if step < zoom - 1e-4:
            return step
    return max(MIN_ZOOM, zoom * 0.8)
