#!/usr/bin/env python
# Orion — PDF Editor for Desktop
# Copyright (C) 2026 Marco Lombardo
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# Distributed WITHOUT ANY WARRANTY; see LICENSE for the full terms.
# A commercial licence, without the AGPL's obligations, is available for use
# in proprietary or closed-source products — see COMMERCIAL-LICENSE.md.

"""Inventory the third-party code Orion actually ships, and what licenses it.

THIRD-PARTY-LICENSES.md is generated from this script rather than written by
hand, because a hand-written list of a PyInstaller bundle is wrong the day
after it is written: PyInstaller collects whatever the build machine's linker
resolved, so the list changes when the runner image changes, not when anyone
edits the repository.

The script walks an *extracted* release bundle — the artefact users download,
not the build tree — and attributes every native library in it to the thing
that put it there:

  wheel   a Python wheel vendored it (PySide6, PyMuPDF, Pillow)
  cpython the interpreter and its stdlib extension modules
  system  PyInstaller collected it from the build machine's own libraries

Only the third class needs looking up, and on a Debian-family host dpkg knows
the answer: which package owns the file, and what that package's copyright
file says.

Two warnings about that lookup, both learned the hard way and both the reason
this script exists instead of a one-line shell pipeline.

The first: a debian/copyright file lists every licence appearing anywhere in
the *source* package, including test fixtures and build scripts. Reporting
that union is alarmist nonsense — it makes GLib look like it has a GPL-2+
term. What governs a shipped shared library is the licence of that library's
own sources, which in a machine-readable copyright file is the stanza whose
``Files:`` pattern covers them.

The second: even the ``Files: *`` stanza is not that licence when the source
package builds several libraries under different terms. util-linux's default
stanza says GPL-2+, but the libraries Orion ships from it — libblkid, libmount,
libuuid — carry LGPL-2.1+, LGPL-2.1+ and BSD-3-clause in their own stanzas.
Taking the default would have published three wrong answers.

So: the default stanza is a starting point, REVIEWED below is where a human
looked at the sub-stanza and recorded what it actually said, and anything the
script cannot resolve is reported as unresolved rather than guessed. A gap you
can see is worth more than a plausible-looking entry that is wrong.

Usage:

    python tools/licence_inventory.py --bundle linux=/path/to/extracted/Orion
    python tools/licence_inventory.py --bundle linux=... --json out.json

Run it on a host of the same family as the release runner (Ubuntu, for the
Linux bundle) — otherwise the system-library lookup has nothing to consult and
every such library is reported unresolved.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field

#: Wheel-vendored libraries carry an eight-hex-digit tag inserted by auditwheel
#: so two wheels can vendor different builds of the same library without
#: colliding. The tag is how they are told apart from the system copies.
VENDOR_TAG = re.compile(r"-[0-9a-f]{8}\.(?:so|dylib)")

#: Where each origin's licence terms are stated, for the report to cite.
ORIGIN_SOURCES = {
    "wheel": "the wheel's own distribution metadata",
    "cpython": "the Python Software Foundation License, version 2",
    "system": "the build machine's package copyright records",
}

#: What each wheel's own metadata declares, copied from the ``License`` and
#: ``License-Expression`` fields of the installed distributions rather than
#: from anyone's memory of what these projects are licensed under. PySide6
#: states no commercial term because the PyPI wheels *are* the open-source
#: build; a Qt commercial licence is bought from The Qt Company separately and
#: replaces this line for whoever holds one.
WHEEL_LICENCES = {
    "PySide6 / Qt 6": "LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only",
    "PySide6 / Qt 6 (ICU)": "Unicode-3.0 (vendored in the PySide6 wheel)",
    "PyMuPDF / MuPDF": "AGPL-3.0-only OR Artifex-Commercial",
    "Pillow (vendored native libraries)": "MIT-CMU, plus the per-library terms in Pillow's LICENSE",
}

#: Sub-library licences a human verified by reading the stanza named in
#: ``evidence``, because the copyright file's default stanza does not describe
#: the library Orion actually ships. Keyed by binary package name.
REVIEWED: dict[str, tuple[str, str]] = {
    "libblkid1": ("LGPL-2.1-or-later", "Files: libblkid/* — default stanza says GPL-2+"),
    "libmount1": ("LGPL-2.1-or-later", "Files: libmount/* — default stanza says GPL-2+"),
    "libuuid1": ("BSD-3-Clause", "Files: libuuid/* — default stanza says GPL-2+"),
    "libkeyutils1": ("LGPL-2.0-or-later", "Files: keyutils.* — default stanza says GPL-2+"),
    "libbsd0": (
        "BSD-3-Clause AND BSD-2-Clause AND ISC",
        "per-file stanzas, all permissive BSD/ISC variants",
    ),
    "libmd0": (
        "BSD-3-Clause AND BSD-2-Clause AND ISC",
        "per-file stanzas, all permissive BSD/ISC variants",
    ),
    "libjpeg-turbo8": (
        "IJG AND BSD-3-Clause AND Zlib",
        "per-file stanzas; no Files: * stanza exists",
    ),
}

#: Debian's copyright files use their own licence shorthand. Translating it to
#: SPDX makes the report comparable with the wheel metadata, which already
#: speaks SPDX — but only where the translation is unambiguous. Anything not
#: listed here is reported exactly as Debian wrote it rather than guessed at.
SPDX = {
    "Expat": "MIT",
    "MIT/X": "MIT",
    "MIT/X11": "MIT",
    "MIT/X Consortium License": "MIT",
    "GPL-2": "GPL-2.0-only",
    "GPL-2+": "GPL-2.0-or-later",
    "LGPL-2+": "LGPL-2.0-or-later",
    "LGPL-2.1+": "LGPL-2.1-or-later",
    "BSD-2-clause": "BSD-2-Clause",
    "BSD-3-clause": "BSD-3-Clause",
    "BSD-3-clause or GPL-2": "BSD-3-Clause OR GPL-2.0-only",
    "BSD-variant": "bzip2-1.0.6",
    "PD": "public domain",
    "public-domain": "public domain",
    "libpng": "Libpng",
    "FTL": "FTL (FreeType License)",
    "LGPL-2.1+ or MPL-1.1 or GPL-2+": "LGPL-2.1-or-later OR MPL-1.1 OR GPL-2.0-or-later",
    "GPL-2+ or AFL-2.1, and Expat and Tcl-BSDish": "AFL-2.1 OR GPL-2.0-or-later",
    "BSD-3-clause-Cambridge with BINARY LIBRARY-LIKE PACKAGES exception": (
        "BSD-3-Clause (PCRE2 variant)"
    ),
}

#: Resolutions a human should not take on trust. These resolve to *something*,
#: but the something is disputed or unrepresentative, and the report says so
#: instead of presenting a clean answer that might be wrong.
FLAGGED = {
    "libcom-err2": (
        "Ubuntu's copyright file has no stanza for lib/et, so the GPL-2 default "
        "applies by omission; upstream e2fsprogs licenses com_err under MIT. "
        "Confirm before relying on either reading."
    ),
}

#: Packages whose copyright file is free-form prose rather than machine
#: readable, read once by a human and recorded here with the phrase that
#: identifies the licence. Without this the entire X.Org stack is unresolved.
FREEFORM: dict[str, tuple[str, str]] = {
    "libfontconfig1": ("MIT", "'Permission to use, copy, modify' — Keith Packard, fontconfig"),
    "libgcc-s1": (
        "GPL-3.0-or-later WITH GCC-exception-3.1",
        "'version 3.1 of the GCC Runtime Library Exception'",
    ),
    "libstdc++6": (
        "GPL-3.0-or-later WITH GCC-exception-3.1",
        "'version 3.1 of the GCC Runtime Library Exception'",
    ),
    "libgcrypt20": ("LGPL-2.1-or-later", "'Lesser General Public License', version 2.1"),
    "libgssapi-krb5-2": ("MIT", "MIT Kerberos 5 'permission to use, copy, modify'"),
    "libk5crypto3": ("MIT", "MIT Kerberos 5 'permission to use, copy, modify'"),
    "libkrb5-3": ("MIT", "MIT Kerberos 5 'permission to use, copy, modify'"),
    "libkrb5support0": ("MIT", "MIT Kerberos 5 'permission to use, copy, modify'"),
    "libpixman-1-0": ("MIT", "'MIT license'"),
}

#: On macOS, delocate rewrites Pillow's vendored libraries without the hex tag
#: auditwheel adds on Linux, and PyInstaller then hoists them out of
#: PIL/.dylibs into Frameworks/ and Resources/. Nothing in the path or the name
#: says "Pillow" any more, so they are recognised by name.
PILLOW_DARWIN = {
    "libXau", "libavif", "libjpeg", "liblcms2", "liblzma", "libopenjp2",
    "libsharpyuv", "libtiff", "libwebp", "libwebpdemux", "libwebpmux",
    "libxcb", "libz",
}

#: Binaries that come from the platform rather than from a package manager, so
#: dpkg has nothing to say about them. The Windows bundle is almost entirely
#: this: the Universal CRT forwarders and the Visual C++ runtime, which
#: Microsoft licenses for redistribution under its own terms and not under any
#: open-source licence, plus the OpenSSL and libffi builds that ship inside
#: python.org's own Windows and macOS distributions.
PLATFORM_COMPONENTS: list[tuple[re.Pattern[str], str, str]] = [
    (
        re.compile(r"^(api-ms-win-|ucrtbase\.dll$|VCRUNTIME140|MSVCP140)", re.I),
        "Microsoft Visual C++ / Universal CRT runtime",
        "Microsoft redistributable terms — not an open-source licence",
    ),
    (re.compile(r"^lib(ssl|crypto)[-.]", re.I), "OpenSSL", "Apache-2.0"),
    (re.compile(r"^libffi[-.]", re.I), "libffi", "MIT"),
]

#: The X.Org and XCB stacks: dozens of packages, one licence between them, all
#: with free-form copyright files. Listing each by hand would be noise.
XORG_MIT = "MIT"
XORG_EVIDENCE = "X.Org / XCB standard copyright — MIT/X11 permission notice"


@dataclass
class Entry:
    """One native binary in the bundle and what is known about its licence."""

    path: str
    origin: str
    component: str
    licence: str | None = None
    evidence: str | None = None
    flag: str | None = None

    @property
    def resolved(self) -> bool:
        return self.licence is not None


@dataclass
class Inventory:
    platform: str
    root: str
    entries: list[Entry] = field(default_factory=list)

    @property
    def unresolved(self) -> list[Entry]:
        return [e for e in self.entries if not e.resolved]


#: A macOS framework's actual Mach-O binary has no extension at all: it is
#: Foo.framework/Versions/A/Foo. Matching only on extensions silently skips
#: every Qt module on macOS, which is most of what the bundle is.
FRAMEWORK_BINARY = re.compile(r"(?:^|/)(?P<name>[^/]+)\.framework/Versions/[^/]+/(?P=name)$")


def is_native(rel: str) -> bool:
    """True for anything the loader maps as machine code at run time."""
    name = os.path.basename(rel)
    return (
        ".so" in name
        or name.endswith((".dylib", ".dll", ".pyd"))
        or FRAMEWORK_BINARY.search(rel.replace("\\", "/")) is not None
    )


def classify(rel: str) -> tuple[str, str] | None:
    """Attribute one bundle-relative path to the component that shipped it.

    Returns ``(origin, component)``, or None when the path is not a native
    binary. Order matters: the Qt wheel vendors its own ICU, and PyInstaller
    hoists it next to the system libraries where it would otherwise be
    mistaken for one.
    """
    if not is_native(rel):
        return None
    base = os.path.basename(rel)
    lower = rel.replace("\\", "/").lower()

    if lower.startswith("pymupdf/") or base.startswith(("libmupdf", "_mupdf")):
        return "wheel", "PyMuPDF / MuPDF"
    if (
        lower.startswith(("pyside6/", "shiboken6/"))
        or base.startswith(("libQt6", "Qt6", "libpyside", "libshiboken", "shiboken6"))
        # Qt ships as frameworks on macOS: QtCore.framework/Versions/A/QtCore.
        or (".framework/versions/" in lower and base.startswith("Qt"))
    ):
        return "wheel", "PySide6 / Qt 6"
    if base.startswith("libicu"):
        # Vendored inside the PySide6 wheel (PySide6/Qt/lib), not a system copy.
        return "wheel", "PySide6 / Qt 6 (ICU)"
    if (
        lower.startswith(("pil/", "pillow.libs/"))
        or "/pil/" in lower
        or VENDOR_TAG.search(base)
        # macOS only: on Linux these same stems name the *system* copies
        # (libjpeg.so.8 is libjpeg-turbo8), and Pillow's are hex-tagged.
        or (base.endswith(".dylib") and base.split(".")[0] in PILLOW_DARWIN)
    ):
        return "wheel", "Pillow (vendored native libraries)"
    if (
        base.startswith(("libpython3", "python3"))
        or "cpython-3" in base
        # A .pyd sitting directly in _internal is a stdlib extension module;
        # the ones belonging to a package sit inside that package's directory.
        or (base.endswith(".pyd") and "/" not in lower)
        or lower.startswith("python.framework/")
    ):
        return "cpython", "CPython"
    return "system", ""


def dpkg_owner(basename: str) -> str | None:
    """Ask dpkg which package owns a library, trying shorter sonames first."""
    candidates = [basename]
    trimmed = re.match(r"^(.*\.so\.\d+)\.", basename)
    if trimmed:
        candidates.append(trimmed.group(1))
    for candidate in candidates:
        for prefix in ("/usr/lib/x86_64-linux-gnu/", "/lib/x86_64-linux-gnu/", "/usr/lib/"):
            found = subprocess.run(
                ["dpkg-query", "-S", prefix + candidate],
                capture_output=True,
                text=True,
            )
            if found.returncode == 0 and found.stdout.strip():
                return found.stdout.split(":")[0].strip()
    return None


def default_stanza_licence(package: str) -> tuple[str | None, bool]:
    """The ``Files: *`` licence from a package's copyright file.

    Returns ``(licence, machine_readable)``. A free-form copyright file yields
    ``(None, False)`` — it needs a human, which is what FREEFORM records.
    """
    path = f"/usr/share/doc/{package.split(':')[0]}/copyright"
    if not os.path.exists(path):
        return None, False
    with open(path, encoding="utf-8", errors="replace") as handle:
        text = handle.read()
    if "Format:" not in text.split("\n\n")[0]:
        return None, False
    for stanza in text.split("\n\n"):
        files = licence = None
        for line in stanza.splitlines():
            if line.startswith("Files:"):
                files = line[len("Files:"):].strip()
            elif line.startswith("License:") and files is not None:
                licence = line[len("License:"):].strip()
                break
        if files == "*" and licence:
            return licence, True
    return None, True


def resolve_system(basename: str) -> tuple[str, str | None, str | None]:
    """Resolve one system library to ``(package, licence, evidence)``."""
    package = dpkg_owner(basename)
    if package is None:
        for pattern, component, licence in PLATFORM_COMPONENTS:
            if pattern.match(basename):
                return component, licence, "shipped by the platform, not by a package manager"
        return "unknown", None, None
    if package in REVIEWED:
        licence, evidence = REVIEWED[package]
        return package, licence, f"reviewed: {evidence}"
    if package in FREEFORM:
        licence, evidence = FREEFORM[package]
        return package, licence, f"free-form copyright: {evidence}"
    if package.startswith(("libx", "libxcb")) or package.startswith("libxkbcommon"):
        return package, XORG_MIT, f"free-form copyright: {XORG_EVIDENCE}"
    licence, machine_readable = default_stanza_licence(package)
    if licence:
        return package, SPDX.get(licence, licence), "debian/copyright, Files: * stanza"
    if not machine_readable:
        return package, None, "free-form copyright — needs review"
    return package, None, "no Files: * stanza — needs review"


def take_inventory(platform: str, root: str) -> Inventory:
    inventory = Inventory(platform=platform, root=root)
    for directory, _subdirs, files in os.walk(root):
        for name in sorted(files):
            rel = os.path.relpath(os.path.join(directory, name), root)
            # PyInstaller lays the bundle out differently per platform:
            # _internal/ on Windows and Linux, Contents/Frameworks and
            # Contents/Resources inside an .app on macOS. Attribution rules
            # are written against the path *below* that prefix, so strip it.
            inner = rel.split("_internal/", 1)[-1]
            for prefix in ("Contents/Frameworks/", "Contents/Resources/", "Contents/MacOS/"):
                inner = inner.split(prefix, 1)[-1]
            classified = classify(inner)
            if classified is None:
                continue
            origin, component = classified
            if origin == "system":
                package, licence, evidence = resolve_system(os.path.basename(rel))
                inventory.entries.append(
                    Entry(rel, origin, package, licence, evidence, FLAGGED.get(package))
                )
            else:
                if origin == "cpython":
                    licence = "PSF-2.0"
                else:
                    licence = WHEEL_LICENCES.get(component)
                inventory.entries.append(
                    Entry(rel, origin, component, licence, ORIGIN_SOURCES[origin])
                )
    inventory.entries.sort(key=lambda e: (e.origin, e.component, e.path))
    return inventory


def summarise(inventory: Inventory) -> None:
    by_origin: dict[str, int] = {}
    components: dict[tuple[str, str], list[Entry]] = {}
    for entry in inventory.entries:
        by_origin[entry.origin] = by_origin.get(entry.origin, 0) + 1
        components.setdefault((entry.origin, entry.component), []).append(entry)

    print(f"# {inventory.platform}: {len(inventory.entries)} native binaries")
    for origin, count in sorted(by_origin.items()):
        print(f"  {origin:8} {count}")
    print()
    for (origin, component), entries in sorted(components.items()):
        licences = sorted({e.licence or "UNRESOLVED" for e in entries})
        print(f"{origin:8} {component:24} {len(entries):3}  {', '.join(licences)}")
    flagged = sorted({(e.component, e.flag) for e in inventory.entries if e.flag})
    if flagged:
        print("\nda verificare:")
        for component, note in flagged:
            print(f"  {component}: {note}")
    if inventory.unresolved:
        print(f"\nnon risolte: {len(inventory.unresolved)}")
        for entry in inventory.unresolved:
            print(f"  {entry.path}  ({entry.component})  {entry.evidence}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--bundle",
        action="append",
        required=True,
        metavar="PLATFORM=PATH",
        help="an extracted release bundle, e.g. linux=/tmp/Orion",
    )
    parser.add_argument("--json", help="write the full inventory here")
    args = parser.parse_args(argv)

    inventories = []
    for spec in args.bundle:
        if "=" not in spec:
            parser.error(f"--bundle wants PLATFORM=PATH, got {spec!r}")
        platform, path = spec.split("=", 1)
        if not os.path.isdir(path):
            parser.error(f"not a directory: {path}")
        inventory = take_inventory(platform, path)
        summarise(inventory)
        print()
        inventories.append(inventory)

    if args.json:
        payload = {
            inv.platform: [vars(e) for e in inv.entries] for inv in inventories
        }
        with open(args.json, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=1, sort_keys=True)
        print(f"scritto {args.json}")

    return 1 if any(inv.unresolved for inv in inventories) else 0


if __name__ == "__main__":
    sys.exit(main())
