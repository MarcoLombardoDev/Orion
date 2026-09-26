# Orion — PDF Editor for Desktop
# Copyright (C) 2026 Marco Lombardo
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# Distributed WITHOUT ANY WARRANTY; see LICENSE for the full terms.
# A commercial licence, without the AGPL's obligations, is available for use
# in proprietary or closed-source products — see COMMERCIAL-LICENSE.md.

"""The form fields already in a PDF, as objects the user can move.

A widget is the one thing on a page that every PDF editor draws and none of
them lets you touch. Orion imported annotations for exactly this reason — an
object you can see and not select is scenery — and a form field was still
scenery: converting an XFA form produced a document whose fields were in the
places the *template* put them, and no way to nudge one that came out a
millimetre off.

So a widget becomes one of these. It is deliberately a thin record: the
field's identity and enough of its look to draw it, plus ``source_index``,
which is where it sits in the page's ``/Annots``. The writer uses that to find
the real widget dictionary and move it, rather than building a new one — which
is what keeps the field's options, flags, tooltip, default appearance and
everything else Orion does not model. Moving a field must not cost it the
things that make it a field.

What is not here is the value. Orion draws it so the page looks right, and
writes it back untouched: changing a field's contents is filling the form in,
which is a feature of its own and not a side effect of dragging a box.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, ClassVar

from orion.document.objects import (
    BLACK,
    Color,
    ObjectKind,
    PageObject,
    register_object_type,
)

__all__ = ["FormFieldKind", "FormFieldObject"]


class FormFieldKind(str, Enum):
    """What the field is, as far as drawing it goes."""

    TEXT = "text"
    CHECKBOX = "checkbox"
    RADIO = "radio"
    CHOICE = "choice"
    BUTTON = "button"
    SIGNATURE = "signature"
    UNKNOWN = "unknown"

    @property
    def label(self) -> str:
        return {
            FormFieldKind.TEXT: "Text field",
            FormFieldKind.CHECKBOX: "Tick box",
            FormFieldKind.RADIO: "Option button",
            FormFieldKind.CHOICE: "Drop-down",
            FormFieldKind.BUTTON: "Button",
            FormFieldKind.SIGNATURE: "Signature field",
            FormFieldKind.UNKNOWN: "Form field",
        }[self]


@dataclass
class FormFieldObject(PageObject):
    """One form field of the open document, in Orion's own coordinates."""

    kind: ClassVar[ObjectKind] = ObjectKind.FORM_FIELD

    field_kind: FormFieldKind = FormFieldKind.TEXT
    #: The field's full name — the one the PDF stores, so two fields that
    #: differ only by their parent are still told apart.
    name: str = ""
    value: str = ""
    #: What a drop-down offers. Drawn only as a marker; kept for the panel.
    options: tuple[str, ...] = ()
    read_only: bool = False
    required: bool = False
    multiline: bool = False
    #: ``/Q``: 0 left, 1 centred, 2 right — where the value sits across.
    alignment: int = 0
    checked: bool = False
    font_size: float = 10.0
    text_color: Color = BLACK
    border_color: Color | None = None
    fill_color: Color | None = None
    border_width: float = 1.0
    tooltip: str = ""
    #: Where this widget sits in its page's ``/Annots``. -1 for a field that
    #: did not come from a file.
    source_index: int = -1

    @property
    def display_name(self) -> str:
        if self.name:
            return f"{self.field_kind.label} — {self.name.rsplit('.', 1)[-1]}"
        return self.field_kind.label

    @property
    def can_rotate(self) -> bool:
        """No. A widget's rectangle is axis-aligned by the file format."""
        return False

    def _payload(self) -> dict[str, Any]:
        return {
            "field_kind": self.field_kind.value,
            "name": self.name,
            "value": self.value,
            "options": list(self.options),
            "read_only": self.read_only,
            "required": self.required,
            "multiline": self.multiline,
            "alignment": self.alignment,
            "checked": self.checked,
            "font_size": self.font_size,
            "text_color": list(self.text_color),
            "border_color": list(self.border_color) if self.border_color else None,
            "fill_color": list(self.fill_color) if self.fill_color else None,
            "border_width": self.border_width,
            "tooltip": self.tooltip,
            "source_index": self.source_index,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FormFieldObject:
        border = data.get("border_color")
        fill = data.get("fill_color")
        return cls(
            **cls._base_kwargs(data),
            field_kind=FormFieldKind(data.get("field_kind", "text")),
            name=str(data.get("name", "")),
            value=str(data.get("value", "")),
            options=tuple(str(option) for option in data.get("options", ())),
            read_only=bool(data.get("read_only", False)),
            required=bool(data.get("required", False)),
            multiline=bool(data.get("multiline", False)),
            alignment=int(data.get("alignment", 0)),
            checked=bool(data.get("checked", False)),
            font_size=float(data.get("font_size", 10.0)),
            text_color=tuple(data.get("text_color", BLACK)),  # type: ignore[arg-type]
            border_color=tuple(border) if border else None,  # type: ignore[arg-type]
            fill_color=tuple(fill) if fill else None,  # type: ignore[arg-type]
            border_width=float(data.get("border_width", 1.0)),
            tooltip=str(data.get("tooltip", "")),
            source_index=int(data.get("source_index", -1)),
        )


register_object_type(ObjectKind.FORM_FIELD, FormFieldObject.from_dict)
