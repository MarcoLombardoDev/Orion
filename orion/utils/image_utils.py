# Orion — PDF Editor for Desktop
# Copyright (C) 2026 Marco Lombardo
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# Distributed WITHOUT ANY WARRANTY; see LICENSE for the full terms.
# A commercial licence, without the AGPL's obligations, is available for use
# in proprietary or closed-source products — see COMMERCIAL-LICENSE.md.

"""Image decoding, validation and transformation helpers built on Pillow."""

from __future__ import annotations

import io
import logging
from pathlib import Path

from orion.utils.geometry import Size

log = logging.getLogger(__name__)

#: Formats Orion accepts for image objects (spec §10).
SUPPORTED_FORMATS: tuple[str, ...] = ("png", "jpeg", "jpg", "webp")
SUPPORTED_EXTENSIONS: tuple[str, ...] = (".png", ".jpg", ".jpeg", ".webp")

#: Images larger than this on either axis are downsampled on import so a
#: 100-megapixel photo cannot exhaust memory (spec §25 "memoria insufficiente").
MAX_IMPORT_PIXELS = 8192


class UnsupportedImageError(ValueError):
    """Raised when an image cannot be decoded or is in an unsupported format."""


def _pillow():
    from PIL import Image  # imported lazily so tests can run without a GUI

    return Image


def load_image_bytes(path: str | Path) -> tuple[bytes, str, Size]:
    """Read an image file and return ``(data, format, natural_size)``.

    The *encoded* bytes are returned, not a decoded raster: the document model
    stores them verbatim so clipboard, autosave and save-to-PDF are all
    self-contained and lossless.
    """
    path = Path(path)
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise UnsupportedImageError(f"Cannot read image file: {exc.strerror or exc}") from exc
    return decode_image_bytes(data)


def decode_image_bytes(data: bytes) -> tuple[bytes, str, Size]:
    """Validate encoded image *data*, returning ``(data, format, natural_size)``."""
    Image = _pillow()
    try:
        with Image.open(io.BytesIO(data)) as img:
            fmt = (img.format or "").lower()
            width, height = img.size
    except Exception as exc:  # Pillow raises many unrelated exception types
        raise UnsupportedImageError("The file is not a readable image.") from exc

    if fmt not in SUPPORTED_FORMATS:
        raise UnsupportedImageError(
            f"Unsupported image format {fmt.upper() or 'unknown'}. "
            f"Supported: {', '.join(f.upper() for f in ('png', 'jpeg', 'webp'))}."
        )
    if width <= 0 or height <= 0:
        raise UnsupportedImageError("The image has no usable dimensions.")

    if max(width, height) > MAX_IMPORT_PIXELS:
        data, fmt, size = downscale(data, MAX_IMPORT_PIXELS)
        log.info("Downscaled oversized image to %sx%s on import", size.width, size.height)
        return data, fmt, size

    return data, fmt, Size(float(width), float(height))


def downscale(data: bytes, max_edge: int) -> tuple[bytes, str, Size]:
    """Return *data* re-encoded so neither edge exceeds *max_edge* pixels."""
    Image = _pillow()
    with Image.open(io.BytesIO(data)) as img:
        img = img.copy()
    factor = max_edge / float(max(img.size))
    new_size = (max(1, int(img.size[0] * factor)), max(1, int(img.size[1] * factor)))
    img = img.resize(new_size, Image.LANCZOS)
    return encode(img, "png")


def encode(img, fmt: str = "png") -> tuple[bytes, str, Size]:
    """Encode a Pillow image, returning ``(data, format, size)``."""
    buffer = io.BytesIO()
    if fmt == "jpeg" and img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    img.save(buffer, format=fmt.upper())
    return buffer.getvalue(), fmt, Size(float(img.size[0]), float(img.size[1]))


def natural_size(data: bytes) -> Size:
    Image = _pillow()
    with Image.open(io.BytesIO(data)) as img:
        return Size(float(img.size[0]), float(img.size[1]))
