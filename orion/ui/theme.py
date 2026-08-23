# Orion — PDF Editor for Desktop
# Copyright (C) 2026 Marco Lombardo
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# Distributed WITHOUT ANY WARRANTY; see LICENSE for the full terms.
# A commercial licence, without the AGPL's obligations, is available for use
# in proprietary or closed-source products — see COMMERCIAL-LICENSE.md.

"""Light and dark themes (spec §31).

Colours are defined once, as tokens, and everything else — the Qt palette, the
stylesheet, the canvas chrome and the icons — derives from them.  That is what
makes adding a theme a data change rather than a code change.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette

__all__ = ["ThemeMode", "Theme", "LIGHT", "DARK", "resolve_theme", "apply_theme"]


class ThemeMode(str, Enum):
    SYSTEM = "system"
    LIGHT = "light"
    DARK = "dark"


@dataclass(frozen=True, slots=True)
class Theme:
    """A complete colour scheme."""

    name: str
    is_dark: bool
    window: str
    surface: str
    surface_alt: str
    border: str
    text: str
    text_muted: str
    accent: str
    accent_text: str
    canvas: str
    page_shadow: str
    selection: str
    handle: str
    handle_border: str
    search_hit: str
    search_current: str
    danger: str

    def color(self, token: str) -> QColor:
        return QColor(getattr(self, token))


LIGHT = Theme(
    name="light",
    is_dark=False,
    window="#f4f5f7",
    surface="#ffffff",
    surface_alt="#eceef1",
    border="#d3d7de",
    text="#1c1f24",
    text_muted="#6b7280",
    accent="#2f6feb",
    accent_text="#ffffff",
    canvas="#9aa1ab",
    page_shadow="#00000033",
    selection="#2f6feb",
    handle="#ffffff",
    handle_border="#2f6feb",
    search_hit="#ffd54a",
    search_current="#ff8f2e",
    danger="#d64545",
)

DARK = Theme(
    name="dark",
    is_dark=True,
    window="#1e2128",
    surface="#272b33",
    surface_alt="#2f343d",
    border="#3c424d",
    text="#e6e8ec",
    text_muted="#9aa2af",
    accent="#5b8dff",
    accent_text="#0d1017",
    canvas="#15171c",
    page_shadow="#00000066",
    selection="#5b8dff",
    handle="#0d1017",
    handle_border="#5b8dff",
    search_hit="#c8a020",
    search_current="#e07b1f",
    danger="#e06c6c",
)


def resolve_theme(mode: ThemeMode | str) -> Theme:
    """Turn a stored preference into a concrete theme.

    ``SYSTEM`` follows Qt's own light/dark hint, so Orion matches the desktop.
    """
    mode = ThemeMode(mode)
    if mode is ThemeMode.LIGHT:
        return LIGHT
    if mode is ThemeMode.DARK:
        return DARK

    try:
        from PySide6.QtGui import QGuiApplication

        app = QGuiApplication.instance()
        if app is not None and app.styleHints().colorScheme() == Qt.ColorScheme.Dark:
            return DARK
    except Exception:  # pragma: no cover - very old Qt builds
        pass
    return LIGHT


def build_palette(theme: Theme) -> QPalette:
    palette = QPalette()
    role = QPalette.ColorRole
    group = QPalette.ColorGroup

    palette.setColor(role.Window, theme.color("window"))
    palette.setColor(role.WindowText, theme.color("text"))
    palette.setColor(role.Base, theme.color("surface"))
    palette.setColor(role.AlternateBase, theme.color("surface_alt"))
    palette.setColor(role.Text, theme.color("text"))
    palette.setColor(role.Button, theme.color("surface"))
    palette.setColor(role.ButtonText, theme.color("text"))
    palette.setColor(role.Highlight, theme.color("accent"))
    palette.setColor(role.HighlightedText, theme.color("accent_text"))
    palette.setColor(role.ToolTipBase, theme.color("surface"))
    palette.setColor(role.ToolTipText, theme.color("text"))
    palette.setColor(role.PlaceholderText, theme.color("text_muted"))
    palette.setColor(role.Link, theme.color("accent"))

    disabled = theme.color("text_muted")
    for disabled_role in (role.WindowText, role.Text, role.ButtonText):
        palette.setColor(group.Disabled, disabled_role, disabled)
    return palette


def stylesheet(theme: Theme) -> str:
    """A restrained stylesheet: spacing and separators, not a skin."""
    return f"""
    QMainWindow, QDialog {{ background: {theme.window}; }}
    QToolBar {{
        background: {theme.surface};
        border: 0px;
        border-bottom: 1px solid {theme.border};
        padding: 4px 6px;
        spacing: 2px;
    }}
    QToolBar::separator {{
        background: {theme.border};
        width: 1px;
        margin: 5px 6px;
    }}
    QToolButton {{
        border: 1px solid transparent;
        border-radius: 5px;
        padding: 4px;
        color: {theme.text};
    }}
    QToolButton:hover {{ background: {theme.surface_alt}; }}
    QToolButton:checked {{
        background: {theme.accent};
        border-color: {theme.accent};
        color: {theme.accent_text};
    }}
    QToolButton::menu-indicator {{ width: 0px; }}
    QStatusBar {{
        background: {theme.surface};
        border-top: 1px solid {theme.border};
        color: {theme.text_muted};
    }}
    QStatusBar QLabel {{ color: {theme.text_muted}; padding: 0 8px; }}
    QDockWidget {{ color: {theme.text}; titlebar-close-icon: none; }}
    QDockWidget::title {{
        background: {theme.surface_alt};
        padding: 6px 8px;
        border-bottom: 1px solid {theme.border};
        font-weight: 600;
    }}
    QListView {{
        background: {theme.surface};
        border: 0px;
        outline: 0;
    }}
    QListView::item:selected {{ background: {theme.accent}; color: {theme.accent_text}; }}
    QGroupBox {{
        border: 1px solid {theme.border};
        border-radius: 6px;
        margin-top: 12px;
        padding-top: 8px;
        font-weight: 600;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        left: 8px;
        padding: 0 4px;
        color: {theme.text_muted};
    }}
    QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit, QTextEdit {{
        background: {theme.surface};
        border: 1px solid {theme.border};
        border-radius: 5px;
        padding: 3px 6px;
        color: {theme.text};
        selection-background-color: {theme.accent};
        selection-color: {theme.accent_text};
    }}
    QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus,
    QPlainTextEdit:focus, QTextEdit:focus {{ border-color: {theme.accent}; }}
    QPushButton {{
        background: {theme.surface};
        border: 1px solid {theme.border};
        border-radius: 5px;
        padding: 5px 14px;
        color: {theme.text};
    }}
    QPushButton:hover {{ background: {theme.surface_alt}; }}
    QPushButton:default {{
        background: {theme.accent};
        border-color: {theme.accent};
        color: {theme.accent_text};
    }}
    QPushButton:disabled {{ color: {theme.text_muted}; }}
    QScrollBar:vertical {{ background: transparent; width: 12px; margin: 0; }}
    QScrollBar:horizontal {{ background: transparent; height: 12px; margin: 0; }}
    QScrollBar::handle {{ background: {theme.border}; border-radius: 6px; min-height: 28px; }}
    QScrollBar::handle:hover {{ background: {theme.text_muted}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}
    QMenuBar {{ background: {theme.surface}; color: {theme.text}; }}
    QMenuBar::item:selected {{ background: {theme.surface_alt}; }}
    QMenu {{
        background: {theme.surface};
        border: 1px solid {theme.border};
        padding: 4px;
    }}
    QMenu::item {{ padding: 5px 26px 5px 22px; border-radius: 4px; }}
    QMenu::item:selected {{ background: {theme.accent}; color: {theme.accent_text}; }}
    QMenu::separator {{ height: 1px; background: {theme.border}; margin: 4px 8px; }}
    QSplitter::handle {{ background: {theme.border}; }}
    QLabel[role="hint"] {{ color: {theme.text_muted}; }}
    """


def apply_theme(app, theme: Theme) -> None:
    """Apply *theme* to a ``QApplication``."""
    app.setPalette(build_palette(theme))
    app.setStyleSheet(stylesheet(theme))
