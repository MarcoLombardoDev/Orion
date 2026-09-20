# Orion — PDF Editor for Desktop
# Copyright (C) 2026 Marco Lombardo
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# Distributed WITHOUT ANY WARRANTY; see LICENSE for the full terms.
# A commercial licence, without the AGPL's obligations, is available for use
# in proprietary or closed-source products — see COMMERCIAL-LICENSE.md.

"""Telling the user their document is an XFA form, and what can be done.

Two dialogs, and the wording in both is the point. Somebody who opens a form
and is told "this document uses an XFA architecture with dynamic rendering"
has learned nothing. What they need to know is that the file will not open
properly anywhere, that Orion can rebuild it as an ordinary form, and — after
the fact — which parts of it came through and which did not.

So: no acronyms in the first sentence, no counts without a consequence beside
them, and the losses stated as what the user will notice rather than as what
the converter did.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from orion.i18n import tr
from orion.xfa.report import ConversionMode, Severity, XfaConversionReport

__all__ = ["XfaPromptDialog", "XfaReportDialog"]


class XfaPromptDialog(QDialog):
    """Offered when a form arrives that Orion cannot edit as it stands."""

    #: What the user chose.
    CONVERT = 1
    READ_ONLY = 2
    CANCELLED = 0

    def __init__(self, file_name: str, summary=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Form document"))
        self._choice = self.CANCELLED
        self._mode = ConversionMode.KEEP_FIELDS

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        headline = QLabel(
            tr("This document uses an XFA form. Orion can convert it into a "
               "standard PDF you can fill in and edit.")
        )
        headline.setWordWrap(True)
        layout.addWidget(headline)

        if summary is not None:
            layout.addWidget(self._describe(summary))

        note = QLabel(
            tr("The original file is not changed. The conversion is saved as a "
               "new document beside it.")
        )
        note.setWordWrap(True)
        note.setProperty("role", "hint")
        layout.addWidget(note)

        layout.addWidget(self._modes())

        buttons = QDialogButtonBox()
        convert = QPushButton(tr("Convert"))
        convert.setDefault(True)
        read_only = QPushButton(tr("Open read-only"))
        buttons.addButton(convert, QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(read_only, QDialogButtonBox.ButtonRole.ActionRole)
        buttons.addButton(QDialogButtonBox.StandardButton.Cancel)

        convert.clicked.connect(self._convert)
        read_only.clicked.connect(self._read_only)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _describe(self, summary) -> QLabel:
        """What is in the form, in a line the user can weigh."""
        parts = [
            tr("{count} fields").format(count=summary.fields),
        ]
        if summary.choice_lists:
            parts.append(tr("{count} lists").format(count=summary.choice_lists))
        if summary.date_fields:
            parts.append(tr("{count} dates").format(count=summary.date_fields))
        if summary.repeatable:
            parts.append(
                tr("{count} repeating sections").format(count=summary.repeatable)
            )
        if summary.scripts:
            parts.append(tr("{count} automatic rules").format(count=summary.scripts))
        label = QLabel(tr("Orion found: {parts}.").format(parts=", ".join(parts)))
        label.setWordWrap(True)
        return label

    def _modes(self) -> QWidget:
        box = QWidget()
        column = QVBoxLayout(box)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(4)

        self._keep = QRadioButton(tr("Keep as many fields as possible (recommended)"))
        self._keep.setChecked(True)
        self._editable = QRadioButton(tr("Make every field fillable"))
        self._static = QRadioButton(tr("Convert to a document that cannot be filled in"))
        for button in (self._keep, self._editable, self._static):
            column.addWidget(button)
        return box

    @property
    def mode(self) -> ConversionMode:
        if self._editable.isChecked():
            return ConversionMode.EDITABLE
        if self._static.isChecked():
            return ConversionMode.STATIC
        return ConversionMode.KEEP_FIELDS

    @property
    def choice(self) -> int:
        return self._choice

    def _convert(self) -> None:
        self._choice = self.CONVERT
        self.accept()

    def _read_only(self) -> None:
        self._choice = self.READ_ONLY
        self.accept()


class XfaReportDialog(QDialog):
    """What the conversion managed, once it has run."""

    def __init__(self, report: XfaConversionReport, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Conversion complete"))
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        headline = QLabel(self._headline(report))
        headline.setWordWrap(True)
        layout.addWidget(headline)

        layout.addWidget(self._counts(report))

        notes = [e for e in report.entries if e.severity is not Severity.INFO]
        if notes:
            heading = QLabel(tr("Worth knowing:"))
            layout.addWidget(heading)
            listing = QListWidget()
            listing.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
            listing.setWordWrap(True)
            for entry in notes:
                item = QListWidgetItem(str(entry))
                if entry.severity is Severity.ERROR:
                    item.setToolTip(tr("This part of the form could not be converted."))
                listing.addItem(item)
            listing.setMinimumHeight(90)
            layout.addWidget(listing, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)
        self.resize(560, 420 if notes else 260)

    @staticmethod
    def _headline(report: XfaConversionReport) -> str:
        """One sentence that does not oversell the result.

        A conversion that lost the form's automatic behaviour is not a
        conversion that "completed successfully", and saying so here is the
        difference between a user who knows to check their totals and one who
        does not.
        """
        from orion.xfa.report import Fidelity

        if report.errors:
            return tr("The form could not be converted.")
        if (
            report.functional_fidelity in (Fidelity.FULL, Fidelity.HIGH)
            and not report.warnings
        ):
            return tr("The form was converted and everything came across.")
        return tr(
            "The form was converted. It looks the same and its fields work, "
            "but some of what it used to do automatically could not be carried "
            "over — see below."
        )

    @staticmethod
    def _counts(report: XfaConversionReport) -> QWidget:
        box = QWidget()
        column = QVBoxLayout(box)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(2)
        for line in _count_lines(report):
            row = QHBoxLayout()
            label = QLabel(line)
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            row.addWidget(label)
            row.addStretch(1)
            holder = QWidget()
            holder.setLayout(row)
            column.addWidget(holder)
        return box


def _count_lines(report: XfaConversionReport) -> list[str]:
    """The figures, each with the word that makes it mean something."""
    lines = [
        tr("Pages: {count}").format(count=report.pages),
        tr("Fields found: {count}").format(count=report.total_xfa_fields),
        tr("Fields you can fill in: {count}").format(count=report.converted_fields),
    ]
    if report.unsupported_elements:
        lines.append(
            tr("Kept as part of the page: {count}").format(
                count=report.unsupported_elements
            )
        )
    if report.hidden_fields_shown:
        lines.append(
            tr("Fields shown here that the form used to hide: {count}").format(
                count=report.hidden_fields_shown
            )
        )
    if report.scripts_found:
        lines.append(
            tr("Automatic rules not carried over: {count}").format(
                count=report.scripts_not_converted
            )
        )
    if report.repeatable_subforms:
        lines.append(
            tr("Rows kept from repeating sections: {count}").format(
                count=report.preserved_instances
            )
        )
    return lines
