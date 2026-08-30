# -*- mode: python ; coding: utf-8 -*-
# Orion — PDF Editor for Desktop
# Copyright (C) 2026 Marco Lombardo
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# Distributed WITHOUT ANY WARRANTY; see LICENSE for the full terms.
# A commercial licence, without the AGPL's obligations, is available for use
# in proprietary or closed-source products — see COMMERCIAL-LICENSE.md.

"""PyInstaller specification for standalone Orion builds (spec §33).

    pip install pyinstaller
    pyinstaller orion.spec

Produces ``dist/Orion.exe`` on Windows, ``dist/Orion.app`` on macOS and
``dist/Orion`` on Linux.  Packaging is deliberately *not* a requirement for
building or running Orion — this file exists so the project stays compatible
with it.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(SPECPATH) / "tools"))  # noqa: F821 - PyInstaller global

from collect_licences import collect as collect_licences  # noqa: E402

BUILD_DIR = Path(SPECPATH)  # noqa: F821 - injected by PyInstaller
APP_NAME = "Orion"

# Qt Python modules Orion never imports.
EXCLUDED_QT = [
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtQuick",
    "PySide6.QtQml",
    "PySide6.Qt3DCore",
    "PySide6.QtMultimedia",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.QtBluetooth",
    "PySide6.QtPositioning",
    "PySide6.QtSql",
    "PySide6.QtNetwork",
    "PySide6.QtTest",
    "PySide6.QtDesigner",
]

analysis = Analysis(  # noqa: F821 - PyInstaller globals
    [str(BUILD_DIR / "orion" / "__main__.py")],
    pathex=[str(BUILD_DIR)],
    binaries=[],
    datas=[(str(BUILD_DIR / "resources"), "resources")],
    hiddenimports=["pypdfium2", "pypdf", "reportlab", "PIL.Image"],
    hookspath=[],
    runtime_hooks=[],
    excludes=EXCLUDED_QT + [
        "tkinter", "matplotlib", "numpy", "pytest",
        # readline is excluded for the same reason as the virtual keyboard
        # below, and it was missed the first time round. The standard
        # library's optional readline extension links libreadline —
        # **GPL-3.0-or-later, with no linking exception** — so v1.0.0's Linux
        # archive contains a GPL-3 library, which THIRD-PARTY-LICENSES.md
        # duly recorded while §11 was saying nothing in the bundle is copyleft
        # but Qt. libpython does not link it; only this module does, and Orion
        # never reads a line from an interactive prompt. rlcompleter goes with
        # it: it imports readline and exists for nothing else.
        "readline", "rlcompleter",
    ],
    noarchive=False,
)

# ``excludes`` above only drops *Python* modules.  The native Qt libraries and
# plugins come along regardless, pulled in by PyInstaller's Qt hooks, so they
# have to be filtered out of what was collected.
#
# One of them matters legally rather than just for size.  Qt ships the virtual
# keyboard under **GPLv3 or commercial — not LGPL**, so shipping it would put
# GPLv3 code inside a binary that is also offered under a commercial licence.
# Orion has never used a virtual keyboard.  It is also the only thing in the
# bundle that links Qt Quick and Qt Qml, so those leave with it.
#
# Verified with ``ldd`` over the built bundle: nothing else references any of
# these, and ``tests/test_packaging.py`` re-checks that this list still removes
# the GPLv3 module.
UNUSED_QT_COMPONENTS = (
    "virtualkeyboard",          # GPLv3-or-commercial; unused
    "platforminputcontexts",    # the plugin that loads it
    "qt6quick",                 # only ever pulled in by the virtual keyboard
    "qtquick",
    "qt6qml",
    "qtqml",
    "eglfs",                    # embedded/kiosk backends; Orion is a desktop app
    "egldeviceintegrations",
    "qgtk3",                    # GTK platform theme; see GTK_STACK below
    #
    # A second PDF engine, and the network stack behind it, for a feature
    # nothing calls.  Qt's ``qpdf`` *image-format* plugin links libQt6Pdf,
    # which embeds PDFium and links libQt6Network; the TLS, network-information,
    # VNC and TUIO plugins link libQt6Network too.  Orion imports QtCore,
    # QtGui and QtWidgets and nothing else, so none of it is ever loaded.
    #
    # It is worth removing for a licensing reason as much as for the 6.3 MB.
    # libQt6Network drags in the Kerberos libraries, one of which — libcom_err
    # — has a licence Ubuntu's copyright file and upstream e2fsprogs disagree
    # about.  Deleting the chain settles the question without needing a legal
    # opinion on a library nothing calls.
    #
    # Read out of the shipped bundle with ``objdump -p``: after these go,
    # nothing in the bundle references libQt6Pdf or libQt6Network.
    "imageformats/libqpdf",     # the only thing linking libQt6Pdf
    "imageformats/qpdf",        # its Windows and macOS spellings
    "qt6pdf",
    "plugins/tls",
    "plugins/networkinformation",
    "qtuiotouchplugin",
    "libqvnc",
    "qt6network",
    "qtnetwork",                # the Python binding, which links libQt6Network
)

# Removing Qt Network orphans the Kerberos stack it linked for GSSAPI: with
# libQt6Network gone, ``objdump -p`` over the built bundle finds no referrer to
# libgssapi_krb5 outside the chain itself.  PyInstaller collected these during
# Analysis, before the filtering above, so they have to be named to leave.
#
# libcom_err is the one that motivated this: Ubuntu's copyright file has no
# stanza for e2fsprogs' lib/et, so the package default of GPL-2 applies by
# omission, while upstream licenses it MIT.  It is now simply not in the
# archive, which is a better answer than either reading.
ORPHANED_BY_REMOVAL = (
    "libgssapi_krb5",
    "libkrb5",              # also matches libkrb5support
    "libk5crypto",
    "libcom_err",
    "libkeyutils",          # linked only by libkrb5
)

# Dropping the GTK platform theme leaves its dependency chain with nothing to
# load it.  Orion already forces the Fusion style, so that plugin only ever
# supplied GNOME's native file dialogs; Qt's own dialogs take over.
#
# Every name below was checked with ``ldd`` over the built bundle: the only
# things linking them are other members of this list.  Notably absent, because
# the same check showed Qt itself links them, are libglib/libgobject/libgio,
# libfreetype, libharfbuzz, libgcrypt and libsystemd — those are not GTK's, and
# removing them would break Qt.
GTK_STACK = (
    "libgtk-3",
    "libgdk-3",
    "libgdk_pixbuf",
    "libatk-1.0",
    "libatk-bridge",
    "libatspi",
    "libcairo",          # also matches libcairo-gobject
    "libpango",          # also matches libpangocairo, libpangoft2
    "libepoxy",
    "libthai",
    "libdatrie",
)


def _drop_unused(entries):
    """Remove collected files whose destination names an unused component."""
    kept = []
    for entry in entries:
        destination = str(entry[0]).replace("\\", "/").lower()
        unused = UNUSED_QT_COMPONENTS + GTK_STACK + ORPHANED_BY_REMOVAL
        if any(name in destination for name in unused):
            continue
        kept.append(entry)
    return kept


analysis.binaries = _drop_unused(analysis.binaries)
analysis.datas = _drop_unused(analysis.datas)

# The v1.0.0 archives shipped without a single licence file in them, which the
# LGPL, the AGPL and every BSD/MIT notice in the bundle all require.  Assemble
# the texts and ship them.  This runs after the filtering above so the system
# libraries it reads are the ones that actually survive into the archive.
LICENCE_STAGING = BUILD_DIR / "build" / "licenses"
# TOC entries are (destination, source, typecode) — appended directly, so they
# bypass the normalisation Analysis() applies to its own ``datas`` argument and
# have to be in that exact shape.
analysis.datas += [
    (
        str(Path("licenses") / Path(path).relative_to(LICENCE_STAGING) / name),
        str(Path(path) / name),
        "DATA",
    )
    for path, _subdirs, names in os.walk(
        collect_licences(str(BUILD_DIR), str(LICENCE_STAGING), analysis.binaries)
    )
    for name in names
]

pyz = PYZ(analysis.pure)  # noqa: F821

# One drawing, three containers, because each platform will take only its own.
# Windows embeds an .ico in the executable's resources and will not take a PNG;
# macOS will take only an .icns in an application bundle; everywhere else the
# PNG is what PyInstaller wants. All three are drawn by tools/make_icon.py and
# committed, so a build never depends on which fonts the runner happens to
# have -- nor, for the .icns, on whether Pillow happens to be installed in the
# build environment. PyInstaller will convert a PNG on the fly when it is, and
# dies at BUNDLE() with "not in the correct format" when it is not: a whole
# macOS build succeeding and then failing on its last line. That is not a
# hypothetical, it is what the first release of the sibling product with no
# Pillow did.
_icons = BUILD_DIR / "resources" / "icons"
_icon_file = {"win32": "orion.ico", "darwin": "orion.icns"}.get(sys.platform, "orion.png")
icon_path = _icons / _icon_file
icon = str(icon_path) if icon_path.exists() else None

executable = EXE(  # noqa: F821
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    strip=False,
    upx=False,
    console=False,          # a GUI application has no terminal window
    icon=icon,
)

collection = COLLECT(  # noqa: F821
    executable,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    name=APP_NAME,
)

if sys.platform == "darwin":
    app = BUNDLE(  # noqa: F821
        collection,
        name=f"{APP_NAME}.app",
        icon=icon,
        bundle_identifier="dev.marcolombardo.orion",
        info_plist={
            "CFBundleName": APP_NAME,
            "CFBundleDisplayName": APP_NAME,
            "NSHighResolutionCapable": True,
            "CFBundleDocumentTypes": [
                {
                    "CFBundleTypeName": "PDF document",
                    "CFBundleTypeRole": "Editor",
                    "LSItemContentTypes": ["com.adobe.pdf"],
                }
            ],
        },
    )
