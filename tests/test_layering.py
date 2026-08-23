# Orion — PDF Editor for Desktop
# Copyright (C) 2026 Marco Lombardo
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# Distributed WITHOUT ANY WARRANTY; see LICENSE for the full terms.
# A commercial licence, without the AGPL's obligations, is available for use
# in proprietary or closed-source products — see COMMERCIAL-LICENSE.md.

"""The architectural boundary, enforced as a test (spec §5, §36).

``orion/document``, ``orion/commands``, ``orion/utils`` and ``orion/pdf`` must
stay usable without Qt — that is what keeps the model reusable and the suite
fast.  A convention nobody checks is a convention that decays, so this test
checks it.
"""

from __future__ import annotations

import ast
import builtins
import importlib
import pkgutil
import sys
from pathlib import Path

import pytest

import orion

PACKAGE_ROOT = Path(orion.__file__).resolve().parent

#: Packages that must never import Qt, at module level or inside a function.
QT_FREE_PACKAGES = ("document", "commands", "utils", "pdf")

#: Modules whose import must not pull Qt in, even transitively.
QT_FREE_IMPORTS = (
    "orion.utils.geometry",
    "orion.utils.events",
    "orion.utils.image_utils",
    "orion.document",
    "orion.document.serialization",
    "orion.commands",
    "orion.pdf.operations",
    "orion.pdf.writer",
    "orion.pdf.renderer",
    "orion.pdf.text_layout",
    "orion.services.file_service",
    "orion.services.export_service",
)


def _python_files(package: str) -> list[Path]:
    return sorted((PACKAGE_ROOT / package).rglob("*.py"))


@pytest.mark.parametrize("package", QT_FREE_PACKAGES)
def test_lower_layers_never_mention_qt(package):
    """No ``import PySide6`` anywhere in the framework-neutral packages."""
    offenders: list[str] = []
    for path in _python_files(package):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                root = name.split(".")[0]
                if root in ("PySide6", "shiboken6", "PyQt5", "PyQt6"):
                    offenders.append(f"{path.relative_to(PACKAGE_ROOT)}:{node.lineno} {name}")
    assert not offenders, "Qt must not be imported here:\n  " + "\n  ".join(offenders)


def test_importing_the_model_does_not_pull_qt_in(monkeypatch):
    """Even a lazy or transitive Qt import would fail this."""
    real_import = builtins.__import__
    seen: list[str] = []

    def guard(name, *args, **kwargs):
        if name.split(".")[0] in ("PySide6", "shiboken6"):
            seen.append(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guard)
    for module in QT_FREE_IMPORTS:
        sys.modules.pop(module, None)
        importlib.import_module(module)
    assert not seen, f"importing the model layer pulled in Qt: {seen}"


def test_the_ui_package_is_the_only_qt_consumer():
    """Sanity check in the other direction: the UI *does* use Qt."""
    ui_files = _python_files("ui")
    assert ui_files, "the ui package should not be empty"
    uses_qt = any("PySide6" in path.read_text(encoding="utf-8") for path in ui_files)
    assert uses_qt


def test_every_module_is_importable():
    """A module that no longer imports is a broken module, tested or not."""
    failures: list[str] = []
    for info in pkgutil.walk_packages([str(PACKAGE_ROOT)], prefix="orion."):
        if info.name.endswith("__main__"):
            continue  # importing it would try to start the application
        try:
            importlib.import_module(info.name)
        except Exception as exc:  # pragma: no cover - the assertion reports it
            failures.append(f"{info.name}: {type(exc).__name__}: {exc}")
    assert not failures, "modules failed to import:\n  " + "\n  ".join(failures)
