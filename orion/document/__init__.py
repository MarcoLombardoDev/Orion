# Orion — PDF Editor for Desktop
# Copyright (C) 2026 Marco Lombardo
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# Distributed WITHOUT ANY WARRANTY; see LICENSE for the full terms.
# A commercial licence, without the AGPL's obligations, is available for use
# in proprietary or closed-source products — see COMMERCIAL-LICENSE.md.

"""The intermediate document model.

This layer is deliberately free of Qt *and* of the PDF libraries: it is the neutral
representation the UI edits and the PDF writer consumes.
"""

from orion.document.annotations import AnnotationKind, AnnotationObject, InkStroke
from orion.document.document import Document, DocumentSource
from orion.document.objects import (
    Align,
    Color,
    ImageObject,
    ObjectKind,
    PageObject,
    ShapeKind,
    ShapeObject,
    TextObject,
    create_object,
)
from orion.document.page import Page, PageSource

__all__ = [
    "Align",
    "AnnotationKind",
    "AnnotationObject",
    "Color",
    "Document",
    "DocumentSource",
    "ImageObject",
    "InkStroke",
    "ObjectKind",
    "Page",
    "PageObject",
    "PageSource",
    "ShapeKind",
    "ShapeObject",
    "TextObject",
    "create_object",
]
