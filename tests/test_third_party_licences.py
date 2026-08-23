#!/usr/bin/env python
# Orion — PDF Editor for Desktop
# Copyright (C) 2026 Marco Lombardo
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# Distributed WITHOUT ANY WARRANTY; see LICENSE for the full terms.
# A commercial licence, without the AGPL's obligations, is available for use
# in proprietary or closed-source products — see COMMERCIAL-LICENSE.md.

"""Keeps THIRD-PARTY-LICENSES.md honest about the dependencies it describes.

The document is generated from an extracted release bundle, which no test can
reach: CI has no release archive and no Ubuntu package database to consult. So
this file does not try to re-derive the inventory. It checks the part that
*is* checkable from the repository, which is also the part most likely to rot:
the four runtime dependencies.

The failure this guards against is mundane and easy to miss. Someone adds a
fifth dependency, or swaps PyMuPDF for something permissive, and the licence
document keeps describing the old set — which is worse than having no document,
because a stale licence document is one people rely on.

The classifier in tools/licence_inventory.py is tested here too. It is pure
string handling over bundle-relative paths, so it needs no bundle: the paths
below were copied out of the three published v1.0.0 archives, including the
three that previously produced wrong answers.
"""

from __future__ import annotations

import os
import re
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCUMENT = os.path.join(REPO, "THIRD-PARTY-LICENSES.md")

sys.path.insert(0, os.path.join(REPO, "tools"))

from collect_licences import SUPPLIED_TEXTS, collect  # noqa: E402
from licence_inventory import classify, is_native  # noqa: E402


@pytest.fixture(scope="module")
def document() -> str:
    with open(DOCUMENT, encoding="utf-8") as handle:
        return handle.read()


def declared_requirements() -> list[str]:
    """The runtime dependency names, read from requirements.txt."""
    path = os.path.join(REPO, "requirements.txt")
    with open(path, encoding="utf-8") as handle:
        lines = [line.strip() for line in handle]
    names = []
    for line in lines:
        if not line or line.startswith(("#", "-")):
            continue
        names.append(re.split(r"[<>=!~\[]", line)[0].strip())
    return names


def test_every_runtime_dependency_is_documented(document: str) -> None:
    """A dependency the user receives but the licence file never mentions."""
    missing = [
        name for name in declared_requirements()
        if name.lower() not in document.lower()
    ]
    assert not missing, (
        f"{missing} are in requirements.txt but absent from "
        "THIRD-PARTY-LICENSES.md — a dependency was added without recording "
        "what licenses it"
    )


def test_the_document_names_no_dependency_orion_dropped(document: str) -> None:
    """The reverse drift: the file still describing something long removed."""
    table = document.split("| Package | Version built")[1].split("\n\n")[0]
    listed = {
        row.split("|")[1].strip()
        for row in table.splitlines()
        if row.startswith("| ") and "---" not in row
    }
    listed.discard("Package")
    declared = {name.lower() for name in declared_requirements()}
    stale = {name for name in listed if name.lower() not in declared}
    assert not stale, (
        f"{stale} are described as runtime dependencies but are not in "
        "requirements.txt any more"
    )


@pytest.mark.parametrize(
    "dependency, licence",
    [
        # The two that constrain redistribution. If either of these strings
        # stops matching the wheel metadata, the whole licensing analysis in
        # COMMERCIAL-LICENSE.md is built on a false premise.
        ("PyMuPDF", "AGPL-3.0-only OR Artifex-Commercial"),
        ("PySide6", "LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only"),
        # The two that do not.
        ("pypdf", "BSD-3-Clause"),
        ("Pillow", "MIT-CMU"),
    ],
)
def test_licence_of_each_dependency_is_stated(
    document: str, dependency: str, licence: str
) -> None:
    row = next(
        (line for line in document.splitlines()
         if line.startswith(f"| {dependency} ")),
        None,
    )
    assert row is not None, f"no table row for {dependency}"
    assert licence in row, (
        f"{dependency} is documented as something other than {licence!r}: {row}"
    )


def test_the_known_gaps_are_not_quietly_deleted(document: str) -> None:
    """Gaps stay listed until they are actually closed.

    Deleting the section is the tempting way to make a licence document look
    clean. These three are open defects, and the archives still ship without
    licence texts; the section goes when the fix lands, not before.
    """
    assert "## Known gaps" in document
    for gap in ("no licence texts", "libcom_err", "Qt PDF"):
        assert gap in document, f"the '{gap}' gap vanished without a fix"


class TestBundleClassifier:
    """Paths taken from the three published v1.0.0 archives."""

    @pytest.mark.parametrize(
        "path, component",
        [
            # Linux: PyInstaller hoists wheel libraries next to system ones,
            # so the name is all there is to go on.
            ("libQt6Core.so.6", "PySide6 / Qt 6"),
            ("libmupdf.so.28.2", "PyMuPDF / MuPDF"),
            ("pillow.libs/libjpeg-31e2ca52.so.62.4.0", "Pillow (vendored native libraries)"),
            # ICU is vendored inside the PySide6 wheel and looks exactly like
            # a system library once hoisted. Attributing it to the system
            # would credit it to a package the build machine never had.
            ("libicuuc.so.73", "PySide6 / Qt 6 (ICU)"),
            ("_ssl.cpython-312-x86_64-linux-gnu.so", "CPython"),
            # macOS: the framework binary has no extension at all.
            ("QtGui.framework/Versions/A/QtGui", "PySide6 / Qt 6"),
            ("Python.framework/Versions/3.12/Python", "CPython"),
            ("libjpeg.62.4.0.dylib", "Pillow (vendored native libraries)"),
            # Windows: a bare .pyd is a stdlib extension module; one inside a
            # package belongs to that package.
            ("_socket.pyd", "CPython"),
            ("PySide6/QtCore.pyd", "PySide6 / Qt 6"),
            ("pymupdf/_mupdf.pyd", "PyMuPDF / MuPDF"),
        ],
    )
    def test_attribution(self, path: str, component: str) -> None:
        classified = classify(path)
        assert classified is not None, f"{path} was not recognised as native"
        assert classified[1] == component

    def test_linux_system_libjpeg_is_not_credited_to_pillow(self) -> None:
        """The macOS name rule must not reach across to Linux.

        Pillow's macOS libraries lose auditwheel's hex tag, so they are matched
        by stem — and on Linux those same stems name the *system* copies.
        Matching by stem everywhere silently reattributed four Linux system
        libraries to Pillow, with the wrong licence attached to each.
        """
        origin, component = classify("libjpeg.so.8")
        assert origin == "system", component

    def test_the_frozen_executable_is_not_a_library(self) -> None:
        assert not is_native("Orion")
        assert not is_native("base_library.zip")


class TestLicenceCollection:
    """The tree that orion.spec puts inside the archive as licenses/."""

    @pytest.fixture(scope="class")
    def tree(self, tmp_path_factory) -> str:
        return collect(REPO, str(tmp_path_factory.mktemp("licences") / "out"))

    def test_orions_own_licence_is_there(self, tree: str) -> None:
        with open(os.path.join(tree, "Orion-LICENSE.txt"), encoding="utf-8") as f:
            assert "GNU AFFERO GENERAL PUBLIC LICENSE" in f.read()

    def test_qt_gets_a_licence_text_the_wheel_never_shipped(self, tree: str) -> None:
        """PySide6's wheels declare LGPL-3.0 and include no licence file.

        Nothing can be copied forward from a wheel that ships nothing, so the
        text has to be supplied — which is the whole reason licenses/ exists in
        the repository rather than being generated from dist-info alone.
        """
        supplied = os.path.join(tree, "python", "PySide6")
        assert os.path.isdir(supplied), "PySide6 got no licence directory"
        assert os.path.exists(os.path.join(supplied, "LGPL-3.0.txt"))

    def test_lgpl3_never_travels_without_gpl3(self, tree: str) -> None:
        """LGPL-3.0 is a set of additional permissions on top of GPL-3.0.

        Its text is seven kilobytes and defines almost nothing on its own:
        shipping it alone ships half a licence. Every distribution that gets
        LGPL-3.0 gets GPL-3.0 with it.
        """
        for name, texts in SUPPLIED_TEXTS.items():
            if "LGPL-3.0.txt" not in texts:
                continue
            assert "GPL-3.0.txt" in texts, (
                f"{name} is given LGPL-3.0 without the GPL-3.0 it builds on"
            )
            directory = os.path.join(tree, "python", name)
            assert os.path.exists(os.path.join(directory, "GPL-3.0.txt"))

    def test_mupdfs_one_line_copying_is_backed_by_the_agpl_text(self, tree: str) -> None:
        """PyMuPDF's COPYING is a single line naming the dual licence."""
        directory = os.path.join(tree, "python", "PyMuPDF")
        with open(os.path.join(directory, "COPYING"), encoding="utf-8") as f:
            assert len(f.read().strip().splitlines()) == 1
        with open(os.path.join(directory, "AGPL-3.0.txt"), encoding="utf-8") as f:
            assert "GNU AFFERO GENERAL PUBLIC LICENSE" in f.read()

    def test_pillows_licence_covers_its_vendored_libraries(self, tree: str) -> None:
        """Pillow's LICENSE is the notice for a dozen native libraries."""
        with open(os.path.join(tree, "python", "pillow", "LICENSE"), encoding="utf-8") as f:
            text = f.read()
        for library in ("LIBJPEG", "LIBTIFF", "ZLIB", "OPENJPEG", "HARFBUZZ"):
            assert library in text, f"Pillow's notice no longer covers {library}"

    def test_the_pyinstaller_bootloader_exception_travels_with_the_binary(
        self, tree: str
    ) -> None:
        """The bootloader is compiled into the executable, so its terms ship."""
        path = os.path.join(tree, "python", "pyinstaller", "COPYING.txt")
        with open(path, encoding="utf-8") as f:
            assert "Bootloader Exception" in f.read()

    def test_build_tools_that_are_not_shipped_are_not_documented(self, tree: str) -> None:
        """Terms for software that is not in the archive are noise in it."""
        packaged = os.listdir(os.path.join(tree, "python"))
        for tool in ("pytest", "ruff", "setuptools"):
            assert tool not in packaged
