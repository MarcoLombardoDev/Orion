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

XFA lays out in two modes and the tree mixes them freely:

* **position** — children sit at their own ``x``/``y`` within the parent.
  Coordinates are relative, so they accumulate down the tree.
* **tb** (and ``lr-tb``) — children *flow*: each is placed below the last, and
  its own ``y`` is an offset from that running position rather than from the
  parent's origin. A flowed subform's height is what its content came to, not
  what the attribute claims.
* **table** and **row** — a table flows its rows downwards like ``tb``; a row
  flows its cells *across*, each to the right of the last. Cells almost never
  carry an ``x``, because their position is the sum of the widths before them.
  Treating a row as positioned puts every cell at the same place, which reads
  as one line of overlapping words where the table should be.

Repeatable subforms are materialised here, once per instance that the form
already has. That is the honest half of the dynamic story: the instances that
exist are laid out and converted, the ability to add more is not carried over,
and the report says so.

Everything leaves here in **page coordinates, still top-left origin and y
downwards**. The flip to PDF's bottom-left happens once, in the converter,
because doing it earlier means doing it in several places.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from orion.xfa.model import (
    XfaButton,
    XfaDocument,
    XfaDraw,
    XfaField,
    XfaPageArea,
    XfaRect,
    XfaSubform,
)

__all__ = ["LaidOutForm", "PlacedPage", "paginate", "rect_to_pdf", "resolve_layout"]

log = logging.getLogger(__name__)

#: What to give a table row whose cells all declare a width and no height.
#: Roughly one line of 10pt text with room around it, which is what such a
#: row comes out as in a real viewer.
DEFAULT_ROW_HEIGHT = 18.0

#: A guard against a template that would otherwise paginate forever.
MAX_PAGES = 200

#: How many instances of one repeatable subform to materialise, whatever the
#: template claims. ``max="-1"`` means unbounded, and a converter that took
#: that literally would never finish.
MAX_INSTANCES = 100


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


def _sized(rect: XfaRect, height: float = 0.0, width: float = 0.0) -> XfaRect:
    """*rect*, filled out with a height or width it does not have of its own."""
    if height > 0 and rect.height <= 0:
        rect = XfaRect(rect.x, rect.y, rect.width, height)
    if width > 0 and rect.width <= 0:
        rect = XfaRect(rect.x, rect.y, width, rect.height)
    return rect


def _default_page(pages: list[XfaPageArea], index: int) -> XfaPageArea:
    """The page area for page *index*, repeating the last one if it runs out.

    A template that declares one page area and then overflows it is normal:
    XFA repeats the last area, which is how a one-page design produces a
    three-page form once the data is in it.
    """
    if not pages:
        return XfaPageArea()
    return pages[min(index, len(pages) - 1)]


def _instance_count(subform: XfaSubform, data_hint: int | None = None) -> int:
    """How many copies of a repeatable subform to lay out.

    ``initial`` is the template's own answer and is trusted first, because it
    is what the form was designed to open with. ``min`` is the floor. The cap
    is this module's, because ``max="-1"`` is unbounded and a real number has
    to come from somewhere.
    """
    if not subform.is_repeatable:
        return 1
    count = data_hint if data_hint is not None else subform.occur.initial
    count = max(count, subform.occur.min, 1)
    if subform.occur.max > 0:
        count = min(count, subform.occur.max)
    return min(count, MAX_INSTANCES)


class _Layout:
    """One run of the layout algorithm over one template."""

    def __init__(self, document: XfaDocument) -> None:
        self._document = document
        self._areas = document.template.pages
        self.result = LaidOutForm()
        self._page_index = -1
        self._cursor = 0.0  # how far down the current page we have got
        self._new_page()

    # -- pages -------------------------------------------------------------
    def _new_page(self) -> PlacedPage:
        self._page_index += 1
        area = _default_page(self._areas, self._page_index)
        page = PlacedPage(width=area.width, height=area.height)
        self.result.pages.append(page)
        self._cursor = area.margin_top
        # The page's own furniture goes down first, at the page corner rather
        # than inside the content area, and again on every page: that is what
        # makes it furniture rather than content.
        if area.furniture.content:
            self._walk(area.furniture, 0.0, 0.0, 0)
        return page

    @property
    def _page(self) -> PlacedPage:
        return self.result.pages[self._page_index]

    @property
    def _margin_left(self) -> float:
        return _default_page(self._areas, self._page_index).margin_left

    def _room_left(self) -> float:
        area = _default_page(self._areas, self._page_index)
        return self._page.height - area.margin_top - self._cursor

    # -- placing -----------------------------------------------------------
    def _place_field(
        self,
        item: XfaField,
        dx: float,
        dy: float,
        instance: int,
        height: float = 0.0,
        width: float = 0.0,
        hidden: bool = False,
    ) -> None:
        placed = XfaField(**{k: getattr(item, k) for k in item.__slots__})
        placed.rect = _sized(item.rect.translated(dx, dy), height, width)
        placed.page = self._page_index
        placed.instance = instance
        placed.hidden = item.hidden or hidden
        self._page.fields.append(placed)

    def _place_button(
        self,
        item: XfaButton,
        dx: float,
        dy: float,
        instance: int,
        height: float = 0.0,
        width: float = 0.0,
        hidden: bool = False,
    ) -> None:
        placed = XfaButton(**{k: getattr(item, k) for k in item.__slots__})
        placed.rect = _sized(item.rect.translated(dx, dy), height, width)
        placed.page = self._page_index
        placed.instance = instance
        placed.hidden = item.hidden or hidden
        self._page.buttons.append(placed)

    def _place_draw(
        self,
        item: XfaDraw,
        dx: float,
        dy: float,
        instance: int,
        height: float = 0.0,
        width: float = 0.0,
        hidden: bool = False,
    ) -> None:
        placed = XfaDraw(**{k: getattr(item, k) for k in item.__slots__})
        placed.rect = _sized(item.rect.translated(dx, dy), height, width)
        placed.page = self._page_index
        placed.instance = instance
        placed.hidden = item.hidden or hidden
        self._page.draws.append(placed)

    # -- the walk ----------------------------------------------------------
    def _content_height(self, subform: XfaSubform) -> float:
        """How tall a subform's content comes to.

        The declared height wins when there is one. Otherwise it is measured
        from the children, because a flowed subform usually declares none and
        stacking them at zero height would pile everything on one line.
        """
        if subform.rect.height > 0:
            return subform.rect.height
        bottom = 0.0
        for item in list(subform.fields) + list(subform.buttons):
            bottom = max(bottom, item.rect.y + item.rect.height)
        for draw in subform.draws:
            bottom = max(bottom, draw.rect.y + draw.rect.height)
        for child in subform.children:
            bottom = max(bottom, child.rect.y + self._content_height(child))
        return bottom

    def _content_width(self, subform: XfaSubform) -> float:
        """How wide a subform's content comes to — a row's cursor step."""
        if subform.rect.width > 0:
            return subform.rect.width
        right = 0.0
        for child in subform.content:
            if isinstance(child, XfaSubform):
                right = max(right, child.rect.x + self._content_width(child))
            else:
                rect = getattr(child, "rect", XfaRect())
                right = max(right, rect.x + rect.width)
        return right

    @staticmethod
    def _column(columns: tuple[float, ...], index: int) -> float:
        """The width of column *index*, or 0 when the table does not say."""
        return columns[index] if index < len(columns) else 0.0

    def _row_height(self, subform: XfaSubform) -> float:
        """How tall one table row is: its tallest cell.

        Cells in a row routinely declare a width and no height at all, so
        without this they would be placed as zero-height boxes — present in
        the file and impossible to click.
        """
        if subform.rect.height > 0:
            return subform.rect.height
        tallest = 0.0
        for child in subform.content:
            if isinstance(child, XfaSubform):
                tallest = max(tallest, self._content_height(child))
            else:
                tallest = max(tallest, getattr(child, "rect", XfaRect()).height)
        return tallest if tallest > 0 else DEFAULT_ROW_HEIGHT

    def _walk(
        self,
        subform: XfaSubform,
        dx: float,
        dy: float,
        instance: int,
        columns: tuple[float, ...] = (),
        hidden: bool = False,
    ) -> float:
        """Lay out *subform* at (*dx*, *dy*) and return the height it used.

        A **positioned** subform places every child at the child's own
        coordinates. A **flowed** one stacks them in document order, each
        below the last — and that includes fields and draws, not only nested
        subforms, which is why the model keeps a single ordered ``content``
        list rather than only the typed ones. A **row** does the same thing
        sideways, which is the one case where the running cursor is an ``x``.

        *columns* is the enclosing table's column widths, handed down because
        a row's cells take their width and their position from the table and
        carry neither themselves. *hidden* travels the same way: a subform the
        template hides hides everything inside it, and the converter needs to
        know that about each element rather than about its ancestry.
        """
        hidden = hidden or subform.hidden
        mode = subform.layout.lower()
        across = mode in ("row", "lr")
        flowed = mode in ("tb", "lr-tb", "table")
        used = subform.rect.height if subform.rect.height > 0 else 0.0
        row_height = self._row_height(subform) if across else 0.0
        below = subform.column_widths if mode == "table" else ()
        cell = 0
        cursor = 0.0

        for child in subform.content:
            if isinstance(child, XfaSubform):
                count = _instance_count(child)
                if child.is_repeatable:
                    self.result.instances[child.som] = count
                for index in range(count):
                    who = index if count > 1 else instance
                    if across:
                        width = self._column(columns, cell) or self._content_width(child)
                        left = dx + cursor + child.rect.x
                        height = self._walk(
                            child, left, dy + child.rect.y, who, (), hidden
                        )
                        cursor += child.rect.x + width
                        cell += 1
                        used = max(used, child.rect.y + height)
                        continue
                    top = dy + (cursor if flowed else 0.0) + child.rect.y
                    height = self._walk(child, dx + child.rect.x, top, who, below, hidden)
                    if flowed:
                        cursor += child.rect.y + max(height, 0.0)
                        used = max(used, cursor)
                    else:
                        used = max(used, child.rect.y + height)
                continue

            left = dx + (cursor if across else 0.0)
            top = dy + (cursor if flowed else 0.0)
            height = row_height if across else 0.0
            column = self._column(columns, cell) if across else 0.0
            if isinstance(child, XfaField):
                self._place_field(child, left, top, instance, height, column, hidden)
            elif isinstance(child, XfaButton):
                self._place_button(child, left, top, instance, height, column, hidden)
            elif isinstance(child, XfaDraw):
                self._place_draw(child, left, top, instance, height, column, hidden)
            else:  # pragma: no cover - the model has no other child kind
                continue

            if across:
                cursor += child.rect.x + (column or max(child.rect.width, 0.0))
                cell += 1
                used = max(used, child.rect.y + max(child.rect.height, row_height))
                continue

            reach = child.rect.y + max(child.rect.height, 0.0)
            if flowed:
                cursor += reach
                used = max(used, cursor)
            else:
                used = max(used, reach)

        return used if used > 0 else self._content_height(subform)

    def run(self) -> LaidOutForm:
        root = self._document.template.root
        area = _default_page(self._areas, 0)
        self._walk(root, area.margin_left, area.margin_top, 0)
        paginate(self.result)
        return self.result


def paginate(form: LaidOutForm) -> None:
    """Move anything that fell off the bottom onto a page of its own.

    A flowed template can run past its page area — that is what flowing means,
    and it is exactly the case where a real XFA viewer would add a page. Rather
    than let content vanish below the crop box, it is moved down to a new page
    keeping its horizontal position, which preserves columns.
    """
    if not form.pages:
        return
    first = form.pages[0]
    page_height = first.height
    if page_height <= 0:
        return

    overflow_start = page_height
    moved = 0

    def bottom_of(item) -> float:
        return item.rect.y + max(item.rect.height, 0.0)

    while True:
        page = form.pages[-1]
        spilled_fields = [f for f in page.fields if f.rect.y >= overflow_start]
        spilled_buttons = [b for b in page.buttons if b.rect.y >= overflow_start]
        spilled_draws = [d for d in page.draws if d.rect.y >= overflow_start]
        if not (spilled_fields or spilled_buttons or spilled_draws):
            break
        if len(form.pages) >= MAX_PAGES:
            form.warnings.append(
                f"The form is longer than {MAX_PAGES} pages; the rest was left off."
            )
            for item in spilled_fields:
                page.fields.remove(item)
            for item in spilled_buttons:
                page.buttons.remove(item)
            for item in spilled_draws:
                page.draws.remove(item)
            break

        highest = min(
            [i.rect.y for i in spilled_fields + spilled_buttons + spilled_draws]
        )
        shift = highest - 20.0  # a small top margin on the continuation page

        following = PlacedPage(width=page.width, height=page.height)
        for item in spilled_fields:
            page.fields.remove(item)
            item.rect = item.rect.translated(0.0, -shift)
            item.page = len(form.pages)
            following.fields.append(item)
        for item in spilled_buttons:
            page.buttons.remove(item)
            item.rect = item.rect.translated(0.0, -shift)
            item.page = len(form.pages)
            following.buttons.append(item)
        for item in spilled_draws:
            page.draws.remove(item)
            item.rect = item.rect.translated(0.0, -shift)
            item.page = len(form.pages)
            following.draws.append(item)
        moved += len(following.fields) + len(following.buttons) + len(following.draws)
        form.pages.append(following)

    if moved:
        form.warnings.append(
            f"The form ran past one page; {moved} element(s) continue on following pages."
        )


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
