#!/usr/bin/env python
# Orion — PDF Editor for Desktop
# Copyright (C) 2026 Marco Lombardo
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# Distributed WITHOUT ANY WARRANTY; see LICENSE for the full terms.
# A commercial licence, without the AGPL's obligations, is available for use
# in proprietary or closed-source products — see COMMERCIAL-LICENSE.md.

"""Form fields as objects: reading them, moving them, saving them back.

The fault these were written for is the one every PDF editor has: a form field
is drawn and cannot be touched. Converting an XFA form made it acute — the
fields land where the *template* put them, and one that came out a millimetre
off could not be nudged.

What matters here is the round trip and what survives it. A field that can be
dragged but arrives at the other end having lost its options, its flags or its
tooltip has not been moved; it has been replaced by a box with the same name.
"""

from __future__ import annotations

import pytest
from pypdf import PdfReader

from orion.document.forms import FormFieldKind, FormFieldObject
from orion.pdf import reader as pdf_reader
from orion.pdf import writer as pdf_writer
from orion.pdf.coordinates import PageGeometry
from orion.pdf.form_import import import_form_fields


def _form_pdf(path, *, value: str = "Mario") -> str:
    """A PDF with one of each field kind, written by reportlab."""
    from reportlab.pdfgen import canvas

    pdf = canvas.Canvas(str(path), pagesize=(595.276, 841.89))
    form = pdf.acroForm
    form.textfield(
        name="applicant",
        value=value,
        x=72,
        y=700,
        width=200,
        height=20,
        tooltip="Who is asking",
        fieldFlags="required",
        borderColor=None,
    )
    form.choice(
        name="device",
        value="Laptop",
        options=[("Laptop", "LT"), ("Telephone", "TL"), ("Tablet", "TB")],
        x=72,
        y=660,
        width=200,
        height=20,
    )
    form.checkbox(name="urgent", checked=True, x=72, y=620, size=14)
    pdf.showPage()
    pdf.save()
    return str(path)


def _fields_of(document, index: int = 0) -> list[FormFieldObject]:
    return [o for o in document[index].objects if isinstance(o, FormFieldObject)]


class TestReadingThemIn:
    def test_every_widget_becomes_an_object(self, tmp_path):
        source = _form_pdf(tmp_path / "form.pdf")
        opened = pdf_reader.open_pdf(source)
        try:
            document = pdf_reader.build_document(opened)
        finally:
            opened.close()

        fields = _fields_of(document)
        assert {f.name for f in fields} == {"applicant", "device", "urgent"}
        assert document[0].imported_fields == (0, 1, 2)

    def test_each_one_knows_what_kind_it_is(self, tmp_path):
        source = _form_pdf(tmp_path / "kinds.pdf")
        opened = pdf_reader.open_pdf(source)
        try:
            fields = {f.name: f for f in _fields_of(pdf_reader.build_document(opened))}
        finally:
            opened.close()

        assert fields["applicant"].field_kind is FormFieldKind.TEXT
        assert fields["device"].field_kind is FormFieldKind.CHOICE
        assert fields["urgent"].field_kind is FormFieldKind.CHECKBOX
        assert fields["urgent"].checked

    def test_the_value_and_the_flags_come_across(self, tmp_path):
        source = _form_pdf(tmp_path / "flags.pdf", value="Mario Rossi")
        opened = pdf_reader.open_pdf(source)
        try:
            fields = {f.name: f for f in _fields_of(pdf_reader.build_document(opened))}
        finally:
            opened.close()

        assert fields["applicant"].value == "Mario Rossi"
        assert fields["applicant"].required
        assert fields["applicant"].tooltip == "Who is asking"
        assert len(fields["device"].options) == 3

    def test_a_widget_with_no_usable_rectangle_is_left_alone(self, tmp_path):
        """Skipping it also leaves it in the file, which is the safe answer."""
        from pypdf.generic import ArrayObject, DictionaryObject, FloatObject, NameObject

        entry = DictionaryObject(
            {
                NameObject("/Subtype"): NameObject("/Widget"),
                NameObject("/FT"): NameObject("/Tx"),
                NameObject("/Rect"): ArrayObject([FloatObject(0) for _ in range(4)]),
            }
        )

        class _Page(dict):
            pass

        page = _Page({"/Annots": [entry]})
        geometry = PageGeometry(width=595.276, height=841.89, rotation=0)
        assert import_form_fields(page, geometry).objects == []

    def test_the_name_carries_its_parents_with_it(self, tmp_path):
        """Two fields differing only by parent must not collapse into one."""
        from pypdf.generic import (
            ArrayObject,
            DictionaryObject,
            FloatObject,
            NameObject,
            TextStringObject,
        )

        parent = DictionaryObject(
            {
                NameObject("/T"): TextStringObject("section"),
                NameObject("/FT"): NameObject("/Tx"),
            }
        )
        entry = DictionaryObject(
            {
                NameObject("/Subtype"): NameObject("/Widget"),
                NameObject("/T"): TextStringObject("name"),
                NameObject("/Parent"): parent,
                NameObject("/Rect"): ArrayObject(
                    [FloatObject(10), FloatObject(10), FloatObject(110), FloatObject(30)]
                ),
            }
        )

        class _Page(dict):
            pass

        geometry = PageGeometry(width=595.276, height=841.89, rotation=0)
        imported = import_form_fields(_Page({"/Annots": [entry]}), geometry)
        assert imported.objects[0].name == "section.name"
        assert imported.objects[0].field_kind is FormFieldKind.TEXT


class TestMovingThem:
    def _reopen(self, path):
        opened = pdf_reader.open_pdf(path)
        try:
            return pdf_reader.build_document(opened)
        finally:
            opened.close()

    def test_a_moved_field_moves_in_the_file(self, tmp_path):
        source = _form_pdf(tmp_path / "move.pdf")
        document = self._reopen(source)
        page = document[0]
        field = next(f for f in _fields_of(document) if f.name == "applicant")
        page.objects = [
            f.moved_by(30.0, 15.0) if f is field else f for f in page.objects
        ]

        out = tmp_path / "moved.pdf"
        pdf_writer.save_document(document, out)

        before = _widget(source, "applicant")
        after = _widget(out, "applicant")
        assert after[0] == pytest.approx(before[0] + 30.0, abs=0.05)
        # Orion's y runs down the page and the PDF's runs up it.
        assert after[1] == pytest.approx(before[1] - 15.0, abs=0.05)

    def test_moving_one_costs_it_nothing(self, tmp_path):
        """Its options, flags and tooltip are the field; the /Rect is not."""
        source = _form_pdf(tmp_path / "keep.pdf")
        document = self._reopen(source)
        page = document[0]
        page.objects = [f.moved_by(5.0, 5.0) for f in page.objects]
        out = tmp_path / "kept.pdf"
        pdf_writer.save_document(document, out)

        before = PdfReader(str(source)).get_fields() or {}
        after = PdfReader(str(out)).get_fields() or {}
        assert set(after) == set(before)
        assert len(after["device"].get("/Opt")) == len(before["device"].get("/Opt"))
        assert after["applicant"].get("/Ff") == before["applicant"].get("/Ff")
        assert after["applicant"].get("/TU") == before["applicant"].get("/TU")

    def test_deleting_the_object_deletes_the_field(self, tmp_path):
        source = _form_pdf(tmp_path / "delete.pdf")
        document = self._reopen(source)
        page = document[0]
        page.objects = [
            o
            for o in page.objects
            if not (isinstance(o, FormFieldObject) and o.name == "urgent")
        ]

        out = tmp_path / "deleted.pdf"
        pdf_writer.save_document(document, out)
        names = set(PdfReader(str(out)).get_fields() or {})
        assert "urgent" not in names
        assert {"applicant", "device"} <= names

    def test_a_field_survives_being_opened_and_saved_untouched(self, tmp_path):
        source = _form_pdf(tmp_path / "round.pdf")
        document = self._reopen(source)
        out = tmp_path / "round-saved.pdf"
        pdf_writer.save_document(document, out)

        again = self._reopen(out)
        assert {f.name for f in _fields_of(again)} == {"applicant", "device", "urgent"}
        assert _widget(out, "applicant") == pytest.approx(
            _widget(source, "applicant"), abs=0.05
        )


def _widget(path, name: str) -> list[float]:
    for page in PdfReader(str(path)).pages:
        for annotation in page.get("/Annots") or []:
            widget = annotation.get_object()
            if str(widget.get("/T")) == name:
                return [float(v) for v in widget["/Rect"]]
    raise AssertionError(f"no widget named {name} in {path}")
