# Orion — PDF Editor for Desktop
# Copyright (C) 2026 Marco Lombardo
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# Distributed WITHOUT ANY WARRANTY; see LICENSE for the full terms.
# A commercial licence, without the AGPL's obligations, is available for use
# in proprietary or closed-source products — see COMMERCIAL-LICENSE.md.

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
