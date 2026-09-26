# Orion — PDF Editor for Desktop
# Copyright (C) 2026 Marco Lombardo
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# Distributed WITHOUT ANY WARRANTY; see LICENSE for the full terms.
# A commercial licence, without the AGPL's obligations, is available for use
# in proprietary or closed-source products — see COMMERCIAL-LICENSE.md.

"""Putting the saved form back together: its state, then its data.

The template is only the design. A form that somebody filled in and saved
carries two more records, and a conversion that ignores either of them
produces the empty design rather than the document the user opened:

* **The ``form`` packet** is the form object model as it stood at save time.
  It says how many rows each table had — a claim form with thirty expense
  lines lists thirty instances — which sections a script had revealed or
  hidden, the values of fields that are not bound to data, the items a script
  loaded into a drop-down, and the odd size a script changed. Nothing here
  runs a script; this is the record of what the scripts had already done.
* **The ``datasets`` packet** holds the bound values. XFA matches data to the
  form *in order*: each field takes the first unused data value of its name
  inside the data group its subform bound to, and a subform bound with
  ``match="none"`` is transparent. That is how thirty rows each find their own
  amount, where a lookup by name alone gave all thirty the first one.

Both passes only ever read. Neither follows a reference out of the document.
"""

from __future__ import annotations

import copy
import re
from collections import defaultdict
from xml.etree.ElementTree import Element

from orion.xfa.model import (
    XfaButton,
    XfaChoiceList,
    XfaDocument,
    XfaDraw,
    XfaField,
    XfaRect,
    XfaSubform,
)
from orion.xfa.safe_xml import local_name

__all__ = ["apply_form_state", "merge_data"]

#: How many copies of one repeatable subform the saved state may expand to.
#: A generous ceiling on a value read from the file, not a design limit.
MAX_SAVED_INSTANCES = 500

#: The value elements XFA writes inside ``<value>``.
_VALUE_TAGS = {
    "text",
    "date",
    "time",
    "dateTime",
    "float",
    "decimal",
    "integer",
    "boolean",
    "exData",
}


def _elements(node: Element) -> list[Element]:
    return [c for c in node if isinstance(c.tag, str)]


def _first(node: Element | None, name: str) -> Element | None:
    if node is None:
        return None
    for child in node:
        if isinstance(child.tag, str) and local_name(child.tag) == name:
            return child
    return None


# ---------------------------------------------------------------- form state


def _measure(text: str | None) -> float | None:
    from orion.xfa.parser import parse_measurement

    if text is None:
        return None
    value = parse_measurement(text, -1.0)
    return value if value >= 0 else None


def _geometry(rect: XfaRect, node: Element) -> XfaRect:
    """*rect* with whatever ``x``/``y``/``w``/``h`` the saved state changed."""
    x, y, w, h = (_measure(node.get(k)) for k in ("x", "y", "w", "h"))
    if x is None and y is None and w is None and h is None:
        return rect
    return XfaRect(
        rect.x if x is None else x,
        rect.y if y is None else y,
        rect.width if w is None else w,
        rect.height if h is None else h,
    )


def _presence(node: Element) -> bool | None:
    """True when the state hides the element, False when it shows it."""
    presence = node.get("presence")
    if presence is None:
        return None
    return presence in ("hidden", "inactive")


def _saved_value(node: Element) -> str | None:
    """The value a ``<field>`` or ``<draw>`` was saved with, if it says."""
    value = _first(node, "value")
    if value is None:
        return None
    for child in _elements(value):
        if local_name(child.tag) in _VALUE_TAGS:
            text = " ".join("".join(child.itertext()).split())
            return text or None
    return None


def _saved_items(field: XfaField, node: Element) -> None:
    """Replace a drop-down's options with the ones a script had loaded."""
    lists = [item for item in _elements(node) if local_name(item.tag) == "items"]
    if not lists or field.choices is None:
        return
    labels: list[str] = []
    values: list[str] = []
    for items in lists:
        collected = [" ".join("".join(e.itertext()).split()) for e in _elements(items)]
        if items.get("save") == "1" and len(lists) > 1:
            values = collected
        else:
            labels = collected
    if not labels:
        labels, values = values, []
    if len(lists) == 1 and field.choices.values and len(field.choices.labels) == len(labels):
        # Only the stored list was saved and it matches the shown one
        # item for item: keep what the user reads, update what is stored.
        values, labels = labels, list(field.choices.labels)
    field.choices = XfaChoiceList(
        labels=tuple(labels),
        values=tuple(values),
        open=field.choices.open,
        multi_select=field.choices.multi_select,
    )


def _apply_to_field(field: XfaField | XfaButton, node: Element) -> None:
    hidden = _presence(node)
    if hidden is not None:
        field.hidden = hidden
    field.rect = _geometry(field.rect, node)
    if isinstance(field, XfaButton):
        return
    access = node.get("access")
    if access:
        field.access = access
        field.read_only = access in ("readOnly", "protected", "nonInteractive")
    saved = _saved_value(node)
    if saved is not None:
        field.value = saved
    _saved_items(field, node)


def _apply_to_draw(draw: XfaDraw, node: Element) -> None:
    hidden = _presence(node)
    if hidden is not None:
        draw.hidden = hidden
    draw.rect = _geometry(draw.rect, node)
    saved = _saved_value(node)
    if saved is not None and draw.kind == "text":
        draw.text = saved


def _renamed(subform: XfaSubform, old: str, new: str) -> None:
    """Rewrite the SOM of a copied subform and of everything inside it."""

    def swap(som: str) -> str:
        if som == old:
            return new
        if som.startswith(old + "."):
            return new + som[len(old) :]
        return som

    for sub in subform.walk():
        sub.som = swap(sub.som)
        for item in list(sub.fields) + list(sub.buttons):
            item.som = swap(item.som)
            item.parent_som = swap(item.parent_som)
            if isinstance(item, XfaField) and item.group:
                item.group = swap(item.group)
        for draw in sub.draws:
            draw.parent_som = swap(draw.parent_som)


def _copy(subform: XfaSubform, index: int, total: int) -> XfaSubform:
    """One saved instance of a repeatable subform: a deep copy, renamed."""
    clone = copy.deepcopy(subform)
    clone.materialised = total
    clone.instance = index
    if index:
        _renamed(clone, subform.som, f"{subform.som}[{index}]")
    return clone


def _key(item: object) -> tuple[str, str]:
    if isinstance(item, XfaSubform):
        return ("exclGroup" if item.excl_group else "subform", item.name)
    if isinstance(item, XfaField | XfaButton):
        return ("field", item.name)
    if isinstance(item, XfaDraw):
        return ("draw", item.name) if item.name else ("", "")
    return ("", "")


def _apply_to_subform(subform: XfaSubform, node: Element) -> None:
    """Walk *subform* and its saved state side by side."""
    hidden = _presence(node)
    if hidden is not None:
        subform.hidden = hidden
    subform.rect = _geometry(subform.rect, node)

    queues: dict[tuple[str, str], list[Element]] = defaultdict(list)
    for child in _elements(node):
        tag = local_name(child.tag)
        if tag in ("subform", "field", "exclGroup"):
            queues[(tag, child.get("name", ""))].append(child)
        elif tag == "draw" and child.get("name"):
            queues[("draw", child.get("name", ""))].append(child)

    managers = {
        child.get("name", "")
        for child in _elements(node)
        if local_name(child.tag) == "instanceManager"
    }

    content: list[object] = []
    for item in subform.content:
        key = _key(item)
        queue = queues.get(key)
        if isinstance(item, XfaSubform) and item.is_repeatable and not item.excl_group:
            taken = list(queue or [])[:MAX_SAVED_INSTANCES]
            if queue:
                queue.clear()
            if not taken:
                if f"_{item.name}" in managers:
                    continue  # the saved form had no instance of it at all
                content.append(item)
                continue
            for index, saved in enumerate(taken):
                clone = _copy(item, index, len(taken))
                _apply_to_subform(clone, saved)
                content.append(clone)
            continue
        saved = queue.pop(0) if queue else None
        if saved is not None:
            if isinstance(item, XfaSubform):
                _apply_to_subform(item, saved)
            elif isinstance(item, XfaField | XfaButton):
                _apply_to_field(item, saved)
            elif isinstance(item, XfaDraw):
                _apply_to_draw(item, saved)
        content.append(item)

    subform.content = content
    subform.children = [c for c in content if isinstance(c, XfaSubform)]
    subform.fields = [c for c in content if isinstance(c, XfaField)]
    subform.buttons = [c for c in content if isinstance(c, XfaButton)]
    subform.draws = [c for c in content if isinstance(c, XfaDraw)]


def apply_form_state(document: XfaDocument, form_root: Element) -> None:
    """Bring the template up to the state the ``form`` packet recorded."""
    top = [c for c in _elements(form_root) if local_name(c.tag) == "subform"]
    if local_name(form_root.tag) == "subform":
        top = [form_root]
    root = document.template.root
    if not top:
        return
    document.has_form_state = True
    state = top[0]
    _apply_to_subform(root, state)

    page_set = _first(state, "pageSet")
    if page_set is None:
        return
    areas = [c for c in _elements(page_set) if local_name(c.tag) == "pageArea"]
    document.saved_pages = len(areas)
    by_name = {area.name: area for area in document.template.pages}
    seen: set[str] = set()
    for saved in areas:
        name = saved.get("name", "")
        area = by_name.get(name)
        if area is None or name in seen:
            continue  # later instances repeat the first; its furniture is shared
        seen.add(name)
        _apply_to_subform(area.furniture, saved)


# ---------------------------------------------------------------- data merge

_INDEX = re.compile(r"^(.*?)\[(\d+|\*)\]$")


class _Merger:
    """One run of XFA's ordered data merge over one document."""

    def __init__(self, data: Element, record: Element) -> None:
        self._data = data
        self._record = record
        self._used: set[int] = set()
        #: ``id()`` of every field the merge found a data value for.
        self.resolved: set[int] = set()

    def _unused_child(self, context: Element | None, name: str) -> Element | None:
        if context is None or not name:
            return None
        for child in _elements(context):
            if local_name(child.tag) == name and id(child) not in self._used:
                return child
        return None

    def _resolve(self, expression: str, context: Element | None) -> Element | None:
        """A ``bind ref`` like ``$record.a.b[2]`` or ``$.c``, read-only."""
        text = expression.strip()
        if text.startswith("$record"):
            node: Element | None = self._record
            text = text[len("$record") :]
        elif text.startswith("$data"):
            node = self._data
            text = text[len("$data") :]
        elif text.startswith("$"):
            node = context
            text = text[1:]
        else:
            node = context
        for part in [p for p in text.split(".") if p]:
            if node is None:
                return None
            match = _INDEX.match(part)
            name, index = (match.group(1), match.group(2)) if match else (part, "0")
            same = [c for c in _elements(node) if local_name(c.tag) == name]
            if index == "*":
                node = next((c for c in same if id(c) not in self._used), None)
            else:
                position = int(index)
                node = same[position] if position < len(same) else None
        return node

    def _global(self, name: str) -> Element | None:
        for node in self._data.iter():
            if isinstance(node.tag, str) and local_name(node.tag) == name:
                return node
        return None

    @staticmethod
    def _value_of(node: Element) -> str:
        return " ".join("".join(node.itertext()).split())

    def _bind_field(self, item: XfaField, context: Element | None) -> None:
        match = item.binding.match
        if match == "none":
            return
        if item.binding.expression:
            node = self._resolve(item.binding.expression, context)
        elif match == "global":
            node = self._global(item.name)
        else:
            node = self._unused_child(context, item.name)
        if node is None:
            return
        if match != "global":
            self._used.add(id(node))
        self.resolved.add(id(item))
        value = self._value_of(node)
        if value:
            item.value = value

    def _bind_group(self, group: XfaSubform, context: Element | None) -> None:
        if group.binding.match == "none":
            return
        if group.binding.expression:
            node = self._resolve(group.binding.expression, context)
        else:
            node = self._unused_child(context, group.name)
        if node is None:
            return
        self._used.add(id(node))
        value = self._value_of(node)
        for member in group.fields:
            self.resolved.add(id(member))
            if value:
                member.value = value

    def subform(self, subform: XfaSubform, context: Element | None) -> None:
        for item in subform.content:
            if isinstance(item, XfaField):
                self._bind_field(item, context)
            elif isinstance(item, XfaSubform):
                if item.excl_group:
                    self._bind_group(item, context)
                    continue
                inner = context
                if item.name and item.binding.match != "none":
                    if item.binding.expression:
                        inner = self._resolve(item.binding.expression, context)
                    else:
                        inner = self._unused_child(context, item.name)
                    if inner is not None:
                        self._used.add(id(inner))
                self.subform(item, inner)


def merge_data(document: XfaDocument, datasets: Element) -> set[int]:
    """Fill fields from the datasets packet the way XFA matches them.

    Returns the ``id()`` of every field a data value was found for, so the
    looser name-based fallback can leave those alone.
    """
    data = None
    for node in datasets.iter():
        if isinstance(node.tag, str) and local_name(node.tag) == "data":
            data = node
            break
    if data is None:
        data = datasets
    records = _elements(data)
    if not records:
        return set()
    record = records[0]
    merger = _Merger(data, record)
    merger.subform(document.template.root, record)
    for area in document.template.pages:
        merger.subform(area.furniture, record)
    return merger.resolved
