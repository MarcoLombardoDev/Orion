"""Undo/redo built on a real Command pattern (spec §15).

No whole-document snapshots: every command stores only the delta it needs to
reverse itself, so history is cheap even for a 500-page document.
"""

from orion.commands.base import Command, MacroCommand, NullCommand
from orion.commands.history import History
from orion.commands.object_commands import (
    AddObjectCommand,
    DeleteObjectsCommand,
    ModifyObjectCommand,
    MoveObjectsCommand,
    PasteObjectsCommand,
    RaiseObjectCommand,
    ReorderObjectCommand,
    TransformObjectsCommand,
)
from orion.commands.page_commands import (
    DeletePagesCommand,
    DuplicatePageCommand,
    ImportPagesCommand,
    InsertPageCommand,
    MovePageCommand,
    RotatePagesCommand,
)

__all__ = [
    "AddObjectCommand",
    "Command",
    "DeleteObjectsCommand",
    "DeletePagesCommand",
    "DuplicatePageCommand",
    "History",
    "ImportPagesCommand",
    "InsertPageCommand",
    "MacroCommand",
    "ModifyObjectCommand",
    "MoveObjectsCommand",
    "MovePageCommand",
    "NullCommand",
    "PasteObjectsCommand",
    "RaiseObjectCommand",
    "ReorderObjectCommand",
    "RotatePagesCommand",
    "TransformObjectsCommand",
]
