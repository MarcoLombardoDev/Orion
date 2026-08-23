# Orion — PDF Editor for Desktop
# Copyright (C) 2026 Marco Lombardo
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# Distributed WITHOUT ANY WARRANTY; see LICENSE for the full terms.
# A commercial licence, without the AGPL's obligations, is available for use
# in proprietary or closed-source products — see COMMERCIAL-LICENSE.md.

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
