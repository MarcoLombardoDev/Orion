# Orion — PDF Editor for Desktop
# Copyright (C) 2026 Marco Lombardo
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# Distributed WITHOUT ANY WARRANTY; see LICENSE for the full terms.
# A commercial licence, without the AGPL's obligations, is available for use
# in proprietary or closed-source products — see COMMERCIAL-LICENSE.md.

"""Turning the document model back into a real PDF file (spec §19, §20, §29).

The writer is the *only* place that mutates PDF content.  It never touches the
user's original file in place: output goes to a temporary file in the same
directory, is validated by reopening it, and only then replaces the target with
an atomic ``os.replace``.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path

import pymupdf

from orion.document.annotations import AnnotationKind, AnnotationObject
from orion.document.document import Document
from orion.document.objects import (
    Align,
    ImageObject,
    PageObject,
    ShapeKind,
    ShapeObject,
    TextObject,
)
from orion.document.page import Page
from orion.pdf.coordinates import (
    content_angle,
    pdf_morph_angle,
    pdf_rotate_steps,
    polyline_to_pdf,
    quad_points,
    to_pdf_point,
    to_pdf_rect,
)
from orion.pdf.errors import PdfWriteError
from orion.pdf.text_layout import layout_text
from orion.utils.fileio import atomic_write_bytes
from orion.utils.geometry import Point, rotated_bounds
from orion.utils.image_utils import rotate_image

log = logging.getLogger(__name__)

__all__ = ["save_document", "build_pdf_bytes", "SaveResult"]

_ALIGN_TO_PYMUPDF = {
    Align.LEFT: 0,
    Align.CENTER: 1,
    Align.RIGHT: 2,
    Align.JUSTIFY: 3,
}


@dataclass(slots=True)
class SaveResult:
    path: Path
    page_count: int
    bytes_written: int


# --------------------------------------------------------------------------
# Source handling
# --------------------------------------------------------------------------
class _SourcePool:
    """Opens each referenced source PDF once, read-only, for the write pass."""

    def __init__(self, document: Document) -> None:
        self._document = document
        self._open: dict[str, pymupdf.Document] = {}

    def get(self, key: str) -> pymupdf.Document | None:
        if key in self._open:
            return self._open[key]
        source = self._document.sources.get(key)
        if source is None:
            return None
        try:
            if source.data is not None:
                doc = pymupdf.open("pdf", source.data)
            elif source.path is not None:
                doc = pymupdf.open(source.path)
            else:
                return None
        except Exception as exc:
            raise PdfWriteError(
                f"The source file “{source.display_name}” could not be read while saving.",
                detail=str(exc),
            ) from exc
        self._open[key] = doc
        return doc

    def close(self) -> None:
        for doc in self._open.values():
            with suppress(Exception):  # pragma: no cover - best effort
                doc.close()
        self._open.clear()


@contextmanager
def _source_pool(document: Document) -> Iterator[_SourcePool]:
    pool = _SourcePool(document)
    try:
        yield pool
    finally:
        pool.close()


# --------------------------------------------------------------------------
# Assembly
# --------------------------------------------------------------------------
def _assemble(document: Document, pool: _SourcePool) -> pymupdf.Document:
    """Copy source page runs and create blank pages, in document order."""
    out = pymupdf.open()
    run_key: str | None = None
    run_start = run_end = -1

    def flush() -> None:
        nonlocal run_key, run_start, run_end
        if run_key is None:
            return
        src = pool.get(run_key)
        if src is None:
            # The source vanished: emit blanks so page count stays correct.
            for _ in range(run_end - run_start + 1):
                out.new_page(width=595, height=842)
        else:
            out.insert_pdf(src, from_page=run_start, to_page=run_end, annots=True, links=True)
        run_key, run_start, run_end = None, -1, -1

    for page in document.pages:
        if page.source is None:
            flush()
            size = page.base_size
            out.new_page(width=size.width, height=size.height)
            continue
        key, index = page.source.source_key, page.source.index
        if key == run_key and index == run_end + 1:
            run_end = index
        else:
            flush()
            run_key, run_start, run_end = key, index, index
    flush()

    if out.page_count != document.page_count:  # pragma: no cover - defensive
        out.close()
        raise PdfWriteError(
            "Internal error while assembling the document (page count mismatch)."
        )
    return out


# --------------------------------------------------------------------------
# Object stamping
# --------------------------------------------------------------------------
def _stamp_page(pdf_page: pymupdf.Page, page: Page) -> None:
    """Write every Orion object of *page* onto the corresponding PDF page.

    Called *before* the new rotation is applied, so ``derotation_matrix`` still
    reflects the source page's own ``/Rotate`` — which is exactly the transform
    that maps Orion base space onto PDF content space.
    """
    base_rotation = int(pdf_page.rotation)
    for obj in page.objects:
        try:
            if isinstance(obj, AnnotationObject):
                _add_annotation(pdf_page, obj, base_rotation)
            elif isinstance(obj, TextObject):
                _draw_text(pdf_page, obj)
            elif isinstance(obj, ImageObject):
                _draw_image(pdf_page, obj, base_rotation)
            elif isinstance(obj, ShapeObject):
                _draw_shape(pdf_page, obj)
            else:  # pragma: no cover - future object kinds
                log.warning("Skipping unknown object type %s", type(obj).__name__)
        except PdfWriteError:
            raise
        except Exception as exc:
            # One bad object must not lose the whole save.
            log.exception("Could not write object %s (%s)", obj.id, type(obj).__name__)
            raise PdfWriteError(
                f"An object of type “{obj.display_name}” could not be written.",
                detail=str(exc),
            ) from exc


def _morph(pdf_page: pymupdf.Page, obj: PageObject):
    """``morph=`` argument that applies the object's rotation, or ``None``."""
    angle = pdf_morph_angle(obj.rotation)
    if not angle % 360:
        return None
    pivot = to_pdf_point(pdf_page, obj.rect.center)
    return (pivot, pymupdf.Matrix(angle))


def _draw_text(pdf_page: pymupdf.Page, obj: TextObject) -> None:
    if not obj.text.strip():
        return
    fontname = obj.base14_name
    layout = layout_text(
        obj.text,
        obj.rect,
        fontname=fontname,
        font_size=obj.font_size,
        align=obj.align,
        line_spacing=obj.line_spacing,
    )
    morph = _morph(pdf_page, obj)
    color = tuple(obj.color)

    for line in layout.lines:
        for segment in line.segments:
            if not segment.text:
                continue
            point = to_pdf_point(pdf_page, Point(segment.x, line.baseline))
            pdf_page.insert_text(
                point,
                segment.text,
                fontname=fontname,
                fontsize=obj.font_size,
                color=color,
                fill_opacity=obj.opacity,
                stroke_opacity=obj.opacity,
                rotate=0,
                morph=morph,
            )

    if obj.underline:
        for x0, y, x1, thickness in layout.underline_spans():
            p1 = to_pdf_point(pdf_page, Point(x0, y))
            p2 = to_pdf_point(pdf_page, Point(x1, y))
            pdf_page.draw_line(
                p1, p2, color=color, width=thickness, morph=morph, stroke_opacity=obj.opacity
            )


def _draw_image(pdf_page: pymupdf.Page, obj: ImageObject, base_rotation: int) -> None:
    """Place a raster image.

    ``insert_image`` has no ``morph`` parameter and can only rotate in 90-degree
    steps, so this is the one object type where the page rotation has to be
    folded into the angle explicitly (:func:`content_angle`).
    """
    if not obj.data:
        return

    # Footprint of the rotated object, mapped into PDF content space.
    bounds = rotated_bounds(obj.rect, obj.rotation)
    target = to_pdf_rect(pdf_page, bounds)
    angle_in_content = content_angle(obj.rotation, base_rotation) % 360

    if angle_in_content % 90 == 0:
        data = obj.data
        if obj.opacity < 1.0:
            # insert_image has no opacity parameter, so bake it into the alpha
            # channel rather than silently dropping the property.
            data, _ = rotate_image(obj.data, 0.0, opacity=obj.opacity)
        pdf_page.insert_image(
            target,
            stream=data,
            keep_proportion=False,
            rotate=pdf_rotate_steps(obj.rotation, base_rotation),
            overlay=True,
        )
        return

    # Arbitrary angle: PyMuPDF cannot rotate an image freely, so rasterise the
    # rotation with Pillow and place the expanded result in its bounding box.
    data, _size = rotate_image(obj.data, angle_in_content, opacity=obj.opacity)
    pdf_page.insert_image(target, stream=data, keep_proportion=False, overlay=True)


def _draw_shape(pdf_page: pymupdf.Page, obj: ShapeObject) -> None:
    morph = _morph(pdf_page, obj)
    stroke = tuple(obj.stroke_color) if obj.stroke_color else None
    fill = tuple(obj.fill_color) if obj.fill_color else None
    width = max(0.0, obj.stroke_width)
    common = {
        "color": stroke,
        "fill": fill,
        "width": width,
        "morph": morph,
        "stroke_opacity": obj.opacity,
        "fill_opacity": obj.opacity,
        "overlay": True,
    }
    if stroke is None and fill is None:
        return

    if obj.shape is ShapeKind.RECTANGLE:
        pdf_page.draw_rect(to_pdf_rect(pdf_page, obj.rect), **common)
    elif obj.shape is ShapeKind.ELLIPSE:
        pdf_page.draw_oval(to_pdf_rect(pdf_page, obj.rect), **common)
    elif obj.shape in (ShapeKind.LINE, ShapeKind.ARROW):
        start, end = obj.start_point(), obj.end_point()
        p1 = to_pdf_point(pdf_page, start)
        p2 = to_pdf_point(pdf_page, end)
        line_args = {
            "color": stroke or (0.0, 0.0, 0.0),
            "width": width,
            "morph": morph,
            "stroke_opacity": obj.opacity,
            "overlay": True,
        }
        pdf_page.draw_line(p1, p2, **line_args)
        if obj.shape is ShapeKind.ARROW:
            for wing in _arrow_head(start, end, max(obj.arrow_size, width * 2.5)):
                pdf_page.draw_line(
                    to_pdf_point(pdf_page, end),
                    to_pdf_point(pdf_page, wing),
                    **line_args,
                )


def _arrow_head(start: Point, end: Point, size: float) -> tuple[Point, Point]:
    """Two wing points for an arrow head at *end*, in base page space."""
    dx, dy = end.x - start.x, end.y - start.y
    length = (dx * dx + dy * dy) ** 0.5
    if length <= 1e-6:
        return (end, end)
    ux, uy = dx / length, dy / length
    back = Point(end.x - ux * size * 2.2, end.y - uy * size * 2.2)
    return (
        Point(back.x - uy * size, back.y + ux * size),
        Point(back.x + uy * size, back.y - ux * size),
    )


def _add_annotation(pdf_page: pymupdf.Page, obj: AnnotationObject, base_rotation: int) -> None:
    """Write a standard PDF annotation so external readers understand it."""
    kind = obj.annotation
    annot = None

    if kind.is_text_markup:
        quads = quad_points(pdf_page, obj.quads or [obj.rect])
        if not quads:
            return
        adder = {
            AnnotationKind.HIGHLIGHT: pdf_page.add_highlight_annot,
            AnnotationKind.UNDERLINE: pdf_page.add_underline_annot,
            AnnotationKind.STRIKEOUT: pdf_page.add_strikeout_annot,
        }[kind]
        annot = adder(quads=quads)
        annot.set_colors(stroke=tuple(obj.color))
    elif kind is AnnotationKind.INK:
        strokes = [polyline_to_pdf(pdf_page, stroke) for stroke in obj.strokes if len(stroke) > 1]
        if not strokes:
            return
        annot = pdf_page.add_ink_annot(strokes)
        annot.set_colors(stroke=tuple(obj.color))
        annot.set_border(width=obj.stroke_width)
    elif kind.is_note:
        anchor = to_pdf_point(pdf_page, obj.rect.top_left)
        icon = "Comment" if kind is AnnotationKind.COMMENT else "Note"
        annot = pdf_page.add_text_annot(anchor, obj.contents, icon=icon)
        annot.set_colors(stroke=tuple(obj.color))
    else:  # pragma: no cover - defensive
        log.warning("Unhandled annotation kind %s", kind)
        return

    if annot is None:  # pragma: no cover - defensive
        return
    if obj.contents:
        annot.set_info(content=obj.contents, title=obj.author or "Orion")
    elif obj.author:
        annot.set_info(title=obj.author)
    with suppress(Exception):  # not every annotation type supports opacity
        annot.set_opacity(obj.opacity)
    annot.update()


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------
def build_pdf_bytes(document: Document, *, garbage: int = 3, deflate: bool = True) -> bytes:
    """Render the whole model to PDF bytes (used by tests and by Save As)."""
    with _source_pool(document) as pool:
        out = _assemble(document, pool)
        try:
            for index, page in enumerate(document.pages):
                pdf_page = out.load_page(index)
                _stamp_page(pdf_page, page)
                total = page.total_rotation
                if int(pdf_page.rotation) != total:
                    pdf_page.set_rotation(total)
            if document.metadata:
                try:
                    out.set_metadata(dict(document.metadata))
                except Exception:
                    log.debug("Could not write metadata", exc_info=True)
            return out.tobytes(garbage=garbage, deflate=deflate)
        finally:
            out.close()


def save_document(
    document: Document,
    path: str | Path,
    *,
    garbage: int = 3,
    deflate: bool = True,
) -> SaveResult:
    """Write *document* to *path* atomically (spec §20).

    The sequence is: write a temporary file next to the target, reopen it to
    validate, then ``os.replace``.  The original is only touched by that final
    atomic step, so an error at any earlier point leaves it untouched.
    """
    path = Path(path)
    directory = path.parent
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise PdfWriteError(
            f"The folder “{directory}” could not be created.", detail=str(exc)
        ) from exc

    try:
        data = build_pdf_bytes(document, garbage=garbage, deflate=deflate)
    except PdfWriteError:
        raise
    except MemoryError as exc:
        raise PdfWriteError(
            "Not enough memory to build the document. Try saving fewer pages at a time.",
            detail=str(exc),
        ) from exc
    except Exception as exc:
        raise PdfWriteError(detail=str(exc)) from exc

    def _validate(candidate: Path) -> None:
        with pymupdf.open(candidate) as check:
            if check.page_count != document.page_count:
                raise ValueError(
                    f"validated {check.page_count} pages, expected {document.page_count}"
                )

    try:
        atomic_write_bytes(data, path, validate=_validate)
    except ValueError as exc:
        raise PdfWriteError(
            "The saved file failed validation and was discarded; "
            "your original document has not been changed.",
            detail=str(exc),
        ) from exc
    except OSError as exc:
        if getattr(exc, "errno", None) == 28:
            raise PdfWriteError(
                "There is not enough free disk space to save the document.", detail=str(exc)
            ) from exc
        raise PdfWriteError(
            f"“{path.name}” could not be written. "
            "It may be read-only or open in another application.",
            detail=str(exc),
        ) from exc
    except Exception as exc:
        raise PdfWriteError(
            "The document could not be saved; your original file has not been changed.",
            detail=str(exc),
        ) from exc

    log.info("Saved %s (%d pages, %d bytes)", path, document.page_count, len(data))
    return SaveResult(path=path, page_count=document.page_count, bytes_written=len(data))


