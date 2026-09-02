#!/usr/bin/env python
# Orion — PDF Editor for Desktop
# Copyright (C) 2026 Marco Lombardo
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# Distributed WITHOUT ANY WARRANTY; see LICENSE for the full terms.
# A commercial licence, without the AGPL's obligations, is available for use
# in proprietary or closed-source products — see COMMERCIAL-LICENSE.md.

"""English and Italian.

The catalogue tests are ordinary. The one that matters is the last: it builds
the real window in Italian and walks it, because a translation table that is
merely complete against itself proves nothing about the strings the code
forgot to look up.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from orion.i18n import (
    _CATALOGUE,
    Language,
    current_language,
    detect_language,
    set_language,
    tr,
)
from tests.conftest import pump  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _english_again():
    """The language is process-wide; put it back however the test ends."""
    previous = current_language()
    yield
    set_language(previous)


# -- picking a language ----------------------------------------------------
@pytest.mark.parametrize(
    "locale, expected",
    [
        ("it_IT", Language.ITALIAN),
        ("it_CH", Language.ITALIAN),
        ("it", Language.ITALIAN),
        ("IT_it", Language.ITALIAN),
        ("en_GB", Language.ENGLISH),
        ("de_DE", Language.ENGLISH),
        ("fr_FR", Language.ENGLISH),
        ("", Language.ENGLISH),
        (None, Language.ENGLISH),
    ],
)
def test_the_system_locale_picks_the_language(locale, expected):
    """Italian for an Italian desktop, English for every other."""
    assert detect_language(locale) is expected


def test_english_is_the_answer_for_a_language_nobody_wrote():
    """Orion speaks two languages and one of them is the fallback."""
    assert detect_language("ja_JP") is Language.ENGLISH


# -- the look-up -----------------------------------------------------------
def test_english_hands_the_string_straight_back():
    set_language(Language.ENGLISH)
    assert tr("&Save") == "&Save"


def test_italian_looks_it_up():
    set_language(Language.ITALIAN)
    assert tr("&Save") == "&Salva"


def test_an_untranslated_phrase_shows_in_english():
    """A gap must not stop the window opening; the tests are where it is caught."""
    set_language(Language.ITALIAN)
    assert tr("nothing has ever translated this") == "nothing has ever translated this"


def test_the_accelerator_is_part_of_the_phrase():
    """An Italian label needs its own, on a letter the Italian word has."""
    set_language(Language.ITALIAN)
    for english, italian in _CATALOGUE.items():
        if "&" in english:
            assert "&" in italian, f"{english!r} lost its accelerator"


def test_no_translation_is_left_as_english():
    """A row that repeats the English is a row somebody forgot.

    Allowed only where the two languages genuinely agree — "&File" is "&File",
    a paper size is a paper size, and "zoom" is the word Italian uses too.
    """
    same = {k for k, v in _CATALOGUE.items() if k == v}
    allowed = {
        "&File",
        "Zoom",
        "A4 (210 × 297 mm)",
        "A3 (297 × 420 mm)",
        "A5 (148 × 210 mm)",
    }
    assert same <= allowed, f"untranslated: {sorted(same - allowed)}"


# -- the catalogue against the source --------------------------------------
def _wrapped_strings() -> set[str]:
    """Every literal the code passes to ``tr``."""
    found: set[str] = set()
    for path in sorted((REPO / "orion").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "tr"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                found.add(node.args[0].value)
    return found


def test_every_phrase_the_code_asks_for_has_an_italian():
    missing = sorted(_wrapped_strings() - set(_CATALOGUE))
    assert not missing, f"no Italian for: {missing}"


def test_a_placeholder_survives_the_translation():
    """``{name}`` in the English has to be in the Italian, or format() raises."""
    import re

    for english, italian in _CATALOGUE.items():
        fields = set(re.findall(r"\{(\w+)\}", english))
        if fields:
            assert fields == set(re.findall(r"\{(\w+)\}", italian)), (
                f"{english!r} and its Italian disagree about placeholders"
            )


# -- the real window -------------------------------------------------------
class TestTheWindowInItalian:
    """Built in Italian and walked, which is the only test that can find a
    string the code never looked up at all.
    """

    @staticmethod
    def _visible_text(window) -> list[tuple[str, str]]:
        """Every label, action and button the window is showing."""
        from PySide6.QtGui import QAction
        from PySide6.QtWidgets import QAbstractButton, QGroupBox, QLabel

        found: list[tuple[str, str]] = []
        for action in window._actions.all():
            found.append(("action", action.text()))
            found.append(("tooltip", action.toolTip()))
        for kind, attr in (
            (QLabel, "text"),
            (QAbstractButton, "text"),
            (QGroupBox, "title"),
            (QAction, "text"),
        ):
            for widget in window.findChildren(kind):
                found.append((kind.__name__, getattr(widget, attr)()))
        for bar in (window.menuBar(),):
            for action in bar.actions():
                found.append(("menu", action.text()))
        return [(where, text) for where, text in found if text and text.strip()]

    def test_nothing_is_left_in_english(self, window, qapp):
        """Every phrase on screen is either Italian or not a phrase at all."""
        window._apply_language(Language.ITALIAN)
        pump(qapp)

        english = {k for k, v in _CATALOGUE.items() if k != v}
        offenders = sorted(
            {text for _where, text in self._visible_text(window) if text in english}
        )
        assert not offenders, f"still in English: {offenders}"

    def test_switching_back_restores_english(self, window, qapp):
        window._apply_language(Language.ITALIAN)
        pump(qapp)
        assert window._actions["file.save"].text() == "&Salva"

        window._apply_language(Language.ENGLISH)
        pump(qapp)
        assert window._actions["file.save"].text() == "&Save"

    def test_the_menu_bar_is_translated(self, window, qapp):
        window._apply_language(Language.ITALIAN)
        pump(qapp)
        titles = [a.text() for a in window.menuBar().actions()]
        assert titles == ["&File", "&Modifica", "&Visualizza", "&Pagine", "&Strumenti", "&Aiuto"]

    def test_the_choice_is_remembered(self, window, qapp):
        window._apply_language(Language.ITALIAN)
        assert window._settings.get("language") == "it"
        assert window._chosen_language() is Language.ITALIAN

    def test_an_unset_choice_follows_the_desktop(self, window, monkeypatch):
        """The rule for a first run, which is when it actually matters."""
        window._settings.set("language", "")
        monkeypatch.setattr(
            "orion.ui.main_window.QLocale",
            type("L", (), {"system": staticmethod(lambda: type("S", (), {"name": staticmethod(lambda: "it_IT")})())}),
        )
        assert window._chosen_language() is Language.ITALIAN

    @pytest.mark.parametrize("language", [Language.ENGLISH, Language.ITALIAN])
    def test_the_language_menu_sits_above_the_theme_menu(self, window, qapp, language):
        """Asked for in that order, and true in whichever language is on.

        Stated in both because the window may already be Italian: the setting
        is persisted, and an earlier test in this file writes it.
        """
        from PySide6.QtWidgets import QMenu

        window._apply_language(language)
        pump(qapp)
        help_menu = [
            menu
            for menu in window.menuBar().findChildren(QMenu)
            if menu.title() == tr("&Help")
        ][0]
        titles = [a.text() for a in help_menu.actions() if a.text()]
        assert titles.index(tr("&Language")) < titles.index(tr("&Theme"))

    def test_both_languages_are_offered_in_their_own_name(self, window):
        """Somebody in the wrong language is looking for the word they know."""
        assert window._actions["view.language_en"].text() == "English"
        assert window._actions["view.language_it"].text() == "Italiano"
