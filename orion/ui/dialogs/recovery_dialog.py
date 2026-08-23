# Orion — PDF Editor for Desktop
# Copyright (C) 2026 Marco Lombardo
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# Distributed WITHOUT ANY WARRANTY; see LICENSE for the full terms.
# A commercial licence, without the AGPL's obligations, is available for use
# in proprietary or closed-source products — see COMMERCIAL-LICENSE.md.

"""Offer to restore work recovered after a crash (spec §32)."""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from orion.services.autosave import RecoverySnapshot

__all__ = ["RecoveryDialog"]


class RecoveryDialog(QDialog):
    """Lists snapshots left by a previous session."""

    def __init__(
        self, snapshots: Sequence[RecoverySnapshot], parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Recover Unsaved Work")
        self.setMinimumSize(460, 300)
        self._snapshots = list(snapshots)

        layout = QVBoxLayout(self)
        hint = QLabel(
            "Orion did not close normally last time. These documents had unsaved "
            "changes. Recovering opens the saved state — your original PDF files "
            "were never modified."
        )
        hint.setWordWrap(True)
        hint.setProperty("role", "hint")
        layout.addWidget(hint)

        self._list = QListWidget()
        for snapshot in self._snapshots:
            item = QListWidgetItem(
                f"{snapshot.display_name} — {snapshot.page_count} pages, saved {snapshot.age_text}"
            )
            item.setData(Qt.ItemDataRole.UserRole, snapshot)
            self._list.addItem(item)
        self._list.setCurrentRow(0)
        layout.addWidget(self._list, 1)

        buttons = QDialogButtonBox()
        buttons.addButton("Recover", QDialogButtonBox.ButtonRole.AcceptRole)
        discard = buttons.addButton("Discard All", QDialogButtonBox.ButtonRole.DestructiveRole)
        buttons.addButton("Not Now", QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        discard.clicked.connect(self._discard_all)
        layout.addWidget(buttons)
        self._discarded = False

    def _discard_all(self) -> None:
        for snapshot in self._snapshots:
            snapshot.discard()
        self._discarded = True
        self.reject()

    @property
    def discarded(self) -> bool:
        return self._discarded

    def selected(self) -> RecoverySnapshot | None:
        item = self._list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item is not None else None
