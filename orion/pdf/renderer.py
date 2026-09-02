# Orion — PDF Editor for Desktop
# Copyright (C) 2026 Marco Lombardo
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# Distributed WITHOUT ANY WARRANTY; see LICENSE for the full terms.
# A commercial licence, without the AGPL's obligations, is available for use
# in proprietary or closed-source products — see COMMERCIAL-LICENSE.md.

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
from collections.abc import Sequence
from contextlib import suppress
from dataclasses import dataclass

import pypdfium2.raw as pdfium_raw

from orion.document.document import Document, DocumentSource
from orion.document.page import Page
from orion.pdf.coordinates import from_pdf_rect, to_pdf_rect
from orion.pdf.errors import PdfReadError
from orion.pdf.reader import OpenedPdf, open_pdf
from orion.pdf.text_edit import SourceTextLine, read_text_lines
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
    #: Source page objects the user has replaced, which must not be drawn.
    replaced: tuple[int, ...] = ()

    @property
    def cache_key(self) -> tuple:
        return (
            self.source_key,
            self.source_index,
            self.rotation,
            round(self.scale, 4),
            self.replaced,
        )


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
    """Snap *scale* to the cache grid and clamp it to a sane range.

    The clamp is applied *after* snapping as well: a scale below half a
    quantum would otherwise round down to zero and render a 1x1 raster.
    """
    scale = max(MIN_SCALE, min(MAX_SCALE, scale))
    snapped = round(round(scale / SCALE_QUANTUM) * SCALE_QUANTUM, 4)
    return max(MIN_SCALE, min(MAX_SCALE, snapped))


def _overlaps(a: Sequence[float], b: Sequence[float]) -> bool:
    """Do two ``(x0, y0, x1, y1)`` boxes share any area?

    Both are already normalised, so this is the plain interval test on each
    axis. Touching edges do not count: a selection dragged to end exactly on a
    line's top edge should not pick that line up.
    """
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


class PageRenderer:
    """Rasterises pages on demand and caches the results.

    Thread-safe: `render` may be called from worker threads.  Each opened PDF
    keeps its own re-entrant lock, held for the whole pdfium call.
    """

    def __init__(self, cache_bytes: int = DEFAULT_CACHE_BYTES) -> None:
        self._cache: OrderedDict[tuple, RenderedPage] = OrderedDict()
        self._cache_bytes = 0
        self._cache_limit = cache_bytes
        self._cache_lock = threading.RLock()
        self._sources: dict[str, OpenedPdf] = {}
        self._sources_lock = threading.RLock()
        self._blank_color = (1.0, 1.0, 1.0)
        #: Which source objects are currently switched off, per opened page,
        #: so a request only has to touch what actually changed.
        self._deactivated: dict[tuple[str | None, int], frozenset[int]] = {}

    # -- source management -----------------------------------------------
    def register_source(self, source: DocumentSource, opened: OpenedPdf | None = None) -> None:
        """Attach an already-open handle, or open the source's path lazily.

        A renderer owns every handle it holds and closes them all in
        :meth:`close_all`, so a handle must be given to exactly one renderer.
        """
        with self._sources_lock:
            if opened is not None:
                previous = self._sources.get(source.key)
                if previous is not None and previous is not opened:
                    previous.close()
                self._sources[source.key] = opened
                self._forget_deactivated(source.key)
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

    def _forget_deactivated(self, source_key: str) -> None:
        """A fresh handle draws everything again, whatever the old one hid."""
        for key in [k for k in self._deactivated if k[0] == source_key]:
            del self._deactivated[key]

    def close_source(self, source_key: str) -> None:
        with self._sources_lock:
            self._forget_deactivated(source_key)
            opened = self._sources.pop(source_key, None)
        if opened is not None:
            opened.close()
        self.invalidate_source(source_key)

    def close_all(self) -> None:
        """Release every file handle — required before overwriting a source."""
        with self._sources_lock:
            handles = list(self._sources.values())
            self._sources.clear()
            self._deactivated.clear()
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
            replaced=tuple(sorted(page.replaced_text)),
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
        if opened is None or opened.is_closed:
            log.debug("No handle for source %s; rendering blank", request.source_key)
            return self._render_blank(request)

        with opened.lock:
            try:
                page = opened.doc[request.source_index]
                self._apply_replacements(opened, page, request)
                # Orion's rotation is applied on top of the source /Rotate, and
                # pdfium turns the rendered page clockwise for a positive
                # angle — the same direction Orion means. Verified by rendering
                # a marked page in tests/test_renderer.py rather than assumed.
                #
                # rev_byteorder asks pdfium for RGB rather than its native BGR,
                # which is the byte order RenderedPage promises and Qt expects.
                # Without it every rendered page comes out with red and blue
                # swapped, and the stride happens to match either way, so
                # nothing else would notice.
                bitmap = page.render(
                    scale=request.scale,
                    rotation=int(request.rotation) % 360,
                    rev_byteorder=True,
                    draw_annots=True,
                )
            except MemoryError:
                raise
            except Exception as exc:
                log.warning("Could not render page %d: %s", request.source_index, exc)
                return self._render_blank(request)

            return RenderedPage(
                key=request.cache_key,
                width=bitmap.width,
                height=bitmap.height,
                stride=bitmap.stride,
                samples=bytes(bitmap.buffer),
                scale=request.scale,
            )

    def _apply_replacements(self, opened: OpenedPdf, page, request: RenderRequest) -> None:
        """Stop pdfium drawing the lines the user has rewritten.

        Saving already removed them, but the screen went on showing the
        original underneath the replacement — two copies of the line a whisker
        apart, which reads as the edit having done nothing at all.

        Deactivating rather than deleting is deliberate. The model records
        these as *source object indices*, so anything that renumbered them
        would invalidate every line the user has not touched yet, and the
        writer works from the file's own bytes rather than from this copy.
        An inactive object keeps its place in the list, and pdfium leaves it
        out of the raster. Not out of the *text* page, though — that is built
        from the content stream regardless — which is why anything reading the
        page's words goes through :meth:`replaced_boxes` to skip them.

        Applied in full on every render rather than diffed against what was
        done last time. pdfium hands out a fresh page wrapper each time and
        frees the old one, and a page reloaded from the content stream has all
        its objects active again — so a note saying "already hidden" is a note
        about a page that no longer exists. Remembering which indices were
        ever touched is only so one that has *stopped* being replaced gets
        switched back on, for the case where the page did survive.

        Must be called with ``opened.lock`` held.
        """
        key = (request.source_key, request.source_index)
        wanted = set(request.replaced)
        touched = self._deactivated.get(key, frozenset())
        if not wanted and not touched:
            return
        for index in sorted(wanted | touched):
            try:
                obj = pdfium_raw.FPDFPage_GetObject(page.raw, index)
                if not obj:
                    continue
                pdfium_raw.FPDFPageObj_SetIsActive(obj, index not in wanted)
            except Exception:  # pragma: no cover - a stale line beats no page
                log.warning(
                    "Could not hide object %d of page %d", index, request.source_index,
                    exc_info=True,
                )
        self._deactivated[key] = frozenset(wanted)

    # -- text --------------------------------------------------------------
    def _text_source(self, page: Page) -> OpenedPdf | None:
        """The open handle backing *page*, or None if its text is unreachable."""
        if page.source is None:
            return None
        opened = self.source_handle(page.source.source_key)
        if opened is None or opened.is_closed:
            return None
        return opened

    def replaced_boxes(self, page: Page) -> list[Rect]:
        """Where *page*'s replaced lines used to be, in base page space.

        Switching a page object off keeps it out of the raster, but pdfium's
        text page is built from the content stream and still reports it. So
        anything reading the page's words has to skip these by geometry.
        """
        if not page.replaced_text:
            return []
        claimed = set(page.replaced_text)
        return [
            line.hit_box
            for line in self.source_text_lines(page)
            if claimed.issuperset(line.indices)
        ]

    def search_page(self, page: Page, needle: str, *, limit: int = 200) -> list[Rect]:
        """Find *needle* on *page*, returning hit rectangles in base page space.

        Hits inside a line the user has replaced are dropped: those words are
        not on the page any more, and Find that scrolls to a blank patch is
        worse than Find that says there is nothing there.
        """
        if not needle:
            return []
        opened = self._text_source(page)
        if opened is None or page.source is None:
            return []

        replaced = self.replaced_boxes(page)
        index = page.source.index
        geometry = opened.geometry(index)
        hits: list[Rect] = []
        with opened.lock:
            try:
                textpage = opened.doc[index].get_textpage()
                searcher = textpage.search(needle)
                while len(hits) < limit:
                    found = searcher.get_next()
                    if found is None:
                        break
                    start, count = found
                    # A single hit spans several rectangles when it wraps a
                    # line, and each one has to be highlighted separately.
                    for rect_index in range(textpage.count_rects(start, count)):
                        hit = from_pdf_rect(geometry, textpage.get_rect(rect_index))
                        if any(box.contains_point(hit.center) for box in replaced):
                            continue
                        hits.append(hit)
            except Exception as exc:
                log.debug("Search failed on page %d: %s", index, exc)
                return []
        return hits[:limit]

    def page_text(self, page: Page) -> str:
        opened = self._text_source(page)
        if opened is None or page.source is None:
            return ""
        with opened.lock:
            try:
                return opened.doc[page.source.index].get_textpage().get_text_range()
            except Exception:
                return ""

    def text_lines_in(self, page: Page, rect: Rect) -> list[Rect]:
        """Line rectangles of the page text intersecting *rect* (base space).

        Used by the highlight/underline/strikeout tools so a markup annotation
        snaps to the actual text lines rather than to the raw drag rectangle.

        pdfium already groups the page's characters into one rectangle per run
        of text on a line, which is exactly the granularity wanted here — so
        this asks for those rather than reassembling lines out of word boxes
        and having to guess where one ends.
        """
        opened = self._text_source(page)
        if opened is None or page.source is None:
            return []

        index = page.source.index
        geometry = opened.geometry(index)
        selection = to_pdf_rect(geometry, rect)
        with opened.lock:
            try:
                textpage = opened.doc[index].get_textpage()
                candidates = [
                    textpage.get_rect(i) for i in range(textpage.count_rects(0, -1))
                ]
            except Exception:
                return []

        return [
            from_pdf_rect(geometry, candidate)
            for candidate in candidates
            if _overlaps(candidate, selection)
        ]

    def source_text_lines(self, page: Page) -> list[SourceTextLine]:
        """The lines of *page*'s own text, ready to be replaced by the user.

        The page and its text page are held in locals for the whole read and
        released together. Asking pdfium for the same page twice hands out two
        wrappers over one handle, and whichever is collected first frees it for
        both — a crash that arrives later, somewhere else, usually when the
        document is closed. It is worth the two variables.
        """
        opened = self._text_source(page)
        if opened is None or page.source is None:
            return []

        index = page.source.index
        geometry = opened.geometry(index)
        with opened.lock:
            try:
                pdf_page = opened.doc[index]
                textpage = pdf_page.get_textpage()
                return read_text_lines(pdf_page.raw, textpage.raw, geometry)
            except Exception:
                log.warning("Could not read the text of page %d", index, exc_info=True)
                return []

    def __del__(self) -> None:  # pragma: no cover - best-effort cleanup
        with suppress(Exception):
            self.close_all()
