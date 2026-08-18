"""PDF engine: reading, rasterising, writing and file-level operations.

Nothing in this package imports Qt.  The renderer returns raw RGB buffers and
:mod:`orion.ui.render_bridge` turns them into ``QImage``.
"""

from orion.pdf.errors import (
    OrionPdfError,
    PdfCorruptError,
    PdfPasswordRequired,
    PdfReadError,
    PdfWriteError,
    UnsupportedOperationError,
)

__all__ = [
    "OrionPdfError",
    "PdfCorruptError",
    "PdfPasswordRequired",
    "PdfReadError",
    "PdfWriteError",
    "UnsupportedOperationError",
]
