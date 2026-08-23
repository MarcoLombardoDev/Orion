# Orion — PDF Editor for Desktop
# Copyright (C) 2026 Marco Lombardo
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# Distributed WITHOUT ANY WARRANTY; see LICENSE for the full terms.
# A commercial licence, without the AGPL's obligations, is available for use
# in proprietary or closed-source products — see COMMERCIAL-LICENSE.md.

"""Small reusable widgets shared by the panels and dialogs."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QColorDialog, QToolButton, QWidget

from orion.document.objects import Color

__all__ = ["ColorButton", "to_qcolor", "from_qcolor"]


def to_qcolor(color: Color | None, fallback: QColor | None = None) -> QColor:
    if color is None:
        return fallback or QColor(Qt.GlobalColor.transparent)
    return QColor.fromRgbF(*color)


def from_qcolor(color: QColor) -> Color:
    return (color.redF(), color.greenF(), color.blueF())


class ColorButton(QToolButton):
    """A swatch that opens a colour picker; supports an explicit "no colour"."""

    color_changed = Signal(object)  # Color | None

    def __init__(
        self,
        color: Color | None = None,
        *,
        allow_none: bool = False,
        title: str = "Select Colour",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._color = color
        self._allow_none = allow_none
        self._title = title
        self.setFixedSize(QSize(30, 22))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clicked.connect(self._choose)
        self._update_tooltip()

    @property
    def color(self) -> Color | None:
        return self._color

    def set_color(self, color: Color | None, *, notify: bool = False) -> None:
        if color == self._color:
            return
        self._color = color
        self._update_tooltip()
        self.update()
        if notify:
            self.color_changed.emit(color)

    def _update_tooltip(self) -> None:
        if self._color is None:
            self.setToolTip("No colour")
        else:
            self.setToolTip(to_qcolor(self._color).name().upper())

    def _choose(self) -> None:
        options = QColorDialog.ColorDialogOption.DontUseNativeDialog
        if self._allow_none:
            options |= QColorDialog.ColorDialogOption.ShowAlphaChannel
        initial = to_qcolor(self._color, QColor(Qt.GlobalColor.white))
        if self._allow_none and self._color is None:
            initial.setAlpha(0)
        chosen = QColorDialog.getColor(initial, self, self._title, options)
        if not chosen.isValid():
            return
        if self._allow_none and chosen.alpha() == 0:
            self.set_color(None, notify=True)
            return
        self.set_color(from_qcolor(chosen), notify=True)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt naming
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = self.rect().adjusted(2, 2, -2, -2)

        if self._color is None:
            painter.setBrush(QColor(Qt.GlobalColor.white))
            painter.setPen(QPen(QColor("#9aa2af")))
            painter.drawRoundedRect(rect, 4, 4)
            pen = QPen(QColor("#d64545"))
            pen.setWidth(2)
            painter.setPen(pen)
            painter.drawLine(rect.topRight(), rect.bottomLeft())
        else:
            painter.setBrush(to_qcolor(self._color))
            painter.setPen(QPen(QColor("#9aa2af")))
            painter.drawRoundedRect(rect, 4, 4)

        if self.underMouse():
            pen = QPen(QColor("#2f6feb"))
            pen.setWidth(2)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 5, 5)
        painter.end()

    def enterEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().enterEvent(event)
        self.update()

    def leaveEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().leaveEvent(event)
        self.update()
