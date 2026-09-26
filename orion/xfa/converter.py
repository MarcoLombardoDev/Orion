# Orion — PDF Editor for Desktop
# Copyright (C) 2026 Marco Lombardo
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# Distributed WITHOUT ANY WARRANTY; see LICENSE for the full terms.
# A commercial licence, without the AGPL's obligations, is available for use
# in proprietary or closed-source products — see COMMERCIAL-LICENSE.md.

"""Writing the converted document.

The output is an ordinary PDF: a drawn page, and real AcroForm widgets on top
of it. reportlab does both — it is already one of Orion's dependencies, it
draws, and its ``canvas.acroForm`` creates genuine form fields rather than
pictures of them. No new dependency was needed for any of this.

Two layers, drawn in this order:

1. **The static layer** — captions, rules, boxes, backgrounds, and any field
   that could not become interactive, painted as content. This is where the
   form's appearance lives, and for a dynamic XFA it is the *only* place it
   has ever lived, since the original pages carry a placeholder.
2. **The fields** — one AcroForm widget per convertible XFA field, in the same
   place, with the same value, options and constraints.

What a field becomes:

===================  =========================================================
XFA                  AcroForm
===================  =========================================================
textEdit             text field (multiline when the template says so)
numericEdit          text field, digits-only format
dateTimeEdit         text field; the picture clause becomes the field's tooltip
checkButton          checkbox, with its export value
exclGroup            one radio group; each member a widget with its own value
choiceList           combo box — editable when XFA's ``open="userControl"`` —
                     or list box when it allows several
button               drawn, never live — see below
===================  =========================================================

Required and read-only travel with the field, and so does the help text the
form offers for it. A date's picture clause cannot be enforced without the
scripting that a standard form has nowhere to put, so it is carried as words:
the field can no longer *make* you write ``DD/MM/YYYY``, but it still says so.

Buttons are deliberately not recreated as AcroForm buttons. An XFA button does
whatever its script says, and the scripts do not survive (see
:class:`~orion.xfa.model.XfaScript`), so a button that looked live and did
nothing would be a worse outcome than a button that plainly is not. They are
drawn, and the report says what each one used to do.

The source document is opened read-only and never written to. Every conversion
produces a new file.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

from orion.xfa.checks import check_layout
from orion.xfa.detector import FormInfo, inspect_form
from orion.xfa.layout import LaidOutForm, rect_to_pdf, resolve_layout
from orion.xfa.model import (
    XfaButton,
    XfaButtonKind,
    XfaDocument,
    XfaDraw,
    XfaField,
    XfaFieldType,
    XfaFont,
    XfaInsets,
    XfaRect,
)
from orion.xfa.parser import parse_xfa
from orion.xfa.pictures import display_value
from orion.xfa.report import ConversionMode, XfaConversionReport

__all__ = ["ConversionResult", "convert_xfa", "convert_xfa_file"]

log = logging.getLogger(__name__)

#: reportlab knows these by name; anything else is mapped onto one of them.
_BASE_FONTS = {
    "helvetica": "Helvetica",
    "arial": "Helvetica",
    "times": "Times-Roman",
    "times new roman": "Times-Roman",
    "timesnewroman": "Times-Roman",
    "courier": "Courier",
    "courier new": "Courier",
    "myriad pro": "Helvetica",
    "verdana": "Helvetica",
    "calibri": "Helvetica",
    "tahoma": "Helvetica",
}

#: Trimmed off a field name so the AcroForm tree stays flat and predictable.
_NAME_CLEAN = re.compile(r"[^A-Za-z0-9_.\[\]-]")


class ConversionResult:
    """What came out: the file, the report, and the model behind it."""

    __slots__ = ("document", "form", "output", "report")

    def __init__(
        self,
        output: Path | None,
        report: XfaConversionReport,
        document: XfaDocument | None = None,
        form: LaidOutForm | None = None,
    ) -> None:
        self.output = output
        self.report = report
        self.document = document
        self.form = form

    @property
    def succeeded(self) -> bool:
        return self.report.succeeded


def _font_name(font: XfaFont, *, embed: bool = True) -> str:
    """The font to draw *font* with, embedding the real one where it exists.

    A form's typeface is part of how it reads, and the reference document is
    set in Arial and Arial Narrow — neither of which is a base-14 font. So the
    static layer asks Orion's own font resolver, which finds the family
    installed on this machine and embeds a subset of it exactly as the editor
    does for a text object the user types. A family that is not installed
    falls back to the metric-compatible base-14 below, which is why Arial and
    Helvetica share a row: the text still occupies the same width.

    **Form fields are the exception**, hence *embed*. reportlab refuses any
    font that is not one of the standard 14 when it builds a widget — it
    raises rather than substitutes — so a field the user types into is drawn
    with the base-14 stand-in. The visible difference is confined to text
    somebody types after the conversion; everything the form itself prints is
    in the form's own face.
    """
    if embed:
        resolved = _embedded_font(font)
        if resolved:
            return resolved
    return _base14_name(font)


def _embedded_font(font: XfaFont) -> str:
    """The installed face for this family, or "" if there is not one."""
    try:
        from orion.pdf.fonts import FontRequest, resolve

        found = resolve(FontRequest(font.family.strip(), font.bold, font.italic))
    except Exception:  # pragma: no cover - a font scan is never worth a failure
        log.debug("Could not resolve the font %r", font.family, exc_info=True)
        return ""
    return "" if found.substituted or not found.embedded else found.name


def _base14_name(font: XfaFont) -> str:
    """The standard-14 font closest to what the template asked for."""
    base = _BASE_FONTS.get(font.family.strip().lower(), "Helvetica")
    if base == "Times-Roman":
        if font.bold and font.italic:
            return "Times-BoldItalic"
        if font.bold:
            return "Times-Bold"
        if font.italic:
            return "Times-Italic"
        return "Times-Roman"
    if base == "Courier":
        if font.bold and font.italic:
            return "Courier-BoldOblique"
        if font.bold:
            return "Courier-Bold"
        if font.italic:
            return "Courier-Oblique"
        return "Courier"
    if font.bold and font.italic:
        return "Helvetica-BoldOblique"
    if font.bold:
        return "Helvetica-Bold"
    if font.italic:
        return "Helvetica-Oblique"
    return "Helvetica"


def _tooltip(field: XfaField) -> str:
    """What to show when the pointer rests on the field.

    The template's own help text, and the format it expects. The format is
    worth carrying because it is the one piece of a date field's behaviour
    that survives as words: the field itself can no longer enforce
    ``DD/MM/YYYY``, but it can still say so.
    """
    parts = [field.tooltip.strip()] if field.tooltip.strip() else []
    picture = _plain_picture(field.picture)
    if picture:
        # A picture clause is usually a format — DD/MM/YYYY — but a text field
        # often carries a quoted literal instead, which is the form prompting
        # the user rather than telling them a shape. Calling that "Format"
        # would turn a helpful sentence into a nonsensical one.
        literal = picture.startswith("'") and picture.endswith("'") and len(picture) > 1
        parts.append(picture.strip("'") if literal else f"Format: {picture}")
    return " — ".join(part for part in parts if part)


def _plain_picture(picture: str) -> str:
    """``num{zzz9}`` and ``date{DD/MM/YYYY}`` reduced to what they show."""
    if not picture:
        return ""
    inner = re.search(r"\{([^}]*)\}", picture)
    text = (inner.group(1) if inner else picture).strip()
    return text if text and text.lower() not in ("null", "none") else ""


def _safe_name(name: str, used: set[str]) -> str:
    """A field name that is legal, and unique in this document.

    AcroForm names must be unique across the file, while XFA names only have
    to be unique among siblings — so two rows of a repeated table both holding
    ``item`` would otherwise become one field that fills in twice.
    """
    cleaned = _NAME_CLEAN.sub("_", name).strip("._") or "field"
    candidate = cleaned
    counter = 2
    while candidate in used:
        candidate = f"{cleaned}_{counter}"
        counter += 1
    used.add(candidate)
    return candidate


def _split_for_caption(
    field: XfaField, page_height: float
) -> tuple[tuple[float, float, float, float] | None, tuple[float, float, float, float]]:
    """Divide a field's box into the label's part and the widget's part.

    XFA keeps a field's label *inside* the field's own rectangle and says how
    much room it takes with ``reserve`` — the template's own measurement,
    which is what lines every label in a section up with every other. Orion
    used to measure the text instead, so the boxes started wherever the words
    happened to end and a column of labels arrived ragged.

    ``placement`` decides which side is taken. Left is XFA's default and by
    far the common case; the others are handled because a form that uses them
    would otherwise have its labels drawn on top of its own fields.

    Returns ``(caption_rect, box_rect)`` in PDF coordinates, the first being
    ``None`` when there is no caption to draw.
    """
    x, y, width, height = rect_to_pdf(field.rect, page_height)
    if not field.caption:
        return None, (x, y, width, height)

    # The label sits inside the field's *content* area, which the template's
    # margins inset — nineteen points of it on one field of the reference
    # form, which is the difference between its label lining up with the two
    # above it and starting half an inch to their left. The widget keeps the
    # full box, because the border belongs to the box and not to the content.
    inset = field.margins.left
    placement = (field.caption_placement or "left").lower()
    if placement in ("top", "bottom"):
        reserve = field.caption_reserve or field.font.size * 1.25
        reserve = min(reserve, max(height - 8.0, 0.0))
        if reserve <= 0:
            return None, (x, y, width, height)
        if placement == "top":
            return (x, y + height - reserve, width, reserve), (x, y, width, height - reserve)
        return (x, y, width, reserve), (x, y + reserve, width, height - reserve)

    reserve = field.caption_reserve or _measured_caption(field)
    reserve = min(reserve, max(width - inset - 8.0, 0.0))
    if reserve <= 0:
        return None, (x, y, width, height)
    if placement == "right":
        return (
            (x + width - reserve - field.margins.right, y, reserve, height),
            (x, y, width - reserve, height),
        )
    taken = inset + reserve
    return (x + inset, y, reserve, height), (x + taken, y, width - taken, height)


def _caption_font(field: XfaField) -> XfaFont:
    """The font the label is set in, which is rarely the field's own.

    Seven point bold against the field's eight point regular, in the
    reference form — so a label drawn in the field's font comes out bigger
    and lighter than the form's, and wide enough to wrap where the form fits
    it on one line.
    """
    return field.caption_font or field.font


def _measured_caption(field: XfaField) -> float:
    """Room for the label when the template does not say how much it needs."""
    from reportlab.pdfbase.pdfmetrics import stringWidth

    font = _caption_font(field)
    width = stringWidth(field.caption, _font_name(font), font.size)
    return min(width + 6.0, max(field.rect.width * 0.5, 0.0))


#: Line spacing, and how far a line reaches above and below its baseline, as
#: multiples of the font size. Helvetica's and Arial's own figures, rounded;
#: the layout measures text with the same three numbers the drawing uses, so
#: a row is exactly as tall as the lines drawn in it.
LEADING = 1.15
ASCENT = 0.75
DESCENT = 0.22


class _NotReproducible(Exception):
    """This element has no representation in a standard PDF."""


def _draw_static(pdf, item: XfaDraw, page_height: float) -> None:
    """Paint one non-interactive element."""
    x, y, width, height = rect_to_pdf(item.rect, page_height)

    if item.kind == "line":
        pdf.saveState()
        pdf.setStrokeColorRGB(*item.line_color)
        pdf.setLineWidth(max(item.line_width, 0.4))
        # A rule is drawn along its box: horizontal unless the box is tall.
        if height <= width:
            middle = y + height / 2.0
            pdf.line(x, middle, x + width, middle)
        else:
            middle = x + width / 2.0
            pdf.line(middle, y, middle, y + height)
        pdf.restoreState()
        return

    if item.kind == "rectangle":
        pdf.saveState()
        if item.fill_color is not None:
            pdf.setFillColorRGB(*item.fill_color)
        pdf.setStrokeColorRGB(*item.line_color)
        pdf.setLineWidth(max(item.line_width, 0.0))
        pdf.rect(
            x,
            y,
            width,
            height,
            stroke=1 if item.line_width > 0 else 0,
            fill=1 if item.fill_color is not None else 0,
        )
        pdf.restoreState()
        return

    if item.kind == "arc":
        drawn = item.line_width > 0 or item.fill_color is not None
        if not drawn:
            return
        pdf.saveState()
        if item.fill_color is not None:
            pdf.setFillColorRGB(*item.fill_color)
        pdf.setStrokeColorRGB(*item.line_color)
        pdf.setLineWidth(max(item.line_width, 0.0))
        if item.circular:
            side = min(width, height)
            x += (width - side) / 2.0
            y += (height - side) / 2.0
            width = height = side
        pdf.ellipse(
            x,
            y,
            x + width,
            y + height,
            stroke=1 if item.line_width > 0 else 0,
            fill=1 if item.fill_color is not None else 0,
        )
        pdf.restoreState()
        return

    if item.kind == "image":
        # A template points at its images with an href — in the reference form
        # a Windows path, "..\\Assets\\Logo2019.png", on a machine that is not
        # this one. Orion does not open what a document names, so the space is
        # left blank; the caller counts it as something the page lost, which
        # is the honest word for it.
        raise _NotReproducible("image")

    if not item.text:
        return

    pdf.saveState()
    pdf.setFillColorRGB(*item.font.color)
    font_name = _font_name(item.font)
    pdf.setFont(font_name, item.font.size)
    _draw_wrapped(
        pdf,
        item.text,
        x,
        y,
        width,
        height,
        item.font,
        font_name,
        item.align,
        item.valign,
        item.margins,
    )
    pdf.restoreState()


def _draw_wrapped(
    pdf,
    text,
    x,
    y,
    width,
    height,
    font: XfaFont,
    font_name,
    align,
    valign: str = "top",
    insets: XfaInsets | None = None,
) -> None:
    """Text inside its box: wrapped, inset, and aligned both ways.

    Vertical alignment is not a detail on a form. Almost every caption in the
    reference document asks for ``vAlign="middle"`` and its buttons for the
    same, so drawing everything against the top of its box — which is what
    this did — left the whole form sitting a couple of points high and its
    single-line labels floating above the boxes they name.
    """

    if insets is not None and not insets.is_zero:
        x += insets.left
        y += insets.bottom
        width -= insets.left + insets.right
        height -= insets.top + insets.bottom

    leading = font.size * LEADING
    lines = wrap_text(text, font_name, font.size, width)
    if not lines:
        return

    block = ((len(lines) - 1) * LEADING + ASCENT + DESCENT) * font.size
    slack = max(height - block, 0.0)
    if valign == "middle":
        offset = slack / 2.0
    elif valign == "bottom":
        offset = slack
    else:
        offset = 0.0

    top = y + height - offset - ASCENT * font.size
    for index, line in enumerate(lines):
        baseline = top - index * leading
        if baseline < y - leading:
            break
        if align == "center":
            pdf.drawCentredString(x + width / 2.0, baseline, line)
        elif align == "right":
            pdf.drawRightString(x + width, baseline, line)
        else:
            pdf.drawString(x, baseline, line)


def wrap_text(text: str, font_name: str, size: float, width: float) -> list[str]:
    """*text* broken into the lines it takes in a box *width* wide.

    Shared with the layout pass, which has to know how tall a cell's text
    comes out before it can know how tall the row is — and which must break
    the lines exactly where the drawing will, or the row is the wrong height.
    """
    from reportlab.pdfbase.pdfmetrics import stringWidth

    limit = max(width, 1.0)
    lines: list[str] = []
    current = ""
    for word in text.split():
        candidate = f"{current} {word}".strip()
        if stringWidth(candidate, font_name, size) <= limit or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _draw_field_caption(pdf, field: XfaField, rect) -> None:
    """The field's label, inside the part of the box reserved for it."""
    if not field.caption or rect is None:
        return
    x, y, width, height = rect
    # The caption sits in the field's content area, inside its top and
    # bottom margins — which is what lines a bottom-aligned label up with the
    # bottom-aligned value beside it.
    if field.caption_placement in ("left", "right"):
        y += field.margins.bottom
        height = max(height - field.margins.top - field.margins.bottom, 1.0)
    font = _caption_font(field)
    font_name = _font_name(font)
    pdf.saveState()
    pdf.setFillColorRGB(*font.color)
    pdf.setFont(font_name, font.size)
    _draw_wrapped(
        pdf,
        field.caption,
        x,
        y,
        max(width, 1.0),
        height,
        font,
        font_name,
        field.caption_align,
        field.caption_valign,
    )
    pdf.restoreState()


def _draw_field_as_static(pdf, field: XfaField, page_height: float) -> None:
    """A field that will not be interactive, drawn so it is not simply lost."""
    caption_rect, (box_x, y, box_width, height) = _split_for_caption(field, page_height)
    _draw_field_caption(pdf, field, caption_rect)
    box_width = max(box_width, 1.0)

    pdf.saveState()
    if field.fill_color is not None:
        pdf.setFillColorRGB(*field.fill_color)
        pdf.rect(box_x, y, box_width, height, stroke=0, fill=1)
    pdf.restoreState()
    _draw_edges(pdf, field.edges, box_x, y, box_width, height)
    pdf.saveState()
    if field.value:
        pdf.setFillColorRGB(*field.font.color)
        font_name = _font_name(field.font)
        pdf.setFont(font_name, field.font.size)
        _draw_wrapped(
            pdf,
            display_value(field),
            box_x + 2 + field.text_indent,
            y,
            box_width - 4 - field.text_indent,
            height,
            field.font,
            font_name,
            field.align,
            field.valign,
        )
    pdf.restoreState()


def _draw_button(pdf, button: XfaButton, page_height: float) -> None:
    """A button, drawn as it looked. Never made live — see the module docstring."""
    x, y, width, height = rect_to_pdf(button.rect, page_height)
    pdf.saveState()
    pdf.setFillColorRGB(0.92, 0.92, 0.92)
    pdf.setStrokeColorRGB(0.45, 0.45, 0.45)
    pdf.setLineWidth(0.5)
    pdf.roundRect(x, y, max(width, 1.0), max(height, 1.0), 2.0, stroke=1, fill=1)
    if button.caption:
        pdf.setFillColorRGB(0.25, 0.25, 0.25)
        pdf.setFont(_font_name(button.font), button.font.size)
        pdf.drawCentredString(
            x + width / 2.0,
            y + (height - button.font.size) / 2.0 + 1.0,
            button.caption,
        )
    pdf.restoreState()


def _checked(field: XfaField) -> bool:
    """Whether a checkbox or radio is on, given XFA's several ways of saying so."""
    value = (field.value or "").strip().lower()
    if not value:
        return False
    if field.field_type is XfaFieldType.RADIO:
        return value == (field.export_value or "").strip().lower()
    return value in ("1", "on", "true", "yes", (field.export_value or "").strip().lower())


def _uniform_border(field: XfaField):
    """``(width, colour)`` when all four sides are drawn the same, else None.

    A widget's own border is the cheap case and worth taking: it is drawn by
    the reader, it follows the field if anything ever moves it, and it needs
    nothing on the page beneath. Anything less regular — a cell ruled only
    underneath — is drawn onto the page instead.
    """
    edges = field.edges
    if not all(edge.draws for edge in edges):
        return None
    first = edges[0]
    if any(abs(edge.width - first.width) > 0.01 or edge.color != first.color for edge in edges[1:]):
        return None
    return first.width, first.color


def _draw_edges(pdf, edges, x: float, y: float, width: float, height: float) -> None:
    """Paint the sides of a box that a widget's own border cannot express."""
    top, right, bottom, left = edges
    sides = (
        (top, (x, y + height), (x + width, y + height)),
        (right, (x + width, y), (x + width, y + height)),
        (bottom, (x, y), (x + width, y)),
        (left, (x, y), (x, y + height)),
    )
    drawn = [side for side in sides if side[0].draws]
    if not drawn:
        return
    pdf.saveState()
    for edge, start, end in drawn:
        pdf.setStrokeColorRGB(*edge.color)
        pdf.setLineWidth(edge.width)
        pdf.line(start[0], start[1], end[0], end[1])
    pdf.restoreState()


def _wraps(field: XfaField, shown: str) -> bool:
    """Should the widget be a multi-line one?

    A read-only field nobody will type into is multi-line only if its value
    needs the room. A title marked multi-line and set flush right and at the
    bottom of a tall band is drawn at the top left by every reader that
    regenerates it, because that is where a multi-line field starts — where a
    single-line one is centred, which is much nearer what the form asked for.
    """
    if not field.multiline:
        return False
    if not field.read_only:
        return True
    from reportlab.pdfbase.pdfmetrics import stringWidth

    room = field.rect.width - field.margins.left - field.margins.right - field.text_indent - 3.0
    if field.caption and field.caption_placement in ("left", "right"):
        room -= field.caption_reserve
    width = stringWidth(shown, _font_name(field.font, embed=False), field.font.size)
    return "\n" in shown or width > room


def _is_toggle(field: XfaField) -> bool:
    return field.field_type in (XfaFieldType.CHECKBOX, XfaFieldType.RADIO)


def _toggle_box(field: XfaField, box: tuple[float, float, float, float]):
    """Where a checkbox's square goes inside its box, and how big it is.

    A checkbox in a table cell is a ten-point square in a cell three times
    that size. Filling the cell with it — what the conversion did — drew a
    square as big as the row, and a different size on every row that a long
    description had made taller.
    """
    x, y, width, height = box
    x += field.margins.left
    width -= field.margins.left + field.margins.right
    y += field.margins.bottom
    height -= field.margins.top + field.margins.bottom
    size = field.check_size or 10.0
    size = max(min(size, width, height), 6.0)
    if field.align == "center":
        left = x + (width - size) / 2.0
    elif field.align == "right":
        left = x + width - size
    else:
        left = x
    if field.valign == "top":
        bottom = y + height - size
    elif field.valign == "bottom":
        bottom = y
    else:
        bottom = y + (height - size) / 2.0
    return left, bottom, size


def _add_widget(
    pdf,
    field: XfaField,
    page_height: float,
    name: str,
    radio_state,
    blank_choices: set[str],
    looks: dict | None = None,
    *,
    hidden: bool = False,
) -> bool:
    """Create the AcroForm widget for *field*. True when one was made.

    *hidden* makes a widget the reader does not display: the field of a saved
    form that a script had hidden, kept because it holds a value.
    """
    form = pdf.acroForm
    _caption, (box_x, y, box_width, box_height) = _split_for_caption(field, page_height)
    box_width = max(box_width, 8.0)
    box_height = max(box_height, 8.0)
    # reportlab raises on any other font when it builds a widget, so this one
    # call asks for the stand-in rather than the embedded face.
    font_name = _font_name(field.font, embed=False)
    size = max(field.font.size, 4.0)

    # The form's border is drawn onto the page, side by side, because a widget
    # can only have one border all the way round and a real form does not.
    # What reportlab gets is the box with no border of its own — where the
    # form draws a box, the page under the widget already has it; where the
    # form draws nothing, nothing is what should appear. Inventing a hairline
    # around every field, which is what this did, put a black rectangle around
    # twenty-one fields of a form that has a border on none of them.
    uniform = _uniform_border(field)
    common = {
        "x": box_x,
        "y": y,
        "borderWidth": uniform[0] if uniform else 0,
        "borderColor": _grey(uniform[1]) if uniform else None,
        "fillColor": _grey(field.fill_color) if field.fill_color else None,
        "textColor": _grey(field.font.color),
        "forceBorder": bool(uniform),
        "tooltip": _tooltip(field) or None,
    }
    if hidden:
        common["annotationFlags"] = "hidden"
    shown = display_value(field)

    # Both were read out of the template from the start and neither was ever
    # written into the file. A field the form marked as required arrived
    # optional, and one it marked read-only arrived editable — the kind of
    # loss that only shows up when somebody submits the form.
    state = []
    if field.read_only:
        state.append("readOnly")
    if field.mandatory:
        state.append("required")

    if field.field_type in (XfaFieldType.TEXT, XfaFieldType.NUMERIC, XfaFieldType.DATE):
        form.textfield(
            name=name,
            value=shown,
            width=box_width,
            height=box_height,
            fontName=font_name,
            fontSize=size,
            fieldFlags=" ".join([*state, *(["multiline"] if _wraps(field, shown) else [])]),
            maxlen=field.max_length or None,
            **common,
        )
        if looks is not None and not hidden:
            looks[name] = _look_of(field, shown, single_line=not _wraps(field, shown))
        return True

    if _is_toggle(field):
        # The cell's own border is on the page already; the square gets a
        # thin one of its own, as the form draws it.
        left, bottom, square = _toggle_box(field, (box_x, y, box_width, box_height))
        toggle = dict(common)
        toggle.update(
            x=left,
            y=bottom,
            borderWidth=0.5,
            borderColor=_grey((0.35, 0.35, 0.35)),
            forceBorder=True,
        )
        if field.field_type is XfaFieldType.CHECKBOX:
            form.checkbox(
                name=name,
                checked=_checked(field),
                size=square,
                buttonStyle="check",
                fieldFlags=" ".join(state),
                **toggle,
            )
            return True
        group = field.group or field.som
        form.radio(
            name=radio_state.name_for(group),
            value=field.export_value or field.name or "on",
            selected=_checked(field),
            size=square,
            buttonStyle="circle",
            shape="circle",
            fieldFlags=" ".join(["radio", *state]),
            **toggle,
        )
        return True

    if field.field_type is XfaFieldType.CHOICE and field.choices is not None:
        pairs = field.choices.pairs
        options = [(label, value) for label, value in pairs] or [("", "")]
        current = field.value or ""
        # The stored value is what XFA saved; show the label that goes with it.
        chosen = current
        for _label, value in pairs:
            if value == current:
                chosen = value
                break

        # reportlab (through 5.0.1) cannot make an *empty* choice field: in
        # `AcroForm._textfield` the `lbextras` dict is only built inside
        # `if value:`, and the appearance stream is then built with
        # `**lbextras`, so a blank list raises UnboundLocalError. A blank list
        # is the normal state of an unfilled form, so this is not an edge
        # case — it is every drop-down in every form nobody has filled in yet.
        #
        # Worked around by creating the widget with its first option selected
        # and recording the name; `_clear_blank_choices` then strips /V and /I
        # from those fields in the finished file. Preselecting one and leaving
        # it would be worse than the crash: the form would come back saying
        # the user had chosen something they never chose.
        if chosen and all(chosen not in pair for pair in options):
            # A value the list does not offer: typed into an open list, or
            # from a list a script filled in. reportlab refuses to build the
            # widget at all, so the value joins the list rather than vanish.
            options.append((chosen, chosen))
        blank = not chosen
        if blank:
            chosen = options[0][1]
            blank_choices.add(name)

        if field.choices.multi_select:
            maker = form.listbox
            flags = [*state, "multiSelect"]
        else:
            maker = form.choice
            # A list the user may type into as well as pick from — XFA's
            # open="userControl". Without the flag it becomes a fixed list and
            # an answer the form allowed can no longer be given.
            flags = ["combo", *state]
            if field.choices.editable:
                flags.append("edit")
        maker(
            name=name,
            value=chosen,
            options=options,
            width=box_width,
            height=box_height,
            fontName=font_name,
            fontSize=size,
            fieldFlags=" ".join(flags),
            **common,
        )
        if looks is not None and not hidden and not blank and not field.choices.multi_select:
            label = next((lab for lab, val in options if val == chosen), chosen)
            looks[name] = _look_of(field, label, single_line=True)
        return True

    return False


def _merge_default_fonts(path: Path) -> None:
    """Fold reportlab's two ``/Font`` entries in ``/DR`` into one.

    reportlab writes the form's default resources as
    ``/DR << /Font << /HeBo … >> /Font << /Helv … >> >>`` — the same key
    twice, which no PDF dictionary may have. Readers keep whichever they meet
    first and drop the other, so the font named in every widget's ``/DA``
    disappears from the resources that are supposed to supply it, and a viewer
    regenerating a field's appearance has nothing to draw the text with.

    The repair is made in place and padded back to the same length, because
    every cross-reference offset after this point is a byte count: a shorter
    dictionary would leave the whole table pointing a few bytes past where the
    objects are.
    """
    try:
        raw = path.read_bytes()
        start = raw.find(b"/DR <<")
        if start < 0:
            return
        end = _dictionary_end(raw, raw.index(b"<<", start))
        if end < 0:
            return

        block = raw[start:end]
        entries = list(re.finditer(rb"/Font\s*<<(.*?)>>", block, re.S))
        if len(entries) < 2:
            return
        merged = b"/Font <<" + b" ".join(e.group(1).strip() for e in entries) + b">>"
        rebuilt = block[: entries[0].start()] + merged + block[entries[-1].end() :]
        for entry in entries[1:-1]:
            rebuilt = rebuilt.replace(entry.group(0), b"")
        if len(rebuilt) > len(block):  # pragma: no cover - merging only shortens
            return
        rebuilt += b" " * (len(block) - len(rebuilt))
        path.write_bytes(raw[:start] + rebuilt + raw[end:])
    except Exception:  # pragma: no cover - the duplicate is cosmetic at worst
        log.warning("Could not merge the form's default font resources", exc_info=True)


def _dictionary_end(raw: bytes, start: int) -> int:
    """The offset just past the ``>>`` that closes the dictionary at *start*."""
    depth = 0
    index = start
    while index < len(raw):
        if raw[index : index + 2] == b"<<":
            depth += 1
            index += 2
        elif raw[index : index + 2] == b">>":
            depth -= 1
            index += 2
            if depth == 0:
                return index
        else:
            index += 1
    return -1


@dataclass(frozen=True, slots=True)
class _LiveButton:
    """A button the converted document can genuinely carry out."""

    page: int
    rect: tuple[float, float, float, float]
    name: str
    caption: str
    #: ``print``, ``save`` or ``reset`` — resolved into a PDF action below.
    action: str


#: XFA button -> the standard PDF action that does the same thing. These are
#: *actions*, not scripts: a reader carries them out itself, so they need
#: none of the JavaScript that could not come across.
_BUTTON_ACTIONS = {
    XfaButtonKind.PRINT: "print",
    XfaButtonKind.SAVE: "save",
    XfaButtonKind.RESET: "reset",
}


def _can_be_a_widget(field: XfaField, mode: ConversionMode) -> bool:
    """Should this field become something the file can hold a value in?

    A field the template protects is still a field. Painting it onto the page
    loses its name, its type and any chance of unlocking it later, so in the
    mode that converts everything it becomes a widget with the read-only flag
    set instead — visible, named, and one flag away from editable. Signatures,
    images and barcodes stay out either way: there is no AcroForm equivalent
    that would behave.
    """
    if not field.field_type.is_interactive:
        return False
    return field.is_interactive or mode.wants_locked_fields


def _named_action(button: XfaButton) -> str:
    """The action this button can keep, or "" when it cannot keep one.

    Three of a form's buttons ask for something every PDF reader already
    does — print this, save a copy, empty the form — and PDF has had an
    action for each since long before XFA. Those are recreated. The ones that
    add a row to a table or recalculate a total are not: they are the form's
    own programming, they have no equivalent, and the report says so rather
    than the button pretending.
    """
    return _BUTTON_ACTIONS.get(button.kind, "")


@dataclass(frozen=True, slots=True)
class _Look:
    """How a text widget's value is laid out in its box."""

    text: str
    font_name: str
    size: float
    color: tuple[float, float, float]
    align: str
    valign: str
    wrap: bool
    left: float
    right: float
    top: float
    bottom: float


def _look_of(field: XfaField, text: str, *, single_line: bool = False) -> _Look:
    """What the template says about where *field*'s value sits."""
    # With a caption on the left, the margin was spent before the caption.
    left_inset = 0.0 if field.caption and field.caption_placement == "left" else field.margins.left
    return _Look(
        text=text,
        font_name=_font_name(field.font, embed=False),
        size=max(field.font.size, 4.0),
        color=field.font.color,
        align=field.align,
        valign=field.valign,
        wrap=field.multiline and not single_line,
        left=left_inset + field.text_indent + 1.5,
        right=field.margins.right + 1.5,
        top=field.margins.top,
        bottom=field.margins.bottom,
    )


_QUADDING = {"center": 1, "right": 2}


def _pdf_string(text: str) -> str:
    raw = text.encode("cp1252", "replace").decode("latin-1")
    return "(" + raw.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") + ")"


def _box_ops(widget, width: float, height: float) -> list[str]:
    """The widget's background and border, as it asks for them in ``/MK``."""
    look = widget.get("/MK") or {}
    border = [float(c) for c in (look.get("/BC") or [])]
    background = [float(c) for c in (look.get("/BG") or [])]
    line = float((widget.get("/BS") or {}).get("/W", 1.0) or 0.0)
    ops: list[str] = []
    if len(background) == 3:
        ops.append(f"{background[0]} {background[1]} {background[2]} rg")
        ops.append(f"0 0 {width} {height} re f")
    if len(border) == 3 and line > 0:
        inset = line / 2.0
        ops.append(f"{border[0]} {border[1]} {border[2]} RG")
        ops.append(f"{line} w")
        ops.append(f"{inset} {inset} {width - line} {height - line} re S")
    return ops


def _text_appearance(widget, look: _Look, writer):
    """The value drawn where the form draws it: aligned, inset and wrapped.

    reportlab writes every text widget's appearance as one line at the top
    left, whatever the field asked for. A form reads differently for it —
    amounts that should be centred hug the left edge, a title set flush right
    starts at the left, and a description that runs to two lines is cut off
    after the first while the row beneath it was made tall enough for both.
    The field's value, flags and ``/Q`` are untouched; only what a reader
    shows before anyone edits the field is redrawn.
    """
    import re as _re

    from pypdf.generic import (
        ArrayObject,
        DecodedStreamObject,
        DictionaryObject,
        FloatObject,
        NameObject,
    )
    from reportlab.pdfbase.pdfmetrics import stringWidth

    rect = [float(v) for v in widget.get("/Rect", [0, 0, 0, 0])]
    width = max(abs(rect[2] - rect[0]), 1.0)
    height = max(abs(rect[3] - rect[1]), 1.0)

    match = _re.search(r"/(\S+)\s+[\d.]+\s+Tf", str(widget.get("/DA", "")))
    font_key = match.group(1) if match else "Helv"
    resources = DictionaryObject()
    current = (widget.get("/AP") or {}).get("/N")
    if current is not None:
        found = current.get_object().get("/Resources")
        if found is not None:
            resources = found

    inner_width = max(width - look.left - look.right, 1.0)
    if look.wrap:
        lines = []
        for paragraph in look.text.splitlines() or [""]:
            lines.extend(wrap_text(paragraph, look.font_name, look.size, inner_width) or [""])
    else:
        lines = [" ".join(look.text.split())]

    size = look.size
    leading = size * LEADING
    ascent, descent = size * ASCENT, size * DESCENT
    inner_height = height - look.top - look.bottom
    block = (len(lines) - 1) * leading + ascent + descent
    slack = inner_height - block
    if slack <= 0 or look.valign == "top":
        offset = 0.0
    elif look.valign == "middle":
        offset = slack / 2.0
    else:
        offset = slack
    first = height - look.top - offset - ascent

    ops = _box_ops(widget, width, height)
    ops += ["/Tx BMC", "q", f"1 1 {max(width - 2, 1)} {max(height - 2, 1)} re W n", "BT"]
    ops.append(f"/{font_key} {size:.2f} Tf")
    ops.append(f"{look.color[0]:.3f} {look.color[1]:.3f} {look.color[2]:.3f} rg")
    for index, line in enumerate(lines):
        baseline = first - index * leading
        if baseline < -leading:
            break
        text_width = stringWidth(line, look.font_name, size)
        if look.align == "center":
            x = look.left + (inner_width - text_width) / 2.0
        elif look.align == "right":
            x = width - look.right - text_width
        else:
            x = look.left
        ops.append(f"1 0 0 1 {x:.2f} {baseline:.2f} Tm {_pdf_string(line)} Tj")
    ops += ["ET", "Q", "EMC"]

    stream = DecodedStreamObject()
    stream.set_data(("\n".join(ops) + "\n").encode("latin-1", "replace"))
    stream[NameObject("/Type")] = NameObject("/XObject")
    stream[NameObject("/Subtype")] = NameObject("/Form")
    stream[NameObject("/BBox")] = ArrayObject(
        [FloatObject(0), FloatObject(0), FloatObject(width), FloatObject(height)]
    )
    stream[NameObject("/Resources")] = resources
    return DictionaryObject({NameObject("/N"): writer._add_object(stream)})


def _finish_widgets(
    path: Path,
    blank_choices: set[str],
    buttons: list[_LiveButton],
    looks: dict[str, _Look] | None = None,
) -> None:
    """One pass over the finished file for everything reportlab cannot do.

    The jobs all need the file reopened, and reopening it more than once would
    mean writing it more than once, so they share a pass: emptying the
    placeholder choices, redrawing text values where the form puts them, and
    adding the button widgets that carry a print, save or reset action.
    """
    looks = looks or {}
    if not blank_choices and not buttons and not looks:
        return
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import NameObject, NumberObject

    try:
        writer = PdfWriter(clone_from=PdfReader(str(path)))
        for page in writer.pages:
            for annotation in page.get("/Annots") or []:
                widget = annotation.get_object()
                name = str(widget.get("/T", ""))
                look = looks.get(name)
                if look is not None:
                    quadding = _QUADDING.get(look.align, 0)
                    if quadding:
                        widget[NameObject("/Q")] = NumberObject(quadding)
                    widget[NameObject("/AP")] = _text_appearance(widget, look, writer)
                if name not in blank_choices:
                    continue
                for key in ("/V", "/DV", "/I"):
                    if key in widget:
                        del widget[NameObject(key)]
                widget[NameObject("/AP")] = _blank_appearance(widget, writer)

        for button in buttons:
            _add_button_widget(writer, button)

        with open(path, "wb") as handle:
            writer.write(handle)
    except Exception:  # pragma: no cover - a plain file beats no file
        log.warning("Could not finish the converted form's widgets", exc_info=True)


def _add_button_widget(writer, button: _LiveButton) -> None:
    """Put a clickable pushbutton over the button already drawn on the page.

    The look is left to the drawing underneath — it is the form's own button,
    complete with its caption and its raised edge — so the widget carries an
    empty appearance and exists for the click alone. That way nothing is drawn
    twice and nothing has to be redrawn in a reader's idea of a button.
    """
    from pypdf.generic import (
        ArrayObject,
        DecodedStreamObject,
        DictionaryObject,
        FloatObject,
        NameObject,
        NumberObject,
        TextStringObject,
    )

    if button.page >= len(writer.pages):  # pragma: no cover - defensive
        return
    page = writer.pages[button.page]
    x, y, width, height = button.rect
    if width <= 0 or height <= 0:  # pragma: no cover - defensive
        return

    if button.action == "reset":
        action = DictionaryObject({NameObject("/S"): NameObject("/ResetForm")})
    else:
        named = "/Print" if button.action == "print" else "/SaveAs"
        action = DictionaryObject(
            {NameObject("/S"): NameObject("/Named"), NameObject("/N"): NameObject(named)}
        )

    empty = DecodedStreamObject()
    empty.set_data(b"")
    empty[NameObject("/Type")] = NameObject("/XObject")
    empty[NameObject("/Subtype")] = NameObject("/Form")
    empty[NameObject("/BBox")] = ArrayObject(
        [FloatObject(0), FloatObject(0), FloatObject(width), FloatObject(height)]
    )
    empty[NameObject("/Resources")] = DictionaryObject()

    widget = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Annot"),
            NameObject("/Subtype"): NameObject("/Widget"),
            NameObject("/FT"): NameObject("/Btn"),
            # 65536 is the pushbutton flag: a button that holds no value.
            NameObject("/Ff"): NumberObject(65536),
            NameObject("/T"): TextStringObject(button.name),
            NameObject("/TU"): TextStringObject(button.caption),
            NameObject("/F"): NumberObject(4),
            NameObject("/Rect"): ArrayObject(
                [
                    FloatObject(x),
                    FloatObject(y),
                    FloatObject(x + width),
                    FloatObject(y + height),
                ]
            ),
            NameObject("/MK"): DictionaryObject(
                {NameObject("/CA"): TextStringObject(button.caption)}
            ),
            NameObject("/A"): action,
            NameObject("/AP"): DictionaryObject({NameObject("/N"): writer._add_object(empty)}),
        }
    )
    reference = writer._add_object(widget)

    annotations = page.get(NameObject("/Annots"))
    if annotations is None:
        page[NameObject("/Annots")] = ArrayObject([reference])
    else:
        annotations.append(reference)

    form = writer._root_object.get("/AcroForm")
    if form is not None:
        fields = form.get_object().get("/Fields")
        if fields is not None:
            fields.append(reference)


def _blank_appearance(widget, writer):
    """A drop-down drawn empty: its box, and nothing in it.

    The appearance stream reportlab built still *draws* the placeholder, so
    clearing the value alone leaves a field that reads "SMARTPHONE" to the eye
    and reports nothing chosen to anything that opens the file. Asking viewers
    to rebuild the appearance instead (``/NeedAppearances``) is worse again:
    they rebuild every widget in the document, and the borders drawn for the
    text fields go with them. So the box is redrawn here, from the widget's own
    colours, and only for the fields that need it.
    """
    from pypdf.generic import (
        ArrayObject,
        DecodedStreamObject,
        DictionaryObject,
        FloatObject,
        NameObject,
    )

    rect = [float(v) for v in widget.get("/Rect", [0, 0, 0, 0])]
    width = max(abs(rect[2] - rect[0]), 1.0)
    height = max(abs(rect[3] - rect[1]), 1.0)

    look = widget.get("/MK") or {}
    border = [float(c) for c in (look.get("/BC") or [])]
    background = [float(c) for c in (look.get("/BG") or [])]
    line = float((widget.get("/BS") or {}).get("/W", 1.0) or 0.0)

    ops: list[str] = []
    if len(background) == 3:
        ops.append(f"{background[0]} {background[1]} {background[2]} rg")
        ops.append(f"0 0 {width} {height} re f")
    if len(border) == 3 and line > 0:
        inset = line / 2.0
        ops.append(f"{border[0]} {border[1]} {border[2]} RG")
        ops.append(f"{line} w")
        ops.append(f"{inset} {inset} {width - line} {height - line} re S")

    stream = DecodedStreamObject()
    stream.set_data(("\n".join(ops) + "\n").encode("latin-1", "replace"))
    stream[NameObject("/Type")] = NameObject("/XObject")
    stream[NameObject("/Subtype")] = NameObject("/Form")
    stream[NameObject("/BBox")] = ArrayObject(
        [FloatObject(0), FloatObject(0), FloatObject(width), FloatObject(height)]
    )
    stream[NameObject("/Resources")] = DictionaryObject()
    return DictionaryObject({NameObject("/N"): writer._add_object(stream)})


def _grey(colour):
    """reportlab wants a colour object; the model carries a plain RGB triple."""
    if colour is None:
        return None
    from reportlab.lib.colors import Color

    return Color(*colour)


class _RadioNames:
    """One AcroForm field name per XFA exclusion group.

    A radio group is a single AcroForm field with several widgets, so the
    members have to agree on the name, and the name still has to be unique in
    the document.
    """

    def __init__(self, used: set[str]) -> None:
        self._used = used
        self._names: dict[str, str] = {}

    def name_for(self, group: str) -> str:
        if group not in self._names:
            self._names[group] = _safe_name(group, self._used)
        return self._names[group]


def convert_xfa(
    source: str | Path,
    output: str | Path,
    *,
    mode: ConversionMode = ConversionMode.KEEP_FIELDS,
    info: FormInfo | None = None,
) -> ConversionResult:
    """Convert the XFA form in *source* into a standard PDF at *output*.

    *source* is opened read-only and never modified.

    A conversion that cannot do everything still writes a file. That is the
    policy for this whole package: a form with its layout intact and four of
    its twenty-five fields static is useful, and an exception is not.
    """
    source_path = Path(source)
    output_path = Path(output)
    report = XfaConversionReport(source_file=str(source_path), mode=mode, output_file="")

    info = info or inspect_form(source_path)
    report.detected_type = info.form_type.value
    if not info.is_xfa:
        report.error("This document does not contain an XFA form, so there is nothing to convert.")
        return ConversionResult(None, report)

    document = parse_xfa(info.packets)
    form = resolve_layout(document)
    for warning in form.warnings:
        report.warn(warning)

    report.pages = len(form.pages)
    all_fields = form.fields
    report.total_xfa_fields = len(all_fields)
    report.scripts_found = len(document.scripts)
    report.scripts_converted = 0
    report.repeatable_subforms = len(form.instances)
    report.preserved_instances = sum(form.instances.values())

    if not all_fields and not form.draws:
        report.warn(
            "The form's design could not be read, so the converted document "
            "keeps only what the original pages already showed."
        )

    _report_layout_checks(report, form)

    try:
        _write(output_path, form, mode, report, document)
    except Exception as exc:  # pragma: no cover - a write failure is reported
        log.exception("Could not write the converted form to %s", output_path)
        report.error(f"The converted document could not be written: {exc}")
        return ConversionResult(None, report, document, form)

    report.output_file = str(output_path)
    _describe_losses(report, document, form, mode)
    return ConversionResult(output_path, report, document, form)


def _write(
    output_path: Path,
    form: LaidOutForm,
    mode: ConversionMode,
    report: XfaConversionReport,
    document: XfaDocument,
) -> None:
    """Draw every page and add the widgets."""
    from reportlab.pdfgen import canvas

    used_names: set[str] = set()
    radio_names = _RadioNames(used_names)
    blank_choices: set[str] = set()
    converted = 0
    static = 0
    # Fields that ended up on the page but not fillable: a loss of behaviour.
    unsupported = 0
    # Elements that never made it onto the page at all: a loss of appearance.
    undrawn = 0
    # Fields the template hides and this conversion shows anyway.
    hidden_shown = 0
    # What kind of element had to be left out, and how many of each.
    lost_kinds: dict[str, int] = {}
    # Buttons a standard PDF can actually carry out, and where they sit.
    live_buttons: list[_LiveButton] = []
    # How each text widget should look, redrawn after reportlab is done.
    looks: dict[str, _Look] = {}

    pdf = canvas.Canvas(str(output_path), pagesize=(form.pages[0].width, form.pages[0].height))
    pdf.setTitle(output_path.stem)

    # A real form hides fields until a script decides they apply — four of
    # them in a form of nineteen is normal. The scripts are not coming with
    # us, so in a mode that keeps fields the hidden ones are shown: a field
    # nothing can ever reveal again is a field the user has lost. A static
    # copy is a different promise — it stands in for the printed form — so
    # there the template's own answer is kept.
    #
    # Except where showing one would put it on top of something the user can
    # see: a form swaps one field for another in the same place — "TO:" for
    # "A:" — and both at once is two captions printed over each other. Such a
    # field stays hidden, and travels as a widget the reader does not show
    # when it holds a value, so nothing typed into it is lost.
    show_hidden = mode.wants_fields

    for page_index, page in enumerate(form.pages):
        pdf.setPageSize((page.width, page.height))
        covered = _covered_hidden(page, document.has_form_state) if show_hidden else set()

        for drawn in page.draws:
            if drawn.hidden and (not show_hidden or id(drawn) in covered):
                continue
            try:
                _draw_static(pdf, drawn, page.height)
                static += 1
            except _NotReproducible:
                undrawn += 1
                lost_kinds[drawn.kind] = lost_kinds.get(drawn.kind, 0) + 1
            except Exception:  # pragma: no cover - one bad element is not fatal
                log.warning("Could not draw a static element", exc_info=True)
                undrawn += 1
                lost_kinds[drawn.kind] = lost_kinds.get(drawn.kind, 0) + 1

        for button in page.buttons:
            if button.hidden and (not show_hidden or id(button) in covered):
                continue
            _draw_button(pdf, button, page.height)
            static += 1
            action = _named_action(button)
            if action and mode.wants_fields:
                live_buttons.append(
                    _LiveButton(
                        page=page_index,
                        rect=rect_to_pdf(button.rect, page.height),
                        name=_safe_name(button.som or button.name, used_names),
                        caption=button.caption,
                        action=action,
                    )
                )

        for field in page.fields:
            if field.hidden and (not show_hidden or id(field) in covered):
                if show_hidden and field.value and _can_be_a_widget(field, mode):
                    try:
                        if _add_widget(
                            pdf,
                            field,
                            page.height,
                            _safe_name(field.qualified_name, used_names),
                            radio_names,
                            blank_choices,
                            looks,
                            hidden=True,
                        ):
                            converted += 1
                    except Exception:  # pragma: no cover - reportlab refusing a widget
                        log.warning("Could not keep the hidden field %s", field.som, exc_info=True)
                continue
            if field.hidden:
                hidden_shown += 1
            interactive = mode.wants_fields and _can_be_a_widget(field, mode)
            if interactive:
                name = (
                    radio_names.name_for(field.group or field.som)
                    if field.field_type is XfaFieldType.RADIO
                    else _safe_name(field.qualified_name, used_names)
                )
                caption_rect, box = _split_for_caption(field, page.height)
                _draw_field_caption(pdf, field, caption_rect)
                if not _uniform_border(field) or _is_toggle(field):
                    _draw_edges(pdf, field.edges, *box)
                try:
                    made = _add_widget(
                        pdf, field, page.height, name, radio_names, blank_choices, looks
                    )
                except Exception:  # pragma: no cover - reportlab refusing a widget
                    log.warning("Could not create a widget for %s", field.som, exc_info=True)
                    made = False
                if made:
                    converted += 1
                    continue
                report.warn(
                    "This field could not be made interactive and was kept as "
                    "part of the page instead.",
                    field.som,
                )
            _draw_field_as_static(pdf, field, page.height)
            static += 1
            if mode.wants_fields:
                # Reached either because the field is not fillable by nature
                # (protected, or a type with no AcroForm equivalent) or
                # because the widget could not be built. Both leave a field
                # the user cannot type into, which is the same loss.
                unsupported += 1

        pdf.showPage()

    pdf.save()
    _merge_default_fonts(output_path)
    _finish_widgets(output_path, blank_choices, live_buttons, looks)
    report.live_buttons = len(live_buttons)
    report.converted_fields = converted
    report.static_elements = static
    report.unsupported_elements = unsupported
    report.undrawn_elements = undrawn
    report.hidden_fields_shown = hidden_shown
    for kind, count in sorted(lost_kinds.items()):
        if kind == "image":
            report.warn(
                f"{count} image(s) in the form could not be reproduced. The "
                "form keeps its pictures outside the document and points at "
                "them by file name, and Orion does not open files a document "
                "asks it to."
            )
        else:  # pragma: no cover - any other kind is a drawing failure
            report.warn(f"{count} {kind} element(s) could not be reproduced.")


def _paints(item) -> bool:
    """Does this element put something on the page a hidden one could cover?"""
    if isinstance(item, XfaDraw):
        return item.kind == "text" and bool(item.text)
    return True


def _overlap(a: XfaRect, b: XfaRect) -> bool:
    """Do two boxes share more than a quarter of the smaller one?"""
    width = min(a.x + a.width, b.x + b.width) - max(a.x, b.x)
    height = min(a.y + a.height, b.y + b.height) - max(a.y, b.y)
    if width <= 0 or height <= 0:
        return False
    smaller = min(a.width * a.height, b.width * b.height)
    return smaller > 0 and width * height > 0.25 * smaller


def _covered_hidden(page, saved_state: bool) -> set[int]:
    """``id()`` of the hidden elements that would land on something visible.

    Visible elements are placed first; each hidden one is then kept only if
    it lands on nothing already there, so of two hidden alternatives in one
    spot the first is shown. With a saved form state a hidden button is left
    out outright: the state says nobody could see it, and it does nothing
    once converted.
    """
    items = [*page.fields, *page.buttons, *page.draws]
    taken = [item.rect for item in items if not item.hidden and _paints(item)]
    covered: set[int] = set()
    for item in items:
        if not item.hidden:
            continue
        if saved_state and isinstance(item, XfaButton):
            covered.add(id(item))
            continue
        if not _paints(item):
            continue
        if any(_overlap(item.rect, rect) for rect in taken):
            covered.add(id(item))
        else:
            taken.append(item.rect)
    # What a template hides together goes together: a signature block whose
    # line is covered does not keep its label on its own.
    groups = {item.parent_som for item in items if id(item) in covered and item.parent_som}
    for item in items:
        if item.hidden and item.parent_som in groups:
            covered.add(id(item))
    return covered


def _report_layout_checks(report: XfaConversionReport, form: LaidOutForm) -> None:
    """Measure the finished layout and say what came out wrong.

    Grouped rather than listed one by one: a form whose flow was misread has
    every field overlapping every other, and forty identical warnings tell
    the user less than one sentence with a number in it. The first few
    subjects are named because they are where to look.
    """
    issues = check_layout(form)
    if not issues:
        return
    report.layout_problems = len(issues)

    grouped: dict[str, list[str]] = {}
    for issue in issues:
        grouped.setdefault(issue.kind, []).append(issue.subject)

    wording = {
        "overlap": (
            "{count} field(s) sit on top of another field ({names}). The form's "
            "layout could not be worked out exactly, so some of them may be "
            "unusable where they are."
        ),
        "off_page": (
            "{count} field(s) ended up outside the page ({names}) and may not be reachable."
        ),
        "overflow": (
            "{count} piece(s) of text need more room than the form gave them "
            "({names}) and are cut short."
        ),
    }
    for kind, subjects in grouped.items():
        named = ", ".join(subject for subject in subjects[:3] if subject)
        if len(subjects) > 3:
            named += ", …"
        report.warn(wording[kind].format(count=len(subjects), names=named or "unnamed"))


def _describe_losses(
    report: XfaConversionReport,
    document: XfaDocument,
    form: LaidOutForm,
    mode: ConversionMode,
) -> None:
    """Say, in the report, what the conversion could not carry across.

    Written for the person who has to decide whether the result is usable,
    which means naming the consequence rather than the mechanism.
    """
    if mode is ConversionMode.STATIC:
        report.info("Converted to a static document, as asked: nothing in it is fillable.")

    kinds: dict[str, int] = {}
    for script in document.scripts:
        kinds[script.kind.value] = kinds.get(script.kind.value, 0) + 1
    if kinds:
        described = ", ".join(
            f"{count} {kind.replace('_', ' ')}" for kind, count in sorted(kinds.items())
        )
        report.warn(
            f"The form contained {report.scripts_found} script(s) ({described}). "
            "Standard PDF forms have no equivalent for them, so the fields were "
            "kept and the automatic behaviour was not."
        )

    for button in form.buttons:
        label = button.caption or button.name
        if mode.wants_fields and _named_action(button):
            report.info(
                f"The '{label}' button still works: it asks the reader to do "
                "the same thing, through the action PDF has for it rather "
                "than through the form's script.",
                button.som,
            )
        elif button.kind.value in ("instance", "submit", "scripted"):
            report.info(
                f"The '{label}' button is shown but no longer does anything.",
                button.som,
            )

    if form.instances:
        detail = ", ".join(f"{som} x{count}" for som, count in sorted(form.instances.items()))
        report.warn(
            f"The form has sections that could grow on demand ({detail}). The "
            "rows already in the form were kept; new ones can no longer be "
            "added by the document itself."
        )

    if report.hidden_fields_shown:
        report.info(
            f"{report.hidden_fields_shown} field(s) that the form showed only "
            "in certain cases are always shown here. The rule that decided "
            "when to show them could not be carried over, and a field nothing "
            "can reveal again would be a field you had lost."
        )

    unsupported = [f for f in form.fields if not f.field_type.is_interactive]
    for field in unsupported:
        report.info(
            f"A {field.field_type.value} element was kept as part of the page.",
            field.som,
        )


def convert_xfa_file(
    source: str | Path,
    output_dir: str | Path | None = None,
    *,
    mode: ConversionMode = ConversionMode.KEEP_FIELDS,
    suffix: str = "-converted",
) -> ConversionResult:
    """Convert *source* into a new file beside it, never over it.

    The name is derived rather than asked for, and collisions are stepped past
    with a counter: overwriting somebody's earlier conversion silently would
    be the same mistake as overwriting the original.
    """
    source_path = Path(source)
    directory = Path(output_dir) if output_dir else source_path.parent
    directory.mkdir(parents=True, exist_ok=True)

    stem = _NAME_CLEAN.sub("_", source_path.stem).strip() or "form"
    candidate = directory / f"{stem}{suffix}.pdf"
    counter = 2
    while candidate.exists() and candidate.resolve() != source_path.resolve():
        candidate = directory / f"{stem}{suffix}-{counter}.pdf"
        counter += 1
    if candidate.resolve() == source_path.resolve():  # pragma: no cover - defensive
        candidate = directory / f"{stem}{suffix}-new.pdf"

    return convert_xfa(source_path, candidate, mode=mode)
