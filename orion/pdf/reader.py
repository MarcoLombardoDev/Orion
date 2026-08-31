# Orion — PDF Editor for Desktop
# Copyright (C) 2026 Marco Lombardo
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# Distributed WITHOUT ANY WARRANTY; see LICENSE for the full terms.
# A commercial licence, without the AGPL's obligations, is available for use
# in proprietary or closed-source products — see COMMERCIAL-LICENSE.md.

"""Opening PDF files and turning them into a :class:`Document` (spec §6, §25)."""

from __future__ import annotations

import logging
import threading
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_raw

from orion.document.document import Document, DocumentSource
from orion.document.page import Page, PageSource
from orion.pdf.annotation_import import ImportedAnnotations, import_annotations
from orion.pdf.coordinates import PageGeometry
from orion.pdf.errors import PdfCorruptError, PdfPasswordRequired, PdfReadError
from orion.utils.geometry import Size

log = logging.getLogger(__name__)

__all__ = [
    "OpenedPdf",
    "open_pdf",
    "build_document",
    "build_pages",
    "load_document",
    "page_sizes",
]


@dataclass
class OpenedPdf:
    """A pdfium handle plus the lock that serialises access to it.

    pdfium is not safe for concurrent access to the same document, so every
    engine call must hold this lock (spec §24 background rendering).
    """

    path: Path | None
    doc: pdfium.PdfDocument
    lock: threading.RLock

    @property
    def is_closed(self) -> bool:
        """pdfium drops its handle on close; asking it anything then crashes."""
        return getattr(self.doc, "raw", None) is None

    @property
    def page_count(self) -> int:
        return len(self.doc)

    def geometry(self, index: int) -> PageGeometry:
        """The unrotated mediabox and /Rotate of one page.

        This is what :mod:`orion.pdf.coordinates` needs, and the reason it is
        read here: ``get_size()`` reports the page *as displayed*, which is the
        right answer for laying out the canvas and the wrong one for placing
        content, and having both come from the same place stops them being
        confused for each other.
        """
        with self.lock:
            page = self.doc[index]
            left, bottom, right, top = page.get_mediabox()
            return PageGeometry(
                width=abs(right - left),
                height=abs(top - bottom),
                rotation=int(page.get_rotation()),
            )

    def close(self) -> None:
        with self.lock:
            if not self.is_closed:
                self.doc.close()


def _classify_load_failure(path: Path, password: str | None, exc: Exception) -> Exception:
    """Turn a pdfium load failure into the error the user should see.

    pdfium reports a missing password and a wrong one with the same code, so it
    cannot tell them apart — but the caller can: if no password was offered,
    one is needed; if one was offered and the file still will not open, it was
    the wrong one. That is exactly the distinction the UI needs to decide
    between prompting and reporting a failure.

    The code is read from ``FPDF_GetLastError`` rather than matched out of the
    message text, which is a sentence meant for humans and free to change.
    """
    code = pdfium_raw.FPDF_GetLastError()
    if code == pdfium_raw.FPDF_ERR_PASSWORD:
        if password is None:
            return PdfPasswordRequired(
                f"“{path.name}” is password protected. Enter the password to open it."
            )
        return PdfPasswordRequired(wrong=True)
    if code == pdfium_raw.FPDF_ERR_FILE:
        return PdfReadError(
            f"“{path.name}” could not be read from disk.", detail=str(exc)
        )
    return PdfCorruptError(
        f"“{path.name}” is damaged or is not a valid PDF document.", detail=str(exc)
    )


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
        doc = pdfium.PdfDocument(path, password=password, autoclose=True)
    except FileNotFoundError as exc:
        raise PdfReadError(f"The file “{path.name}” does not exist.", detail=str(exc)) from exc
    except PermissionError as exc:
        raise PdfReadError(
            f"Permission denied while opening “{path.name}”.", detail=str(exc)
        ) from exc
    except pdfium.PdfiumError as exc:
        raise _classify_load_failure(path, password, exc) from exc
    except Exception as exc:  # pdfium raises a variety of low-level errors
        raise PdfCorruptError(
            f"“{path.name}” is damaged or is not a valid PDF document.", detail=str(exc)
        ) from exc

    try:
        count = len(doc)
    except Exception as exc:
        doc.close()
        raise PdfCorruptError(detail=str(exc)) from exc

    if count <= 0:
        doc.close()
        raise PdfCorruptError(f"“{path.name}” contains no pages.")

    log.info("Opened %s (%d pages)", path, count)
    return OpenedPdf(path=path, doc=doc, lock=threading.RLock())


def _page_info(opened: OpenedPdf) -> list[tuple[Size, int, int]]:
    """``(displayed_size, source_rotation, annotation_count)`` for every page.

    All three come out of the one walk over the document because loading a
    page is the expensive part and the annotation count is free once it is
    open. Nothing is rasterised: opening a 2000-page file stays fast, and no
    page is drawn until it scrolls into view.
    """
    result: list[tuple[Size, int, int]] = []
    with opened.lock:
        for index in range(len(opened.doc)):
            try:
                page = opened.doc[index]
                width, height = page.get_size()
                count = int(pdfium_raw.FPDFPage_GetAnnotCount(page.raw))
                result.append((Size(width, height), int(page.get_rotation()), count))
            except Exception as exc:  # a single broken page must not stop the open
                log.warning("Page %d has unreadable geometry (%s); using A4", index, exc)
                result.append((Size(595.0, 842.0), 0, 0))
    return result


def page_sizes(opened: OpenedPdf) -> list[tuple[Size, int]]:
    """Return ``(displayed_size, source_rotation)`` for every page."""
    return [(size, rotation) for size, rotation, _ in _page_info(opened)]


def _read_annotations(
    opened: OpenedPdf, info: Sequence[tuple[Size, int, int]], wanted: Sequence[int]
) -> dict[int, ImportedAnnotations]:
    """Import the owned annotations of the *wanted* pages, keyed by page index.

    The file is parsed a second time here, with pypdf, because annotations are
    dictionaries and pypdf hands them over as dictionaries — the same ones the
    writer builds, which is what makes the round trip legible. That parse is
    only paid for when there is something to import: pdfium already counted
    the annotations on every page while measuring it, and the overwhelming
    majority of documents have none at all.
    """
    if not any(info[index][2] for index in wanted if index < len(info)):
        return {}

    from pypdf import PdfReader as _PdfReader  # local: only needed on this path

    try:
        if opened.path is None:
            return {}
        reader = _PdfReader(str(opened.path))
    except Exception:
        # An unreadable file would already have failed to open in pdfium; if
        # pypdf disagrees, the document still opens, just without editable
        # annotations, which is what happened before this existed.
        log.warning("Could not read the annotations of %s", opened.path, exc_info=True)
        return {}

    found: dict[int, ImportedAnnotations] = {}
    for index in wanted:
        if index >= len(info) or not info[index][2]:
            continue
        try:
            pdf_page = reader.pages[index]
            box = pdf_page.mediabox
            geometry = PageGeometry(
                width=abs(float(box.right) - float(box.left)),
                height=abs(float(box.top) - float(box.bottom)),
                rotation=int(pdf_page.get("/Rotate", 0) or 0),
            )
            imported = import_annotations(pdf_page, geometry)
        except Exception:
            log.warning("Could not read the annotations of page %d", index, exc_info=True)
            continue
        if imported.objects:
            found[index] = imported
    return found


def _hide_owned_annotations(
    opened: OpenedPdf, found: dict[int, ImportedAnnotations]
) -> None:
    """Stop pdfium drawing the annotations the model has taken over.

    Pages are rasterised with ``draw_annots=True``, which is right for
    everything Orion cannot edit — a stamp, a form field, a markup kind it has
    no tool for — and wrong for everything it can. An imported highlight would
    otherwise be drawn twice: once into the page image by pdfium and once by
    its own object on the canvas. The two are indistinguishable until the user
    deletes it, at which point the object goes and the page image keeps
    drawing it, so nothing appears to happen.

    Marking them hidden is per-annotation rather than turning annotations off
    for the whole page, so the ones Orion does not own keep showing. It
    touches only the in-memory document pdfium is holding for the screen: the
    writer opens the file again with pypdf, so nothing here reaches the disk.
    """
    with opened.lock:
        for index, imported in found.items():
            try:
                page = opened.doc[index]
                for position in imported.indices:
                    annotation = pdfium_raw.FPDFPage_GetAnnot(page.raw, position)
                    if not annotation:
                        continue
                    flags = int(pdfium_raw.FPDFAnnot_GetFlags(annotation))
                    pdfium_raw.FPDFAnnot_SetFlags(
                        annotation, flags | pdfium_raw.FPDF_ANNOT_FLAG_HIDDEN
                    )
                    pdfium_raw.FPDFPage_CloseAnnot(annotation)
            except Exception:  # pragma: no cover - drawing twice beats crashing
                log.warning("Could not hide the annotations of page %d", index, exc_info=True)
            finally:
                page = None


def build_pages(
    opened: OpenedPdf, source_key: str, indices: Sequence[int] | None = None
) -> list[Page]:
    """Build the model pages for *indices* of an opened file (all, by default).

    Shared by opening a document and importing pages out of another one, so
    an imported page arrives with its annotations editable exactly like a page
    the user opened directly.
    """
    info = _page_info(opened)
    wanted = list(range(len(info))) if indices is None else list(indices)
    for index in wanted:
        if not 0 <= index < len(info):
            raise PdfReadError(f"The document has no page {index + 1}.")

    annotations = _read_annotations(opened, info, wanted)
    _hide_owned_annotations(opened, annotations)

    pages: list[Page] = []
    for index in wanted:
        size, rotation, _ = info[index]
        imported = annotations.get(index, ImportedAnnotations())
        pages.append(
            Page(
                base_size=size,
                source=PageSource(source_key, index),
                source_rotation=rotation,
                objects=list(imported.objects),
                imported_annotations=imported.indices,
            )
        )
    return pages


def build_document(opened: OpenedPdf) -> Document:
    """Create the working :class:`Document` for an opened file."""
    if opened.path is None:
        source = DocumentSource(key="memory", label="Untitled")
    else:
        source = DocumentSource.for_path(opened.path)
    source.data = None

    pages = build_pages(opened, source.key)

    document = Document(pages=pages, sources=[source], path=opened.path)
    with opened.lock:
        try:
            document.metadata = {
                key: str(value)
                for key, value in (opened.doc.get_metadata_dict() or {}).items()
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
