# Orion — PDF Editor for Desktop
# Copyright (C) 2026 Marco Lombardo
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# Distributed WITHOUT ANY WARRANTY; see LICENSE for the full terms.
# A commercial licence, without the AGPL's obligations, is available for use
# in proprietary or closed-source products — see COMMERCIAL-LICENSE.md.

"""Tests for the file-level PDF operations (spec §27)."""

from __future__ import annotations

import pymupdf
import pytest

from orion.pdf import operations
from orion.pdf.errors import PdfWriteError


def _pdf(path, pages: int, tag: str):
    doc = pymupdf.open()
    for index in range(pages):
        page = doc.new_page(width=300, height=400)
        page.insert_text((40, 60), f"{tag}{index + 1}", fontsize=24)
    doc.save(path)
    doc.close()
    return path


def _text_of(path, index: int) -> str:
    with pymupdf.open(path) as doc:
        return doc.load_page(index).get_text().strip()


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

    with pymupdf.open(out) as doc:
        assert doc.page_count == 3
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
    with pymupdf.open(out) as doc:
        assert doc.page_count == 2
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
        with pymupdf.open(part) as doc:
            counts.append(doc.page_count)
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
