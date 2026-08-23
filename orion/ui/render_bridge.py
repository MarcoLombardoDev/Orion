# Orion — PDF Editor for Desktop
# Copyright (C) 2026 Marco Lombardo
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# Distributed WITHOUT ANY WARRANTY; see LICENSE for the full terms.
# A commercial licence, without the AGPL's obligations, is available for use
# in proprietary or closed-source products — see COMMERCIAL-LICENSE.md.

"""The one place that turns engine output into Qt objects (spec §24).

The renderer produces raw RGB buffers precisely so that :mod:`orion.pdf` stays
Qt-free; this module adapts them, and runs rasterisation on a ``QThreadPool``
so a slow page never blocks the GUI thread.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal
from PySide6.QtGui import QImage, QPixmap

from orion.pdf.renderer import PageRenderer, RenderedPage, RenderRequest

log = logging.getLogger(__name__)

__all__ = ["to_qimage", "to_qpixmap", "RenderService"]


def to_qimage(page: RenderedPage) -> QImage:
    """Wrap a rendered page as a ``QImage``.

    ``copy()`` is deliberate: the ``QImage`` must own its memory, because the
    cache entry it came from can be evicted at any moment.
    """
    image = QImage(
        page.samples,
        page.width,
        page.height,
        page.stride,
        QImage.Format.Format_RGB888,
    )
    return image.copy()


def to_qpixmap(page: RenderedPage) -> QPixmap:
    return QPixmap.fromImage(to_qimage(page))


class _RenderTask(QRunnable):
    """A single rasterisation job."""

    def __init__(self, service: RenderService, request: RenderRequest, token: int) -> None:
        super().__init__()
        self._service = service
        self._request = request
        self._token = token
        self.setAutoDelete(True)

    def run(self) -> None:  # pragma: no cover - exercised via RenderService
        if self._service.is_cancelled(self._token):
            self._service._finish(self._request)
            return
        try:
            page = self._service.renderer.render(self._request)
        except MemoryError:
            log.warning("Out of memory rendering page %s", self._request.source_index)
            self._service.failed.emit(self._request, "Not enough memory to render this page.")
            self._service._finish(self._request)
            return
        except Exception as exc:
            log.exception("Rendering failed")
            self._service.failed.emit(self._request, str(exc))
            self._service._finish(self._request)
            return
        self._service._finish(self._request)
        if not self._service.is_cancelled(self._token):
            self._service.rendered.emit(self._request, page)


class RenderService(QObject):
    """Asynchronous front end for :class:`~orion.pdf.renderer.PageRenderer`.

    Results arrive on the GUI thread through :attr:`rendered`.  Requests are
    de-duplicated, so scrolling quickly past twenty pages does not queue twenty
    identical jobs, and a *generation token* lets the view cancel everything
    that is already stale after a zoom change.
    """

    rendered = Signal(object, object)  # (RenderRequest, RenderedPage)
    failed = Signal(object, str)

    def __init__(self, renderer: PageRenderer, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.renderer = renderer
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(max(2, min(4, QThreadPool.globalInstance().maxThreadCount())))
        self._pending: set[tuple] = set()
        self._generation = 0

    # -- queries -----------------------------------------------------------
    def cached(self, request: RenderRequest) -> RenderedPage | None:
        return self.renderer.cached(request)

    def is_cancelled(self, token: int) -> bool:
        return token != self._generation

    # -- control -----------------------------------------------------------
    def request(self, request: RenderRequest) -> RenderedPage | None:
        """Return the page if it is already cached, otherwise queue a render."""
        page = self.renderer.cached(request)
        if page is not None:
            return page
        key = request.cache_key
        if key in self._pending:
            return None
        self._pending.add(key)
        self._pool.start(_RenderTask(self, request, self._generation))
        return None

    def invalidate(self) -> None:
        """Abandon in-flight work — used when the zoom or the document changes."""
        self._generation += 1
        self._pending.clear()

    def shutdown(self) -> None:
        self.invalidate()
        self._pool.clear()
        self._pool.waitForDone(2000)

    def _finish(self, request: RenderRequest) -> None:
        self._pending.discard(request.cache_key)
