# Orion — PDF Editor for Desktop
# Copyright (C) 2026 Marco Lombardo
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# Distributed WITHOUT ANY WARRANTY; see LICENSE for the full terms.
# A commercial licence, without the AGPL's obligations, is available for use
# in proprietary or closed-source products — see COMMERCIAL-LICENSE.md.

"""Reading and editing what a document says about itself.

Orion has always carried the metadata across a save without showing it, which
means a file could go out with the previous author's name on it and nothing in
the interface would ever have said so. This is where that becomes visible and
changeable.

The four fields with their own rows are the ones a reader's Properties window
shows. Everything else the file happens to carry is listed below them, so it
is at least visible, and kept on save rather than quietly dropped.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QWidget,
)

from orion.i18n import tr

__all__ = ["DocumentPropertiesDialog", "EDITABLE_FIELDS"]

#: ``(PDF key, label)`` for the fields a reader shows, in that order.
EDITABLE_FIELDS: tuple[tuple[str, str], ...] = (
    ("/Title", tr("Title")),
    ("/Author", tr("Author")),
    ("/Subject", tr("Subject")),
    ("/Keywords", tr("Keywords")),
)

#: Keys a viewer writes about itself. Shown, never presented as the user's.
_PRODUCED_BY = ("/Producer", "/Creator")


class DocumentPropertiesDialog(QDialog):
    """Title, author, subject and keywords, plus whatever else is in there."""

    def __init__(self, metadata: dict[str, str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Document Properties"))
        self._original = dict(metadata)
        form = QFormLayout(self)

        self._fields: dict[str, QLineEdit] = {}
        for key, label in EDITABLE_FIELDS:
            field = QLineEdit(metadata.get(key, ""))
            form.addRow(label, field)
            self._fields[key] = field

        extra = {
            key: value
            for key, value in metadata.items()
            if key not in dict(EDITABLE_FIELDS) and value
        }
        for key in _PRODUCED_BY:
            if key in extra:
                label = QLabel(extra.pop(key))
                label.setWordWrap(True)
                form.addRow(key.lstrip("/"), label)
        if extra:
            rest = QLabel(", ".join(f"{k.lstrip('/')}: {v}" for k, v in sorted(extra.items())))
            rest.setWordWrap(True)
            form.addRow(tr("Also in the file"), rest)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    @property
    def metadata(self) -> dict[str, str]:
        """The whole set, edits applied and everything else left as it was.

        An emptied field removes the entry rather than writing an empty
        string: a reader shows "Title: " for one and nothing for the other,
        and clearing a field means the second.
        """
        result = dict(self._original)
        for key, field in self._fields.items():
            text = field.text().strip()
            if text:
                result[key] = text
            else:
                result.pop(key, None)
        return result

    @property
    def changed(self) -> bool:
        return self.metadata != self._original
