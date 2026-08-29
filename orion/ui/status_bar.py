# Orion — PDF Editor for Desktop
# Copyright (C) 2026 Marco Lombardo
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# Distributed WITHOUT ANY WARRANTY; see LICENSE for the full terms.
# A commercial licence, without the AGPL's obligations, is available for use
# in proprietary or closed-source products — see COMMERCIAL-LICENSE.md.

"""The status bar: page position, zoom, fit mode and transient messages."""

from __future__ import annotations

from urllib.parse import quote

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QLabel, QStatusBar, QWidget

from orion import CONTACT_EMAIL, LICENSE_NOTICE, LICENSING_SUBJECT

__all__ = ["OrionStatusBar"]


class OrionStatusBar(QStatusBar):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setSizeGripEnabled(True)

        self._page = QLabel()
        self._zoom = QLabel()
        self._mode = QLabel()
        self._modified = QLabel()

        for label in (self._page, self._zoom, self._mode, self._modified):
            label.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        self.addWidget(self._licence_notice())
        self.addPermanentWidget(self._modified)
        self.addPermanentWidget(self._page)
        self.addPermanentWidget(self._zoom)
        self.addPermanentWidget(self._mode)
        self.clear_document()

    def _licence_notice(self) -> QLabel:
        """The copyright and licence line, with the address spelled out.

        AGPL-3.0 section 5 asks the work to carry Appropriate Legal Notices,
        and Iris, Proteus and Argus have all shown this line since their first
        release. Orion shipped v1.0.0 without one.

        The address is a link rather than plain text because the person
        running the application is exactly the person who might need to buy a
        commercial licence, and "available on request" tells them nothing
        about where to ask.

        Added with ``addWidget`` rather than ``addPermanentWidget`` so it sits
        on the left, where a credit belongs, rather than among the page and
        zoom indicators. Qt hides normal status-bar widgets while a transient
        message is showing, which is the accepted cost of that placement: the
        notice is on screen the rest of the time, and the messages last four
        seconds.
        """
        label = QLabel(
            f'{LICENSE_NOTICE} <a href="mailto:{CONTACT_EMAIL}'
            f'?subject={quote(LICENSING_SUBJECT)}">{CONTACT_EMAIL}</a>'
        )
        label.setTextFormat(Qt.TextFormat.RichText)
        label.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        # Opened through QDesktopServices rather than setOpenExternalLinks, so
        # a machine with no mail client configured fails quietly instead of
        # raising: the address stays readable on screen either way.
        label.linkActivated.connect(
            lambda url: QDesktopServices.openUrl(QUrl(url))
        )
        label.setStyleSheet("color: palette(mid); font-size: 10px;")
        return label

    def set_page(self, index: int, total: int) -> None:
        self._page.setText(f"Page {index + 1} / {total}" if total else "")

    def set_zoom(self, zoom: float, mode: str) -> None:
        self._zoom.setText(f"Zoom {round(zoom * 100)}%")
        self._mode.setText(
            {"fit_width": "Fit Width", "fit_page": "Fit Page"}.get(mode, "Custom Zoom")
        )

    def set_modified(self, modified: bool) -> None:
        self._modified.setText("Modified" if modified else "")

    def clear_document(self) -> None:
        self._page.clear()
        self._zoom.clear()
        self._mode.clear()
        self._modified.clear()

    def flash(self, message: str, milliseconds: int = 4000) -> None:
        self.showMessage(message, milliseconds)
