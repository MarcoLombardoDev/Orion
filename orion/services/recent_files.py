"""The Recent Files list (spec §6)."""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

from orion.services.settings import Settings
from orion.utils.events import Event

__all__ = ["RecentFiles", "MAX_RECENT"]

MAX_RECENT = 12


class RecentFiles:
    """Most-recent-first list of file paths, persisted in the settings file."""

    def __init__(self, settings: Settings, limit: int = MAX_RECENT) -> None:
        self._settings = settings
        self._limit = limit
        self.changed = Event("recent_files_changed")

    @property
    def paths(self) -> list[Path]:
        stored: Sequence[str] = self._settings.get("recent_files", []) or []
        return [Path(item) for item in stored][: self._limit]

    def existing(self) -> list[Path]:
        """Recent files that are still on disk."""
        return [path for path in self.paths if path.exists()]

    def add(self, path: str | Path) -> None:
        resolved = Path(path).expanduser()
        try:
            resolved = resolved.resolve()
        except OSError:  # pragma: no cover - unreachable network paths
            pass
        entries = [str(resolved)]
        entries += [str(p) for p in self.paths if p != resolved]
        self._settings.set("recent_files", entries[: self._limit])
        self.changed.emit(self.paths)

    def remove(self, path: str | Path) -> None:
        target = Path(path)
        entries = [str(p) for p in self.paths if p != target]
        self._settings.set("recent_files", entries)
        self.changed.emit(self.paths)

    def clear(self) -> None:
        self._settings.set("recent_files", [])
        self.changed.emit([])
