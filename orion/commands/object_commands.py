# Orion — PDF Editor for Desktop
# Copyright (C) 2026 Marco Lombardo
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# Distributed WITHOUT ANY WARRANTY; see LICENSE for the full terms.
# A commercial licence, without the AGPL's obligations, is available for use
# in proprietary or closed-source products — see COMMERCIAL-LICENSE.md.

"""Commands that add, change, move or remove objects on a page (spec §15)."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

from orion.commands.base import Command
from orion.document.document import Document
from orion.document.objects import PageObject
from orion.utils.geometry import Rect

__all__ = [
    "AddObjectCommand",
    "DeleteObjectsCommand",
    "MoveObjectsCommand",
    "TransformObjectsCommand",
    "ModifyObjectCommand",
    "PasteObjectsCommand",
    "RaiseObjectCommand",
    "ReorderObjectCommand",
]


class _ObjectCommand(Command):
    """Shared plumbing: locating pages and notifying the document."""

    def __init__(self, document: Document, page_index: int) -> None:
        self._document = document
        self._page_index = page_index

    @property
    def _page(self):
        page = self._document.page_at(self._page_index)
        if page is None:
            raise IndexError(f"Page {self._page_index} no longer exists")
        return page

    def _notify(self, object_id: str | None = None) -> None:
        self._document.notify_content_changed(self._page_index, object_id)


class AddObjectCommand(_ObjectCommand):
    """Insert one object on a page."""

    def __init__(
        self,
        document: Document,
        page_index: int,
        obj: PageObject,
        *,
        index: int | None = None,
        text: str | None = None,
    ) -> None:
        super().__init__(document, page_index)
        self._object = obj
        self._index = index
        self.text = text or f"Add {obj.display_name.split('—')[0].strip()}"

    @property
    def object(self) -> PageObject:
        return self._object

    def execute(self) -> None:
        self._index = self._page.add_object(self._object, self._index)
        self._notify(self._object.id)

    def undo(self) -> None:
        self._page.remove_object(self._object.id)
        self._notify(self._object.id)


class PasteObjectsCommand(_ObjectCommand):
    """Insert several objects at once (paste / duplicate)."""

    def __init__(
        self,
        document: Document,
        page_index: int,
        objects: Sequence[PageObject],
        *,
        text: str = "Paste",
    ) -> None:
        super().__init__(document, page_index)
        self._objects = list(objects)
        self.text = text

    @property
    def objects(self) -> list[PageObject]:
        return list(self._objects)

    def execute(self) -> None:
        page = self._page
        for obj in self._objects:
            page.add_object(obj)
        self._notify()

    def undo(self) -> None:
        page = self._page
        for obj in self._objects:
            page.remove_object(obj.id)
        self._notify()


class DeleteObjectsCommand(_ObjectCommand):
    """Remove objects, remembering their z-order so undo restores it exactly."""

    def __init__(
        self,
        document: Document,
        page_index: int,
        object_ids: Iterable[str],
        *,
        text: str = "Delete",
    ) -> None:
        super().__init__(document, page_index)
        self._ids = list(object_ids)
        self._removed: list[tuple[int, PageObject]] = []
        self.text = text

    def execute(self) -> None:
        page = self._page
        self._removed = []
        for object_id in self._ids:
            result = page.remove_object(object_id)
            if result is not None:
                obj, index = result
                self._removed.append((index, obj))
        self._notify()

    def undo(self) -> None:
        page = self._page
        for index, obj in sorted(self._removed, key=lambda item: item[0]):
            page.add_object(obj, index)
        self._notify()


class MoveObjectsCommand(_ObjectCommand):
    """Translate one or more objects.

    Consecutive moves of the same selection merge, so holding an arrow key
    produces one undo entry rather than fifty.  A mouse drag is already
    condensed into a single command by the canvas and passes
    ``allow_merge=False``, so two separate drags stay two separate undo steps.
    """

    text = "Move"

    def __init__(
        self,
        document: Document,
        page_index: int,
        object_ids: Sequence[str],
        dx: float,
        dy: float,
        *,
        allow_merge: bool = True,
    ) -> None:
        super().__init__(document, page_index)
        self._ids = list(object_ids)
        self._dx = dx
        self._dy = dy
        self._allow_merge = allow_merge

    def _shift(self, dx: float, dy: float) -> None:
        page = self._page
        for object_id in self._ids:
            obj = page.find_object(object_id)
            if obj is None:
                continue
            obj.rect = obj.rect.translated(dx, dy)
            if hasattr(obj, "quads") and obj.quads:
                obj.quads = [q.translated(dx, dy) for q in obj.quads]
            if hasattr(obj, "strokes") and obj.strokes:
                from orion.utils.geometry import Point

                obj.strokes = [
                    [Point(p.x + dx, p.y + dy) for p in stroke] for stroke in obj.strokes
                ]
        self._notify()

    def execute(self) -> None:
        self._shift(self._dx, self._dy)

    def undo(self) -> None:
        self._shift(-self._dx, -self._dy)

    def merge_with(self, other: Command) -> bool:
        if (
            self._allow_merge
            and isinstance(other, MoveObjectsCommand)
            and other._allow_merge
            and other._page_index == self._page_index
            and other._ids == self._ids
        ):
            self._dx += other._dx
            self._dy += other._dy
            return True
        return False


class TransformObjectsCommand(_ObjectCommand):
    """Set the geometry (rect and/or rotation) of one or more objects.

    Used for resize and rotate, where the intermediate states are already
    reflected on screen and only the before/after values need recording.
    ``allow_merge=False`` keeps two separate gestures as two undo steps.
    """

    def __init__(
        self,
        document: Document,
        page_index: int,
        before: dict[str, tuple[Rect, float]],
        after: dict[str, tuple[Rect, float]],
        *,
        text: str = "Transform",
        allow_merge: bool = True,
    ) -> None:
        super().__init__(document, page_index)
        self._before = dict(before)
        self._after = dict(after)
        self._allow_merge = allow_merge
        self.text = text

    def _apply(self, state: dict[str, tuple[Rect, float]]) -> None:
        page = self._page
        for object_id, (rect, rotation) in state.items():
            obj = page.find_object(object_id)
            if obj is None:
                continue
            obj.rect = rect
            obj.rotation = rotation
        self._notify()

    def execute(self) -> None:
        self._apply(self._after)

    def undo(self) -> None:
        self._apply(self._before)

    def merge_with(self, other: Command) -> bool:
        if (
            self._allow_merge
            and isinstance(other, TransformObjectsCommand)
            and other._allow_merge
            and other._page_index == self._page_index
            and other._before.keys() == self._after.keys()
            and other.text == self.text
        ):
            self._after = dict(other._after)
            return True
        return False


class ModifyObjectCommand(_ObjectCommand):
    """Change arbitrary properties of a single object (properties panel).

    Property edits of the *same* attribute merge, so dragging an opacity slider
    is one undo step rather than fifty.
    """

    def __init__(
        self,
        document: Document,
        page_index: int,
        object_id: str,
        changes: dict[str, Any],
        *,
        text: str | None = None,
        mergeable: bool = True,
    ) -> None:
        super().__init__(document, page_index)
        self._object_id = object_id
        self._changes = dict(changes)
        self._previous: dict[str, Any] = {}
        self._mergeable = mergeable
        self.text = text or _describe(changes)

    def execute(self) -> None:
        obj = self._page.find_object(self._object_id)
        if obj is None:
            return
        self._previous = {key: getattr(obj, key) for key in self._changes if hasattr(obj, key)}
        for key, value in self._changes.items():
            if hasattr(obj, key):
                setattr(obj, key, value)
        self._notify(self._object_id)

    def undo(self) -> None:
        obj = self._page.find_object(self._object_id)
        if obj is None:
            return
        for key, value in self._previous.items():
            setattr(obj, key, value)
        self._notify(self._object_id)

    def merge_with(self, other: Command) -> bool:
        if (
            self._mergeable
            and isinstance(other, ModifyObjectCommand)
            and other._mergeable
            and other._object_id == self._object_id
            and other._changes.keys() == self._changes.keys()
        ):
            self._changes = dict(other._changes)
            return True
        return False


class ReorderObjectCommand(_ObjectCommand):
    """Move an object within the page's z-order."""

    def __init__(
        self, document: Document, page_index: int, object_id: str, to_index: int, *, text: str
    ) -> None:
        super().__init__(document, page_index)
        self._object_id = object_id
        self._to_index = to_index
        self._from_index = -1
        self.text = text

    def execute(self) -> None:
        page = self._page
        self._from_index = page.index_of(self._object_id)
        if self._from_index < 0:
            return
        obj = page.objects.pop(self._from_index)
        page.objects.insert(max(0, min(self._to_index, len(page.objects))), obj)
        self._notify(self._object_id)

    def undo(self) -> None:
        page = self._page
        index = page.index_of(self._object_id)
        if index < 0 or self._from_index < 0:
            return
        obj = page.objects.pop(index)
        page.objects.insert(self._from_index, obj)
        self._notify(self._object_id)


class RaiseObjectCommand(ReorderObjectCommand):
    """Convenience wrapper for Bring to Front / Send to Back."""

    def __init__(
        self, document: Document, page_index: int, object_id: str, *, to_top: bool
    ) -> None:
        page = document.page_at(page_index)
        count = len(page.objects) if page else 0
        super().__init__(
            document,
            page_index,
            object_id,
            count - 1 if to_top else 0,
            text="Bring to Front" if to_top else "Send to Back",
        )


_FRIENDLY_NAMES = {
    "text": "Text",
    "font_family": "Font",
    "font_size": "Font Size",
    "bold": "Bold",
    "italic": "Italic",
    "underline": "Underline",
    "color": "Colour",
    "align": "Alignment",
    "opacity": "Opacity",
    "rotation": "Rotation",
    "stroke_color": "Stroke Colour",
    "stroke_width": "Stroke Width",
    "fill_color": "Fill Colour",
    "contents": "Comment",
    "keep_aspect": "Aspect Ratio",
    "line_spacing": "Line Spacing",
}


def _describe(changes: dict[str, Any]) -> str:
    if len(changes) == 1:
        key = next(iter(changes))
        return f"Change {_FRIENDLY_NAMES.get(key, key.replace('_', ' ').title())}"
    return "Change Properties"
