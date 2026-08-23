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
sixth dependency, or swaps one engine for another, and the licence
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

from collect_licences import (  # noqa: E402
    RUNTIME_DISTRIBUTIONS,
    SUPPLIED_TEXTS,
    _flatten,
    collect,
)
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
        # The one that still constrains redistribution. If this string stops
        # matching the wheel metadata, the licensing analysis in
        # COMMERCIAL-LICENSE.md is built on a false premise.
        ("PySide6", "LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only"),
        # The ones that do not.
        ("pypdfium2", "BSD-3-Clause"),
        ("pypdf", "BSD-3-Clause"),
        ("reportlab", "BSD"),
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


def test_the_document_separates_what_was_run_from_what_was_inspected(
    document: str,
) -> None:
    """A licence document has to say how strongly each claim was checked.

    Everything here was verified, but not all of it the same way. The published
    archive was downloaded and its contents listed; the save path was executed
    against a frozen bundle on one platform and inferred from the archive's
    contents on the other two. Presenting those as one uniform "verified" is
    the kind of accurate-but-misleading that gets somebody into trouble, so the
    section that reports the state has to distinguish them.
    """
    assert "## Known gaps" in document
    section = document[document.index("## Known gaps"):]
    assert "inspection" in section, (
        "the document does not say which claims rest on inspection rather than "
        "on having been run"
    )
    assert "SHA-256" in section, (
        "nothing records that the published archive itself was checked, as "
        "opposed to the build that produced it"
    )


def test_the_engine_replacement_is_explained_not_just_applied(document: str) -> None:
    """Why MuPDF left is the question a commercial buyer will ask first."""
    assert "MuPDF" in document
    assert "sublicense" in document.lower() or "sublicence" in document.lower()
    for library in ("pypdfium2", "pypdf", "reportlab"):
        assert library in document, f"{library} took over part of the job and is unnamed"


class TestBundleClassifier:
    """Paths taken from the three published v1.0.0 archives."""

    @pytest.mark.parametrize(
        "path, component",
        [
            # Linux: PyInstaller hoists wheel libraries next to system ones,
            # so the name is all there is to go on.
            ("libQt6Core.so.6", "PySide6 / Qt 6"),
            ("libpdfium.so", "pypdfium2 / PDFium"),
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
            ("pypdfium2_raw/pdfium.dll", "pypdfium2 / PDFium"),
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

    def test_pdfiums_own_third_party_notices_are_collected(self, tree: str) -> None:
        """pypdfium2's licence files are not named like licence files.

        It ships nineteen of them, named after the licence rather than the
        word — Apache-2.0.txt, BSD-3-Clause.txt, and one per library PDFium
        builds in. Matching on the file name alone collected none of them and
        said nothing about it, which is the exact failure the collector exists
        to prevent, so this checks the awkward case rather than the easy one.
        """
        directory = os.path.join(tree, "python", "pypdfium2")
        assert os.path.isdir(directory), "pypdfium2 got no licence directory"
        collected = {
            os.path.basename(name)
            for _root, _dirs, files in os.walk(directory)
            for name in files
        }
        assert "pdfium.txt" in collected, "PDFium's own licence was not collected"
        for library in ("freetype.txt", "libpng.txt", "zlib.txt", "icu.txt"):
            assert library in collected, f"PDFium bundles {library} and says so"

    def test_pillows_licence_covers_its_vendored_libraries(self, tree: str) -> None:
        """Pillow's LICENSE is the notice for a dozen native libraries.

        Matched case-insensitively, and against libraries every wheel vendors.
        The first version of this test looked for the uppercase section
        headings the Linux wheel uses — LIBJPEG, LIBTIFF — and failed on
        Windows, whose wheel carries the same libraries under prose headings
        ("libjpeg-turbo Licenses"). It was checking the formatting of one
        platform's file, not the coverage of the notice.

        The two wheels do differ in substance as well: the Windows notice has
        no zstd or AOM section, because the Windows wheel vendors neither.
        Those are deliberately not asserted here.
        """
        with open(os.path.join(tree, "python", "pillow", "LICENSE"), encoding="utf-8") as f:
            text = f.read().lower()
        for library in ("freetype", "libjpeg", "libpng", "zlib", "libtiff", "libwebp"):
            assert library in text, f"Pillow's notice no longer covers {library}"

    def test_the_pyinstaller_bootloader_exception_travels_with_the_binary(
        self, tree: str
    ) -> None:
        """The bootloader is compiled into the executable, so its terms ship.

        Skipped where PyInstaller is not installed. CI installs the test
        dependencies and not the packaging ones, so demanding the file exist
        here asserted a property of my machine rather than of the collector —
        and the collector was right to omit terms for software that is not
        present. What matters in that case is covered by the test below.
        """
        from importlib.metadata import PackageNotFoundError, distribution

        try:
            distribution("pyinstaller")
        except PackageNotFoundError:
            pytest.skip("PyInstaller is not installed in this environment")
        path = os.path.join(tree, "python", "pyinstaller", "COPYING.txt")
        with open(path, encoding="utf-8") as f:
            assert "Bootloader Exception" in f.read()

    def test_a_missing_licence_is_recorded_rather_than_passed_over(
        self, tree: str
    ) -> None:
        """Silence is the dangerous failure mode for a licence collector.

        If a distribution ships no licence file and none is supplied for it,
        the tree simply has no directory for it — which looks identical to a
        distribution that is not used at all. The index has to say so, so that
        a gap is visible in the archive instead of being indistinguishable
        from completeness.
        """
        with open(os.path.join(tree, "README.md"), encoding="utf-8") as f:
            index = f.read()
        for name in RUNTIME_DISTRIBUTIONS:
            assert name in index, (
                f"{name} appears nowhere in the shipped index, so its absence "
                "from the tree carries no explanation"
            )

    def test_build_tools_that_are_not_shipped_are_not_documented(self, tree: str) -> None:
        """Terms for software that is not in the archive are noise in it."""
        packaged = os.listdir(os.path.join(tree, "python"))
        for tool in ("pytest", "ruff", "setuptools"):
            assert tool not in packaged


class TestLicencePathHandling:
    """Two licence files with the same name must not become one.

    Wheels put licence texts both beside METADATA and under a ``licenses/``
    directory, and some ship many at once — pip's wheel carries twenty, one
    per vendored package, every one of them called LICENSE. Writing them by
    base name leaves a tree that looks complete and has silently kept only the
    last, which is the single failure this collector exists to prevent.
    """

    def test_the_conventional_licenses_prefix_is_dropped(self) -> None:
        """It is packaging convention, not information."""
        assert _flatten([("licenses/LICENSE", "x")]) == [("LICENSE", "x")]

    def test_but_not_when_that_would_collide(self) -> None:
        """A wheel shipping both keeps both, under distinct names."""
        flattened = dict(_flatten([("LICENSE", "outer"), ("licenses/LICENSE", "inner")]))
        assert flattened == {"LICENSE": "outer", "licenses/LICENSE": "inner"}

    def test_deeper_paths_are_preserved(self) -> None:
        """pip vendors twenty LICENSE files; only the path tells them apart."""
        vendored = [
            ("licenses/src/pip/_vendor/requests/LICENSE", "requests"),
            ("licenses/src/pip/_vendor/urllib3/LICENSE.txt", "urllib3"),
        ]
        flattened = dict(_flatten(vendored))
        assert len(flattened) == 2
        assert flattened["src/pip/_vendor/requests/LICENSE"] == "requests"
