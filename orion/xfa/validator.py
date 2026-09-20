# Orion — PDF Editor for Desktop
# Copyright (C) 2026 Marco Lombardo
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# Distributed WITHOUT ANY WARRANTY; see LICENSE for the full terms.
# A commercial licence, without the AGPL's obligations, is available for use
# in proprietary or closed-source products — see COMMERCIAL-LICENSE.md.

"""Checking that the converted document is actually a document.

A converter can write a file that satisfies every internal invariant and is
still broken — a field off the edge of the page, two fields sharing a name so
one overwrites the other, a choice list with no choices. So the output is
reopened *with a different library from the one that wrote it* and inspected
as a stranger would.

That cross-check is the point. reportlab wrote it; pypdf reads it back. A
fault that both agree on is a fault in the file rather than in one library's
idea of it, and that is the only kind worth reporting.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from orion.xfa.report import Severity

__all__ = ["ValidationIssue", "ValidationResult", "validate_converted_pdf"]

log = logging.getLogger(__name__)

#: A widget may sit a whisker outside the page from rounding; more than this
#: and it was placed wrongly.
EDGE_TOLERANCE = 2.0


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    severity: Severity
    message: str
    subject: str = ""

    def __str__(self) -> str:
        return f"{self.subject}: {self.message}" if self.subject else self.message


@dataclass(slots=True)
class ValidationResult:
    """What reopening the file found."""

    ok: bool = True
    pages: int = 0
    field_count: int = 0
    field_names: tuple[str, ...] = ()
    has_acroform: bool = False
    issues: list[ValidationIssue] = field(default_factory=list)

    def add(self, severity: Severity, message: str, subject: str = "") -> None:
        self.issues.append(ValidationIssue(severity, message, subject))
        if severity is Severity.ERROR:
            self.ok = False

    @property
    def errors(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity is Severity.ERROR]

    @property
    def warnings(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity is Severity.WARNING]


def validate_converted_pdf(
    path: str | Path,
    *,
    expect_pages: int = 0,
    expect_fields: int = 0,
    expect_interactive: bool = True,
) -> ValidationResult:
    """Reopen the converted file and check it is sound.

    The expectations are optional: passing none still checks everything that
    can be judged from the file alone, which is what makes this useful as a
    standalone check on a document somebody else produced.
    """
    path = Path(path)
    result = ValidationResult()

    if not path.exists() or path.stat().st_size == 0:
        result.add(Severity.ERROR, "The converted file was not written.")
        return result

    try:
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        result.pages = len(reader.pages)
    except Exception as exc:
        result.add(Severity.ERROR, f"The converted file cannot be opened: {exc}")
        return result

    if result.pages == 0:
        result.add(Severity.ERROR, "The converted file has no pages.")
        return result
    if expect_pages and result.pages != expect_pages:
        result.add(
            Severity.WARNING,
            f"The converted file has {result.pages} page(s) where "
            f"{expect_pages} were expected.",
        )

    for index, page in enumerate(reader.pages):
        try:
            box = page.mediabox
            width = float(box.width)
            height = float(box.height)
        except Exception:
            result.add(Severity.ERROR, "A page has no usable size.", f"page {index + 1}")
            continue
        if width <= 0 or height <= 0:
            result.add(Severity.ERROR, "A page has a zero or negative size.", f"page {index + 1}")

    try:
        root = reader.trailer["/Root"].get_object()
        result.has_acroform = "/AcroForm" in root
    except Exception:  # pragma: no cover - a catalogue this broken fails above
        result.has_acroform = False

    fields: dict = {}
    try:
        fields = reader.get_fields() or {}
    except Exception as exc:
        result.add(Severity.WARNING, f"The form fields could not be read back: {exc}")

    result.field_count = len(fields)
    result.field_names = tuple(str(name) for name in fields)

    if expect_interactive:
        if not result.has_acroform:
            result.add(Severity.ERROR, "The converted file has no form dictionary.")
        elif not fields:
            result.add(Severity.ERROR, "The converted file has a form but no fields in it.")
    if expect_fields and result.field_count != expect_fields:
        result.add(
            Severity.WARNING,
            f"The converted file has {result.field_count} field(s) where "
            f"{expect_fields} were expected.",
        )

    _check_names(result)
    _check_fields(reader, fields, result)
    return result


def _check_names(result: ValidationResult) -> None:
    """Field names have to be unique, or one field fills in for two."""
    seen: set[str] = set()
    duplicates: set[str] = set()
    for name in result.field_names:
        if name in seen:
            duplicates.add(name)
        seen.add(name)
    for name in sorted(duplicates):
        result.add(
            Severity.ERROR,
            "Two fields share this name, so typing in one would fill the other.",
            name,
        )
    for name in result.field_names:
        if not str(name).strip():
            result.add(Severity.ERROR, "A field has no name.")


def _check_fields(reader, fields: dict, result: ValidationResult) -> None:
    """Per-field sanity: a usable type, real coordinates, options where needed."""
    known_types = {"/Tx", "/Btn", "/Ch", "/Sig"}
    page_boxes = []
    for page in reader.pages:
        try:
            box = page.mediabox
            page_boxes.append((float(box.width), float(box.height)))
        except Exception:  # pragma: no cover - reported above
            page_boxes.append((0.0, 0.0))

    for name, spec in fields.items():
        field_type = spec.get("/FT")
        if field_type is not None and str(field_type) not in known_types:
            result.add(Severity.WARNING, f"Unfamiliar field type {field_type}.", str(name))

        if str(field_type) == "/Ch":
            options = spec.get("/Opt") or []
            if len(options) == 0:
                result.add(
                    Severity.WARNING,
                    "This choice field offers nothing to choose from.",
                    str(name),
                )

    # Widget rectangles are on the annotations, not the field dictionaries.
    for index, page in enumerate(reader.pages):
        annots = page.get("/Annots")
        if not annots:
            continue
        width, height = page_boxes[index] if index < len(page_boxes) else (0.0, 0.0)
        for annotation in annots:
            try:
                widget = annotation.get_object()
                if widget.get("/Subtype") != "/Widget":
                    continue
                rect = [float(v) for v in widget.get("/Rect", [])]
            except Exception:
                continue
            if len(rect) != 4:
                result.add(Severity.WARNING, "A widget has no usable rectangle.")
                continue
            x0, y0, x1, y1 = rect
            if x1 - x0 <= 0 or y1 - y0 <= 0:
                result.add(
                    Severity.WARNING,
                    "A field has zero width or height and cannot be clicked.",
                    str(widget.get("/T", "")),
                )
            if (
                width
                and height
                and (
                    x0 < -EDGE_TOLERANCE
                    or y0 < -EDGE_TOLERANCE
                    or x1 > width + EDGE_TOLERANCE
                    or y1 > height + EDGE_TOLERANCE
                )
            ):
                result.add(
                    Severity.WARNING,
                    "A field sits outside the page and may not be reachable.",
                    str(widget.get("/T", "")),
                )


def opens_in_orion(path: str | Path) -> tuple[bool, str]:
    """Can Orion itself open the result?

    The last check, and the one that matters to the user: a converted form
    that some other reader accepts but Orion does not is a failed conversion
    as far as this program is concerned. Uses Orion's own reader so the answer
    is the real one rather than an approximation of it.
    """
    from orion.pdf.errors import OrionPdfError
    from orion.pdf.reader import open_pdf

    opened = None
    try:
        opened = open_pdf(path)
        pages = len(opened.doc)
        if pages <= 0:
            return False, "the converted document has no pages"
        return True, f"{pages} page(s)"
    except OrionPdfError as exc:
        return False, exc.message
    except Exception as exc:  # pragma: no cover - defensive
        return False, str(exc)
    finally:
        if opened is not None:
            opened.close()
