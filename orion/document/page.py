"""A single page of the working document."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from orion.document.objects import PageObject, create_object
from orion.utils.geometry import Point, Rect, Size, rotate_point

__all__ = ["Page", "PageSource", "normalise_rotation"]


def normalise_rotation(degrees: int) -> int:
    """Snap an arbitrary integer to one of 0/90/180/270."""
    return int(round(degrees / 90.0)) * 90 % 360


@dataclass(frozen=True, slots=True)
class PageSource:
    """Where a page's original content comes from.

    ``source_key`` identifies a :class:`~orion.document.document.DocumentSource`;
    ``index`` is the 0-based page number inside it.  Pages imported from another
    PDF keep pointing at that other file until the document is saved, so nothing
    is copied or rewritten until the user asks for it.
    """

    source_key: str
    index: int

    def as_tuple(self) -> tuple[str, int]:
        return (self.source_key, self.index)


@dataclass
class Page:
    """One page: original content (or blank) plus the objects Orion adds.

    ``base_size`` is the page size *as the source PDF displays it*, i.e. with
    the source file's own ``/Rotate`` already applied.  ``rotation`` is the
    extra rotation Orion applies on top; objects are stored in base space so
    rotating a page is an O(1) metadata change and objects stay attached to the
    content they annotate.
    """

    base_size: Size = field(default_factory=lambda: Size(595.0, 842.0))
    source: PageSource | None = None
    rotation: int = 0
    objects: list[PageObject] = field(default_factory=list)
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    #: Rotation the source page already had, needed by the writer to convert
    #: base-space coordinates into PDF content space.
    source_rotation: int = 0
    label: str = ""

    # -- geometry --------------------------------------------------------
    @property
    def is_blank(self) -> bool:
        return self.source is None

    @property
    def display_size(self) -> Size:
        """Page size as the user sees it, with Orion's rotation applied."""
        return self.base_size.swapped() if self.rotation % 180 else self.base_size

    @property
    def base_rect(self) -> Rect:
        return Rect.from_xywh(0.0, 0.0, self.base_size.width, self.base_size.height)

    @property
    def display_rect(self) -> Rect:
        size = self.display_size
        return Rect.from_xywh(0.0, 0.0, size.width, size.height)

    @property
    def total_rotation(self) -> int:
        """Rotation the final PDF page will carry."""
        return normalise_rotation(self.source_rotation + self.rotation)

    def base_to_display(self, point: Point) -> Point:
        """Map a point from base page space to the rotated display space."""
        rot = self.rotation % 360
        w, h = self.base_size.width, self.base_size.height
        if rot == 90:
            return Point(h - point.y, point.x)
        if rot == 180:
            return Point(w - point.x, h - point.y)
        if rot == 270:
            return Point(point.y, w - point.x)
        return point

    def display_to_base(self, point: Point) -> Point:
        """Inverse of :meth:`base_to_display`."""
        rot = self.rotation % 360
        w, h = self.base_size.width, self.base_size.height
        if rot == 90:
            return Point(point.y, h - point.x)
        if rot == 180:
            return Point(w - point.x, h - point.y)
        if rot == 270:
            return Point(w - point.y, point.x)
        return point

    def base_rect_to_display(self, rect: Rect) -> Rect:
        return Rect.from_points(self.base_to_display(c) for c in rect.corners)

    def display_rect_to_base(self, rect: Rect) -> Rect:
        return Rect.from_points(self.display_to_base(c) for c in rect.corners)

    def rotate(self, delta: int) -> None:
        self.rotation = normalise_rotation(self.rotation + delta)

    # -- objects ---------------------------------------------------------
    def __iter__(self) -> Iterator[PageObject]:
        return iter(self.objects)

    def __len__(self) -> int:
        return len(self.objects)

    def add_object(self, obj: PageObject, index: int | None = None) -> int:
        position = len(self.objects) if index is None else max(0, min(index, len(self.objects)))
        self.objects.insert(position, obj)
        return position

    def remove_object(self, obj_id: str) -> tuple[PageObject, int] | None:
        for index, obj in enumerate(self.objects):
            if obj.id == obj_id:
                return self.objects.pop(index), index
        return None

    def find_object(self, obj_id: str) -> PageObject | None:
        for obj in self.objects:
            if obj.id == obj_id:
                return obj
        return None

    def index_of(self, obj_id: str) -> int:
        for index, obj in enumerate(self.objects):
            if obj.id == obj_id:
                return index
        return -1

    def replace_object(self, obj: PageObject) -> PageObject | None:
        index = self.index_of(obj.id)
        if index < 0:
            return None
        previous = self.objects[index]
        self.objects[index] = obj
        return previous

    def raise_object(self, obj_id: str, to_top: bool = False) -> bool:
        index = self.index_of(obj_id)
        if index < 0 or index == len(self.objects) - 1:
            return False
        obj = self.objects.pop(index)
        self.objects.append(obj) if to_top else self.objects.insert(index + 1, obj)
        return True

    def lower_object(self, obj_id: str, to_bottom: bool = False) -> bool:
        index = self.index_of(obj_id)
        if index <= 0:
            return False
        obj = self.objects.pop(index)
        self.objects.insert(0 if to_bottom else index - 1, obj)
        return True

    def objects_in(self, rect: Rect) -> list[PageObject]:
        return [obj for obj in self.objects if obj.visual_bounds.intersects(rect)]

    def object_at(self, point: Point) -> PageObject | None:
        """Topmost object whose (rotation-aware) area contains *point*."""
        for obj in reversed(self.objects):
            local = rotate_point(point, obj.rect.center, -obj.rotation)
            if obj.rect.contains_point(local):
                return obj
        return None

    # -- copying ---------------------------------------------------------
    def duplicate(self) -> Page:
        """A deep copy that shares the same source page but has fresh ids."""
        return Page(
            base_size=self.base_size,
            source=self.source,
            rotation=self.rotation,
            objects=[obj.clone() for obj in self.objects],
            source_rotation=self.source_rotation,
            label=self.label,
        )

    # -- serialisation ---------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "base_size": list(self.base_size.as_tuple()),
            "source": list(self.source.as_tuple()) if self.source else None,
            "rotation": self.rotation,
            "source_rotation": self.source_rotation,
            "label": self.label,
            "objects": [obj.to_dict() for obj in self.objects],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Page:
        source = data.get("source")
        return cls(
            id=data.get("id") or uuid.uuid4().hex,
            base_size=Size.from_tuple(data.get("base_size", (595.0, 842.0))),
            source=PageSource(str(source[0]), int(source[1])) if source else None,
            rotation=normalise_rotation(int(data.get("rotation", 0))),
            source_rotation=normalise_rotation(int(data.get("source_rotation", 0))),
            label=data.get("label", ""),
            objects=[create_object(item) for item in data.get("objects", [])],
        )


def blank_page(size: Size | None = None) -> Page:
    """Create an empty page (defaults to A4)."""
    return Page(base_size=size or Size(595.0, 842.0))
