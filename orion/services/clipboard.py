"""The object clipboard (spec §14).

Copy/cut/paste work on Orion objects, not on rasterised pixels.  The payload is
kept in-process *and*, when Qt is available, mirrored onto the system clipboard
as JSON under a private MIME type, so two Orion windows can exchange objects.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from orion.document.objects import PageObject
from orion.document.serialization import CLIPBOARD_MIME, objects_from_json, objects_to_json
from orion.utils.events import Event

log = logging.getLogger(__name__)

__all__ = ["ObjectClipboard", "release_system_clipboard", "PASTE_OFFSET"]

#: Offset applied to a pasted copy so it does not hide the original.
PASTE_OFFSET = (12.0, 12.0)


class ObjectClipboard:
    """Holds a set of copied objects."""

    def __init__(self, *, use_system_clipboard: bool = True) -> None:
        self._objects: list[PageObject] = []
        self._use_system = use_system_clipboard
        self.changed = Event("clipboard_changed")

    # -- state -----------------------------------------------------------
    @property
    def is_empty(self) -> bool:
        """Cheap check: does *not* deserialise the payload.

        This is polled every time the UI state refreshes, so parsing an
        embedded image out of the clipboard here would make every selection
        change slow.
        """
        return not self._objects and not self._system_has_objects()

    def clear(self) -> None:
        self._objects = []
        self.changed.emit(self)

    # -- operations ------------------------------------------------------
    def copy(self, objects: Sequence[PageObject]) -> int:
        """Store clones of *objects*.  Returns how many were copied."""
        self._objects = [obj.clone(new_id=False) for obj in objects]
        if self._use_system:
            self._write_system(self._objects)
        self.changed.emit(self)
        return len(self._objects)

    def paste(self, *, offset: tuple[float, float] = PASTE_OFFSET) -> list[PageObject]:
        """Return fresh copies (new ids, nudged) ready to be added to a page."""
        objects = self._read_system() or self._objects
        return [obj.clone(new_id=True, offset=offset) for obj in objects]

    def peek(self) -> list[PageObject]:
        return list(self._read_system() or self._objects)

    # -- system clipboard bridge ----------------------------------------
    def _write_system(self, objects: Sequence[PageObject]) -> None:
        mime = self._qt_mime()
        if mime is None:
            return
        try:
            from PySide6.QtCore import QByteArray
            from PySide6.QtGui import QGuiApplication

            payload = objects_to_json(objects).encode("utf-8")
            data = mime()
            data.setData(CLIPBOARD_MIME, QByteArray(payload))
            data.setText(_plain_text_preview(objects))
            QGuiApplication.clipboard().setMimeData(data)
        except Exception:  # a headless or restricted session must still work
            log.debug("System clipboard unavailable", exc_info=True)

    def _system_has_objects(self) -> bool:
        """Whether the system clipboard carries an Orion payload."""
        if not self._use_system:
            return False
        try:
            from PySide6.QtGui import QGuiApplication

            if QGuiApplication.instance() is None:
                return False
            data = QGuiApplication.clipboard().mimeData()
            return data is not None and data.hasFormat(CLIPBOARD_MIME)
        except Exception:
            return False

    def _read_system(self) -> list[PageObject]:
        if not self._use_system:
            return []
        try:
            from PySide6.QtGui import QGuiApplication

            if QGuiApplication.instance() is None:
                return []
            data = QGuiApplication.clipboard().mimeData()
            if data is None or not data.hasFormat(CLIPBOARD_MIME):
                return []
            payload = bytes(data.data(CLIPBOARD_MIME).data())
            return objects_from_json(payload)
        except Exception:
            log.debug("Could not read the system clipboard", exc_info=True)
            return []

    @staticmethod
    def _qt_mime():
        try:
            from PySide6.QtCore import QMimeData
            from PySide6.QtGui import QGuiApplication

            if QGuiApplication.instance() is None:
                return None
            return QMimeData
        except Exception:
            return None


def release_system_clipboard() -> None:
    """Hand the system clipboard back to Qt before the application exits.

    A ``QMimeData`` created in Python and given to ``QClipboard.setMimeData``
    is still referenced by the clipboard when the ``QApplication`` is
    destroyed, and freeing it then segfaults the process (reproduced on
    PySide6 6.11 with a twelve-line script, no Orion code involved).  So on
    shutdown Orion's payload is replaced by a plain-text copy, which Qt
    allocates and owns: the object that crashes is gone, and other
    applications can still paste the text that was copied.

    Anything *not* put there by Orion is left untouched.
    """
    try:
        from PySide6.QtGui import QGuiApplication

        if QGuiApplication.instance() is None:
            return
        clipboard = QGuiApplication.clipboard()
        data = clipboard.mimeData()
        if data is None or not data.hasFormat(CLIPBOARD_MIME):
            return
        text = data.text()
        if text:
            clipboard.setText(text)
        else:
            clipboard.clear()
    except Exception:  # shutdown must never raise
        log.debug("Could not release the system clipboard", exc_info=True)


def _plain_text_preview(objects: Sequence[PageObject]) -> str:
    """Text put on the clipboard for other applications."""
    parts = [getattr(obj, "text", "") or getattr(obj, "contents", "") for obj in objects]
    text = "\n".join(part for part in parts if part)
    return text or f"{len(objects)} Orion object(s)"
