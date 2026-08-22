"""Annotation objects (spec §12).

Annotations are modelled separately from content objects because they are
written as **real PDF annotations** (``/Highlight``, ``/Underline``,
``/StrikeOut``, ``/Ink``, ``/Text``), so any other PDF reader shows them
natively and can toggle them.  Content objects (text/image/shape) instead
become page content streams.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, ClassVar

from orion.document.objects import (
    Color,
    ObjectKind,
    PageObject,
    register_object_type,
)
from orion.utils.geometry import Point, Rect

__all__ = ["AnnotationKind", "AnnotationObject", "InkStroke", "DEFAULT_ANNOTATION_COLORS"]

#: A freehand stroke: an ordered polyline in base page space.
InkStroke = list[Point]


class AnnotationKind(str, Enum):
    HIGHLIGHT = "highlight"
    UNDERLINE = "underline"
    STRIKEOUT = "strikeout"
    INK = "ink"
    COMMENT = "comment"
    STICKY_NOTE = "sticky_note"

    @property
    def is_text_markup(self) -> bool:
        """True for the three annotations that mark up existing page text."""
        return self in (
            AnnotationKind.HIGHLIGHT,
            AnnotationKind.UNDERLINE,
            AnnotationKind.STRIKEOUT,
        )

    @property
    def is_note(self) -> bool:
        return self in (AnnotationKind.COMMENT, AnnotationKind.STICKY_NOTE)


DEFAULT_ANNOTATION_COLORS: dict[AnnotationKind, Color] = {
    AnnotationKind.HIGHLIGHT: (1.0, 0.92, 0.23),
    AnnotationKind.UNDERLINE: (0.13, 0.55, 0.95),
    AnnotationKind.STRIKEOUT: (0.90, 0.22, 0.21),
    AnnotationKind.INK: (0.90, 0.22, 0.21),
    AnnotationKind.COMMENT: (1.0, 0.80, 0.20),
    AnnotationKind.STICKY_NOTE: (1.0, 0.80, 0.20),
}

#: On-page footprint of a note icon, in points.
NOTE_ICON_SIZE = 20.0


@dataclass
class AnnotationObject(PageObject):
    """Highlight, underline, strikeout, freehand ink, comment or sticky note."""

    kind: ClassVar[ObjectKind] = ObjectKind.ANNOTATION

    annotation: AnnotationKind = AnnotationKind.HIGHLIGHT
    color: Color = (1.0, 0.92, 0.23)
    #: One rectangle per marked-up text line (text-markup kinds only).
    quads: list[Rect] = field(default_factory=list)
    #: One polyline per pen-down..pen-up gesture (ink only).
    strokes: list[InkStroke] = field(default_factory=list)
    stroke_width: float = 1.5
    contents: str = ""
    author: str = ""
    #: Text markup annotations are not freely rotatable in the PDF spec, so
    #: Orion keeps them axis-aligned; ink and notes honour ``rotation``.
    ROTATABLE_KINDS: ClassVar[frozenset[AnnotationKind]] = frozenset(
        {AnnotationKind.INK, AnnotationKind.COMMENT, AnnotationKind.STICKY_NOTE}
    )

    @property
    def can_rotate(self) -> bool:
        return self.annotation in self.ROTATABLE_KINDS

    @property
    def can_resize(self) -> bool:
        """Text markup follows the text it marks; notes have a fixed icon size."""
        return self.annotation == AnnotationKind.INK

    @property
    def display_name(self) -> str:
        label = self.annotation.value.replace("_", " ").title()
        if self.contents:
            return f"{label} — {self.contents.splitlines()[0][:24]}"
        return label

    def clone(
        self, *, new_id: bool = True, offset: tuple[float, float] = (0.0, 0.0)
    ) -> AnnotationObject:
        copy = super().clone(new_id=new_id, offset=offset)
        assert isinstance(copy, AnnotationObject)
        # Deep-copy the mutable geometry so the clone is truly independent.
        dx, dy = offset
        copy.quads = [q.translated(dx, dy) for q in self.quads]
        copy.strokes = [[Point(p.x + dx, p.y + dy) for p in s] for s in self.strokes]
        return copy

    def recompute_rect(self) -> Rect:
        """Derive ``rect`` from the annotation's own geometry."""
        if self.quads:
            rect = self.quads[0]
            for quad in self.quads[1:]:
                rect = rect.united(quad)
            return rect
        if self.strokes:
            points = [p for stroke in self.strokes for p in stroke]
            if points:
                return Rect.from_points(points).expanded(self.stroke_width)
        return self.rect

    def _payload(self) -> dict[str, Any]:
        return {
            "annotation": self.annotation.value,
            "color": list(self.color),
            "quads": [list(q.as_tuple()) for q in self.quads],
            "strokes": [[list(p.as_tuple()) for p in stroke] for stroke in self.strokes],
            "stroke_width": self.stroke_width,
            "contents": self.contents,
            "author": self.author,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AnnotationObject:
        return cls(
            **cls._base_kwargs(data),
            annotation=AnnotationKind(data.get("annotation", "highlight")),
            color=tuple(data.get("color", (1.0, 0.92, 0.23))),  # type: ignore[arg-type]
            quads=[Rect.from_tuple(q) for q in data.get("quads", [])],
            strokes=[[Point.from_tuple(p) for p in s] for s in data.get("strokes", [])],
            stroke_width=float(data.get("stroke_width", 1.5)),
            contents=data.get("contents", ""),
            author=data.get("author", ""),
        )


register_object_type(ObjectKind.ANNOTATION, AnnotationObject.from_dict)
