# Orion — PDF Editor for Desktop
# Copyright (C) 2026 Marco Lombardo
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# Distributed WITHOUT ANY WARRANTY; see LICENSE for the full terms.
# A commercial licence, without the AGPL's obligations, is available for use
# in proprietary or closed-source products — see COMMERCIAL-LICENSE.md.

"""Converting a form somebody filled in and saved.

The template is only the design. A saved form also records how many rows its
table had, which sections a script revealed, and values its data packet does
not hold — and a conversion that reads only the template produces the empty
design. These tests build such a form (see
:func:`tests.xfa_fixtures.build_saved_form`) and check what comes out: every
row with its own values, a table laid out by its columns and paginated with
its heading repeated, page numbers, and values shown the way the form's
picture clauses show them.
"""

from __future__ import annotations

import pytest

from orion.xfa import convert_xfa, inspect_form, parse_xfa
from orion.xfa.converter import _toggle_box
from orion.xfa.layout import resolve_layout
from orion.xfa.model import XfaField, XfaFieldType, XfaInsets, XfaRect
from orion.xfa.pictures import display_value
from tests.xfa_fixtures import LONG_DESCRIPTION, build_saved_form, build_xfa_pdf

ROWS = 40


@pytest.fixture(scope="module")
def saved(tmp_path_factory):
    return build_saved_form(tmp_path_factory.mktemp("saved") / "claim.pdf", rows=ROWS)


@pytest.fixture(scope="module")
def document(saved):
    return parse_xfa(inspect_form(saved).packets)


@pytest.fixture(scope="module")
def form(document):
    return resolve_layout(document)


@pytest.fixture(scope="module")
def converted(saved, tmp_path_factory):
    out = tmp_path_factory.mktemp("out") / "claim-converted.pdf"
    result = convert_xfa(saved, out)
    assert result.succeeded
    return out


def _fields(document, name):
    return [f for f in document.fields if f.name == name]


def _fields_of(path):
    from pypdf import PdfReader

    return PdfReader(str(path)).get_fields() or {}


class TestTheSavedStateIsRead:
    def test_the_form_packet_is_recognised(self, document):
        assert document.has_form_state
        assert document.saved_pages == 2

    def test_every_saved_row_is_there(self, document):
        assert len(_fields(document, "What")) == ROWS

    def test_each_row_keeps_its_own_values(self, document):
        described = [f.value for f in _fields(document, "What")]
        assert described[0] == "Expense number 1"
        assert described[2] == LONG_DESCRIPTION
        assert described[-1] == f"Expense number {ROWS}"
        assert len(set(described)) == ROWS

    def test_bound_values_are_matched_in_order(self, document):
        """Each row takes the next unused value of its name, not the first one."""
        methods = [f.value for f in _fields(document, "Method")]
        assert methods[:4] == ["Card", "Transfer", "Card", "Transfer"]

    def test_the_rows_get_names_of_their_own(self, document):
        names = [f.qualified_name for f in _fields(document, "What")]
        assert len(set(names)) == ROWS
        assert names[1].endswith("Row[1].What")

    def test_a_field_a_script_revealed_is_visible_with_its_value(self, document):
        (period,) = _fields(document, "Period")
        assert not period.hidden
        assert period.value == "08/2023"

    def test_a_field_the_saved_form_hid_stays_hidden(self, document):
        (alternative,) = _fields(document, "ToAlt")
        assert alternative.hidden

    def test_the_repeatable_row_counts_once_with_its_instances(self, document):
        from orion.xfa import summarise_form

        summary = summarise_form(document)
        assert summary.repeatable == 1
        assert summary.instances == ROWS


class TestTheTableIsLaidOut:
    def _row(self, form, number):
        return [f for f in form.fields if f.parent_som.endswith(f"Row[{number}]")]

    def test_stale_coordinates_inside_a_flow_are_ignored(self, form):
        """The heading row says ``y="200pt"``; in a flowed table that means nothing."""
        heading = next(d for d in form.pages[0].draws if d.text == "DESCRIPTION")
        header_bottom = 60.0 + 60.0  # content top plus the header's height
        assert heading.rect.y == pytest.approx(header_bottom)

    def test_cells_take_their_width_from_the_columns(self, form):
        what = next(f for f in form.fields if f.name == "What")
        assert what.rect.width == pytest.approx(400.0)
        heading = next(d for d in form.pages[0].draws if d.text == "AMOUNT")
        assert heading.rect.width == pytest.approx(120.0)
        assert heading.rect.x == pytest.approx(18.0 + 80.0 + 400.0)

    def test_a_long_description_makes_its_whole_row_taller(self, form):
        row = self._row(form, 2)
        assert {f.name for f in row} == {"When", "What", "Amount", "Method"}
        heights = {round(f.rect.height, 2) for f in row}
        assert len(heights) == 1, "every cell is stretched to the row's height"
        assert heights.pop() > 18.0

    def test_the_table_continues_on_a_second_page(self, form):
        assert len(form.pages) == 2
        for number, page in enumerate(form.pages):
            bottom = 60.0 + 480.0
            for field in page.fields:
                if field.name in ("When", "What", "Amount", "Method"):
                    assert field.rect.y + field.rect.height <= bottom + 0.5, number

    def test_the_heading_row_is_repeated_on_the_continuation_page(self, form):
        headings = [d for d in form.pages[1].draws if d.text == "DESCRIPTION"]
        assert len(headings) == 1
        assert headings[0].rect.y == pytest.approx(60.0)
        first_row = min(
            (f for f in form.pages[1].fields if f.name == "What"), key=lambda f: f.rect.y
        )
        assert first_row.rect.y == pytest.approx(60.0 + 18.0)

    def test_the_page_furniture_is_on_every_page_with_its_number(self, form):
        numbers = [next(f for f in page.fields if f.name == "PageNo").value for page in form.pages]
        assert numbers == ["1", "2"]
        for page in form.pages:
            assert any(d.kind == "rectangle" for d in page.draws)


class TestTheConvertedFile:
    def test_every_row_becomes_a_field(self, converted):
        names = [n for n in _fields_of(converted) if n.endswith("What") or "What" in n]
        assert len(names) == ROWS

    def test_amounts_and_dates_are_shown_as_the_form_shows_them(self, converted):
        fields = _fields_of(converted)
        amounts = sorted(str(v.get("/V")) for n, v in fields.items() if "Amount" in n)
        assert "1,234.50" in amounts
        dates = [str(v.get("/V")) for n, v in fields.items() if "When" in n]
        assert "01/08/2023" in dates

    def test_an_amount_set_flush_right_is_written_flush_right(self, converted):
        from pypdf import PdfReader

        page = PdfReader(str(converted)).pages[0]
        amount = next(
            a.get_object()
            for a in page.get("/Annots")
            if "Amount" in str(a.get_object().get("/T", ""))
        )
        assert int(amount.get("/Q", 0)) == 2

    def test_a_saved_answer_the_list_does_not_offer_is_kept(self, converted):
        fields = _fields_of(converted)
        methods = [v for n, v in fields.items() if n.endswith("Method") or "Method" in n]
        transfer = [m for m in methods if str(m.get("/V")) == "Transfer"]
        assert len(transfer) == ROWS // 2
        assert any("Transfer" in str(option) for option in transfer[0].get("/Opt"))

    def test_a_hidden_alternative_is_not_printed_over_the_visible_field(self, converted):
        import pypdfium2 as pdfium

        document = pdfium.PdfDocument(str(converted))
        try:
            text = document[0].get_textpage().get_text_range()
        finally:
            document.close()
        assert "TO:" in text
        assert "ALTERNATIVE" not in text
        assert not any("ToAlt" in n for n in _fields_of(converted))

    def test_the_title_band_s_ring_is_drawn(self, converted):
        """An ``<arc>`` used to be dropped without a word."""
        import pypdfium2 as pdfium

        document = pdfium.PdfDocument(str(converted))
        try:
            image = document[0].render(scale=1.0).to_pil().convert("RGB")
        finally:
            document.close()
        # The ring is white on the red band: somewhere inside its box a pixel
        # is near white where the band alone would be red.
        pixels = [image.getpixel((x, y)) for x in range(24, 54) for y in range(18, 48)]
        assert any(min(pixel) > 200 for pixel in pixels)


class TestHiddenValuesTravel:
    def test_a_hidden_field_with_a_value_is_kept_as_an_invisible_widget(self, tmp_path):
        from pypdf import PdfReader

        from tests.xfa_fixtures import saved_form_packets, saved_form_template

        datasets, form = saved_form_packets(2)
        datasets = datasets.replace("<ToAlt/>", "<ToAlt>Kept value</ToAlt>")
        source = build_xfa_pdf(
            tmp_path / "hidden.pdf",
            saved_form_template(),
            datasets=datasets,
            form_state=form,
        )
        out = tmp_path / "hidden-converted.pdf"
        convert_xfa(source, out)

        reader = PdfReader(str(out))
        widgets = [
            a.get_object()
            for page in reader.pages
            for a in page.get("/Annots") or []
            if "ToAlt" in str(a.get_object().get("/T", ""))
        ]
        assert len(widgets) == 1
        assert str(widgets[0].get("/V")) == "Kept value"
        assert int(widgets[0].get("/F", 0)) & 2, "hidden from the reader"

    def test_orion_does_not_turn_a_hidden_widget_into_an_object(self, tmp_path):
        from pypdf import PdfReader
        from reportlab.pdfgen import canvas

        from orion.pdf.coordinates import PageGeometry
        from orion.pdf.form_import import import_form_fields

        path = tmp_path / "hidden-widget.pdf"
        pdf = canvas.Canvas(str(path))
        pdf.acroForm.textfield(name="shown", x=72, y=700, width=120, height=18)
        pdf.acroForm.textfield(
            name="kept", x=72, y=650, width=120, height=18, annotationFlags="hidden"
        )
        pdf.showPage()
        pdf.save()

        page = PdfReader(str(path)).pages[0]
        geometry = PageGeometry(width=595.276, height=841.89, rotation=0)
        imported = import_form_fields(page, geometry)
        assert [o.name for o in imported.objects] == ["shown"]


class TestShowingValues:
    @pytest.mark.parametrize(
        ("kind", "picture", "value", "shown"),
        [
            (XfaFieldType.DATE, "date{DD/MM/YYYY}", "2023-08-02", "02/08/2023"),
            (XfaFieldType.DATE, "date{D MMM YYYY}", "2023-08-02", "2 Aug 2023"),
            (XfaFieldType.DATE, "date{DD/MM/YYYY}", "not a date", "not a date"),
            (XfaFieldType.NUMERIC, "num{zzzzzzz,zzz,zz9.99}", "4416.00000000", "4,416.00"),
            (XfaFieldType.NUMERIC, "num{zzz9}", "12.6", "13"),
            (XfaFieldType.NUMERIC, "", "4416.00000000", "4416"),
            (XfaFieldType.NUMERIC, "", "0.50000", "0.5"),
            (XfaFieldType.TEXT, "date{DD/MM/YYYY}", "2023-08-02", "2023-08-02"),
        ],
    )
    def test_the_picture_clause_decides(self, kind, picture, value, shown):
        field = XfaField(name="f", field_type=kind, value=value, picture=picture)
        assert display_value(field) == shown


class TestACheckboxIsTheSizeTheFormDrawsIt:
    def test_the_square_is_the_form_s_size_not_the_cell_s(self):
        field = XfaField(
            name="tick",
            field_type=XfaFieldType.CHECKBOX,
            rect=XfaRect(0, 0, 40, 30),
            margins=XfaInsets(left=2.0),
            valign="middle",
        )
        left, bottom, size = _toggle_box(field, (100.0, 200.0, 40.0, 30.0))
        assert size == pytest.approx(10.0)
        assert left == pytest.approx(102.0)
        assert bottom == pytest.approx(210.0)

    def test_a_declared_size_is_used(self):
        field = XfaField(name="tick", field_type=XfaFieldType.CHECKBOX, check_size=7.0)
        assert _toggle_box(field, (0.0, 0.0, 40.0, 30.0))[2] == pytest.approx(7.0)


def test_orion_reads_where_a_value_is_aligned(converted):
    """The editor paints a field's value itself, so it needs ``/Q`` as well."""
    from pypdf import PdfReader

    from orion.pdf.coordinates import PageGeometry
    from orion.pdf.form_import import import_form_fields

    page = PdfReader(str(converted)).pages[0]
    box = page.mediabox
    geometry = PageGeometry(width=float(box.width), height=float(box.height), rotation=0)
    objects = import_form_fields(page, geometry).objects
    amount = next(o for o in objects if o.name.endswith("Amount"))
    assert amount.alignment == 2
    described = next(o for o in objects if o.name.endswith("Row[2].What"))
    assert described.multiline
