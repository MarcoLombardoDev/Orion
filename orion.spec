# -*- mode: python ; coding: utf-8 -*-
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

# Qt modules Orion never touches; excluding them roughly halves the bundle.
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
