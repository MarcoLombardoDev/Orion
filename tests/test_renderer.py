# Orion — PDF Editor for Desktop
# Copyright (C) 2026 Marco Lombardo
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# Distributed WITHOUT ANY WARRANTY; see LICENSE for the full terms.
# A commercial licence, without the AGPL's obligations, is available for use
# in proprietary or closed-source products — see COMMERCIAL-LICENSE.md.

"""Rasterisation, caching and the rotation path (spec §6, §24)."""

from __future__ import annotations

import pymupdf
import pytest

from orion.document.document import Document, DocumentSource
from orion.document.page import Page, PageSource
from orion.pdf.reader import open_pdf
from orion.pdf.renderer import (
    MAX_SCALE,
    PageRenderer,
    quantize_scale,
)
from orion.utils.geometry import Rect, Size


@pytest.fixture
def marked_pdf(tmp_path):
    """A 400x600 page with a red block in its top-left corner."""
    path = tmp_path / "marked.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=400, height=600)
    page.draw_rect(pymupdf.Rect(0, 0, 80, 40), color=(1, 0, 0), fill=(1, 0, 0))
    page.insert_text((120, 200), "FINDME", fontsize=20)
    doc.save(path)
    doc.close()
    return path


@pytest.fixture
def renderer_and_document(marked_pdf):
    renderer = PageRenderer(cache_bytes=8 * 1024 * 1024)
    opened = open_pdf(marked_pdf)
    source = DocumentSource.for_path(marked_pdf)
    renderer.register_source(source, opened)
    page = Page(base_size=Size(400.0, 600.0), source=PageSource(source.key, 0))
    document = Document(pages=[page], sources=[source], path=marked_pdf)
    yield renderer, document
    renderer.close_all()


def _pixel(rendered, x: int, y: int) -> tuple[int, int, int]:
    offset = y * rendered.stride + x * 3
    return tuple(rendered.samples[offset : offset + 3])


def _is_red(pixel) -> bool:
    return pixel[0] > 180 and pixel[1] < 90 and pixel[2] < 90


# -- basic rendering -----------------------------------------------------
def test_render_produces_the_expected_size(renderer_and_document):
    renderer, document = renderer_and_document
    request = renderer.request_for(document[0], 1.0)
    rendered = renderer.render(request)
    assert (rendered.width, rendered.height) == (400, 600)
    assert _is_red(_pixel(rendered, 10, 10))
    assert not _is_red(_pixel(rendered, 300, 500))


def test_scale_changes_the_raster_size(renderer_and_document):
    renderer, document = renderer_and_document
    rendered = renderer.render(renderer.request_for(document[0], 2.0))
    assert (rendered.width, rendered.height) == (800, 1200)


@pytest.mark.parametrize(
    "rotation,expected_size,marker",
    [
        (0, (400, 600), (10, 10)),
        (90, (600, 400), (589, 10)),
        (180, (400, 600), (389, 589)),
        (270, (600, 400), (10, 389)),
    ],
)
def test_orion_page_rotation_rotates_the_raster(
    renderer_and_document, rotation, expected_size, marker
):
    """Orion's own page rotation must actually turn the rendered page."""
    renderer, document = renderer_and_document
    page = document[0]
    page.rotation = rotation

    rendered = renderer.render(renderer.request_for(page, 1.0))
    assert (rendered.width, rendered.height) == expected_size
    assert _is_red(_pixel(rendered, *marker)), (
        f"the corner marker is not where a {rotation}° turn would put it"
    )


def test_blank_pages_render_white(renderer_and_document):
    renderer, _document = renderer_and_document
    blank = Page(base_size=Size(200.0, 100.0))
    rendered = renderer.render(renderer.request_for(blank, 1.0))
    assert (rendered.width, rendered.height) == (200, 100)
    assert _pixel(rendered, 100, 50) == (255, 255, 255)


def test_a_missing_source_renders_blank_instead_of_raising(renderer_and_document):
    renderer, document = renderer_and_document
    renderer.close_source(document[0].source.source_key)
    rendered = renderer.render(renderer.request_for(document[0], 1.0))
    assert (rendered.width, rendered.height) == (400, 600)
    assert _pixel(rendered, 10, 10) == (255, 255, 255)


# -- caching -------------------------------------------------------------
def test_identical_requests_hit_the_cache(renderer_and_document):
    renderer, document = renderer_and_document
    request = renderer.request_for(document[0], 1.0)
    first = renderer.render(request)
    assert renderer.cached(request) is first
    assert renderer.render(request) is first


def test_the_cache_is_bounded_by_bytes_not_by_page_count(renderer_and_document):
    """A count-based cache would happily hold gigabytes at high zoom."""
    renderer, document = renderer_and_document
    renderer.set_cache_limit(16 * 1024 * 1024)
    for scale in (0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0):
        renderer.render(renderer.request_for(document[0], scale))
    assert renderer.cache_bytes <= renderer._cache_limit


def test_rotation_and_scale_are_part_of_the_cache_key(renderer_and_document):
    renderer, document = renderer_and_document
    page = document[0]
    upright = renderer.request_for(page, 1.0)
    page.rotation = 90
    turned = renderer.request_for(page, 1.0)
    assert upright.cache_key != turned.cache_key


def test_closing_a_source_drops_its_cached_pages(renderer_and_document):
    renderer, document = renderer_and_document
    request = renderer.request_for(document[0], 1.0)
    renderer.render(request)
    assert renderer.cache_bytes > 0
    renderer.close_source(document[0].source.source_key)
    assert renderer.cached(request) is None
    assert renderer.cache_bytes == 0


@pytest.mark.parametrize(
    "raw,expected",
    [(1.0, 1.0), (1.01, 1.0), (1.04, 1.05), (0.0, 0.02), (1000.0, MAX_SCALE)],
)
def test_scale_quantisation(raw, expected):
    assert quantize_scale(raw) == pytest.approx(expected, abs=1e-6)


# -- text ----------------------------------------------------------------
def test_search_returns_base_space_rectangles(renderer_and_document):
    renderer, document = renderer_and_document
    hits = renderer.search_page(document[0], "FINDME")
    assert len(hits) == 1
    assert hits[0].x0 == pytest.approx(120, abs=6)
    assert hits[0].y1 == pytest.approx(200, abs=8)


def test_search_misses_return_nothing(renderer_and_document):
    renderer, document = renderer_and_document
    assert renderer.search_page(document[0], "NOTHERE") == []
    assert renderer.search_page(document[0], "") == []


def test_text_lines_in_snaps_to_the_page_text(renderer_and_document):
    """This is what makes the highlight tool follow words rather than the drag."""
    renderer, document = renderer_and_document
    lines = renderer.text_lines_in(document[0], Rect.from_xywh(100, 180, 200, 40))
    assert len(lines) == 1
    assert lines[0].width > 40
    assert renderer.text_lines_in(document[0], Rect.from_xywh(0, 500, 50, 20)) == []
