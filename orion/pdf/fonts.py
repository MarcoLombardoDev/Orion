# Orion — PDF Editor for Desktop
# Copyright (C) 2026 Marco Lombardo
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# Distributed WITHOUT ANY WARRANTY; see LICENSE for the full terms.
# A commercial licence, without the AGPL's obligations, is available for use
# in proprietary or closed-source products — see COMMERCIAL-LICENSE.md.

"""Which font a text object is drawn with, and where that font comes from.

Two kinds, one interface. The **base-14** fonts — Helvetica, Times, Courier —
are built into every PDF reader: they cost nothing, need no embedding and no
licence, and they are still the default. Everything else installed on the
machine is a **system font**, embedded as a subset into the file that uses it.

:func:`resolve` is the single entry point. It takes the family and the two
style flags the document model stores, and answers with the name reportlab
should draw with plus the metrics the layout needs, having registered the font
if that was necessary. Nothing above this module knows which of the two kinds
it got.

**On the metrics.** ``ascender`` and ``descender`` are the font *bounding box*,
not the typographic ascent — 1.075 for Helvetica, where the AFM's ascent is
0.718. Orion has always placed its first baseline at
``top + ascender * font_size`` against the bounding-box figure, and changing
the quantity now would lift the first line of every text box in every document
anyone has saved. System fonts are read the same way, from the head table's
bounding box, so a text box does not jump when its font is changed.

**On discovery.** Finding the installed families means reading the ``name``
table out of every font file on the machine, and nothing else: about 0.03 ms
per file, so a few hundred fonts cost under twenty milliseconds and the whole
question of background scanning does not arise. reportlab's own parser reads
the glyph and metric tables too and takes 10 ms a file, which is 350 times
more work for two strings — it is used here only for the handful of fonts a
document actually draws with.

**On what is offered.** A family is listed only if it can actually be
embedded: TrueType outlines, with the tables reportlab needs. PostScript-
outline OpenType and colour bitmap fonts are skipped at the scan, because
offering a font that fails when the file is saved is worse than not offering
it at all.
"""

from __future__ import annotations

import logging
import os
import struct
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

log = logging.getLogger(__name__)

__all__ = [
    "FontRequest",
    "ResolvedFont",
    "BASE14_FAMILIES",
    "available_families",
    "resolve",
    "refresh_system_fonts",
]

#: The three families every PDF reader provides, in the order they are offered.
BASE14_FAMILIES: tuple[str, ...] = ("Helvetica", "Times", "Courier")

#: family -> (regular, bold, italic, bold-italic) base-14 identifiers. These
#: are stored in saved sessions, so they are part of the format.
BASE14_MAP: dict[str, tuple[str, str, str, str]] = {
    "Helvetica": ("helv", "hebo", "heit", "hebi"),
    "Times": ("tiro", "tibo", "tiit", "tibi"),
    "Courier": ("cour", "cobo", "coit", "cobi"),
}

#: Orion's base-14 identifiers mapped to the names reportlab knows them by.
REPORTLAB_NAMES: dict[str, str] = {
    "helv": "Helvetica",
    "hebo": "Helvetica-Bold",
    "heit": "Helvetica-Oblique",
    "hebi": "Helvetica-BoldOblique",
    "tiro": "Times-Roman",
    "tibo": "Times-Bold",
    "tiit": "Times-Italic",
    "tibi": "Times-BoldItalic",
    "cour": "Courier",
    "cobo": "Courier-Bold",
    "coit": "Courier-Oblique",
    "cobi": "Courier-BoldOblique",
}

#: ``(ascender, descender)`` as fractions of the font size — the font bounding
#: box, not the typographic ascent. See the module docstring for why.
BASE14_METRICS: dict[str, tuple[float, float]] = {
    "helv": (1.075, -0.299),
    "hebo": (1.070, -0.307),
    "heit": (1.070, -0.284),
    "hebi": (1.073, -0.309),
    "tiro": (1.053, -0.281),
    "tibo": (1.044, -0.341),
    "tiit": (0.951, -0.270),
    "tibi": (0.972, -0.324),
    "cour": (0.932, -0.317),
    "cobo": (1.007, -0.393),
    "coit": (0.920, -0.317),
    "cobi": (0.997, -0.393),
}

DEFAULT_FAMILY = "Helvetica"
DEFAULT_BASE14 = "helv"

#: Extensions worth opening. A file that is not one of these is not read.
FONT_SUFFIXES = frozenset({".ttf", ".ttc", ".otf"})


@dataclass(frozen=True, slots=True)
class FontRequest:
    """What the document model asks for: a family and two style flags."""

    family: str = DEFAULT_FAMILY
    bold: bool = False
    italic: bool = False


@dataclass(frozen=True, slots=True)
class ResolvedFont:
    """What it actually gets."""

    #: The name to pass to ``canvas.setFont`` and ``pdfmetrics.stringWidth``.
    name: str
    ascender: float
    descender: float
    #: Whether the chosen face is really bold or italic. A family that ships
    #: no italic gives its upright face back, and the canvas has to be told,
    #: or the screen would slant text the saved file does not.
    bold: bool = False
    italic: bool = False
    #: True when the family asked for was not available and Helvetica stood in.
    substituted: bool = False
    #: True for a system font, which is embedded; false for the base-14.
    embedded: bool = False


@dataclass(frozen=True, slots=True)
class _Face:
    """One style of one family, and the file it lives in."""

    family: str
    bold: bool
    italic: bool
    path: Path
    #: Index within a TrueType collection; 0 for an ordinary font file.
    index: int = 0

    @property
    def reportlab_name(self) -> str:
        suffix = ("-Bold" if self.bold else "") + ("-Italic" if self.italic else "")
        return f"Orion:{self.family}{suffix}"


# --------------------------------------------------------------------------
# Where the fonts are
# --------------------------------------------------------------------------
def font_directories() -> list[Path]:
    """The places this platform keeps fonts, user directories included."""
    home = Path.home()
    if sys.platform == "win32":
        windir = Path(os.environ.get("WINDIR", r"C:\Windows"))
        local = os.environ.get("LOCALAPPDATA")
        candidates = [windir / "Fonts"]
        if local:
            candidates.append(Path(local) / "Microsoft" / "Windows" / "Fonts")
    elif sys.platform == "darwin":
        candidates = [
            Path("/System/Library/Fonts"),
            Path("/Library/Fonts"),
            home / "Library" / "Fonts",
        ]
    else:
        candidates = [
            Path("/usr/share/fonts"),
            Path("/usr/local/share/fonts"),
            home / ".fonts",
            home / ".local" / "share" / "fonts",
        ]
    return [path for path in candidates if path.is_dir()]


# --------------------------------------------------------------------------
# Reading just enough of a font file
# --------------------------------------------------------------------------
#: Tables reportlab needs to embed a font. ``glyf``/``loca`` together mean
#: TrueType outlines: a PostScript-outline OpenType has ``CFF `` instead and
#: reportlab cannot embed it, and a colour bitmap font has neither.
REQUIRED_TABLES = (b"glyf", b"loca", b"head", b"cmap")


def _read_table_directory(handle, offset: int) -> dict[bytes, tuple[int, int]]:
    """``{tag: (offset, length)}`` for one font within the file."""
    handle.seek(offset)
    handle.read(4)  # sfnt version
    (count,) = struct.unpack(">H", handle.read(2))
    handle.read(6)  # searchRange, entrySelector, rangeShift
    raw = handle.read(16 * count)
    tables: dict[bytes, tuple[int, int]] = {}
    for index in range(count):
        record = raw[index * 16 : (index + 1) * 16]
        if len(record) < 16:
            break
        tag = record[:4]
        table_offset, length = struct.unpack(">II", record[8:16])
        tables[tag] = (table_offset, length)
    return tables


def _read_names(handle, offset: int, length: int) -> tuple[str, str]:
    """``(family, subfamily)`` from a ``name`` table.

    Name IDs 1 and 2 are the family and the style. The first readable record
    for each wins: a font carries the same name several times over for
    different platforms, and they agree often enough that preferring one
    encoding over another buys nothing.
    """
    handle.seek(offset)
    header = handle.read(6)
    if len(header) < 6:
        return "", ""
    _format, count, strings_offset = struct.unpack(">HHH", header)
    records = handle.read(12 * count)
    base = offset + strings_offset
    found: dict[int, str] = {}
    for index in range(count):
        record = records[index * 12 : (index + 1) * 12]
        if len(record) < 12:
            break
        platform, _encoding, _language, name_id, size, position = struct.unpack(
            ">HHHHHH", record
        )
        if name_id not in (1, 2) or name_id in found:
            continue
        handle.seek(base + position)
        raw = handle.read(size)
        try:
            text = raw.decode("utf-16-be" if platform == 3 else "latin-1")
        except (UnicodeDecodeError, ValueError):
            continue
        text = text.replace("\x00", "").strip()
        if text:
            found[name_id] = text
    return found.get(1, ""), found.get(2, "")


def _faces_in_file(path: Path) -> list[_Face]:
    """Every usable face in one font file, or none if it cannot be embedded."""
    faces: list[_Face] = []
    with open(path, "rb") as handle:
        tag = handle.read(4)
        if tag == b"ttcf":
            handle.read(4)  # version
            (count,) = struct.unpack(">I", handle.read(4))
            offsets = list(struct.unpack(f">{count}I", handle.read(4 * count)))
        else:
            offsets = [0]

        for index, offset in enumerate(offsets):
            tables = _read_table_directory(handle, offset)
            if not all(name in tables for name in REQUIRED_TABLES):
                continue
            if b"name" not in tables:
                continue
            family, style = _read_names(handle, *tables[b"name"])
            if not family:
                continue
            lowered = style.lower()
            faces.append(
                _Face(
                    family=family,
                    bold="bold" in lowered,
                    italic="italic" in lowered or "oblique" in lowered,
                    path=path,
                    index=index,
                )
            )
    return faces


def _scan() -> dict[str, dict[tuple[bool, bool], _Face]]:
    """Index every embeddable face on the machine, by family and style."""
    families: dict[str, dict[tuple[bool, bool], _Face]] = {}
    for directory in font_directories():
        for path in sorted(directory.rglob("*")):
            if path.suffix.lower() not in FONT_SUFFIXES or not path.is_file():
                continue
            try:
                faces = _faces_in_file(path)
            except (OSError, struct.error, ValueError):
                # A font Orion cannot read is a font it does not offer. There
                # is nothing for the user to do about it and nothing to say.
                log.debug("Skipping unreadable font %s", path, exc_info=True)
                continue
            for face in faces:
                # The first file to claim a style keeps it: directories are
                # walked system-first, and a user's copy of a font should not
                # silently replace the one everything else on the machine uses.
                families.setdefault(face.family, {}).setdefault(
                    (face.bold, face.italic), face
                )
    return families


_system_fonts: dict[str, dict[tuple[bool, bool], _Face]] | None = None


def _index() -> dict[str, dict[tuple[bool, bool], _Face]]:
    global _system_fonts
    if _system_fonts is None:
        _system_fonts = _scan()
        log.info("Found %d embeddable font families", len(_system_fonts))
    return _system_fonts


def refresh_system_fonts() -> None:
    """Forget the scan, so the next request picks up newly installed fonts."""
    global _system_fonts
    _system_fonts = None
    resolve.cache_clear()


def available_families() -> tuple[str, ...]:
    """Every family a text object may use: the base-14 first, then the rest.

    The base-14 lead because they are the ones with no consequences — nothing
    embedded, nothing to license, the smallest file. Everything installed
    follows, alphabetically, minus the three that would repeat a base-14 name.
    """
    system = sorted(
        name for name in _index() if name not in BASE14_MAP
    )
    return BASE14_FAMILIES + tuple(system)


# --------------------------------------------------------------------------
# Resolution
# --------------------------------------------------------------------------
def base14_name(family: str, bold: bool, italic: bool) -> str:
    """The base-14 identifier for a style combination of a built-in family."""
    regular, bold_name, italic_name, both = BASE14_MAP.get(
        family, BASE14_MAP[DEFAULT_FAMILY]
    )
    if bold and italic:
        return both
    if bold:
        return bold_name
    if italic:
        return italic_name
    return regular


def _resolve_base14(request: FontRequest, *, substituted: bool = False) -> ResolvedFont:
    identifier = base14_name(request.family, request.bold, request.italic)
    ascender, descender = BASE14_METRICS[identifier]
    return ResolvedFont(
        name=REPORTLAB_NAMES[identifier],
        ascender=ascender,
        descender=descender,
        bold=request.bold,
        italic=request.italic,
        substituted=substituted,
    )


def _fallback(request: FontRequest) -> ResolvedFont:
    """Helvetica, standing in for a family this machine cannot supply.

    Marked as a substitution so the panel can say so: silently drawing a
    different typeface than the one the document names is how a layout gets
    reflowed without anybody noticing.
    """
    return _resolve_base14(
        FontRequest(DEFAULT_FAMILY, request.bold, request.italic), substituted=True
    )


def _closest(styles: dict[tuple[bool, bool], _Face], bold: bool, italic: bool) -> _Face:
    """The nearest face a family actually ships.

    Dropping italic before bold when neither exact match is there: a family
    with one extra weight almost always has the bold, and losing the slant is
    the smaller change to the look of a paragraph.
    """
    for candidate in (
        (bold, italic),
        (bold, False),
        (False, italic),
        (False, False),
    ):
        face = styles.get(candidate)
        if face is not None:
            return face
    return next(iter(styles.values()))


@lru_cache(maxsize=64)
def resolve(request: FontRequest) -> ResolvedFont:
    """The font to draw *request* with, registering it if it is a system one.

    Cached because it is called for every line of every text object on every
    repaint, and because registering the same font twice is wasted work.
    """
    if request.family in BASE14_MAP:
        return _resolve_base14(request)

    styles = _index().get(request.family)
    if not styles:
        log.warning("Font “%s” is not installed; using Helvetica", request.family)
        return _fallback(request)

    face = _closest(styles, request.bold, request.italic)
    try:
        return _register(face)
    except Exception:
        # A font that parsed enough to be listed can still fail to embed.
        # Falling back keeps the document editable and saveable; refusing to
        # draw it would not.
        log.warning("Font “%s” could not be embedded; using Helvetica",
                    request.family, exc_info=True)
        return _fallback(request)


def _register(face: _Face) -> ResolvedFont:
    """Register *face* with reportlab and read its metrics back out."""
    name = face.reportlab_name
    try:
        registered = pdfmetrics.getFont(name)
    except KeyError:
        pdfmetrics.registerFont(
            TTFont(name, str(face.path), subfontIndex=face.index)
        )
        registered = pdfmetrics.getFont(name)

    bbox = getattr(registered.face, "bbox", None)
    if bbox and len(bbox) >= 4:
        ascender, descender = float(bbox[3]) / 1000.0, float(bbox[1]) / 1000.0
    else:  # pragma: no cover - every TrueType face has one
        ascender, descender = 1.0, -0.2
    return ResolvedFont(
        name=name,
        ascender=ascender,
        descender=descender,
        bold=face.bold,
        italic=face.italic,
        embedded=True,
    )
