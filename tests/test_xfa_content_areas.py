# Orion — PDF Editor for Desktop
# Copyright (C) 2026 Marco Lombardo
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# Distributed WITHOUT ANY WARRANTY; see LICENSE for the full terms.
# A commercial licence, without the AGPL's obligations, is available for use
# in proprietary or closed-source products — see COMMERCIAL-LICENSE.md.

"""A page with more than one content area, and the breaks that name them.

The regression this guards against: a one-page payment request came out on
five pages, because every section's ``<break before="contentArea">`` was read
as "start a new page" — where XFA means "be in this content area", which a
section already in it satisfies — and its signature block, sent to the strip
at the foot of the page, was sent to a page of its own instead.
"""

from __future__ import annotations

import pytest

from orion.xfa import convert_xfa, inspect_form, parse_xfa
from orion.xfa.layout import resolve_layout
from tests.xfa_fixtures import build_xfa_pdf, content_areas_template


def _form(tmp_path, **options):
    source = build_xfa_pdf(tmp_path / "request.pdf", content_areas_template(**options))
    return source, resolve_layout(parse_xfa(inspect_form(source).packets))


def test_both_content_areas_are_read(tmp_path):
    source, _ = _form(tmp_path)
    document = parse_xfa(inspect_form(source).packets)
    names = [area.name for area in document.template.pages[0].content_areas]
    assert names == ["A1", "A2"]


def test_a_break_to_the_area_already_in_use_does_not_start_a_page(tmp_path):
    _, form = _form(tmp_path)
    assert len(form.pages) == 1


def test_the_signature_block_goes_to_the_strip_it_names(tmp_path):
    _, form = _form(tmp_path)
    signed_on = next(f for f in form.fields if f.name == "SignedOn")
    assert signed_on.page == 0
    assert signed_on.rect.y == pytest.approx(690.0)


def test_area_groups_are_laid_out_with_their_fields(tmp_path):
    _, form = _form(tmp_path)
    roles = sorted(d.text for d in form.draws if d.text in ("Associate", "Manager", "Head of unit"))
    assert roles == ["Associate", "Head of unit", "Manager"]
    signs = sorted(f.rect.x for f in form.fields if f.name == "Sign")
    assert signs == pytest.approx([48.0, 218.0, 388.0])
    assert all(f.rect.y == pytest.approx(690.0 + 30.0 + 24.0) for f in form.fields if f.name == "Sign")


def test_start_new_does_start_a_fresh_area(tmp_path):
    """``startNew="1"`` on "any content area" moves on even from the one in use."""
    _, form = _form(tmp_path, start_new=True)
    line1 = next(f for f in form.fields if f.name == "Line1")
    line0 = next(f for f in form.fields if f.name == "Line0")
    assert (line1.page, line1.rect.y) != (line0.page, line0.rect.y + 18.0)
    assert line1.rect.y == pytest.approx(690.0), "the next area on the page is the strip"


def test_the_body_overflows_into_the_next_page_not_over_the_signatures(tmp_path):
    _, form = _form(tmp_path, sections=40)
    body_bottom = 72.0 + 600.0
    for field in form.fields:
        if field.name.startswith("Line") and field.page == 0 and field.rect.y < 690.0:
            assert field.rect.y + field.rect.height <= body_bottom + 1.5
    assert len(form.pages) >= 2


def test_every_field_including_the_grouped_ones_is_converted(tmp_path):
    from pypdf import PdfReader

    source, _ = _form(tmp_path)
    out = tmp_path / "request-converted.pdf"
    assert convert_xfa(source, out).succeeded
    names = list(PdfReader(str(out)).get_fields() or {})
    assert sum(1 for n in names if n.endswith("Sign") or "Sign_" in n or "Sign[" in n) == 3
    assert len(PdfReader(str(out)).pages) == 1
