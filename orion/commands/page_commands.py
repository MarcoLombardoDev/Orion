# Orion — PDF Editor for Desktop
# Copyright (C) 2026 Marco Lombardo
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# Distributed WITHOUT ANY WARRANTY; see LICENSE for the full terms.
# A commercial licence, without the AGPL's obligations, is available for use
# in proprietary or closed-source products — see COMMERCIAL-LICENSE.md.

"""Commands for page management (spec §16)."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from orion.commands.base import Command
from orion.document.document import Document, DocumentSource
from orion.document.page import Page, normalise_rotation
from orion.utils.geometry import Size

__all__ = [
    "InsertPageCommand",
    "DeletePagesCommand",
    "DuplicatePageCommand",
    "MovePageCommand",
    "ReorderPagesCommand",
    "RotatePagesCommand",
    "ImportPagesCommand",
]


class InsertPageCommand(Command):
    """Insert a blank page (spec §16 "Add Page")."""

    def __init__(
        self,
        document: Document,
        index: int,
        size: Size | None = None,
        *,
        page: Page | None = None,
        text: str = "Insert Page",
    ) -> None:
        self._document = document
        self._index = index
        self._page = page or Page(base_size=size or _default_size(document, index))
        self.text = text

    @property
    def page(self) -> Page:
        return self._page

    @property
    def index(self) -> int:
        return self._index

    def execute(self) -> None:
        self._index = self._document.insert_page(self._index, self._page)

    def undo(self) -> None:
        self._document.remove_page(self._document.index_of_page(self._page.id))


class DeletePagesCommand(Command):
    """Delete one or more pages, restoring their exact positions on undo."""

    def __init__(
        self, document: Document, indices: Iterable[int], *, text: str | None = None
    ) -> None:
        self._document = document
        self._indices = sorted(set(indices))
        self._removed: list[tuple[int, Page]] = []
        count = len(self._indices)
        self.text = text or ("Delete Page" if count == 1 else f"Delete {count} Pages")

    def execute(self) -> None:
        self._removed = []
        for index in sorted(self._indices, reverse=True):
            page = self._document.remove_page(index)
            if page is not None:
                self._removed.append((index, page))
        self._document.prune_sources()

    def undo(self) -> None:
        for index, page in sorted(self._removed, key=lambda item: item[0]):
            self._document.insert_page(index, page)


class DuplicatePageCommand(Command):
    """Duplicate a page, inserting the copy right after the original."""

    text = "Duplicate Page"

    def __init__(self, document: Document, index: int) -> None:
        self._document = document
        self._index = index
        self._copy: Page | None = None

    @property
    def copy(self) -> Page | None:
        return self._copy

    def execute(self) -> None:
        original = self._document.page_at(self._index)
        if original is None:
            return
        if self._copy is None:
            self._copy = original.duplicate()
        self._document.insert_page(self._index + 1, self._copy)

    def undo(self) -> None:
        if self._copy is None:
            return
        self._document.remove_page(self._document.index_of_page(self._copy.id))


class MovePageCommand(Command):
    """Reorder a single page (drag & drop in the thumbnail panel)."""

    text = "Move Page"

    def __init__(self, document: Document, from_index: int, to_index: int) -> None:
        self._document = document
        self._from = from_index
        self._to = to_index

    def execute(self) -> None:
        self._document.move_page(self._from, self._to)

    def undo(self) -> None:
        self._document.move_page(self._to, self._from)


class ReorderPagesCommand(Command):
    """Apply an arbitrary new page order in one step."""

    text = "Reorder Pages"

    def __init__(self, document: Document, order: Sequence[int]) -> None:
        self._document = document
        self._order = list(order)
        self._previous: list[int] = []

    def execute(self) -> None:
        self._previous = [0] * len(self._order)
        for new_index, old_index in enumerate(self._order):
            self._previous[old_index] = new_index
        self._document.set_page_order(self._order)

    def undo(self) -> None:
        self._document.set_page_order(self._previous)


class RotatePagesCommand(Command):
    """Rotate pages by a multiple of 90 degrees (spec §16)."""

    def __init__(self, document: Document, indices: Iterable[int], delta: int) -> None:
        self._document = document
        self._indices = sorted(set(indices))
        self._delta = normalise_rotation(delta)
        count = len(self._indices)
        noun = "Page" if count == 1 else f"{count} Pages"
        self.text = f"Rotate {noun} {self._delta}°"

    def _rotate(self, delta: int) -> None:
        for index in self._indices:
            page = self._document.page_at(index)
            if page is not None:
                page.rotate(delta)
        self._document.notify_structure_changed()

    def execute(self) -> None:
        self._rotate(self._delta)

    def undo(self) -> None:
        self._rotate(-self._delta)


class ImportPagesCommand(Command):
    """Insert pages taken from another PDF (spec §16 "Import Pages").

    The pages keep referencing the *other* file until the document is saved, so
    importing 500 pages costs nothing until the user actually writes the result.
    """

    def __init__(
        self,
        document: Document,
        index: int,
        source: DocumentSource,
        pages: Sequence[Page],
    ) -> None:
        self._document = document
        self._index = index
        self._source = source
        self._pages = list(pages)
        count = len(self._pages)
        self.text = f"Import {count} Page{'s' if count != 1 else ''}"

    @property
    def pages(self) -> list[Page]:
        return list(self._pages)

    def execute(self) -> None:
        self._document.add_source(self._source)
        for offset, page in enumerate(self._pages):
            self._document.insert_page(self._index + offset, page)

    def undo(self) -> None:
        for page in self._pages:
            self._document.remove_page(self._document.index_of_page(page.id))
        self._document.prune_sources()


def _default_size(document: Document, index: int) -> Size:
    """A new blank page matches its neighbour, falling back to A4."""
    neighbour = document.page_at(min(max(index - 1, 0), document.page_count - 1))
    return neighbour.display_size if neighbour is not None else Size(595.0, 842.0)
