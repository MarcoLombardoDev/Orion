# Orion — PDF Editor for Desktop
# Copyright (C) 2026 Marco Lombardo
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# Distributed WITHOUT ANY WARRANTY; see LICENSE for the full terms.
# A commercial licence, without the AGPL's obligations, is available for use
# in proprietary or closed-source products — see COMMERCIAL-LICENSE.md.

"""Tests for the file-level PDF operations (spec §27)."""

from __future__ import annotations

import pytest

from orion.pdf import operations
from orion.pdf.errors import PdfWriteError
from tests.conftest import PdfProbe, make_pdf


def _pdf(path, pages: int, tag: str):
    return make_pdf(
        path, [(300.0, 400.0, f"{tag}{index + 1}") for index in range(pages)]
    )


def _text_of(path, index: int) -> str:
    with PdfProbe(path) as probe:
        return probe.text(index).strip()


def _page_count(path) -> int:
    with PdfProbe(path) as probe:
        return probe.page_count


# -- page ranges ---------------------------------------------------------
def test_parse_page_ranges_basic():
    assert operations.parse_page_ranges("1-3, 5", 10) == [[0, 1, 2], [4]]


def test_parse_page_ranges_reversed_range_is_honoured():
    assert operations.parse_page_ranges("3-1", 10) == [[2, 1, 0]]


@pytest.mark.parametrize("text", ["", "abc", "0", "1-99", "1--2"])
def test_parse_page_ranges_rejects_bad_input(text):
    with pytest.raises(ValueError):
        operations.parse_page_ranges(text, 10)


def test_format_page_ranges_round_trips():
    assert operations.format_page_ranges([0, 1, 2, 4, 7, 8]) == "1-3, 5, 8-9"
    assert operations.format_page_ranges([]) == ""


# -- merge ---------------------------------------------------------------
def test_merge_keeps_the_requested_order(tmp_path):
    a = _pdf(tmp_path / "a.pdf", 2, "A")
    b = _pdf(tmp_path / "b.pdf", 1, "B")
    out = operations.merge([b, a], tmp_path / "merged.pdf")

    assert _page_count(out) == 3
    assert _text_of(out, 0) == "B1"
    assert _text_of(out, 1) == "A1"
    assert _text_of(out, 2) == "A2"


def test_merge_can_select_pages(tmp_path):
    a = _pdf(tmp_path / "a.pdf", 4, "A")
    out = operations.merge(
        [operations.MergeItem(a, pages=[3, 0])], tmp_path / "picked.pdf"
    )
    assert _text_of(out, 0) == "A4"
    assert _text_of(out, 1) == "A1"


def test_merge_rejects_an_empty_job(tmp_path):
    with pytest.raises(PdfWriteError):
        operations.merge([], tmp_path / "nope.pdf")


# -- extract / split -----------------------------------------------------
def test_extract_pages(tmp_path):
    src = _pdf(tmp_path / "src.pdf", 5, "P")
    out = operations.extract_pages(src, tmp_path / "extract.pdf", [4, 2])
    assert _page_count(out) == 2
    assert _text_of(out, 0) == "P5"
    assert _text_of(out, 1) == "P3"


def test_extract_rejects_out_of_range(tmp_path):
    src = _pdf(tmp_path / "src.pdf", 2, "P")
    with pytest.raises(PdfWriteError):
        operations.extract_pages(src, tmp_path / "x.pdf", [9])


def test_split_every(tmp_path):
    src = _pdf(tmp_path / "src.pdf", 5, "P")
    parts = operations.split_every(src, tmp_path / "out", 2, stem="doc")
    assert [p.name for p in parts] == ["doc_1.pdf", "doc_2.pdf", "doc_3.pdf"]
    counts = []
    for part in parts:
        counts.append(_page_count(part))
    assert counts == [2, 2, 1]


def test_split_by_ranges(tmp_path):
    src = _pdf(tmp_path / "src.pdf", 6, "P")
    groups = operations.parse_page_ranges("1-2, 3-6", 6)
    parts = operations.split_by_ranges(src, tmp_path / "out", groups, stem="split")
    assert len(parts) == 2
    assert _text_of(parts[1], 0) == "P3"


def test_split_does_not_overwrite_existing_files(tmp_path):
    src = _pdf(tmp_path / "src.pdf", 2, "P")
    first = operations.split_every(src, tmp_path / "out", 1, stem="doc")
    second = operations.split_every(src, tmp_path / "out", 1, stem="doc")
    assert {p.name for p in second} == {"doc_1-2.pdf", "doc_2-2.pdf"}
    assert all(p.exists() for p in first + second)


def test_split_every_rejects_zero(tmp_path):
    src = _pdf(tmp_path / "src.pdf", 2, "P")
    with pytest.raises(PdfWriteError):
        operations.split_every(src, tmp_path / "out", 0)


def test_corrupt_file_raises_a_friendly_error(tmp_path):
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"this is not a pdf")
    with pytest.raises(Exception) as info:
        operations.page_count_of(broken)
    assert "damaged" in str(info.value) or "valid PDF" in str(info.value)


class TestExportingImages:
    """One image per page, showing what a save would put in the file."""

    def _document(self, tmp_path, pages: int = 3):
        from orion.document.document import Document, DocumentSource
        from orion.document.objects import ShapeKind, ShapeObject
        from orion.document.page import Page, PageSource
        from orion.utils.geometry import Rect, Size
        from tests.conftest import make_pdf

        path = make_pdf(
            tmp_path / "src.pdf",
            [(400.0, 600.0, f"Page {n + 1}") for n in range(pages)],
        )
        source = DocumentSource.for_path(path)
        model = [
            Page(base_size=Size(400.0, 600.0), source=PageSource(source.key, index))
            for index in range(pages)
        ]
        model[0].add_object(
            ShapeObject(
                rect=Rect.from_xywh(40.0, 40.0, 120.0, 60.0),
                shape=ShapeKind.RECTANGLE,
                stroke_color=(1.0, 0.0, 0.0),
                fill_color=(1.0, 0.0, 0.0),
            )
        )
        return Document(pages=model, sources=[source], path=path)

    def test_one_file_per_page(self, tmp_path):
        from orion.services.export_service import ExportService

        written = ExportService().export_images(
            self._document(tmp_path), [0, 2], tmp_path / "out"
        )
        assert len(written) == 2
        assert [p.name for p in written] == ["src-001.png", "src-003.png"]
        assert all(p.exists() and p.stat().st_size > 0 for p in written)

    def test_the_image_shows_what_the_save_would_write(self, tmp_path):
        """Rendered from the built document, not from the canvas.

        Which is the whole reason it is in the export service: an image taken
        off the screen would carry selection handles and page shadows, and
        would miss anything the canvas had not drawn yet.
        """
        from PIL import Image

        from orion.services.export_service import ExportService

        written = ExportService().export_images(
            self._document(tmp_path), [0], tmp_path / "out", dpi=72
        )
        pixels = Image.open(written[0]).convert("RGB").load()
        assert pixels[100, 70][0] > 150 and pixels[100, 70][1] < 100, (
            "the object the user added is not in the image"
        )

    def test_the_resolution_is_honoured(self, tmp_path):
        from PIL import Image

        from orion.services.export_service import ExportService

        document = self._document(tmp_path)
        low = ExportService().export_images(document, [0], tmp_path / "lo", dpi=72)
        high = ExportService().export_images(document, [0], tmp_path / "hi", dpi=144)
        assert Image.open(high[0]).width == pytest.approx(
            Image.open(low[0]).width * 2, abs=2
        )

    def test_jpeg_is_written_without_an_alpha_channel(self, tmp_path):
        from PIL import Image

        from orion.services.export_service import ExportService

        written = ExportService().export_images(
            self._document(tmp_path), [0], tmp_path / "out", image_format="JPEG"
        )
        assert written[0].suffix == ".jpg"
        assert Image.open(written[0]).mode == "RGB"

    def test_an_empty_selection_is_refused(self, tmp_path):
        from orion.pdf.errors import PdfWriteError
        from orion.services.export_service import ExportService

        with pytest.raises(PdfWriteError):
            ExportService().export_images(self._document(tmp_path), [], tmp_path / "out")

    def test_an_unknown_format_is_refused_before_anything_is_written(self, tmp_path):
        """Better than a folder of files in a format nobody asked for."""
        from orion.pdf.errors import PdfWriteError
        from orion.services.export_service import ExportService

        target = tmp_path / "out"
        with pytest.raises(PdfWriteError):
            ExportService().export_images(
                self._document(tmp_path), [0], target, image_format="TIFF"
            )
        assert not target.exists()
