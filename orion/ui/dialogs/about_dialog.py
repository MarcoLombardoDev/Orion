# Orion — PDF Editor for Desktop
# Copyright (C) 2026 Marco Lombardo
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# Distributed WITHOUT ANY WARRANTY; see LICENSE for the full terms.
# A commercial licence, without the AGPL's obligations, is available for use
# in proprietary or closed-source products — see COMMERCIAL-LICENSE.md.

"""About Orion (spec §1, §34)."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QVBoxLayout, QWidget

from orion import APP_NAME, APP_SUBTITLE, __version__

__all__ = ["AboutDialog"]


class AboutDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"About {APP_NAME}")
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        title = QLabel(APP_NAME)
        title.setStyleSheet("font-size: 26px; font-weight: 700;")
        layout.addWidget(title)

        subtitle = QLabel(APP_SUBTITLE)
        subtitle.setProperty("role", "hint")
        layout.addWidget(subtitle)

        versions = QLabel(
            f"Version {__version__}\n"
            f"Python {sys.version.split()[0]} · {_qt_version()} · {_engine_version()}"
        )
        versions.setProperty("role", "hint")
        layout.addWidget(versions)

        licence = QLabel(
            "Orion is free software released under the GNU Affero General Public "
            "License, version 3 or later.\n\n"
            "It works entirely offline: no account, no server, no telemetry."
        )
        licence.setWordWrap(True)
        layout.addWidget(licence)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)


def _qt_version() -> str:
    try:
        from PySide6.QtCore import qVersion

        return f"Qt {qVersion()}"
    except Exception:  # pragma: no cover - defensive
        return "Qt"


def _engine_version() -> str:
    """The PDF engine, named in the About box because bug reports need it.

    Two libraries share the work, and a rendering complaint and a saving
    complaint point at different ones, so both versions are shown.
    """
    parts = []
    try:
        import pypdfium2

        parts.append(f"pdfium {pypdfium2.PDFIUM_INFO.version}")
    except Exception:  # pragma: no cover - defensive
        parts.append("pdfium (unknown)")
    try:
        import pypdf

        parts.append(f"pypdf {pypdf.__version__}")
    except Exception:  # pragma: no cover - defensive
        parts.append("pypdf (unknown)")
    return " · ".join(parts)
