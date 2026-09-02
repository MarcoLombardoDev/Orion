# Orion — PDF Editor for Desktop
# Copyright (C) 2026 Marco Lombardo
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# Distributed WITHOUT ANY WARRANTY; see LICENSE for the full terms.
# A commercial licence, without the AGPL's obligations, is available for use
# in proprietary or closed-source products — see COMMERCIAL-LICENSE.md.

"""The menu bar (spec §7).

Structure only: every entry resolves to an action from
:class:`~orion.ui.actions.ActionRegistry`, so behaviour and shortcuts live in
one place and this module stays a layout description.
"""

from __future__ import annotations

from PySide6.QtWidgets import QMenu, QMenuBar, QWidget

from orion.i18n import tr
from orion.ui.actions import ActionRegistry
from orion.ui.tools import Tool

__all__ = ["build_menu_bar", "MenuBundle"]

SEPARATOR = None

#: (menu title, [action keys or None for a separator])
_STRUCTURE: tuple[tuple[str, tuple[str | None, ...]], ...] = (
    (
        "&File",
        (
            "file.new",
            "file.open",
            "@recent",
            SEPARATOR,
            "file.save",
            "file.save_as",
            SEPARATOR,
            "file.merge",
            "file.export_images",
            SEPARATOR,
            "file.properties",
            SEPARATOR,
            "file.close",
            "file.quit",
        ),
    ),
    (
        "&Edit",
        (
            "edit.undo",
            "edit.redo",
            SEPARATOR,
            "edit.cut",
            "edit.copy",
            "edit.paste",
            "edit.duplicate",
            "edit.delete",
            SEPARATOR,
            "edit.select_all",
            "edit.deselect",
            SEPARATOR,
            "edit.bring_front",
            "edit.send_back",
        ),
    ),
    (
        "&View",
        (
            "view.zoom_in",
            "view.zoom_out",
            "view.zoom_reset",
            "view.fit_page",
            "view.fit_width",
            SEPARATOR,
            "view.first_page",
            "view.previous_page",
            "view.next_page",
            "view.last_page",
            "view.go_to_page",
            SEPARATOR,
            "view.search",
            "view.find_next",
            "view.find_previous",
            SEPARATOR,
            "view.thumbnails",
            "view.properties",
        ),
    ),
    (
        "&Pages",
        (
            "pages.insert",
            "pages.duplicate",
            "pages.delete",
            SEPARATOR,
            "pages.rotate_left",
            "pages.rotate_right",
            "pages.rotate_180",
            SEPARATOR,
            "pages.move_up",
            "pages.move_down",
            SEPARATOR,
            "pages.import",
            "pages.extract",
            "pages.split",
        ),
    ),
    (
        "&Tools",
        (
            # Whatever the palette holds, in the palette's own order, built
            # from one list so the two cannot drift apart. Everything below
            # the separator is in the palette too, as a button that opens a
            # dialog rather than one that arms a click.
            "@tools",
            SEPARATOR,
            "tools.watermark",
            "tools.page_numbers",
        ),
    ),
    (
        "&Help",
        (
            "view.commands",
            SEPARATOR,
            "@language",
            "@theme",
            SEPARATOR,
            "help.shortcuts",
            "help.log",
            SEPARATOR,
            "help.about",
        ),
    ),
)


class MenuBundle:
    """The menus that need to be updated at runtime."""

    def __init__(self) -> None:
        self.recent: QMenu | None = None
        self.theme: QMenu | None = None
        self.language: QMenu | None = None


def build_menu_bar(parent: QWidget, actions: ActionRegistry) -> tuple[QMenuBar, MenuBundle]:
    bar = QMenuBar(parent)
    bundle = MenuBundle()

    for title, entries in _STRUCTURE:
        menu = bar.addMenu(tr(title))
        for entry in entries:
            if entry is SEPARATOR:
                menu.addSeparator()
            elif entry == "@recent":
                bundle.recent = menu.addMenu(tr("Open &Recent"))
            elif entry == "@theme":
                bundle.theme = _build_theme_menu(menu, actions)
            elif entry == "@language":
                bundle.language = _build_language_menu(menu, actions)
            elif entry == "@tools":
                _add_tool_entries(menu, actions)
            else:
                action = actions.get(entry)
                if action is not None:
                    menu.addAction(action)
    return bar, bundle


def _build_theme_menu(menu: QMenu, actions: ActionRegistry) -> QMenu:
    submenu = menu.addMenu(tr("&Theme"))
    for key in ("view.theme_system", "view.theme_light", "view.theme_dark"):
        submenu.addAction(actions[key])
    return submenu


def _build_language_menu(menu: QMenu, actions: ActionRegistry) -> QMenu:
    submenu = menu.addMenu(tr("&Language"))
    for key in ("view.language_en", "view.language_it"):
        submenu.addAction(actions[key])
    return submenu


def _add_tool_entries(menu: QMenu, actions: ActionRegistry) -> None:
    groups: tuple[tuple[Tool, ...], ...] = (
        (Tool.SELECT, Tool.HAND),
        (Tool.TEXT, Tool.IMAGE),
        (Tool.RECTANGLE, Tool.ELLIPSE, Tool.LINE, Tool.ARROW),
        (Tool.HIGHLIGHT, Tool.UNDERLINE, Tool.STRIKEOUT, Tool.REDACT),
        (Tool.FREEHAND, Tool.STICKY_NOTE),
    )
    for index, group in enumerate(groups):
        if index:
            menu.addSeparator()
        for tool in group:
            menu.addAction(actions.tool_action(tool))
