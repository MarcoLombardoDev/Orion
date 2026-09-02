# Orion — PDF Editor for Desktop
# Copyright (C) 2026 Marco Lombardo
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# Distributed WITHOUT ANY WARRANTY; see LICENSE for the full terms.
# A commercial licence, without the AGPL's obligations, is available for use
# in proprietary or closed-source products — see COMMERCIAL-LICENSE.md.

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

__all__ = ["ExportService", "IMAGE_FORMATS"]

#: The image formats offered, and the extension each is written with. Both are
#: in Pillow's core, so neither adds anything to the bundle.
IMAGE_FORMATS: tuple[str, ...] = ("PNG", "JPEG")
_IMAGE_SUFFIXES = {"PNG": ".png", "JPEG": ".jpg", "JPG": ".jpg"}


class ExportService:
    """Stateless: every operation renders the model afresh, so a document
    edited between two exports can never produce a stale result."""

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
    def export_images(
        self,
        document: Document,
        indices: Sequence[int],
        directory: str | Path,
        *,
        image_format: str = "PNG",
        dpi: int = 150,
    ) -> list[Path]:
        """Save the chosen pages as images, and return the files written.

        Rendered from the document built to PDF bytes rather than from the
        canvas, so what lands in the image is exactly what a save would put in
        the file — objects, annotations and redactions included, and none of
        the selection handles or page shadows the screen shows.
        """
        import pypdfium2 as pdfium

        if not indices:
            raise PdfWriteError("Select at least one page to export.")
        suffix = _IMAGE_SUFFIXES.get(image_format.upper())
        if suffix is None:
            raise PdfWriteError(f"“{image_format}” is not an image format Orion writes.")

        directory = Path(directory)
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise PdfWriteError(
                f"The folder “{directory}” could not be created.", detail=str(exc)
            ) from exc

        stem = _stem_for(document)
        # 72 points to the inch is the PDF unit, so this is the scale factor.
        scale = max(dpi, 1) / 72.0
        written: list[Path] = []
        pdf = pdfium.PdfDocument(self._bytes_of(document))
        try:
            for index in indices:
                if not 0 <= index < len(pdf):
                    continue
                page = pdf[index]
                try:
                    image = page.render(scale=scale, rev_byteorder=True).to_pil()
                    if image_format.upper() in ("JPEG", "JPG"):
                        # JPEG has no alpha, and pasting onto white is what a
                        # reader shows for a page with no background of its own.
                        image = image.convert("RGB")
                    target = directory / f"{stem}-{index + 1:03d}{suffix}"
                    image.save(target)
                    written.append(target)
                finally:
                    del page
        except PdfWriteError:
            raise
        except Exception as exc:
            raise PdfWriteError(
                "The pages could not be exported as images.", detail=str(exc)
            ) from exc
        finally:
            pdf.close()

        log.info("Exported %d page(s) to %s", len(written), directory)
        return written

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
