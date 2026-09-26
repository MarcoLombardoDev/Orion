# Orion — PDF Editor for Desktop
# Copyright (C) 2026 Marco Lombardo
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# Distributed WITHOUT ANY WARRANTY; see LICENSE for the full terms.
# A commercial licence, without the AGPL's obligations, is available for use
# in proprietary or closed-source products — see COMMERCIAL-LICENSE.md.

"""Working out where everything actually goes.

This is the pass that earns the feature. A dynamic XFA's PDF pages are a
placeholder — "if this message is not eventually replaced…" — so there is no
existing appearance to copy, and rasterising the original would preserve
nothing but the apology. The layout has to be *computed* from the template,
which is what a real XFA viewer does at open time and what makes these forms
unopenable everywhere else.

XFA lays out in a handful of modes and the tree mixes them freely:

* **position** — children sit at their own ``x``/``y`` within the parent.
  Coordinates are relative, so they accumulate down the tree.
* **tb** — children *flow*: each is placed below the last, at the parent's
  left edge. Their own ``x`` and ``y`` are ignored, as the specification
  says: LiveCycle Designer keeps whatever coordinates an object had before it
  was dropped into a flowed subform, and honouring them opened gaps of
  several centimetres in the middle of a table.
* **lr-tb** — the same across, wrapping onto a new line at the right edge.
* **table** and **row** — a table flows its rows downwards; a row runs its
  cells across, and every cell takes its width from the table's
  ``columnWidths`` rather than from its own ``w``. A row is as tall as its
  tallest cell, and every cell is stretched to that height, which is what
  keeps a table's rules continuous when one description runs to two lines.

An element with a minimum height rather than a fixed one grows to fit its
content, as it does in a real viewer, so a long description makes its row
taller instead of spilling out of it.

**Pagination** is a separate step over what the walk produced. The walk lays
everything out on one long galley and records which elements belong together
— a row, a positioned block — and the paginator then cuts that galley into
the page area's content area, moving a block that does not fit onto the next
page whole. A table that continues repeats its heading row (``overflow
leader``), and the page's own furniture — header band, footer, page number —
is laid down on every page. A field whose script writes the page number
gets the number, since that is the one layout script whose answer the
converter knows.

Repeatable subforms are materialised once per instance that the saved form
state recorded (see :mod:`orion.xfa.merge`), or as many as the template asks
for at open time when there is no saved state.

Everything leaves here in **page coordinates, still top-left origin and y
downwards**. The flip to PDF's bottom-left happens once, in the converter,
because doing it earlier means doing it in several places.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from orion.xfa.model import (
    XfaBreak,
    XfaButton,
    XfaDocument,
    XfaDraw,
    XfaField,
    XfaPageArea,
    XfaRect,
    XfaSubform,
)

__all__ = ["LaidOutForm", "PlacedPage", "rect_to_pdf", "resolve_layout"]

log = logging.getLogger(__name__)

#: What to give a table row whose cells all declare a width and no height.
#: Roughly one line of 10pt text with room around it, which is what such a
#: row comes out as in a real viewer.
DEFAULT_ROW_HEIGHT = 18.0

#: A guard against a template that would otherwise paginate forever.
MAX_PAGES = 200

#: How many instances of one repeatable subform to materialise from the
#: template alone, whatever it claims. ``max="-1"`` means unbounded, and a
#: converter that took that literally would never finish.
MAX_INSTANCES = 100

#: Layouts whose children flow rather than sit where they say.
_FLOWED = ("tb", "lr-tb", "rl-tb", "table")

#: Slack allowed when deciding whether a block fits. Half a millimetre: the
#: sizes here are Orion's measurements of the designer's objects, and a form
#: drawn to fill its content area exactly comes out a fraction of a point
#: over — enough, without this, to send its last row onto a page of its own.
_FIT_TOLERANCE = 1.5

_INDEX_SUFFIX = re.compile(r"\[\d+\]$")

Element = XfaField | XfaButton | XfaDraw


@dataclass(slots=True)
class PlacedPage:
    """One page of the converted document and everything on it."""

    width: float
    height: float
    fields: list[XfaField] = field(default_factory=list)
    buttons: list[XfaButton] = field(default_factory=list)
    draws: list[XfaDraw] = field(default_factory=list)


@dataclass(slots=True)
class LaidOutForm:
    """The template resolved into pages, ready to be drawn."""

    pages: list[PlacedPage] = field(default_factory=list)
    #: SOM of each repeatable subform -> how many instances were laid out.
    instances: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    @property
    def fields(self) -> list[XfaField]:
        return [f for page in self.pages for f in page.fields]

    @property
    def buttons(self) -> list[XfaButton]:
        return [b for page in self.pages for b in page.buttons]

    @property
    def draws(self) -> list[XfaDraw]:
        return [d for page in self.pages for d in page.draws]


@dataclass(slots=True)
class _Block:
    """Elements that go onto a page together or not at all."""

    id: int
    items: list[Element] = field(default_factory=list)
    #: A table's heading row, repeated at the top of each continuation page.
    is_leader: bool = False
    #: The heading row this block's table repeats, if it has one.
    leader: int | None = None
    #: Where the block asks to start, from its subform's break or the one
    #: before it.
    break_before: XfaBreak | None = None

    def extent(self) -> tuple[float, float] | None:
        """Top and bottom of the block's visible elements, or None."""
        shown = [item for item in self.items if not item.hidden and not _is_spacer(item)]
        if not shown:
            return None
        top = min(item.rect.y for item in shown)
        bottom = max(item.rect.y + max(item.rect.height, 0.0) for item in shown)
        return top, bottom


def _is_spacer(item: Element) -> bool:
    """An element that draws nothing and is there only to make room.

    Designers leave empty text objects at the foot of a section to push what
    follows down. On one page they do that; at a page break they are nothing,
    and letting one decide the break sent a block of signatures to a page of
    its own because the blank space under it did not fit.
    """
    return (
        isinstance(item, XfaDraw)
        and item.kind == "text"
        and not item.text
        and item.fill_color is None
        and not any(edge.draws for edge in item.edges)
    )


def _default_page(pages: list[XfaPageArea], index: int) -> XfaPageArea:
    """The page area for page *index*, repeating the last one if it runs out.

    A template that declares one page area and then overflows it is normal:
    XFA repeats the last area, which is how a one-page design produces a
    three-page form once the data is in it.
    """
    if not pages:
        return XfaPageArea()
    return pages[min(index, len(pages) - 1)]


def _content_boxes(area: XfaPageArea) -> list[tuple[float, float, float]]:
    """Left, top and bottom of each of the area's content regions, in points."""
    regions = [
        (region.x, region.y, region.y + region.height)
        for region in area.content_areas
        if region.height > 0
    ]
    if regions:
        return regions
    top = area.margin_top
    height = area.content_height
    if height <= 0:
        height = max(area.height - 2 * top, area.height * 0.5)
    return [(area.margin_left, top, top + height)]


def _content_box(area: XfaPageArea) -> tuple[float, float, float]:
    """The first content region: where a page's content starts."""
    return _content_boxes(area)[0]


def _region_named(area: XfaPageArea, target: str) -> int | None:
    """The index of the content region called *target*, by name or id."""
    for index, region in enumerate(area.content_areas):
        if target and target in (region.name, region.identifier):
            return index
    return None


def _instance_count(subform: XfaSubform) -> int:
    """How many copies of a repeatable subform to lay out.

    A copy the saved state already expanded is one copy. Otherwise
    ``initial`` is the template's own answer and is trusted first, because it
    is what the form was designed to open with; ``min`` is the floor. The cap
    is this module's, because ``max="-1"`` is unbounded and a real number has
    to come from somewhere.
    """
    if not subform.is_repeatable or subform.materialised:
        return 1
    count = max(subform.occur.initial, subform.occur.min, 1)
    if subform.occur.max > 0:
        count = min(count, subform.occur.max)
    return min(count, MAX_INSTANCES)


def _copy(item: Element, rect: XfaRect, instance: int, hidden: bool) -> Element:
    placed = type(item)(**{k: getattr(item, k) for k in item.__slots__})
    placed.rect = rect
    placed.instance = instance
    placed.hidden = item.hidden or hidden
    return placed


def _has_box(subform: XfaSubform) -> bool:
    return subform.fill_color is not None or any(edge.draws for edge in subform.edges)


class _Layout:
    """One run of the layout algorithm over one template."""

    def __init__(self, document: XfaDocument) -> None:
        self._document = document
        self._areas = document.template.pages
        self.result = LaidOutForm()
        self._blocks: list[_Block] = []
        self._sink: list[Element] | None = None
        self._pending_break: XfaBreak | None = None
        #: ``id()`` of a subform -> the block(s) it became, one per instance.
        self._blocks_of: dict[int, list[_Block]] = {}

    # -- blocks ------------------------------------------------------------
    def _new_block(self) -> _Block:
        block = _Block(id=len(self._blocks), break_before=self._pending_break)
        self._pending_break = None
        self._blocks.append(block)
        return block

    def _emit(self, placed: Element, block: _Block | None) -> None:
        if self._sink is not None:
            self._sink.append(placed)
            return
        if block is None:
            block = self._new_block()
        block.items.append(placed)

    # -- measuring ---------------------------------------------------------
    @staticmethod
    def _text_height(text: str, font, width: float, embed: bool) -> float:
        from orion.xfa.converter import ASCENT, DESCENT, LEADING, _font_name, wrap_text

        lines = wrap_text(text, _font_name(font, embed=embed), font.size, width)
        if not lines:
            return 0.0
        return ((len(lines) - 1) * LEADING + ASCENT + DESCENT) * font.size

    @staticmethod
    def _text_width(text: str, font) -> float:
        from reportlab.pdfbase.pdfmetrics import stringWidth

        from orion.xfa.converter import _font_name

        return stringWidth(text, _font_name(font), font.size)

    def _natural(self, item: Element, width: float) -> tuple[float, float]:
        """How wide and tall *item* comes out when *width* is what it gets."""
        rect = item.rect
        w = width if width > 0 else rect.width
        h = rect.height
        if isinstance(item, XfaDraw) and item.kind == "text" and item.text:
            insets = item.margins
            if item.auto_width and width <= 0:
                w = max(w, self._text_width(item.text, item.font) + insets.left + insets.right)
            if item.auto_height or h <= 0:
                inner = max(w - insets.left - insets.right, 1.0)
                needed = self._text_height(item.text, item.font, inner, True)
                h = max(h, needed + insets.top + insets.bottom)
        elif isinstance(item, XfaField) and item.grows and item.multiline and item.value:
            insets = item.margins
            # The same box the converter's appearance stream fills.
            inner = w - insets.left - insets.right - item.text_indent - 3.0
            if item.caption and item.caption_placement in ("left", "right"):
                inner -= item.caption_reserve
            needed = self._text_height(item.value, item.font, max(inner, 1.0), False)
            h = max(h, needed + insets.top + insets.bottom)
        return w, h

    def _content_width(self, subform: XfaSubform) -> float:
        """How wide a subform's content comes to, when it does not say."""
        if subform.rect.width > 0:
            return subform.rect.width
        right = 0.0
        for child in subform.content:
            if isinstance(child, XfaSubform):
                right = max(right, child.rect.x + self._content_width(child))
            else:
                right = max(right, child.rect.x + self._natural(child, 0.0)[0])
        return right

    @staticmethod
    def _span(columns: tuple[float, ...], cell: int, span: int) -> float:
        """The width of *span* columns from *cell*, or 0 when the table does not say."""
        if cell >= len(columns):
            return 0.0
        end = len(columns) if span == -1 else min(cell + max(span, 1), len(columns))
        return sum(columns[cell:end])

    # -- the walk ----------------------------------------------------------
    def _instances(self, child: XfaSubform) -> int:
        count = _instance_count(child)
        if child.is_repeatable:
            key = _INDEX_SUFFIX.sub("", child.som)
            if child.materialised:
                self.result.instances[key] = self.result.instances.get(key, 0) + 1
            else:
                self.result.instances[key] = count
        return count

    def _walk(
        self,
        subform: XfaSubform,
        dx: float,
        dy: float,
        instance: int,
        columns: tuple[float, ...] = (),
        hidden: bool = False,
        block: _Block | None = None,
        width: float = 0.0,
    ) -> float:
        """Lay out *subform* at (*dx*, *dy*) and return the height it used.

        *columns* is the enclosing table's column widths, handed down to its
        rows. *width* is the room the parent gives this subform when the
        subform does not say how wide it is — a table cell's column. *block*
        is what the elements belong to for pagination: a positioned subform
        or a row is one block, and everything inside it goes with it.
        """
        hidden = hidden or subform.hidden
        mode = subform.layout.lower()
        if subform.break_before is not None and block is None:
            self._pending_break = subform.break_before
        if block is None and mode not in _FLOWED and self._sink is None:
            block = self._new_block()
            self._blocks_of.setdefault(id(subform), []).append(block)

        own_width = subform.rect.width or width or self._content_width(subform)
        box = None
        # A flowed subform outside any block can break across pages, and one
        # box around both halves of it would be drawn across the break — so
        # only a subform that goes onto one page whole gets its border.
        if _has_box(subform) and (block is not None or self._sink is not None):
            box = XfaDraw(
                kind="text",
                rect=XfaRect(dx, dy, own_width, 0.0),
                edges=subform.edges,
                fill_color=subform.fill_color,
                parent_som=subform.som,
                instance=instance,
                hidden=hidden,
            )
            self._emit(box, block)

        if mode == "row":
            used = self._walk_row(subform, dx, dy, instance, columns, hidden, block)
        elif mode in _FLOWED:
            used = self._walk_flowed(subform, dx, dy, instance, hidden, block, own_width)
        else:
            used = self._walk_positioned(subform, dx, dy, instance, hidden, block)

        used = max(used, subform.rect.height)
        if box is not None:
            box.rect = XfaRect(dx, dy, own_width, used)
        if subform.break_after is not None and block is None:
            self._pending_break = subform.break_after
        return used

    def _place(
        self,
        item: Element,
        x: float,
        y: float,
        width: float,
        instance: int,
        hidden: bool,
        block: _Block | None,
    ) -> Element:
        w, h = self._natural(item, width)
        placed = _copy(item, XfaRect(x, y, w, h), instance, hidden)
        self._emit(placed, block)
        return placed

    def _walk_positioned(self, subform, dx, dy, instance, hidden, block) -> float:
        used = 0.0
        for child in subform.content:
            if isinstance(child, XfaSubform):
                for index in range(self._instances(child)):
                    who = index if _instance_count(child) > 1 else instance
                    height = self._walk(
                        child, dx + child.rect.x, dy + child.rect.y, who, (), hidden, block
                    )
                    used = max(used, child.rect.y + height)
                continue
            placed = self._place(
                child, dx + child.rect.x, dy + child.rect.y, 0.0, instance, hidden, block
            )
            used = max(used, child.rect.y + placed.rect.height)
        return used

    def _walk_flowed(self, subform, dx, dy, instance, hidden, block, own_width) -> float:
        mode = subform.layout.lower()
        across = mode in ("lr-tb", "rl-tb")
        columns = subform.column_widths if mode == "table" else ()
        cursor = 0.0  # down the subform
        line_x = 0.0  # across the current line, for lr-tb
        line_height = 0.0

        for child in subform.content:
            if isinstance(child, XfaSubform):
                for index in range(self._instances(child)):
                    who = index if _instance_count(child) > 1 else instance
                    child_hidden = hidden or child.hidden
                    if across:
                        wide = self._content_width(child)
                        if line_x > 0 and line_x + wide > own_width + _FIT_TOLERANCE:
                            cursor += line_height
                            line_x, line_height = 0.0, 0.0
                        height = self._walk(
                            child, dx + line_x, dy + cursor, who, (), child_hidden, block
                        )
                        line_x += wide
                        line_height = max(line_height, height)
                        continue
                    height = self._walk(
                        child, dx, dy + cursor, who, columns, child_hidden, block, own_width
                    )
                    cursor += max(height, 0.0)
                continue

            if across:
                wide = self._natural(child, 0.0)[0]
                if line_x > 0 and line_x + wide > own_width + _FIT_TOLERANCE:
                    cursor += line_height
                    line_x, line_height = 0.0, 0.0
                placed = self._place(child, dx + line_x, dy + cursor, 0.0, instance, hidden, block)
                line_x += placed.rect.width
                line_height = max(line_height, placed.rect.height)
                continue
            # ``<para spaceAbove>`` is not a gap between objects: it is room
            # above the element's own text, inside its box. Read as flow
            # spacing it made every row of a form taller than it was drawn,
            # which pushed the last row of a one-page request off the page.
            placed = self._place(child, dx, dy + cursor, 0.0, instance, hidden, block)
            cursor += placed.rect.height

        return cursor + line_height

    def _walk_row(self, subform, dx, dy, instance, columns, hidden, block) -> float:
        """One table row: cells across, each as wide as its columns, all as tall as the tallest."""
        cursor = 0.0
        cell = 0
        tallest = 0.0
        stretch: list[Element] = []
        for child in subform.content:
            span = getattr(child, "col_span", 1)
            width = self._span(columns, cell, span)
            if isinstance(child, XfaSubform):
                width = width or self._content_width(child)
                before = len(block.items) if block is not None else 0
                height = self._walk(child, dx + cursor, dy, instance, (), hidden, block, width)
                if block is not None and _has_box(child) and len(block.items) > before:
                    stretch.append(block.items[before])
            else:
                placed = self._place(child, dx + cursor, dy, width, instance, hidden, block)
                width = placed.rect.width
                height = placed.rect.height
                stretch.append(placed)
            tallest = max(tallest, height)
            cursor += width
            cell += len(columns) if span == -1 else max(span, 1)

        row_height = max(tallest, subform.rect.height) or DEFAULT_ROW_HEIGHT
        for item in stretch:
            item.rect = XfaRect(item.rect.x, item.rect.y, item.rect.width, row_height)
        return row_height

    # -- running -----------------------------------------------------------
    def run(self) -> LaidOutForm:
        root = self._document.template.root
        area = _default_page(self._areas, 0)
        left, top, _ = _content_box(area)
        self._walk_root(root, left, top)
        self._paginate()
        return self.result

    def _walk_root(self, root: XfaSubform, left: float, top: float) -> None:
        self._walk(root, left, top, 0)
        # Every row of a table that names a heading row repeats it. The rows
        # are found by object, because a saved form's rows are copies that
        # share one name.
        for sub in root.walk():
            if not sub.overflow_leader:
                continue
            leader = next((c for c in sub.children if c.name == sub.overflow_leader), None)
            headings = self._blocks_of.get(id(leader), []) if leader is not None else []
            if not headings:
                continue
            heading = headings[0]
            heading.is_leader = True
            for row in sub.children:
                if row is leader:
                    continue
                for row_block in self._blocks_of.get(id(row), []):
                    row_block.leader = heading.id

    def _regions(self, page: int) -> list[tuple[float, float, float]]:
        return _content_boxes(_default_page(self._areas, page))

    def _next_region(self, page: int, region: int) -> tuple[int, int]:
        """The content region after this one: further down the page, or the next page."""
        if region + 1 < len(self._regions(page)):
            return page, region + 1
        return page + 1, 0

    def _honour(
        self, request: XfaBreak, page: int, region: int, occupied: bool
    ) -> tuple[int, int]:
        """Where a block that asks for *request* goes, from (*page*, *region*).

        A break to a content area the layout is already in does nothing
        unless it says ``startNew`` — which is what lets a form mark every
        section "in the body area" without each one starting a page, and
        still send its signature block to the strip at the foot of the page.
        """
        area = _default_page(self._areas, page)
        if request.target_type == "contentArea":
            wanted = _region_named(area, request.target)
            if wanted is None:
                # "Any content area": staying in this one satisfies it.
                if not request.start_new or not occupied:
                    return page, region
                return self._next_region(page, region)
            if wanted == region and (not request.start_new or not occupied):
                return page, region
            if wanted > region:
                return page, wanted
            return page + 1, wanted
        named = request.target and request.target in (area.name, area.identifier)
        if not occupied or (named and not request.start_new):
            return page, region
        return page + 1, 0

    def _paginate(self) -> None:
        """Cut the galley into content regions and pages, keeping each block whole."""
        galley_left = _content_box(_default_page(self._areas, 0))[0]
        page, region = 0, 0
        shift = 0.0
        dx = 0.0
        occupied = False  # has the current region any content yet
        # (block, page, vertical shift, horizontal shift)
        assignments: list[tuple[_Block, int, float, float]] = []
        leader_copies: list[tuple[int, list[Element]]] = []
        pages_of: dict[int, int] = {}

        blocks = self._blocks
        for position, block in enumerate(blocks):
            extent = block.extent()
            if extent is None:
                assignments.append((block, page, shift, dx))
                continue
            top, bottom = extent

            target = (page, region)
            if block.break_before is not None:
                target = self._honour(block.break_before, page, region, occupied)
            overflow = False
            if target == (page, region) and occupied:
                content_bottom = self._regions(page)[region][2]
                if bottom - shift > content_bottom + _FIT_TOLERANCE:
                    overflow = True
                elif block.is_leader:
                    # A heading row alone at the foot of a page, with its
                    # first row on the next, reads as a mistake: keep it
                    # with the row.
                    following = next(
                        (b for b in blocks[position + 1 :] if b.extent() is not None), None
                    )
                    if following is not None and following.leader == block.id:
                        overflow = following.extent()[1] - shift > content_bottom + _FIT_TOLERANCE
                if overflow:
                    target = self._next_region(page, region)

            if target != (page, region):
                if target[0] >= MAX_PAGES:
                    self.result.warnings.append(
                        f"The form is longer than {MAX_PAGES} pages; the rest was left off."
                    )
                    break
                left_behind = page
                page, region = target
                left, content_top, _ = self._regions(page)[region]
                dx = left - galley_left
                carried = self._headings_before(assignments, left_behind) if overflow else []
                if carried:
                    # A section's heading goes over with the section.
                    first = carried[0][0].extent()
                    top = first[0] if first is not None else top
                shift = top - content_top
                for entry in carried:
                    index = assignments.index(entry)
                    assignments[index] = (entry[0], page, shift, dx)
                    pages_of[entry[0].id] = page
                leader = blocks[block.leader] if block.leader is not None else None
                if leader is not None and pages_of.get(leader.id, page) < page:
                    heading = leader.extent()
                    if heading is not None:
                        copies = [
                            _copy(
                                item,
                                item.rect.translated(dx, content_top - heading[0]),
                                item.instance,
                                False,
                            )
                            for item in leader.items
                        ]
                        leader_copies.append((page, copies))
                        shift -= heading[1] - heading[0]
                occupied = False

            _, region_top, region_bottom = self._regions(page)[region]
            if bottom - top > region_bottom - region_top + _FIT_TOLERANCE:
                self.result.warnings.append(
                    "A section of the form is taller than its area and was cut at the bottom."
                )
            assignments.append((block, page, shift, dx))
            pages_of[block.id] = page
            occupied = True

        total = page + 1
        for index in range(total):
            area = _default_page(self._areas, index)
            self.result.pages.append(PlacedPage(width=area.width, height=area.height))
            self._furnish(index, area, total)

        for block, number, offset, across in assignments:
            for item in block.items:
                item.rect = item.rect.translated(across, -offset)
                self._put(item, number)
        for number, copies in leader_copies:
            for item in copies:
                self._put(item, number)

        if total > 1:
            self.result.warnings.append(f"The form was laid out on {total} pages.")

    @staticmethod
    def _headings_before(
        assignments: list[tuple[_Block, int, float, float]], page: int
    ) -> list[tuple[_Block, int, float, float]]:
        """The heading blocks at the foot of *page*, which should not stay behind.

        A section title and the add/remove buttons under it carry no fields;
        left at the bottom of a page with the table they introduce on the next,
        they read as a section with nothing in it. Up to three of them move with
        what follows — never so many that the page is left empty.
        """
        carried: list[tuple[_Block, int, float, float]] = []
        for entry in reversed(assignments):
            block, number = entry[0], entry[1]
            if number != page:
                break
            if block.extent() is None:
                continue
            if any(isinstance(i, XfaField) and not i.hidden for i in block.items):
                break
            if len(carried) == 3:
                return []
            carried.insert(0, entry)
        else:
            return []  # nothing but headings on the page: leave them
        remaining = [
            entry
            for entry in assignments
            if entry[1] == page and entry not in carried and entry[0].extent() is not None
        ]
        return carried if remaining else []

    def _furnish(self, index: int, area: XfaPageArea, total: int) -> None:
        """The page area's own contents, on page *index* of *total*."""
        if not area.furniture.content:
            return
        self._sink = []
        try:
            self._walk(area.furniture, 0.0, 0.0, 0)
            placed = self._sink
        finally:
            self._sink = None
        for item in placed:
            if isinstance(item, XfaField) and item.page_counter:
                item.value = str(index + 1 if item.page_counter == "page" else total)
            if index:
                # Every page has its own copy of the furniture; the fields in
                # it need names of their own or they would fill in together.
                item.instance = index
            self._put(item, index)

    def _put(self, item: Element, number: int) -> None:
        page = self.result.pages[number]
        item.page = number
        if isinstance(item, XfaField):
            page.fields.append(item)
        elif isinstance(item, XfaButton):
            page.buttons.append(item)
        else:
            page.draws.append(item)


def resolve_layout(document: XfaDocument) -> LaidOutForm:
    """Resolve *document*'s template into pages of positioned elements.

    Never raises for an awkward template. A layout that cannot be worked out
    yields an empty page and a warning, because the caller's fallback — a
    static conversion of whatever the PDF already had — is better than an
    exception in the middle of the user's open.
    """
    try:
        form = _Layout(document).run()
    except RecursionError:
        log.warning("The XFA template nests too deeply to lay out", exc_info=True)
        return LaidOutForm(
            pages=[PlacedPage(width=595.276, height=841.89)],
            warnings=["The form's structure nests too deeply to lay out."],
        )
    except Exception as exc:  # pragma: no cover - defensive
        log.warning("Could not resolve the XFA layout", exc_info=True)
        return LaidOutForm(
            pages=[PlacedPage(width=595.276, height=841.89)],
            warnings=[f"The form's layout could not be worked out: {exc}"],
        )

    form.warnings.extend(document.warnings)
    if not form.pages:
        form.pages.append(PlacedPage(width=595.276, height=841.89))
    return form


def rect_to_pdf(rect: XfaRect, page_height: float) -> tuple[float, float, float, float]:
    """XFA's top-left box -> PDF's bottom-left ``(x, y, width, height)``.

    The one place the flip happens. Everything upstream works top-down, which
    is how the template is written, and everything downstream works bottom-up,
    which is how PDF is written.
    """
    return (rect.x, page_height - rect.y - rect.height, rect.width, rect.height)
