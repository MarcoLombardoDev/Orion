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
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from orion.document.document import Document
from orion.document.serialization import load_document_snapshot, save_document_snapshot
from orion.utils.paths import recovery_dir

log = logging.getLogger(__name__)

__all__ = ["RecoverySnapshot", "AutosaveService", "list_recoverable", "discard_all"]

SNAPSHOT_SUFFIX = ".orion-recovery.json"


@dataclass(slots=True)
class RecoverySnapshot:
    path: Path
    document_path: Optional[Path]
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

    def __init__(self, session_id: str, *, directory: Path | None = None, enabled: bool = True) -> None:
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
        try:
            info = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
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
    if pid <= 0 or pid == os.getpid():
        return pid == os.getpid()
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True
