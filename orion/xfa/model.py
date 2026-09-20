# Orion — PDF Editor for Desktop
# Copyright (C) 2026 Marco Lombardo
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# Distributed WITHOUT ANY WARRANTY; see LICENSE for the full terms.
# A commercial licence, without the AGPL's obligations, is available for use
# in proprietary or closed-source products — see COMMERCIAL-LICENSE.md.

"""What an XFA form is, once it is out of the XML.

Plain dataclasses that know nothing about PDF libraries or about Qt. The point
of the indirection is that XFA is a large, strange and effectively frozen
specification: the parser deals with its shape once, and everything downstream
— layout, conversion, the report, the tests — works against something small
enough to reason about.

Coordinates are in **XFA units**, which are points once the parser has done
its conversion, with the origin at the top-left of the containing subform and
y growing downwards. That is XFA's own convention and it is kept as far as the
layout pass, which is the one place that turns it into a page coordinate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

__all__ = [
    "XfaBinding",
    "XfaButton",
    "XfaButtonKind",
    "XfaChoiceList",
    "XfaDocument",
    "XfaField",
    "XfaFieldType",
    "XfaFont",
    "XfaOccur",
    "XfaRect",
    "XfaScript",
    "XfaScriptKind",
    "XfaSubform",
    "XfaTemplate",
]


class XfaFieldType(str, Enum):
    """The control an XFA field presents.

    XFA calls these "UI types" and they are what decides which AcroForm widget
    a field becomes.
    """

    TEXT = "text"
    NUMERIC = "numeric"
    DATE = "date"
    CHECKBOX = "checkbox"
    RADIO = "radio"
    CHOICE = "choice"
    BUTTON = "button"
    SIGNATURE = "signature"
    IMAGE = "image"
    BARCODE = "barcode"
    #: A field whose UI element Orion does not model. Drawn, never interactive.
    UNKNOWN = "unknown"

    @property
    def is_interactive(self) -> bool:
        """Can this become a field the user types in or clicks?

        Signatures, images and barcodes are excluded on purpose. A signature
        widget that does not sign is worse than no widget, and neither an
        image nor a barcode has an AcroForm equivalent that would behave.
        """
        return self in (
            XfaFieldType.TEXT,
            XfaFieldType.NUMERIC,
            XfaFieldType.DATE,
            XfaFieldType.CHECKBOX,
            XfaFieldType.RADIO,
            XfaFieldType.CHOICE,
        )


class XfaButtonKind(str, Enum):
    """What a button was for, as far as the template admits."""

    #: Decorative, or its behaviour lives entirely in a script.
    PLAIN = "plain"
    SUBMIT = "submit"
    RESET = "reset"
    PRINT = "print"
    #: Adds or removes instances of a repeatable section. No AcroForm equal.
    INSTANCE = "instance"
    SCRIPTED = "scripted"


class XfaScriptKind(str, Enum):
    """Why a script is there. Classified, never run."""

    VALIDATION = "validation"
    CALCULATION = "calculation"
    INITIALIZATION = "initialization"
    EVENT_HANDLER = "event_handler"
    BUTTON_ACTION = "button_action"
    DYNAMIC_LAYOUT = "dynamic_layout"
    VISIBILITY = "visibility"
    ENABLE_DISABLE = "enable_disable"
    VALUE_ASSIGNMENT = "value_assignment"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class XfaRect:
    """A box in XFA space: top-left origin, y downwards, points."""

    x: float = 0.0
    y: float = 0.0
    width: float = 0.0
    height: float = 0.0

    def translated(self, dx: float, dy: float) -> XfaRect:
        return XfaRect(self.x + dx, self.y + dy, self.width, self.height)

    @property
    def is_empty(self) -> bool:
        return self.width <= 0.0 or self.height <= 0.0


@dataclass(frozen=True, slots=True)
class XfaFont:
    family: str = "Helvetica"
    size: float = 10.0
    bold: bool = False
    italic: bool = False
    #: RGB in 0..1, to match the rest of Orion.
    color: tuple[float, float, float] = (0.0, 0.0, 0.0)


@dataclass(frozen=True, slots=True)
class XfaBinding:
    """Where a field's value comes from in the datasets packet."""

    #: The ``ref``/``bind`` expression as written in the template.
    expression: str = ""
    #: ``once``, ``global``, ``none`` — XFA's ``match`` attribute.
    match: str = "once"


@dataclass(frozen=True, slots=True)
class XfaOccur:
    """How many times a subform may appear.

    ``max`` of -1 is XFA's "unbounded". What the converter does with this is
    limited and deliberately so: it keeps the instances that exist and says in
    the report that the form can no longer grow.
    """

    min: int = 1
    max: int = 1
    initial: int = 1

    @property
    def is_repeatable(self) -> bool:
        return self.max == -1 or self.max > 1


@dataclass(frozen=True, slots=True)
class XfaScript:
    """A script found in the template. Its text is data, never code."""

    kind: XfaScriptKind
    #: The SOM expression of the node it hangs off.
    owner: str
    #: The XFA event that would fire it: ``click``, ``initialize``, ``calculate``…
    event: str
    source: str
    #: ``formcalc`` or ``javascript``.
    language: str = "javascript"

    @property
    def convertible(self) -> bool:
        """Whether an equivalent could exist in a plain AcroForm.

        Always False, and that is a statement about AcroForm rather than about
        effort. XFA scripts address a live form object model — subforms,
        instance managers, SOM expressions, layout — that simply is not there
        once the form is an AcroForm. Translating the text would produce
        JavaScript that referenced things the document does not have.
        """
        return False

    @property
    def reason(self) -> str:
        return (
            "XFA scripts act on a form object model (subforms, instance "
            "managers, SOM expressions, layout) that a standard PDF form does "
            "not have."
        )


@dataclass(frozen=True, slots=True)
class XfaChoiceList:
    """The options behind a choice field."""

    #: What the user reads.
    labels: tuple[str, ...] = ()
    #: What gets stored. Falls back to the labels when the template gives none.
    values: tuple[str, ...] = ()
    open: bool = False
    multi_select: bool = False

    @property
    def editable(self) -> bool:
        """May the user type an answer that is not in the list?

        XFA's ``open="userControl"``. A drop-down converted without it becomes
        a fixed list, and an answer the form allowed can no longer be given.
        """
        return self.open and not self.multi_select

    @property
    def pairs(self) -> tuple[tuple[str, str], ...]:
        """(label, value), with the label standing in for a missing value."""
        values = self.values or self.labels
        return tuple(
            (label, values[index] if index < len(values) else label)
            for index, label in enumerate(self.labels)
        )


@dataclass(slots=True)
class XfaField:
    """One control in the form."""

    name: str
    field_type: XfaFieldType = XfaFieldType.TEXT
    som: str = ""
    identifier: str = ""
    caption: str = ""
    value: str = ""
    default_value: str = ""
    rect: XfaRect = field(default_factory=XfaRect)
    #: Filled in by the layout pass; -1 until then.
    page: int = -1
    font: XfaFont = field(default_factory=XfaFont)
    multiline: bool = False
    read_only: bool = False
    mandatory: bool = False
    max_length: int = 0
    #: XFA ``picture`` clause — the display format, e.g. ``DD/MM/YYYY``.
    picture: str = ""
    #: ``<assist><toolTip>``: the help the form itself offers for this field.
    tooltip: str = ""
    #: ``<caption reserve="…">`` in points: how much of the field's own box the
    #: label takes. The template's answer, which is what lines every label in a
    #: section up with every other; 0 means it did not say.
    caption_reserve: float = 0.0
    #: ``left`` (XFA's default), ``right``, ``top``, ``bottom``, ``inline``.
    caption_placement: str = "left"
    validation_pattern: str = ""
    choices: XfaChoiceList | None = None
    binding: XfaBinding = field(default_factory=XfaBinding)
    data_type: str = ""
    #: ``open``, ``readOnly``, ``protected``, ``nonInteractive``.
    access: str = "open"
    scripts: tuple[XfaScript, ...] = ()
    #: Set for radio buttons: every member of one group shares it.
    group: str = ""
    export_value: str = ""
    #: SOM of the subform this sits in, for tracing a conversion back.
    parent_som: str = ""
    #: Which instance of a repeated subform this came from. 0 when unique.
    instance: int = 0
    border_width: float = 0.0
    border_color: tuple[float, float, float] = (0.0, 0.0, 0.0)
    fill_color: tuple[float, float, float] | None = None
    #: The template hides this until something reveals it — see
    #: :func:`orion.xfa.parser.is_hidden`.
    hidden: bool = False

    @property
    def has_scripts(self) -> bool:
        return bool(self.scripts)

    @property
    def is_interactive(self) -> bool:
        """Convertible into something the user can actually operate."""
        if self.access in ("protected", "nonInteractive"):
            return False
        return self.field_type.is_interactive

    @property
    def qualified_name(self) -> str:
        """A name unique across the document, for the AcroForm field tree.

        An XFA name only has to be unique among its siblings, whereas an
        AcroForm field name has to be unique in the file — so a repeated
        subform full of identically-named fields would otherwise collapse into
        one. The instance number keeps them apart.
        """
        base = self.som or self.name
        if self.instance:
            return f"{base}[{self.instance}]"
        return base


@dataclass(slots=True)
class XfaButton:
    """A button. Kept apart from fields because it never holds a value."""

    name: str
    kind: XfaButtonKind = XfaButtonKind.PLAIN
    caption: str = ""
    som: str = ""
    rect: XfaRect = field(default_factory=XfaRect)
    page: int = -1
    font: XfaFont = field(default_factory=XfaFont)
    scripts: tuple[XfaScript, ...] = ()
    parent_som: str = ""
    instance: int = 0
    hidden: bool = False


@dataclass(slots=True)
class XfaSubform:
    """A container. Subforms nest, and they are what gives a form its shape."""

    name: str = ""
    som: str = ""
    rect: XfaRect = field(default_factory=XfaRect)
    #: ``position`` places children by coordinate; ``tb``/``lr-tb`` flow them;
    #: ``table`` stacks rows and ``row`` runs its cells across.
    layout: str = "position"
    #: A table's column widths in points, in order. Cells take their width and
    #: their horizontal position from these rather than from their own ``x``,
    #: which they normally do not have.
    column_widths: tuple[float, ...] = ()
    occur: XfaOccur = field(default_factory=XfaOccur)
    children: list[XfaSubform] = field(default_factory=list)
    fields: list[XfaField] = field(default_factory=list)
    buttons: list[XfaButton] = field(default_factory=list)
    #: Lines, rectangles and static text: the visual furniture.
    draws: list[XfaDraw] = field(default_factory=list)
    #: Every child again, in the order the template wrote them. The typed
    #: lists above are for looking things up; this is what layout walks,
    #: because a flowed subform stacks its children in document order and
    #: fields, draws and nested subforms all take their turn in that queue.
    content: list[object] = field(default_factory=list)
    scripts: tuple[XfaScript, ...] = ()
    #: True when this subform begins a new page in the template.
    page_break_before: bool = False
    instance: int = 0
    #: The template hides this subform, and everything in it, until something
    #: reveals it.
    hidden: bool = False

    @property
    def is_repeatable(self) -> bool:
        return self.occur.is_repeatable

    def walk(self):
        """This subform and every subform beneath it, outermost first."""
        yield self
        for child in self.children:
            yield from child.walk()

    def all_fields(self) -> list[XfaField]:
        return [f for sub in self.walk() for f in sub.fields]

    def all_buttons(self) -> list[XfaButton]:
        return [b for sub in self.walk() for b in sub.buttons]

    def all_draws(self) -> list[XfaDraw]:
        return [d for sub in self.walk() for d in sub.draws]


@dataclass(slots=True)
class XfaDraw:
    """Something drawn but never filled in: a caption, a rule, a box.

    These carry the form's appearance, and for a dynamic XFA they are the only
    record of it that exists — so they matter as much as the fields do.
    """

    #: ``text``, ``line``, ``rectangle``, ``image``.
    kind: str = "text"
    text: str = ""
    rect: XfaRect = field(default_factory=XfaRect)
    page: int = -1
    font: XfaFont = field(default_factory=XfaFont)
    #: ``left``, ``center``, ``right``.
    align: str = "left"
    line_width: float = 0.0
    line_color: tuple[float, float, float] = (0.0, 0.0, 0.0)
    fill_color: tuple[float, float, float] | None = None
    parent_som: str = ""
    instance: int = 0
    hidden: bool = False


@dataclass(slots=True)
class XfaPageArea:
    """A page as the template describes it, in points."""

    name: str = ""
    width: float = 595.276  # A4, which is what an unmarked template means here
    height: float = 841.89
    margin_left: float = 0.0
    margin_top: float = 0.0
    #: What the page itself carries rather than the form: the header band, the
    #: logo, the page number. XFA calls a page area's own children furniture,
    #: and it repeats on every page the area is used for. Positioned against
    #: the page corner, not against the content area.
    furniture: XfaSubform = field(default_factory=XfaSubform)


@dataclass(slots=True)
class XfaTemplate:
    """The form's design: its pages and the tree of subforms on them."""

    root: XfaSubform = field(default_factory=XfaSubform)
    pages: list[XfaPageArea] = field(default_factory=list)

    @property
    def page_count(self) -> int:
        return max(1, len(self.pages))


@dataclass(slots=True)
class XfaDocument:
    """A parsed XFA form, and what was learned while parsing it."""

    template: XfaTemplate = field(default_factory=XfaTemplate)
    #: Field SOM/name -> value, read out of the datasets packet.
    data: dict[str, str] = field(default_factory=dict)
    #: Packets that were present in the file.
    packet_names: tuple[str, ...] = ()
    #: Anything the parser could not make sense of but did not want to lose.
    warnings: list[str] = field(default_factory=list)

    @property
    def _containers(self) -> list[XfaSubform]:
        """The form's tree, and every page area's furniture with it.

        Page furniture is part of the document even though it sits outside the
        subform tree — the title in a page's header is a field like any other,
        and the data packet has a value for it.
        """
        return [self.template.root] + [area.furniture for area in self.template.pages]

    @property
    def fields(self) -> list[XfaField]:
        return [f for container in self._containers for f in container.all_fields()]

    @property
    def buttons(self) -> list[XfaButton]:
        return [b for container in self._containers for b in container.all_buttons()]

    @property
    def draws(self) -> list[XfaDraw]:
        return [d for container in self._containers for d in container.all_draws()]

    @property
    def scripts(self) -> list[XfaScript]:
        found: list[XfaScript] = []
        for subform in self.template.root.walk():
            found.extend(subform.scripts)
            for item in subform.fields:
                found.extend(item.scripts)
            for button in subform.buttons:
                found.extend(button.scripts)
        return found

    @property
    def repeatable_subforms(self) -> list[XfaSubform]:
        return [s for s in self.template.root.walk() if s.is_repeatable]
