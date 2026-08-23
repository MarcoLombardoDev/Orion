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

Three libraries share the work, along the seam each is good at:

* **pypdf** assembles the document — copying page runs out of the sources,
  creating blank pages, and carrying annotations and links across.
* **reportlab** draws everything the user added, onto a transparent overlay
  page the size of the page's mediabox, which is then merged in. Generating a
  content stream is what reportlab is for, and it can rotate and blend
  arbitrarily, so text, shapes and images all go through the same path.
* Annotations are written as **PDF dictionaries directly**, because they are
  not content: a highlight is a `/Highlight` object with `/QuadPoints`, and
  building it by hand is both shorter and more predictable than persuading a
  library to emit one.

Everything below the coordinate conversion works in PDF content space —
y upwards from the bottom-left of the *unrotated* mediabox. Nothing here
should ever see a base-space coordinate that has not been through
:mod:`orion.pdf.coordinates`.
"""

from __future__ import annotations

import io
import logging
from collections.abc import Iterator, Sequence
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path

import pypdf
import pypdfium2 as pdfium
from pypdf import PdfReader, PdfWriter
from pypdf.generic import (
    ArrayObject,
    DictionaryObject,
    FloatObject,
    NameObject,
    NumberObject,
    TextStringObject,
)
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas as rl_canvas

from orion.document.annotations import AnnotationKind, AnnotationObject
from orion.document.document import Document
from orion.document.objects import (
    ImageObject,
    PageObject,
    ShapeKind,
    ShapeObject,
    TextObject,
)
from orion.document.page import Page
from orion.pdf.coordinates import (
    PageGeometry,
    content_angle,
    polyline_to_pdf,
    quad_points,
    to_pdf_point,
    to_pdf_rect,
)
from orion.pdf.errors import PdfWriteError
from orion.pdf.text_layout import layout_text, reportlab_name
from orion.utils.fileio import atomic_write_bytes
from orion.utils.geometry import Point

log = logging.getLogger(__name__)

__all__ = ["save_document", "build_pdf_bytes", "SaveResult"]

#: Fallback page size for a source that disappeared between opening and saving.
FALLBACK_SIZE = (595.0, 842.0)


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
        self._open: dict[str, PdfReader] = {}

    def get(self, key: str) -> PdfReader | None:
        if key in self._open:
            return self._open[key]
        source = self._document.sources.get(key)
        if source is None:
            return None
        try:
            if source.data is not None:
                reader = PdfReader(io.BytesIO(source.data))
            elif source.path is not None:
                reader = PdfReader(str(source.path))
            else:
                return None
        except Exception as exc:
            raise PdfWriteError(
                f"The source file “{source.display_name}” could not be read while saving.",
                detail=str(exc),
            ) from exc
        self._open[key] = reader
        return reader

    def close(self) -> None:
        for reader in self._open.values():
            with suppress(Exception):  # pragma: no cover - best effort
                reader.close()
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
def _assemble(document: Document, pool: _SourcePool) -> PdfWriter:
    """Copy source page runs and create blank pages, in document order.

    Runs of consecutive pages from one source are copied in a single call
    rather than page by page: pypdf can then share the resources between them
    instead of duplicating every font and image once per page, which on a
    scanned document is the difference between a file that grows and one that
    does not.
    """
    out = PdfWriter()
    run_key: str | None = None
    run_start = run_end = -1

    def flush() -> None:
        nonlocal run_key, run_start, run_end
        if run_key is None:
            return
        reader = pool.get(run_key)
        if reader is None:
            # The source vanished: emit blanks so page count stays correct.
            for _ in range(run_end - run_start + 1):
                out.add_blank_page(*FALLBACK_SIZE)
        else:
            out.append(reader, pages=(run_start, run_end + 1))
        run_key, run_start, run_end = None, -1, -1

    for page in document.pages:
        if page.source is None:
            flush()
            size = page.base_size
            out.add_blank_page(size.width, size.height)
            continue
        key, index = page.source.source_key, page.source.index
        if key == run_key and index == run_end + 1:
            run_end = index
        else:
            flush()
            run_key, run_start, run_end = key, index, index
    flush()

    if len(out.pages) != document.page_count:  # pragma: no cover - defensive
        raise PdfWriteError(
            "Internal error while assembling the document (page count mismatch)."
        )
    return out


def _page_geometry(pdf_page: pypdf.PageObject) -> tuple[PageGeometry, float, float]:
    """``(geometry, origin_x, origin_y)`` for a page being written.

    A mediabox does not have to start at the origin, and a handful of real
    documents — anything cropped by a scanner driver — do not. Content
    coordinates are relative to that corner, so the offset is returned
    separately and applied once, when the overlay is drawn, instead of leaking
    into every conversion.
    """
    box = pdf_page.mediabox
    left, bottom = float(box.left), float(box.bottom)
    width = abs(float(box.right) - left)
    height = abs(float(box.top) - bottom)
    rotation = int(pdf_page.get("/Rotate", 0) or 0)
    geometry = PageGeometry(
        width or FALLBACK_SIZE[0], height or FALLBACK_SIZE[1], rotation
    )
    return geometry, left, bottom


# --------------------------------------------------------------------------
# Object stamping
# --------------------------------------------------------------------------
def _stamp_page(writer: PdfWriter, index: int, page: Page) -> None:
    """Write every Orion object of *page* onto the corresponding PDF page.

    Called *before* the new rotation is applied, so the geometry still
    describes the source page's own ``/Rotate`` — which is exactly what maps
    Orion base space onto PDF content space.
    """
    pdf_page = writer.pages[index]
    geometry, origin_x, origin_y = _page_geometry(pdf_page)

    drawables = [obj for obj in page.objects if not isinstance(obj, AnnotationObject)]
    annotations = [obj for obj in page.objects if isinstance(obj, AnnotationObject)]

    if drawables:
        overlay = _draw_overlay(drawables, geometry, origin_x, origin_y)
        if overlay is not None:
            pdf_page.merge_page(overlay, over=True)

    for obj in annotations:
        try:
            entry = _annotation_dict(obj, geometry, origin_x, origin_y)
        except Exception as exc:
            log.exception("Could not write annotation %s", obj.id)
            raise PdfWriteError(
                f"An object of type “{obj.display_name}” could not be written.",
                detail=str(exc),
            ) from exc
        if entry is not None:
            writer.add_annotation(index, entry)


def _draw_overlay(
    objects: Sequence[PageObject],
    geometry: PageGeometry,
    origin_x: float,
    origin_y: float,
) -> pypdf.PageObject | None:
    """Render *objects* to a one-page PDF and return it, ready to merge."""
    buffer = io.BytesIO()
    canvas = rl_canvas.Canvas(buffer, pagesize=(geometry.width, geometry.height))
    canvas.translate(origin_x, origin_y)

    for obj in objects:
        try:
            if isinstance(obj, TextObject):
                _draw_text(canvas, obj, geometry)
            elif isinstance(obj, ImageObject):
                _draw_image(canvas, obj, geometry)
            elif isinstance(obj, ShapeObject):
                _draw_shape(canvas, obj, geometry)
            else:  # pragma: no cover - future object kinds
                log.warning("Skipping unknown object type %s", type(obj).__name__)
        except Exception as exc:
            # One bad object must not lose the whole save.
            log.exception("Could not write object %s (%s)", obj.id, type(obj).__name__)
            raise PdfWriteError(
                f"An object of type “{obj.display_name}” could not be written.",
                detail=str(exc),
            ) from exc

    canvas.showPage()
    canvas.save()
    buffer.seek(0)
    try:
        return PdfReader(buffer).pages[0]
    except Exception:  # pragma: no cover - defensive
        log.exception("The generated overlay could not be re-read")
        return None


@contextmanager
def _rotated(canvas, obj: PageObject, geometry: PageGeometry) -> Iterator[None]:
    """Apply an object's rotation about its own centre, then undo it.

    Rotating about the pivot and translating back means everything inside the
    block can go on using absolute content coordinates, instead of every call
    having to be expressed relative to the object's centre.
    """
    canvas.saveState()
    if obj.rotation:
        # No page-rotation term. to_pdf_point has already mapped the pivot, and
        # that map reverses an axis — which inverts the sense of rotation and
        # is the whole of the difference. Adding /Rotate here as well applies
        # it twice, which is invisible on an upright page and wrong on every
        # other one.
        pivot_x, pivot_y = to_pdf_point(geometry, obj.rect.center)
        canvas.translate(pivot_x, pivot_y)
        canvas.rotate(-obj.rotation)
        canvas.translate(-pivot_x, -pivot_y)
    try:
        yield
    finally:
        canvas.restoreState()


def _draw_text(canvas, obj: TextObject, geometry: PageGeometry) -> None:
    if not obj.text.strip():
        return
    layout = layout_text(
        obj.text,
        obj.rect,
        fontname=obj.base14_name,
        font_size=obj.font_size,
        align=obj.align,
        line_spacing=obj.line_spacing,
    )
    font = reportlab_name(obj.base14_name)
    red, green, blue = obj.color

    with _rotated(canvas, obj, geometry):
        canvas.setFillColorRGB(red, green, blue)
        canvas.setStrokeColorRGB(red, green, blue)
        canvas.setFillAlpha(obj.opacity)
        canvas.setStrokeAlpha(obj.opacity)
        canvas.setFont(font, obj.font_size)

        for line in layout.lines:
            for segment in line.segments:
                if not segment.text:
                    continue
                x, y = to_pdf_point(geometry, Point(segment.x, line.baseline))
                _draw_string(canvas, geometry, x, y, segment.text)

        if obj.underline:
            for x0, y, x1, thickness in layout.underline_spans():
                start = to_pdf_point(geometry, Point(x0, y))
                end = to_pdf_point(geometry, Point(x1, y))
                canvas.setLineWidth(thickness)
                canvas.line(start[0], start[1], end[0], end[1])


def _draw_string(canvas, geometry: PageGeometry, x: float, y: float, text: str) -> None:
    """Draw one run of text, upright in *base* space.

    On a quarter-turn page the conversion has swapped the axes, so text that is
    horizontal to the user is vertical in content space and has to be turned to
    match — otherwise it is written across the page and the viewer's own
    ``/Rotate`` then makes it unreadable.
    """
    angle = content_angle(0.0, geometry.rotation) % 360
    if not angle:
        canvas.drawString(x, y, text)
        return
    canvas.saveState()
    canvas.translate(x, y)
    canvas.rotate(angle)
    canvas.drawString(0, 0, text)
    canvas.restoreState()


def _draw_image(canvas, obj: ImageObject, geometry: PageGeometry) -> None:
    """Place a raster image, rotated by the canvas rather than resampled.

    The previous engine could only rotate an image in 90-degree steps, so any
    other angle had to be baked into the pixels with Pillow and placed in an
    expanded bounding box — which resampled the image every save. reportlab
    rotates in the content stream, so the original pixels are written once and
    the viewer does the rotation.
    """
    if not obj.data:
        return
    reader = ImageReader(io.BytesIO(obj.data))
    centre_x, centre_y = to_pdf_point(geometry, obj.rect.center)
    # Base-space dimensions, not the converted rectangle's: on a quarter-turn
    # page the conversion transposes the footprint, and rotating the image by
    # the page angle below is what fills that transposed box correctly. Taking
    # the converted width and height as well would transpose it twice.
    width, height = obj.rect.width, obj.rect.height
    page_angle = content_angle(0.0, geometry.rotation) % 360

    with _rotated(canvas, obj, geometry):
        canvas.setFillAlpha(obj.opacity)
        canvas.setStrokeAlpha(obj.opacity)
        canvas.saveState()
        canvas.translate(centre_x, centre_y)
        if page_angle:
            canvas.rotate(page_angle)
        canvas.drawImage(
            reader,
            -width / 2.0,
            -height / 2.0,
            width=width,
            height=height,
            mask="auto",
            preserveAspectRatio=False,
            anchor="sw",
        )
        canvas.restoreState()


def _draw_shape(canvas, obj: ShapeObject, geometry: PageGeometry) -> None:
    stroke = tuple(obj.stroke_color) if obj.stroke_color else None
    fill = tuple(obj.fill_color) if obj.fill_color else None
    if stroke is None and fill is None:
        return
    width = max(0.0, obj.stroke_width)

    with _rotated(canvas, obj, geometry):
        canvas.setFillAlpha(obj.opacity)
        canvas.setStrokeAlpha(obj.opacity)
        canvas.setLineWidth(width)
        if stroke is not None:
            canvas.setStrokeColorRGB(*stroke)
        if fill is not None:
            canvas.setFillColorRGB(*fill)
        do_stroke = 1 if stroke is not None and width > 0 else 0
        do_fill = 1 if fill is not None else 0

        if obj.shape is ShapeKind.RECTANGLE:
            x0, y0, x1, y1 = to_pdf_rect(geometry, obj.rect)
            canvas.rect(x0, y0, x1 - x0, y1 - y0, stroke=do_stroke, fill=do_fill)
        elif obj.shape is ShapeKind.ELLIPSE:
            x0, y0, x1, y1 = to_pdf_rect(geometry, obj.rect)
            canvas.ellipse(x0, y0, x1, y1, stroke=do_stroke, fill=do_fill)
        elif obj.shape in (ShapeKind.LINE, ShapeKind.ARROW):
            if stroke is None:
                canvas.setStrokeColorRGB(0.0, 0.0, 0.0)
            start, end = obj.start_point(), obj.end_point()
            p1 = to_pdf_point(geometry, start)
            p2 = to_pdf_point(geometry, end)
            canvas.line(p1[0], p1[1], p2[0], p2[1])
            if obj.shape is ShapeKind.ARROW:
                tip = to_pdf_point(geometry, end)
                for wing in _arrow_head(start, end, max(obj.arrow_size, width * 2.5)):
                    point = to_pdf_point(geometry, wing)
                    canvas.line(tip[0], tip[1], point[0], point[1])


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


# --------------------------------------------------------------------------
# Annotations
# --------------------------------------------------------------------------
#: Orion's markup kinds and the PDF annotation subtype each one becomes.
_MARKUP_SUBTYPES = {
    AnnotationKind.HIGHLIGHT: "/Highlight",
    AnnotationKind.UNDERLINE: "/Underline",
    AnnotationKind.STRIKEOUT: "/StrikeOut",
}


def _floats(values: Sequence[float]) -> ArrayObject:
    return ArrayObject([FloatObject(float(v)) for v in values])


def _offset(values: Sequence[float], dx: float, dy: float) -> list[float]:
    """Shift a flat ``x, y, x, y, ...`` list onto a mediabox that is not at 0,0."""
    return [v + (dx if i % 2 == 0 else dy) for i, v in enumerate(values)]


def _bounds_of(flat: Sequence[float], padding: float = 0.0) -> list[float]:
    """The ``/Rect`` enclosing a flat coordinate list."""
    xs = flat[0::2]
    ys = flat[1::2]
    return [
        min(xs) - padding,
        min(ys) - padding,
        max(xs) + padding,
        max(ys) + padding,
    ]


def _annotation_dict(
    obj: AnnotationObject,
    geometry: PageGeometry,
    origin_x: float,
    origin_y: float,
) -> DictionaryObject | None:
    """Build the PDF dictionary for one annotation, or None to skip it.

    No ``/AP`` appearance stream is written. Every annotation here is one of
    the types a reader is required to be able to draw from its own properties,
    and generating appearances by hand means reimplementing each reader's
    idea of what a highlight looks like. Readers that insist on an appearance
    stream generate one on first open.
    """
    kind = obj.annotation
    entry = DictionaryObject()
    entry[NameObject("/Type")] = NameObject("/Annot")

    if kind in _MARKUP_SUBTYPES:
        quads = quad_points(geometry, obj.quads or [obj.rect])
        if not quads:
            return None
        quads = _offset(quads, origin_x, origin_y)
        entry[NameObject("/Subtype")] = NameObject(_MARKUP_SUBTYPES[kind])
        entry[NameObject("/QuadPoints")] = _floats(quads)
        entry[NameObject("/Rect")] = _floats(_bounds_of(quads))
    elif kind is AnnotationKind.INK:
        strokes = [
            _offset(polyline_to_pdf(geometry, stroke), origin_x, origin_y)
            for stroke in obj.strokes
            if len(stroke) > 1
        ]
        if not strokes:
            return None
        entry[NameObject("/Subtype")] = NameObject("/Ink")
        entry[NameObject("/InkList")] = ArrayObject([_floats(s) for s in strokes])
        # The rect has to clear the stroke, not just its centre line, or
        # readers that clip to it shave the outside edge off every curve.
        flat = [value for stroke in strokes for value in stroke]
        entry[NameObject("/Rect")] = _floats(_bounds_of(flat, obj.stroke_width))
        border = DictionaryObject()
        border[NameObject("/W")] = FloatObject(float(obj.stroke_width))
        entry[NameObject("/BS")] = border
    elif kind.is_note:
        x, y = to_pdf_point(geometry, obj.rect.top_left)
        x, y = x + origin_x, y + origin_y
        size = max(obj.rect.width, 20.0)
        entry[NameObject("/Subtype")] = NameObject("/Text")
        entry[NameObject("/Rect")] = _floats([x, y - size, x + size, y])
        entry[NameObject("/Name")] = NameObject(
            "/Comment" if kind is AnnotationKind.COMMENT else "/Note"
        )
        entry[NameObject("/Open")] = pypdf.generic.BooleanObject(False)
    else:  # pragma: no cover - defensive
        log.warning("Unhandled annotation kind %s", kind)
        return None

    entry[NameObject("/C")] = _floats(tuple(obj.color))
    entry[NameObject("/CA")] = FloatObject(float(obj.opacity))
    if obj.contents:
        entry[NameObject("/Contents")] = TextStringObject(obj.contents)
    if obj.author:
        entry[NameObject("/T")] = TextStringObject(obj.author)
    elif obj.contents:
        entry[NameObject("/T")] = TextStringObject("Orion")
    return entry


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------
def build_pdf_bytes(document: Document, *, garbage: int = 3, deflate: bool = True) -> bytes:
    """Render the whole model to PDF bytes (used by tests and by Save As).

    ``garbage`` and ``deflate`` are kept for call-site compatibility; pypdf
    exposes the equivalent as object deduplication and content-stream
    compression, and both are applied when asked for.
    """
    with _source_pool(document) as pool:
        out = _assemble(document, pool)
        for index, page in enumerate(document.pages):
            _stamp_page(out, index, page)
            total = int(page.total_rotation) % 360
            out.pages[index][NameObject("/Rotate")] = NumberObject(total)

        if document.metadata:
            try:
                out.add_metadata(
                    {
                        NameObject(f"/{key}"): TextStringObject(str(value))
                        for key, value in document.metadata.items()
                        if key and value
                    }
                )
            except Exception:
                log.debug("Could not write metadata", exc_info=True)

        if garbage:
            with suppress(Exception):
                out.compress_identical_objects()
        if deflate:
            for pdf_page in out.pages:
                with suppress(Exception):
                    pdf_page.compress_content_streams()

        buffer = io.BytesIO()
        out.write(buffer)
        return buffer.getvalue()


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
        # Validated with the rendering engine rather than the writing one: a
        # file pypdf is willing to read back is not proof of much, since it
        # wrote it. This is the library that has to display it afterwards.
        check = pdfium.PdfDocument(candidate)
        try:
            if len(check) != document.page_count:
                raise ValueError(
                    f"validated {len(check)} pages, expected {document.page_count}"
                )
        finally:
            check.close()

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
