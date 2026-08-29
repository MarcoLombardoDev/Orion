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
"""

import pathlib
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
    """In target pixels. Zero below 32: at that size a frame costs more in
    contrast than it returns in shape, and the letter needs the room."""
    if target < 32:
        return 0
    return max(1, round(target / 28))


def _letter_height(target: int) -> float:
    """As a fraction of the square. The smaller the icon, the more of it the
    letter has to be before it stops reading as a letter."""
    if target < 32:
        return 0.86
    if target <= 48:
        return 0.72
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


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: make_icon.py <Name> <output directory>", file=sys.stderr)
        return 2

    name, out = argv[1], pathlib.Path(argv[2])
    out.mkdir(parents=True, exist_ok=True)
    letter = name[0].upper()

    draw(letter, PNG_SIZE).save(out / f"{name.lower()}.png")

    # Largest first: Pillow drops any requested size bigger than the image it
    # was handed, so leading with 16x16 silently produces a one-frame icon.
    frames = [draw(letter, size) for size in sorted(ICO_SIZES, reverse=True)]
    frames[0].save(
        out / f"{name.lower()}.ico",
        sizes=[(size, size) for size in ICO_SIZES],
        append_images=frames[1:],
    )
    print(f"{name}: wrote {name.lower()}.png and {name.lower()}.ico in {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
