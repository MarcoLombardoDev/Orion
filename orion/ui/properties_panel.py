# Orion — PDF Editor for Desktop
# Copyright (C) 2026 Marco Lombardo
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# Distributed WITHOUT ANY WARRANTY; see LICENSE for the full terms.
# A commercial licence, without the AGPL's obligations, is available for use
# in proprietary or closed-source products — see COMMERCIAL-LICENSE.md.

"""The properties panel (spec §30).

One panel, several *sections*.  Which sections are visible depends on the type
of the selected object, so adding a property to an object type means adding a
row here, not writing a new panel.

Every edit goes through :class:`~orion.commands.object_commands.ModifyObjectCommand`,
so undo works uniformly and dragging a slider still produces one history entry.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from orion.commands.history import History
from orion.commands.object_commands import ModifyObjectCommand, TransformObjectsCommand
from orion.document.annotations import AnnotationKind, AnnotationObject
from orion.document.document import Document
from orion.document.objects import (
    Align,
    ImageObject,
    PageObject,
    ShapeObject,
    TextObject,
)
from orion.pdf.fonts import FontRequest, available_families, resolve
from orion.ui.widgets import ColorButton
from orion.utils.events import Blocker
from orion.utils.geometry import Rect

log = logging.getLogger(__name__)

__all__ = ["PropertiesPanel"]

_ALIGN_LABELS = [
    ("Left", Align.LEFT),
    ("Centre", Align.CENTER),
    ("Right", Align.RIGHT),
    ("Justify", Align.JUSTIFY),
]


def _spin(
    minimum: float,
    maximum: float,
    step: float = 1.0,
    decimals: int = 1,
    suffix: str = "",
) -> QDoubleSpinBox:
    box = QDoubleSpinBox()
    box.setRange(minimum, maximum)
    box.setSingleStep(step)
    box.setDecimals(decimals)
    box.setSuffix(suffix)
    box.setKeyboardTracking(False)
    box.setMinimumWidth(84)
    box.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    return box


class PropertiesPanel(QWidget):
    """Shows and edits the properties of the current selection."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._document: Document | None = None
        self._history: History | None = None
        self._objects: list[PageObject] = []
        self._page_index = 0
        self._blocker = Blocker()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer.addWidget(scroll)

        body = QWidget()
        self._layout = QVBoxLayout(body)
        self._layout.setContentsMargins(10, 10, 10, 10)
        self._layout.setSpacing(10)
        scroll.setWidget(body)

        self._empty = QLabel("Select an object to edit its properties.")
        self._empty.setWordWrap(True)
        self._empty.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._empty.setProperty("role", "hint")
        self._layout.addWidget(self._empty)

        self._build_sections()
        self._layout.addStretch(1)
        self.setMinimumWidth(286)
        self.show_selection([], 0)

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------
    def _build_sections(self) -> None:
        self._heading = QLabel()
        self._heading.setStyleSheet("font-weight: 600;")
        self._layout.addWidget(self._heading)

        self._text_group = self._build_text_section()
        self._image_group = self._build_image_section()
        self._shape_group = self._build_shape_section()
        self._note_group = self._build_note_section()
        self._geometry_group = self._build_geometry_section()
        self._arrange_group = self._build_arrange_section()

        for group in (
            self._text_group,
            self._image_group,
            self._shape_group,
            self._note_group,
            self._geometry_group,
            self._arrange_group,
        ):
            self._layout.addWidget(group)

    def _build_text_section(self) -> QGroupBox:
        group = QGroupBox("Text")
        form = QFormLayout(group)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

        self._text_edit = QPlainTextEdit()
        self._text_edit.setPlaceholderText("Type the text…")
        self._text_edit.setFixedHeight(74)
        self._text_edit.focusOutEvent = self._wrap_focus_out(  # type: ignore[method-assign]
            self._text_edit.focusOutEvent, self._commit_text
        )
        form.addRow(self._text_edit)

        # Editable so a long list can be typed into rather than scrolled: a
        # machine with three hundred fonts makes a plain drop-down useless.
        # Insertion is off, so typing a name that does not exist selects
        # nothing rather than inventing a family.
        self._font_family = QComboBox()
        self._font_family.setEditable(True)
        self._font_family.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self._font_family.addItems(available_families())
        completer = self._font_family.completer()
        if completer is not None:
            completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
            completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self._font_family.activated.connect(
            lambda _index: self._apply(
                {"font_family": self._font_family.currentText()}, "Change Font"
            )
        )
        form.addRow("Font", self._font_family)

        #: Says when the family a document names is not on this machine, or
        #: when the style it asks for is not one the family ships. Silence is
        #: the wrong answer to either: the saved file will not look like the
        #: screen, and nothing else would say so.
        self._font_note = QLabel()
        self._font_note.setWordWrap(True)
        self._font_note.setVisible(False)
        form.addRow("", self._font_note)

        self._font_size = _spin(1.0, 999.0, 1.0, 1, " pt")
        self._font_size.valueChanged.connect(
            lambda value: self._apply({"font_size": float(value)}, "Change Font Size")
        )
        form.addRow("Size", self._font_size)

        style_row = QWidget()
        style_layout = QHBoxLayout(style_row)
        style_layout.setContentsMargins(0, 0, 0, 0)
        self._bold = QCheckBox("Bold")
        self._italic = QCheckBox("Italic")
        self._underline = QCheckBox("Underline")
        styles = ((self._bold, "bold"), (self._italic, "italic"), (self._underline, "underline"))
        for box, key in styles:
            box.toggled.connect(
                lambda value, k=key: self._apply({k: bool(value)}, f"Toggle {k.title()}")
            )
            style_layout.addWidget(box)
        style_layout.addStretch(1)
        form.addRow(style_row)

        self._text_color = ColorButton((0.0, 0.0, 0.0), title="Text Colour")
        self._text_color.color_changed.connect(
            lambda value: self._apply({"color": value}, "Change Colour")
        )
        form.addRow("Colour", self._text_color)

        self._align = QComboBox()
        for label, value in _ALIGN_LABELS:
            self._align.addItem(label, value)
        self._align.currentIndexChanged.connect(
            lambda index: self._apply(
                {"align": self._align.itemData(index)}, "Change Alignment"
            )
        )
        form.addRow("Alignment", self._align)

        self._line_spacing = _spin(0.5, 4.0, 0.05, 2)
        self._line_spacing.valueChanged.connect(
            lambda value: self._apply({"line_spacing": float(value)}, "Change Line Spacing")
        )
        form.addRow("Line spacing", self._line_spacing)
        return group

    def _build_image_section(self) -> QGroupBox:
        group = QGroupBox("Image")
        form = QFormLayout(group)
        self._image_info = QLabel()
        self._image_info.setProperty("role", "hint")
        form.addRow(self._image_info)

        self._keep_aspect = QCheckBox("Lock aspect ratio")
        self._keep_aspect.toggled.connect(
            lambda value: self._apply({"keep_aspect": bool(value)}, "Change Aspect Ratio")
        )
        form.addRow(self._keep_aspect)

        self._reset_aspect = QPushButton("Reset to natural size")
        self._reset_aspect.clicked.connect(self._reset_image_size)
        form.addRow(self._reset_aspect)
        return group

    def _build_shape_section(self) -> QGroupBox:
        group = QGroupBox("Shape")
        form = QFormLayout(group)

        self._stroke_color = ColorButton((0.0, 0.0, 0.0), allow_none=True, title="Stroke Colour")
        self._stroke_color.color_changed.connect(
            lambda value: self._apply({"stroke_color": value}, "Change Stroke Colour")
        )
        form.addRow("Stroke", self._stroke_color)

        self._stroke_width = _spin(0.0, 72.0, 0.5, 2, " pt")
        self._stroke_width.valueChanged.connect(
            lambda value: self._apply({"stroke_width": float(value)}, "Change Stroke Width")
        )
        form.addRow("Stroke width", self._stroke_width)

        self._fill_color = ColorButton(None, allow_none=True, title="Fill Colour")
        self._fill_color.color_changed.connect(
            lambda value: self._apply({"fill_color": value}, "Change Fill Colour")
        )
        form.addRow("Fill", self._fill_color)
        return group

    def _build_note_section(self) -> QGroupBox:
        group = QGroupBox("Annotation")
        form = QFormLayout(group)

        self._annotation_color = ColorButton((1.0, 0.9, 0.2), title="Annotation Colour")
        self._annotation_color.color_changed.connect(
            lambda value: self._apply({"color": value}, "Change Colour")
        )
        form.addRow("Colour", self._annotation_color)

        self._ink_width = _spin(0.2, 40.0, 0.5, 2, " pt")
        self._ink_width.valueChanged.connect(
            lambda value: self._apply({"stroke_width": float(value)}, "Change Stroke Width")
        )
        form.addRow("Pen width", self._ink_width)

        self._contents = QPlainTextEdit()
        self._contents.setPlaceholderText("Comment…")
        self._contents.setFixedHeight(66)
        self._contents.focusOutEvent = self._wrap_focus_out(  # type: ignore[method-assign]
            self._contents.focusOutEvent, self._commit_contents
        )
        form.addRow("Note", self._contents)
        return group

    def _build_geometry_section(self) -> QGroupBox:
        group = QGroupBox("Geometry")
        form = QFormLayout(group)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

        self._x = _spin(-20000.0, 20000.0, 1.0, 1, " pt")
        self._y = _spin(-20000.0, 20000.0, 1.0, 1, " pt")
        self._width = _spin(1.0, 20000.0, 1.0, 1, " pt")
        self._height = _spin(1.0, 20000.0, 1.0, 1, " pt")
        self._rotation = _spin(-360.0, 360.0, 1.0, 1, "°")
        self._opacity = _spin(0.0, 100.0, 5.0, 0, " %")

        for box in (self._x, self._y, self._width, self._height, self._rotation):
            box.valueChanged.connect(self._apply_geometry)
        self._opacity.valueChanged.connect(
            lambda value: self._apply({"opacity": float(value) / 100.0}, "Change Opacity")
        )

        form.addRow("X", self._x)
        form.addRow("Y", self._y)
        form.addRow("Width", self._width)
        form.addRow("Height", self._height)
        form.addRow("Rotation", self._rotation)
        form.addRow("Opacity", self._opacity)
        return group

    def _build_arrange_section(self) -> QGroupBox:
        group = QGroupBox("Arrange")
        layout = QHBoxLayout(group)
        self._front = QPushButton("Bring to Front")
        self._back = QPushButton("Send to Back")
        self._front.clicked.connect(lambda: self.arrange_requested.emit(True))
        self._back.clicked.connect(lambda: self.arrange_requested.emit(False))
        layout.addWidget(self._front)
        layout.addWidget(self._back)
        return group

    arrange_requested = Signal(bool)

    @staticmethod
    def _wrap_focus_out(original: Callable, commit: Callable) -> Callable:
        def handler(event):
            original(event)
            commit()

        return handler

    # ------------------------------------------------------------------
    # Wiring
    # ------------------------------------------------------------------
    def set_session(self, session) -> None:
        self._document = session.document
        self._history = session.history
        self.show_selection([], 0)

    def close_session(self) -> None:
        self._document = None
        self._history = None
        self.show_selection([], 0)

    # ------------------------------------------------------------------
    # Display
    # ------------------------------------------------------------------
    def show_selection(self, objects: Sequence[PageObject], page_index: int) -> None:
        self._objects = list(objects)
        self._page_index = page_index
        single = self._objects[0] if len(self._objects) == 1 else None

        has_selection = bool(self._objects)
        self._empty.setVisible(not has_selection)
        self._heading.setVisible(has_selection)
        for group in (
            self._text_group,
            self._image_group,
            self._shape_group,
            self._note_group,
            self._geometry_group,
            self._arrange_group,
        ):
            group.setVisible(False)
        if not has_selection:
            return

        if single is None:
            self._heading.setText(f"{len(self._objects)} objects selected")
            self._geometry_group.setVisible(True)
            self._arrange_group.setVisible(False)
            with self._blocker:
                self._show_multi_geometry()
            return

        self._heading.setText(single.display_name)
        self._arrange_group.setVisible(True)
        with self._blocker:
            if isinstance(single, TextObject):
                self._show_text(single)
            elif isinstance(single, ImageObject):
                self._show_image(single)
            elif isinstance(single, ShapeObject):
                self._show_shape(single)
            elif isinstance(single, AnnotationObject):
                self._show_annotation(single)
            self._show_geometry(single)

    def refresh(self) -> None:
        """Re-read the current selection (after undo or a canvas gesture)."""
        self.show_selection(self._objects, self._page_index)

    def _show_text(self, obj: TextObject) -> None:
        self._text_group.setVisible(True)
        if self._text_edit.toPlainText() != obj.text:
            self._text_edit.setPlainText(obj.text)
        # A document can name a font this machine does not have. Adding it to
        # the list keeps the panel truthful about what the object says, and
        # keeps the name from being lost the moment anything else is edited.
        if self._font_family.findText(obj.font_family) < 0:
            self._font_family.addItem(obj.font_family)
        self._font_family.setCurrentText(obj.font_family)
        self._show_font_note(obj)
        self._font_size.setValue(obj.font_size)
        self._bold.setChecked(obj.bold)
        self._italic.setChecked(obj.italic)
        self._underline.setChecked(obj.underline)
        self._text_color.set_color(obj.color)
        index = self._align.findData(obj.align)
        self._align.setCurrentIndex(max(0, index))
        self._line_spacing.setValue(obj.line_spacing)

    def _show_font_note(self, obj: TextObject) -> None:
        """Warn when the file will not look like the screen, and why."""
        resolved = resolve(FontRequest(obj.font_family, obj.bold, obj.italic))
        if resolved.substituted:
            message = (
                f"“{obj.font_family}” is not installed here. "
                "Helvetica is being used instead."
            )
        elif resolved.embedded and (obj.bold, obj.italic) != (
            resolved.bold,
            resolved.italic,
        ):
            missing = " ".join(
                word
                for word, wanted, got in (
                    ("bold", obj.bold, resolved.bold),
                    ("italic", obj.italic, resolved.italic),
                )
                if wanted and not got
            )
            message = f"“{obj.font_family}” has no {missing} face; the plain one is used."
        elif resolved.embedded:
            message = "This font is embedded in the saved file."
        else:
            message = ""
        self._font_note.setText(message)
        self._font_note.setVisible(bool(message))

    def _show_image(self, obj: ImageObject) -> None:
        self._image_group.setVisible(True)
        natural = obj.natural_size
        self._image_info.setText(
            f"{obj.image_format.upper()} · {int(natural.width)} × {int(natural.height)} px"
        )
        self._keep_aspect.setChecked(obj.keep_aspect)

    def _show_shape(self, obj: ShapeObject) -> None:
        self._shape_group.setVisible(True)
        self._stroke_color.set_color(obj.stroke_color)
        self._stroke_width.setValue(obj.stroke_width)
        self._fill_color.set_color(obj.fill_color)
        self._fill_color.setEnabled(not obj.shape.is_linear)

    def _show_annotation(self, obj: AnnotationObject) -> None:
        self._note_group.setVisible(True)
        self._annotation_color.set_color(obj.color)
        is_ink = obj.annotation is AnnotationKind.INK
        self._ink_width.setVisible(is_ink)
        self._ink_width.setValue(obj.stroke_width)
        supports_note = obj.annotation.is_note or is_ink or obj.annotation.is_text_markup
        self._contents.setVisible(supports_note)
        if self._contents.toPlainText() != obj.contents:
            self._contents.setPlainText(obj.contents)

    def _show_geometry(self, obj: PageObject) -> None:
        self._geometry_group.setVisible(True)
        rect = obj.rect
        self._x.setValue(rect.x0)
        self._y.setValue(rect.y0)
        self._width.setValue(max(rect.width, self._width.minimum()))
        self._height.setValue(max(rect.height, self._height.minimum()))
        self._rotation.setValue(obj.rotation)
        self._opacity.setValue(obj.opacity * 100.0)

        rotatable = not isinstance(obj, AnnotationObject) or obj.can_rotate
        resizable = not isinstance(obj, AnnotationObject) or obj.can_resize
        self._rotation.setEnabled(rotatable and not obj.locked)
        self._width.setEnabled(resizable and not obj.locked)
        self._height.setEnabled(resizable and not obj.locked)

    def _show_multi_geometry(self) -> None:
        bounds = self._objects[0].rect
        for obj in self._objects[1:]:
            bounds = bounds.united(obj.rect)
        self._x.setValue(bounds.x0)
        self._y.setValue(bounds.y0)
        self._width.setValue(max(bounds.width, self._width.minimum()))
        self._height.setValue(max(bounds.height, self._height.minimum()))
        for box in (self._width, self._height, self._rotation):
            box.setEnabled(False)
        self._rotation.setValue(0.0)
        self._opacity.setValue(self._objects[0].opacity * 100.0)

    # ------------------------------------------------------------------
    # Applying edits
    # ------------------------------------------------------------------
    def _apply(self, changes: dict[str, Any], text: str, *, mergeable: bool = True) -> None:
        if self._blocker or self._history is None or self._document is None:
            return
        applicable = [obj for obj in self._objects if all(hasattr(obj, k) for k in changes)]
        if not applicable:
            return
        if len(applicable) == 1:
            self._history.push(
                ModifyObjectCommand(
                    self._document,
                    self._page_index,
                    applicable[0].id,
                    changes,
                    text=text,
                    mergeable=mergeable,
                )
            )
            return
        self._history.begin_macro(text)
        try:
            for obj in applicable:
                self._history.push(
                    ModifyObjectCommand(
                        self._document, self._page_index, obj.id, changes, text=text
                    )
                )
        finally:
            self._history.end_macro()

    def _apply_geometry(self) -> None:
        if self._blocker or self._history is None or self._document is None:
            return
        if len(self._objects) != 1:
            return
        obj = self._objects[0]
        width = max(self._width.value(), 1.0)
        height = max(self._height.value(), 1.0)

        if isinstance(obj, ImageObject) and obj.keep_aspect:
            if abs(width - obj.rect.width) > 1e-6:
                height = obj.size_for_aspect(width=width).height
            elif abs(height - obj.rect.height) > 1e-6:
                width = obj.size_for_aspect(height=height).width

        rect = Rect.from_xywh(self._x.value(), self._y.value(), width, height)
        rotation = self._rotation.value() % 360.0
        if rect == obj.rect and abs(rotation - obj.rotation) < 1e-9:
            return

        self._history.push(
            TransformObjectsCommand(
                self._document,
                self._page_index,
                {obj.id: (obj.rect, obj.rotation)},
                {obj.id: (rect, rotation)},
                text="Change Geometry",
            )
        )

    def _commit_text(self) -> None:
        if self._blocker or len(self._objects) != 1:
            return
        obj = self._objects[0]
        if not isinstance(obj, TextObject):
            return
        new_text = self._text_edit.toPlainText()
        if new_text != obj.text:
            self._apply({"text": new_text}, "Edit Text", mergeable=False)

    def _commit_contents(self) -> None:
        if self._blocker or len(self._objects) != 1:
            return
        obj = self._objects[0]
        if not isinstance(obj, AnnotationObject):
            return
        new_text = self._contents.toPlainText()
        if new_text != obj.contents:
            self._apply({"contents": new_text}, "Edit Comment", mergeable=False)

    def _reset_image_size(self) -> None:
        if len(self._objects) != 1 or self._history is None or self._document is None:
            return
        obj = self._objects[0]
        if not isinstance(obj, ImageObject):
            return
        natural = obj.natural_size
        rect = Rect.from_xywh(obj.rect.x0, obj.rect.y0, natural.width, natural.height)
        self._history.push(
            TransformObjectsCommand(
                self._document,
                self._page_index,
                {obj.id: (obj.rect, obj.rotation)},
                {obj.id: (rect, obj.rotation)},
                text="Reset Image Size",
            )
        )
