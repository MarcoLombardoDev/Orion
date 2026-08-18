"""Opening PDF files and turning them into a :class:`Document` (spec §6, §25)."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pymupdf

from orion.document.document import Document, DocumentSource
from orion.document.page import Page, PageSource
from orion.pdf.errors import PdfCorruptError, PdfPasswordRequired, PdfReadError
from orion.utils.geometry import Size

log = logging.getLogger(__name__)

__all__ = ["OpenedPdf", "open_pdf", "build_document", "load_document", "page_sizes"]


@dataclass
class OpenedPdf:
    """A PyMuPDF handle plus the lock that serialises access to it.

    PyMuPDF is not documented as thread-safe for concurrent access to the same
    document, so every engine call must hold this lock (spec §24 background
    rendering).
    """

    path: Optional[Path]
    doc: "pymupdf.Document"
    lock: threading.RLock

    @property
    def page_count(self) -> int:
        return self.doc.page_count

    def close(self) -> None:
        with self.lock:
            if not self.doc.is_closed:
                self.doc.close()


def open_pdf(path: str | Path, password: str | None = None) -> OpenedPdf:
    """Open *path*, raising a typed, user-presentable error on failure."""
    path = Path(path)
    if not path.exists():
        raise PdfReadError(
            f"The file “{path.name}” does not exist.", detail=str(path)
        )
    if path.is_dir():
        raise PdfReadError(f"“{path.name}” is a folder, not a PDF file.")

    try:
        doc = pymupdf.open(path)
    except FileNotFoundError as exc:
        raise PdfReadError(f"The file “{path.name}” does not exist.", detail=str(exc)) from exc
    except PermissionError as exc:
        raise PdfReadError(
            f"Permission denied while opening “{path.name}”.", detail=str(exc)
        ) from exc
    except Exception as exc:  # PyMuPDF raises a variety of low-level errors
        raise PdfCorruptError(
            f"“{path.name}” is damaged or is not a valid PDF document.", detail=str(exc)
        ) from exc

    if doc.needs_pass:
        if password is None:
            doc.close()
            raise PdfPasswordRequired(
                f"“{path.name}” is password protected. Enter the password to open it."
            )
        if not doc.authenticate(password):
            doc.close()
            raise PdfPasswordRequired(wrong=True)

    try:
        count = doc.page_count
    except Exception as exc:
        doc.close()
        raise PdfCorruptError(detail=str(exc)) from exc

    if count <= 0:
        doc.close()
        raise PdfCorruptError(f"“{path.name}” contains no pages.")

    log.info("Opened %s (%d pages)", path, count)
    return OpenedPdf(path=path, doc=doc, lock=threading.RLock())


def page_sizes(opened: OpenedPdf) -> list[tuple[Size, int]]:
    """Return ``(displayed_size, source_rotation)`` for every page.

    Reading only the geometry keeps opening a 2000-page file fast: no page is
    rasterised until it scrolls into view.
    """
    result: list[tuple[Size, int]] = []
    with opened.lock:
        for index in range(opened.doc.page_count):
            try:
                page = opened.doc.load_page(index)
                rect = page.rect
                result.append((Size(rect.width, rect.height), int(page.rotation)))
            except Exception as exc:  # a single broken page must not stop the open
                log.warning("Page %d has unreadable geometry (%s); using A4", index, exc)
                result.append((Size(595.0, 842.0), 0))
    return result


def build_document(opened: OpenedPdf) -> Document:
    """Create the working :class:`Document` for an opened file."""
    if opened.path is None:
        source = DocumentSource(key="memory", label="Untitled")
    else:
        source = DocumentSource.for_path(opened.path)
    source.data = None

    pages: list[Page] = []
    for index, (size, rotation) in enumerate(page_sizes(opened)):
        pages.append(
            Page(
                base_size=size,
                source=PageSource(source.key, index),
                source_rotation=rotation,
            )
        )

    document = Document(pages=pages, sources=[source], path=opened.path)
    with opened.lock:
        try:
            document.metadata = {
                key: str(value)
                for key, value in (opened.doc.metadata or {}).items()
                if value
            }
        except Exception:  # metadata is optional; never fail an open over it
            log.debug("Could not read metadata", exc_info=True)
    document.set_modified(False)
    return document


def load_document(path: str | Path, password: str | None = None) -> tuple[Document, OpenedPdf]:
    """Convenience wrapper: open a file and build its document in one call."""
    opened = open_pdf(path, password)
    try:
        return build_document(opened), opened
    except Exception:
        opened.close()
        raise
