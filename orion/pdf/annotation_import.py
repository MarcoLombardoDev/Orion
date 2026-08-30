# Orion — PDF Editor for Desktop
# Copyright (C) 2026 Marco Lombardo
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# Distributed WITHOUT ANY WARRANTY; see LICENSE for the full terms.
# A commercial licence, without the AGPL's obligations, is available for use
# in proprietary or closed-source products — see COMMERCIAL-LICENSE.md.

"""Reading the annotations already in a PDF back into the document model.

This is the mirror of the annotation half of :mod:`orion.pdf.writer`, and the
two are deliberately built around one shared list: :data:`OWNED_SUBTYPES`.

Orion **takes ownership** of the annotation types it can represent. Those are
turned into :class:`AnnotationObject` here, so the user can select, recolour
and delete them like anything else they drew; on the way out the writer drops
the originals from the copied page and writes the model's version instead.
Everything else — links, form fields, stamps, file attachments, the markup
kinds Orion has no tool for — is neither imported nor touched, and rides
through the save inside the copied page exactly as it arrived.

Without this, an annotation was editable only until the file was closed. It
was written correctly, every other reader showed it, and reopening the
document turned it into part of the scenery: still drawn, because pdfium draws
annotations, but with nothing behind it to click. Deleting a highlight
somebody else had put in a contract was impossible in a PDF *editor*.

Ownership is recorded per page as the indices the objects came from, rather
than inferred from the subtype at save time. The difference matters when an
annotation is skipped: one that is malformed, or of an owned subtype but
carrying no geometry Orion can use, is left in the file untouched instead of
being deleted by a save it was never part of.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from pypdf.generic import DictionaryObject

from orion.document.annotations import (
    DEFAULT_ANNOTATION_COLORS,
    NOTE_ICON_SIZE,
    AnnotationKind,
    AnnotationObject,
)
from orion.pdf.coordinates import PageGeometry, from_pdf_point, from_pdf_rect
from orion.utils.geometry import Point, Rect

log = logging.getLogger(__name__)

__all__ = ["ImportedAnnotations", "OWNED_SUBTYPES", "import_annotations"]

#: PDF subtype -> the Orion annotation it becomes. A subtype absent from this
#: table is left alone, both here and in the writer.
OWNED_SUBTYPES: dict[str, AnnotationKind] = {
    "/Highlight": AnnotationKind.HIGHLIGHT,
    "/Underline": AnnotationKind.UNDERLINE,
    "/StrikeOut": AnnotationKind.STRIKEOUT,
    "/Ink": AnnotationKind.INK,
    "/Text": AnnotationKind.COMMENT,
}

#: Below this, a quad is a rounding artefact rather than a marked-up line.
MIN_QUAD_SIZE = 0.5


@dataclass(slots=True)
class ImportedAnnotations:
    """What one page gave up: the objects, and where they came from."""

    objects: list[AnnotationObject] = field(default_factory=list)
    #: Indices into the page's ``/Annots`` that :attr:`objects` replace.
    indices: tuple[int, ...] = ()


def import_annotations(pdf_page, geometry: PageGeometry) -> ImportedAnnotations:
    """Read the owned annotations of one page into base page space.

    *pdf_page* is a pypdf page; *geometry* describes its **unrotated** mediabox
    and its own ``/Rotate``, so the result is in the same base page space every
    object in the model uses.
    """
    try:
        annots = pdf_page.get("/Annots")
    except Exception:  # pragma: no cover - a damaged page dictionary
        log.debug("Could not read /Annots", exc_info=True)
        return ImportedAnnotations()
    if not annots:
        return ImportedAnnotations()

    origin_x, origin_y = _mediabox_origin(pdf_page)
    objects: list[AnnotationObject] = []
    indices: list[int] = []

    for index, reference in enumerate(annots):
        try:
            entry = reference.get_object()
            kind = OWNED_SUBTYPES.get(str(entry.get("/Subtype", "")))
            if kind is None:
                continue
            obj = _build(entry, kind, geometry, origin_x, origin_y)
        except Exception:
            # One unreadable annotation must not stop a file from opening, and
            # leaving it unimported also leaves it in the saved file.
            log.warning("Skipping an unreadable annotation", exc_info=True)
            continue
        if obj is None:
            continue
        objects.append(obj)
        indices.append(index)

    return ImportedAnnotations(objects=objects, indices=tuple(indices))


def _mediabox_origin(pdf_page) -> tuple[float, float]:
    """The mediabox corner, which annotation coordinates are relative to.

    Nearly always (0, 0); a page cropped by a scanner driver is the exception,
    and there every coordinate in the file is offset by it.
    """
    try:
        box = pdf_page.mediabox
        return float(box.left), float(box.bottom)
    except Exception:  # pragma: no cover - defensive
        return 0.0, 0.0


def _build(
    entry: DictionaryObject,
    kind: AnnotationKind,
    geometry: PageGeometry,
    origin_x: float,
    origin_y: float,
) -> AnnotationObject | None:
    """One annotation dictionary -> one Orion object, or None to leave it."""
    obj = AnnotationObject(
        annotation=kind,
        color=_colour(entry, kind),
        contents=_string(entry, "/Contents"),
        author=_string(entry, "/T"),
        opacity=_opacity(entry),
    )

    if kind.is_text_markup:
        obj.quads = _quads(entry, geometry, origin_x, origin_y)
        if not obj.quads:
            # A markup annotation with no usable /QuadPoints has nothing to
            # attach to. Falling back to /Rect would put a block of colour over
            # a paragraph the user never marked.
            return None
        obj.rect = obj.recompute_rect()
        return obj

    if kind is AnnotationKind.INK:
        obj.strokes = _strokes(entry, geometry, origin_x, origin_y)
        if not obj.strokes:
            return None
        obj.stroke_width = _border_width(entry)
        obj.rect = obj.recompute_rect()
        return obj

    rect = _rect(entry, geometry, origin_x, origin_y)
    if rect is None:
        return None
    # A note is an icon of a fixed size wherever it came from: readers draw
    # /Text at their own size and the stored /Rect is frequently nonsense.
    obj.annotation = _note_kind(entry)
    obj.rect = Rect.from_xywh(rect.x0, rect.y0, NOTE_ICON_SIZE, NOTE_ICON_SIZE)
    return obj


def _note_kind(entry: DictionaryObject) -> AnnotationKind:
    """``/Text`` covers both of Orion's notes; ``/Name`` says which."""
    name = str(entry.get("/Name", "") or "")
    if name in ("/Note", "/Help", "/Paragraph", "/NewParagraph"):
        return AnnotationKind.STICKY_NOTE
    return AnnotationKind.COMMENT


def _quads(
    entry: DictionaryObject, geometry: PageGeometry, origin_x: float, origin_y: float
) -> list[Rect]:
    """``/QuadPoints`` -> one base-space rectangle per marked-up line.

    The eight numbers per quad are corners, not a rectangle, and writers
    disagree about the order — the specification says upper-left, upper-right,
    lower-left, lower-right, and enough real files use the winding order of a
    polygon instead that reading them positionally gets some documents wrong.
    Taking the extent of all four corners is right for both, which is what
    every reader ends up doing.
    """
    values = [float(v) for v in (entry.get("/QuadPoints") or [])]
    rects: list[Rect] = []
    for start in range(0, len(values) - 7, 8):
        quad = values[start : start + 8]
        xs = [x - origin_x for x in quad[0::2]]
        ys = [y - origin_y for y in quad[1::2]]
        rect = from_pdf_rect(geometry, (min(xs), min(ys), max(xs), max(ys)))
        if rect.width >= MIN_QUAD_SIZE and rect.height >= MIN_QUAD_SIZE:
            rects.append(rect)
    return rects


def _strokes(
    entry: DictionaryObject, geometry: PageGeometry, origin_x: float, origin_y: float
) -> list[list[Point]]:
    """``/InkList`` -> one base-space polyline per pen-down..pen-up gesture."""
    strokes: list[list[Point]] = []
    for raw in entry.get("/InkList") or []:
        values = [float(v) for v in raw.get_object()]
        points = [
            from_pdf_point(geometry, (values[i] - origin_x, values[i + 1] - origin_y))
            for i in range(0, len(values) - 1, 2)
        ]
        if len(points) > 1:
            strokes.append(points)
    return strokes


def _rect(
    entry: DictionaryObject, geometry: PageGeometry, origin_x: float, origin_y: float
) -> Rect | None:
    values = [float(v) for v in (entry.get("/Rect") or [])]
    if len(values) < 4:
        return None
    x0, y0, x1, y1 = values[:4]
    return from_pdf_rect(
        geometry,
        (
            min(x0, x1) - origin_x,
            min(y0, y1) - origin_y,
            max(x0, x1) - origin_x,
            max(y0, y1) - origin_y,
        ),
    )


def _colour(entry: DictionaryObject, kind: AnnotationKind) -> tuple[float, float, float]:
    """``/C`` -> RGB, whatever colour space it was written in.

    An empty array is legal and means "no colour": the reader picks. Orion has
    to store something, so it uses the colour its own tool would have made.
    """
    values = [float(v) for v in (entry.get("/C") or [])]
    if len(values) == 3:
        return (values[0], values[1], values[2])
    if len(values) == 1:  # DeviceGray
        return (values[0], values[0], values[0])
    if len(values) == 4:  # DeviceCMYK
        cyan, magenta, yellow, black = values
        return (
            (1.0 - min(1.0, cyan + black)),
            (1.0 - min(1.0, magenta + black)),
            (1.0 - min(1.0, yellow + black)),
        )
    return DEFAULT_ANNOTATION_COLORS[kind]


def _opacity(entry: DictionaryObject) -> float:
    try:
        value = float(entry.get("/CA", 1.0))
    except (TypeError, ValueError):
        return 1.0
    return min(1.0, max(0.05, value))


def _border_width(entry: DictionaryObject) -> float:
    """The ink stroke width, from ``/BS`` or the older ``/Border``."""
    border = entry.get("/BS")
    if isinstance(border, DictionaryObject) or hasattr(border, "get"):
        try:
            return max(0.1, float(border.get("/W", 1.5)))
        except (TypeError, ValueError):
            pass
    values = entry.get("/Border")
    if values is not None and len(values) >= 3:
        try:
            return max(0.1, float(values[2]))
        except (TypeError, ValueError):
            pass
    return 1.5


def _string(entry: DictionaryObject, key: str) -> str:
    value = entry.get(key)
    if value is None:
        return ""
    try:
        return str(value)
    except Exception:  # pragma: no cover - an undecodable string object
        return ""

