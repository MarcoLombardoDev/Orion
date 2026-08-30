# Orion — PDF Editor for Desktop
# Copyright (C) 2026 Marco Lombardo
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# Distributed WITHOUT ANY WARRANTY; see LICENSE for the full terms.
# A commercial licence, without the AGPL's obligations, is available for use
# in proprietary or closed-source products — see COMMERCIAL-LICENSE.md.

"""A single registry of every command in the application (spec §22, §31).

The menu bar, the toolbar, context menus and the keyboard shortcuts all read
from the same declarative table, so a shortcut can never disagree with the menu
that shows it and no action is defined twice.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QWidget

from orion.ui.icons import icon
from orion.ui.tools import TOOL_INFO, Tool

__all__ = ["ActionSpec", "ActionRegistry", "ACTIONS", "TOOL_ACTIONS"]


@dataclass(frozen=True, slots=True)
class ActionSpec:
    key: str
    text: str
    icon: str = ""
    shortcut: str = ""
    tip: str = ""
    checkable: bool = False
    #: Shown in the menu but greyed out until a document is open.
    needs_document: bool = True
    #: Scope the shortcut to the canvas.  Without this, Delete would delete an
    #: object while the user is editing text in the find bar, and Ctrl+A would
    #: select objects instead of the text in whatever field has focus.
    canvas_scoped: bool = False


def _standard(name: str) -> str:
    """Platform-correct shortcut string for a Qt standard key."""
    sequence = QKeySequence(getattr(QKeySequence.StandardKey, name))
    return sequence.toString(QKeySequence.SequenceFormat.PortableText)


#: Every non-tool action, grouped the way the menus present them.
ACTIONS: tuple[ActionSpec, ...] = (
    # -- File ------------------------------------------------------------
    ActionSpec("file.new", "&New Document", "new", "Ctrl+N", "Create an empty document", needs_document=False),
    ActionSpec("file.open", "&Open…", "open", "Ctrl+O", "Open a PDF document", needs_document=False),
    ActionSpec("file.close", "&Close Document", "close", "Ctrl+W", "Close the current document"),
    ActionSpec("file.save", "&Save", "save", "Ctrl+S", "Save the document"),
    ActionSpec("file.save_as", "Save &As…", "save_as", "Ctrl+Shift+S", "Save the document under a new name"),
    ActionSpec("file.merge", "&Merge PDF…", "merge", "", "Combine several PDF files into one", needs_document=False),
    ActionSpec("file.clear_recent", "Clear Recent Files", "", "", "Forget the list of recently opened files", needs_document=False),
    ActionSpec("file.quit", "&Quit", "", "Ctrl+Q", "Close Orion", needs_document=False),
    # -- Edit ------------------------------------------------------------
    ActionSpec("edit.undo", "&Undo", "undo", "Ctrl+Z", "Undo the last change"),
    ActionSpec("edit.redo", "&Redo", "redo", "Ctrl+Y", "Redo the last undone change"),
    ActionSpec("edit.cut", "Cu&t", "cut", "Ctrl+X", "Cut the selected objects"),
    ActionSpec("edit.copy", "&Copy", "copy", "Ctrl+C", "Copy the selected objects"),
    ActionSpec("edit.paste", "&Paste", "paste", "Ctrl+V", "Paste objects onto the current page"),
    ActionSpec("edit.duplicate", "&Duplicate", "duplicate", "Ctrl+D", "Duplicate the selected objects"),
    ActionSpec("edit.delete", "Delete", "delete", "Del", "Delete the selected objects", canvas_scoped=True),
    ActionSpec("edit.select_all", "Select &All on Page", "", "Ctrl+A", "Select every object on this page", canvas_scoped=True),
    ActionSpec("edit.deselect", "Deselect", "", "Esc", "Clear the selection", canvas_scoped=True),
    ActionSpec("edit.bring_front", "Bring to &Front", "bring_front", "Ctrl+Shift+]", "Move the object above the others"),
    ActionSpec("edit.send_back", "Send to &Back", "send_back", "Ctrl+Shift+[", "Move the object below the others"),
    # -- View ------------------------------------------------------------
    ActionSpec("view.zoom_in", "Zoom &In", "zoom_in", "Ctrl++", "Zoom in"),
    ActionSpec("view.zoom_out", "Zoom &Out", "zoom_out", "Ctrl+-", "Zoom out"),
    ActionSpec("view.zoom_reset", "Actual Size", "", "Ctrl+0", "Show the page at 100%"),
    ActionSpec("view.fit_page", "Fit &Page", "fit_page", "Ctrl+1", "Fit the whole page in the window", checkable=True),
    ActionSpec("view.fit_width", "Fit &Width", "fit_width", "Ctrl+2", "Fit the page width to the window", checkable=True),
    ActionSpec("view.first_page", "&First Page", "first_page", "Ctrl+Home", "Go to the first page"),
    ActionSpec("view.previous_page", "&Previous Page", "prev_page", "PgUp", "Go to the previous page"),
    ActionSpec("view.next_page", "&Next Page", "next_page", "PgDown", "Go to the next page"),
    ActionSpec("view.last_page", "&Last Page", "last_page", "Ctrl+End", "Go to the last page"),
    ActionSpec("view.go_to_page", "&Go to Page…", "", "Ctrl+G", "Jump to a page number"),
    ActionSpec("view.search", "&Find…", "search", "Ctrl+F", "Search for text"),
    ActionSpec("view.find_next", "Find Next", "", "F3", "Go to the next match"),
    ActionSpec("view.find_previous", "Find Previous", "", "Shift+F3", "Go to the previous match"),
    ActionSpec("view.thumbnails", "&Thumbnails", "sidebar", "F9", "Show or hide the page thumbnails", checkable=True, needs_document=False),
    ActionSpec("view.properties", "&Properties Panel", "properties", "F10", "Show or hide the properties panel", checkable=True, needs_document=False),
    ActionSpec("view.theme_light", "&Light Theme", "", "", "Use the light theme", checkable=True, needs_document=False),
    ActionSpec("view.theme_dark", "&Dark Theme", "", "", "Use the dark theme", checkable=True, needs_document=False),
    ActionSpec("view.theme_system", "Match &System", "", "", "Follow the desktop's light or dark setting", checkable=True, needs_document=False),
    # -- Pages -----------------------------------------------------------
    ActionSpec("pages.insert", "&Insert Blank Page…", "page_add", "", "Add an empty page"),
    ActionSpec("pages.duplicate", "&Duplicate Page", "duplicate", "", "Duplicate the current page"),
    ActionSpec("pages.delete", "De&lete Page", "page_delete", "", "Delete the selected pages"),
    ActionSpec("pages.rotate_left", "Rotate &Left", "rotate_left", "Ctrl+[", "Rotate the selected pages 90° left"),
    ActionSpec("pages.rotate_right", "Rotate &Right", "rotate_right", "Ctrl+]", "Rotate the selected pages 90° right"),
    ActionSpec("pages.rotate_180", "Rotate 180°", "", "", "Turn the selected pages upside down"),
    ActionSpec("pages.move_up", "Move Page &Up", "", "Ctrl+Shift+Up", "Move the current page earlier"),
    ActionSpec("pages.move_down", "Move Page D&own", "", "Ctrl+Shift+Down", "Move the current page later"),
    ActionSpec("pages.import", "I&mport Pages…", "import", "", "Insert pages from another PDF"),
    ActionSpec("pages.extract", "&Extract Pages…", "extract", "", "Save selected pages as a new PDF"),
    ActionSpec("pages.split", "&Split PDF…", "split", "", "Split this document into several files"),
    # -- Tools -----------------------------------------------------------
    ActionSpec("tools.insert_image", "Insert &Image…", "image", "Ctrl+Shift+I", "Place an image on the page"),
    ActionSpec("tools.edit_text", "&Edit Text Object", "text", "F2", "Edit the selected text object"),
    ActionSpec("tools.edit_note", "Edit &Comment…", "comment", "", "Edit the selected annotation's comment"),
    # -- Help ------------------------------------------------------------
    ActionSpec("help.shortcuts", "&Keyboard Shortcuts", "", "", "List the keyboard shortcuts", needs_document=False),
    ActionSpec("help.log", "Open &Log Folder", "", "", "Open the folder containing Orion's log file", needs_document=False),
    ActionSpec("help.about", "&About Orion", "info", "", "About this application", needs_document=False),
)

#: Actions generated from the tool table, so a new tool needs no boilerplate.
TOOL_ACTIONS: tuple[ActionSpec, ...] = tuple(
    ActionSpec(
        key=f"tool.{tool.value}",
        text=info.label,
        icon=info.icon,
        shortcut=info.shortcut,
        tip=info.hint,
        checkable=True,
    )
    for tool, info in TOOL_INFO.items()
)


class ActionRegistry:
    """Creates and owns every :class:`QAction`."""

    def __init__(self, parent: QWidget) -> None:
        self._parent = parent
        self._actions: dict[str, QAction] = {}
        self._specs: dict[str, ActionSpec] = {}
        for spec in ACTIONS + TOOL_ACTIONS:
            self._create(spec)

        # Redo has a second, platform-conventional shortcut.
        self["edit.redo"].setShortcuts(
            [QKeySequence("Ctrl+Y"), QKeySequence("Ctrl+Shift+Z")]
        )

    def _create(self, spec: ActionSpec) -> QAction:
        action = QAction(spec.text, self._parent)
        if spec.icon:
            action.setIcon(icon(spec.icon))
        if spec.shortcut:
            action.setShortcut(QKeySequence(spec.shortcut))
        if spec.tip:
            action.setToolTip(spec.tip)
            action.setStatusTip(spec.tip)
        action.setCheckable(spec.checkable)
        action.setData(spec.key)
        self._actions[spec.key] = action
        self._specs[spec.key] = spec
        return action

    # -- access ------------------------------------------------------------
    def __getitem__(self, key: str) -> QAction:
        return self._actions[key]

    def get(self, key: str) -> QAction | None:
        return self._actions.get(key)

    def spec(self, key: str) -> ActionSpec:
        return self._specs[key]

    def keys(self) -> Iterable[str]:
        return self._actions.keys()

    def connect(self, key: str, slot: Callable[..., None]) -> None:
        self._actions[key].triggered.connect(slot)

    def tool_action(self, tool: Tool) -> QAction:
        return self._actions[f"tool.{tool.value}"]

    def bind_canvas_shortcuts(self, canvas: QWidget) -> None:
        """Re-scope the canvas-only shortcuts so other widgets keep their keys.

        The actions stay on the window (so the menus still show and trigger
        them), but their *shortcuts* only fire when the canvas has focus.
        """
        from PySide6.QtCore import Qt

        for key, spec in self._specs.items():
            if not spec.canvas_scoped:
                continue
            action = self._actions[key]
            action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            canvas.addAction(action)

    def refresh_icons(self) -> None:
        """Re-tint every icon after a theme change."""
        for key, action in self._actions.items():
            name = self._specs[key].icon
            if name:
                action.setIcon(icon(name))

    def set_document_open(self, is_open: bool) -> None:
        """Grey out everything that needs a document."""
        for key, action in self._actions.items():
            if self._specs[key].needs_document:
                action.setEnabled(is_open)

    def shortcut_table(self) -> list[tuple[str, str]]:
        """(description, shortcut) pairs, for the Help dialog."""
        rows: list[tuple[str, str]] = []
        for key, action in self._actions.items():
            sequence = action.shortcut().toString(QKeySequence.SequenceFormat.NativeText)
            if sequence:
                rows.append((self._specs[key].text.replace("&", ""), sequence))
        rows.sort(key=lambda row: row[0])
        return rows
