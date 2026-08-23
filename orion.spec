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

import sys
from pathlib import Path

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
    "PySide6.QtTest",
    "PySide6.QtDesigner",
]

analysis = Analysis(  # noqa: F821 - PyInstaller globals
    [str(BUILD_DIR / "orion" / "__main__.py")],
    pathex=[str(BUILD_DIR)],
    binaries=[],
    datas=[(str(BUILD_DIR / "resources"), "resources")],
    hiddenimports=["pymupdf", "pypdf", "PIL.Image"],
    hookspath=[],
    runtime_hooks=[],
    excludes=EXCLUDED_QT + ["tkinter", "matplotlib", "numpy", "pytest"],
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
)


def _drop_unused(entries):
    """Remove collected files whose destination names an unused component."""
    kept = []
    for entry in entries:
        destination = str(entry[0]).replace("\\", "/").lower()
        if any(name in destination for name in UNUSED_QT_COMPONENTS):
            continue
        kept.append(entry)
    return kept


analysis.binaries = _drop_unused(analysis.binaries)
analysis.datas = _drop_unused(analysis.datas)

pyz = PYZ(analysis.pure)  # noqa: F821

icon_path = BUILD_DIR / "resources" / "icons" / "orion.png"
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
