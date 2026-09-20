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
from pathlib import Path

from orion.xfa.detector import FormInfo, inspect_form
from orion.xfa.layout import LaidOutForm, rect_to_pdf, resolve_layout
from orion.xfa.model import (
    XfaButton,
    XfaDocument,
    XfaDraw,
    XfaField,
    XfaFieldType,
    XfaFont,
)
from orion.xfa.parser import parse_xfa
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
    reserve = min(reserve, max(width - 8.0, 0.0))
    if reserve <= 0:
        return None, (x, y, width, height)
    if placement == "right":
        return (x + width - reserve, y, reserve, height), (x, y, width - reserve, height)
    return (x, y, reserve, height), (x + reserve, y, width - reserve, height)


def _measured_caption(field: XfaField) -> float:
    """Room for the label when the template does not say how much it needs."""
    from reportlab.pdfbase.pdfmetrics import stringWidth

    width = stringWidth(field.caption, _font_name(field.font), field.font.size)
    return min(width + 6.0, max(field.rect.width * 0.5, 0.0))


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
            x, y, width, height,
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
    _draw_wrapped(pdf, item.text, x, y, width, height, item.font, font_name, item.align)
    pdf.restoreState()


def _draw_wrapped(pdf, text, x, y, width, height, font: XfaFont, font_name, align) -> None:
    """Text inside its box, wrapped, top-aligned the way XFA lays it out."""
    from reportlab.pdfbase.pdfmetrics import stringWidth

    leading = font.size * 1.2
    limit = max(width, 1.0)
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if stringWidth(candidate, font_name, font.size) <= limit or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)

    top = y + height - font.size
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


def _draw_field_caption(pdf, field: XfaField, rect) -> None:
    """The field's label, inside the part of the box reserved for it."""
    if not field.caption or rect is None:
        return
    x, y, width, height = rect
    font_name = _font_name(field.font)
    pdf.saveState()
    pdf.setFillColorRGB(*field.font.color)
    pdf.setFont(font_name, field.font.size)
    _draw_wrapped(
        pdf, field.caption, x, y, max(width, 1.0), height, field.font, font_name, "left"
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
    if field.border_width > 0:
        pdf.setStrokeColorRGB(*field.border_color)
        pdf.setLineWidth(field.border_width)
        pdf.rect(box_x, y, box_width, height, stroke=1, fill=0)
    if field.value:
        pdf.setFillColorRGB(*field.font.color)
        font_name = _font_name(field.font)
        pdf.setFont(font_name, field.font.size)
        _draw_wrapped(
            pdf, field.value, box_x + 2, y, box_width - 4, height, field.font, font_name, "left"
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


def _add_widget(
    pdf, field: XfaField, page_height: float, name: str, radio_state, blank_choices: set[str]
) -> bool:
    """Create the AcroForm widget for *field*. True when one was made."""
    form = pdf.acroForm
    _caption, (box_x, y, box_width, box_height) = _split_for_caption(field, page_height)
    box_width = max(box_width, 8.0)
    box_height = max(box_height, 8.0)
    # reportlab raises on any other font when it builds a widget, so this one
    # call asks for the stand-in rather than the embedded face.
    font_name = _font_name(field.font, embed=False)
    size = max(field.font.size, 4.0)

    common = {
        "x": box_x,
        "y": y,
        "borderWidth": field.border_width if field.border_width > 0 else 0.5,
        "borderColor": _grey(field.border_color),
        "fillColor": _grey(field.fill_color) if field.fill_color else None,
        "textColor": _grey(field.font.color),
        "forceBorder": field.border_width > 0,
        "tooltip": _tooltip(field) or None,
    }

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
            value=field.value or "",
            width=box_width,
            height=box_height,
            fontName=font_name,
            fontSize=size,
            fieldFlags=" ".join([*state, *(["multiline"] if field.multiline else [])]),
            maxlen=field.max_length or None,
            **common,
        )
        return True

    if field.field_type is XfaFieldType.CHECKBOX:
        form.checkbox(
            name=name,
            checked=_checked(field),
            size=min(box_height, box_width),
            buttonStyle="check",
            fieldFlags=" ".join(state),
            **common,
        )
        return True

    if field.field_type is XfaFieldType.RADIO:
        group = field.group or field.som
        selected = _checked(field)
        form.radio(
            name=radio_state.name_for(group),
            value=field.export_value or field.name or "on",
            selected=selected,
            size=min(box_height, box_width),
            buttonStyle="circle",
            shape="circle",
            fieldFlags=" ".join(["radio", *state]),
            **common,
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


def _clear_blank_choices(path: Path, names: set[str]) -> None:
    """Undo the placeholder selection forced on us by reportlab.

    Removing ``/V``, ``/DV`` and ``/I`` leaves the field exactly as an
    untouched drop-down should be: its options intact, nothing chosen. The
    default value matters as much as the value, because a viewer that finds no
    value falls back to it and shows the placeholder anyway — and the drawn
    appearance matters as much as both, which is what
    :func:`_blank_appearance` replaces.
    """
    if not names:
        return
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import NameObject

    try:
        writer = PdfWriter(clone_from=PdfReader(str(path)))
        for page in writer.pages:
            for annotation in page.get("/Annots") or []:
                widget = annotation.get_object()
                if str(widget.get("/T", "")) not in names:
                    continue
                for key in ("/V", "/DV", "/I"):
                    if key in widget:
                        del widget[NameObject(key)]
                widget[NameObject("/AP")] = _blank_appearance(widget, writer)
        with open(path, "wb") as handle:
            writer.write(handle)
    except Exception:  # pragma: no cover - a preselected list beats no file
        log.warning("Could not clear the placeholder choice values", exc_info=True)


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
    report = XfaConversionReport(
        source_file=str(source_path), mode=mode, output_file=""
    )

    info = info or inspect_form(source_path)
    report.detected_type = info.form_type.value
    if not info.is_xfa:
        report.error(
            "This document does not contain an XFA form, so there is nothing "
            "to convert."
        )
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

    pdf = canvas.Canvas(str(output_path), pagesize=(form.pages[0].width, form.pages[0].height))
    pdf.setTitle(output_path.stem)

    # A real form hides fields until a script decides they apply — four of
    # them in a form of nineteen is normal. The scripts are not coming with
    # us, so in a mode that keeps fields the hidden ones are shown: a field
    # nothing can ever reveal again is a field the user has lost. A static
    # copy is a different promise — it stands in for the printed form — so
    # there the template's own answer is kept.
    show_hidden = mode.wants_fields

    for page in form.pages:
        pdf.setPageSize((page.width, page.height))

        for drawn in page.draws:
            if drawn.hidden and not show_hidden:
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
            if button.hidden and not show_hidden:
                continue
            _draw_button(pdf, button, page.height)
            static += 1

        for field in page.fields:
            if field.hidden:
                if not show_hidden:
                    continue
                hidden_shown += 1
            interactive = mode.wants_fields and field.is_interactive
            if interactive:
                name = (
                    radio_names.name_for(field.group or field.som)
                    if field.field_type is XfaFieldType.RADIO
                    else _safe_name(field.qualified_name, used_names)
                )
                _draw_field_caption(pdf, field, _split_for_caption(field, page.height)[0])
                try:
                    made = _add_widget(
                        pdf, field, page.height, name, radio_names, blank_choices
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
    _clear_blank_choices(output_path, blank_choices)
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
        report.info(
            "Converted to a static document, as asked: nothing in it is fillable."
        )

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
        if button.kind.value in ("instance", "submit", "reset", "print", "scripted"):
            report.info(
                f"The '{button.caption or button.name}' button is shown but no "
                "longer does anything.",
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
