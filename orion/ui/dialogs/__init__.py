"""Dialogs for the operations that need more than a single click."""

from orion.ui.dialogs.about_dialog import AboutDialog
from orion.ui.dialogs.merge_dialog import MergeDialog
from orion.ui.dialogs.page_dialogs import (
    GoToPageDialog,
    ImportPagesDialog,
    InsertPageDialog,
    NoteDialog,
    PageSelectionDialog,
)
from orion.ui.dialogs.recovery_dialog import RecoveryDialog
from orion.ui.dialogs.split_dialog import SplitDialog

__all__ = [
    "AboutDialog",
    "GoToPageDialog",
    "ImportPagesDialog",
    "InsertPageDialog",
    "MergeDialog",
    "NoteDialog",
    "PageSelectionDialog",
    "RecoveryDialog",
    "SplitDialog",
]
