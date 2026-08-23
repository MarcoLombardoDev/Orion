# Orion — PDF Editor for Desktop
# Copyright (C) 2026 Marco Lombardo
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# Distributed WITHOUT ANY WARRANTY; see LICENSE for the full terms.
# A commercial licence, without the AGPL's obligations, is available for use
# in proprietary or closed-source products — see COMMERCIAL-LICENSE.md.

"""The status bar: page position, zoom, fit mode and transient messages."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QStatusBar, QWidget

__all__ = ["OrionStatusBar"]


class OrionStatusBar(QStatusBar):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setSizeGripEnabled(True)

        self._page = QLabel()
        self._zoom = QLabel()
        self._mode = QLabel()
        self._modified = QLabel()

        for label in (self._page, self._zoom, self._mode, self._modified):
            label.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self.addPermanentWidget(self._modified)
        self.addPermanentWidget(self._page)
        self.addPermanentWidget(self._zoom)
        self.addPermanentWidget(self._mode)
        self.clear_document()

    def set_page(self, index: int, total: int) -> None:
        self._page.setText(f"Page {index + 1} / {total}" if total else "")

    def set_zoom(self, zoom: float, mode: str) -> None:
        self._zoom.setText(f"Zoom {round(zoom * 100)}%")
        self._mode.setText(
            {"fit_width": "Fit Width", "fit_page": "Fit Page"}.get(mode, "Custom Zoom")
        )

    def set_modified(self, modified: bool) -> None:
        self._modified.setText("Modified" if modified else "")

    def clear_document(self) -> None:
        self._page.clear()
        self._zoom.clear()
        self._mode.clear()
        self._modified.clear()

    def flash(self, message: str, milliseconds: int = 4000) -> None:
        self.showMessage(message, milliseconds)
