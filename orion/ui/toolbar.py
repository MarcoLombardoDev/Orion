# Orion — PDF Editor for Desktop
# Copyright (C) 2026 Marco Lombardo
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# Distributed WITHOUT ANY WARRANTY; see LICENSE for the full terms.
# A commercial licence, without the AGPL's obligations, is available for use
# in proprietary or closed-source products — see COMMERCIAL-LICENSE.md.

"""The main toolbar and the tool palette (spec §7, §31)."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QActionGroup
from PySide6.QtWidgets import (
    QComboBox,
    QLabel,
    QSizePolicy,
    QSpinBox,
    QToolBar,
    QWidget,
)

from orion.ui.actions import ActionRegistry
from orion.ui.tools import Tool

__all__ = ["MainToolBar", "ToolPalette", "ZOOM_PRESETS"]

ZOOM_PRESETS = (25, 50, 75, 100, 125, 150, 200, 400)


class MainToolBar(QToolBar):
    """File, history, navigation and zoom — the things used constantly."""

    zoom_entered = Signal(float)
    page_entered = Signal(int)

    def __init__(self, actions: ActionRegistry, parent: QWidget | None = None) -> None:
        super().__init__("Main", parent)
        self.setObjectName("main_toolbar")
        self.setMovable(False)
        self.setIconSize(QSize(20, 20))
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)

        for key in ("file.open", "file.save"):
            self.addAction(actions[key])
        self.addSeparator()
        for key in ("edit.undo", "edit.redo"):
            self.addAction(actions[key])
        self.addSeparator()

        self.addAction(actions["view.first_page"])
        self.addAction(actions["view.previous_page"])

        self._page_spin = QSpinBox()
        self._page_spin.setRange(1, 1)
        self._page_spin.setFixedWidth(66)
        self._page_spin.setAlignment(Qt.AlignmentFlag.AlignRight)
        self._page_spin.setToolTip("Current page")
        self._page_spin.setKeyboardTracking(False)
        self._page_spin.valueChanged.connect(lambda value: self.page_entered.emit(value - 1))
        self.addWidget(self._page_spin)

        self._page_total = QLabel(" / 0 ")
        self.addWidget(self._page_total)

        self.addAction(actions["view.next_page"])
        self.addAction(actions["view.last_page"])
        self.addSeparator()

        self.addAction(actions["view.zoom_out"])
        self._zoom_box = QComboBox()
        self._zoom_box.setEditable(True)
        self._zoom_box.setFixedWidth(84)
        self._zoom_box.setToolTip("Zoom")
        self._zoom_box.addItems([f"{value}%" for value in ZOOM_PRESETS])
        self._zoom_box.setCurrentText("100%")
        self._zoom_box.lineEdit().returnPressed.connect(self._emit_zoom)
        self._zoom_box.activated.connect(lambda _index: self._emit_zoom())
        self.addWidget(self._zoom_box)
        self.addAction(actions["view.zoom_in"])
        self.addAction(actions["view.fit_width"])
        self.addAction(actions["view.fit_page"])
        self.addSeparator()
        self.addAction(actions["view.search"])

        spacer = QWidget()
        spacer.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        self.addWidget(spacer)
        self.addAction(actions["view.thumbnails"])
        self.addAction(actions["view.properties"])

        self._updating = False

    def _emit_zoom(self) -> None:
        text = self._zoom_box.currentText().strip().rstrip("%").replace(",", ".")
        try:
            value = float(text)
        except ValueError:
            return
        if value > 0:
            self.zoom_entered.emit(value / 100.0)

    # -- display -----------------------------------------------------------
    def set_zoom(self, zoom: float) -> None:
        if self._updating:
            return
        self._updating = True
        try:
            self._zoom_box.setCurrentText(f"{round(zoom * 100)}%")
        finally:
            self._updating = False

    def set_page(self, index: int, total: int) -> None:
        self._updating = True
        try:
            self._page_spin.setRange(1, max(1, total))
            self._page_spin.setValue(index + 1)
            self._page_total.setText(f" / {total} ")
            self._page_spin.setEnabled(total > 0)
        finally:
            self._updating = False


class ToolPalette(QToolBar):
    """The vertical palette of editing tools, on the left of the canvas."""

    tool_selected = Signal(Tool)

    #: Tools in the order they appear, with ``None`` marking a separator.
    LAYOUT: tuple[Tool | None, ...] = (
        Tool.SELECT,
        Tool.HAND,
        None,
        Tool.TEXT,
        Tool.IMAGE,
        None,
        Tool.RECTANGLE,
        Tool.ELLIPSE,
        Tool.LINE,
        Tool.ARROW,
        None,
        Tool.HIGHLIGHT,
        Tool.UNDERLINE,
        Tool.STRIKEOUT,
        None,
        Tool.FREEHAND,
        Tool.COMMENT,
        Tool.STICKY_NOTE,
    )

    def __init__(self, actions: ActionRegistry, parent: QWidget | None = None) -> None:
        super().__init__("Tools", parent)
        self.setObjectName("tool_palette")
        self.setMovable(False)
        self.setOrientation(Qt.Orientation.Vertical)
        self.setIconSize(QSize(20, 20))

        self._group = QActionGroup(self)
        self._group.setExclusive(True)
        for entry in self.LAYOUT:
            if entry is None:
                self.addSeparator()
                continue
            action = actions.tool_action(entry)
            self._group.addAction(action)
            self.addAction(action)
            action.triggered.connect(
                lambda _checked=False, tool=entry: self.tool_selected.emit(tool)
            )
        actions.tool_action(Tool.SELECT).setChecked(True)

    def set_tool(self, tool: Tool) -> None:
        for action in self._group.actions():
            if action.data() == f"tool.{tool.value}":
                action.setChecked(True)
                return
