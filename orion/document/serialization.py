"""JSON (de)serialisation of the document model.

Used by three features that would otherwise each invent their own format:
crash-recovery snapshots (§32), the object clipboard (§14) and the test-suite.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Sequence

from orion.document.document import Document
from orion.document.objects import PageObject, create_object

__all__ = [
    "document_to_json",
    "document_from_json",
    "save_document_snapshot",
    "load_document_snapshot",
    "objects_to_json",
    "objects_from_json",
    "CLIPBOARD_MIME",
]

#: MIME type Orion puts on the system clipboard so a paste between two Orion
#: windows carries real objects rather than a screenshot.
CLIPBOARD_MIME = "application/x-orion-objects+json"

SNAPSHOT_VERSION = 1


def document_to_json(document: Document, *, indent: int | None = None) -> str:
    return json.dumps(document.to_dict(), indent=indent, ensure_ascii=False)


def document_from_json(text: str | bytes) -> Document:
    return Document.from_dict(json.loads(text))


def save_document_snapshot(document: Document, path: str | Path) -> Path:
    """Write a snapshot atomically so a crash mid-write cannot corrupt it."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text(document_to_json(document), encoding="utf-8")
    temporary.replace(path)
    return path


def load_document_snapshot(path: str | Path) -> Document:
    return document_from_json(Path(path).read_text(encoding="utf-8"))


def objects_to_json(objects: Iterable[PageObject]) -> str:
    payload = {
        "version": SNAPSHOT_VERSION,
        "type": "orion-objects",
        "objects": [obj.to_dict() for obj in objects],
    }
    return json.dumps(payload, ensure_ascii=False)


def objects_from_json(text: str | bytes) -> list[PageObject]:
    """Parse clipboard payload; returns an empty list if it is not ours."""
    try:
        payload: Any = json.loads(text)
    except (ValueError, TypeError):
        return []
    if not isinstance(payload, dict) or payload.get("type") != "orion-objects":
        return []
    items: Sequence[Any] = payload.get("objects", [])
    objects: list[PageObject] = []
    for item in items:
        try:
            objects.append(create_object(item))
        except (ValueError, KeyError, TypeError):
            continue
    return objects
