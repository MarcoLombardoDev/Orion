#!/usr/bin/env python
# Orion — PDF Editor for Desktop
# Copyright (C) 2026 Marco Lombardo
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# Distributed WITHOUT ANY WARRANTY; see LICENSE for the full terms.
# A commercial licence, without the AGPL's obligations, is available for use
# in proprietary or closed-source products — see COMMERCIAL-LICENSE.md.

"""Building XFA documents to test against.

There is no way to obtain an XFA form from a library: Adobe's tooling is gone,
nothing open source writes one, and the format's own producers stopped. So the
fixtures are assembled here — a real XFA package, attached to a real PDF by
its AcroForm dictionary, exactly the way LiveCycle attached one.

These are not mock objects. What comes out is a PDF that any reader will
identify as XFA, with a template and datasets packet the parser has to work
through for real. The shapes covered are the ones that break converters:
nested subforms, an exclusion group, a choice list whose stored values differ
from its labels, a date with a picture clause, a repeatable row with two
instances already in it, and scripts of several kinds.

``build_reference_form`` is modelled on the structure of the document this
feature was asked for — a headed form with a details block, a choice of
device, a date, a repeatable table row and a submit button — so that the
pipeline is exercised end to end even where that file itself is not present.
"""

from __future__ import annotations

import io
from pathlib import Path

__all__ = [
    "XFA_TEMPLATE_NS",
    "build_acroform_pdf",
    "build_plain_pdf",
    "build_reference_form",
    "build_xfa_pdf",
    "dynamic_template",
    "static_template",
]

XFA_TEMPLATE_NS = "http://www.xfa.org/schema/xfa-template/3.0/"
XFA_DATA_NS = "http://www.xfa.org/schema/xfa-data/1.0/"


def build_plain_pdf(path: Path, pages: int = 1) -> Path:
    """An ordinary PDF with no form of any kind."""
    from reportlab.pdfgen import canvas

    pdf = canvas.Canvas(str(path), pagesize=(595.276, 841.89))
    for index in range(pages):
        pdf.setFont("Helvetica", 12)
        pdf.drawString(72, 760, f"Plain page {index + 1}")
        pdf.showPage()
    pdf.save()
    return path


def build_acroform_pdf(path: Path) -> Path:
    """An ordinary interactive PDF form, for the detector to tell apart."""
    from reportlab.pdfgen import canvas

    pdf = canvas.Canvas(str(path), pagesize=(595.276, 841.89))
    pdf.setFont("Helvetica", 12)
    pdf.drawString(72, 780, "Ordinary AcroForm")
    form = pdf.acroForm
    form.textfield(name="surname", x=72, y=720, width=200, height=18, value="")
    form.checkbox(name="agreed", x=72, y=690, size=14)
    pdf.showPage()
    pdf.save()
    return path


def static_template() -> str:
    """A positioned form: every element placed by coordinate.

    This is what XFA calls "foreground" — the PDF page underneath still holds
    the real appearance, and the template merely describes the fields on top.
    """
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<template xmlns="{XFA_TEMPLATE_NS}">
  <subform name="form1" layout="position" w="595.28pt" h="841.89pt">
    <pageSet>
      <pageArea name="Page1">
        <medium short="595.28pt" long="841.89pt" orientation="portrait"/>
        <contentArea x="36pt" y="36pt" w="523.28pt" h="769.89pt"/>
      </pageArea>
    </pageSet>
    <draw name="title" x="36pt" y="36pt" w="400pt" h="24pt">
      <value><text>Static request form</text></value>
      <font typeface="Helvetica" size="16pt" weight="bold"/>
    </draw>
    <field name="surname" x="36pt" y="80pt" w="220pt" h="20pt">
      <ui><textEdit/></ui>
      <caption reserve="80pt"><value><text>Surname</text></value></caption>
      <value><text>Rossi</text></value>
      <border><edge thickness="0.5pt"><color value="0,0,0"/></edge></border>
      <bind ref="$record.surname" match="once"/>
    </field>
    <field name="agreed" x="36pt" y="110pt" w="14pt" h="14pt">
      <ui><checkButton/></ui>
      <caption><value><text>I agree</text></value></caption>
      <items><text>yes</text></items>
    </field>
  </subform>
</template>"""


def dynamic_template() -> str:
    """A flowed form with repeatable rows, an exclusion group and scripts.

    The hard case: the PDF page carries nothing, so every bit of the
    appearance here has to survive the conversion or it is gone.
    """
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<template xmlns="{XFA_TEMPLATE_NS}">
  <subform name="form1" layout="tb" w="595.28pt" h="841.89pt">
    <pageSet>
      <pageArea name="Page1">
        <medium short="595.28pt" long="841.89pt" orientation="portrait"/>
        <contentArea x="36pt" y="36pt" w="523.28pt" h="769.89pt"/>
      </pageArea>
    </pageSet>
    <event activity="initialize">
      <script contentType="application/x-javascript">
        Row.instanceManager.setInstances(2);
      </script>
    </event>

    <subform name="header" layout="position" w="523.28pt" h="60pt">
      <draw name="heading" x="0pt" y="0pt" w="400pt" h="22pt">
        <value><text>Device assignment request</text></value>
        <font typeface="Helvetica" size="15pt" weight="bold"/>
      </draw>
      <draw name="rule" x="0pt" y="26pt" w="523pt" h="1pt">
        <value><line><edge thickness="1pt"><color value="80,80,80"/></edge></line></value>
      </draw>
    </subform>

    <subform name="details" layout="position" w="523.28pt" h="160pt">
      <field name="applicant" x="0pt" y="0pt" w="240pt" h="20pt">
        <ui><textEdit/></ui>
        <caption reserve="90pt"><value><text>Applicant</text></value></caption>
        <border><edge thickness="0.5pt"><color value="0,0,0"/></edge></border>
        <bind ref="$record.applicant" match="once"/>
        <validate nullTest="error"/>
      </field>
      <field name="notes" x="0pt" y="28pt" w="380pt" h="46pt">
        <ui><textEdit multiLine="1"/></ui>
        <caption reserve="90pt"><value><text>Notes</text></value></caption>
      </field>
      <field name="device" x="0pt" y="82pt" w="200pt" h="20pt">
        <ui><choiceList open="userControl"/></ui>
        <caption reserve="90pt"><value><text>Device</text></value></caption>
        <items><text>Laptop</text><text>Telephone</text><text>Tablet</text></items>
        <items save="1" presence="hidden"><text>LT</text><text>TL</text><text>TB</text></items>
        <bind ref="$record.device" match="once"/>
      </field>
      <field name="issued" x="0pt" y="110pt" w="120pt" h="20pt">
        <ui><dateTimeEdit/></ui>
        <caption reserve="90pt"><value><text>Issued on</text></value></caption>
        <format><picture>DD/MM/YYYY</picture></format>
        <bind ref="$record.issued" match="once"/>
      </field>
      <field name="quantity" x="220pt" y="110pt" w="80pt" h="20pt">
        <ui><numericEdit/></ui>
        <caption reserve="60pt"><value><text>How many</text></value></caption>
        <format><picture>num{{zzz9}}</picture></format>
        <calculate>
          <script contentType="application/x-javascript">
            this.rawValue = Row.instanceManager.count;
          </script>
        </calculate>
      </field>
    </subform>

    <exclGroup name="urgency" x="0pt" y="0pt" w="300pt" h="20pt">
      <field name="normal" x="0pt" y="0pt" w="14pt" h="14pt">
        <ui><checkButton/></ui>
        <caption><value><text>Normal</text></value></caption>
        <items><text>N</text></items>
      </field>
      <field name="urgent" x="100pt" y="0pt" w="14pt" h="14pt">
        <ui><checkButton/></ui>
        <caption><value><text>Urgent</text></value></caption>
        <items><text>U</text></items>
      </field>
      <value><text>N</text></value>
    </exclGroup>

    <subform name="Row" layout="position" w="523.28pt" h="24pt">
      <occur min="1" max="-1" initial="2"/>
      <field name="item" x="0pt" y="0pt" w="200pt" h="18pt">
        <ui><textEdit/></ui>
        <caption reserve="60pt"><value><text>Item</text></value></caption>
        <border><edge thickness="0.5pt"><color value="0,0,0"/></edge></border>
      </field>
      <field name="serial" x="220pt" y="0pt" w="160pt" h="18pt">
        <ui><textEdit/></ui>
        <caption reserve="50pt"><value><text>Serial</text></value></caption>
        <border><edge thickness="0.5pt"><color value="0,0,0"/></edge></border>
      </field>
    </subform>

    <field name="addRow" x="0pt" y="0pt" w="90pt" h="20pt">
      <ui><button/></ui>
      <caption><value><text>Add a row</text></value></caption>
      <event activity="click">
        <script contentType="application/x-javascript">
          Row.instanceManager.addInstance(1);
        </script>
      </event>
    </field>
    <field name="send" x="110pt" y="0pt" w="90pt" h="20pt">
      <ui><button/></ui>
      <caption><value><text>Submit</text></value></caption>
      <event activity="click">
        <script contentType="application/x-javascript">
          xfa.host.messageBox("submitting"); event.target.submitForm();
        </script>
      </event>
    </field>
  </subform>
</template>"""


def _datasets(values: dict[str, str]) -> str:
    rows = "".join(f"<{name}>{value}</{name}>" for name, value in values.items())
    return (
        f'<?xml version="1.0" encoding="UTF-8"?>'
        f'<xfa:datasets xmlns:xfa="{XFA_DATA_NS}">'
        f"<xfa:data><record>{rows}</record></xfa:data>"
        f"</xfa:datasets>"
    )


def build_xfa_pdf(
    path: Path,
    template: str,
    *,
    data: dict[str, str] | None = None,
    dynamic: bool = True,
    with_acroform: bool = False,
    placeholder: bool = True,
) -> Path:
    """Write a PDF carrying *template* as a real XFA package.

    The packets go into ``/AcroForm /XFA`` as the name/stream array LiveCycle
    writes, and a dynamic form additionally sets ``/NeedsRendering`` — which
    is the producer stating outright that its pages are not the form.
    """
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import (
        ArrayObject,
        BooleanObject,
        DecodedStreamObject,
        DictionaryObject,
        NameObject,
        NumberObject,
        TextStringObject,
    )
    from reportlab.pdfgen import canvas

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=(595.276, 841.89))
    if placeholder and dynamic:
        # What a dynamic XFA actually shows in a reader that cannot render it.
        pdf.setFont("Helvetica", 11)
        pdf.drawString(
            72, 700, "If this message is not eventually replaced by the proper"
        )
        pdf.drawString(72, 685, "contents of the document, your PDF viewer may not be")
        pdf.drawString(72, 670, "able to display this type of document.")
    else:
        pdf.setFont("Helvetica-Bold", 16)
        pdf.drawString(36, 780, "Static request form")
        pdf.setFont("Helvetica", 10)
        pdf.drawString(36, 745, "Surname")
        pdf.drawString(36, 715, "I agree")
    if with_acroform:
        pdf.acroForm.textfield(name="surname", x=120, y=740, width=200, height=18)
    pdf.showPage()
    pdf.save()
    buffer.seek(0)

    writer = PdfWriter(clone_from=PdfReader(buffer))

    def stream_of(text: str) -> DecodedStreamObject:
        stream = DecodedStreamObject()
        stream.set_data(text.encode("utf-8"))
        return writer._add_object(stream)

    packets = ArrayObject(
        [
            TextStringObject("template"),
            stream_of(template),
            TextStringObject("datasets"),
            stream_of(_datasets(data or {})),
            TextStringObject("config"),
            stream_of(
                '<config xmlns="http://www.xfa.org/schema/xci/3.0/"><present>'
                f"<pdf><interactive>1</interactive></pdf>"
                f"<dynamicRender>{'required' if dynamic else 'forbidden'}</dynamicRender>"
                "</present></config>"
            ),
        ]
    )

    root = writer._root_object
    acroform = root.get("/AcroForm")
    if acroform is None:
        acroform = DictionaryObject()
        acroform[NameObject("/Fields")] = ArrayObject()
        root[NameObject("/AcroForm")] = writer._add_object(acroform)
    else:
        acroform = acroform.get_object()
    acroform[NameObject("/XFA")] = packets
    if dynamic:
        root[NameObject("/NeedsRendering")] = BooleanObject(True)
        acroform[NameObject("/SigFlags")] = NumberObject(0)

    with open(path, "wb") as handle:
        writer.write(handle)
    return path


def build_reference_form(path: Path) -> Path:
    """The dynamic fixture, filled in — the closest stand-in for the real file."""
    return build_xfa_pdf(
        path,
        dynamic_template(),
        data={
            "applicant": "Mario Rossi",
            "device": "LT",
            "issued": "2026-09-20",
        },
        dynamic=True,
    )
