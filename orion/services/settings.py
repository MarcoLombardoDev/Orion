"""A tiny JSON-backed settings store.

Deliberately not ``QSettings``: the settings need to be readable by the model
layer and by tests without a ``QApplication``, and a single JSON file is easier
to inspect and to reset than a per-platform registry/plist.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from orion.utils.fileio import atomic_write_bytes
from orion.utils.paths import settings_file

log = logging.getLogger(__name__)

__all__ = ["Settings", "settings"]

DEFAULTS: dict[str, Any] = {
    "theme": "system",
    "zoom_mode": "fit_width",
    "zoom": 1.0,
    "show_thumbnails": True,
    "show_properties": True,
    "recent_files": [],
    "autosave_enabled": True,
    "autosave_interval_seconds": 60,
    "render_cache_mb": 256,
    "window_geometry": None,
    "window_state": None,
    "last_directory": "",
    "default_author": "",
}


class Settings:
    """Load once, save on change, never raise at the caller."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or settings_file()
        self._values: dict[str, Any] = dict(DEFAULTS)
        self.load()

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> None:
        try:
            raw = self._path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return
        except OSError as exc:
            log.warning("Could not read settings: %s", exc)
            return
        try:
            stored = json.loads(raw)
        except ValueError:
            log.warning("Settings file is not valid JSON; using defaults")
            return
        if isinstance(stored, dict):
            self._values.update(stored)

    def save(self) -> None:
        try:
            payload = json.dumps(self._values, indent=2, ensure_ascii=False).encode("utf-8")
            atomic_write_bytes(payload, self._path, suffix=".tmp")
        except Exception as exc:  # settings must never break the application
            log.warning("Could not save settings: %s", exc)

    def get(self, key: str, default: Any = None) -> Any:
        return self._values.get(key, DEFAULTS.get(key, default))

    def set(self, key: str, value: Any, *, persist: bool = True) -> None:
        if self._values.get(key) == value:
            return
        self._values[key] = value
        if persist:
            self.save()

    def update(self, values: dict[str, Any]) -> None:
        self._values.update(values)
        self.save()

    def reset(self) -> None:
        self._values = dict(DEFAULTS)
        self.save()

    def __contains__(self, key: str) -> bool:
        return key in self._values


_instance: Settings | None = None


def settings() -> Settings:
    """Process-wide settings instance (created on first use)."""
    global _instance
    if _instance is None:
        _instance = Settings()
    return _instance
