"""Page rasterisation with a byte-bounded LRU cache (spec §6, §24).

The renderer is the only component that decides how much memory rendered pages
may occupy.  The cache is bounded **by bytes, not by page count**, because a
page at 25% and the same page at 400% differ by a factor of 256 in size — a
count-based cache would happily use several gigabytes.
"""

from __future__ import annotations

import logging
import threading
from collections import OrderedDict
from contextlib import suppress
from dataclasses import dataclass

import pymupdf

from orion.document.document import Document, DocumentSource
from orion.document.page import Page
from orion.pdf.errors import PdfReadError
from orion.pdf.reader import OpenedPdf, open_pdf
from orion.utils.geometry import Rect, Size

log = logging.getLogger(__name__)

__all__ = ["RenderedPage", "RenderRequest", "PageRenderer", "DEFAULT_CACHE_BYTES"]

#: Total budget for cached page rasters.  256 MB is roughly 20 A4 pages at 300%.
DEFAULT_CACHE_BYTES = 256 * 1024 * 1024

#: Scales are snapped to this step so a continuous zoom gesture reuses cache
#: entries instead of allocating a new raster for every intermediate value.
SCALE_QUANTUM = 0.05

MAX_SCALE = 16.0
MIN_SCALE = 0.02


@dataclass(frozen=True, slots=True)
class RenderRequest:
    page_id: str
    source_key: str | None
    source_index: int
    rotation: int
    scale: float
    size: Size

    @property
    def cache_key(self) -> tuple:
        return (self.source_key, self.source_index, self.rotation, round(self.scale, 4))


@dataclass(slots=True)
class RenderedPage:
    """A rasterised page as a raw RGB888 buffer (no Qt types here)."""

    key: tuple
    width: int
    height: int
    stride: int
    samples: bytes
    scale: float

    @property
    def nbytes(self) -> int:
        return len(self.samples)


def quantize_scale(scale: float) -> float:
    """Snap *scale* to the cache grid and clamp it to a sane range."""
    scale = max(MIN_SCALE, min(MAX_SCALE, scale))
    return round(round(scale / SCALE_QUANTUM) * SCALE_QUANTUM, 4)


class PageRenderer:
    """Rasterises pages on demand and caches the results.

    Thread-safe: `render` may be called from worker threads.  Each opened PDF
    keeps its own re-entrant lock, held for the whole PyMuPDF call.
    """

    def __init__(self, cache_bytes: int = DEFAULT_CACHE_BYTES) -> None:
        self._cache: OrderedDict[tuple, RenderedPage] = OrderedDict()
        self._cache_bytes = 0
        self._cache_limit = cache_bytes
        self._cache_lock = threading.RLock()
        self._sources: dict[str, OpenedPdf] = {}
        self._sources_lock = threading.RLock()
        self._blank_color = (1.0, 1.0, 1.0)

    # -- source management -----------------------------------------------
    def register_source(self, source: DocumentSource, opened: OpenedPdf | None = None) -> None:
        """Attach an already-open handle, or remember a path to open lazily."""
        with self._sources_lock:
            if opened is not None:
                previous = self._sources.get(source.key)
                if previous is not None and previous is not opened:
                    previous.close()
                self._sources[source.key] = opened
            elif source.key not in self._sources and source.path is not None:
                self._sources[source.key] = open_pdf(source.path)

    def register_document(self, document: Document) -> None:
        for source in document.sources.values():
            if source.path is not None or source.data is not None:
                try:
                    self.register_source(source)
                except PdfReadError:
                    log.warning("Source %s is not readable; its pages render blank", source.path)

    def source_handle(self, source_key: str) -> OpenedPdf | None:
        with self._sources_lock:
            return self._sources.get(source_key)

    def close_source(self, source_key: str) -> None:
        with self._sources_lock:
            opened = self._sources.pop(source_key, None)
        if opened is not None:
            opened.close()
        self.invalidate_source(source_key)

    def close_all(self) -> None:
        """Release every file handle — required before overwriting a source."""
        with self._sources_lock:
            handles = list(self._sources.values())
            self._sources.clear()
        for handle in handles:
            handle.close()
        self.clear_cache()

    # -- cache -----------------------------------------------------------
    def clear_cache(self) -> None:
        with self._cache_lock:
            self._cache.clear()
            self._cache_bytes = 0

    def invalidate_source(self, source_key: str) -> None:
        with self._cache_lock:
            for key in [k for k in self._cache if k[0] == source_key]:
                entry = self._cache.pop(key)
                self._cache_bytes -= entry.nbytes

    @property
    def cache_bytes(self) -> int:
        return self._cache_bytes

    def set_cache_limit(self, limit: int) -> None:
        self._cache_limit = max(16 * 1024 * 1024, limit)
        self._trim()

    def _store(self, entry: RenderedPage) -> None:
        with self._cache_lock:
            if entry.key in self._cache:
                self._cache_bytes -= self._cache[entry.key].nbytes
            self._cache[entry.key] = entry
            self._cache_bytes += entry.nbytes
            self._cache.move_to_end(entry.key)
            self._trim_locked()

    def _trim(self) -> None:
        with self._cache_lock:
            self._trim_locked()

    def _trim_locked(self) -> None:
        while self._cache_bytes > self._cache_limit and len(self._cache) > 1:
            _, evicted = self._cache.popitem(last=False)
            self._cache_bytes -= evicted.nbytes

    def cached(self, request: RenderRequest) -> RenderedPage | None:
        with self._cache_lock:
            entry = self._cache.get(request.cache_key)
            if entry is not None:
                self._cache.move_to_end(request.cache_key)
            return entry

    # -- rendering -------------------------------------------------------
    def request_for(self, page: Page, scale: float) -> RenderRequest:
        return RenderRequest(
            page_id=page.id,
            source_key=page.source.source_key if page.source else None,
            source_index=page.source.index if page.source else -1,
            rotation=page.rotation,
            scale=quantize_scale(scale),
            size=page.display_size,
        )

    def render(self, request: RenderRequest, *, use_cache: bool = True) -> RenderedPage:
        """Rasterise a page.  Safe to call from a worker thread."""
        if use_cache:
            entry = self.cached(request)
            if entry is not None:
                return entry

        if request.source_key is None:
            entry = self._render_blank(request)
        else:
            entry = self._render_source(request)

        if use_cache:
            self._store(entry)
        return entry

    def _render_blank(self, request: RenderRequest) -> RenderedPage:
        width = max(1, int(round(request.size.width * request.scale)))
        height = max(1, int(round(request.size.height * request.scale)))
        stride = width * 3
        return RenderedPage(
            key=request.cache_key,
            width=width,
            height=height,
            stride=stride,
            samples=b"\xff" * (stride * height),
            scale=request.scale,
        )

    def _render_source(self, request: RenderRequest) -> RenderedPage:
        opened = self.source_handle(request.source_key or "")
        if opened is None or opened.doc.is_closed:
            log.debug("No handle for source %s; rendering blank", request.source_key)
            return self._render_blank(request)

        matrix = pymupdf.Matrix(request.scale, request.scale)
        with opened.lock:
            try:
                page = opened.doc.load_page(request.source_index)
                if request.rotation:
                    # Orion's rotation is applied on top of the source /Rotate.
                    matrix = matrix * pymupdf.Matrix(-request.rotation)
                pixmap = page.get_pixmap(matrix=matrix, alpha=False, colorspace=pymupdf.csRGB)
            except MemoryError:
                raise
            except Exception as exc:
                log.warning("Could not render page %d: %s", request.source_index, exc)
                return self._render_blank(request)

        return RenderedPage(
            key=request.cache_key,
            width=pixmap.width,
            height=pixmap.height,
            stride=pixmap.stride,
            samples=bytes(pixmap.samples),
            scale=request.scale,
        )

    # -- text --------------------------------------------------------------
    def search_page(self, page: Page, needle: str, *, limit: int = 200) -> list[Rect]:
        """Find *needle* on *page*, returning hit rectangles in base page space."""
        if not needle or page.source is None:
            return []
        opened = self.source_handle(page.source.source_key)
        if opened is None or opened.doc.is_closed:
            return []
        from orion.pdf.coordinates import from_pdf_rect

        with opened.lock:
            try:
                pdf_page = opened.doc.load_page(page.source.index)
                hits = pdf_page.search_for(needle)[:limit]
                return [from_pdf_rect(pdf_page, hit) for hit in hits]
            except Exception as exc:
                log.debug("Search failed on page %d: %s", page.source.index, exc)
                return []

    def page_text(self, page: Page) -> str:
        if page.source is None:
            return ""
        opened = self.source_handle(page.source.source_key)
        if opened is None or opened.doc.is_closed:
            return ""
        with opened.lock:
            try:
                return opened.doc.load_page(page.source.index).get_text()
            except Exception:
                return ""

    def text_lines_in(self, page: Page, rect: Rect) -> list[Rect]:
        """Line rectangles of the page text intersecting *rect* (base space).

        Used by the highlight/underline/strikeout tools so a markup annotation
        snaps to the actual text lines rather than to the raw drag rectangle.
        """
        if page.source is None:
            return []
        opened = self.source_handle(page.source.source_key)
        if opened is None or opened.doc.is_closed:
            return []
        from orion.pdf.coordinates import from_pdf_rect, to_pdf_rect

        with opened.lock:
            try:
                pdf_page = opened.doc.load_page(page.source.index)
                selection = to_pdf_rect(pdf_page, rect)
                words = pdf_page.get_text("words")
            except Exception:
                return []

        lines: dict[tuple[int, int], pymupdf.Rect] = {}
        for x0, y0, x1, y1, _text, block, line, _word in words:
            word_rect = pymupdf.Rect(x0, y0, x1, y1)
            if not word_rect.intersects(selection):
                continue
            key = (block, line)
            lines[key] = word_rect if key not in lines else lines[key] | word_rect

        with opened.lock:
            pdf_page = opened.doc.load_page(page.source.index)
            return [from_pdf_rect(pdf_page, r) for r in lines.values()]

    def __del__(self) -> None:  # pragma: no cover - best-effort cleanup
        with suppress(Exception):
            self.close_all()
