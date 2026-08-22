"""The page thumbnail panel (spec §7, §16).

Thumbnails render asynchronously at a small fixed scale and live in their own
cache, so scrolling the panel never competes with the main canvas for memory.
Reordering is drag & drop and produces one undoable command.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QModelIndex, QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QWidget,
)

from orion.document.document import Document
from orion.pdf.renderer import PageRenderer, RenderedPage, RenderRequest
from orion.ui.render_bridge import RenderService, to_qimage
from orion.ui.theme import LIGHT, Theme

log = logging.getLogger(__name__)

__all__ = ["ThumbnailPanel", "THUMBNAIL_WIDTH"]

#: Thumbnails are rendered to this width in points; the cache stays tiny.
THUMBNAIL_WIDTH = 132
LABEL_HEIGHT = 18
ITEM_PADDING = 10


class _ThumbnailDelegate(QStyledItemDelegate):
    """Draws the page preview, its border and its number."""

    def __init__(self, panel: ThumbnailPanel) -> None:
        super().__init__(panel)
        self._panel = panel

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        theme = self._panel.theme
        rect = option.rect.adjusted(ITEM_PADDING // 2, ITEM_PADDING // 2, -ITEM_PADDING // 2, -2)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        preview_rect = QRect(rect.x(), rect.y(), rect.width(), rect.height() - LABEL_HEIGHT)
        pixmap: QPixmap | None = index.data(Qt.ItemDataRole.DecorationRole)
        if isinstance(pixmap, QPixmap) and not pixmap.isNull():
            scaled = pixmap.size().scaled(preview_rect.size(), Qt.AspectRatioMode.KeepAspectRatio)
            target = QRect(
                preview_rect.x() + (preview_rect.width() - scaled.width()) // 2,
                preview_rect.y() + (preview_rect.height() - scaled.height()),
                scaled.width(),
                scaled.height(),
            )
            painter.fillRect(target, QColor(Qt.GlobalColor.white))
            painter.drawPixmap(target, pixmap)
        else:
            target = preview_rect
            painter.fillRect(target, theme.color("surface_alt"))

        pen = QPen(theme.color("accent") if selected else theme.color("border"))
        pen.setWidth(2 if selected else 1)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(target.adjusted(0, 0, -1, -1))

        painter.setPen(theme.color("accent") if selected else theme.color("text_muted"))
        label_rect = QRect(rect.x(), rect.bottom() - LABEL_HEIGHT, rect.width(), LABEL_HEIGHT)
        painter.drawText(
            label_rect,
            Qt.AlignmentFlag.AlignCenter,
            str(index.data(Qt.ItemDataRole.DisplayRole) or ""),
        )
        painter.restore()


class ThumbnailPanel(QListWidget):
    """One row per page, with drag & drop reordering and a context menu."""

    page_activated = Signal(int)
    pages_reordered = Signal(int, int)  # (from_index, to_index)
    context_action = Signal(str, list)  # (action name, page indices)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._document: Document | None = None
        self._render_service: RenderService | None = None
        self._theme: Theme = LIGHT
        self._pending: dict[str, int] = {}
        self._updating = False

        self.setViewMode(QListWidget.ViewMode.ListMode)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setItemDelegate(_ThumbnailDelegate(self))
        self.setUniformItemSizes(False)
        self.setSpacing(2)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setMinimumWidth(THUMBNAIL_WIDTH + 3 * ITEM_PADDING)

        self.customContextMenuRequested.connect(self._show_context_menu)
        self.itemSelectionChanged.connect(self._on_selection_changed)
        self.model().rowsMoved.connect(self._on_rows_moved)

    # -- wiring ------------------------------------------------------------
    @property
    def theme(self) -> Theme:
        return self._theme

    def apply_theme(self, theme: Theme) -> None:
        self._theme = theme
        self.viewport().update()

    def set_session(self, session) -> None:
        self._document = session.document
        if self._render_service is not None:
            self._render_service.shutdown()
        # A dedicated renderer keeps thumbnail rasters out of the canvas cache.
        thumb_renderer = PageRenderer(cache_bytes=24 * 1024 * 1024)
        for source in session.document.sources.values():
            handle = session.renderer.source_handle(source.key)
            if handle is not None:
                thumb_renderer.register_source(source, handle)
        self._render_service = RenderService(thumb_renderer, self)
        self._render_service.rendered.connect(self._on_rendered)
        self.reload()

    def close_session(self) -> None:
        if self._render_service is not None:
            self._render_service.shutdown()
            self._render_service = None
        self._document = None
        self.clear()

    # -- population --------------------------------------------------------
    def reload(self) -> None:
        self._updating = True
        try:
            self.clear()
            self._pending.clear()
            if self._document is None:
                return
            for index, page in enumerate(self._document.pages):
                item = QListWidgetItem(str(index + 1))
                item.setSizeHint(self._size_hint_for(index))
                item.setData(Qt.ItemDataRole.UserRole, page.id)
                self.addItem(item)
            self._request_visible()
        finally:
            self._updating = False

    def _size_hint_for(self, index: int) -> QSize:
        page = self._document.pages[index] if self._document else None
        if page is None:
            return QSize(THUMBNAIL_WIDTH, THUMBNAIL_WIDTH + LABEL_HEIGHT)
        size = page.display_size
        height = THUMBNAIL_WIDTH * (size.height / max(size.width, 1.0))
        return QSize(
            THUMBNAIL_WIDTH + ITEM_PADDING,
            int(height) + LABEL_HEIGHT + ITEM_PADDING,
        )

    def refresh_page(self, index: int) -> None:
        item = self.item(index)
        if item is None or self._document is None:
            return
        item.setSizeHint(self._size_hint_for(index))
        item.setData(Qt.ItemDataRole.DecorationRole, None)
        self._request(index)

    def refresh_all(self) -> None:
        for index in range(self.count()):
            self.refresh_page(index)

    def _request_visible(self) -> None:
        for index in range(self.count()):
            self._request(index)

    def _request(self, index: int) -> None:
        if self._document is None or self._render_service is None:
            return
        page = self._document.page_at(index)
        if page is None:
            return
        scale = THUMBNAIL_WIDTH / max(page.display_size.width, 1.0)
        request = self._render_service.renderer.request_for(page, scale)
        self._pending[page.id] = index
        rendered = self._render_service.request(request)
        if rendered is not None:
            self._apply(page.id, rendered)

    def _on_rendered(self, request: RenderRequest, rendered: RenderedPage) -> None:
        self._apply(request.page_id, rendered)

    def _apply(self, page_id: str, rendered: RenderedPage) -> None:
        index = self._pending.get(page_id)
        if index is None or self._document is None:
            return
        page = self._document.page_at(index)
        if page is None or page.id != page_id:
            # Pages moved while the render was in flight; find it again.
            index = self._document.index_of_page(page_id)
            if index < 0:
                return
        item = self.item(index)
        if item is None:
            return
        item.setData(Qt.ItemDataRole.DecorationRole, QPixmap.fromImage(to_qimage(rendered)))
        self.viewport().update()

    # -- selection ---------------------------------------------------------
    def selected_pages(self) -> list[int]:
        return sorted(self.row(item) for item in self.selectedItems())

    def set_current_page(self, index: int) -> None:
        if self._updating or index < 0 or index >= self.count():
            return
        self._updating = True
        try:
            self.setCurrentRow(index)
            self.scrollToItem(self.item(index), QAbstractItemView.ScrollHint.EnsureVisible)
        finally:
            self._updating = False

    def _on_selection_changed(self) -> None:
        if self._updating:
            return
        rows = self.selected_pages()
        if rows:
            self.page_activated.emit(rows[0])

    def _on_rows_moved(self, _parent, start: int, _end: int, _dest, row: int) -> None:
        if self._updating:
            return
        target = row - 1 if row > start else row
        if target != start:
            self.pages_reordered.emit(start, target)

    # -- context menu ------------------------------------------------------
    def _show_context_menu(self, position: QPoint) -> None:
        if self._document is None:
            return
        rows = self.selected_pages()
        clicked = self.indexAt(position)
        if clicked.isValid() and clicked.row() not in rows:
            self.setCurrentRow(clicked.row())
            rows = [clicked.row()]
        if not rows:
            return

        from orion.ui.icons import icon

        menu = QMenu(self)
        entries = [
            ("Rotate Left", "rotate_left", "rotate_left"),
            ("Rotate Right", "rotate_right", "rotate_right"),
            (None, None, None),
            ("Duplicate", "duplicate", "duplicate"),
            ("Insert Blank Page After", "page_add", "insert_after"),
            ("Extract to New PDF…", "extract", "extract"),
            (None, None, None),
            ("Delete", "page_delete", "delete"),
        ]
        for label, icon_name, action_name in entries:
            if label is None:
                menu.addSeparator()
                continue
            action = menu.addAction(icon(icon_name), label)
            action.triggered.connect(
                lambda _checked=False, name=action_name: self.context_action.emit(name, rows)
            )
        menu.exec(self.viewport().mapToGlobal(position))
