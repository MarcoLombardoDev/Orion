# Orion — PDF Editor for Desktop
# Copyright (C) 2026 Marco Lombardo
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# Distributed WITHOUT ANY WARRANTY; see LICENSE for the full terms.
# A commercial licence, without the AGPL's obligations, is available for use
# in proprietary or closed-source products — see COMMERCIAL-LICENSE.md.

"""In-place text editing on the canvas (spec §9).

Double-clicking a text object turns it into a real ``QGraphicsTextItem`` with a
caret, so editing feels like editing text and not like filling in a form.  On
commit the new string goes through the normal command history.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QFont, QKeyEvent, QTextOption
from PySide6.QtWidgets import QGraphicsItem, QGraphicsTextItem

from orion.commands.object_commands import ModifyObjectCommand

if TYPE_CHECKING:  # pragma: no cover - typing only
    from orion.ui.object_items import TextObjectItem

__all__ = ["InlineTextEditor"]

_ALIGNMENT = {
    "left": Qt.AlignmentFlag.AlignLeft,
    "center": Qt.AlignmentFlag.AlignHCenter,
    "right": Qt.AlignmentFlag.AlignRight,
    "justify": Qt.AlignmentFlag.AlignJustify,
}


class _EditorItem(QGraphicsTextItem):
    """The editable text item; forwards Escape and Ctrl+Return to the editor."""

    def __init__(self, editor: InlineTextEditor, parent: QGraphicsItem) -> None:
        super().__init__(parent)
        self._editor = editor

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 - Qt naming
        key = event.key()
        if key == Qt.Key.Key_Escape:
            event.accept()
            self._editor.owner.end_editing(commit=False)
            return
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and event.modifiers() & (
            Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier
        ):
            event.accept()
            self._editor.owner.end_editing(commit=True)
            return
        super().keyPressEvent(event)

    def focusOutEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().focusOutEvent(event)
        # Clicking elsewhere commits, which is what every editor does.
        self._editor.owner.end_editing(commit=True)


class InlineTextEditor:
    """Owns the temporary editing item for one :class:`TextObjectItem`."""

    def __init__(self, owner: TextObjectItem) -> None:
        self.owner = owner
        obj = owner.text_object
        self._original = obj.text

        item = _EditorItem(self, owner)
        item.setPos(QPointF(0.0, 0.0))
        item.setTextWidth(max(owner.local_rect().width(), 10.0))
        item.setDefaultTextColor(QColor.fromRgbF(*obj.color))
        item.setFont(self._font(owner))
        item.setPlainText(obj.text)

        option = item.document().defaultTextOption()
        option.setAlignment(_ALIGNMENT.get(obj.align.value, Qt.AlignmentFlag.AlignLeft))
        option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        item.document().setDefaultTextOption(option)

        item.setTextInteractionFlags(Qt.TextInteractionFlag.TextEditorInteraction)
        item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsFocusable, True)
        item.setFocus(Qt.FocusReason.MouseFocusReason)
        cursor = item.textCursor()
        cursor.select(cursor.SelectionType.Document)
        item.setTextCursor(cursor)

        self._item = item
        owner.update()

    @staticmethod
    def _font(owner: TextObjectItem) -> QFont:
        """The same font the item paints with, so nothing shifts on edit.

        A ``QGraphicsTextItem`` sizes its font against the paint device just
        as ``QPainter`` does, so it needs the same conversion from points to
        scene units. Assuming it resolved against 72 dpi is what made the text
        grow by a third the instant the caret appeared, on every screen
        reporting the usual 96.
        """
        from orion.ui.object_items import scene_font

        obj = owner.text_object
        viewport = owner._canvas.viewport()
        dpi = float(viewport.logicalDpiY()) if viewport is not None else 72.0
        font = scene_font(obj, dpi)
        font.setUnderline(obj.underline)
        return font

    def finish(self, *, commit: bool) -> None:
        text = self._item.toPlainText()
        scene = self._item.scene()
        if scene is not None:
            scene.removeItem(self._item)
        self._item.setParentItem(None)

        if not commit or text == self._original:
            self.owner.text_object.text = self._original
            self.owner.update()
            return

        canvas = self.owner._canvas
        # Restore the original first: the command records the change itself.
        self.owner.text_object.text = self._original
        canvas.history.push(
            ModifyObjectCommand(
                canvas.document,
                self.owner.page_index,
                self.owner.object.id,
                {"text": text},
                text="Edit Text",
                mergeable=False,
            )
        )
        self.owner.sync_from_model()
