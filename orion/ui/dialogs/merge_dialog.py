# Orion — PDF Editor for Desktop
# Copyright (C) 2026 Marco Lombardo
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# Distributed WITHOUT ANY WARRANTY; see LICENSE for the full terms.
# A commercial licence, without the AGPL's obligations, is available for use
# in proprietary or closed-source products — see COMMERCIAL-LICENSE.md.

"""Merge several PDFs, with the order under the user's control (spec §17)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from orion.i18n import tr
from orion.pdf import operations
from orion.pdf.errors import OrionPdfError

__all__ = ["MergeDialog", "CURRENT_DOCUMENT"]

#: Sentinel identifying "the document currently open" in the merge list.
CURRENT_DOCUMENT = object()


class MergeDialog(QDialog):
    """Pick documents and drag them into the order they should be joined."""

    def __init__(self, parent: QWidget | None = None, *, current_name: str | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Merge PDF"))
        self.setMinimumSize(500, 380)
        self._current_name = current_name

        layout = QVBoxLayout(self)
        hint = QLabel(
            "Add the documents to merge, then drag them into the order you want. "
            "The result is written to a new file."
        )
        hint.setWordWrap(True)
        hint.setProperty("role", "hint")
        layout.addWidget(hint)

        self._list = QListWidget()
        self._list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self._list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._list.setAlternatingRowColors(True)
        layout.addWidget(self._list, 1)

        buttons_row = QWidget()
        row = QHBoxLayout(buttons_row)
        row.setContentsMargins(0, 0, 0, 0)
        add = QPushButton(tr("Add Files…"))
        add.clicked.connect(self._add_files)
        row.addWidget(add)

        if current_name:
            add_current = QPushButton(tr("Add Current Document"))
            add_current.clicked.connect(self._add_current)
            row.addWidget(add_current)

        remove = QPushButton(tr("Remove"))
        remove.clicked.connect(self._remove_selected)
        row.addWidget(remove)

        up = QPushButton(tr("Move Up"))
        up.clicked.connect(lambda: self._move(-1))
        row.addWidget(up)

        down = QPushButton(tr("Move Down"))
        down.clicked.connect(lambda: self._move(1))
        row.addWidget(down)
        row.addStretch(1)
        layout.addWidget(buttons_row)

        self._summary = QLabel()
        self._summary.setProperty("role", "hint")
        layout.addWidget(self._summary)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._buttons.button(QDialogButtonBox.StandardButton.Ok).setText(tr("Merge…"))
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)
        layout.addWidget(self._buttons)

        self._list.model().rowsInserted.connect(self._update_state)
        self._list.model().rowsRemoved.connect(self._update_state)
        self._list.model().rowsMoved.connect(self._update_state)
        self._update_state()

    # -- list management ---------------------------------------------------
    def _add_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, tr("Select PDF files to merge"), "", tr("PDF documents (*.pdf)")
        )
        for path in paths:
            self._append(Path(path))
        self._update_state()

    def _add_current(self) -> None:
        for row in range(self._list.count()):
            if self._list.item(row).data(Qt.ItemDataRole.UserRole) is CURRENT_DOCUMENT:
                return
        item = QListWidgetItem(f"{self._current_name}  (current document)")
        item.setData(Qt.ItemDataRole.UserRole, CURRENT_DOCUMENT)
        self._list.addItem(item)
        self._update_state()

    def _append(self, path: Path) -> None:
        try:
            pages = operations.page_count_of(path)
            label = f"{path.name}  ({pages} pages)"
        except OrionPdfError as exc:
            label = f"{path.name}  — {exc.message}"
        item = QListWidgetItem(label)
        item.setData(Qt.ItemDataRole.UserRole, path)
        item.setToolTip(str(path))
        self._list.addItem(item)

    def _remove_selected(self) -> None:
        for item in self._list.selectedItems():
            self._list.takeItem(self._list.row(item))
        self._update_state()

    def _move(self, delta: int) -> None:
        rows = sorted(self._list.row(i) for i in self._list.selectedItems())
        if not rows:
            return
        if delta < 0 and rows[0] == 0:
            return
        if delta > 0 and rows[-1] == self._list.count() - 1:
            return
        for row in (rows if delta < 0 else reversed(rows)):
            item = self._list.takeItem(row)
            self._list.insertItem(row + delta, item)
            item.setSelected(True)
        self._update_state()

    def _update_state(self, *_args) -> None:
        count = self._list.count()
        self._summary.setText(
            tr("Add at least two documents.") if count < 2 else f"{count} documents will be merged."
        )
        self._buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(count >= 2)

    # -- result ------------------------------------------------------------
    def items(self) -> list[object]:
        """The documents to merge, in the chosen order."""
        return [
            self._list.item(row).data(Qt.ItemDataRole.UserRole)
            for row in range(self._list.count())
        ]
