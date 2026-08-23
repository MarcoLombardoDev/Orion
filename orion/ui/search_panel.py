# Orion — PDF Editor for Desktop
# Copyright (C) 2026 Marco Lombardo
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# Distributed WITHOUT ANY WARRANTY; see LICENSE for the full terms.
# A commercial licence, without the AGPL's obligations, is available for use
# in proprietary or closed-source products — see COMMERCIAL-LICENSE.md.

"""Text search across the document (spec §6).

Searching runs page by page on demand rather than indexing the whole file up
front, so a 2000-page document is searchable immediately.  Results are shown as
overlays on the canvas and navigated with Enter / Shift+Enter or F3.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QToolButton,
    QWidget,
)

from orion.pdf.renderer import PageRenderer
from orion.utils.geometry import Rect

log = logging.getLogger(__name__)

__all__ = ["SearchPanel", "SearchHit"]


@dataclass(frozen=True, slots=True)
class SearchHit:
    page_index: int
    hit_index: int
    rect: Rect


class SearchPanel(QFrame):
    """A slim find bar shown above the canvas."""

    hits_changed = Signal(object)  # {page_index: [Rect, ...]}; dict needs `object`
    current_hit_changed = Signal(object)  # SearchHit | None
    closed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._renderer: PageRenderer | None = None
        self._document = None
        self._hits: list[SearchHit] = []
        self._current = -1
        self._needle = ""

        self.setFrameShape(QFrame.Shape.NoFrame)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(6)

        from orion.ui.icons import icon

        layout.addWidget(QLabel("Find"))
        self._field = QLineEdit()
        self._field.setPlaceholderText("Search text…")
        self._field.setClearButtonEnabled(True)
        self._field.returnPressed.connect(self.find_next)
        self._field.textChanged.connect(self._on_text_changed)
        layout.addWidget(self._field, 1)

        self._previous_button = QToolButton()
        self._previous_button.setIcon(icon("prev_page", 16))
        self._previous_button.setToolTip("Previous match (Shift+Enter)")
        self._previous_button.clicked.connect(self.find_previous)
        layout.addWidget(self._previous_button)

        self._next_button = QToolButton()
        self._next_button.setIcon(icon("next_page", 16))
        self._next_button.setToolTip("Next match (Enter)")
        self._next_button.clicked.connect(self.find_next)
        layout.addWidget(self._next_button)

        self._status = QLabel()
        self._status.setProperty("role", "hint")
        self._status.setMinimumWidth(96)
        self._status.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self._status)

        self._close_button = QToolButton()
        self._close_button.setIcon(icon("close", 16))
        self._close_button.setToolTip("Close (Esc)")
        self._close_button.clicked.connect(self.close_panel)
        layout.addWidget(self._close_button)

        self.setVisible(False)

    # -- wiring ------------------------------------------------------------
    def set_session(self, session) -> None:
        self._renderer = session.renderer
        self._document = session.document
        self.reset()

    def close_session(self) -> None:
        self._renderer = None
        self._document = None
        self.reset()
        self.setVisible(False)

    # -- lifecycle ---------------------------------------------------------
    def activate(self, initial: str = "") -> None:
        self.setVisible(True)
        if initial:
            self._field.setText(initial)
        self._field.setFocus()
        self._field.selectAll()

    def close_panel(self) -> None:
        self.setVisible(False)
        self.reset()
        self.closed.emit()

    def reset(self) -> None:
        self._hits = []
        self._current = -1
        self._needle = ""
        self._status.clear()
        self.hits_changed.emit({})
        self.current_hit_changed.emit(None)

    # -- searching ---------------------------------------------------------
    def _on_text_changed(self, text: str) -> None:
        if not text:
            self.reset()
            return
        self._search(text)

    def _search(self, needle: str) -> None:
        if self._renderer is None or self._document is None:
            return
        self._needle = needle
        self._hits = []
        for page_index, page in enumerate(self._document.pages):
            try:
                rects = self._renderer.search_page(page, needle)
            except Exception:  # a broken page must not break the search
                log.debug("Search failed on page %d", page_index, exc_info=True)
                continue
            for hit_index, rect in enumerate(rects):
                self._hits.append(SearchHit(page_index, hit_index, rect))

        self.hits_changed.emit(self.grouped_hits())

        self._current = 0 if self._hits else -1
        self._update_status()
        if self._hits:
            self.current_hit_changed.emit(self._hits[0])

    def find_next(self) -> None:
        self._step(1)

    def find_previous(self) -> None:
        self._step(-1)

    def _step(self, direction: int) -> None:
        if not self._hits:
            if self._field.text():
                self._search(self._field.text())
            return
        self._current = (self._current + direction) % len(self._hits)
        self._update_status()
        self.current_hit_changed.emit(self._hits[self._current])

    def _update_status(self) -> None:
        if not self._needle:
            self._status.clear()
        elif not self._hits:
            self._status.setText("No matches")
        else:
            self._status.setText(f"{self._current + 1} of {len(self._hits)}")
        has_hits = bool(self._hits)
        self._next_button.setEnabled(has_hits)
        self._previous_button.setEnabled(has_hits)

    def grouped_hits(self) -> dict[int, list[Rect]]:
        """All hits, keyed by page index — what the canvas overlay needs."""
        grouped: dict[int, list[Rect]] = {}
        for hit in self._hits:
            grouped.setdefault(hit.page_index, []).append(hit.rect)
        return grouped

    @property
    def current_hit(self) -> SearchHit | None:
        if 0 <= self._current < len(self._hits):
            return self._hits[self._current]
        return None

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if event.key() == Qt.Key.Key_Escape:
            self.close_panel()
            event.accept()
            return
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                self.find_previous()
            else:
                self.find_next()
            event.accept()
            return
        super().keyPressEvent(event)
