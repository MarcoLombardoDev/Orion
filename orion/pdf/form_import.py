# Orion — PDF Editor for Desktop
# Copyright (C) 2026 Marco Lombardo
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# Distributed WITHOUT ANY WARRANTY; see LICENSE for the full terms.
# A commercial licence, without the AGPL's obligations, is available for use
# in proprietary or closed-source products — see COMMERCIAL-LICENSE.md.

"""Reading a PDF's form fields into the document model.

The mirror of :mod:`orion.pdf.annotation_import`, for the one annotation kind
that is not really an annotation. A widget carries a field dictionary — its
name, type, value, flags, options, default appearance — and Orion models none
of that beyond what it takes to draw the thing and name it in a panel. What it
does take is :attr:`~orion.document.forms.FormFieldObject.source_index`, and
the writer then moves the *original* dictionary rather than composing a new
one. A field that survives being dragged across the page with its options and
its tooltip intact is a field; one rebuilt from the four properties Orion
understands is a box.

A field's name may be split across a parent chain — ``/T`` on the parent, the
partial name on the widget — so the full name is assembled the way a reader
assembles it. Fields whose type is only on the parent are read the same way.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from orion.document.forms import FormFieldKind, FormFieldObject
from orion.pdf.coordinates import PageGeometry, from_pdf_rect

log = logging.getLogger(__name__)

__all__ = ["ImportedFields", "import_form_fields"]

#: ``/FT`` -> what Orion draws. ``/Btn`` splits three ways on its flags.
_FIELD_TYPES = {
    "/Tx": FormFieldKind.TEXT,
    "/Ch": FormFieldKind.CHOICE,
    "/Sig": FormFieldKind.SIGNATURE,
}

#: Bits of ``/Ff`` this module reads, from the PDF specification's table.
_READ_ONLY = 1
_REQUIRED = 2
_MULTILINE = 4096
_RADIO = 32768
_PUSHBUTTON = 65536


@dataclass(slots=True)
class ImportedFields:
    """What one page's form gave up."""

    objects: list[FormFieldObject] = field(default_factory=list)
    #: Indices into the page's ``/Annots`` these objects stand for.
    indices: tuple[int, ...] = ()


def import_form_fields(pdf_page, geometry: PageGeometry) -> ImportedFields:
    """Read the widgets of one page into base page space."""
    try:
        annots = pdf_page.get("/Annots")
    except Exception:  # pragma: no cover - a damaged page dictionary
        log.debug("Could not read /Annots", exc_info=True)
        return ImportedFields()
    if not annots:
        return ImportedFields()

    objects: list[FormFieldObject] = []
    indices: list[int] = []
    for index, reference in enumerate(annots):
        try:
            entry = reference.get_object()
            if str(entry.get("/Subtype", "")) != "/Widget":
                continue
            if int(entry.get("/F", 0) or 0) & _HIDDEN_FLAG:
                # A widget the document itself hides — a converted XFA field a
                # script had hidden, kept only for its value. Left in the file
                # untouched rather than turned into an object nobody can see.
                continue
            obj = _build(entry, geometry, index)
        except Exception:
            # One unreadable widget must not stop a document opening, and not
            # importing it also leaves it in the file exactly as it was.
            log.warning("Skipping an unreadable form field", exc_info=True)
            continue
        if obj is None:
            continue
        objects.append(obj)
        indices.append(index)

    return ImportedFields(objects=objects, indices=tuple(indices))


def _quadding(entry) -> int:
    """``/Q``, inherited like the rest, clamped to the three values it has."""
    try:
        value = int(_inherited(entry, "/Q") or 0)
    except (TypeError, ValueError):
        return 0
    return value if value in (0, 1, 2) else 0


#: PDF annotation flag bit 2: "do not display or print".
_HIDDEN_FLAG = 2


def _inherited(entry, key: str, depth: int = 0):
    """*key* from this widget or, failing that, from its parent field.

    A widget with several siblings — the members of a radio group — keeps the
    shared half of its definition on a parent, so reading only the widget
    gives a field with no type and no name.
    """
    if key in entry:
        return entry[key]
    parent = entry.get("/Parent")
    if parent is None or depth > 8:
        return None
    try:
        return _inherited(parent.get_object(), key, depth + 1)
    except Exception:  # pragma: no cover - a broken parent chain
        return None


def _full_name(entry, depth: int = 0) -> str:
    """The field's name with its parents' in front, dot-separated."""
    own = entry.get("/T")
    parent = entry.get("/Parent")
    above = ""
    if parent is not None and depth <= 8:
        try:
            above = _full_name(parent.get_object(), depth + 1)
        except Exception:  # pragma: no cover - a broken parent chain
            above = ""
    if own is None:
        return above
    return f"{above}.{own}" if above else str(own)


def _kind(entry) -> FormFieldKind:
    field_type = str(_inherited(entry, "/FT") or "")
    if field_type == "/Btn":
        flags = int(_inherited(entry, "/Ff") or 0)
        if flags & _PUSHBUTTON:
            return FormFieldKind.BUTTON
        return FormFieldKind.RADIO if flags & _RADIO else FormFieldKind.CHECKBOX
    return _FIELD_TYPES.get(field_type, FormFieldKind.UNKNOWN)


def _colour(look, key: str):
    """``/MK`` colours are 0, 1, 3 or 4 numbers: none, grey, RGB or CMYK."""
    try:
        components = [float(v) for v in (look.get(key) or [])]
    except Exception:  # pragma: no cover - defensive
        return None
    if len(components) == 1:
        grey = components[0]
        return (grey, grey, grey)
    if len(components) == 3:
        return (components[0], components[1], components[2])
    if len(components) == 4:
        cyan, magenta, yellow, black = components
        return (
            (1.0 - min(1.0, cyan + black)),
            (1.0 - min(1.0, magenta + black)),
            (1.0 - min(1.0, yellow + black)),
        )
    return None


def _font_size(entry) -> float:
    """The size out of ``/DA`` — ``/Helv 9 Tf 0 g``.

    Zero means "fit the box", which the specification allows and which Orion
    turns into something it can actually draw with.
    """
    appearance = str(_inherited(entry, "/DA") or "")
    parts = appearance.split()
    for position, token in enumerate(parts):
        if token == "Tf" and position >= 1:
            try:
                size = float(parts[position - 1])
            except ValueError:
                break
            return size if size > 0 else 0.0
    return 0.0


def _value(entry) -> str:
    raw = _inherited(entry, "/V")
    if raw is None:
        return ""
    text = str(raw)
    return "" if text in ("/Off", "None") else text.lstrip("/")


def _build(entry, geometry: PageGeometry, index: int) -> FormFieldObject | None:
    rectangle = entry.get("/Rect")
    if not rectangle or len(rectangle) != 4:
        return None
    rect = from_pdf_rect(geometry, [float(v) for v in rectangle])
    if rect.width <= 0 or rect.height <= 0:
        return None

    flags = int(_inherited(entry, "/Ff") or 0)
    look = entry.get("/MK") or {}
    options = []
    for option in _inherited(entry, "/Opt") or []:
        try:
            resolved = option.get_object() if hasattr(option, "get_object") else option
        except Exception:  # pragma: no cover - defensive
            continue
        options.append(str(resolved[0] if isinstance(resolved, list) else resolved))

    border_width = 1.0
    style = entry.get("/BS")
    if style is not None:
        try:
            border_width = float(style.get("/W", 1.0))
        except Exception:  # pragma: no cover - defensive
            border_width = 1.0

    kind = _kind(entry)
    return FormFieldObject(
        rect=rect,
        field_kind=kind,
        name=_full_name(entry),
        value=_value(entry),
        options=tuple(options),
        read_only=bool(flags & _READ_ONLY),
        required=bool(flags & _REQUIRED),
        multiline=bool(flags & _MULTILINE),
        alignment=_quadding(entry),
        checked=bool(kind in (FormFieldKind.CHECKBOX, FormFieldKind.RADIO) and _value(entry)),
        font_size=_font_size(entry) or 10.0,
        border_color=_colour(look, "/BC"),
        fill_color=_colour(look, "/BG"),
        border_width=border_width,
        tooltip=str(entry.get("/TU") or ""),
        source_index=index,
    )
