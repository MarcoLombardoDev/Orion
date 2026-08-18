"""Cross-platform locations for configuration, cache, logs and recovery files.

Kept free of Qt so the model/engine layers and the test-suite can use it.
Platform branching is confined to this module (spec §23).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from orion import APP_NAME

__all__ = [
    "config_dir",
    "data_dir",
    "cache_dir",
    "log_dir",
    "recovery_dir",
    "settings_file",
    "ensure_dir",
]


def _home() -> Path:
    return Path(os.path.expanduser("~"))


def _base(kind: str) -> Path:
    """``kind`` is one of ``config``, ``data``, ``cache``."""
    override = os.environ.get("ORION_HOME")
    if override:
        return Path(override) / kind

    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA") or str(_home() / "AppData" / "Roaming")
        local = os.environ.get("LOCALAPPDATA") or str(_home() / "AppData" / "Local")
        root = Path(local if kind == "cache" else appdata)
        return root / APP_NAME
    if sys.platform == "darwin":
        if kind == "cache":
            return _home() / "Library" / "Caches" / APP_NAME
        return _home() / "Library" / "Application Support" / APP_NAME
    # Linux / BSD — XDG base directory specification
    env = {
        "config": ("XDG_CONFIG_HOME", ".config"),
        "data": ("XDG_DATA_HOME", ".local/share"),
        "cache": ("XDG_CACHE_HOME", ".cache"),
    }[kind]
    root = os.environ.get(env[0]) or str(_home() / env[1])
    return Path(root) / APP_NAME.lower()


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_dir() -> Path:
    return ensure_dir(_base("config"))


def data_dir() -> Path:
    return ensure_dir(_base("data"))


def cache_dir() -> Path:
    return ensure_dir(_base("cache"))


def log_dir() -> Path:
    return ensure_dir(_base("cache") / "logs")


def recovery_dir() -> Path:
    return ensure_dir(_base("data") / "recovery")


def settings_file() -> Path:
    return config_dir() / "settings.json"
