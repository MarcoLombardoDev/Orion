# Orion — PDF Editor for Desktop
# Copyright (C) 2026 Marco Lombardo
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# Distributed WITHOUT ANY WARRANTY; see LICENSE for the full terms.
# A commercial licence, without the AGPL's obligations, is available for use
# in proprietary or closed-source products — see COMMERCIAL-LICENSE.md.

"""Choosing which pages to save as images, and at what resolution."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QWidget,
)

from orion.i18n import tr
from orion.pdf.operations import format_page_ranges, parse_page_ranges
from orion.services.export_service import IMAGE_FORMATS

__all__ = ["ExportImagesDialog"]

#: Offered resolutions. 150 is the default because it is the point where a
#: page stops looking like a screenshot and the files are still a sane size.
DPI_CHOICES = (72, 96, 150, 200, 300, 600)


class ExportImagesDialog(QDialog):
    """One image per page, into a folder the caller then asks for."""

    def __init__(self, page_count: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Export Pages as Images"))
        self._page_count = page_count
        form = QFormLayout(self)

        self._range = QLineEdit(format_page_ranges(range(page_count)))
        self._range.setToolTip(tr("For example: 1-3, 7, 10-12"))
        form.addRow("Pages", self._range)

        self._format = QComboBox()
        self._format.addItems(IMAGE_FORMATS)
        form.addRow(tr("Format"), self._format)

        self._dpi = QComboBox()
        for value in DPI_CHOICES:
            self._dpi.addItem(f"{value} dpi", value)
        self._dpi.setCurrentText("150 dpi")
        form.addRow(tr("Resolution"), self._dpi)

        note = QLabel(
            "One file per page, named after the document. The images show what "
            "saving would put in the PDF, including anything you have added."
        )
        note.setWordWrap(True)
        form.addRow(note)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    @property
    def indices(self) -> list[int]:
        try:
            groups = parse_page_ranges(self._range.text(), self._page_count)
        except ValueError:
            return []
        return sorted({index for group in groups for index in group})

    @property
    def image_format(self) -> str:
        return self._format.currentText()

    @property
    def dpi(self) -> int:
        return int(self._dpi.currentData())
