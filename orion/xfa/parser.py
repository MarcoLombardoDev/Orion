# Orion — PDF Editor for Desktop
# Copyright (C) 2026 Marco Lombardo
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# Distributed WITHOUT ANY WARRANTY; see LICENSE for the full terms.
# A commercial licence, without the AGPL's obligations, is available for use
# in proprietary or closed-source products — see COMMERCIAL-LICENSE.md.

"""Turning the XFA packets into the model.

Two packets carry everything that matters. ``template`` is the design — the
subform tree, where each field sits, what it looks like, what it is called.
``datasets`` is the data filled into it, held in a separate tree whose shape
mirrors the template's bindings rather than the template itself.

What makes this fiddly rather than hard:

* **Namespaces move.** The template namespace URI carries a version that
  changes between LiveCycle releases, so every match is on the *local* name.
* **Measurements carry units.** ``12.7mm``, ``0.5in``, ``36pt``, and bare
  numbers meaning points. All of it becomes points here, once.
* **A field's type is its UI child**, not an attribute. ``<ui><textEdit/></ui>``
  is a text box; ``<ui><choiceList/></ui>`` a dropdown. A field with no ``ui``
  is still a text box, which is XFA's own default.
* **Values live in two places.** The template's ``<value>`` holds the default;
  the datasets packet holds what the form was saved with. The second wins.

Nothing here executes anything. Script text is copied into the model as a
string and classified later, and that is the only thing ever done with it.
"""

from __future__ import annotations

import logging
import re
from xml.etree.ElementTree import Element

from orion.xfa.model import (
    NO_EDGES,
    XfaBinding,
    XfaButton,
    XfaButtonKind,
    XfaChoiceList,
    XfaDocument,
    XfaDraw,
    XfaEdge,
    XfaField,
    XfaFieldType,
    XfaFont,
    XfaInsets,
    XfaOccur,
    XfaPageArea,
    XfaRect,
    XfaScript,
    XfaScriptKind,
    XfaSubform,
)
from orion.xfa.safe_xml import XmlRejected, local_name, parse_xml

__all__ = ["is_hidden", "parse_measurement", "parse_xfa"]

log = logging.getLogger(__name__)

#: XFA writes lengths with a unit suffix. Everything becomes points.
_UNITS = {
    "pt": 1.0,
    "in": 72.0,
    "mm": 72.0 / 25.4,
    "cm": 72.0 / 2.54,
    "px": 72.0 / 96.0,  # XFA's px is a CSS pixel, not a device one
    "pc": 12.0,  # pica
    "em": 12.0,  # only ever an approximation; XFA rarely uses it for geometry
}

_MEASURE = re.compile(r"^\s*([+-]?\d*\.?\d+)\s*([a-z]*)\s*$", re.IGNORECASE)

#: ``<ui>`` child -> what kind of control it is.
_UI_TYPES = {
    "textedit": XfaFieldType.TEXT,
    "numericedit": XfaFieldType.NUMERIC,
    "datetimeedit": XfaFieldType.DATE,
    "checkbutton": XfaFieldType.CHECKBOX,
    "choicelist": XfaFieldType.CHOICE,
    "button": XfaFieldType.BUTTON,
    "signature": XfaFieldType.SIGNATURE,
    "imageedit": XfaFieldType.IMAGE,
    "barcode": XfaFieldType.BARCODE,
    "passwordedit": XfaFieldType.TEXT,
}

#: XFA event name -> why the script is there. Used for classification only.
_EVENT_KINDS = {
    "validate": XfaScriptKind.VALIDATION,
    "calculate": XfaScriptKind.CALCULATION,
    "initialize": XfaScriptKind.INITIALIZATION,
    "click": XfaScriptKind.BUTTON_ACTION,
    "change": XfaScriptKind.EVENT_HANDLER,
    "enter": XfaScriptKind.EVENT_HANDLER,
    "exit": XfaScriptKind.EVENT_HANDLER,
    "ready": XfaScriptKind.INITIALIZATION,
    "docready": XfaScriptKind.INITIALIZATION,
    "form:ready": XfaScriptKind.INITIALIZATION,
    "mouseenter": XfaScriptKind.EVENT_HANDLER,
    "mouseexit": XfaScriptKind.EVENT_HANDLER,
}

#: Substrings that mean a script touches something AcroForm has no notion of.
_LAYOUT_HINTS = ("instancemanager", "addinstance", "removeinstance", "_count", "xfa.layout")
_VISIBILITY_HINTS = ("presence", "relevant")
_ACCESS_HINTS = ("access =", "access=", ".access")


def parse_measurement(text: str | None, default: float = 0.0) -> float:
    """``"12.7mm"`` -> points. A bare number is already points."""
    if not text:
        return default
    match = _MEASURE.match(str(text))
    if not match:
        return default
    value = float(match.group(1))
    unit = (match.group(2) or "pt").lower()
    return value * _UNITS.get(unit, 1.0)


def _children(node: Element, name: str) -> list[Element]:
    return [c for c in node if local_name(c.tag) == name]


def _child(node: Element, name: str) -> Element | None:
    for candidate in node:
        if local_name(candidate.tag) == name:
            return candidate
    return None


def _text_of(node: Element | None) -> str:
    """All the text under *node*, whitespace collapsed.

    XFA wraps display text in ``<text>`` inside ``<value>`` inside ``<caption>``
    and similar nests, often with the string split across several nodes.
    """
    if node is None:
        return ""
    return " ".join("".join(node.itertext()).split())


def _rect_of(node: Element) -> XfaRect:
    """The box an element declares, in points.

    An element that grows with its content carries ``minW``/``minH`` and no
    ``w``/``h`` at all — which is how most of a real flowed form is written.
    Reading only ``w``/``h`` gives such an element a height of zero, and a
    flowed parent then stacks every one of its children on the same line: the
    whole lower half of a form collapsed into three overlapping rows. The
    minimum is the size the form opens at, so it is the size to lay out.
    """
    return XfaRect(
        x=parse_measurement(node.get("x")),
        y=parse_measurement(node.get("y")),
        width=max(parse_measurement(node.get("w")), parse_measurement(node.get("minW"))),
        height=max(parse_measurement(node.get("h")), parse_measurement(node.get("minH"))),
    )


def is_hidden(node: Element) -> bool:
    """Does the template hide this element when the form opens?

    ``presence="hidden"`` and ``presence="inactive"`` both mean "not on the
    page", and a real form uses them heavily: a field appears only once a
    script decides it applies. Orion records the fact rather than acting on
    it, because what to do about it depends on the conversion mode — see
    :mod:`orion.xfa.converter`. ``invisible`` is deliberately not in this
    list: it means the element takes its space and draws nothing, so it is
    still part of the layout.
    """
    return node.get("presence") in ("hidden", "inactive")


def _column_widths_of(node: Element) -> tuple[float, ...]:
    """``columnWidths="36mm 39mm 39mm 39mm"`` -> the widths in points.

    A table declares its columns once and its rows then declare nothing but
    their cells, so this is the only place the geometry of a table exists.
    """
    raw = node.get("columnWidths")
    if not raw:
        return ()
    widths = [parse_measurement(part) for part in raw.split()]
    # A zero-width column is kept: dropping it would shift every cell after
    # it one column to the left.
    return tuple(widths) if any(w > 0 for w in widths) else ()


def _insets_of(node: Element) -> XfaInsets:
    """``<margin leftInset="6.7mm" …>`` in points."""
    margin = _child(node, "margin")
    if margin is None:
        return XfaInsets()
    return XfaInsets(
        left=parse_measurement(margin.get("leftInset")),
        top=parse_measurement(margin.get("topInset")),
        right=parse_measurement(margin.get("rightInset")),
        bottom=parse_measurement(margin.get("bottomInset")),
    )


def _indent_of(node: Element | None) -> float:
    """``<para marginLeft>``: how far in from its box the text starts."""
    if node is None:
        return 0.0
    para = _child(node, "para")
    return parse_measurement(para.get("marginLeft")) if para is not None else 0.0


def _space_of(node: Element | None) -> tuple[float, float]:
    """``<para spaceAbove/spaceBelow>``: the gap a flowed parent leaves.

    LiveCycle Designer offers these as an object's spacing, and a flowed form
    is built out of them: without them every row in a section butts against
    the next one and the document comes out tighter than it was drawn.
    """
    if node is None:
        return 0.0, 0.0
    para = _child(node, "para")
    if para is None:
        return 0.0, 0.0
    return (
        parse_measurement(para.get("spaceAbove")),
        parse_measurement(para.get("spaceBelow")),
    )


def _para_of(node: Element | None) -> tuple[str, str]:
    """``<para hAlign vAlign>`` -> ``(horizontal, vertical)``.

    XFA's defaults are left and top, which is also what everything here falls
    back to, so an element without a ``<para>`` reads the same as before.
    """
    if node is None:
        return "left", "top"
    para = _child(node, "para")
    if para is None:
        return "left", "top"
    return (para.get("hAlign") or "left"), (para.get("vAlign") or "top")


def _colour_of(text: str | None, default=(0.0, 0.0, 0.0)) -> tuple[float, float, float]:
    """XFA writes colour as ``"255,128,0"``."""
    if not text:
        return default
    parts = [p.strip() for p in str(text).split(",")]
    if len(parts) != 3:
        return default
    try:
        return tuple(min(255, max(0, int(float(p)))) / 255.0 for p in parts)  # type: ignore[return-value]
    except ValueError:
        return default


def _font_of(node: Element, inherited: XfaFont) -> XfaFont:
    """A node's font, falling back to whatever it inherited.

    XFA fonts cascade down the subform tree the way CSS does, so a field that
    declares nothing takes its parent's.
    """
    font_node = _child(node, "font")
    if font_node is None:
        return inherited
    family = font_node.get("typeface") or inherited.family
    size = parse_measurement(font_node.get("size"), inherited.size)
    weight = (font_node.get("weight") or "").lower()
    posture = (font_node.get("posture") or "").lower()
    fill = _child(font_node, "fill")
    colour = inherited.color
    if fill is not None:
        solid = _child(fill, "color")
        if solid is not None:
            colour = _colour_of(solid.get("value"), inherited.color)
    return XfaFont(
        family=family,
        size=size if size > 0 else inherited.size,
        bold=weight == "bold" or inherited.bold if weight else inherited.bold,
        italic=posture == "italic" if posture else inherited.italic,
        color=colour,
    )


def _script_kind(event: str, source: str) -> XfaScriptKind:
    """Classify a script by its event and by what it plainly touches.

    Reading the text is pattern-matching for hints, not interpretation: the
    point is to tell the user *why* something was lost, and "it rearranged the
    form" is a more useful answer than "a script".
    """
    lowered = source.lower()
    if any(hint in lowered for hint in _LAYOUT_HINTS):
        return XfaScriptKind.DYNAMIC_LAYOUT
    if any(hint in lowered for hint in _VISIBILITY_HINTS):
        return XfaScriptKind.VISIBILITY
    if any(hint in lowered for hint in _ACCESS_HINTS):
        return XfaScriptKind.ENABLE_DISABLE
    kind = _EVENT_KINDS.get(event.lower())
    if kind is not None:
        return kind
    if ".rawvalue" in lowered and "=" in lowered:
        return XfaScriptKind.VALUE_ASSIGNMENT
    return XfaScriptKind.UNKNOWN


def _scripts_of(node: Element, som: str) -> tuple[XfaScript, ...]:
    """Every script hanging off *node*, classified and left as text."""
    found: list[XfaScript] = []
    for event in _children(node, "event"):
        activity = event.get("activity", "")
        for script in _children(event, "script"):
            source = (script.text or "").strip()
            if not source:
                continue
            found.append(
                XfaScript(
                    kind=_script_kind(activity, source),
                    owner=som,
                    event=activity,
                    source=source,
                    language=(script.get("contentType") or "javascript").split("/")[-1],
                )
            )
    # calculate/validate hold their script directly rather than under an event.
    for holder, kind in (
        ("calculate", XfaScriptKind.CALCULATION),
        ("validate", XfaScriptKind.VALIDATION),
    ):
        for wrapper in _children(node, holder):
            for script in _children(wrapper, "script"):
                source = (script.text or "").strip()
                if source:
                    found.append(
                        XfaScript(
                            kind=kind,
                            owner=som,
                            event=holder,
                            source=source,
                            language=(script.get("contentType") or "javascript").split("/")[-1],
                        )
                    )
    return tuple(found)


def _field_type(node: Element) -> tuple[XfaFieldType, Element | None]:
    """A field's control, from its ``<ui>`` child.

    A field with no ``ui`` is a text box: that is XFA's default, not a guess.
    """
    ui = _child(node, "ui")
    if ui is None:
        return XfaFieldType.TEXT, None
    for candidate in ui:
        name = local_name(candidate.tag).lower()
        if name in _UI_TYPES:
            return _UI_TYPES[name], candidate
    return XfaFieldType.UNKNOWN, None


def _choices_of(node: Element, ui_node: Element | None) -> XfaChoiceList:
    """The options behind a choice list.

    XFA keeps them in ``<items>`` siblings: one list of what is shown and,
    when the two differ, a second marked ``save="1"`` of what is stored.
    """
    labels: list[str] = []
    values: list[str] = []
    for items in _children(node, "items"):
        collected = [_text_of(entry) for entry in items]
        if items.get("save") == "1" or items.get("presence") == "hidden":
            values = collected
        else:
            labels = collected
    if not labels and values:
        labels, values = values, []
    open_list = bool(ui_node is not None and ui_node.get("open") in ("userControl", "multiSelect"))
    multi = bool(ui_node is not None and ui_node.get("open") == "multiSelect")
    return XfaChoiceList(
        labels=tuple(labels),
        values=tuple(values),
        open=open_list,
        multi_select=multi,
    )


def _occur_of(node: Element) -> XfaOccur:
    occur = _child(node, "occur")
    if occur is None:
        return XfaOccur()

    def as_int(text: str | None, default: int) -> int:
        if text is None:
            return default
        cleaned = str(text).strip().lower()
        if cleaned in ("-1", "unbounded", "*"):
            return -1
        try:
            return int(float(cleaned))
        except ValueError:
            return default

    minimum = as_int(occur.get("min"), 1)
    maximum = as_int(occur.get("max"), 1)
    initial = as_int(occur.get("initial"), max(minimum, 1))
    return XfaOccur(min=minimum, max=maximum, initial=initial)


def _som(parent: str, name: str) -> str:
    """Build the dotted path XFA uses to address a node."""
    if not name:
        return parent
    return f"{parent}.{name}" if parent else name


def _parse_field(node: Element, parent_som: str, font: XfaFont) -> XfaField | XfaButton:
    name = node.get("name") or ""
    som = _som(parent_som, name)
    field_type, ui_node = _field_type(node)
    own_font = _font_of(node, font)
    caption_node = _child(node, "caption")
    caption = _text_of(_child(caption_node, "value")) if caption_node is not None else ""
    caption_reserve = (
        parse_measurement(caption_node.get("reserve")) if caption_node is not None else 0.0
    )
    caption_placement = (
        (caption_node.get("placement") or "left") if caption_node is not None else "left"
    )
    scripts = _scripts_of(node, som)

    if field_type is XfaFieldType.BUTTON:
        return XfaButton(
            name=name,
            kind=_button_kind(node, scripts),
            caption=caption or name,
            som=som,
            rect=_rect_of(node),
            font=own_font,
            scripts=scripts,
            parent_som=parent_som,
            hidden=is_hidden(node),
        )

    value_node = _child(node, "value")
    default_value = _text_of(value_node)
    binding = _child(node, "bind")

    edit = ui_node
    multiline = bool(edit is not None and edit.get("multiLine") == "1")
    validate = _child(node, "validate")
    mandatory = bool(validate is not None and validate.get("nullTest") in ("error", "warning"))

    picture = ""
    fmt = _child(node, "format")
    if fmt is not None:
        picture_node = _child(fmt, "picture")
        picture = _text_of(picture_node)

    border = _child(node, "border")
    border_width, border_colour, fill_colour = _border_of(border)

    access = node.get("access", "open")
    field = XfaField(
        name=name,
        field_type=field_type,
        som=som,
        identifier=node.get("id", ""),
        caption=caption,
        value=default_value,
        default_value=default_value,
        rect=_rect_of(node),
        font=own_font,
        multiline=multiline,
        # XFA's three non-editable accesses all mean the same thing to a
        # standard form: the field is there and the user may not change it.
        read_only=access in ("readOnly", "protected", "nonInteractive"),
        mandatory=mandatory,
        max_length=int(parse_measurement(edit.get("maxChars"), 0)) if edit is not None else 0,
        picture=picture,
        caption_reserve=caption_reserve,
        caption_placement=caption_placement,
        margins=_insets_of(node),
        align=_para_of(node)[0],
        valign=_para_of(node)[1],
        caption_align=_para_of(caption_node)[0],
        caption_valign=_para_of(caption_node)[1],
        caption_font=_font_of(caption_node, own_font) if caption_node is not None else None,
        text_indent=_indent_of(node),
        space_above=_space_of(node)[0],
        space_below=_space_of(node)[1],
        edges=_edges_of(border),
        tooltip=_text_of(_child(_child(node, "assist"), "toolTip"))
        if _child(node, "assist") is not None
        else "",
        choices=_choices_of(node, ui_node) if field_type is XfaFieldType.CHOICE else None,
        binding=XfaBinding(
            expression=binding.get("ref", "") if binding is not None else "",
            match=binding.get("match", "once") if binding is not None else "once",
        ),
        access=access,
        scripts=scripts,
        parent_som=parent_som,
        border_width=border_width,
        border_color=border_colour,
        fill_color=fill_colour,
        hidden=is_hidden(node),
    )

    # A checkbox whose UI declares more than two states is a radio member in
    # everything but name; XFA models an exclusion group as its container.
    if field_type is XfaFieldType.CHECKBOX:
        items = _children(node, "items")
        if items:
            options = [_text_of(entry) for entry in items[0]]
            field.export_value = options[0] if options else "1"
        else:
            field.export_value = "1"
    return field


def _button_kind(node: Element, scripts: tuple[XfaScript, ...]) -> XfaButtonKind:
    for script in scripts:
        if script.kind is XfaScriptKind.DYNAMIC_LAYOUT:
            return XfaButtonKind.INSTANCE
    text = " ".join(s.source.lower() for s in scripts)
    if "submit" in text or _child(node, "submit") is not None:
        return XfaButtonKind.SUBMIT
    if "resetdata" in text or "xfa.host.resetdata" in text:
        return XfaButtonKind.RESET
    if "print" in text:
        return XfaButtonKind.PRINT
    if "execmenuitem" in text and "save" in text:
        return XfaButtonKind.SAVE
    return XfaButtonKind.SCRIPTED if scripts else XfaButtonKind.PLAIN


#: What XFA draws an ``<edge>`` with when it does not say. The specification's
#: default, and the reason a border read as "no thickness given, so none" came
#: out invisible where the form shows a line.
DEFAULT_EDGE_THICKNESS = 0.5


def _edges_of(border: Element | None) -> tuple[XfaEdge, XfaEdge, XfaEdge, XfaEdge]:
    """The four sides of a ``<border>``, in XFA's order: top, right, bottom, left.

    One ``<edge>`` stands for all four — the usual case, a plain box. Four of
    them describe the sides separately, which is how a form draws a cell with
    a rule under it and nothing elsewhere. A hidden ``<border>`` hides all of
    them however many are written inside it.
    """
    if border is None or border.get("presence") == "hidden":
        return NO_EDGES

    declared = _children(border, "edge")
    if not declared:
        return NO_EDGES

    sides: list[XfaEdge] = []
    for edge in declared[:4]:
        colour_node = _child(edge, "color")
        sides.append(
            XfaEdge(
                width=parse_measurement(edge.get("thickness"), DEFAULT_EDGE_THICKNESS),
                color=(
                    _colour_of(colour_node.get("value"))
                    if colour_node is not None
                    else (0.0, 0.0, 0.0)
                ),
                visible=edge.get("presence") not in ("hidden", "inactive"),
            )
        )
    if len(sides) == 1:
        return (sides[0], sides[0], sides[0], sides[0])
    while len(sides) < 4:
        sides.append(XfaEdge())
    return (sides[0], sides[1], sides[2], sides[3])


def _border_of(border: Element | None):
    """Width, line colour and fill colour of a ``<border>``.

    The single-figure view, still wanted by everything that draws a plain box
    — a rule, a button — while :func:`_edges_of` carries the sides. The width
    reported here is the thickest side that is actually drawn, so an element
    with three hidden edges no longer claims a box it does not have.
    """
    if border is None:
        return 0.0, (0.0, 0.0, 0.0), None
    edges = _edges_of(border)
    drawn = [edge for edge in edges if edge.draws]
    width = max((edge.width for edge in drawn), default=0.0)
    colour = drawn[0].color if drawn else (0.0, 0.0, 0.0)
    fill_colour = None
    fill = _child(border, "fill")
    if fill is not None and fill.get("presence") != "hidden":
        solid = _child(fill, "color")
        fill_colour = _colour_of(solid.get("value"), (1.0, 1.0, 1.0)) if solid is not None else None
    return width, colour, fill_colour


def _parse_draw(node: Element, parent_som: str, font: XfaFont) -> XfaDraw:
    """A ``<draw>``: static text, a rule, a box. The form's furniture."""
    own_font = _font_of(node, font)
    value = _child(node, "value")
    text = _text_of(value)
    rect = _rect_of(node)
    border_width, border_colour, fill_colour = _border_of(_child(node, "border"))

    kind = "text"
    line_width = border_width
    line_colour = border_colour
    if value is not None:
        if _child(value, "line") is not None:
            kind = "line"
            line = _child(value, "line")
            edge = _child(line, "edge") if line is not None else None
            if edge is not None:
                line_width = parse_measurement(edge.get("thickness"), 1.0)
                edge_colour = _child(edge, "color")
                if edge_colour is not None:
                    line_colour = _colour_of(edge_colour.get("value"))
            if line_width <= 0:
                line_width = 1.0
        elif _child(value, "rectangle") is not None:
            kind = "rectangle"
            rectangle = _child(value, "rectangle")
            fill = _child(rectangle, "fill") if rectangle is not None else None
            if fill is not None:
                solid = _child(fill, "color")
                if solid is not None:
                    fill_colour = _colour_of(solid.get("value"), (1.0, 1.0, 1.0))
        elif _child(value, "image") is not None:
            kind = "image"

    align, valign = _para_of(node)

    return XfaDraw(
        kind=kind,
        text=text,
        rect=rect,
        font=own_font,
        align=align,
        valign=valign,
        margins=_insets_of(node),
        space_above=_space_of(node)[0],
        space_below=_space_of(node)[1],
        edges=_edges_of(_child(node, "border")),
        line_width=line_width,
        line_color=line_colour,
        fill_color=fill_colour,
        parent_som=parent_som,
        hidden=is_hidden(node),
    )


def _parse_subform(node: Element, parent_som: str, font: XfaFont, depth: int = 0) -> XfaSubform:
    name = node.get("name") or ""
    som = _som(parent_som, name)
    own_font = _font_of(node, font)
    subform = XfaSubform(
        name=name,
        som=som,
        rect=_rect_of(node),
        layout=node.get("layout", "position"),
        column_widths=_column_widths_of(node),
        occur=_occur_of(node),
        scripts=_scripts_of(node, som),
        page_break_before=_child(node, "breakBefore") is not None,
        hidden=is_hidden(node),
        space_above=_space_of(node)[0],
        space_below=_space_of(node)[1],
    )

    for child in node:
        tag = local_name(child.tag)
        if tag == "subform":
            nested = _parse_subform(child, som, own_font, depth + 1)
            subform.children.append(nested)
            subform.content.append(nested)
        elif tag == "subformSet":
            # A wrapper XFA uses to group alternatives; its subforms are ours.
            for inner in _children(child, "subform"):
                nested = _parse_subform(inner, som, own_font, depth + 1)
                subform.children.append(nested)
                subform.content.append(nested)
        elif tag == "field":
            parsed = _parse_field(child, som, own_font)
            if isinstance(parsed, XfaButton):
                subform.buttons.append(parsed)
            else:
                subform.fields.append(parsed)
            subform.content.append(parsed)
        elif tag == "draw":
            drawn = _parse_draw(child, som, own_font)
            subform.draws.append(drawn)
            subform.content.append(drawn)
        elif tag == "exclGroup":
            # An exclusion group *is* a radio group: its fields are the options.
            _parse_excl_group(child, som, own_font, subform)

    return subform


def _parse_excl_group(node: Element, parent_som: str, font: XfaFont, into: XfaSubform) -> None:
    """Turn an ``<exclGroup>`` into a positioned container of radio fields.

    XFA models mutual exclusion as a container holding checkbuttons; AcroForm
    models it as one field with several widgets and distinct export values.
    Same idea, written the other way round — so the group's name travels onto
    each member and becomes the AcroForm field name.

    It becomes a *subform* rather than a handful of loose fields because the
    group is one thing on the page. Flattening its members into the parent
    made each of them a separate item in a flowed layout, which stacked two
    radio buttons that belong side by side down the page instead.
    """
    group_name = node.get("name") or ""
    group_som = _som(parent_som, group_name)
    own_font = _font_of(node, font)
    selected = _text_of(_child(node, "value"))

    container = XfaSubform(
        name=group_name,
        som=group_som,
        rect=_rect_of(node),
        layout="position",
        scripts=_scripts_of(node, group_som),
    )

    for child in _children(node, "field"):
        parsed = _parse_field(child, group_som, own_font)
        if isinstance(parsed, XfaButton):
            continue
        parsed.field_type = XfaFieldType.RADIO
        parsed.group = group_som
        items = _children(child, "items")
        options = [_text_of(entry) for entry in items[0]] if items else []
        parsed.export_value = options[0] if options else (parsed.name or "on")
        parsed.value = selected
        container.fields.append(parsed)
        container.content.append(parsed)

    into.children.append(container)
    into.content.append(container)


def _parse_page_areas(template_root: Element) -> list[XfaPageArea]:
    """The page sizes the template declares, in order."""
    pages: list[XfaPageArea] = []
    for page_set in template_root.iter():
        if local_name(page_set.tag) != "pageArea":
            continue
        area = XfaPageArea(name=page_set.get("name", ""))
        medium = _child(page_set, "medium")
        if medium is not None:
            width = parse_measurement(medium.get("short"), 0.0)
            height = parse_measurement(medium.get("long"), 0.0)
            if width > 0:
                area.width = width
            if height > 0:
                area.height = height
            if medium.get("orientation") == "landscape":
                area.width, area.height = area.height, area.width
        content = _child(page_set, "contentArea")
        if content is not None:
            area.margin_left = parse_measurement(content.get("x"), 0.0)
            area.margin_top = parse_measurement(content.get("y"), 0.0)
        area.furniture = _parse_furniture(page_set, area.name)
        pages.append(area)
    return pages


def _parse_furniture(page_set: Element, page_name: str) -> XfaSubform:
    """A page area's own contents: the header, the logo, the page number.

    These sit outside the form's subform tree — they belong to the page rather
    than to the data — and a converter that walks only the tree produces a form
    with its masthead missing. They are positioned against the page corner, so
    the container is a positioned subform at the origin.
    """
    furniture = XfaSubform(name=page_name, som=page_name, layout="position")
    font = XfaFont()
    for child in page_set:
        tag = local_name(child.tag)
        if tag in ("subform", "area"):
            nested = _parse_subform(child, page_name, font)
            furniture.children.append(nested)
            furniture.content.append(nested)
        elif tag == "field":
            parsed = _parse_field(child, page_name, font)
            if isinstance(parsed, XfaButton):
                furniture.buttons.append(parsed)
            else:
                furniture.fields.append(parsed)
            furniture.content.append(parsed)
        elif tag == "draw":
            drawn = _parse_draw(child, page_name, font)
            furniture.draws.append(drawn)
            furniture.content.append(drawn)
    return furniture


def _collect_data(node: Element, prefix: str, into: dict[str, str]) -> None:
    """Flatten the datasets tree into ``path -> value``.

    Both the full dotted path and the bare leaf name are stored, because a
    template's ``bind ref`` may address a field either way and matching only
    one of them loses values for no reason.
    """
    for child in node:
        name = child.get("name") or local_name(child.tag)
        path = f"{prefix}.{name}" if prefix else name
        children = list(child)
        if children:
            _collect_data(child, path, into)
        else:
            text = (child.text or "").strip()
            if text:
                into[path] = text
                into.setdefault(name, text)


def parse_xfa(packets: dict[str, bytes]) -> XfaDocument:
    """Build the model from the packets the detector pulled out.

    A missing or unreadable template is not fatal: the caller still gets a
    document, with the trouble recorded in ``warnings``, so that a conversion
    can fall back to something useful rather than stopping.
    """
    document = XfaDocument(packet_names=tuple(sorted(packets)))

    template_bytes = packets.get("template")
    xdp_bytes = packets.get("xdp")
    template_root: Element | None = None

    if template_bytes:
        try:
            template_root = parse_xml(template_bytes)
        except XmlRejected as exc:
            document.warnings.append(str(exc))
    elif xdp_bytes:
        # One XDP holding every packet: find the template inside it.
        try:
            xdp = parse_xml(xdp_bytes)
        except XmlRejected as exc:
            document.warnings.append(str(exc))
        else:
            for node in xdp.iter():
                if local_name(node.tag) == "template":
                    template_root = node
                    break
            if template_root is None and local_name(xdp.tag) == "template":
                template_root = xdp

    if template_root is not None:
        root_subforms = _children(template_root, "subform")
        base_font = XfaFont()
        if len(root_subforms) == 1:
            document.template.root = _parse_subform(root_subforms[0], "", base_font)
        elif root_subforms:
            holder = XfaSubform(name="", som="")
            for node in root_subforms:
                holder.children.append(_parse_subform(node, "", base_font))
            document.template.root = holder
        else:
            document.warnings.append("The XFA template contains no subform.")
        document.template.pages = _parse_page_areas(template_root)
    else:
        document.warnings.append("The XFA template could not be read.")

    datasets_bytes = packets.get("datasets")
    if datasets_bytes:
        try:
            datasets = parse_xml(datasets_bytes)
        except XmlRejected as exc:
            document.warnings.append(str(exc))
        else:
            _collect_data(datasets, "", document.data)
    elif xdp_bytes and template_root is not None:
        try:
            xdp = parse_xml(xdp_bytes)
        except XmlRejected:
            pass
        else:
            for node in xdp.iter():
                if local_name(node.tag) == "datasets":
                    _collect_data(node, "", document.data)
                    break

    _apply_data(document)
    return document


def _apply_data(document: XfaDocument) -> None:
    """Fill the template's fields with what the datasets packet saved.

    The binding expression wins when it resolves; failing that the field's own
    name is tried, which is what XFA does implicitly when a field binds by
    name. A field the data says nothing about keeps its template default.
    """
    if not document.data:
        return
    for field in document.fields:
        ref = field.binding.expression
        candidates = []
        if ref:
            cleaned = ref.lstrip("$").replace("record.", "").replace("data.", "")
            candidates.extend([ref, cleaned, cleaned.split(".")[-1]])
        candidates.extend([field.som, field.name])
        for candidate in candidates:
            if candidate and candidate in document.data:
                field.value = document.data[candidate]
                break
