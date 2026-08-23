# Orion — PDF Editor for Desktop
# Copyright (C) 2026 Marco Lombardo
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# Distributed WITHOUT ANY WARRANTY; see LICENSE for the full terms.
# A commercial licence, without the AGPL's obligations, is available for use
# in proprietary or closed-source products — see COMMERCIAL-LICENSE.md.

"""Internal logging for debugging (spec §25).

Writes a size-limited rotating log next to the cache directory and mirrors
records to stderr.  Tracebacks go to the log file only — the user never sees a
Python traceback, they see the friendly message produced by
:mod:`orion.pdf.errors`.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import sys
from pathlib import Path

from orion.utils.paths import log_dir

_CONFIGURED = False
_FORMAT = "%(asctime)s %(levelname)-7s %(name)-28s %(message)s"


def setup_logging(level: int | str | None = None, *, to_file: bool = True) -> Path | None:
    """Configure the root logger once.  Returns the log file path, if any."""
    global _CONFIGURED
    if _CONFIGURED:
        return _current_log_file()

    if level is None:
        level = os.environ.get("ORION_LOG_LEVEL", "INFO")
    if isinstance(level, str):
        level = getattr(logging, level.upper(), logging.INFO)

    root = logging.getLogger()
    root.setLevel(level)

    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(logging.Formatter(_FORMAT))
    root.addHandler(console)

    path: Path | None = None
    if to_file:
        try:
            path = log_dir() / "orion.log"
            handler = logging.handlers.RotatingFileHandler(
                path, maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8"
            )
            handler.setFormatter(logging.Formatter(_FORMAT))
            root.addHandler(handler)
        except OSError:
            # A read-only or missing home directory must not prevent start-up.
            path = None

    _CONFIGURED = True
    logging.getLogger(__name__).debug("Logging initialised (level=%s, file=%s)", level, path)
    return path


def _current_log_file() -> Path | None:
    for handler in logging.getLogger().handlers:
        if isinstance(handler, logging.handlers.RotatingFileHandler):
            return Path(handler.baseFilename)
    return None


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
