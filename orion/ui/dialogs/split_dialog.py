# Orion — PDF Editor for Desktop
# Copyright (C) 2026 Marco Lombardo
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# Distributed WITHOUT ANY WARRANTY; see LICENSE for the full terms.
# A commercial licence, without the AGPL's obligations, is available for use
# in proprietary or closed-source products — see COMMERCIAL-LICENSE.md.

"""Split the current document into several files (spec §18)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from orion.pdf import operations

__all__ = ["SplitDialog"]


class SplitDialog(QDialog):
    """Split every N pages, or by explicit page ranges."""

    def __init__(self, page_count: int, output_dir: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Split PDF")
        self.setMinimumWidth(460)
        self._page_count = page_count

        layout = QVBoxLayout(self)
        header = QLabel(f"This document has {page_count} pages.")
        header.setProperty("role", "hint")
        layout.addWidget(header)

        self._every_radio = QRadioButton("Split every")
        self._every_radio.setChecked(True)
        self._every_spin = QSpinBox()
        self._every_spin.setRange(1, max(1, page_count))
        self._every_spin.setValue(1)
        self._every_spin.setSuffix(" pages")
        every_row = QWidget()
        every_layout = QHBoxLayout(every_row)
        every_layout.setContentsMargins(0, 0, 0, 0)
        every_layout.addWidget(self._every_radio)
        every_layout.addWidget(self._every_spin)
        every_layout.addStretch(1)
        layout.addWidget(every_row)

        self._ranges_radio = QRadioButton("Split by page ranges")
        layout.addWidget(self._ranges_radio)
        self._ranges_field = QLineEdit()
        self._ranges_field.setPlaceholderText("for example  1-5, 6-10, 11-20")
        self._ranges_field.setEnabled(False)
        layout.addWidget(self._ranges_field)

        self._ranges_radio.toggled.connect(self._ranges_field.setEnabled)
        self._ranges_radio.toggled.connect(lambda on: self._every_spin.setEnabled(not on))
        self._ranges_field.textChanged.connect(self._validate)

        folder_row = QWidget()
        folder_layout = QHBoxLayout(folder_row)
        folder_layout.setContentsMargins(0, 0, 0, 0)
        folder_layout.addWidget(QLabel("Save to"))
        self._folder_field = QLineEdit(str(output_dir))
        folder_layout.addWidget(self._folder_field, 1)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._choose_folder)
        folder_layout.addWidget(browse)
        layout.addWidget(folder_row)

        self._message = QLabel()
        self._message.setWordWrap(True)
        self._message.setProperty("role", "hint")
        layout.addWidget(self._message)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Split")
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)
        layout.addWidget(self._buttons)
        self._validate()

    def _choose_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "Choose an output folder", self._folder_field.text()
        )
        if folder:
            self._folder_field.setText(folder)

    def _validate(self) -> None:
        ok = True
        if self._ranges_radio.isChecked():
            try:
                groups = operations.parse_page_ranges(self._ranges_field.text(), self._page_count)
                self._message.setText(f"{len(groups)} files will be created.")
            except ValueError as exc:
                self._message.setText(str(exc))
                ok = False
        else:
            count = -(-self._page_count // max(1, self._every_spin.value()))
            self._message.setText(f"{count} files will be created.")
        self._buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(ok)

    def accept(self) -> None:
        if self._ranges_radio.isChecked():
            try:
                operations.parse_page_ranges(self._ranges_field.text(), self._page_count)
            except ValueError as exc:
                self._message.setText(str(exc))
                return
        super().accept()

    # -- result ------------------------------------------------------------
    @property
    def output_dir(self) -> Path:
        return Path(self._folder_field.text())

    def groups(self) -> list[list[int]] | None:
        """Explicit page groups, or ``None`` when splitting every N pages."""
        if not self._ranges_radio.isChecked():
            return None
        return operations.parse_page_ranges(self._ranges_field.text(), self._page_count)

    @property
    def every(self) -> int:
        return self._every_spin.value()
