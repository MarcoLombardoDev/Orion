# Orion — PDF Editor for Desktop
# Copyright (C) 2026 Marco Lombardo
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# Distributed WITHOUT ANY WARRANTY; see LICENSE for the full terms.
# A commercial licence, without the AGPL's obligations, is available for use
# in proprietary or closed-source products — see COMMERCIAL-LICENSE.md.

"""The editing tools and the state that goes with them (spec §7, §31)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from orion.document.annotations import DEFAULT_ANNOTATION_COLORS, AnnotationKind
from orion.document.objects import Align, Color, ShapeKind

__all__ = ["Tool", "ToolState", "TOOL_INFO", "ToolInfo"]


class Tool(str, Enum):
    SELECT = "select"
    HAND = "hand"
    TEXT = "text"
    IMAGE = "image"
    RECTANGLE = "rectangle"
    ELLIPSE = "ellipse"
    LINE = "line"
    ARROW = "arrow"
    HIGHLIGHT = "highlight"
    UNDERLINE = "underline"
    STRIKEOUT = "strikeout"
    FREEHAND = "freehand"
    COMMENT = "comment"
    STICKY_NOTE = "sticky_note"
    PAGE_TEXT = "page_text"

    @property
    def is_drawing(self) -> bool:
        """True for tools that create an object by dragging out a rectangle."""
        return self in (
            Tool.TEXT,
            Tool.RECTANGLE,
            Tool.ELLIPSE,
            Tool.LINE,
            Tool.ARROW,
        )

    @property
    def is_markup(self) -> bool:
        """True for the tools that mark up existing page text."""
        return self in (Tool.HIGHLIGHT, Tool.UNDERLINE, Tool.STRIKEOUT)

    @property
    def shape_kind(self) -> ShapeKind | None:
        return {
            Tool.RECTANGLE: ShapeKind.RECTANGLE,
            Tool.ELLIPSE: ShapeKind.ELLIPSE,
            Tool.LINE: ShapeKind.LINE,
            Tool.ARROW: ShapeKind.ARROW,
        }.get(self)

    @property
    def annotation_kind(self) -> AnnotationKind | None:
        return {
            Tool.HIGHLIGHT: AnnotationKind.HIGHLIGHT,
            Tool.UNDERLINE: AnnotationKind.UNDERLINE,
            Tool.STRIKEOUT: AnnotationKind.STRIKEOUT,
            Tool.FREEHAND: AnnotationKind.INK,
            Tool.COMMENT: AnnotationKind.COMMENT,
            Tool.STICKY_NOTE: AnnotationKind.STICKY_NOTE,
        }.get(self)


@dataclass(frozen=True, slots=True)
class ToolInfo:
    label: str
    icon: str
    shortcut: str
    hint: str


TOOL_INFO: dict[Tool, ToolInfo] = {
    Tool.SELECT: ToolInfo("Select", "select", "V", "Select, move and resize objects"),
    Tool.HAND: ToolInfo("Pan", "hand", "H", "Drag to scroll the page"),
    Tool.TEXT: ToolInfo("Text", "text", "T", "Click or drag to add a text box"),
    Tool.IMAGE: ToolInfo("Image", "image", "I", "Click to place an image"),
    Tool.RECTANGLE: ToolInfo("Rectangle", "rectangle", "R", "Drag to draw a rectangle"),
    Tool.ELLIPSE: ToolInfo("Ellipse", "ellipse", "O", "Drag to draw an ellipse"),
    Tool.LINE: ToolInfo("Line", "line", "L", "Drag to draw a line"),
    Tool.ARROW: ToolInfo("Arrow", "arrow", "A", "Drag to draw an arrow"),
    Tool.HIGHLIGHT: ToolInfo("Highlight", "highlight", "", "Drag across text to highlight it"),
    Tool.UNDERLINE: ToolInfo("Underline", "underline", "", "Drag across text to underline it"),
    Tool.STRIKEOUT: ToolInfo("Strikeout", "strikeout", "", "Drag across text to strike it out"),
    Tool.FREEHAND: ToolInfo("Freehand", "freehand", "P", "Draw freely with the mouse"),
    Tool.COMMENT: ToolInfo("Comment", "comment", "", "Click to attach a comment"),
    Tool.STICKY_NOTE: ToolInfo("Sticky Note", "sticky_note", "N", "Click to place a note"),
    Tool.PAGE_TEXT: ToolInfo(
        "Edit Page Text",
        "edit_page_text",
        "E",
        "Click a line of the document's own text to rewrite it",
    ),
}


@dataclass
class ToolState:
    """Default properties new objects are created with.

    Keeping these on one object means the toolbar, the properties panel and the
    canvas all read and write the same defaults, and a user's last choice of
    colour or font carries over to the next object they draw.
    """

    tool: Tool = Tool.SELECT

    # Text
    font_family: str = "Helvetica"
    font_size: float = 12.0
    bold: bool = False
    italic: bool = False
    underline: bool = False
    text_color: Color = (0.0, 0.0, 0.0)
    align: Align = Align.LEFT

    # Shapes
    stroke_color: Color | None = (0.85, 0.15, 0.15)
    stroke_width: float = 1.5
    fill_color: Color | None = None

    # Annotations
    annotation_colors: dict[AnnotationKind, Color] = field(
        default_factory=lambda: dict(DEFAULT_ANNOTATION_COLORS)
    )
    ink_width: float = 2.0
    author: str = ""

    opacity: float = 1.0

    def color_for(self, kind: AnnotationKind) -> Color:
        return self.annotation_colors.get(kind, DEFAULT_ANNOTATION_COLORS[kind])
