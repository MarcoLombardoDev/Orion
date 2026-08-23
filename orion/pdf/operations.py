# Orion — PDF Editor for Desktop
# Copyright (C) 2026 Marco Lombardo
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# Distributed WITHOUT ANY WARRANTY; see LICENSE for the full terms.
# A commercial licence, without the AGPL's obligations, is available for use
# in proprietary or closed-source products — see COMMERCIAL-LICENSE.md.

"""File-level PDF operations: merge, split, extract (spec §16, §17, §18).

These work on files and byte buffers rather than on the document model, so the
same code serves the UI today and a command-line interface later.  ``pypdf`` is
used here (rather than PyMuPDF) because page copying is exactly what it is good
at, and it keeps a second, independent implementation available for the
operations that must never corrupt a user's file.
"""

from __future__ import annotations

import io
import logging
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from pypdf.errors import PdfReadError as _PyPdfReadError

from orion.pdf.errors import (
    PdfCorruptError,
    PdfPasswordRequired,
    PdfReadError,
    PdfWriteError,
)
from orion.utils.fileio import atomic_write_bytes, unique_path

log = logging.getLogger(__name__)

__all__ = [
    "PdfInput",
    "parse_page_ranges",
    "format_page_ranges",
    "page_count_of",
    "merge",
    "extract_pages",
    "split_by_ranges",
    "split_every",
]

#: Anything the operations accept as an input document.
PdfInput = Path | str | bytes


# --------------------------------------------------------------------------
# Page range parsing
# --------------------------------------------------------------------------
_RANGE_RE = re.compile(r"^\s*(\d+)\s*(?:-\s*(\d+)\s*)?$")


def parse_page_ranges(text: str, page_count: int) -> list[list[int]]:
    """Parse ``"1-5, 8, 11-20"`` into groups of **0-based** page indices.

    Page numbers in the UI are 1-based; indices in the model are 0-based, and
    that translation happens here so it is written once.

    Raises :class:`ValueError` with a message meant for the user.
    """
    groups: list[list[int]] = []
    for chunk in re.split(r"[,;\n]", text):
        chunk = chunk.strip()
        if not chunk:
            continue
        match = _RANGE_RE.match(chunk)
        if not match:
            raise ValueError(f"“{chunk}” is not a valid page range.")
        start = int(match.group(1))
        end = int(match.group(2)) if match.group(2) else start
        if start < 1 or end < 1:
            raise ValueError("Page numbers start at 1.")
        if start > page_count or end > page_count:
            raise ValueError(
                f"“{chunk}” is outside the document, which has {page_count} pages."
            )
        step = 1 if end >= start else -1
        groups.append([index - 1 for index in range(start, end + step, step)])
    if not groups:
        raise ValueError("Enter at least one page or page range, for example 1-5.")
    return groups


def format_page_ranges(indices: Sequence[int]) -> str:
    """Inverse of :func:`parse_page_ranges` for a single flat selection."""
    if not indices:
        return ""
    ordered = sorted(set(indices))
    parts: list[str] = []
    start = previous = ordered[0]
    for index in ordered[1:]:
        if index == previous + 1:
            previous = index
            continue
        parts.append(f"{start + 1}" if start == previous else f"{start + 1}-{previous + 1}")
        start = previous = index
    parts.append(f"{start + 1}" if start == previous else f"{start + 1}-{previous + 1}")
    return ", ".join(parts)


# --------------------------------------------------------------------------
# Reading
# --------------------------------------------------------------------------
def _open(source: PdfInput, password: str | None = None) -> PdfReader:
    label = Path(source).name if isinstance(source, (str, Path)) else "the document"
    try:
        stream = io.BytesIO(source) if isinstance(source, bytes) else Path(source)
        reader = PdfReader(stream)
    except FileNotFoundError as exc:
        raise PdfReadError(f"“{label}” does not exist.", detail=str(exc)) from exc
    except PermissionError as exc:
        raise PdfReadError(f"Permission denied while reading “{label}”.", detail=str(exc)) from exc
    except (_PyPdfReadError, ValueError, OSError) as exc:
        raise PdfCorruptError(
            f"“{label}” is damaged or is not a valid PDF document.", detail=str(exc)
        ) from exc

    if reader.is_encrypted:
        try:
            if reader.decrypt(password or "") == 0:
                raise PdfPasswordRequired(
                    f"“{label}” is password protected and cannot be used here."
                )
        except PdfPasswordRequired:
            raise
        except Exception as exc:
            raise PdfPasswordRequired(
                f"“{label}” is password protected and cannot be used here.", detail=str(exc)
            ) from exc
    return reader


def page_count_of(source: PdfInput, password: str | None = None) -> int:
    reader = _open(source, password)
    return len(reader.pages)


def _write(writer: PdfWriter, output: Path, *, expected_pages: int) -> Path:
    buffer = io.BytesIO()
    try:
        writer.write(buffer)
    except Exception as exc:
        raise PdfWriteError(detail=str(exc)) from exc

    def _validate(candidate: Path) -> None:
        reader = PdfReader(candidate)
        if len(reader.pages) != expected_pages:
            raise ValueError(f"wrote {len(reader.pages)} pages, expected {expected_pages}")

    try:
        return atomic_write_bytes(buffer.getvalue(), output, validate=_validate)
    except ValueError as exc:
        raise PdfWriteError(
            "The generated file failed validation and was discarded.", detail=str(exc)
        ) from exc
    except OSError as exc:
        if getattr(exc, "errno", None) == 28:
            raise PdfWriteError(
                "There is not enough free disk space to write the file.", detail=str(exc)
            ) from exc
        raise PdfWriteError(
            f"“{output.name}” could not be written.", detail=str(exc)
        ) from exc


# --------------------------------------------------------------------------
# Operations
# --------------------------------------------------------------------------
@dataclass(slots=True)
class MergeItem:
    """One entry in a merge job: a document and, optionally, a page selection."""

    source: PdfInput
    pages: Sequence[int] | None = None
    password: str | None = None

    @property
    def label(self) -> str:
        if isinstance(self.source, bytes):
            return "in-memory document"
        return Path(self.source).name


def merge(items: Sequence[MergeItem | PdfInput], output: str | Path) -> Path:
    """Concatenate documents, in the given order, into *output* (spec §17)."""
    normalised = [item if isinstance(item, MergeItem) else MergeItem(item) for item in items]
    if not normalised:
        raise PdfWriteError("Select at least two documents to merge.")

    writer = PdfWriter()
    total = 0
    for item in normalised:
        reader = _open(item.source, item.password)
        indices = list(item.pages) if item.pages is not None else list(range(len(reader.pages)))
        for index in indices:
            if not 0 <= index < len(reader.pages):
                raise PdfWriteError(
                    f"“{item.label}” has no page {index + 1}."
                )
            writer.add_page(reader.pages[index])
            total += 1

    if total == 0:
        raise PdfWriteError("The merge would produce an empty document.")
    return _write(writer, Path(output), expected_pages=total)


def extract_pages(source: PdfInput, output: str | Path, indices: Iterable[int]) -> Path:
    """Create a new PDF containing only *indices*, in the order given (spec §16)."""
    reader = _open(source)
    order = list(indices)
    if not order:
        raise PdfWriteError("Select at least one page to extract.")

    writer = PdfWriter()
    for index in order:
        if not 0 <= index < len(reader.pages):
            raise PdfWriteError(f"The document has no page {index + 1}.")
        writer.add_page(reader.pages[index])
    return _write(writer, Path(output), expected_pages=len(order))


def split_by_ranges(
    source: PdfInput,
    output_dir: str | Path,
    groups: Sequence[Sequence[int]],
    *,
    stem: str = "document",
    overwrite: bool = False,
) -> list[Path]:
    """Write one file per group of page indices (spec §18)."""
    if not groups:
        raise PdfWriteError("Define at least one page range to split by.")
    directory = Path(output_dir)
    results: list[Path] = []
    for number, group in enumerate(groups, start=1):
        target = directory / f"{stem}_{number}.pdf"
        if not overwrite:
            target = unique_path(target)
        results.append(extract_pages(source, target, group))
    log.info("Split into %d files in %s", len(results), directory)
    return results


def split_every(
    source: PdfInput,
    output_dir: str | Path,
    every: int,
    *,
    stem: str = "document",
    overwrite: bool = False,
) -> list[Path]:
    """Split into chunks of *every* pages (spec §18)."""
    if every < 1:
        raise PdfWriteError("The number of pages per file must be at least 1.")
    count = page_count_of(source)
    groups = [list(range(start, min(start + every, count))) for start in range(0, count, every)]
    return split_by_ranges(source, output_dir, groups, stem=stem, overwrite=overwrite)
