# Orion — PDF Editor for Desktop
# Copyright (C) 2026 Marco Lombardo
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# Distributed WITHOUT ANY WARRANTY; see LICENSE for the full terms.
# A commercial licence, without the AGPL's obligations, is available for use
# in proprietary or closed-source products — see COMMERCIAL-LICENSE.md.

"""Crash recovery (spec §32).

Orion never writes to the user's PDF without an explicit Save.  Instead it
periodically serialises the *document model* to a clearly-named recovery file
under the application data directory.  A recovery file is a JSON snapshot, not
a PDF, so it can never be mistaken for the original document.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from orion.document.document import Document
from orion.document.serialization import load_document_snapshot, save_document_snapshot
from orion.utils.paths import recovery_dir

log = logging.getLogger(__name__)

__all__ = ["RecoverySnapshot", "AutosaveService", "list_recoverable", "discard_all"]

SNAPSHOT_SUFFIX = ".orion-recovery.json"


@dataclass(slots=True)
class RecoverySnapshot:
    path: Path
    document_path: Path | None
    saved_at: float
    page_count: int
    pid: int

    @property
    def display_name(self) -> str:
        return self.document_path.name if self.document_path else "Untitled document"

    @property
    def age_text(self) -> str:
        minutes = max(0, int((time.time() - self.saved_at) // 60))
        if minutes < 1:
            return "less than a minute ago"
        if minutes < 60:
            return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
        hours = minutes // 60
        return f"{hours} hour{'s' if hours != 1 else ''} ago"

    def load(self) -> Document:
        return load_document_snapshot(self.path)

    def discard(self) -> None:
        for candidate in (self.path, _meta_path(self.path)):
            try:
                candidate.unlink(missing_ok=True)
            except OSError:  # pragma: no cover - best effort
                log.debug("Could not remove %s", candidate)


class AutosaveService:
    """Writes a snapshot when the document is dirty.

    The service is deliberately *pull*-based: the UI calls :meth:`maybe_save`
    from a timer.  That keeps threading out of the picture entirely — a
    snapshot of a few hundred kilobytes of JSON is far cheaper than the risk of
    serialising a model that is being mutated on another thread.
    """

    def __init__(
        self, session_id: str, *, directory: Path | None = None, enabled: bool = True
    ) -> None:
        self._session_id = session_id
        self._directory = directory or recovery_dir()
        self._enabled = enabled
        self._last_saved_at = 0.0
        self._snapshot_path = self._directory / f"{session_id}{SNAPSHOT_SUFFIX}"

    @property
    def enabled(self) -> bool:
        return self._enabled

    def set_enabled(self, value: bool) -> None:
        self._enabled = value
        if not value:
            self.discard()

    @property
    def snapshot_path(self) -> Path:
        return self._snapshot_path

    def maybe_save(self, document: Document | None) -> bool:
        """Snapshot *document* if it has unsaved changes.  Returns ``True`` if written."""
        if not self._enabled or document is None or not document.modified:
            return False
        try:
            save_document_snapshot(document, self._snapshot_path)
            _meta_path(self._snapshot_path).write_text(
                json.dumps(
                    {
                        "document_path": str(document.path) if document.path else None,
                        "saved_at": time.time(),
                        "page_count": document.page_count,
                        "pid": os.getpid(),
                    }
                ),
                encoding="utf-8",
            )
        except Exception as exc:  # autosave must never interrupt the user
            log.warning("Autosave failed: %s", exc)
            return False
        self._last_saved_at = time.time()
        log.debug("Autosaved to %s", self._snapshot_path)
        return True

    def discard(self) -> None:
        """Remove this session's snapshot — called after a real save or a clean exit."""
        for candidate in (self._snapshot_path, _meta_path(self._snapshot_path)):
            try:
                candidate.unlink(missing_ok=True)
            except OSError:  # pragma: no cover - best effort
                log.debug("Could not remove %s", candidate)


def _meta_path(snapshot: Path) -> Path:
    return snapshot.with_suffix(snapshot.suffix + ".meta")


def list_recoverable(
    directory: Path | None = None, *, exclude_session: str | None = None
) -> list[RecoverySnapshot]:
    """Find snapshots left behind by a previous run."""
    directory = directory or recovery_dir()
    results: list[RecoverySnapshot] = []
    try:
        candidates = sorted(directory.glob(f"*{SNAPSHOT_SUFFIX}"))
    except OSError:  # pragma: no cover - unreadable directory
        return []

    for path in candidates:
        if exclude_session and path.name.startswith(exclude_session):
            continue
        meta_path = _meta_path(path)
        info: dict = {}
        with suppress(OSError, ValueError):
            info = json.loads(meta_path.read_text(encoding="utf-8"))
        pid = int(info.get("pid", 0) or 0)
        if pid and _process_alive(pid):
            continue  # another Orion instance is using it right now
        document_path = info.get("document_path")
        results.append(
            RecoverySnapshot(
                path=path,
                document_path=Path(document_path) if document_path else None,
                saved_at=float(info.get("saved_at", path.stat().st_mtime)),
                page_count=int(info.get("page_count", 0)),
                pid=pid,
            )
        )
    results.sort(key=lambda snapshot: snapshot.saved_at, reverse=True)
    return results


def discard_all(directory: Path | None = None) -> None:
    for snapshot in list_recoverable(directory):
        snapshot.discard()


def _process_alive(pid: int) -> bool:
    """Is the process that wrote a snapshot still running?

    A snapshot belonging to a live instance is in use, not recoverable.  When
    the answer is uncertain the conservative choice is "alive": that only means
    Orion does not offer to recover it, whereas a wrong "dead" could hand the
    same document to two instances at once.
    """
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    if sys.platform == "win32":
        return _windows_process_alive(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # it exists, it just belongs to another user
    except OSError:
        return False
    return True


def _windows_process_alive(pid: int) -> bool:
    """Windows liveness probe that does **not** use ``os.kill``.

    On Windows ``os.kill(pid, 0)`` does not probe anything: any signal other
    than CTRL_C_EVENT/CTRL_BREAK_EVENT goes straight to ``TerminateProcess``.
    Using it here would kill the very Orion instance whose unsaved work this
    check exists to protect, so the probe opens a query-only handle instead.
    """
    import ctypes
    from ctypes import wintypes

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    ERROR_ACCESS_DENIED = 5
    STILL_ACTIVE = 259

    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            # Access denied means the process exists but is not ours to query.
            return ctypes.get_last_error() == ERROR_ACCESS_DENIED
        try:
            code = wintypes.DWORD()
            if kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return code.value == STILL_ACTIVE
            return True
        finally:
            kernel32.CloseHandle(handle)
    except Exception:  # pragma: no cover - exercised only on Windows
        log.debug("Could not probe process %d", pid, exc_info=True)
        return True
