# Orion — PDF Editor for Desktop
# Copyright (C) 2026 Marco Lombardo
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# Distributed WITHOUT ANY WARRANTY; see LICENSE for the full terms.
# A commercial licence, without the AGPL's obligations, is available for use
# in proprietary or closed-source products — see COMMERCIAL-LICENSE.md.

"""Centralised undo/redo history (spec §15)."""

from __future__ import annotations

import logging

from orion.commands.base import Command, MacroCommand
from orion.utils.events import Event

log = logging.getLogger(__name__)

__all__ = ["History", "DEFAULT_HISTORY_LIMIT"]

DEFAULT_HISTORY_LIMIT = 200


class History:
    """Two stacks plus a *clean marker* that derives the "modified" state.

    The clean marker is what makes "Save, then undo back to where you saved"
    correctly report the document as unmodified again, without comparing
    documents.
    """

    def __init__(self, limit: int = DEFAULT_HISTORY_LIMIT) -> None:
        self._undo: list[Command] = []
        self._redo: list[Command] = []
        self._limit = max(1, limit)
        self._clean_depth = 0
        self._clean_valid = True
        self._macro: list[Command] | None = None
        self._macro_text = ""

        self.changed = Event("history_changed")
        self.clean_changed = Event("history_clean_changed")

    # -- state -----------------------------------------------------------
    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    @property
    def undo_text(self) -> str:
        return self._undo[-1].text if self._undo else ""

    @property
    def redo_text(self) -> str:
        return self._redo[-1].text if self._redo else ""

    @property
    def is_clean(self) -> bool:
        return self._clean_valid and len(self._undo) == self._clean_depth

    @property
    def depth(self) -> int:
        return len(self._undo)

    def mark_clean(self) -> None:
        """Called after a successful save."""
        was_clean = self.is_clean
        self._clean_depth = len(self._undo)
        self._clean_valid = True
        if not was_clean:
            self.clean_changed.emit(True)

    def clear(self) -> None:
        self._undo.clear()
        self._redo.clear()
        self._clean_depth = 0
        self._clean_valid = True
        self._macro = None
        self.changed.emit(self)
        self.clean_changed.emit(True)

    # -- macros ----------------------------------------------------------
    def begin_macro(self, text: str) -> None:
        """Group everything pushed until :meth:`end_macro` into one undo step."""
        if self._macro is not None:
            raise RuntimeError("A macro is already open")
        self._macro = []
        self._macro_text = text

    def end_macro(self) -> Command | None:
        if self._macro is None:
            return None
        commands, text = self._macro, self._macro_text
        self._macro = None
        if not commands:
            return None
        command = commands[0] if len(commands) == 1 else MacroCommand(commands, text)
        if len(commands) > 1:
            command.text = text
        self._push(command)
        return command

    def abort_macro(self) -> None:
        if self._macro is None:
            return
        for command in reversed(self._macro):
            try:
                command.undo()
            except Exception:  # pragma: no cover - defensive
                log.exception("Failed to roll back an aborted macro")
        self._macro = None

    # -- pushing ---------------------------------------------------------
    def push(self, command: Command, *, execute: bool = True) -> Command:
        """Run *command* (unless already applied) and record it."""
        if execute:
            command.execute()
        if self._macro is not None:
            self._macro.append(command)
            return command
        self._push(command)
        return command

    def _push(self, command: Command) -> None:
        if self._undo and self._undo[-1].merge_with(command):
            self._redo.clear()
            self._invalidate_clean_if_needed()
            self.changed.emit(self)
            return

        was_clean = self.is_clean
        self._redo.clear()
        self._undo.append(command)
        if len(self._undo) > self._limit:
            dropped = len(self._undo) - self._limit
            del self._undo[:dropped]
            self._clean_depth -= dropped
            if self._clean_depth < 0:
                # The save point fell off the end of the history; we can no
                # longer prove the document is unmodified.
                self._clean_valid = False
                self._clean_depth = 0
        if was_clean:
            self.clean_changed.emit(False)
        self.changed.emit(self)

    def _invalidate_clean_if_needed(self) -> None:
        if self.is_clean:
            self._clean_valid = False
            self.clean_changed.emit(False)

    # -- undo / redo -----------------------------------------------------
    def undo(self) -> Command | None:
        if not self._undo:
            return None
        was_clean = self.is_clean
        command = self._undo.pop()
        try:
            command.undo()
        except Exception:
            self._undo.append(command)
            log.exception("Undo failed for %r", command)
            raise
        self._redo.append(command)
        self._emit_after_move(was_clean)
        return command

    def redo(self) -> Command | None:
        if not self._redo:
            return None
        was_clean = self.is_clean
        command = self._redo.pop()
        try:
            command.redo()
        except Exception:
            self._redo.append(command)
            log.exception("Redo failed for %r", command)
            raise
        self._undo.append(command)
        self._emit_after_move(was_clean)
        return command

    def _emit_after_move(self, was_clean: bool) -> None:
        if self.is_clean != was_clean:
            self.clean_changed.emit(self.is_clean)
        self.changed.emit(self)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<History undo={len(self._undo)} redo={len(self._redo)} clean={self.is_clean}>"
