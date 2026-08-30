#!/usr/bin/env python3
# Orion — PDF Editor for Desktop
# Copyright (C) 2026 Marco Lombardo
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# Distributed WITHOUT ANY WARRANTY; see LICENSE for the full terms.
# A commercial licence, without the AGPL's obligations, is available for use
# in proprietary or closed-source products — see COMMERCIAL-LICENSE.md.

"""Draw the application icon: the initial, in black, on white.

One letter, a serif face, a thin frame. The four products share the drawing
and differ only in the letter, so a taskbar with all four open reads as one
family rather than four unrelated programs.

The face is Liberation Serif, metric-compatible with Times New Roman and
redistributable; Times New Roman itself is neither free nor present on the
machines that build these. The output is committed rather than generated at
build time, so no release depends on which fonts a runner happens to have.

Every size is drawn for itself rather than scaled down from one master. A
frame that reads as a hairline at 256 pixels is a smear at 16, and the letter
that has room to breathe at 256 has to fill the square at 16 to be a letter at
all. Scaling one drawing gives the small sizes -- the ones actually on the
taskbar -- to whichever end of the range was drawn first.

The .ico is assembled here rather than by Pillow, for one reason: which
compression each frame uses. Pillow writes every frame as PNG. Windows has
accepted PNG frames since Vista, but the format every icon editor produces,
and the one the shell has always read, is an uncompressed DIB below 256 pixels
and PNG only for the 256 -- which is the size where PNG saves something worth
saving. Explorer showing a stale or generic icon for an executable whose
resources are demonstrably correct is exactly the shape of problem that
convention exists to avoid, so this writes the conventional thing.
"""

import io
import pathlib
import struct
import sys

from PIL import Image, ImageDraw, ImageFont

#: Every size Windows asks for. 256 is also what macOS and Linux use.
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)
PNG_SIZE = 512

#: Each size is drawn this much larger and then reduced, so the edges are
#: antialiased rather than aliased into the few pixels available.
SUPERSAMPLE = 8

FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",
    "/usr/share/fonts/liberation/LiberationSerif-Regular.ttf",
    "C:/Windows/Fonts/times.ttf",
    "/System/Library/Fonts/Supplemental/Times New Roman.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
)

BLACK = (0, 0, 0, 255)
WHITE = (255, 255, 255, 255)


def _font(size: int) -> ImageFont.FreeTypeFont:
    for path in FONT_CANDIDATES:
        if pathlib.Path(path).exists():
            return ImageFont.truetype(path, size)
    raise SystemExit("no serif font found; install fonts-liberation and retry")


def _frame_width(target: int) -> int:
    """In target pixels, and never zero.

    It was zero below 32 pixels, on the reasoning that at that size a frame
    costs more in contrast than it returns in shape. That was a judgement
    about one icon rather than about four: the products draw their window
    icon from different sources -- Qt scales the 512-pixel PNG, Tk picks the
    matching frame out of the .ico -- so a rule that changed the drawing with
    the size made the same product look like two, and the four look like
    four different families. One shape, one letter apart, at every size.
    """
    return max(1, round(target / 28))


def _letter_height(target: int) -> float:
    """As a fraction of the square. The smaller the icon, the more of it the
    letter has to be before it stops reading as a letter -- but it now shares
    the square with a frame at every size, so there is a little less of it to
    have."""
    if target < 32:
        return 0.66
    if target <= 48:
        return 0.68
    return 0.62


def draw(letter: str, target: int) -> Image.Image:
    canvas = target * SUPERSAMPLE
    image = Image.new("RGBA", (canvas, canvas), WHITE)
    pen = ImageDraw.Draw(image)

    frame = _frame_width(target) * SUPERSAMPLE
    if frame:
        pen.rectangle((0, 0, canvas - 1, canvas - 1), outline=BLACK, width=frame)

    # Sized and centred on the ink, not on the font's metrics: a serif capital
    # sits well off-centre inside its own advance box, and centring on that
    # puts it visibly low and to the left.
    wanted = canvas * _letter_height(target)
    font = _font(int(wanted))
    left, top, right, bottom = pen.textbbox((0, 0), letter, font=font)
    if bottom - top:
        font = _font(max(1, int(wanted * wanted / (bottom - top))))
        left, top, right, bottom = pen.textbbox((0, 0), letter, font=font)

    pen.text(
        ((canvas - (right - left)) / 2 - left,
         (canvas - (bottom - top)) / 2 - top),
        letter,
        font=font,
        fill=BLACK,
    )
    return image.resize((target, target), Image.LANCZOS)



def _dib_frame(image: Image.Image) -> bytes:
    """One icon frame in the uncompressed form Windows has always read.

    A BITMAPINFOHEADER whose height is doubled -- the convention that says
    "colour rows, then mask rows" -- followed by bottom-up BGRA pixels and a
    1-bit AND mask. The mask is all zeroes because these icons are fully
    opaque; it is written out anyway rather than left off, because a header
    that promises mask rows and a frame that does not carry them is the kind
    of nearly-valid file that works in one reader and not the next.
    """
    width, height = image.size
    pixels = image.convert("RGBA").tobytes()

    rows = []
    for y in range(height - 1, -1, -1):          # bottom-up
        row = bytearray()
        for x in range(width):
            r, g, b, a = pixels[(y * width + x) * 4:(y * width + x) * 4 + 4]
            row += bytes((b, g, r, a))           # BGRA, not RGBA
        rows.append(bytes(row))
    xor = b"".join(rows)

    mask_stride = ((width + 31) // 32) * 4       # rows padded to 4 bytes
    and_mask = b"\x00" * (mask_stride * height)

    header = struct.pack(
        "<IiiHHIIiiII",
        40,              # biSize
        width,
        height * 2,      # colour rows plus mask rows
        1,               # biPlanes
        32,              # biBitCount
        0,               # biCompression: BI_RGB
        len(xor) + len(and_mask),
        0, 0, 0, 0,      # resolution and palette counts
    )
    return header + xor + and_mask


def build_ico(frames: dict[int, Image.Image]) -> bytes:
    """Assemble the .ico: DIB below 256 pixels, PNG for the 256."""
    payloads = []
    for size in sorted(frames):
        if size >= 256:
            buffer = io.BytesIO()
            frames[size].save(buffer, "png")
            payloads.append((size, buffer.getvalue(), True))
        else:
            payloads.append((size, _dib_frame(frames[size]), False))

    header = struct.pack("<HHH", 0, 1, len(payloads))
    offset = len(header) + 16 * len(payloads)
    directory, data = b"", b""
    for size, blob, _is_png in payloads:
        directory += struct.pack(
            "<BBBBHHII",
            0 if size >= 256 else size,   # 0 means 256
            0 if size >= 256 else size,
            0,           # no palette
            0,           # reserved
            1,           # planes
            32,          # bits per pixel
            len(blob),
            offset,
        )
        data += blob
        offset += len(blob)
    return header + directory + data


#: The ``.icns`` entries macOS reads, as (four-character type, pixel size).
#:
#: Each is a PNG, which every macOS since 10.7 accepts and which keeps the file
#: a tenth the size of the old raw-ARGB-plus-mask encoding. The pairs are the
#: retina ones: ``ic11`` is 16pt at 2x and ``ic12`` is 32pt at 2x, so a Finder
#: showing 16-point icons on a retina display has a real 32-pixel drawing to
#: use instead of a scaled 16.
ICNS_TYPES = (
    (b"icp4", 16),
    (b"icp5", 32),
    (b"ic11", 32),
    (b"ic12", 64),
    (b"ic07", 128),
    (b"ic13", 256),
    (b"ic08", 256),
    (b"ic14", 512),
    (b"ic09", 512),
)


def build_icns(letter: str) -> bytes:
    """Assemble the ``.icns`` macOS wants for an application bundle.

    Written out here rather than left to PyInstaller. PyInstaller will convert
    a PNG on the fly, but only if Pillow happens to be installed in the build
    environment — and when it is not, the macOS job dies at BUNDLE() with
    "not in the correct format" after the whole build has succeeded. That is
    exactly what happened to the first release of the product that has no
    Pillow. An icon committed as a file cannot fail that way.

    The container is as simple as the .ico: an 8-byte header carrying the
    magic and the total length, then one chunk per entry, each with its own
    four-character type and a length that counts its own 8 bytes.
    """
    chunks = b""
    for kind, size in ICNS_TYPES:
        buffer = io.BytesIO()
        draw(letter, size).save(buffer, "png")
        blob = buffer.getvalue()
        chunks += kind + struct.pack(">I", len(blob) + 8) + blob
    return b"icns" + struct.pack(">I", len(chunks) + 8) + chunks

def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: make_icon.py <Name> <output directory>", file=sys.stderr)
        return 2

    name, out = argv[1], pathlib.Path(argv[2])
    out.mkdir(parents=True, exist_ok=True)
    letter = name[0].upper()

    draw(letter, PNG_SIZE).save(out / f"{name.lower()}.png")

    frames = {size: draw(letter, size) for size in ICO_SIZES}
    (out / f"{name.lower()}.ico").write_bytes(build_ico(frames))
    (out / f"{name.lower()}.icns").write_bytes(build_icns(letter))
    print(
        f"{name}: wrote {name.lower()}.png, {name.lower()}.ico "
        f"and {name.lower()}.icns in {out}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
