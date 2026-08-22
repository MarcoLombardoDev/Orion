"""Merge / split / extract driven from the live document (spec §17, §18).

The important detail: operations that start from the *open* document run on the
current model — including objects and annotations the user has not saved yet —
by building it to PDF bytes in memory first.  Operations on other files go
straight to :mod:`orion.pdf.operations`.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from pathlib import Path

from orion.document.document import Document
from orion.pdf import operations
from orion.pdf.errors import PdfWriteError
from orion.pdf.operations import MergeItem
from orion.pdf.writer import build_pdf_bytes

log = logging.getLogger(__name__)

__all__ = ["ExportService"]


class ExportService:
    def __init__(self) -> None:
        self._cache: tuple[int, bytes] | None = None

    # -- helpers ---------------------------------------------------------
    def _bytes_of(self, document: Document) -> bytes:
        """Render the working document to PDF bytes (objects included)."""
        try:
            return build_pdf_bytes(document)
        except PdfWriteError:
            raise
        except Exception as exc:
            raise PdfWriteError(
                "The current document could not be prepared for this operation.",
                detail=str(exc),
            ) from exc

    # -- operations ------------------------------------------------------
    def extract(self, document: Document, indices: Sequence[int], output: str | Path) -> Path:
        """Write the selected pages of *document* to a new file (spec §16)."""
        if not indices:
            raise PdfWriteError("Select at least one page to extract.")
        return operations.extract_pages(self._bytes_of(document), output, indices)

    def split_by_ranges(
        self,
        document: Document,
        groups: Sequence[Sequence[int]],
        output_dir: str | Path,
        *,
        stem: str | None = None,
    ) -> list[Path]:
        return operations.split_by_ranges(
            self._bytes_of(document),
            output_dir,
            groups,
            stem=stem or _stem_for(document),
        )

    def split_every(
        self, document: Document, every: int, output_dir: str | Path, *, stem: str | None = None
    ) -> list[Path]:
        return operations.split_every(
            self._bytes_of(document), output_dir, every, stem=stem or _stem_for(document)
        )

    def merge(
        self,
        items: Sequence[MergeItem | Path | str],
        output: str | Path,
        *,
        document: Document | None = None,
        current_marker: object = None,
    ) -> Path:
        """Merge documents.

        Any entry equal to *current_marker* is replaced by the live document,
        so "merge this file into the document I have open" works without
        forcing the user to save first.
        """
        resolved: list[MergeItem] = []
        for item in items:
            if current_marker is not None and item is current_marker:
                if document is None:
                    raise PdfWriteError("No document is open to merge.")
                resolved.append(MergeItem(self._bytes_of(document)))
            elif isinstance(item, MergeItem):
                resolved.append(item)
            else:
                resolved.append(MergeItem(item))
        return operations.merge(resolved, output)


def _stem_for(document: Document) -> str:
    return document.path.stem if document.path else "document"
