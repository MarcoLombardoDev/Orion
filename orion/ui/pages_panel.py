# Orion — PDF Editor for Desktop
# Copyright (C) 2026 Marco Lombardo
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# Distributed WITHOUT ANY WARRANTY; see LICENSE for the full terms.
# A commercial licence, without the AGPL's obligations, is available for use
# in proprietary or closed-source products — see COMMERCIAL-LICENSE.md.

"""The page thumbnails, with the page commands beside them.

Everything under the Pages menu used to be *only* under the Pages menu, which
put the commands about pages a long way from the pages themselves: the user
selects three thumbnails and then goes hunting along the menu bar for the verb.
The strip down this panel's edge carries the same actions — the window's own,
not copies, so each keeps its shortcut and its enabled state — right next to
the thing they act on.

The panel also draws the line that separates it from the tool palette. Two
vertical strips of icons side by side with nothing between them read as one
strip of icons that has been arranged oddly; the rule says where the tools stop
and the pages begin.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QToolBar, QWidget

from orion.ui.actions import ActionRegistry
from orion.ui.thumbnails import ThumbnailPanel

__all__ = ["PagesPanel"]

#: Every Pages action, in the menu's order, with ``None`` for a separator.
PAGE_COMMANDS: tuple[str | None, ...] = (
    "pages.insert",
    "pages.duplicate",
    "pages.delete",
    None,
    "pages.rotate_left",
    "pages.rotate_right",
    "pages.rotate_180",
    None,
    "pages.move_up",
    "pages.move_down",
    None,
    "pages.import",
    "pages.extract",
    "pages.split",
)


class PagesPanel(QWidget):
    """The thumbnails, and the commands that act on them."""

    def __init__(self, actions: ActionRegistry, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("pages_panel")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # The divider. A QFrame rather than a border on the panel, because a
        # styled border on a dock's widget gets clipped at the dock's own edge
        # on some platforms and simply is not drawn on others.
        self._divider = QFrame(self)
        self._divider.setObjectName("pages_divider")
        self._divider.setFrameShape(QFrame.Shape.VLine)
        self._divider.setFrameShadow(QFrame.Shadow.Plain)
        self._divider.setFixedWidth(1)
        layout.addWidget(self._divider)

        self._commands = QToolBar("Pages", self)
        self._commands.setObjectName("pages_commands")
        self._commands.setMovable(False)
        self._commands.setFloatable(False)
        self._commands.setOrientation(Qt.Orientation.Vertical)
        self._commands.setIconSize(QSize(18, 18))
        self._commands.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        for key in PAGE_COMMANDS:
            if key is None:
                self._commands.addSeparator()
            else:
                self._commands.addAction(actions[key])
        # Pinned to the width of one button. Left to itself a vertical QToolBar
        # asks for room enough for its widest *label* even when it is showing
        # none, which here came to 136px -- wider than the thumbnails beside
        # it. That made the dock's minimum wider than the width the window
        # asks for it, and the two then argued: the dock pushed, the canvas
        # resized, fit-page recomputed the zoom, and the resize came round
        # again. The window hung on the first page rotation.
        self._commands.setFixedWidth(self._commands.iconSize().width() + 16)
        layout.addWidget(self._commands)

        self.thumbnails = ThumbnailPanel(self)
        layout.addWidget(self.thumbnails, 1)

    def apply_theme(self, theme) -> None:
        """Colour the divider by hand; a QFrame line ignores the palette."""
        self._divider.setStyleSheet(f"background: {theme.border}; border: 0px;")
        self.thumbnails.apply_theme(theme)
