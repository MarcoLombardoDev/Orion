# Orion — PDF Editor for Desktop
# Copyright (C) 2026 Marco Lombardo
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# Distributed WITHOUT ANY WARRANTY; see LICENSE for the full terms.
# A commercial licence, without the AGPL's obligations, is available for use
# in proprietary or closed-source products — see COMMERCIAL-LICENSE.md.

"""End-to-end tests of open -> edit -> save (spec §19, §20, §27, §29)."""

from __future__ import annotations

import io

import pymupdf
import pytest
from PIL import Image

from orion.document.annotations import AnnotationKind, AnnotationObject
from orion.document.objects import Align, ImageObject, ShapeKind, ShapeObject, TextObject
from orion.pdf.errors import PdfWriteError
from orion.pdf.writer import build_pdf_bytes
from orion.services.export_service import ExportService
from orion.services.file_service import FileService
from orion.utils.geometry import Point, Rect, Size
from tests.conftest import find_color_bbox, is_red


@pytest.fixture
def service() -> FileService:
    return FileService()


def _png(width: int = 40, height: int = 20, color=(0, 128, 255)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), color).save(buffer, format="PNG")
    return buffer.getvalue()


# -- opening -------------------------------------------------------------
def test_open_builds_a_matching_document(service, sample_pdf):
    session = service.open(sample_pdf)
    try:
        assert session.document.page_count == 3
        assert session.document.pages[0].base_size == Size(400.0, 600.0)
        assert not session.is_modified
        assert session.renderer.source_handle(
            session.document.pages[0].source.source_key
        ) is not None
    finally:
        session.close()


def test_open_reports_missing_and_broken_files(service, tmp_path):
    from orion.pdf.errors import PdfReadError

    with pytest.raises(PdfReadError):
        service.open(tmp_path / "nope.pdf")
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"%PDF-1.4 garbage")
    with pytest.raises(PdfReadError):
        service.open(broken)


def test_password_protected_file_is_reported_clearly(service, tmp_path):
    from orion.pdf.errors import PdfPasswordRequired

    path = tmp_path / "locked.pdf"
    doc = pymupdf.open()
    doc.new_page()
    doc.save(path, encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="secret")
    doc.close()

    with pytest.raises(PdfPasswordRequired):
        service.open(path)
    session = service.open(path, password="secret")
    session.close()


# -- saving --------------------------------------------------------------
def test_text_is_written_as_real_searchable_text(service, sample_pdf, tmp_path):
    session = service.open(sample_pdf)
    try:
        session.document[0].add_object(
            TextObject(
                rect=Rect.from_xywh(40, 200, 300, 60),
                text="ORION STAMP",
                font_size=20,
                align=Align.LEFT,
            )
        )
        out = tmp_path / "stamped.pdf"
        service.save_as(session, out)
    finally:
        session.close()

    with pymupdf.open(out) as doc:
        page = doc.load_page(0)
        assert "ORION STAMP" in page.get_text()
        hits = page.search_for("ORION STAMP")
        assert hits, "the stamped text must be findable by other readers"
        assert hits[0].y0 == pytest.approx(200, abs=25)


def test_shapes_annotations_and_images_all_survive(service, sample_pdf, tmp_path):
    session = service.open(sample_pdf)
    try:
        page = session.document[0]
        page.add_object(
            ShapeObject(
                rect=Rect.from_xywh(100, 300, 120, 60),
                shape=ShapeKind.RECTANGLE,
                stroke_color=(1.0, 0.0, 0.0),
                fill_color=(1.0, 0.0, 0.0),
            )
        )
        page.add_object(
            ImageObject(
                rect=Rect.from_xywh(40, 400, 80, 40),
                data=_png(),
                natural_size=Size(40, 20),
            )
        )
        page.add_object(
            AnnotationObject(
                rect=Rect.from_xywh(50, 95, 160, 25),
                annotation=AnnotationKind.HIGHLIGHT,
                quads=[Rect.from_xywh(50, 95, 160, 25)],
            )
        )
        page.add_object(
            AnnotationObject(
                rect=Rect.from_xywh(200, 500, 20, 20),
                annotation=AnnotationKind.STICKY_NOTE,
                contents="Check this",
            )
        )
        page.add_object(
            AnnotationObject(
                rect=Rect.from_xywh(250, 250, 60, 60),
                annotation=AnnotationKind.INK,
                strokes=[[Point(250, 250), Point(280, 300), Point(310, 250)]],
            )
        )
        out = tmp_path / "rich.pdf"
        service.save_as(session, out)
    finally:
        session.close()

    with pymupdf.open(out) as doc:
        page = doc.load_page(0)
        kinds = {annot.type[1] for annot in page.annots()}
        assert {"Highlight", "Text", "Ink"} <= kinds
        pixmap = page.get_pixmap(dpi=72)
        assert find_color_bbox(pixmap, is_red) is not None
        assert page.get_images(), "the image must be embedded in the output"


def test_page_operations_are_reflected_in_the_output(service, sample_pdf, tmp_path):
    session = service.open(sample_pdf)
    try:
        document = session.document
        document.move_page(0, 2)
        document[0].rotate(90)
        document.remove_page(1)
        out = tmp_path / "reordered.pdf"
        service.save_as(session, out)
    finally:
        session.close()

    with pymupdf.open(out) as doc:
        assert doc.page_count == 2
        assert doc.load_page(0).rotation == 90
        assert "PAGE 2" in doc.load_page(0).get_text()
        assert "PAGE 1" in doc.load_page(1).get_text()


def test_blank_pages_are_written(service, sample_pdf, tmp_path):
    from orion.document.page import Page

    session = service.open(sample_pdf)
    try:
        session.document.insert_page(1, Page(base_size=Size(300.0, 300.0)))
        out = tmp_path / "with-blank.pdf"
        service.save_as(session, out)
    finally:
        session.close()

    with pymupdf.open(out) as doc:
        assert doc.page_count == 4
        assert doc.load_page(1).rect.width == pytest.approx(300.0)
        assert doc.load_page(1).get_text().strip() == ""


# -- file safety ---------------------------------------------------------
def test_saving_over_the_open_file_does_not_duplicate_objects(service, sample_pdf, tmp_path):
    """Save twice in a row over the source: the stamp must appear exactly once."""
    session = service.open(sample_pdf)
    try:
        session.document[0].add_object(
            TextObject(rect=Rect.from_xywh(40, 300, 300, 40), text="ONCE", font_size=20)
        )
        service.save_as(session, sample_pdf)
        service.save_as(session, sample_pdf)
        assert session.shadowed_sources, "the original must have been shadowed"
    finally:
        session.close()

    with pymupdf.open(sample_pdf) as doc:
        assert doc.load_page(0).get_text().count("ONCE") == 1
        assert doc.page_count == 3


def test_saving_keeps_undo_history_valid(service, sample_pdf, tmp_path):
    from orion.commands import AddObjectCommand

    session = service.open(sample_pdf)
    try:
        shape = ShapeObject(rect=Rect.from_xywh(10, 10, 20, 20))
        session.history.push(AddObjectCommand(session.document, 0, shape))
        service.save_as(session, tmp_path / "saved.pdf")
        assert not session.is_modified
        session.history.undo()
        assert session.is_modified
        assert len(session.document[0]) == 0
    finally:
        session.close()


def test_a_failed_save_leaves_the_original_untouched(service, sample_pdf, tmp_path):
    original = sample_pdf.read_bytes()
    session = service.open(sample_pdf)
    try:
        session.document[0].add_object(
            ShapeObject(rect=Rect.from_xywh(0, 0, 10, 10), stroke_color=(0, 0, 0))
        )
        # A directory where the file should go: the atomic replace must fail
        # and the original must be left exactly as it was.
        target = tmp_path / "out.pdf"
        target.mkdir()
        with pytest.raises(PdfWriteError):
            service.save_as(session, target)
    finally:
        session.close()
    assert sample_pdf.read_bytes() == original


def test_no_temporary_files_are_left_behind(service, sample_pdf, tmp_path):
    session = service.open(sample_pdf)
    try:
        out = tmp_path / "clean.pdf"
        service.save_as(session, out)
    finally:
        session.close()
    leftovers = [p.name for p in tmp_path.iterdir() if "orion.tmp" in p.name]
    assert leftovers == []


def test_save_without_a_path_is_refused(service):
    session = service.create_blank()
    try:
        with pytest.raises(PdfWriteError):
            service.save(session)
    finally:
        session.close()


# -- export --------------------------------------------------------------
def test_extract_includes_unsaved_objects(service, sample_pdf, tmp_path):
    session = service.open(sample_pdf)
    export = ExportService()
    try:
        session.document[2].add_object(
            TextObject(rect=Rect.from_xywh(30, 300, 300, 40), text="UNSAVED", font_size=18)
        )
        out = export.extract(session.document, [2], tmp_path / "extracted.pdf")
    finally:
        session.close()

    with pymupdf.open(out) as doc:
        assert doc.page_count == 1
        assert "UNSAVED" in doc.load_page(0).get_text()


def test_split_and_merge_from_the_live_document(service, sample_pdf, tmp_path):
    session = service.open(sample_pdf)
    export = ExportService()
    try:
        parts = export.split_every(session.document, 1, tmp_path / "parts")
        assert len(parts) == 3
        merged = export.merge(
            [parts[2], parts[0]], tmp_path / "merged.pdf"
        )
    finally:
        session.close()

    with pymupdf.open(merged) as doc:
        assert doc.page_count == 2
        assert "PAGE 3" in doc.load_page(0).get_text()


def test_import_pages_references_the_other_file_until_save(service, sample_pdf, tmp_path):
    other = tmp_path / "other.pdf"
    doc = pymupdf.open()
    doc.new_page(width=200, height=200).insert_text((20, 40), "OTHER", fontsize=16)
    doc.save(other)
    doc.close()

    session = service.open(sample_pdf)
    try:
        source, pages = service.import_pages(session, other)
        assert len(pages) == 1
        session.document.add_source(source)
        session.document.insert_page(0, pages[0])
        out = tmp_path / "imported.pdf"
        service.save_as(session, out)
    finally:
        session.close()

    with pymupdf.open(out) as result:
        assert result.page_count == 4
        assert "OTHER" in result.load_page(0).get_text()


def test_build_pdf_bytes_is_a_valid_pdf(service, sample_pdf):
    session = service.open(sample_pdf)
    try:
        data = build_pdf_bytes(session.document)
    finally:
        session.close()
    assert data.startswith(b"%PDF")
    with pymupdf.open("pdf", data) as doc:
        assert doc.page_count == 3


# -- what you see is what you save ---------------------------------------
@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_rotating_a_page_saves_what_the_canvas_showed(service, tmp_path, rotation):
    """The renderer and the writer must agree about which way is up.

    The page carries a red corner marker; after rotating it in Orion and
    saving, the marker must sit in the same place in the written file as the
    on-screen renderer put it.
    """
    source = tmp_path / f"marker{rotation}.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=400, height=600)
    page.draw_rect(pymupdf.Rect(0, 0, 80, 40), color=(1, 0, 0), fill=(1, 0, 0))
    doc.save(source)
    doc.close()

    session = service.open(source)
    try:
        session.document[0].rotation = rotation
        rendered = session.renderer.render(
            session.renderer.request_for(session.document[0], 1.0)
        )
        out = tmp_path / f"rotated{rotation}.pdf"
        service.save_as(session, out)
    finally:
        session.close()

    def marker_centre_of_buffer(buffer, width, height, stride):
        xs, ys = [], []
        for y in range(0, height, 3):
            for x in range(0, width, 3):
                offset = y * stride + x * 3
                pixel = buffer[offset : offset + 3]
                if pixel[0] > 180 and pixel[1] < 90:
                    xs.append(x)
                    ys.append(y)
        assert xs, "the marker was not found"
        return (sum(xs) / len(xs), sum(ys) / len(ys))

    on_screen = marker_centre_of_buffer(
        rendered.samples, rendered.width, rendered.height, rendered.stride
    )
    with pymupdf.open(out) as result:
        pixmap = result.load_page(0).get_pixmap(dpi=72, alpha=False)
        assert (pixmap.width, pixmap.height) == (rendered.width, rendered.height)
        in_file = marker_centre_of_buffer(
            pixmap.samples, pixmap.width, pixmap.height, pixmap.stride
        )

    assert in_file[0] == pytest.approx(on_screen[0], abs=4)
    assert in_file[1] == pytest.approx(on_screen[1], abs=4)


def test_rotating_a_page_carries_its_objects_with_it(service, sample_pdf, tmp_path):
    """An annotation must stay glued to the content it marks."""
    session = service.open(sample_pdf)
    try:
        page = session.document[0]
        page.add_object(
            ShapeObject(
                rect=Rect.from_xywh(20, 30, 60, 20),
                shape=ShapeKind.RECTANGLE,
                stroke_color=(1.0, 0.0, 0.0),
                fill_color=(1.0, 0.0, 0.0),
            )
        )
        page.rotation = 90
        out = tmp_path / "rotated-with-object.pdf"
        service.save_as(session, out)
    finally:
        session.close()

    with pymupdf.open(out) as doc:
        result = doc.load_page(0)
        assert result.rotation == 90
        pixmap = result.get_pixmap(dpi=72)
        bbox = find_color_bbox(pixmap, is_red)
    assert bbox is not None
    # Base-space (20,30)-(80,50) on a 400x600 page, turned 90° clockwise for
    # display, lands near the top-right of the 600x400 result.
    assert bbox[0] > 500
    assert bbox[1] < 120


def test_merge_can_include_the_open_document(service, sample_pdf, tmp_path):
    """"Add Current Document" must merge unsaved edits, not the file on disk."""
    from orion.ui.dialogs.merge_dialog import CURRENT_DOCUMENT

    other = tmp_path / "other.pdf"
    doc = pymupdf.open()
    doc.new_page(width=200, height=200).insert_text((20, 40), "OTHER", fontsize=16)
    doc.save(other)
    doc.close()

    session = service.open(sample_pdf)
    export = ExportService()
    try:
        session.document[0].add_object(
            TextObject(rect=Rect.from_xywh(40, 250, 300, 40), text="NOT YET SAVED", font_size=18)
        )
        merged = export.merge(
            [other, CURRENT_DOCUMENT],
            tmp_path / "merged.pdf",
            document=session.document,
            current_marker=CURRENT_DOCUMENT,
        )
    finally:
        session.close()

    with pymupdf.open(merged) as result:
        assert result.page_count == 4
        assert "OTHER" in result.load_page(0).get_text()
        assert "NOT YET SAVED" in result.load_page(1).get_text()


def test_merge_without_a_document_reports_it(service, tmp_path):
    from orion.ui.dialogs.merge_dialog import CURRENT_DOCUMENT

    export = ExportService()
    with pytest.raises(PdfWriteError):
        export.merge(
            [CURRENT_DOCUMENT, CURRENT_DOCUMENT],
            tmp_path / "nope.pdf",
            document=None,
            current_marker=CURRENT_DOCUMENT,
        )
