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
dateTimeEdit         text field, with the template's picture kept as its format
checkButton          checkbox, with its export value
exclGroup            one radio group; each member a widget with its own value
choiceList           combo box, or list box when it allows several
button               drawn, never live — see below
===================  =========================================================

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


def _font_name(font: XfaFont) -> str:
    """The reportlab base font closest to what the template asked for.

    Only the base-14 are used. Embedding the form's actual typeface would mean
    finding it on this machine and taking on its licence, which is a decision
    Orion leaves to the user elsewhere and should not make silently here.
    """
    base = _BASE_FONTS.get(font.family.strip().lower(), "Helvetica")
    if base == "Times-Roman":
        if font.bold and font.italic:
            return "Times-BoldItalic"
        if font.bold:
            return "Times-Bold"
        if font.italic:
            return "Times-Italic"
        return "Times-Roman"
    if font.bold and font.italic:
        return f"{base}-BoldOblique"
    if font.bold:
        return f"{base}-Bold"
    if font.italic:
        return f"{base}-Oblique"
    return base


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


def _caption_width(field: XfaField) -> float:
    """How much room the caption takes to the left of the box.

    XFA puts a field's label inside the field's own rectangle by default,
    reserving space on one side. Drawing the caption on top of the widget is
    the usual way this goes wrong, so the widget is narrowed instead.
    """
    if not field.caption:
        return 0.0
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


def _draw_field_caption(pdf, field: XfaField, page_height: float, reserve: float) -> None:
    if not field.caption or reserve <= 0:
        return
    x, y, _width, height = rect_to_pdf(field.rect, page_height)
    pdf.saveState()
    pdf.setFillColorRGB(*field.font.color)
    pdf.setFont(_font_name(field.font), field.font.size)
    pdf.drawString(x, y + height - field.font.size, field.caption)
    pdf.restoreState()


def _draw_field_as_static(pdf, field: XfaField, page_height: float) -> None:
    """A field that will not be interactive, drawn so it is not simply lost."""
    reserve = _caption_width(field)
    _draw_field_caption(pdf, field, page_height, reserve)
    x, y, width, height = rect_to_pdf(field.rect, page_height)
    box_x = x + reserve
    box_width = max(width - reserve, 1.0)

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
    reserve = _caption_width(field)
    x, y, width, height = rect_to_pdf(field.rect, page_height)
    box_x = x + reserve
    box_width = max(width - reserve, 8.0)
    box_height = max(height, 8.0)
    font_name = _font_name(field.font)
    size = max(field.font.size, 4.0)

    common = {
        "x": box_x,
        "y": y,
        "borderWidth": field.border_width if field.border_width > 0 else 0.5,
        "borderColor": _grey(field.border_color),
        "fillColor": _grey(field.fill_color) if field.fill_color else None,
        "textColor": _grey(field.font.color),
        "forceBorder": field.border_width > 0,
    }

    if field.field_type in (XfaFieldType.TEXT, XfaFieldType.NUMERIC, XfaFieldType.DATE):
        form.textfield(
            name=name,
            value=field.value or "",
            width=box_width,
            height=box_height,
            fontName=font_name,
            fontSize=size,
            fieldFlags="multiline" if field.multiline else "",
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

        maker = form.listbox if field.choices.multi_select else form.choice
        maker(
            name=name,
            value=chosen,
            options=options,
            width=box_width,
            height=box_height,
            fontName=font_name,
            fontSize=size,
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
                _draw_field_caption(pdf, field, page.height, _caption_width(field))
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
