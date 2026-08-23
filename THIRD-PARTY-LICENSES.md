# Third-party licences

Orion is licensed **AGPL-3.0-or-later** (see [LICENSE](LICENSE)), with a
commercial licence available separately (see
[COMMERCIAL-LICENSE.md](COMMERCIAL-LICENSE.md)). That covers the code in this
repository. It does not cover the code Orion is built on, and a downloadable
release is mostly that other code: across the three v1.0.0 archives there are
519 native binaries — 243 on Linux, 156 on macOS, 120 on Windows — and not one
of them was written for Orion. Orion's own code travels through them as Python
bytecode.

This file is the inventory of what those binaries are and what licenses them.

## How this was produced

It was generated, not written from memory, by
[`tools/licence_inventory.py`](tools/licence_inventory.py) run against the
**extracted release archives** — the files users actually download — and not
against the build tree. That distinction matters: PyInstaller collects whatever
the build machine's linker resolved, so the contents change when the runner
image changes, not when someone edits this repository. A hand-maintained list
would be stale within one CI image bump and nobody would notice.

Every entry traces to a machine-readable source:

- **Python packages** — the `License` and `License-Expression` fields of the
  installed distribution metadata.
- **Libraries collected from the Linux build machine** — the owning package
  from `dpkg-query`, and that package's `debian/copyright`.
- **Libraries the platform supplies** (the Windows CRT, the OpenSSL that ships
  inside python.org's builds) — identified by name, since no package manager
  owns them.

Two traps in that lookup are worth stating, because both produced wrong answers
before they were caught, and both are handled in the script rather than
papered over:

A `debian/copyright` file enumerates every licence appearing anywhere in the
*source* package, test fixtures and build scripts included. Reporting that
union makes GLib look like it carries a GPL-2+ term. What governs a shipped
shared library is the licence of that library's own sources.

Even the default `Files: *` stanza is not that licence when one source package
builds several libraries under different terms. util-linux's default stanza
says GPL-2+, but the three libraries Orion ships from it — `libblkid`,
`libmount`, `libuuid` — carry LGPL-2.1+, LGPL-2.1+ and BSD-3-Clause in their
own stanzas. Taking the default would have published three wrong answers here.
Those, and every other case where a human had to read the sub-stanza, are
recorded in the script's `REVIEWED` table with the stanza that was read.

The Linux lookup was run on Ubuntu 24.04 — the same image family as the
`ubuntu-latest` release runner. Run on anything else it has nothing to consult
and reports the system libraries as unresolved rather than guessing.

## What Orion depends on directly

Four packages, declared in [`requirements.txt`](requirements.txt), with the
licence each one's own metadata states:

| Package | Version built | Licence (from its metadata) | What Orion uses it for |
|---|---|---|---|
| PySide6 | 6.11.2 | `LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only` | the entire user interface |
| PyMuPDF | 1.28.2 | `AGPL-3.0-only OR Artifex-Commercial` | rendering, text extraction, writing objects and annotations |
| pypdf | 6.16.1 | `BSD-3-Clause` | page-level operations: merge, split, extract, reorder |
| Pillow | 12.3.0 | `MIT-CMU` | decoding PNG, JPEG and WEBP before they are placed |

pypdf and Pillow impose nothing beyond attribution. The other two are the
whole of Orion's licensing problem, and they are treated separately below.

Note what the PySide6 metadata does **not** say: there is no commercial option
in it. The PyPI wheels *are* the open-source build of Qt. A Qt commercial
licence is bought from The Qt Company and replaces those terms for whoever
holds one; it is not something a wheel can grant.

## The components that actually constrain redistribution

Most of the inventory below is MIT, BSD and ISC — attribution and nothing
more. Five things are not, and these are the only ones worth a decision:

**MuPDF, via PyMuPDF — `AGPL-3.0-only OR Artifex-Commercial`.** This is the
structural blocker for Orion's Commercial and Redistribution tiers, and no
amount of packaging work changes it. Orion cannot sublicense Artifex's code:
a customer who buys a commercial Orion licence still receives AGPL MuPDF, and
the AGPL's obligations still attach to them. The only two real exits are
replacing the engine (pypdfium2 / pikepdf / reportlab are permissively licensed
and cover the same ground, at roughly 1,270 lines of work across five modules)
or negotiating an OEM/redistribution agreement with Artifex.

**Qt, via PySide6 — LGPL-3.0.** Distributable inside a closed product, but not
for free: the LGPL requires that a recipient be able to relink the application
against a modified Qt, that the licence text and a notice of Qt's use be
supplied, and that no further restriction be imposed on Qt itself. Orion links
Qt dynamically and ships it unmodified, which is the easy case — but the
notice and licence-text obligations are currently **not met** in the shipped
archives. See "Known gaps" below.

**The LGPL-2.1 system libraries** — GLib and its family, libgcrypt,
libgpg-error, libsystemd, libfribidi, libgraphite2, libblkid, libmount,
libkeyutils. Same shape of obligation as Qt, same easy case (dynamic,
unmodified), same missing notice.

**The GCC runtime** — `libgcc_s` and `libstdc++`, GPL-3.0-or-later **with the
GCC Runtime Library Exception 3.1**. The exception is what makes this
distributable at all; without it a GPL-3 library would sit in the middle of
every build. Nothing to do here, but it should not be mistaken for a permissive
licence.

**The Microsoft Visual C++ and Universal CRT runtime** (Windows only, 45
files) — not open source at all. It is redistributable under Microsoft's own
redistributable terms, which is a different legal basis from every other entry
in this document and carries its own conditions.

## What was deliberately removed

Two things were dropped from the bundle for licensing reasons, and their
absence from the published v1.0.0 archives is verified:

- **Qt Virtual Keyboard** — GPLv3-only, not LGPL like the rest of Qt. It was
  shipping by accident as part of the default PySide6 collection. A GPLv3
  module inside a product offered under a commercial licence is a direct
  contradiction, so it and the `platforminputcontexts` plugin that loads it are
  filtered out in [`orion.spec`](orion.spec).
- **The GTK platform theme and its stack** — `qgtk3` plus GTK, GDK, ATK,
  Pango, Cairo and friends. Unused by Orion, and it dragged an LGPL stack into
  the bundle for no benefit.

Both exclusions are pinned by [`tests/test_packaging.py`](tests/test_packaging.py)
so they cannot silently come back.

## Full inventory

Counts are files, not projects: one project usually contributes several
binaries. "Evidence" names where the licence came from, so any line here can
be re-checked rather than taken on trust.

### Linux (`Orion-1.0.0-linux-x64.tar.gz`) — 243 native binaries

| Component | Files | Licence | Evidence |
|---|--:|---|---|
| `CPython` | 50 | PSF-2.0 | the Python Software Foundation License, version 2 |
| `Pillow (vendored native libraries)` | 32 | MIT-CMU, plus the per-library terms in Pillow's LICENSE | the wheel's own distribution metadata |
| `PyMuPDF / MuPDF` | 6 | AGPL-3.0-only OR Artifex-Commercial | the wheel's own distribution metadata |
| `PySide6 / Qt 6` | 79 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only | the wheel's own distribution metadata |
| `PySide6 / Qt 6 (ICU)` | 3 | Unicode-3.0 (vendored in the PySide6 wheel) | the wheel's own distribution metadata |
| `libblkid1` | 1 | LGPL-2.1-or-later | reviewed: Files: libblkid/* — default stanza says GPL-2+ |
| `libbrotli1` | 2 | MIT | debian/copyright, Files: * stanza |
| `libbsd0` | 1 | BSD-3-Clause AND BSD-2-Clause AND ISC | reviewed: per-file stanzas, all permissive BSD/ISC variants |
| `libbz2-1.0` | 1 | bzip2-1.0.6 | debian/copyright, Files: * stanza |
| `libcap2` | 1 | BSD-3-Clause OR GPL-2.0-only | debian/copyright, Files: * stanza |
| `libcom-err2` | 1 | GPL-2.0-only | debian/copyright, Files: * stanza |
| `libdbus-1-3` | 1 | AFL-2.1 OR GPL-2.0-or-later | debian/copyright, Files: * stanza |
| `libexpat1` | 1 | MIT | debian/copyright, Files: * stanza |
| `libffi8` | 1 | MIT | debian/copyright, Files: * stanza |
| `libfontconfig1` | 1 | MIT | free-form copyright: 'Permission to use, copy, modify' — Keith Packard, fontconfig |
| `libfreetype6` | 1 | FTL (FreeType License) | debian/copyright, Files: * stanza |
| `libfribidi0` | 1 | LGPL-2.1-or-later | debian/copyright, Files: * stanza |
| `libgcc-s1` | 1 | GPL-3.0-or-later WITH GCC-exception-3.1 | free-form copyright: 'version 3.1 of the GCC Runtime Library Exception' |
| `libgcrypt20` | 1 | LGPL-2.1-or-later | free-form copyright: 'Lesser General Public License', version 2.1 |
| `libglib2.0-0t64` | 5 | LGPL-2.1-or-later | debian/copyright, Files: * stanza |
| `libgpg-error0` | 1 | LGPL-2.1-or-later | debian/copyright, Files: * stanza |
| `libgraphite2-3` | 1 | LGPL-2.1-or-later OR MPL-1.1 OR GPL-2.0-or-later | debian/copyright, Files: * stanza |
| `libgssapi-krb5-2` | 1 | MIT | free-form copyright: MIT Kerberos 5 'permission to use, copy, modify' |
| `libharfbuzz0b` | 1 | MIT | debian/copyright, Files: * stanza |
| `libjpeg-turbo8` | 1 | IJG AND BSD-3-Clause AND Zlib | reviewed: per-file stanzas; no Files: * stanza exists |
| `libk5crypto3` | 1 | MIT | free-form copyright: MIT Kerberos 5 'permission to use, copy, modify' |
| `libkeyutils1` | 1 | LGPL-2.0-or-later | reviewed: Files: keyutils.* — default stanza says GPL-2+ |
| `libkrb5-3` | 1 | MIT | free-form copyright: MIT Kerberos 5 'permission to use, copy, modify' |
| `libkrb5support0` | 1 | MIT | free-form copyright: MIT Kerberos 5 'permission to use, copy, modify' |
| `liblz4-1` | 1 | BSD-2-Clause | debian/copyright, Files: * stanza |
| `liblzma5` | 1 | public domain | debian/copyright, Files: * stanza |
| `libmd0` | 1 | BSD-3-Clause AND BSD-2-Clause AND ISC | reviewed: per-file stanzas, all permissive BSD/ISC variants |
| `libmount1` | 1 | LGPL-2.1-or-later | reviewed: Files: libmount/* — default stanza says GPL-2+ |
| `libpcre2-8-0` | 1 | BSD-3-Clause (PCRE2 variant) | debian/copyright, Files: * stanza |
| `libpixman-1-0` | 1 | MIT | free-form copyright: 'MIT license' |
| `libpng16-16t64` | 1 | Libpng | debian/copyright, Files: * stanza |
| `libselinux1` | 1 | public domain | debian/copyright, Files: * stanza |
| `libssl3t64` | 2 | Apache-2.0 | debian/copyright, Files: * stanza |
| `libstdc++6` | 1 | GPL-3.0-or-later WITH GCC-exception-3.1 | free-form copyright: 'version 3.1 of the GCC Runtime Library Exception' |
| `libsystemd0` | 1 | LGPL-2.1-or-later | debian/copyright, Files: * stanza |
| `libuuid1` | 1 | BSD-3-Clause | reviewed: Files: libuuid/* — default stanza says GPL-2+ |
| `libx11-6` | 1 | MIT | free-form copyright: X.Org / XCB standard copyright — MIT/X11 permission notice |
| `libx11-xcb1` | 1 | MIT | free-form copyright: X.Org / XCB standard copyright — MIT/X11 permission notice |
| `libxau6` | 1 | MIT | free-form copyright: X.Org / XCB standard copyright — MIT/X11 permission notice |
| `libxcb-cursor0` | 1 | MIT | free-form copyright: X.Org / XCB standard copyright — MIT/X11 permission notice |
| `libxcb-glx0` | 1 | MIT | free-form copyright: X.Org / XCB standard copyright — MIT/X11 permission notice |
| `libxcb-icccm4` | 1 | MIT | free-form copyright: X.Org / XCB standard copyright — MIT/X11 permission notice |
| `libxcb-image0` | 1 | MIT | free-form copyright: X.Org / XCB standard copyright — MIT/X11 permission notice |
| `libxcb-keysyms1` | 1 | MIT | free-form copyright: X.Org / XCB standard copyright — MIT/X11 permission notice |
| `libxcb-randr0` | 1 | MIT | free-form copyright: X.Org / XCB standard copyright — MIT/X11 permission notice |
| `libxcb-render-util0` | 1 | MIT | free-form copyright: X.Org / XCB standard copyright — MIT/X11 permission notice |
| `libxcb-render0` | 1 | MIT | free-form copyright: X.Org / XCB standard copyright — MIT/X11 permission notice |
| `libxcb-shape0` | 1 | MIT | free-form copyright: X.Org / XCB standard copyright — MIT/X11 permission notice |
| `libxcb-shm0` | 1 | MIT | free-form copyright: X.Org / XCB standard copyright — MIT/X11 permission notice |
| `libxcb-sync1` | 1 | MIT | free-form copyright: X.Org / XCB standard copyright — MIT/X11 permission notice |
| `libxcb-util1` | 1 | MIT | free-form copyright: X.Org / XCB standard copyright — MIT/X11 permission notice |
| `libxcb-xfixes0` | 1 | MIT | free-form copyright: X.Org / XCB standard copyright — MIT/X11 permission notice |
| `libxcb-xkb1` | 1 | MIT | free-form copyright: X.Org / XCB standard copyright — MIT/X11 permission notice |
| `libxcomposite1` | 1 | MIT | free-form copyright: X.Org / XCB standard copyright — MIT/X11 permission notice |
| `libxcursor1` | 1 | MIT | free-form copyright: X.Org / XCB standard copyright — MIT/X11 permission notice |
| `libxdamage1` | 1 | MIT | free-form copyright: X.Org / XCB standard copyright — MIT/X11 permission notice |
| `libxdmcp6` | 1 | MIT | free-form copyright: X.Org / XCB standard copyright — MIT/X11 permission notice |
| `libxext6` | 1 | MIT | free-form copyright: X.Org / XCB standard copyright — MIT/X11 permission notice |
| `libxfixes3` | 1 | MIT | free-form copyright: X.Org / XCB standard copyright — MIT/X11 permission notice |
| `libxi6` | 1 | MIT | free-form copyright: X.Org / XCB standard copyright — MIT/X11 permission notice |
| `libxinerama1` | 1 | MIT | free-form copyright: X.Org / XCB standard copyright — MIT/X11 permission notice |
| `libxkbcommon-x11-0` | 1 | MIT | free-form copyright: X.Org / XCB standard copyright — MIT/X11 permission notice |
| `libxkbcommon0` | 1 | MIT | free-form copyright: X.Org / XCB standard copyright — MIT/X11 permission notice |
| `libxrandr2` | 1 | MIT | free-form copyright: X.Org / XCB standard copyright — MIT/X11 permission notice |
| `libxrender1` | 1 | MIT | free-form copyright: X.Org / XCB standard copyright — MIT/X11 permission notice |
| `libzstd1` | 1 | BSD-3-Clause OR GPL-2.0-only | debian/copyright, Files: * stanza |
| `zlib1g` | 1 | Zlib | debian/copyright, Files: * stanza |

### Windows (`Orion-1.0.0-windows-x64.zip`) — 120 native binaries

| Component | Files | Licence | Evidence |
|---|--:|---|---|
| `CPython` | 17 | PSF-2.0 | the Python Software Foundation License, version 2 |
| `Microsoft Visual C++ / Universal CRT runtime` | 45 | Microsoft redistributable terms — not an open-source licence | shipped by the platform, not by a package manager |
| `OpenSSL` | 4 | Apache-2.0 | shipped by the platform, not by a package manager |
| `Pillow (vendored native libraries)` | 6 | MIT-CMU, plus the per-library terms in Pillow's LICENSE | the wheel's own distribution metadata |
| `PyMuPDF / MuPDF` | 3 | AGPL-3.0-only OR Artifex-Commercial | the wheel's own distribution metadata |
| `PySide6 / Qt 6` | 44 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only | the wheel's own distribution metadata |
| `libffi` | 1 | MIT | shipped by the platform, not by a package manager |

### macOS (`Orion-1.0.0-macos-arm64.zip`) — 156 native binaries

| Component | Files | Licence | Evidence |
|---|--:|---|---|
| `CPython` | 51 | PSF-2.0 | the Python Software Foundation License, version 2 |
| `OpenSSL` | 4 | Apache-2.0 | shipped by the platform, not by a package manager |
| `Pillow (vendored native libraries)` | 45 | MIT-CMU, plus the per-library terms in Pillow's LICENSE | the wheel's own distribution metadata |
| `PyMuPDF / MuPDF` | 8 | AGPL-3.0-only OR Artifex-Commercial | the wheel's own distribution metadata |
| `PySide6 / Qt 6` | 48 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only | the wheel's own distribution metadata |

## Build-time tools

These run in CI or on a developer's machine and are **not** in any release
archive, with one exception noted below:

| Tool | Licence | Shipped? |
|---|---|---|
| PyInstaller 6.22.2 | `GPL-2.0-or-later WITH Bootloader-exception` | **the bootloader is**, see below |
| pytest 9.1.1 | `MIT` | no |
| pytest-qt | `MIT` | no |
| ruff 0.16.4 | `MIT` | no |
| setuptools 79.0.1 | `MIT` | no |
| altgraph, packaging, pluggy, iniconfig, Pygments | `MIT`, `Apache-2.0 OR BSD-2-Clause`, `MIT`, `MIT`, `BSD-2-Clause` | no |

PyInstaller is the exception that matters. Its **bootloader is compiled into
every `Orion` executable Orion ships**, so PyInstaller's licence reaches the
released binaries even though PyInstaller itself does not. The Bootloader
Exception is what makes that harmless, and it is unambiguous:

> In addition to the permissions in the GNU General Public License, the authors
> give you unlimited permission to link or embed compiled bootloader and
> related files into combinations with other programs, and to distribute those
> combinations without any restriction coming from the use of those files.

So the GPL-2.0 does not propagate into Orion through the bootloader. This is
worth stating explicitly because "we build with PyInstaller, which is GPL" is a
recurring false alarm.

## Known gaps

The tables above describe the **published v1.0.0 archives**, which is what
users currently download. Three defects were found in them. All three are
fixed in `orion.spec`, and none of the fixes is in a published archive yet —
they land in the next release, and this document gets regenerated against it.

**1. The archives contain no licence texts at all — fixed, not yet released.**
A recursive search of all three published v1.0.0 archives for `LICENSE`,
`COPYING` or `NOTICE` files returns zero results. This is a genuine compliance
defect: LGPL-3.0 §4 requires a copy of the licence to accompany the object
code, the BSD and MIT libraries require their copyright notices be reproduced
in binary distributions, and MuPDF's AGPL requires the same.

The PySide6 wheels make it worse rather than easier: they declare LGPL-3.0 in
their metadata and ship no licence file, so there is nothing to copy forward
automatically and the text has to be supplied from somewhere. Note also that
LGPL-3.0 is not self-contained — it is a set of additional permissions on top
of GPL-3.0, so shipping it alone ships half a licence.

[`tools/collect_licences.py`](tools/collect_licences.py) now assembles the tree
and `orion.spec` adds it to the bundle as `licenses/`. A local Linux build
produces **87 files**: Orion's own AGPL text, each wheel's own licence where it
ships one, the canonical texts from [`licenses/`](licenses) for the wheels that
ship none, and the build machine's copyright record for every system package
whose library survives into the archive. Collection runs *after* the exclusion
filter, so it documents what is actually shipped and nothing that was removed.

**2. `libcom_err` had a disputed licence — removed rather than resolved.**
Ubuntu's copyright file for `libcom-err2` has no stanza covering `lib/et`, so
the package default of GPL-2 applies by omission; upstream e2fsprogs licenses
`com_err` under MIT. One reading put a GPL-2 library in the archive.

It is gone, which is a better answer than a legal opinion. The chain, read out
of the ELF headers of the published bundle:

```
libQt6Network  →  libgssapi_krb5  →  libcom_err, libkrb5, libk5crypto, libkrb5support
```

and `libQt6Network` was itself reached only from Qt's TLS, network-information,
VNC, TUIO and PDF plugins. Orion imports `QtCore`, `QtGui` and `QtWidgets` and
nothing else, so none of it ever loaded.

**3. Qt PDF shipped and was never used — removed.** `libQt6Pdf` (4.3 MB) was in
the Linux and macOS archives for one reason: Qt's `qpdf` *image-format* plugin
links it, and PyInstaller collects the plugin. Qt PDF embeds PDFium and its own
third-party dependencies, so this was a second PDF engine — and a second set of
licence obligations — riding along for a feature nothing calls.

Removing a library without its dependants leaves them behind: PyInstaller
resolves dependencies during Analysis, before the spec's filter runs, so
dropping `libQt6Network` does not drop what `libQt6Network` dragged in. The
orphaned Kerberos chain is named explicitly in `ORPHANED_BY_REMOVAL`, and
`objdump -p` over the rebuilt bundle finds no referrer to any of it.

Measured by building both specs in the same environment, the removals are worth
**9.0 MB unpacked and 4.3 MB compressed** — net of the ~0.5 MB of licence texts
added at the same time. The rebuilt bundle has no unresolved shared-library
dependencies (`ldd` over all 202 libraries) and still starts under the real
`xcb` platform plugin.

## Reproducing this

```sh
# extract a release archive, then:
python tools/licence_inventory.py --bundle linux=/path/to/extracted/Orion
```

The script exits non-zero if any binary in the bundle cannot be attributed, so
it can be wired into CI as a gate: a new unattributed library in the bundle
becomes a build failure rather than a silent omission from this file.

---

*Last regenerated against the published v1.0.0 archives. If the bundle changes,
regenerate — do not edit the tables by hand.*
