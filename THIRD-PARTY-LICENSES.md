# Third-party licences

Orion is licensed **AGPL-3.0-or-later** (see [LICENSE](LICENSE)), with a
commercial licence available separately (see
[COMMERCIAL-LICENSE.md](COMMERCIAL-LICENSE.md)). That covers the code in this
repository. It does not cover the code Orion is built on, and a downloadable
release is mostly that other code: a Linux build contains 185 native binaries
and not one of them was written for Orion. Orion's own code travels through
them as Python bytecode.

This file is the inventory of what those binaries are and what licenses them.

## The PDF engine was replaced

Until recently Orion rendered and wrote PDFs with **MuPDF**, through PyMuPDF.
Artifex licenses MuPDF under the AGPL-3.0 **or** a commercial licence of its
own, and Orion held no right to sublicense it — so a customer who bought a
commercial or redistribution licence to Orion still received AGPL MuPDF, and
the AGPL's obligations still attached to them. No amount of packaging work
changed that. It was the single reason the commercial tiers did not work.

MuPDF is gone. Three permissively licensed libraries do the work now, split
along the seam each is good at:

| Job | Library | Licence |
|---|---|---|
| Rendering pages, extracting and searching text | **pypdfium2** (Google's PDFium) | BSD-3-Clause / Apache-2.0 |
| Assembling documents, page operations, annotations | **pypdf** | BSD-3-Clause |
| Drawing what the user added — text, shapes, images | **reportlab** | BSD-3-Clause |

Nothing in the dependency closure is copyleft any more except Qt, which is
LGPL and was always workable. The change is also worth 46.6 MB unpacked and
20.6 MB compressed, measured by building both engines in the same environment.

## How this was produced

It was generated, not written from memory, by
[`tools/licence_inventory.py`](tools/licence_inventory.py) run against an
**extracted build** — the layout users actually download — and not against the
source tree. That distinction matters: PyInstaller collects whatever the build
machine's linker resolved, so the contents change when the runner image
changes, not when someone edits this repository. A hand-maintained list would
be stale within one CI image bump and nobody would notice.

The release workflow runs the same script on the runner, against the bundle it
is about to package, and files the result inside the archive as
`licenses/THIRD-PARTY-LICENSES-<platform>.md`. Those numbers are the
download's own, and they are the ones to trust for any particular archive.

One caveat on the table below specifically: it comes from a build of the same
source made on Ubuntu 24.04 — the same family as the release runner, not the
runner itself — which resolves a different number of files into the same set
of projects. Treat the counts here as the shape of the bundle rather than as a
checksum of the download.

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

The Linux lookup was run on Ubuntu 24.04 — the same image family as the
`ubuntu-latest` release runner. Run on anything else it has nothing to consult
and reports the system libraries as unresolved rather than guessing.

## What Orion depends on directly

Five packages, declared in [`requirements.txt`](requirements.txt), with the
licence each one's own metadata states:

| Package | Version built | Licence (from its metadata) | What Orion uses it for |
|---|---|---|---|
| PySide6 | 6.11.2 | `LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only` | the entire user interface |
| pypdfium2 | 5.13.0 | `BSD-3-Clause, Apache-2.0` | rendering pages, extracting and searching text |
| pypdf | 6.16.1 | `BSD-3-Clause` | assembling documents, page operations, annotations |
| reportlab | 5.0.1 | `BSD-3-Clause` | drawing added text, shapes and images |
| Pillow | 12.3.0 | `MIT-CMU` | decoding PNG, JPEG and WEBP before they are placed |

reportlab pulls in `charset-normalizer` (MIT); nothing else in the closure has
a mandatory dependency at all. Every one of these imposes attribution and
nothing more.

Only Qt is not permissive, and note what the PySide6 metadata does **not** say:
there is no commercial option in it. The PyPI wheels *are* the open-source
build of Qt. A Qt commercial licence is bought from The Qt Company and is not
something this licence, or a wheel, can grant.

## The components that actually constrain redistribution

Most of the inventory below is MIT, BSD and ISC — attribution and nothing
more. Four things are not, and these are the only ones worth a decision:

**Qt, via PySide6 — LGPL-3.0.** Distributable inside a closed product, but not
for free: the LGPL requires that a recipient be able to relink the application
against a modified Qt, that the licence text and a notice of Qt's use be
supplied, and that no further restriction be imposed on Qt itself. Orion links
Qt dynamically and ships it unmodified, which is the easy case, and the licence
texts now travel inside the archive.

**The LGPL-2.1 system libraries** — GLib and its family, libgcrypt,
libgpg-error, libsystemd, libfribidi, libgraphite2, libblkid, libmount. Same
shape of obligation as Qt, same easy case (dynamic, unmodified).

**The GCC runtime** — `libgcc_s` and `libstdc++`, GPL-3.0-or-later **with the
GCC Runtime Library Exception 3.1**. The exception is what makes this
distributable at all; without it a GPL-3 library would sit in the middle of
every build. Nothing to do here, but it should not be mistaken for a permissive
licence.

**The Microsoft Visual C++ and Universal CRT runtime** (Windows only) — not
open source at all. It is redistributable under Microsoft's own redistributable
terms, which is a different legal basis from every other entry in this document
and carries its own conditions.

## What was deliberately removed

Beyond MuPDF, five things were dropped from the bundle for licensing reasons:

- **Qt Virtual Keyboard** — GPLv3-only, not LGPL like the rest of Qt. It was
  shipping by accident as part of the default PySide6 collection. A GPLv3
  module inside a product offered under a commercial licence is a direct
  contradiction, so it and the `platforminputcontexts` plugin that loads it are
  filtered out in [`orion.spec`](orion.spec).
- **The GTK platform theme and its stack** — `qgtk3` plus GTK, GDK, ATK,
  Pango, Cairo and friends. Unused by Orion, and it dragged an LGPL stack into
  the bundle for no benefit.
- **Qt PDF** — a second PDF engine, embedding PDFium and its own dependencies,
  present only because Qt's `qpdf` image-format plugin links it.
- **Qt Network and the Kerberos stack behind it** — including `libcom_err`,
  whose licence Ubuntu's copyright file and upstream e2fsprogs disagree about.
  Not shipping it settles the question better than an opinion would.
- **The standard library's `readline` extension** — it links `libreadline`,
  **GPL-3.0-or-later with no linking exception**. This one was missed the first
  time round, and the inventory below is the evidence: `libreadline8t64` is in
  it, in a build offered for commercial redistribution, while the top of this
  document says nothing in the closure is copyleft but Qt. The table was right
  and the sentence was about the *dependency* closure; between them they
  described a bundle nobody had looked at closely enough. `libpython` does not
  link it — only that module does, and Orion never reads a line from an
  interactive prompt — so it and `rlcompleter` are now excluded, and `libtinfo`
  leaves with them. The v1.0.0 tag was re-cut onto the fixed build, so the
  archives on the releases page no longer contain it — but a copy downloaded
  before that does, and nothing about the file name says which one it is.

All of these exclusions are pinned by
[`tests/test_packaging.py`](tests/test_packaging.py) so they cannot silently
come back.

## Licence texts travel with the build

The v1.0.0 archives contained no `LICENSE`, `COPYING` or `NOTICE` file at all,
which LGPL-3.0 §4, the AGPL and every BSD and MIT notice in the bundle all
require. [`tools/collect_licences.py`](tools/collect_licences.py) now assembles
them and `orion.spec` ships them as `licenses/` — **100 files** in a Linux
build.

Two of the wheels needed care. **PySide6 declares LGPL-3.0 and ships no licence
file at all**, so its text is supplied from [`licenses/`](licenses) in this
repository, together with the GPL-3.0 it builds on — LGPL-3.0 is a set of
additional permissions on top of GPL-3.0 and means little alone. And
**pypdfium2's nineteen licence files are not named like licence files**: they
are named after the licence, one per library PDFium builds in — freetype, icu,
libjpeg-turbo, libpng, libtiff, zlib and the rest. Collecting only files called
LICENSE found none of them.

## Full inventory

Counts are files, not projects: one project usually contributes several
binaries. "Evidence" names where the licence came from, so any line here can
be re-checked rather than taken on trust.

### Linux — 185 native binaries

Regenerated from the build the current `v1.0.0` archives were made from. The
same build before `readline` was excluded contained 199, one of which was
`libreadline8t64` under GPL-3.0-or-later — see *What was deliberately removed*
above. Nothing in this table is copyleft without an exception.

| Component | Files | Licence | Evidence |
|---|--:|---|---|
| `CPython` | 26 | PSF-2.0 | the Python Software Foundation License, version 2 |
| `libblkid1` | 1 | LGPL-2.1-or-later | reviewed: Files: libblkid/* — default stanza says GPL-2+ |
| `libbrotli1` | 2 | MIT | debian/copyright, Files: * stanza |
| `libbsd0` | 1 | BSD-3-Clause AND BSD-2-Clause AND ISC | reviewed: per-file stanzas, all permissive BSD/ISC variants |
| `libbz2-1.0` | 1 | bzip2-1.0.6 | debian/copyright, Files: * stanza |
| `libcap2` | 1 | BSD-3-Clause OR GPL-2.0-only | debian/copyright, Files: * stanza |
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
| `libharfbuzz0b` | 1 | MIT | debian/copyright, Files: * stanza |
| `libjpeg-turbo8` | 1 | IJG AND BSD-3-Clause AND Zlib | reviewed: per-file stanzas; no Files: * stanza exists |
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
| `libx11-6` | 1 | MIT | free-form copyright: X.Org / XCB standard copyright — MIT/X11 permission notice |
| `libx11-xcb1` | 1 | MIT | free-form copyright: X.Org / XCB standard copyright — MIT/X11 permission notice |
| `libxau6` | 1 | MIT | free-form copyright: X.Org / XCB standard copyright — MIT/X11 permission notice |
| `libxcb-glx0` | 1 | MIT | free-form copyright: X.Org / XCB standard copyright — MIT/X11 permission notice |
| `libxcb-randr0` | 1 | MIT | free-form copyright: X.Org / XCB standard copyright — MIT/X11 permission notice |
| `libxcb-render0` | 1 | MIT | free-form copyright: X.Org / XCB standard copyright — MIT/X11 permission notice |
| `libxcb-shm0` | 1 | MIT | free-form copyright: X.Org / XCB standard copyright — MIT/X11 permission notice |
| `libxcb-sync1` | 1 | MIT | free-form copyright: X.Org / XCB standard copyright — MIT/X11 permission notice |
| `libxcb-xfixes0` | 1 | MIT | free-form copyright: X.Org / XCB standard copyright — MIT/X11 permission notice |
| `libxcomposite1` | 1 | MIT | free-form copyright: X.Org / XCB standard copyright — MIT/X11 permission notice |
| `libxcursor1` | 1 | MIT | free-form copyright: X.Org / XCB standard copyright — MIT/X11 permission notice |
| `libxdamage1` | 1 | MIT | free-form copyright: X.Org / XCB standard copyright — MIT/X11 permission notice |
| `libxdmcp6` | 1 | MIT | free-form copyright: X.Org / XCB standard copyright — MIT/X11 permission notice |
| `libxext6` | 1 | MIT | free-form copyright: X.Org / XCB standard copyright — MIT/X11 permission notice |
| `libxfixes3` | 1 | MIT | free-form copyright: X.Org / XCB standard copyright — MIT/X11 permission notice |
| `libxi6` | 1 | MIT | free-form copyright: X.Org / XCB standard copyright — MIT/X11 permission notice |
| `libxinerama1` | 1 | MIT | free-form copyright: X.Org / XCB standard copyright — MIT/X11 permission notice |
| `libxkbcommon0` | 1 | MIT | free-form copyright: X.Org / XCB standard copyright — MIT/X11 permission notice |
| `libxrandr2` | 1 | MIT | free-form copyright: X.Org / XCB standard copyright — MIT/X11 permission notice |
| `libxrender1` | 1 | MIT | free-form copyright: X.Org / XCB standard copyright — MIT/X11 permission notice |
| `libzstd1` | 1 | BSD-3-Clause OR GPL-2.0-only | debian/copyright, Files: * stanza |
| `Pillow (vendored native libraries)` | 32 | MIT-CMU, plus the per-library terms in Pillow's LICENSE | the wheel's own distribution metadata |
| `pypdfium2 / PDFium` | 1 | BSD-3-Clause AND Apache-2.0 (PDFium: BSD-3-Clause) | the wheel's own distribution metadata |
| `PySide6 / Qt 6` | 66 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only | the wheel's own distribution metadata |
| `PySide6 / Qt 6 (ICU)` | 3 | Unicode-3.0 (vendored in the PySide6 wheel) | the wheel's own distribution metadata |
| `zlib1g` | 1 | Zlib | debian/copyright, Files: * stanza |

Windows and macOS carry the same wheels and the same Qt, and differ below that:
Windows adds the Microsoft Visual C++ and Universal CRT runtime and has no
dpkg-owned libraries at all, and macOS ships Qt as frameworks. Their tables are
regenerated from the published archives at each release.

## Build-time tools

These run in CI or on a developer's machine and are **not** in any release
archive, with one exception noted below:

| Tool | Licence | Shipped? |
|---|---|---|
| PyInstaller | `GPL-2.0-or-later WITH Bootloader-exception` | **the bootloader is**, see below |
| pytest, pytest-qt, ruff, setuptools | `MIT` | no |
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

The three defects this document opened with are closed, and the published
archives now carry the fixes rather than merely the repository.

Verified against the file on the releases page rather than against the build
that produced it: the Windows archive was downloaded, its SHA-256 checked
against the release metadata, and its 288 entries listed. It contains no
MuPDF, PyMuPDF or fitz; it contains pdfium, pypdf and reportlab; it carries 55
files under `licenses/`; and Virtual Keyboard, Qt Quick, Qt Qml, EglFS, Qt PDF
and Qt Network are all absent.

One thing is worth stating precisely, because it is the difference between
"checked" and "checked the way that matters":

**The published archives were built before the smoke test learned to save.**
Their startup was exercised on each platform's own runner — Qt comes up on
`windows`, `cocoa` and `xcb` respectively, and the release fails otherwise —
but writing a PDF was not, because that check landed after the build. So the
save path is proven on Linux, where it was run against the frozen bundle
directly, and on Windows and macOS it is supported by inspection of the
archive rather than by execution. Rebuilding the release closes that, and
every release after this one is covered automatically.

## Reproducing this

```sh
pyinstaller --noconfirm --clean orion.spec
python tools/licence_inventory.py --bundle linux=dist/Orion
```

The script exits non-zero if any binary in the bundle cannot be attributed, so
it can be wired into CI as a gate: a new unattributed library in the bundle
becomes a build failure rather than a silent omission from this file.

---

*Regenerate after any change to the bundle — do not edit the tables by hand.*
