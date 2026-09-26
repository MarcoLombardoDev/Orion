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
from orion.xfa.checks import check_layout
from orion.xfa.converter import _split_for_caption
from orion.xfa.layout import LaidOutForm, PlacedPage, resolve_layout
from orion.xfa.model import XfaDraw, XfaField, XfaFieldType, XfaRect, XfaScriptKind
from orion.xfa.parser import parse_measurement
from orion.xfa.report import Fidelity, XfaConversionReport
from orion.xfa.safe_xml import XmlRejected, parse_xml
from orion.xfa.validator import opens_in_orion
from tests.xfa_fixtures import (
    build_acroform_pdf,
    build_awkward_form,
    build_plain_pdf,
    build_reference_form,
    build_xfa_pdf,
    dynamic_template,
    static_template,
    typeface_template,
)

REPO = pathlib.Path(__file__).resolve().parent.parent


def _page_text(path) -> str:
    """The text a reader finds on the first page of *path*.

    Read with pdfium rather than with the model, so the assertion is about the
    file somebody will open and not about what the converter believes it wrote.
    """
    import pypdfium2 as pdfium

    document = pdfium.PdfDocument(str(path))
    try:
        return document[0].get_textpage().get_text_range()
    finally:
        document.close()

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
        """Test 10. Shown the way the field's picture clause, DD/MM/YYYY, shows it."""
        spec = self._fields(converted)["form1.details.issued"]
        assert str(spec.get("/FT")) == "/Tx"
        assert str(spec.get("/V")) == "20/09/2026"

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

    def test_a_field_kept_as_static_is_not_a_loss_of_appearance(self):
        """Drawn but not fillable is a loss of behaviour, and only that.

        The real reference form has three protected signature fields. They are
        painted onto the page exactly where they belong, so the document looks
        right; what they lost is the ability to be typed into. Charging that to
        the appearance would report a faithfully reproduced form as visually
        partial — the single misleading number this class exists to prevent.
        """
        report = XfaConversionReport(
            output_file="out.pdf",
            total_xfa_fields=19,
            converted_fields=16,
            static_elements=16,
            unsupported_elements=3,
        )
        assert report.visual_fidelity is Fidelity.FULL
        assert report.functional_fidelity is not Fidelity.FULL

    def test_something_that_could_not_be_drawn_is_a_loss_of_appearance(self):
        report = XfaConversionReport(
            output_file="out.pdf",
            total_xfa_fields=4,
            converted_fields=4,
            static_elements=6,
            undrawn_elements=4,
        )
        assert report.visual_fidelity in (Fidelity.PARTIAL, Fidelity.LOW)

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


# == 15b: the shapes the real document turned out to be made of ============
class TestTheShapesARealFormIsMadeOf:
    """Regressions, every one of them found by converting the genuine file.

    A fixture built to be tidy never produced any of these; the document did.
    """

    @pytest.fixture(scope="class")
    def awkward(self, tmp_path_factory):
        return build_awkward_form(tmp_path_factory.mktemp("awkward") / "awkward.pdf")

    @pytest.fixture(scope="class")
    def laid_out(self, awkward):
        return resolve_layout(parse_xfa(inspect_form(awkward).packets))

    def test_a_field_with_only_a_minimum_height_still_has_one(self, laid_out):
        """``minH`` and no ``h`` is how most of a real flowed form is written."""
        assert all(f.rect.height > 0 for f in laid_out.fields)

    def test_flowed_fields_stack_instead_of_piling_up(self, laid_out):
        """The bug this is named after put six fields on the same line."""
        by_name = {f.name: f for f in laid_out.fields}
        first, second = by_name["first"], by_name["second"]
        assert second.rect.y >= first.rect.y + first.rect.height

    def test_table_cells_sit_side_by_side_at_the_table_s_columns(self, laid_out):
        by_name = {f.name: f for f in laid_out.fields}
        device, kind, from_ = by_name["device"], by_name["kind"], by_name["from"]
        assert device.rect.y == kind.rect.y == from_.rect.y
        assert (device.rect.width, kind.rect.width, from_.rect.width) == (100.0, 150.0, 90.0)
        assert kind.rect.x == device.rect.x + 100.0
        assert from_.rect.x == kind.rect.x + 150.0

    def test_the_headings_line_up_with_the_cells_beneath_them(self, laid_out):
        headings = {d.text: d for d in laid_out.draws if d.text in ("Device", "Kind", "From")}
        by_name = {f.name: f for f in laid_out.fields}
        assert headings["Device"].rect.x == by_name["device"].rect.x
        assert headings["Kind"].rect.x == by_name["kind"].rect.x
        assert headings["From"].rect.x == by_name["from"].rect.x

    def test_hiding_a_subform_hides_what_is_inside_it(self, laid_out):
        by_name = {f.name: f for f in laid_out.fields}
        assert by_name["conditional"].hidden
        assert by_name["alsoHidden"].hidden
        assert not by_name["first"].hidden

    def test_a_hidden_field_is_kept_when_fields_are_kept(self, awkward, tmp_path):
        """Nothing can reveal it any more, so hiding it would lose it for good."""
        out = tmp_path / "kept.pdf"
        report = convert_xfa(awkward, out, mode=ConversionMode.KEEP_FIELDS).report
        assert report.hidden_fields_shown == 2
        names = validate_converted_pdf(out).field_names
        assert any(name.endswith("conditional") for name in names)

    def test_a_static_copy_shows_what_the_form_showed(self, awkward, tmp_path):
        out = tmp_path / "static.pdf"
        report = convert_xfa(awkward, out, mode=ConversionMode.STATIC).report
        assert report.hidden_fields_shown == 0
        text = _page_text(out)
        assert "Only sometimes" not in text
        assert "First" in text

    def test_the_page_s_own_furniture_is_drawn(self, awkward, tmp_path):
        """The header and footer live in the page area, not in the form tree."""
        out = tmp_path / "furniture.pdf"
        convert_xfa(awkward, out)
        assert "Internal form - version 2" in _page_text(out)

    def test_a_field_in_the_page_header_is_filled_from_the_data(self, laid_out):
        title = next(f for f in laid_out.fields if f.name == "Title")
        assert title.value == "REAL TITLE FROM THE DATA"

    def test_an_image_is_never_fetched_and_never_silently_dropped(
        self, awkward, tmp_path
    ):
        """The href is a path on the form author's machine. It stays unopened.

        Counting it is the other half: a page missing its logo is a page that
        does not look like the form, and the appearance figure has to say so.
        """
        out = tmp_path / "image.pdf"
        report = convert_xfa(awkward, out).report
        assert report.undrawn_elements == 1
        assert any("image" in w.message.lower() for w in report.warnings)
        assert report.visual_fidelity is not Fidelity.FULL


class TestTheLayoutIsChecked:
    """The converter cannot see its own output, so it measures it.

    Every one of these was a real fault once, found by opening the result and
    looking at it. Measuring them means the next one is reported rather than
    noticed.
    """

    def _page(self, fields=(), draws=()):
        page = PlacedPage(width=595.276, height=841.89)
        page.fields.extend(fields)
        page.draws.extend(draws)
        form = LaidOutForm(pages=[page])
        return form

    def test_two_fields_in_the_same_place_are_reported(self):
        one = XfaField(name="one", som="f.one", rect=XfaRect(50, 50, 200, 20))
        two = XfaField(name="two", som="f.two", rect=XfaRect(55, 52, 200, 20))
        issues = check_layout(self._page(fields=[one, two]))
        assert [i.kind for i in issues] == ["overlap"]
        assert "two" in issues[0].message

    def test_fields_that_merely_touch_are_left_alone(self):
        """A table's cells share an edge by design."""
        one = XfaField(name="one", rect=XfaRect(50, 50, 100, 20))
        two = XfaField(name="two", rect=XfaRect(150, 50, 100, 20))
        assert check_layout(self._page(fields=[one, two])) == []

    def test_a_field_off_the_page_is_reported(self):
        stray = XfaField(name="stray", som="f.stray", rect=XfaRect(560, 50, 200, 20))
        issues = check_layout(self._page(fields=[stray]))
        assert [i.kind for i in issues] == ["off_page"]

    def test_text_that_cannot_fit_its_box_is_reported(self):
        long_text = "A caption far longer than the room the form gave it " * 3
        drawn = XfaDraw(kind="text", text=long_text, rect=XfaRect(50, 50, 80, 10))
        issues = check_layout(self._page(draws=[drawn]))
        assert [i.kind for i in issues] == ["overflow"]

    def test_a_sound_conversion_reports_no_layout_problems(self, tmp_path):
        source = build_awkward_form(tmp_path / "sound.pdf")
        report = convert_xfa(source, tmp_path / "sound-converted.pdf").report
        assert report.layout_problems == 0, [str(w) for w in report.warnings]


class TestButtonsThatStillWork:
    """Three of a form's buttons ask for something PDF can already do."""

    @pytest.fixture
    def converted_reference(self, tmp_path):
        source = build_reference_form(tmp_path / "buttons.pdf")
        out = tmp_path / "buttons-converted.pdf"
        result = convert_xfa(source, out, mode=ConversionMode.EDITABLE)
        return result, out

    def test_a_print_button_becomes_a_print_action(self, tmp_path):
        from pypdf import PdfReader

        template = dynamic_template().replace(
            'xfa.host.messageBox("submitting"); event.target.submitForm();',
            "xfa.host.print(1, \"0\", \"0\", 0, 0, 0, 0, 0);",
        )
        source = build_xfa_pdf(tmp_path / "print.pdf", template)
        out = tmp_path / "print-converted.pdf"
        report = convert_xfa(source, out, mode=ConversionMode.EDITABLE).report

        actions = []
        for page in PdfReader(str(out)).pages:
            for annotation in page.get("/Annots") or []:
                widget = annotation.get_object()
                if str(widget.get("/FT")) == "/Btn":
                    actions.append(dict(widget.get("/A") or {}))
        assert {"/S": "/Named", "/N": "/Print"} in [
            {k: str(v) for k, v in a.items()} for a in actions
        ]
        assert report.live_buttons >= 1

    def test_a_button_whose_job_was_a_script_is_not_pretended_to_work(
        self, converted_reference
    ):
        """Adding a row is the form's own programming and cannot come across."""
        result, _out = converted_reference
        text = " ".join(str(e) for e in result.report.entries)
        assert "no longer does anything" in text

    def test_no_javascript_is_written_into_the_converted_file(
        self, converted_reference
    ):
        """The actions are actions. Nothing here executes anything."""
        _result, out = converted_reference
        raw = out.read_bytes()
        assert b"/JavaScript" not in raw and b"/JS" not in raw


class TestLookingLikeTheFormItCameFrom:
    """The details that make a conversion read as the same document."""

    @pytest.fixture(scope="class")
    def awkward(self, tmp_path_factory):
        return build_awkward_form(tmp_path_factory.mktemp("look") / "look.pdf")

    @pytest.fixture(scope="class")
    def document(self, awkward):
        return parse_xfa(inspect_form(awkward).packets)

    def test_a_caption_keeps_its_own_font(self, document):
        """A label is rarely set in the field's font: six point bold here.

        Drawing it in the field's font made every label in the document the
        wrong size and the wrong weight, and wide enough to wrap where the
        form fits it on one line.
        """
        field = next(f for f in document.fields if f.name == "spacedField")
        assert field.caption_font is not None
        assert field.caption_font.size == 6.0
        assert field.caption_font.bold

    def test_a_border_the_form_hides_is_not_drawn(self, document, tmp_path):
        """Twenty-one fields of the reference form declare no border at all.

        A hairline invented around each of them is twenty-one rectangles the
        document does not have.
        """
        field = next(f for f in document.fields if f.name == "spacedField")
        assert all(not edge.draws for edge in field.edges)

    def test_one_edge_of_four_makes_a_rule_and_not_a_box(self, document):
        """A cell ruled underneath is how a form draws a line to write on."""
        field = next(f for f in document.fields if f.name == "ruledField")
        drawn = [index for index, edge in enumerate(field.edges) if edge.draws]
        assert drawn == [2], "only the bottom edge should be drawn"
        assert field.edges[2].width == pytest.approx(1.0)
        assert field.edges[2].color == pytest.approx((0.0, 0.0, 1.0))

    def test_an_edge_with_no_thickness_still_draws(self, document):
        """XFA's default is half a point, not nothing.

        Reading a missing ``thickness`` as zero made every plainly-bordered
        cell in a form borderless.
        """
        cell = next(f for f in document.fields if f.name == "device")
        assert all(edge.draws for edge in cell.edges)
        assert cell.edges[0].width == pytest.approx(0.5)

    def test_paragraph_spacing_is_inside_the_box_not_between_boxes(self, awkward):
        """``<para spaceAbove>`` is room above a field's own text.

        It was once read as a gap a flowed parent leaves between objects,
        which made every row of a real one-page request taller than it was
        drawn and sent its last row, and its signatures, onto a second page.
        """
        form = resolve_layout(parse_xfa(inspect_form(awkward).packets))
        placed = {f.name: f for f in form.fields}
        spaced = placed["spacedField"]
        above = placed["alsoHidden"]
        gap = spaced.rect.y - (above.rect.y + above.rect.height)
        assert gap == pytest.approx(0.0, abs=0.01)
        assert spaced.space_above == pytest.approx(10.0)

    def test_the_widget_carries_no_border_the_form_did_not_ask_for(
        self, awkward, tmp_path
    ):
        from pypdf import PdfReader

        out = tmp_path / "borders-converted.pdf"
        convert_xfa(awkward, out, mode=ConversionMode.EDITABLE)

        for page in PdfReader(str(out)).pages:
            for annotation in page.get("/Annots") or []:
                widget = annotation.get_object()
                if str(widget.get("/T", "")).endswith("spacedField"):
                    look = widget.get("/MK") or {}
                    assert not look.get("/BC"), "a border was invented"
                    return
        raise AssertionError("the field was not converted")


class TestTheFileTheConverterWrites:
    """Checks on the bytes, not on the model that produced them."""

    def test_an_unset_drop_down_is_empty_in_every_way(self, tmp_path):
        """reportlab will not write a choice field with no value in it.

        Working around that by preselecting the first option and stripping it
        afterwards is only honest if *everything* goes: the value, the default
        value and the appearance stream that still draws it. A form that looks
        filled in and reports itself empty is worse than one that crashed.
        """
        from pypdf import PdfReader

        source = build_xfa_pdf(tmp_path / "blank.pdf", dynamic_template(), data={})
        out = tmp_path / "blank-converted.pdf"
        convert_xfa(source, out)

        reader = PdfReader(str(out))
        choices = {
            name: spec
            for name, spec in (reader.get_fields() or {}).items()
            if str(spec.get("/FT")) == "/Ch"
        }
        assert choices, "the fixture has a choice field"
        for name, spec in choices.items():
            assert spec.get("/V") in (None, ""), name
            assert spec.get("/DV") in (None, ""), name
            assert len(spec.get("/Opt") or []) >= 3, name
        assert "Laptop" not in _page_text(out)

    def test_the_form_s_own_typeface_is_embedded_when_it_is_installed(
        self, tmp_path
    ):
        """A form set in Arial should come out in Arial, not in a stand-in.

        Run against whatever non-standard family this machine happens to have,
        because the point is the mechanism and not one font: if the family is
        installed, the converted file must carry it.

        What the file is checked against is the face Orion resolved, read back
        from reportlab, rather than the family's own name. Those are not the
        same string and only look like it on some machines: "DejaVu Sans" is
        written into a PDF as ``DejaVuSans``, which made an assertion about
        the family with its spaces removed pass on Linux and fail on a macOS
        runner, where the first font installed is "Academy Engraved LET" and
        the name in the file is ``AcademyEngravedLetPlain``.
        """
        from reportlab.pdfbase import pdfmetrics

        from orion.pdf.fonts import (
            BASE14_FAMILIES,
            FontRequest,
            available_families,
            resolve,
        )

        family = resolved = None
        for candidate in available_families():
            if candidate in BASE14_FAMILIES:
                continue
            found = resolve(FontRequest(candidate))
            # A family can be listed and still fail to embed; the next one is
            # as good a subject as the first.
            if found.embedded:
                family, resolved = candidate, found
                break
        if resolved is None:  # pragma: no cover - a machine with only the base-14
            pytest.skip("no system font on this machine can be embedded")

        source = build_xfa_pdf(tmp_path / "typeface.pdf", typeface_template(family))
        out = tmp_path / "typeface-converted.pdf"
        convert_xfa(source, out)

        raw = out.read_bytes()
        assert b"/FontFile2" in raw, "nothing was embedded"
        # reportlab hands the name back as its own bytes-like subclass on some
        # versions and as a plain string on others.
        name = pdfmetrics.getFont(resolved.name).face.name
        face = bytes(name) if isinstance(name, bytes | bytearray) else str(name).encode()
        assert face in raw, f"{family} was resolved but {face!r} is not in the file"
        assert "Typeface sample" in _page_text(out)

    def test_an_uninstalled_family_falls_back_without_complaint(self, tmp_path):
        """Metric-compatible stand-in, and a file that still converts."""
        source = build_xfa_pdf(
            tmp_path / "missing.pdf", typeface_template("Nonexistent Sans")
        )
        out = tmp_path / "missing-converted.pdf"
        assert convert_xfa(source, out).report.succeeded
        assert "Typeface sample" in _page_text(out)

    def test_labels_line_up_where_the_template_reserved_room_for_them(
        self, tmp_path
    ):
        """``<caption reserve>`` is the design's own label column width.

        Measuring the words instead started every box wherever its label
        happened to end, so a column of fields arrived ragged.
        """
        from pypdf import PdfReader

        template = dynamic_template().replace('reserve="60pt"', 'reserve="90pt"')
        source = build_xfa_pdf(tmp_path / "reserve.pdf", template)
        out = tmp_path / "reserve-converted.pdf"
        convert_xfa(source, out)

        reader = PdfReader(str(out))
        lefts = {}
        for page in reader.pages:
            for annotation in page.get("/Annots") or []:
                widget = annotation.get_object()
                name = str(widget.get("/T", "")).rsplit(".", 1)[-1]
                if name in ("applicant", "notes", "device"):
                    lefts[name] = round(float(widget["/Rect"][0]), 2)
        assert len(lefts) == 3
        assert len(set(lefts.values())) == 1, f"boxes do not line up: {lefts}"

    def test_a_label_above_the_field_does_not_land_on_top_of_it(self, tmp_path):
        """``placement="top"`` takes height, not width.

        Handled as a side taken out of the field's own box, the same way XFA
        does it, so the widget shrinks rather than the label overlapping it.
        """
        field = XfaField(
            name="a",
            caption="Name",
            caption_placement="top",
            caption_reserve=12.0,
            rect=XfaRect(x=0.0, y=0.0, width=200.0, height=40.0),
        )
        caption, box = _split_for_caption(field, 841.89)
        assert caption is not None
        caption_bottom = caption[1]
        box_top = box[1] + box[3]
        assert caption_bottom >= box_top, "the label sits over the box"
        assert box[2] == 200.0, "a label above should not narrow the box"

    def test_what_the_template_says_about_a_field_reaches_the_file(self, tmp_path):
        """Required, read-only and the form's own help text.

        All three were read out of the template from the start and none of
        them was written into the PDF: a required field arrived optional.
        """
        from pypdf import PdfReader

        source = build_reference_form(tmp_path / "flags.pdf")
        out = tmp_path / "flags-converted.pdf"
        convert_xfa(source, out)

        fields = PdfReader(str(out)).get_fields() or {}
        applicant = next(s for n, s in fields.items() if n.endswith("applicant"))
        assert int(applicant.get("/Ff", 0)) & 2, "the required flag was not written"

        notes = next(s for n, s in fields.items() if n.endswith("notes"))
        assert int(notes.get("/Ff", 0)) & 4096, "the multiline flag was not written"

        device = next(s for n, s in fields.items() if n.endswith("device"))
        # open="userControl": the user may type an answer that is not listed.
        assert int(device.get("/Ff", 0)) & 262144, "the drop-down is not editable"

    def test_the_text_of_the_converted_form_can_be_edited(self, tmp_path):
        """Orion's page-text editing has to work on what the converter draws.

        The static layer is the form: its headings, its captions, its rules.
        If those arrive as something Orion cannot pick up, the conversion has
        produced a picture of a form rather than a document.
        """
        from orion.pdf.coordinates import PageGeometry
        from orion.pdf.reader import open_pdf
        from orion.pdf.text_edit import read_text_lines

        source = build_awkward_form(tmp_path / "editable.pdf")
        out = tmp_path / "editable-converted.pdf"
        convert_xfa(source, out)

        opened = open_pdf(out)
        try:
            page = opened.doc[0]
            box = page.get_mediabox()
            geometry = PageGeometry(
                width=box[2] - box[0], height=box[3] - box[1], rotation=0
            )
            lines = read_text_lines(page.raw, page.get_textpage().raw, geometry)
        finally:
            opened.close()

        assert lines, "none of the converted text can be edited"
        assert any("First" in line.text for line in lines)
        assert all(line.font_size > 0 for line in lines)

    def test_the_default_resources_name_every_font_the_fields_use(self, tmp_path):
        """reportlab writes ``/Font`` twice in ``/DR``; readers keep one.

        The one they drop is the one the fields' ``/DA`` asks for, which
        leaves a viewer with no font to redraw a field's text with.
        """
        from pypdf import PdfReader

        source = build_xfa_pdf(tmp_path / "fonts.pdf", dynamic_template())
        out = tmp_path / "fonts-converted.pdf"
        convert_xfa(source, out)

        raw = out.read_bytes()
        block = raw[raw.index(b"/DR") : raw.index(b"/DR") + 400]
        assert block.count(b"/Font") == 1, "the duplicate key is back"

        resources = PdfReader(str(out)).trailer["/Root"]["/AcroForm"]["/DR"]
        assert "/Helv" in resources["/Font"]


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
