"""Safe file writing (spec §20).

Content is written to a temporary file in the *same directory* as the target —
so the final rename stays on one filesystem and is therefore atomic — then
validated by the caller and moved into place with :func:`os.replace`.
"""

from __future__ import annotations

import logging
import os
import tempfile
from collections.abc import Callable
from pathlib import Path

log = logging.getLogger(__name__)

__all__ = ["atomic_write_bytes", "remove_quietly", "unique_path"]


def atomic_write_bytes(
    data: bytes,
    path: str | Path,
    *,
    validate: Callable[[Path], None] | None = None,
    suffix: str = ".orion.tmp",
) -> Path:
    """Write *data* to *path* without ever leaving it half-written.

    ``validate`` receives the temporary file and should raise if the content is
    not acceptable; in that case the temporary file is deleted and the target
    is left exactly as it was.
    """
    path = Path(path)
    directory = path.parent
    directory.mkdir(parents=True, exist_ok=True)

    fd, temp_name = tempfile.mkstemp(prefix=f".{path.stem}-", suffix=suffix, dir=directory)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if validate is not None:
            validate(temp_path)
        os.replace(temp_path, path)
    except BaseException:
        remove_quietly(temp_path)
        raise
    return path


def remove_quietly(path: Path | None) -> None:
    if path is None:
        return
    try:
        path.unlink(missing_ok=True)
    except OSError:  # pragma: no cover - best effort
        log.debug("Could not remove temporary file %s", path)


def unique_path(path: Path) -> Path:
    """Return *path*, or ``name-2.pdf``, ``name-3.pdf``… if it already exists."""
    if not path.exists():
        return path
    stem, suffix, parent = path.stem, path.suffix, path.parent
    for counter in range(2, 1000):
        candidate = parent / f"{stem}-{counter}{suffix}"
        if not candidate.exists():
            return candidate
    return parent / f"{stem}-{os.getpid()}{suffix}"
