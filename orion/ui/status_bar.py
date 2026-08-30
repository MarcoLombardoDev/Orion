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

#: Breathing room kept between the notice and the edges it must not touch:
#: the left of the bar, and the leftmost indicator.
MARGIN = 8

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

        self.addPermanentWidget(self._modified)
        self.addPermanentWidget(self._page)
        self.addPermanentWidget(self._zoom)
        self.addPermanentWidget(self._mode)

        # Not added to the layout at all: see _place_notice.
        self._notice = self._licence_notice()
        self.messageChanged.connect(lambda _text: self._place_notice())

        self.clear_document()

    # -- the licence notice ------------------------------------------------

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt's spelling
        super().resizeEvent(event)
        self._place_notice()

    def _place_notice(self) -> None:
        """Centre the notice on the whole bar, and get out of the way.

        A QStatusBar lays normal widgets from the left and permanent ones from
        the right, so anything in the layout centres in whatever is left over
        and slides sideways as the page and zoom indicators appear. Iris,
        Proteus and Argus give their notice a strip of its own where nothing
        else competes; this is the same result in the one strip Orion has.

        So the notice is a plain child, positioned here.

        Centred on the bar when that clears the indicators, and nudged left
        just enough when it does not -- not dropped. Requiring the *centred*
        rectangle to fit was the first attempt, and it hid the address on a
        1400-pixel window on Windows, where Segoe UI makes both the notice and
        the indicators wider than the font this was written against. Staying
        visible matters more than staying exactly centred.

        Hidden only while a transient message is showing, where the two would
        overlap, and when even the short form has nowhere to go.
        """
        notice = self._notice
        if self.currentMessage():
            notice.hide()
            return

        # The permanent widgets are laid out from the right; the leftmost one
        # that is actually showing is where the space for this ends.
        occupied = [
            label.geometry().left()
            for label in (self._modified, self._page, self._zoom, self._mode)
            if label.isVisible() and label.text()
        ]
        limit = min(occupied) if occupied else self.width()

        # Full text first, then the notice without the invitation to write.
        # A narrow window is a reason to say less, not a reason to stop
        # carrying the notice: the copyright and the licence are the part
        # AGPL-3.0 section 5 is about, and they survive to the last step.
        for html in (self._notice_full, self._notice_short):
            notice.setText(html)
            wanted = notice.sizeHint()
            if wanted.width() > limit - 2 * MARGIN:
                continue          # this form does not fit at all; try the next

            # Centred on the bar, then pulled back inside the free strip if
            # that would run under the indicators. The pull is the smallest
            # one that clears them, so it stays as close to centred as the
            # window allows.
            left = (self.width() - wanted.width()) // 2
            left = min(left, limit - MARGIN - wanted.width())
            left = max(left, MARGIN)

            notice.setGeometry(
                left,
                (self.height() - wanted.height()) // 2,
                wanted.width(),
                wanted.height(),
            )
            notice.show()
            notice.raise_()
            return

        notice.hide()

    def _licence_notice(self) -> QLabel:
        """The copyright and licence line, with the address spelled out.

        AGPL-3.0 section 5 asks the work to carry Appropriate Legal Notices,
        and Iris, Proteus and Argus have all shown this line since their first
        release. Orion shipped v1.0.0 without one.

        The address is a link rather than plain text because the person
        running the application is exactly the person who might need to buy a
        commercial licence, and "available on request" tells them nothing
        about where to ask.

        Kept out of the status bar's layout and positioned by hand; the
        reasoning is in :meth:`_place_notice`.
        """
        link = (
            f'<a href="mailto:{CONTACT_EMAIL}'
            f'?subject={quote(LICENSING_SUBJECT)}">{CONTACT_EMAIL}</a>'
        )
        self._notice_full = f"{LICENSE_NOTICE} {link}"
        # Without the trailing "Commercial licensing:", which is what the
        # address was introducing.
        self._notice_short = LICENSE_NOTICE.rsplit("|", 1)[0].strip()

        label = QLabel(self._notice_full, self)
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
        self._place_notice()

    def set_zoom(self, zoom: float, mode: str) -> None:
        self._zoom.setText(f"Zoom {round(zoom * 100)}%")
        self._mode.setText(
            {"fit_width": "Fit Width", "fit_page": "Fit Page"}.get(mode, "Custom Zoom")
        )
        self._place_notice()

    def set_modified(self, modified: bool) -> None:
        self._modified.setText("Modified" if modified else "")
        self._place_notice()

    def clear_document(self) -> None:
        self._page.clear()
        self._zoom.clear()
        self._mode.clear()
        self._modified.clear()
        self._place_notice()

    def flash(self, message: str, milliseconds: int = 4000) -> None:
        self.showMessage(message, milliseconds)
