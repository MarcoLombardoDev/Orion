# Orion — PDF Editor for Desktop
# Copyright (C) 2026 Marco Lombardo
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# Distributed WITHOUT ANY WARRANTY; see LICENSE for the full terms.
# A commercial licence, without the AGPL's obligations, is available for use
# in proprietary or closed-source products — see COMMERCIAL-LICENSE.md.

"""The working document: an ordered list of pages plus its source registry."""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from orion.document.page import Page
from orion.utils.events import Event
from orion.utils.geometry import Size

__all__ = ["Document", "DocumentSource"]


@dataclass
class DocumentSource:
    """A PDF file referenced by one or more pages.

    Pages imported from another PDF keep pointing at that file (by *key*) until
    the document is written, so importing 500 pages costs nothing until save.
    """

    key: str
    path: Path | None = None
    data: bytes | None = None
    label: str = ""

    @property
    def display_name(self) -> str:
        if self.label:
            return self.label
        if self.path is not None:
            return self.path.name
        return self.key[:8]

    @classmethod
    def for_path(cls, path: str | Path) -> DocumentSource:
        path = Path(path)
        key = hashlib.sha1(str(path.resolve()).encode("utf-8")).hexdigest()[:16]
        return cls(key=key, path=path, label=path.name)

    def to_dict(self) -> dict[str, Any]:
        # ``data`` is intentionally not serialised: recovery snapshots reference
        # sources by path, they are not a substitute for the source files.
        return {"key": self.key, "path": str(self.path) if self.path else None, "label": self.label}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DocumentSource:
        path = data.get("path")
        return cls(key=data["key"], path=Path(path) if path else None, label=data.get("label", ""))


class Document:
    """An editable PDF document.

    The document owns pages and knows whether it has unsaved changes; it does
    *not* know how to read or write PDF files — that is :mod:`orion.pdf`.
    Change notification uses :class:`~orion.utils.events.Event` rather than Qt
    signals so this layer stays framework-neutral and unit-testable.
    """

    def __init__(
        self,
        pages: Iterable[Page] | None = None,
        *,
        sources: Iterable[DocumentSource] | None = None,
        path: str | Path | None = None,
        title: str = "",
    ) -> None:
        self.id: str = uuid.uuid4().hex
        self._pages: list[Page] = list(pages or [])
        self._sources: dict[str, DocumentSource] = {s.key: s for s in (sources or [])}
        self.path: Path | None = Path(path) if path else None
        self.title: str = title
        self.metadata: dict[str, str] = {}
        self._modified: bool = False

        #: Emitted with the whole document after a structural change.
        self.pages_changed = Event("pages_changed")
        #: Emitted with ``(page_index, object_id | None)`` after a content change.
        self.page_content_changed = Event("page_content_changed")
        #: Emitted with the new modified flag.
        self.modified_changed = Event("modified_changed")

    # -- identity --------------------------------------------------------
    @property
    def display_name(self) -> str:
        if self.path is not None:
            return self.path.name
        return self.title or "Untitled"

    @property
    def modified(self) -> bool:
        return self._modified

    def set_modified(self, value: bool = True) -> None:
        if self._modified != value:
            self._modified = value
            self.modified_changed.emit(value)

    # -- pages -----------------------------------------------------------
    @property
    def pages(self) -> list[Page]:
        return self._pages

    @property
    def page_count(self) -> int:
        return len(self._pages)

    def __len__(self) -> int:
        return len(self._pages)

    def __iter__(self) -> Iterator[Page]:
        return iter(self._pages)

    def __getitem__(self, index: int) -> Page:
        return self._pages[index]

    def page_at(self, index: int) -> Page | None:
        if 0 <= index < len(self._pages):
            return self._pages[index]
        return None

    def index_of_page(self, page_id: str) -> int:
        for index, page in enumerate(self._pages):
            if page.id == page_id:
                return index
        return -1

    def find_page(self, page_id: str) -> Page | None:
        index = self.index_of_page(page_id)
        return self._pages[index] if index >= 0 else None

    def insert_page(self, index: int, page: Page) -> int:
        index = max(0, min(index, len(self._pages)))
        self._pages.insert(index, page)
        self._changed_structure()
        return index

    def append_page(self, page: Page) -> int:
        return self.insert_page(len(self._pages), page)

    def remove_page(self, index: int) -> Page | None:
        if not (0 <= index < len(self._pages)):
            return None
        page = self._pages.pop(index)
        self._changed_structure()
        return page

    def move_page(self, from_index: int, to_index: int) -> bool:
        if not (0 <= from_index < len(self._pages)):
            return False
        to_index = max(0, min(to_index, len(self._pages) - 1))
        if from_index == to_index:
            return False
        page = self._pages.pop(from_index)
        self._pages.insert(to_index, page)
        self._changed_structure()
        return True

    def set_page_order(self, order: list[int]) -> bool:
        """Reorder pages so the new sequence is ``[pages[i] for i in order]``."""
        if sorted(order) != list(range(len(self._pages))):
            return False
        self._pages = [self._pages[i] for i in order]
        self._changed_structure()
        return True

    # -- objects ---------------------------------------------------------
    def locate_object(self, object_id: str) -> tuple[int, Page] | None:
        for index, page in enumerate(self._pages):
            if page.find_object(object_id) is not None:
                return index, page
        return None

    # -- sources ---------------------------------------------------------
    @property
    def sources(self) -> dict[str, DocumentSource]:
        return self._sources

    def add_source(self, source: DocumentSource) -> DocumentSource:
        existing = self._sources.get(source.key)
        if existing is not None:
            return existing
        self._sources[source.key] = source
        return source

    def source_for(self, page: Page) -> DocumentSource | None:
        if page.source is None:
            return None
        return self._sources.get(page.source.source_key)

    def prune_sources(self) -> None:
        """Forget sources no page references any more."""
        used = {p.source.source_key for p in self._pages if p.source is not None}
        for key in list(self._sources):
            if key not in used:
                del self._sources[key]

    # -- notification ----------------------------------------------------
    def _changed_structure(self) -> None:
        self.set_modified(True)
        self.pages_changed.emit(self)

    def notify_structure_changed(self) -> None:
        self._changed_structure()

    def notify_content_changed(self, page_index: int, object_id: str | None = None) -> None:
        self.set_modified(True)
        self.page_content_changed.emit(page_index, object_id)

    # -- serialisation ---------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return {
            "version": 1,
            "id": self.id,
            "path": str(self.path) if self.path else None,
            "title": self.title,
            "metadata": dict(self.metadata),
            "sources": [s.to_dict() for s in self._sources.values()],
            "pages": [p.to_dict() for p in self._pages],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Document:
        document = cls(
            pages=[Page.from_dict(p) for p in data.get("pages", [])],
            sources=[DocumentSource.from_dict(s) for s in data.get("sources", [])],
            path=data.get("path"),
            title=data.get("title", ""),
        )
        document.id = data.get("id") or document.id
        document.metadata = dict(data.get("metadata", {}))
        return document

    @classmethod
    def blank(cls, size: Size | None = None, page_count: int = 1) -> Document:
        return cls(pages=[Page(base_size=size or Size(595.0, 842.0)) for _ in range(page_count)])

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"<Document {self.display_name!r} "
            f"pages={len(self._pages)} modified={self._modified}>"
        )
