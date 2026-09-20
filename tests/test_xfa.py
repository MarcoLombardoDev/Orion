#!/usr/bin/env python
# Orion — PDF Editor for Desktop
# Copyright (C) 2026 Marco Lombardo
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# Distributed WITHOUT ANY WARRANTY; see LICENSE for the full terms.
# A commercial licence, without the AGPL's obligations, is available for use
# in proprietary or closed-source products — see COMMERCIAL-LICENSE.md.

"""XFA forms: recognising, reading and converting them.

The fixtures are real PDFs carrying real XFA packages — see
``tests/xfa_fixtures.py`` for why they have to be built rather than obtained.
The converted output is checked by reopening it with **pypdf**, which is not
the library that wrote it, so a field that both agree on is a field that is
actually in the file.
"""

from __future__ import annotations

import pathlib

import pytest

from orion.xfa import (
    ConversionMode,
    PdfFormType,
    convert_xfa,
    detect_form_type,
    inspect_form,
    parse_xfa,
    summarise_form,
    validate_converted_pdf,
)
from orion.xfa.layout import resolve_layout
from orion.xfa.model import XfaFieldType, XfaScriptKind
from orion.xfa.parser import parse_measurement
from orion.xfa.report import Fidelity
from orion.xfa.safe_xml import XmlRejected, parse_xml
from orion.xfa.validator import opens_in_orion
from tests.xfa_fixtures import (
    build_acroform_pdf,
    build_plain_pdf,
    build_reference_form,
    build_xfa_pdf,
    static_template,
)

REPO = pathlib.Path(__file__).resolve().parent.parent

#: The document this feature was asked for. Not in the repository — it is
#: somebody's real form — so the tests that need it skip until it is put here.
REFERENCE_PDF = REPO / "tests" / "data" / "Mod. 1 - Richiesta Assegnazione Dispositivi.pdf"


@pytest.fixture
def plain(tmp_path):
    return build_plain_pdf(tmp_path / "plain.pdf")


@pytest.fixture
def acroform(tmp_path):
    return build_acroform_pdf(tmp_path / "acro.pdf")


@pytest.fixture
def xfa_static(tmp_path):
    return build_xfa_pdf(
        tmp_path / "static.pdf", static_template(), data={"surname": "Rossi"}, dynamic=False
    )


@pytest.fixture
def xfa_dynamic(tmp_path):
    return build_reference_form(tmp_path / "dynamic.pdf")


@pytest.fixture
def xfa_both(tmp_path):
    return build_xfa_pdf(
        tmp_path / "both.pdf", static_template(), dynamic=False, with_acroform=True
    )


@pytest.fixture
def converted(tmp_path, xfa_dynamic):
    """The dynamic fixture, converted once and reused."""
    return convert_xfa(xfa_dynamic, tmp_path / "out.pdf", mode=ConversionMode.KEEP_FIELDS)


# == 1-5: telling the kinds of document apart ==============================
def test_an_ordinary_pdf_is_not_a_form(plain):
    """Test 1. Nothing about a plain document may look like XFA."""
    assert detect_form_type(plain) is PdfFormType.NONE


def test_an_acroform_is_recognised_as_one(acroform):
    """Test 2. An ordinary interactive form is not XFA and needs no conversion."""
    info = inspect_form(acroform)
    assert info.form_type is PdfFormType.ACROFORM
    assert not info.form_type.needs_conversion
    assert "surname" in info.acroform_fields


def test_a_static_xfa_is_recognised(xfa_static):
    """Test 3."""
    info = inspect_form(xfa_static)
    assert info.form_type is PdfFormType.XFA_STATIC
    assert info.template and info.datasets


def test_a_dynamic_xfa_is_recognised(xfa_dynamic):
    """Test 4. And it must not be mistaken for the static kind.

    The difference decides whether the original pages are worth keeping, so
    guessing "static" produces a converted document that is blank.
    """
    info = inspect_form(xfa_dynamic)
    assert info.form_type is PdfFormType.XFA_DYNAMIC
    assert info.needs_rendering


def test_xfa_alongside_an_acroform_is_recognised(xfa_both):
    """Test 5."""
    info = inspect_form(xfa_both)
    assert info.form_type is PdfFormType.XFA_WITH_ACROFORM
    assert info.acroform_fields


def test_detection_reads_structure_rather_than_the_page(tmp_path):
    """The placeholder wording is a symptom, and symptoms lie.

    A perfectly ordinary PDF may contain that sentence — this one does — and
    a detector matching on it would offer to convert a document with no form.
    """
    from reportlab.pdfgen import canvas

    path = tmp_path / "decoy.pdf"
    pdf = canvas.Canvas(str(path))
    pdf.drawString(72, 700, "If this message is not eventually replaced by the proper")
    pdf.drawString(72, 685, "contents of the document, your PDF viewer may not be able")
    pdf.save()
    assert detect_form_type(path) is PdfFormType.NONE


def test_an_unreadable_file_does_not_raise(tmp_path):
    """Detection runs on every open, so it must never be what breaks one."""
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"%PDF-1.7\nnot really a pdf")
    assert detect_form_type(broken) is PdfFormType.FLATTENED_OR_UNKNOWN


# == the XML is hostile until proven otherwise =============================
class TestTheXmlIsTreatedAsHostile:
    """Test 13, and the rest of the security requirement.

    Every one of these is a real attack on an XML parser, and every one
    arrives inside a document the user merely opened.
    """

    def test_an_ordinary_packet_parses(self):
        root = parse_xml(b'<template xmlns="x"><subform name="a"/></template>')
        assert len(list(root)) == 1

    @pytest.mark.parametrize(
        "name, payload",
        [
            (
                "external entity",
                b'<!DOCTYPE r [<!ENTITY f SYSTEM "file:///etc/passwd">]><r>&f;</r>',
            ),
            (
                "billion laughs",
                b'<!DOCTYPE l [<!ENTITY a "x"><!ENTITY b "&a;&a;&a;&a;&a;">]><l>&b;</l>',
            ),
            ("external dtd", b'<!DOCTYPE r SYSTEM "http://example.invalid/x.dtd"><r/>'),
        ],
    )
    def test_entity_attacks_are_refused(self, name, payload):
        with pytest.raises(XmlRejected):
            parse_xml(payload)

    def test_a_depth_bomb_is_refused(self):
        with pytest.raises(XmlRejected):
            parse_xml(b"<a>" * 400 + b"</a>" * 400)

    def test_an_enormous_packet_is_refused(self):
        from orion.xfa.safe_xml import MAX_XML_BYTES

        with pytest.raises(XmlRejected):
            parse_xml(b"<a/>" + b" " * (MAX_XML_BYTES + 1))

    def test_malformed_xml_is_refused_rather_than_guessed_at(self):
        with pytest.raises(XmlRejected):
            parse_xml(b"<a><b></a>")

    def test_scripts_are_read_but_never_run(self, xfa_dynamic, tmp_path):
        """The scripts in the fixture would be obvious if they ran.

        Parsing, analysing and converting all touch the script text; none of
        them may do anything with it but look at it.
        """
        marker = tmp_path / "script-ran"
        document = parse_xfa(inspect_form(xfa_dynamic).packets)
        assert document.scripts, "the fixture has scripts to be careful with"
        convert_xfa(xfa_dynamic, tmp_path / "out.pdf")
        assert not marker.exists()
        # And the text survived as data, which is what the report needs.
        assert any("instanceManager" in s.source for s in document.scripts)


# == reading the template ==================================================
def test_measurements_become_points():
    """XFA writes lengths in whatever unit suits; everything downstream is points."""
    assert parse_measurement("72pt") == pytest.approx(72.0)
    assert parse_measurement("1in") == pytest.approx(72.0)
    assert parse_measurement("25.4mm") == pytest.approx(72.0)
    assert parse_measurement("2.54cm") == pytest.approx(72.0)
    assert parse_measurement("36") == pytest.approx(36.0)
    assert parse_measurement(None, 5.0) == pytest.approx(5.0)
    assert parse_measurement("nonsense", 3.0) == pytest.approx(3.0)


class TestReadingTheForm:
    """Every field type the requirement names, out of a real template."""

    @pytest.fixture
    def document(self, xfa_dynamic):
        return parse_xfa(inspect_form(xfa_dynamic).packets)

    def test_the_template_and_data_both_parse(self, document):
        assert not document.warnings
        assert document.fields
        assert document.data

    def test_a_text_field_is_read(self, document):
        field = self._by_name(document, "applicant")
        assert field.field_type is XfaFieldType.TEXT
        assert field.caption == "Applicant"
        assert field.mandatory, "nullTest=error means the field is required"

    def test_a_multiline_field_is_read_as_one(self, document):
        assert self._by_name(document, "notes").multiline

    def test_a_choice_list_keeps_labels_and_stored_values(self, document):
        """The two differ, and a converter that keeps only one breaks the data."""
        field = self._by_name(document, "device")
        assert field.field_type is XfaFieldType.CHOICE
        assert [label for label, _ in field.choices.pairs] == ["Laptop", "Telephone", "Tablet"]
        assert [value for _, value in field.choices.pairs] == ["LT", "TL", "TB"]

    def test_a_date_field_keeps_its_format(self, document):
        field = self._by_name(document, "issued")
        assert field.field_type is XfaFieldType.DATE
        assert field.picture == "DD/MM/YYYY"

    def test_a_numeric_field_is_told_from_a_text_one(self, document):
        assert self._by_name(document, "quantity").field_type is XfaFieldType.NUMERIC

    def test_an_exclusion_group_becomes_radio_fields_sharing_a_group(self, document):
        radios = [f for f in document.fields if f.field_type is XfaFieldType.RADIO]
        assert len(radios) == 2
        assert len({f.group for f in radios}) == 1, "both belong to one group"
        assert {f.export_value for f in radios} == {"N", "U"}
        assert all(f.value == "N" for f in radios), "the group's value reaches its members"

    def test_values_come_from_the_datasets_packet(self, document):
        assert self._by_name(document, "applicant").value == "Mario Rossi"
        assert self._by_name(document, "device").value == "LT"

    def test_buttons_are_classified_by_what_they_did(self, document):
        kinds = {b.name: b.kind.value for b in document.buttons}
        assert kinds["addRow"] == "instance"
        assert kinds["send"] == "submit"

    def test_scripts_are_classified(self, document):
        kinds = {s.kind for s in document.scripts}
        assert XfaScriptKind.DYNAMIC_LAYOUT in kinds
        assert XfaScriptKind.CALCULATION in kinds
        assert all(not s.convertible for s in document.scripts)

    def test_a_repeatable_subform_is_recognised(self, document):
        repeatable = document.repeatable_subforms
        assert len(repeatable) == 1
        assert repeatable[0].occur.max == -1, "unbounded"
        assert repeatable[0].occur.initial == 2

    def test_the_summary_counts_what_is_there(self, document):
        summary = summarise_form(document)
        assert summary.fields == len(document.fields)
        assert summary.choice_lists == 1
        assert summary.date_fields == 1
        assert summary.repeatable == 1

    @staticmethod
    def _by_name(document, name):
        for field in document.fields:
            if field.name == name:
                return field
        raise AssertionError(f"no field named {name}: {[f.name for f in document.fields]}")


# == 11, 12: layout =========================================================
class TestLayout:
    @pytest.fixture
    def form(self, xfa_dynamic):
        return resolve_layout(parse_xfa(inspect_form(xfa_dynamic).packets))

    def test_every_element_lands_on_a_page(self, form):
        """Test 11. A field with no page is a field nobody will ever see."""
        assert form.pages
        for field in form.fields:
            assert field.page >= 0
            assert field.rect.width > 0 and field.rect.height > 0

    def test_nested_subforms_accumulate_their_offsets(self, form):
        """Test 11. A child's coordinates are relative to its parent, not the page."""
        applicant = next(f for f in form.fields if f.name == "applicant")
        # The template puts it at y=0 inside `details`, which is itself below
        # the header — so a correct layout has it well down the page.
        assert applicant.rect.y > 60, "the subform's own offset was not applied"
        assert applicant.rect.x >= 36, "the page margin was not applied"

    def test_the_existing_instances_of_a_repeating_row_are_kept(self, form):
        """Test 12. Two rows in the template means two rows in the output."""
        assert form.instances == {"form1.Row": 2}
        items = [f for f in form.fields if f.name == "item"]
        assert len(items) == 2
        assert items[0].rect.y != items[1].rect.y, "the rows sit on top of each other"

    def test_repeated_fields_get_distinct_names(self, form):
        """Otherwise both rows become one field that fills in twice."""
        names = [f.qualified_name for f in form.fields if f.name == "item"]
        assert len(set(names)) == 2

    def test_members_of_one_radio_group_share_a_line(self, form):
        """The group is one thing on the page, not two stacked things."""
        radios = [f for f in form.fields if f.field_type is XfaFieldType.RADIO]
        assert radios[0].rect.y == pytest.approx(radios[1].rect.y)
        assert radios[0].rect.x != radios[1].rect.x

    def test_a_template_that_cannot_be_laid_out_still_yields_a_page(self):
        """The caller's fallback is better than an exception mid-open."""
        from orion.xfa.model import XfaDocument

        form = resolve_layout(XfaDocument())
        assert len(form.pages) == 1


# == 6-10: the conversion ==================================================
class TestConversion:
    def test_the_original_file_is_never_touched(self, xfa_dynamic, tmp_path):
        before = xfa_dynamic.read_bytes()
        convert_xfa(xfa_dynamic, tmp_path / "out.pdf")
        assert xfa_dynamic.read_bytes() == before

    def test_the_output_is_a_real_acroform(self, converted):
        """Test 14, and the point of the whole feature.

        Read back with pypdf, which did not write it.
        """
        from pypdf import PdfReader

        assert converted.succeeded
        reader = PdfReader(str(converted.output))
        assert "/AcroForm" in reader.trailer["/Root"]
        assert reader.get_fields()

    def test_the_converted_document_opens_in_orion(self, converted):
        """The check that matters to the user, made with Orion's own reader."""
        ok, detail = opens_in_orion(converted.output)
        assert ok, detail

    def test_a_text_field_converts_with_its_value(self, converted):
        """Test 6."""
        spec = self._fields(converted)["form1.details.applicant"]
        assert str(spec.get("/FT")) == "/Tx"
        assert str(spec.get("/V")) == "Mario Rossi"

    def test_a_multiline_field_stays_multiline(self, converted):
        spec = self._fields(converted)["form1.details.notes"]
        flags = int(spec.get("/Ff", 0))
        assert flags & (1 << 12), "the multiline flag was not set"

    def test_a_checkbox_converts(self, tmp_path):
        """Test 7. From the static fixture, which has one."""
        source = build_xfa_pdf(
            tmp_path / "cb.pdf", static_template(), dynamic=False
        )
        result = convert_xfa(source, tmp_path / "cb-out.pdf")
        fields = self._fields(result)
        checkbox = fields["form1.agreed"]
        assert str(checkbox.get("/FT")) == "/Btn"

    def test_a_radio_group_converts_as_one_field(self, converted):
        """Test 8. Two XFA fields, one AcroForm field with two widgets."""
        fields = self._fields(converted)
        assert "form1.urgency" in fields
        group = fields["form1.urgency"]
        assert str(group.get("/FT")) == "/Btn"
        assert "normal" not in fields and "urgent" not in fields

    def test_the_selected_radio_is_the_one_that_was_selected(self, converted):
        group = self._fields(converted)["form1.urgency"]
        assert str(group.get("/V")) == "/N"

    def test_a_choice_list_converts_with_all_its_options(self, converted):
        """Test 9."""
        spec = self._fields(converted)["form1.details.device"]
        assert str(spec.get("/FT")) == "/Ch"
        options = spec.get("/Opt") or []
        assert len(options) == 3
        assert str(spec.get("/V")) == "LT", "the stored value, not the label"

    def test_a_date_field_converts_and_keeps_its_value(self, converted):
        """Test 10."""
        spec = self._fields(converted)["form1.details.issued"]
        assert str(spec.get("/FT")) == "/Tx"
        assert str(spec.get("/V")) == "2026-09-20"

    def test_every_field_name_is_unique(self, converted):
        names = list(self._fields(converted))
        assert len(names) == len(set(names))

    def test_the_repeated_rows_are_separate_fields(self, converted):
        names = list(self._fields(converted))
        rows = [n for n in names if "Row.item" in n]
        assert len(rows) == 2

    def test_buttons_are_drawn_rather_than_made_live(self, converted):
        """A button whose script is gone must not pretend it still works."""
        names = list(self._fields(converted))
        assert not any("addRow" in n or "send" in n for n in names)

    @staticmethod
    def _fields(result):
        from pypdf import PdfReader

        return PdfReader(str(result.output)).get_fields() or {}


class TestConversionModes:
    def test_static_mode_produces_no_fields(self, xfa_dynamic, tmp_path):
        from pypdf import PdfReader

        result = convert_xfa(xfa_dynamic, tmp_path / "static.pdf", mode=ConversionMode.STATIC)
        assert result.succeeded
        assert not (PdfReader(str(result.output)).get_fields() or {})
        assert result.report.functional_fidelity is Fidelity.NONE

    def test_static_mode_still_keeps_the_appearance(self, xfa_dynamic, tmp_path):
        """Nothing interactive, but the form still has to be readable."""
        result = convert_xfa(xfa_dynamic, tmp_path / "static.pdf", mode=ConversionMode.STATIC)
        assert result.report.static_elements > 0
        assert result.report.visual_fidelity in (Fidelity.FULL, Fidelity.HIGH)

    def test_editable_mode_converts_everything_it_can(self, xfa_dynamic, tmp_path):
        result = convert_xfa(xfa_dynamic, tmp_path / "edit.pdf", mode=ConversionMode.EDITABLE)
        assert result.report.converted_fields > 0

    def test_converting_a_document_with_no_xfa_is_refused_clearly(self, plain, tmp_path):
        result = convert_xfa(plain, tmp_path / "no.pdf")
        assert not result.succeeded
        assert result.report.errors
        assert "XFA" in result.report.errors[0].message

    def test_the_output_never_overwrites_the_source(self, xfa_dynamic):
        from orion.xfa import convert_xfa_file

        result = convert_xfa_file(xfa_dynamic)
        assert result.output is not None
        assert result.output.resolve() != xfa_dynamic.resolve()
        assert xfa_dynamic.exists()


class TestTheReport:
    def test_the_counts_are_measured_rather_than_assumed(self, converted, xfa_dynamic):
        document = parse_xfa(inspect_form(xfa_dynamic).packets)
        form = resolve_layout(document)
        report = converted.report
        assert report.total_xfa_fields == len(form.fields)
        assert report.scripts_found == len(document.scripts)
        assert report.converted_fields <= report.total_xfa_fields

    def test_no_script_is_claimed_to_have_been_converted(self, converted):
        assert converted.report.scripts_found > 0
        assert converted.report.scripts_converted == 0
        assert converted.report.scripts_not_converted == converted.report.scripts_found

    def test_the_two_fidelities_are_reported_separately(self, converted):
        """A form can look perfect and behave worse, and must be able to say so."""
        report = converted.report
        assert report.visual_fidelity is Fidelity.FULL
        assert report.functional_fidelity is Fidelity.PARTIAL

    def test_losing_the_dynamic_behaviour_is_stated(self, converted):
        text = " ".join(str(e) for e in converted.report.entries).lower()
        assert "script" in text
        assert "grow" in text or "added" in text

    def test_the_summary_reads_as_sentences(self, converted):
        lines = converted.report.summary_lines()
        assert any(line.startswith("Fields found:") for line in lines)
        assert any("Appearance:" in line for line in lines)
        assert any("Behaviour:" in line for line in lines)


class TestValidation:
    def test_a_good_conversion_validates(self, converted):
        result = validate_converted_pdf(converted.output, expect_pages=converted.report.pages)
        assert result.ok, [str(i) for i in result.issues]
        assert result.has_acroform
        assert result.field_count > 0

    def test_a_missing_file_is_an_error_not_an_exception(self, tmp_path):
        result = validate_converted_pdf(tmp_path / "nope.pdf")
        assert not result.ok
        assert result.errors

    def test_a_file_that_is_not_a_pdf_is_an_error(self, tmp_path):
        broken = tmp_path / "broken.pdf"
        broken.write_bytes(b"not a pdf at all")
        result = validate_converted_pdf(broken)
        assert not result.ok

    def test_duplicate_field_names_are_caught(self, tmp_path):
        """The check exists because it is the failure that silently loses data."""
        from orion.xfa.report import Severity
        from orion.xfa.validator import ValidationResult, _check_names

        result = ValidationResult(field_names=("a", "a", "b"))
        _check_names(result)
        assert not result.ok
        assert any(i.severity is Severity.ERROR for i in result.issues)


class TestTheEngineChoice:
    def test_pdfium_is_asked_rather_than_assumed(self):
        """Recorded as a test because the answer could change under us.

        The published pdfium builds are compiled without XFA, so the symbols
        exist and do nothing. If a build with it ever ships, this fails and
        somebody gets to reconsider the whole approach.
        """
        from orion.xfa import pdfium_supports_xfa

        assert pdfium_supports_xfa() is False

    def test_the_native_engine_takes_an_xfa_document(self, xfa_dynamic):
        from orion.xfa import choose_engine
        from orion.xfa.engine import NativeXfaEngine

        assert isinstance(choose_engine(inspect_form(xfa_dynamic)), NativeXfaEngine)

    def test_a_static_form_asked_to_go_static_is_simply_copied(self, xfa_static):
        """Its pages already are the appearance; redrawing them would be worse."""
        from orion.xfa import choose_engine
        from orion.xfa.engine import FallbackRenderer

        engine = choose_engine(inspect_form(xfa_static), ConversionMode.STATIC)
        assert isinstance(engine, FallbackRenderer)

    def test_the_fallback_strips_the_form_so_readers_stop_choking(
        self, xfa_dynamic, tmp_path
    ):
        from pypdf import PdfReader

        from orion.xfa.engine import FallbackRenderer

        info = inspect_form(xfa_dynamic)
        out = tmp_path / "copied.pdf"
        result = FallbackRenderer().convert(
            xfa_dynamic, out, mode=ConversionMode.STATIC, info=info
        )
        assert result.succeeded
        root = PdfReader(str(out)).trailer["/Root"]
        assert "/AcroForm" not in root and "/NeedsRendering" not in root

    def test_a_converted_document_is_no_longer_xfa(self, converted):
        """Otherwise Orion would offer to convert its own output for ever."""
        assert detect_form_type(converted.output) is PdfFormType.ACROFORM


# == 16: the real document =================================================
@pytest.mark.skipif(
    not REFERENCE_PDF.exists(),
    reason=(
        f"Put the reference form at {REFERENCE_PDF.relative_to(REPO)} to run this. "
        "It is somebody's real document, so it is not in the repository."
    ),
)
class TestTheReferenceForm:
    """The document this feature was asked for.

    Written against what the requirement says the file contains rather than
    against exact counts, because the counts are that document's and asserting
    them would make the test a statement about one file rather than about the
    converter.
    """

    @pytest.fixture(scope="class")
    def info(self):
        return inspect_form(REFERENCE_PDF)

    @pytest.fixture(scope="class")
    def document(self, info):
        return parse_xfa(info.packets)

    def test_it_is_recognised_as_xfa(self, info):
        assert info.is_xfa

    def test_the_template_and_datasets_are_extracted(self, info):
        assert info.template, "no template packet"
        assert info.packets

    def test_the_template_parses_into_fields(self, document):
        assert not document.warnings, document.warnings
        assert document.fields, "no fields were read out of the template"

    def test_it_contains_the_kinds_of_control_described(self, document):
        kinds = {f.field_type for f in document.fields}
        assert XfaFieldType.TEXT in kinds
        assert kinds & {XfaFieldType.CHOICE, XfaFieldType.DATE}, (
            "the form is described as having choice lists and dates"
        )

    def test_it_has_a_subform_structure(self, document):
        assert len(list(document.template.root.walk())) > 1

    def test_the_conversion_produces_a_usable_form(self, tmp_path):
        from pypdf import PdfReader

        result = convert_xfa(REFERENCE_PDF, tmp_path / "reference-out.pdf")
        assert result.succeeded, str(result.report)
        reader = PdfReader(str(result.output))
        assert "/AcroForm" in reader.trailer["/Root"]
        assert reader.get_fields(), "no fields in the converted document"

    def test_the_converted_form_opens_in_orion(self, tmp_path):
        result = convert_xfa(REFERENCE_PDF, tmp_path / "reference-out.pdf")
        ok, detail = opens_in_orion(result.output)
        assert ok, detail

    def test_the_converted_fields_can_be_changed(self, tmp_path):
        """Editable in the plainest sense: write a value and read it back."""
        from pypdf import PdfReader, PdfWriter

        result = convert_xfa(REFERENCE_PDF, tmp_path / "reference-out.pdf")
        reader = PdfReader(str(result.output))
        fields = reader.get_fields() or {}
        text_fields = [n for n, s in fields.items() if str(s.get("/FT")) == "/Tx"]
        assert text_fields, "no text field to edit"

        writer = PdfWriter(clone_from=reader)
        writer.update_page_form_field_values(
            writer.pages[0], {text_fields[0]: "edited by Orion"}
        )
        edited = tmp_path / "edited.pdf"
        with open(edited, "wb") as handle:
            writer.write(handle)
        back = PdfReader(str(edited)).get_fields() or {}
        assert str(back[text_fields[0]].get("/V")) == "edited by Orion"

    def test_the_original_is_left_alone(self, tmp_path):
        before = REFERENCE_PDF.read_bytes()
        convert_xfa(REFERENCE_PDF, tmp_path / "reference-out.pdf")
        assert REFERENCE_PDF.read_bytes() == before
