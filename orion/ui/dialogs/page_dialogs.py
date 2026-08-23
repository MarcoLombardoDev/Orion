# Orion — PDF Editor for Desktop
# Copyright (C) 2026 Marco Lombardo
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# Distributed WITHOUT ANY WARRANTY; see LICENSE for the full terms.
# A commercial licence, without the AGPL's obligations, is available for use
# in proprietary or closed-source products — see COMMERCIAL-LICENSE.md.

"""Small dialogs for page operations and notes (spec §16, §12)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from orion.pdf import operations
from orion.utils.geometry import Size

__all__ = [
    "GoToPageDialog",
    "InsertPageDialog",
    "PageSelectionDialog",
    "ImportPagesDialog",
    "NoteDialog",
    "PAGE_SIZES",
]

#: Common page sizes in points, offered when inserting a blank page.
PAGE_SIZES: dict[str, Size] = {
    "A4 (210 × 297 mm)": Size(595.28, 841.89),
    "A3 (297 × 420 mm)": Size(841.89, 1190.55),
    "A5 (148 × 210 mm)": Size(419.53, 595.28),
    "US Letter (8.5 × 11 in)": Size(612.0, 792.0),
    "US Legal (8.5 × 14 in)": Size(612.0, 1008.0),
}


class GoToPageDialog(QDialog):
    def __init__(self, page_count: int, current: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Go to Page")
        layout = QFormLayout(self)
        self._spin = QSpinBox()
        self._spin.setRange(1, max(1, page_count))
        self._spin.setValue(current + 1)
        self._spin.selectAll()
        layout.addRow(f"Page (1–{page_count})", self._spin)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    @property
    def page_index(self) -> int:
        return self._spin.value() - 1


class InsertPageDialog(QDialog):
    """Choose the size and position of a new blank page."""

    def __init__(
        self, page_count: int, current: int, default: Size, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Insert Blank Page")
        self._default = default
        layout = QFormLayout(self)

        self._size = QComboBox()
        self._size.addItem(
            f"Same as current page ({default.width:.0f} × {default.height:.0f} pt)", default
        )
        for label, size in PAGE_SIZES.items():
            self._size.addItem(label, size)
        layout.addRow("Size", self._size)

        self._position = QComboBox()
        self._position.addItem("After current page", current + 1)
        self._position.addItem("Before current page", current)
        self._position.addItem("At the beginning", 0)
        self._position.addItem("At the end", page_count)
        layout.addRow("Position", self._position)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    @property
    def size(self) -> Size:
        return self._size.currentData()

    @property
    def index(self) -> int:
        return int(self._position.currentData())


class PageSelectionDialog(QDialog):
    """Ask for a set of pages, e.g. for Extract Pages."""

    def __init__(
        self,
        page_count: int,
        *,
        title: str = "Select Pages",
        prompt: str = "Pages",
        initial: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(360)
        self._page_count = page_count

        layout = QVBoxLayout(self)
        form = QFormLayout()
        self._field = QLineEdit(initial)
        self._field.setPlaceholderText("for example  1-3, 7, 10-12")
        form.addRow(f"{prompt} (1–{page_count})", self._field)
        layout.addLayout(form)

        self._message = QLabel()
        self._message.setProperty("role", "hint")
        self._message.setWordWrap(True)
        layout.addWidget(self._message)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)
        layout.addWidget(self._buttons)

        self._field.textChanged.connect(self._validate)
        self._validate()

    def _validate(self) -> None:
        try:
            indices = self.indices()
        except ValueError as exc:
            self._message.setText(str(exc))
            self._buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
            return
        self._message.setText(f"{len(indices)} page{'s' if len(indices) != 1 else ''} selected.")
        self._buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(bool(indices))

    def indices(self) -> list[int]:
        groups = operations.parse_page_ranges(self._field.text(), self._page_count)
        seen: list[int] = []
        for group in groups:
            for index in group:
                if index not in seen:
                    seen.append(index)
        return seen


class ImportPagesDialog(PageSelectionDialog):
    """Choose which pages of another PDF to import, and where to put them."""

    def __init__(
        self, path: Path, page_count: int, insert_at: int, total: int, parent: QWidget | None = None
    ) -> None:
        super().__init__(
            page_count,
            title="Import Pages",
            prompt=f"Pages from “{path.name}”",
            initial=f"1-{page_count}",
            parent=parent,
        )
        self._position = QComboBox()
        self._position.addItem("After current page", insert_at)
        self._position.addItem("At the beginning", 0)
        self._position.addItem("At the end", total)
        form = QFormLayout()
        form.addRow("Insert", self._position)
        self.layout().insertLayout(1, form)

    @property
    def insert_index(self) -> int:
        return int(self._position.currentData())


class NoteDialog(QDialog):
    """Edit the text of a comment or sticky note."""

    def __init__(
        self,
        text: str = "",
        author: str = "",
        *,
        title: str = "Comment",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumSize(400, 240)

        layout = QVBoxLayout(self)
        self._editor = QPlainTextEdit(text)
        self._editor.setPlaceholderText("Write your note…")
        layout.addWidget(self._editor, 1)

        form = QFormLayout()
        self._author = QLineEdit(author)
        self._author.setPlaceholderText("Optional")
        form.addRow("Author", self._author)
        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._editor.setFocus()

    @property
    def text(self) -> str:
        return self._editor.toPlainText()

    @property
    def author(self) -> str:
        return self._author.text().strip()
