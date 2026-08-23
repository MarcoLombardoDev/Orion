#!/usr/bin/env python
# Orion — PDF Editor for Desktop
# Copyright (C) 2026 Marco Lombardo
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# Distributed WITHOUT ANY WARRANTY; see LICENSE for the full terms.
# A commercial licence, without the AGPL's obligations, is available for use
# in proprietary or closed-source products — see COMMERCIAL-LICENSE.md.

"""Assemble the licence texts that must travel inside a release archive.

Orion's v1.0.0 archives shipped without a single licence file in them. A
recursive search of all three for LICENSE, COPYING or NOTICE returned nothing.
That is not a formality: LGPL-3.0 §4 requires a copy of the licence to
accompany the object code, the BSD and MIT libraries require their copyright
notices be reproduced in binary distributions, and MuPDF's AGPL requires the
same. Shipping a hundred-odd libraries with none of their terms attached is a
straightforward compliance defect, and THIRD-PARTY-LICENSES.md sitting in the
repository does not fix it — a user who downloads a zip never sees it.

So orion.spec calls this before COLLECT, and the resulting tree is added to
the bundle as ``licenses/``.

Three sources feed it, in descending order of authority:

1. **The distributions themselves.** Most wheels ship their licence in
   dist-info, and that copy is the one their authors chose to send. Pillow's
   is particularly worth having: 1,574 lines covering every native library it
   vendors, from libjpeg to zstd.

2. **Canonical texts vendored in ``licenses/``** for the distributions that
   ship none. PySide6 is the important one — the wheels declare LGPL-3.0 in
   their metadata and then include no licence file at all, so there is nothing
   to copy forward and the text has to come from somewhere. LGPL-3.0 is also
   not self-contained: it is a set of additional permissions on top of GPL-3.0,
   so shipping it alone would be shipping half a licence. Both go.

3. **The build machine's package copyright records**, on Linux, for the
   libraries PyInstaller collected from the system. These vary with the runner
   image, which is exactly why they are read at build time rather than
   committed.

What this script does *not* do is decide anything. It copies texts and records
where each came from. The analysis of what those texts require lives in
THIRD-PARTY-LICENSES.md, and the reader of a bundle gets pointed at both.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import sys

log = logging.getLogger(__name__)

#: Distributions whose wheels ship no licence file, mapped to the canonical
#: texts that have to be supplied on their behalf. Qt's entry carries two
#: files on purpose: LGPL-3.0 is a supplement to GPL-3.0 and means nothing
#: without it.
SUPPLIED_TEXTS = {
    "PySide6": ("LGPL-3.0.txt", "GPL-3.0.txt"),
    "PySide6_Essentials": ("LGPL-3.0.txt", "GPL-3.0.txt"),
    "PySide6_Addons": ("LGPL-3.0.txt", "GPL-3.0.txt"),
    "shiboken6": ("LGPL-3.0.txt", "GPL-3.0.txt"),
}

#: Runtime distributions, in the order a reader should meet them. Build-time
#: tools are deliberately absent: they are not in the archive, so their terms
#: do not belong in it. PyInstaller is the exception discussed in
#: THIRD-PARTY-LICENSES.md — its bootloader *is* shipped, under an exception
#: that permits exactly that, so its COPYING.txt comes along.
RUNTIME_DISTRIBUTIONS = (
    "PySide6",
    "PySide6_Essentials",
    "PySide6_Addons",
    "shiboken6",
    "pypdfium2",
    "pypdf",
    "reportlab",
    "charset-normalizer",
    "pillow",
    "pyinstaller",
)

#: A licence file is usually *named* like one...
LICENCE_FILE = re.compile(r"(?i)^(licen[cs]e|copying|notice|authors)")

#: ...but not always. pypdfium2 ships nineteen of them, named after the licence
#: rather than after the word — Apache-2.0.txt, BSD-3-Clause.txt, and one per
#: library PDFium builds in: freetype, icu, libjpeg_turbo, libpng, zlib and the
#: rest. Matching on the file name alone silently collected none of them, which
#: is precisely the failure this script exists to prevent, so a file sitting in
#: a directory that announces itself as licences counts too.
LICENCE_DIRECTORY = re.compile(r"(?i)^(licen[cs]es?|build_licenses)$")


def _distribution_licence_files(name: str) -> list[tuple[str, str]]:
    """Return ``(relative path, text)`` for every licence file a wheel ships.

    The path is kept relative to the dist-info directory rather than reduced
    to a bare file name. Wheels put licence files in both places — ``LICENSE``
    beside METADATA and ``licenses/LICENSE`` below it — and pip's own wheel
    ships twenty of them, one per vendored package, all named LICENSE. Writing
    by base name would have each overwrite the last and leave a tree that
    looks complete and is not, which is the one failure this script exists to
    prevent.
    """
    try:
        from importlib.metadata import distribution
    except ImportError:  # pragma: no cover - Python < 3.8 is not supported
        return []
    try:
        dist = distribution(name)
    except Exception:
        return []
    found = []
    for file in dist.files or ():
        parts = str(file).split("/")
        info = next(
            (i for i, part in enumerate(parts)
             if part.endswith((".dist-info", ".egg-info"))),
            None,
        )
        if info is None:
            continue
        below = parts[info + 1:]
        named = LICENCE_FILE.match(parts[-1])
        housed = any(LICENCE_DIRECTORY.match(part) for part in below[:-1])
        if not named and not housed:
            continue
        try:
            text = _read_text(file.locate())
        except Exception:
            # Loud on purpose. A licence file that cannot be read has to be
            # noticed, not quietly left out of the archive — a tree that looks
            # complete and is not is worse than one with an obvious hole.
            log.warning("Could not read the licence file %s", file, exc_info=True)
            continue
        found.append(("/".join(below), text))
    return _flatten(found)


def _read_text(path) -> str:
    """Read a licence file whatever it happens to be encoded in.

    Not everything is UTF-8. FreeType's licence, which arrives inside
    pypdfium2 because PDFium builds FreeType in, is Latin-1: the copyright
    sign in "copyright \xa9 The FreeType Project" is a single byte that UTF-8
    rejects outright. Reading it as UTF-8 raised, the exception handler
    dropped the file, and the tree came out with eighteen of pypdfium2's
    nineteen notices and no indication that one was missing.

    Latin-1 is the fallback because it cannot fail — every byte is a
    character — and it decodes exactly the Western European text these older
    files contain. The result is written back out as UTF-8.
    """
    data = path.read_bytes()
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def _flatten(files: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Drop the leading ``licenses/`` most wheels wrap their texts in.

    It is a packaging convention, not information, and keeping it produces
    licenses/python/pillow/licenses/LICENSE. Dropped only where it does not
    collide with a file already sitting at the top of dist-info — a wheel that
    ships both LICENSE and licenses/LICENSE keeps them apart.
    """
    names = {path for path, _ in files}
    flattened = []
    for path, text in files:
        head, _, rest = path.partition("/")
        if head == "licenses" and rest and rest not in names:
            path = rest
        flattened.append((path, text))
    return flattened


def _system_packages(binaries) -> list[str]:
    """Package names owning the system libraries PyInstaller collected.

    Only meaningful on a Debian-family build machine. Everywhere else this
    returns nothing and the caller records why.
    """
    if not shutil.which("dpkg-query"):
        return []
    packages = set()
    for entry in binaries:
        source = str(entry[1])
        # Wheel-vendored libraries live under site-packages; only the ones
        # taken from the system's own lib directories have an owning package.
        if "site-packages" in source or not os.path.exists(source):
            continue
        found = subprocess.run(
            ["dpkg-query", "-S", os.path.realpath(source)],
            capture_output=True,
            text=True,
        )
        if found.returncode == 0 and found.stdout.strip():
            packages.add(found.stdout.split(":")[0].strip())
    return sorted(packages)


def collect(repo: str, staging: str, binaries=()) -> str:
    """Build the licence tree under ``staging`` and return its path."""
    if os.path.isdir(staging):
        shutil.rmtree(staging)
    os.makedirs(staging)

    index = [
        "# Licences of the software in this package",
        "",
        "Orion itself is licensed AGPL-3.0-or-later; the full text is in",
        "`Orion-LICENSE.txt`. A commercial licence, without the AGPL's",
        "obligations, is available separately — see the project's",
        "COMMERCIAL-LICENSE.md.",
        "",
        "Everything else in this package was written by other people, under",
        "their own terms. This directory holds those terms. The inventory of",
        "which binary belongs to which project is THIRD-PARTY-LICENSES.md in",
        "the Orion repository.",
        "",
        "## Orion",
        "",
        "- `Orion-LICENSE.txt` — GNU Affero General Public License v3.0",
        "",
    ]

    shutil.copyfile(
        os.path.join(repo, "LICENSE"), os.path.join(staging, "Orion-LICENSE.txt")
    )

    index += ["## Python packages", ""]
    python_dir = os.path.join(staging, "python")
    os.makedirs(python_dir)
    for name in RUNTIME_DISTRIBUTIONS:
        files = _distribution_licence_files(name)
        supplied = SUPPLIED_TEXTS.get(name, ())
        if not files and not supplied:
            index.append(f"- **{name}** — no licence file found; see the inventory")
            continue
        target = os.path.join(python_dir, name)
        os.makedirs(target, exist_ok=True)
        written = []
        for filename, text in files:
            destination = os.path.join(target, *filename.split("/"))
            os.makedirs(os.path.dirname(destination), exist_ok=True)
            with open(destination, "w", encoding="utf-8") as out:
                out.write(text)
            written.append(filename)
        for canonical in supplied:
            shutil.copyfile(
                os.path.join(repo, "licenses", canonical),
                os.path.join(target, canonical),
            )
            written.append(f"{canonical} (supplied — the wheel ships none)")
        index.append(f"- **{name}** — {', '.join(written)}")
    index.append("")

    packages = _system_packages(binaries)
    index += ["## System libraries collected at build time", ""]
    if packages:
        system_dir = os.path.join(staging, "system")
        os.makedirs(system_dir)
        for package in packages:
            source = f"/usr/share/doc/{package.split(':')[0]}/copyright"
            if not os.path.exists(source):
                continue
            shutil.copyfile(source, os.path.join(system_dir, f"{package}.txt"))
        index.append(
            f"The build machine's copyright records for {len(packages)} packages "
            "are in `system/`."
        )
    else:
        index.append(
            "This build was not produced on a Debian-family machine, so there "
            "are no package copyright records to copy. The libraries collected "
            "from the platform on this build are the Microsoft Visual C++ and "
            "Universal CRT runtime (redistributable under Microsoft's own "
            "terms, not an open-source licence), and the OpenSSL and libffi "
            "builds that ship inside python.org's distributions — Apache-2.0 "
            "and MIT respectively; `Apache-2.0.txt` is included here."
        )
        shutil.copyfile(
            os.path.join(repo, "licenses", "Apache-2.0.txt"),
            os.path.join(staging, "Apache-2.0.txt"),
        )
    index += [
        "",
        "## Relinking",
        "",
        "Qt is used under the LGPL-3.0. It is unmodified, and it is linked",
        "dynamically: the Qt libraries in this package are separate files, so",
        "they can be replaced with a modified build of the same version",
        "without rebuilding Orion. `python/PySide6/` holds LGPL-3.0 and the",
        "GPL-3.0 text it builds on. The same applies to the LGPL-2.1",
        "libraries collected from the build machine.",
        "",
    ]

    with open(os.path.join(staging, "README.md"), "w", encoding="utf-8") as out:
        out.write("\n".join(index))
    return staging


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    staging = argv[0] if argv else os.path.join(repo, "build", "licenses")
    collect(repo, staging)
    for directory, _subdirs, files in os.walk(staging):
        for name in sorted(files):
            path = os.path.join(directory, name)
            print(f"{os.path.getsize(path):>8}  {os.path.relpath(path, staging)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
