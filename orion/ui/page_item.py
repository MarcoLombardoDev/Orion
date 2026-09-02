# Orion — PDF Editor for Desktop
# Copyright (C) 2026 Marco Lombardo
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# Distributed WITHOUT ANY WARRANTY; see LICENSE for the full terms.
# A commercial licence, without the AGPL's obligations, is available for use
# in proprietary or closed-source products — see COMMERCIAL-LICENSE.md.

"""The graphics item that draws one original PDF page (spec §8, §29).

The page raster and the objects the user adds are kept strictly apart: this
item paints *only* the original content, and hosts a child layer that holds the
object items.  That child layer carries the base -> display rotation, which is
why rotating a page never touches a single object coordinate.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QTransform
from PySide6.QtWidgets import QGraphicsItem, QStyleOptionGraphicsItem, QWidget

from orion.document.page import Page
from orion.pdf.renderer import RenderedPage, RenderRequest
from orion.ui.render_bridge import to_qimage
from orion.ui.theme import Theme
from orion.utils.geometry import Rect

__all__ = ["PageItem", "ContentLayer", "base_to_display_transform"]

#: Z values keep the layers unambiguous.
Z_PAGE = 0
Z_CONTENT = 10
Z_OVERLAY = 20


def base_to_display_transform(page: Page) -> QTransform:
    """Transform mapping base page space onto the rotated display space.

    Mirrors :meth:`orion.document.page.Page.base_to_display`; the two are kept
    consistent by ``tests/test_canvas.py``.
    """
    rotation = page.rotation % 360
    width, height = page.base_size.width, page.base_size.height
    if rotation == 90:
        return QTransform(0.0, 1.0, -1.0, 0.0, height, 0.0)
    if rotation == 180:
        return QTransform(-1.0, 0.0, 0.0, -1.0, width, height)
    if rotation == 270:
        return QTransform(0.0, -1.0, 1.0, 0.0, 0.0, width)
    return QTransform()


class ContentLayer(QGraphicsItem):
    """Parent of every object item on a page; carries the page rotation."""

    def __init__(self, parent: PageItem) -> None:
        super().__init__(parent)
        self.setZValue(Z_CONTENT)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemHasNoContents, True)

    def boundingRect(self) -> QRectF:  # noqa: N802 - Qt naming
        return QRectF()

    def paint(self, painter, option, widget=None) -> None:  # pragma: no cover - no contents
        return None


class PageItem(QGraphicsItem):
    """Draws one page's original content, lazily and at the right resolution."""

    def __init__(self, page: Page, index: int, canvas) -> None:
        super().__init__()
        self._page = page
        self._index = index
        self._canvas = canvas
        self._image: QImage | None = None
        self._image_scale = 0.0
        self._requested_scale = 0.0
        #: The replaced set the raster on screen was made with, so a page-text
        #: edit is noticed even though nothing about the zoom has changed.
        self._image_replaced: tuple[int, ...] | None = None
        self._search_hits: list[Rect] = []
        self._current_hit: int = -1

        self.setZValue(Z_PAGE)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemUsesExtendedStyleOption, True)
        self.setCacheMode(QGraphicsItem.CacheMode.NoCache)
        self.content = ContentLayer(self)
        self.update_transform()

    # -- model ------------------------------------------------------------
    @property
    def page(self) -> Page:
        return self._page

    @property
    def index(self) -> int:
        return self._index

    def set_index(self, index: int) -> None:
        self._index = index

    def update_transform(self) -> None:
        """Re-apply the page rotation to the object layer."""
        self.content.setTransform(base_to_display_transform(self._page))
        self.prepareGeometryChange()

    def invalidate_raster(self) -> None:
        self._image = None
        self._image_scale = 0.0
        self._requested_scale = 0.0
        self._image_replaced = None
        self.update()

    # -- geometry ---------------------------------------------------------
    def boundingRect(self) -> QRectF:  # noqa: N802 - Qt naming
        size = self._page.display_size
        return QRectF(0.0, 0.0, size.width, size.height)

    def page_rect(self) -> QRectF:
        return self.boundingRect()

    # -- search overlay ---------------------------------------------------
    def set_search_hits(self, hits: list[Rect], current: int = -1) -> None:
        self._search_hits = hits
        self._current_hit = current
        self.update()

    def clear_search_hits(self) -> None:
        if self._search_hits:
            self._search_hits = []
            self._current_hit = -1
            self.update()

    # -- painting ---------------------------------------------------------
    def deliver(self, request: RenderRequest, rendered: RenderedPage) -> None:
        """Called on the GUI thread when a background render finishes."""
        if request.page_id != self._page.id or request.rotation != self._page.rotation:
            return
        if rendered.scale < self._image_scale and self._image is not None:
            return  # a sharper raster is already on screen
        self._image = to_qimage(rendered)
        self._image_scale = rendered.scale
        self._image_replaced = request.replaced
        self.update()

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionGraphicsItem,
        widget: QWidget | None = None,
    ) -> None:
        rect = self.boundingRect()
        theme: Theme = self._canvas.theme

        painter.fillRect(rect, QColor(Qt.GlobalColor.white))

        scale = option.levelOfDetailFromTransform(painter.worldTransform())
        self._ensure_raster(scale)

        if self._image is not None:
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            painter.drawImage(rect, self._image)
        else:
            self._paint_placeholder(painter, rect, theme)

        self._paint_search_hits(painter, theme)

        pen = QPen(theme.color("border"))
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(rect)

    def _ensure_raster(self, scale: float) -> None:
        """Ask for a fresh raster when the zoom, or the page itself, has moved on.

        Rewriting a line of the document's own text changes what the page
        looks like without changing its size, its rotation or the zoom — so
        without the second test here the stale picture stays on screen, still
        showing the words the edit removed.
        """
        request = self._canvas.render_service.renderer.request_for(self._page, scale)
        stale = request.replaced != self._image_replaced
        if not stale:
            if abs(request.scale - self._image_scale) < 1e-3:
                return
            if abs(request.scale - self._requested_scale) < 1e-3 and self._image is not None:
                return
        self._requested_scale = request.scale
        rendered = self._canvas.render_service.request(request)
        if rendered is not None:
            self._image = to_qimage(rendered)
            self._image_scale = rendered.scale
            self._image_replaced = request.replaced

    def _paint_placeholder(self, painter: QPainter, rect: QRectF, theme: Theme) -> None:
        """A calm placeholder while the page is still rendering."""
        painter.save()
        pen = QPen(theme.color("border"))
        pen.setCosmetic(True)
        pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)
        centre = rect.center()
        painter.drawLine(QPointF(centre.x() - 18, centre.y()), QPointF(centre.x() + 18, centre.y()))
        painter.restore()

    def _paint_search_hits(self, painter: QPainter, theme: Theme) -> None:
        if not self._search_hits:
            return
        painter.save()
        painter.setPen(Qt.PenStyle.NoPen)
        transform = base_to_display_transform(self._page)
        for index, hit in enumerate(self._search_hits):
            colour = QColor(
                theme.search_current if index == self._current_hit else theme.search_hit
            )
            colour.setAlpha(150 if index == self._current_hit else 90)
            painter.setBrush(colour)
            painter.drawRect(_map_rect(transform, hit))
        painter.restore()


def _map_rect(transform: QTransform, rect: Rect) -> QRectF:
    return transform.mapRect(QRectF(rect.x0, rect.y0, rect.width, rect.height))
