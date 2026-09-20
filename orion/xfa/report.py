# Orion — PDF Editor for Desktop
# Copyright (C) 2026 Marco Lombardo
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# Distributed WITHOUT ANY WARRANTY; see LICENSE for the full terms.
# A commercial licence, without the AGPL's obligations, is available for use
# in proprietary or closed-source products — see COMMERCIAL-LICENSE.md.

"""What the conversion did, and what it could not do.

The report exists because an XFA conversion is almost never total, and a
program that says "done" after losing a form's arithmetic has misled the
person relying on it. So two figures are kept apart and neither is allowed to
stand for the other:

**Visual fidelity** — does the new document look like the form did.
**Functional fidelity** — does it still *behave* like the form did.

A typical result is high on the first and middling on the second: every field
is there, in the right place, holding the right value, and the calculation
that used to fill one of them from two others is gone. Averaging those into a
single "95% converted" would be the one number that hides the thing the user
needs to know.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

__all__ = [
    "ConversionMode",
    "Fidelity",
    "ReportEntry",
    "Severity",
    "XfaConversionReport",
]


class ConversionMode(str, Enum):
    """What the user asked for."""

    #: Standard PDF with AcroForm fields. Everything convertible becomes live.
    EDITABLE = "editable"
    #: Standard PDF, nothing interactive. The fallback that always works.
    STATIC = "static"
    #: The default: keep as many fields as possible, staticise the rest.
    KEEP_FIELDS = "keep_fields"

    @property
    def wants_fields(self) -> bool:
        return self is not ConversionMode.STATIC


class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class Fidelity(str, Enum):
    """How close the result is, on one axis.

    Deliberately coarse. A percentage would imply a precision that nothing
    here can honestly support: there is no metric that says a form's layout is
    91% right.
    """

    FULL = "full"
    HIGH = "high"
    PARTIAL = "partial"
    LOW = "low"
    NONE = "none"

    @property
    def label(self) -> str:
        return {
            Fidelity.FULL: "complete",
            Fidelity.HIGH: "high",
            Fidelity.PARTIAL: "partial",
            Fidelity.LOW: "low",
            Fidelity.NONE: "none",
        }[self]


@dataclass(frozen=True, slots=True)
class ReportEntry:
    """One thing worth telling the user, in words they can act on."""

    severity: Severity
    message: str
    #: The SOM expression or name it concerns, when it concerns one.
    subject: str = ""

    def __str__(self) -> str:
        return f"{self.subject}: {self.message}" if self.subject else self.message


@dataclass(slots=True)
class XfaConversionReport:
    """The record of one conversion. Every count is measured, none assumed."""

    source_file: str = ""
    output_file: str = ""
    detected_type: str = ""
    mode: ConversionMode = ConversionMode.KEEP_FIELDS
    pages: int = 0

    total_xfa_fields: int = 0
    converted_fields: int = 0
    static_elements: int = 0
    unsupported_elements: int = 0

    scripts_found: int = 0
    scripts_converted: int = 0

    #: Repeatable subforms met, and how many instances were carried over.
    repeatable_subforms: int = 0
    preserved_instances: int = 0

    entries: list[ReportEntry] = field(default_factory=list)

    def add(self, severity: Severity, message: str, subject: str = "") -> None:
        self.entries.append(ReportEntry(severity, message, subject))

    def info(self, message: str, subject: str = "") -> None:
        self.add(Severity.INFO, message, subject)

    def warn(self, message: str, subject: str = "") -> None:
        self.add(Severity.WARNING, message, subject)

    def error(self, message: str, subject: str = "") -> None:
        self.add(Severity.ERROR, message, subject)

    # -- what came out of it ----------------------------------------------
    @property
    def warnings(self) -> list[ReportEntry]:
        return [e for e in self.entries if e.severity is Severity.WARNING]

    @property
    def errors(self) -> list[ReportEntry]:
        return [e for e in self.entries if e.severity is Severity.ERROR]

    @property
    def scripts_not_converted(self) -> int:
        return max(0, self.scripts_found - self.scripts_converted)

    @property
    def succeeded(self) -> bool:
        """A file was produced. Warnings do not make a conversion a failure.

        Partial output that a person can use beats an error message, which is
        the whole policy of this package where XFA cannot be fully honoured.
        """
        return bool(self.output_file) and not self.errors

    @property
    def visual_fidelity(self) -> Fidelity:
        """How much of the appearance survived.

        Driven by what had to be dropped rather than by what was drawn: the
        static layer is redrawn from the template, so the question is whether
        anything in it had no representation at all.
        """
        if self.errors:
            return Fidelity.LOW
        drawn = self.static_elements
        if self.unsupported_elements == 0:
            return Fidelity.FULL if drawn or self.converted_fields else Fidelity.HIGH
        total = max(1, drawn + self.unsupported_elements)
        lost = self.unsupported_elements / total
        if lost < 0.05:
            return Fidelity.HIGH
        if lost < 0.25:
            return Fidelity.PARTIAL
        return Fidelity.LOW

    @property
    def functional_fidelity(self) -> Fidelity:
        """How much of the behaviour survived.

        Scripts and repeatable sections weigh heaviest, because they are the
        behaviour: a form that calculated a total and now does not has lost
        its point even with every field in place.
        """
        if self.mode is ConversionMode.STATIC:
            return Fidelity.NONE
        if self.total_xfa_fields == 0:
            return Fidelity.NONE if self.scripts_found else Fidelity.FULL

        converted = self.converted_fields / self.total_xfa_fields
        lost_logic = self.scripts_not_converted > 0 or self.repeatable_subforms > 0

        if converted >= 0.999 and not lost_logic:
            return Fidelity.FULL
        if converted >= 0.9:
            return Fidelity.PARTIAL if lost_logic else Fidelity.HIGH
        if converted >= 0.5:
            return Fidelity.PARTIAL
        return Fidelity.LOW

    # -- saying it ---------------------------------------------------------
    def summary_lines(self) -> list[str]:
        """The report as a person would want it read out.

        Plain sentences: this is shown in a dialog, not in a log.
        """
        lines = [
            f"Form type: {self.detected_type}",
            f"Pages: {self.pages}",
            f"Fields found: {self.total_xfa_fields}",
            f"Fields converted: {self.converted_fields}",
            f"Elements kept as static content: {self.static_elements}",
        ]
        if self.unsupported_elements:
            lines.append(f"Elements that could not be reproduced: {self.unsupported_elements}")
        if self.scripts_found:
            lines.append(
                f"Scripts found: {self.scripts_found} "
                f"(carried over: {self.scripts_converted})"
            )
        if self.repeatable_subforms:
            lines.append(
                f"Repeatable sections: {self.repeatable_subforms} "
                f"({self.preserved_instances} instance(s) kept)"
            )
        lines.append(f"Appearance: {self.visual_fidelity.label}")
        lines.append(f"Behaviour: {self.functional_fidelity.label}")
        return lines

    def __str__(self) -> str:
        parts = list(self.summary_lines())
        for entry in self.entries:
            if entry.severity is not Severity.INFO:
                parts.append(f"{entry.severity.value}: {entry}")
        return "\n".join(parts)
