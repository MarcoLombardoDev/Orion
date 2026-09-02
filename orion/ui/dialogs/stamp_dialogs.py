# Orion — PDF Editor for Desktop
# Copyright (C) 2026 Marco Lombardo
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# Distributed WITHOUT ANY WARRANTY; see LICENSE for the full terms.
# A commercial licence, without the AGPL's obligations, is available for use
# in proprietary or closed-source products — see COMMERCIAL-LICENSE.md.

"""Asking for a watermark or a set of page numbers.

Both dialogs answer with a specification from :mod:`orion.document.stamps` and
a list of page indices, and neither knows what happens next. Both default to
the whole document, because stamping some of the pages is the exception and
typing a range to say "all of them" is a tax on the common case.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QWidget,
)

from orion.i18n import tr
from orion.pdf.fonts import available_families
from orion.pdf.operations import format_page_ranges, parse_page_ranges
from orion.pdf.stamps import Corner, PageNumberSpec, WatermarkSpec
from orion.ui.widgets import ColorButton

__all__ = ["WatermarkDialog", "PageNumberDialog"]


class _RangeRow:
    """The "which pages" field, shared by both dialogs.

    Pre-filled with every page rather than left empty: an empty field that
    silently means "all" is a guess, and one that means "none" is a dead end.
    """

    def __init__(self, form: QFormLayout, page_count: int) -> None:
        self._page_count = page_count
        self._field = QLineEdit(format_page_ranges(range(page_count)))
        self._field.setToolTip("For example: 1-3, 7, 10-12")
        form.addRow("Pages", self._field)

    @property
    def indices(self) -> list[int]:
        try:
            groups = parse_page_ranges(self._field.text(), self._page_count)
        except ValueError:
            return []
        return sorted({index for group in groups for index in group})

    @property
    def is_valid(self) -> bool:
        return bool(self.indices)


def _font_box(default: str = "Helvetica") -> QComboBox:
    box = QComboBox()
    box.addItems(available_families())
    box.setCurrentText(default)
    return box


def _buttons(dialog: QDialog, form: QFormLayout) -> QDialogButtonBox:
    buttons = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
    )
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    form.addRow(buttons)
    return buttons


class WatermarkDialog(QDialog):
    """A word across the middle of every page."""

    def __init__(self, page_count: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Watermark"))
        form = QFormLayout(self)

        self._text = QLineEdit("DRAFT")
        form.addRow("Text", self._text)

        self._font = _font_box()
        form.addRow(tr("Font"), self._font)

        self._size = QDoubleSpinBox()
        self._size.setRange(6.0, 400.0)
        self._size.setValue(60.0)
        self._size.setSuffix(" pt")
        form.addRow("Size", self._size)

        self._color = ColorButton((0.5, 0.5, 0.5), title=tr("Watermark Colour"))
        form.addRow(tr("Colour"), self._color)

        self._opacity = QSpinBox()
        self._opacity.setRange(5, 100)
        self._opacity.setValue(25)
        self._opacity.setSuffix(" %")
        form.addRow(tr("Opacity"), self._opacity)

        self._angle = QSpinBox()
        self._angle.setRange(-90, 90)
        self._angle.setValue(-45)
        self._angle.setSuffix("°")
        form.addRow(tr("Angle"), self._angle)

        self._range = _RangeRow(form, page_count)
        note = QLabel(
            "The watermark is added as text you can move, restyle or delete "
            "afterwards, on each page you choose."
        )
        note.setWordWrap(True)
        form.addRow(note)
        _buttons(self, form)

    @property
    def spec(self) -> WatermarkSpec:
        return WatermarkSpec(
            text=self._text.text() or "DRAFT",
            font_family=self._font.currentText(),
            font_size=float(self._size.value()),
            color=self._color.color or (0.5, 0.5, 0.5),
            opacity=self._opacity.value() / 100.0,
            rotation=float(self._angle.value()),
        )

    @property
    def indices(self) -> list[int]:
        return self._range.indices


class PageNumberDialog(QDialog):
    """Numbers along an edge."""

    def __init__(self, page_count: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Page Numbers"))
        form = QFormLayout(self)

        self._template = QLineEdit("{n}")
        self._template.setToolTip("{n} is the number, {total} the count")
        form.addRow(tr("Format"), self._template)

        self._corner = QComboBox()
        for corner in Corner:
            self._corner.addItem(corner.label, corner)
        self._corner.setCurrentText(Corner.BOTTOM_CENTRE.label)
        form.addRow(tr("Position"), self._corner)

        self._font = _font_box()
        form.addRow(tr("Font"), self._font)

        self._size = QDoubleSpinBox()
        self._size.setRange(4.0, 72.0)
        self._size.setValue(10.0)
        self._size.setSuffix(" pt")
        form.addRow("Size", self._size)

        self._color = ColorButton((0.0, 0.0, 0.0), title=tr("Page Number Colour"))
        form.addRow(tr("Colour"), self._color)

        self._start = QSpinBox()
        self._start.setRange(0, 99999)
        self._start.setValue(1)
        self._start.setToolTip(tr("What the first numbered page is called"))
        form.addRow(tr("Start at"), self._start)

        self._range = _RangeRow(form, page_count)
        note = QLabel(
            "Leave a cover page out of the range rather than starting at 0: "
            "the pages you choose are numbered in order from the start value."
        )
        note.setWordWrap(True)
        form.addRow(note)
        _buttons(self, form)

    @property
    def spec(self) -> PageNumberSpec:
        return PageNumberSpec(
            template=self._template.text() or "{n}",
            corner=self._corner.currentData(),
            font_family=self._font.currentText(),
            font_size=float(self._size.value()),
            color=self._color.color or (0.0, 0.0, 0.0),
            start_at=int(self._start.value()),
        )

    @property
    def indices(self) -> list[int]:
        return self._range.indices
