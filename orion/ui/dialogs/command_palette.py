# Orion — PDF Editor for Desktop
# Copyright (C) 2026 Marco Lombardo
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# Distributed WITHOUT ANY WARRANTY; see LICENSE for the full terms.
# A commercial licence, without the AGPL's obligations, is available for use
# in proprietary or closed-source products — see COMMERCIAL-LICENSE.md.

"""Type a few letters, get the command.

Orion has grown past the point where a menu bar is a good way to find things:
there are now some sixty actions across six menus, and the honest failure of a
menu is that it only helps someone who already knows which menu the thing is
in. Watermark is under Tools; page numbers are too; exporting images is under
File. None of that is guessable, and all of it is one search away.

Matching is by subsequence rather than substring — "wm" finds Watermark, "epg"
finds Export Pages — because that is what makes a short query worth typing.
Ranking prefers a match that starts at the beginning of a word, then the
shortest label, so the obvious command for a query is the one already selected
when the user presses Enter.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QAction, QKeyEvent
from PySide6.QtWidgets import (
    QDialog,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from orion.i18n import tr

__all__ = ["CommandPalette", "match_score", "rank_actions"]

#: Shown at once; more than this and the list is a scroll bar, not an answer.
VISIBLE_ROWS = 12


@dataclass(frozen=True, slots=True)
class _Scored:
    action: QAction
    score: tuple[int, int, int]


def match_score(query: str, label: str) -> tuple[int, int, int] | None:
    """How well *label* matches *query*, or None if it does not.

    Lower is better, so the tuple sorts directly. Its three parts, in order of
    weight: whether the match began at the start of a word, how far into the
    label the first matched letter was, and the label's length. The first is
    what makes "wm" put Watermark above "Show Bookmarks", and the last is what
    breaks ties towards the plainer of two commands.
    """
    if not query:
        return (1, 0, len(label))
    haystack = label.casefold()
    needle = query.casefold().replace(" ", "")
    if not needle:
        return (1, 0, len(label))

    position = 0
    first = -1
    at_word_start = True
    for character in needle:
        found = haystack.find(character, position)
        if found < 0:
            return None
        if first < 0:
            first = found
            at_word_start = found == 0 or not haystack[found - 1].isalnum()
        position = found + 1
    return (0 if at_word_start else 1, first, len(label))


def rank_actions(actions: list[QAction], query: str) -> list[QAction]:
    """The actions matching *query*, best first.

    Disabled actions are left out rather than shown greyed: the palette is a
    way to *do* something, and offering a command that cannot run is a dead
    end dressed up as an answer.
    """
    scored: list[_Scored] = []
    for action in actions:
        if not action.isEnabled() or not action.text():
            continue
        score = match_score(query, _plain(action.text()))
        if score is not None:
            scored.append(_Scored(action, score))
    scored.sort(key=lambda entry: (entry.score, _plain(entry.action.text())))
    return [entry.action for entry in scored]


def _plain(text: str) -> str:
    """A menu label as a person reads it: no ampersands, no trailing dots."""
    return text.replace("&", "").replace("…", "").strip()


class CommandPalette(QDialog):
    """A filter over every action the window has."""

    def __init__(self, actions: list[QAction], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Commands"))
        self.setModal(True)
        self._actions = actions
        self._chosen: QAction | None = None

        layout = QVBoxLayout(self)
        self._query = QLineEdit()
        self._query.setPlaceholderText(tr("Type a command…"))
        self._query.textChanged.connect(self._refresh)
        self._query.installEventFilter(self)
        layout.addWidget(self._query)

        self._list = QListWidget()
        self._list.setAlternatingRowColors(True)
        self._list.itemActivated.connect(self._choose)
        self._list.itemClicked.connect(self._choose)
        layout.addWidget(self._list)

        self.resize(QSize(460, 380))
        self._refresh("")

    # -- behaviour --------------------------------------------------------
    def _refresh(self, query: str) -> None:
        self._list.clear()
        for action in rank_actions(self._actions, query)[:200]:
            item = QListWidgetItem(_plain(action.text()))
            shortcut = action.shortcut().toString()
            if shortcut:
                item.setText(f"{_plain(action.text())}\t{shortcut}")
            if not action.icon().isNull():
                item.setIcon(action.icon())
            item.setData(Qt.ItemDataRole.UserRole, action)
            item.setToolTip(action.toolTip())
            self._list.addItem(item)
        if self._list.count():
            self._list.setCurrentRow(0)

    def eventFilter(self, watched, event) -> bool:  # noqa: N802 - Qt naming
        """Let the arrow keys drive the list while the cursor stays in the box.

        Without this the user has to leave the field to choose anything, which
        defeats the point of typing.
        """
        if (
            watched is self._query
            and isinstance(event, QKeyEvent)
            and event.type() == QKeyEvent.Type.KeyPress
        ):
            if event.key() in (Qt.Key.Key_Down, Qt.Key.Key_Up):
                row = self._list.currentRow()
                step = 1 if event.key() == Qt.Key.Key_Down else -1
                self._list.setCurrentRow(max(0, min(self._list.count() - 1, row + step)))
                return True
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                item = self._list.currentItem()
                if item is not None:
                    self._choose(item)
                return True
        return super().eventFilter(watched, event)

    def _choose(self, item: QListWidgetItem) -> None:
        self._chosen = item.data(Qt.ItemDataRole.UserRole)
        self.accept()

    @property
    def chosen(self) -> QAction | None:
        """The action to run, or None if the palette was dismissed."""
        return self._chosen
