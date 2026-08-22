"""Application entry point.

Responsibilities kept deliberately small: configure logging, create the
``QApplication``, install a last-resort exception handler so a bug becomes a
log entry and a message rather than a silent crash, and show the window.
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence
from contextlib import suppress
from pathlib import Path

from orion import APP_NAME, ORGANISATION, __version__
from orion.utils.logging import setup_logging

log = logging.getLogger(__name__)

__all__ = ["main"]


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="orion", description=f"{APP_NAME} — PDF Editor for Desktop"
    )
    parser.add_argument("files", nargs="*", type=Path, help="PDF files to open")
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {__version__}")
    parser.add_argument(
        "--log-level",
        default=None,
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="verbosity of the log file and console output",
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def _set_application_icon(app) -> None:
    """Use the bundled application icon, if it is where we expect it."""
    from PySide6.QtGui import QIcon

    from orion.utils.paths import resources_dir

    for name in ("orion.png", "orion.svg"):
        candidate = resources_dir() / "icons" / name
        if candidate.exists():
            app.setWindowIcon(QIcon(str(candidate)))
            return
    log.debug("No application icon found; using the platform default")


def _install_exception_hook(window) -> None:
    """Turn an unexpected exception into a log entry and a readable message."""
    from PySide6.QtWidgets import QMessageBox

    def hook(exc_type, exc_value, traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, traceback)
            return
        log.critical("Unhandled exception", exc_info=(exc_type, exc_value, traceback))
        with suppress(Exception):  # pragma: no cover - the UI may already be gone
            QMessageBox.critical(
                window,
                f"{APP_NAME} — Unexpected Error",
                "Something went wrong and the last action could not be completed.\n\n"
                "Your document has not been written to disk. Details were written "
                "to the log file (Help ▸ Open Log Folder).",
            )

    sys.excepthook = hook


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    setup_logging(args.log_level)
    log.info("Starting %s %s", APP_NAME, __version__)

    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    QApplication.setApplicationName(APP_NAME)
    QApplication.setApplicationDisplayName(APP_NAME)
    QApplication.setOrganizationName(ORGANISATION)
    QApplication.setApplicationVersion(__version__)
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_DontShowIconsInMenus, False)

    app = QApplication(sys.argv[:1] + [])
    app.setStyle("Fusion")  # the one style that looks the same on every platform
    _set_application_icon(app)

    from orion.services.clipboard import release_system_clipboard
    from orion.ui.main_window import MainWindow

    app.aboutToQuit.connect(release_system_clipboard)

    window = MainWindow()
    _install_exception_hook(window)
    window.show()

    for path in args.files:
        if window.open_path(Path(path)):
            break

    try:
        return app.exec()
    finally:
        # Belt and braces: aboutToQuit normally fires first, but this also
        # covers an exec() that returns without it.  The call is idempotent.
        release_system_clipboard()


if __name__ == "__main__":  # pragma: no cover - thin wrapper
    raise SystemExit(main())
