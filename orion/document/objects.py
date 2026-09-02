# Orion — PDF Editor for Desktop
# Copyright (C) 2026 Marco Lombardo
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# Distributed WITHOUT ANY WARRANTY; see LICENSE for the full terms.
# A commercial licence, without the AGPL's obligations, is available for use
# in proprietary or closed-source products — see COMMERCIAL-LICENSE.md.

"""Objects the user adds on top of a PDF page.

Every object lives in **base page space**: points, origin at the page's
top-left as the *source* PDF displays it, y growing downwards.  Orion's own
page rotation is applied by the canvas and by the writer, never by rewriting
object coordinates — see ``docs/ARCHITECTURE.md`` §3.

``rect`` is the object's *unrotated* bounding box; ``rotation`` spins it
clockwise around that rectangle's centre.
"""

from __future__ import annotations

import base64
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any, ClassVar

from orion.utils.geometry import Point, Rect, Size, rotated_bounds

__all__ = [
    "Align",
    "Color",
    "ObjectKind",
    "PageObject",
    "TextObject",
    "ImageObject",
    "ShapeKind",
    "ShapeObject",
    "create_object",
    "RedactionObject",
    "register_object_type",
    "new_object_id",
    "MIN_OBJECT_SIZE",
]

#: Objects may not be resized below this (points) — smaller is unselectable.
MIN_OBJECT_SIZE = 4.0

#: RGB in the 0..1 range, matching the PDF specification.
Color = tuple[float, float, float]

BLACK: Color = (0.0, 0.0, 0.0)
WHITE: Color = (1.0, 1.0, 1.0)


def new_object_id() -> str:
    return uuid.uuid4().hex


class ObjectKind(str, Enum):
    TEXT = "text"
    IMAGE = "image"
    SHAPE = "shape"
    ANNOTATION = "annotation"
    REDACTION = "redaction"


class Align(str, Enum):
    LEFT = "left"
    CENTER = "center"
    RIGHT = "right"
    JUSTIFY = "justify"


class ShapeKind(str, Enum):
    RECTANGLE = "rectangle"
    ELLIPSE = "ellipse"
    LINE = "line"
    ARROW = "arrow"

    @property
    def is_linear(self) -> bool:
        return self in (ShapeKind.LINE, ShapeKind.ARROW)


# --------------------------------------------------------------------------
# Base
# --------------------------------------------------------------------------
@dataclass
class PageObject:
    """Base class for everything Orion can place on a page."""

    #: Discriminator used by (de)serialisation; overridden by every subclass.
    kind: ClassVar[ObjectKind] = ObjectKind.SHAPE

    rect: Rect = field(default_factory=Rect)
    rotation: float = 0.0
    opacity: float = 1.0
    locked: bool = False
    id: str = field(default_factory=new_object_id)

    # -- geometry --------------------------------------------------------
    @property
    def center(self) -> Point:
        return self.rect.center

    @property
    def size(self) -> Size:
        return self.rect.size

    @property
    def visual_bounds(self) -> Rect:
        """Axis-aligned bounds including this object's own rotation."""
        return rotated_bounds(self.rect, self.rotation)

    def moved_by(self, dx: float, dy: float) -> PageObject:
        return self.with_changes(rect=self.rect.translated(dx, dy))

    def with_changes(self, **changes: Any) -> PageObject:
        """Return a copy with *changes* applied (dataclasses.replace)."""
        return replace(self, **changes)

    # -- identity --------------------------------------------------------
    def clone(self, *, new_id: bool = True, offset: tuple[float, float] = (0.0, 0.0)) -> PageObject:
        copy = replace(self, id=new_object_id() if new_id else self.id)
        if offset != (0.0, 0.0):
            copy.rect = copy.rect.translated(*offset)
        return copy

    @property
    def display_name(self) -> str:
        return self.kind.value.capitalize()

    # -- serialisation ---------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "kind": self.kind.value,
            "id": self.id,
            "rect": list(self.rect.as_tuple()),
            "rotation": self.rotation,
            "opacity": self.opacity,
            "locked": self.locked,
        }
        data.update(self._payload())
        return data

    def _payload(self) -> dict[str, Any]:
        return {}

    @classmethod
    def _base_kwargs(cls, data: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": data.get("id") or new_object_id(),
            "rect": Rect.from_tuple(data.get("rect", (0, 0, 0, 0))),
            "rotation": float(data.get("rotation", 0.0)),
            "opacity": float(data.get("opacity", 1.0)),
            "locked": bool(data.get("locked", False)),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PageObject:
        return cls(**cls._base_kwargs(data))


# --------------------------------------------------------------------------
# Text
# --------------------------------------------------------------------------
#: The 14 fonts every PDF reader is required to provide.  Restricting V1 to
#: these guarantees the on-screen text and the written PDF text agree without
#: embedding font files.  TTF embedding is a documented follow-up.
#: The three families that need no embedding. Kept here as well as in
#: :mod:`orion.pdf.fonts` because the model must not depend on the PDF layer,
#: and because "which families are built in" is a fact about the file format
#: rather than about this machine's fonts.
BASE14_FAMILIES: tuple[str, ...] = ("Helvetica", "Times", "Courier")

#: family -> (regular, bold, italic, bold-italic) base-14 font identifiers.
#: These are stored in saved documents, so they are part of the file format and
#: cannot be renamed; orion/pdf/fonts.py maps them to the names the writer
#: draws with.
BASE14_MAP: dict[str, tuple[str, str, str, str]] = {
    "Helvetica": ("helv", "hebo", "heit", "hebi"),
    "Times": ("tiro", "tibo", "tiit", "tibi"),
    "Courier": ("cour", "cobo", "coit", "cobi"),
}


@dataclass
class TextObject(PageObject):
    """A text box added by the user; written as real, searchable PDF text."""

    kind: ClassVar[ObjectKind] = ObjectKind.TEXT

    text: str = ""
    font_family: str = "Helvetica"
    font_size: float = 12.0
    bold: bool = False
    italic: bool = False
    underline: bool = False
    color: Color = BLACK
    align: Align = Align.LEFT
    line_spacing: float = 1.2

    @property
    def base14_name(self) -> str:
        """Base-14 font identifier for this style combination."""
        regular, bold, italic, bold_italic = BASE14_MAP.get(
            self.font_family, BASE14_MAP["Helvetica"]
        )
        if self.bold and self.italic:
            return bold_italic
        if self.bold:
            return bold
        if self.italic:
            return italic
        return regular

    @property
    def display_name(self) -> str:
        snippet = self.text.strip().splitlines()[0] if self.text.strip() else "Empty"
        return f"Text — {snippet[:24]}"

    def _payload(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "font_family": self.font_family,
            "font_size": self.font_size,
            "bold": self.bold,
            "italic": self.italic,
            "underline": self.underline,
            "color": list(self.color),
            "align": self.align.value,
            "line_spacing": self.line_spacing,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TextObject:
        return cls(
            **cls._base_kwargs(data),
            text=data.get("text", ""),
            font_family=data.get("font_family", "Helvetica"),
            font_size=float(data.get("font_size", 12.0)),
            bold=bool(data.get("bold", False)),
            italic=bool(data.get("italic", False)),
            underline=bool(data.get("underline", False)),
            color=tuple(data.get("color", BLACK)),  # type: ignore[arg-type]
            align=Align(data.get("align", "left")),
            line_spacing=float(data.get("line_spacing", 1.2)),
        )


# --------------------------------------------------------------------------
# Image
# --------------------------------------------------------------------------
@dataclass
class ImageObject(PageObject):
    """A raster image.

    The *encoded* source bytes are kept in the model so copy/paste, autosave
    and save-to-PDF never depend on the original file still being there.
    """

    kind: ClassVar[ObjectKind] = ObjectKind.IMAGE

    data: bytes = b""
    image_format: str = "png"
    natural_size: Size = field(default_factory=lambda: Size(1.0, 1.0))
    keep_aspect: bool = True
    source_name: str = ""

    @property
    def display_name(self) -> str:
        return f"Image — {self.source_name}" if self.source_name else "Image"

    def size_for_aspect(self, width: float | None = None, height: float | None = None) -> Size:
        """Complete a width/height pair using the image's natural aspect ratio."""
        aspect = self.natural_size.aspect or 1.0
        if width is not None and height is None:
            return Size(width, width / aspect)
        if height is not None and width is None:
            return Size(height * aspect, height)
        if width is not None and height is not None:
            return Size(width, height)
        return self.natural_size

    def _payload(self) -> dict[str, Any]:
        return {
            "data": base64.b64encode(self.data).decode("ascii"),
            "image_format": self.image_format,
            "natural_size": list(self.natural_size.as_tuple()),
            "keep_aspect": self.keep_aspect,
            "source_name": self.source_name,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ImageObject:
        raw = data.get("data", "")
        return cls(
            **cls._base_kwargs(data),
            data=base64.b64decode(raw) if raw else b"",
            image_format=data.get("image_format", "png"),
            natural_size=Size.from_tuple(data.get("natural_size", (1.0, 1.0))),
            keep_aspect=bool(data.get("keep_aspect", True)),
            source_name=data.get("source_name", ""),
        )


# --------------------------------------------------------------------------
# Shapes
# --------------------------------------------------------------------------
@dataclass
class ShapeObject(PageObject):
    """Rectangle, ellipse, line or arrow.

    Lines and arrows store their endpoints as *normalised fractions* of
    ``rect`` (default: top-left to bottom-right).  That way a line can point in
    any direction while still using the generic rect-based move/resize/rotate
    machinery — no special case anywhere else in the codebase.
    """

    kind: ClassVar[ObjectKind] = ObjectKind.SHAPE

    shape: ShapeKind = ShapeKind.RECTANGLE
    stroke_color: Color | None = BLACK
    stroke_width: float = 1.5
    fill_color: Color | None = None
    line_start: tuple[float, float] = (0.0, 0.0)
    line_end: tuple[float, float] = (1.0, 1.0)
    arrow_size: float = 4.0

    @property
    def display_name(self) -> str:
        return self.shape.value.capitalize()

    def start_point(self) -> Point:
        return self.rect.lerp_point(*self.line_start)

    def end_point(self) -> Point:
        return self.rect.lerp_point(*self.line_end)

    def _payload(self) -> dict[str, Any]:
        return {
            "shape": self.shape.value,
            "stroke_color": list(self.stroke_color) if self.stroke_color else None,
            "stroke_width": self.stroke_width,
            "fill_color": list(self.fill_color) if self.fill_color else None,
            "line_start": list(self.line_start),
            "line_end": list(self.line_end),
            "arrow_size": self.arrow_size,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ShapeObject:
        stroke = data.get("stroke_color", list(BLACK))
        fill = data.get("fill_color")
        return cls(
            **cls._base_kwargs(data),
            shape=ShapeKind(data.get("shape", "rectangle")),
            stroke_color=tuple(stroke) if stroke else None,  # type: ignore[arg-type]
            stroke_width=float(data.get("stroke_width", 1.5)),
            fill_color=tuple(fill) if fill else None,  # type: ignore[arg-type]
            line_start=tuple(data.get("line_start", (0.0, 0.0))),  # type: ignore[arg-type]
            line_end=tuple(data.get("line_end", (1.0, 1.0))),  # type: ignore[arg-type]
            arrow_size=float(data.get("arrow_size", 4.0)),
        )


# --------------------------------------------------------------------------
# Registry
# --------------------------------------------------------------------------
_REGISTRY: dict[str, Callable[[dict[str, Any]], PageObject]] = {}


@dataclass
class RedactionObject(PageObject):
    """An area whose content is **removed** from the saved file.

    A black rectangle drawn over a name hides nothing: the words are still in
    the file, still selectable, still found by search, and one copy-and-paste
    away from whoever was not supposed to read them. This is the object that
    means it. On the canvas it is a box like any other — selectable, movable,
    undoable — and at save time the writer deletes every drawing operation it
    covers before painting the box on top.

    ``fill_color`` is what gets painted where the content was. Black by
    convention; white is the other useful answer, for taking something out
    without announcing that anything was there.
    """

    kind: ClassVar[ObjectKind] = ObjectKind.REDACTION

    fill_color: Color = BLACK

    @property
    def display_name(self) -> str:
        return "Redaction"

    def _payload(self) -> dict[str, Any]:
        return {"fill_color": list(self.fill_color)}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RedactionObject:
        return cls(
            **cls._base_kwargs(data),
            fill_color=tuple(data.get("fill_color", BLACK)),  # type: ignore[arg-type]
        )


def register_object_type(kind: ObjectKind, factory: Callable[[dict[str, Any]], PageObject]) -> None:
    """Register a deserialiser.  New object types plug in here (spec §2, §36)."""
    _REGISTRY[kind.value] = factory


def create_object(data: dict[str, Any]) -> PageObject:
    """Rebuild a :class:`PageObject` from its serialised form."""
    kind = data.get("kind")
    factory = _REGISTRY.get(kind or "")
    if factory is None:
        raise ValueError(f"Unknown object kind: {kind!r}")
    return factory(data)


register_object_type(ObjectKind.TEXT, TextObject.from_dict)
register_object_type(ObjectKind.IMAGE, ImageObject.from_dict)
register_object_type(ObjectKind.SHAPE, ShapeObject.from_dict)


register_object_type(ObjectKind.REDACTION, RedactionObject.from_dict)
