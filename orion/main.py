# Orion — PDF Editor for Desktop
# Copyright (C) 2026 Marco Lombardo
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# Distributed WITHOUT ANY WARRANTY; see LICENSE for the full terms.
# A commercial licence, without the AGPL's obligations, is available for use
# in proprietary or closed-source products — see COMMERCIAL-LICENSE.md.

"""Application entry point.

Responsibilities kept deliberately small: configure logging, create the
``QApplication``, install a last-resort exception handler so a bug becomes a
log entry and a message rather than a silent crash, and show the window.
"""

from __future__ import annotations

import argparse
import logging
import os
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
        "--self-check",
        action="store_true",
        help="start Qt, report the platform plugin in use, and exit without a window",
    )
    parser.add_argument(
        "--log-level",
        default=None,
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="verbosity of the log file and console output",
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def _apply_stylesheet(app) -> None:
    """Give the interface the palette Iris and Proteus have.

    Those two get theirs from ttkbootstrap's "flatly". This is Qt, so the
    library cannot be shared -- only the numbers can, and they are the numbers
    that matter: the same white ground, the same near-black text, the same
    dark navy on anything primary.

    A missing or unreadable stylesheet leaves the platform's own look, which
    is a perfectly good interface. It is not worth failing to start over.
    """
    from orion.utils.paths import resources_dir

    sheet = resources_dir() / "styles" / "orion.qss"
    try:
        app.setStyleSheet(sheet.read_text(encoding="utf-8"))
    except OSError:
        log.debug("No stylesheet at %s; using the platform look", sheet)


def _set_application_icon(app) -> None:
    """Use the bundled application icon, if it is where we expect it."""
    from PySide6.QtGui import QIcon

    from orion.utils.paths import resources_dir

    candidate = resources_dir() / "icons" / "orion.png"
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


def _round_trip() -> str:
    """Write a small document and read it back. Returns a one-line report.

    The release smoke test used to stop at "Qt started", which leaves the
    entire PDF engine untested in the artefact that actually ships. That is the
    wrong half to skip: a frozen bundle breaks by *missing a file* — a data
    directory PyInstaller did not collect, a shared library it did not find —
    and every one of those failures happens the first time a user saves, not at
    startup. The test suite cannot see them either, because it runs against an
    installed package where nothing is missing.

    So this does the smallest thing that touches all four libraries: build a
    page with text, a shape and an annotation, save it, and open the result.
    Writing exercises reportlab's font metrics and pypdf's assembly; reading
    back exercises pdfium; and finding the text again proves the glyphs were
    written as text rather than as a picture of text.
    """
    import tempfile
    from pathlib import Path

    from orion.document.annotations import AnnotationKind, AnnotationObject
    from orion.document.document import Document
    from orion.document.objects import ShapeKind, ShapeObject, TextObject
    from orion.document.page import Page
    from orion.pdf import reader, writer
    from orion.utils.geometry import Rect, Size

    needle = "ORION SELF CHECK"
    page = Page(base_size=Size(400.0, 600.0))
    page.add_object(
        TextObject(rect=Rect.from_xywh(40.0, 60.0, 320.0, 60.0), text=needle, font_size=16.0)
    )
    page.add_object(
        ShapeObject(
            rect=Rect.from_xywh(40.0, 160.0, 120.0, 80.0),
            shape=ShapeKind.RECTANGLE,
            stroke_color=(1.0, 0.0, 0.0),
        )
    )
    page.add_object(
        AnnotationObject(
            rect=Rect.from_xywh(40.0, 60.0, 320.0, 20.0),
            annotation=AnnotationKind.HIGHLIGHT,
            quads=[Rect.from_xywh(40.0, 60.0, 320.0, 20.0)],
        )
    )

    with tempfile.TemporaryDirectory(prefix="orion-self-check-") as directory:
        target = Path(directory) / "self-check.pdf"
        result = writer.save_document(Document(pages=[page]), target)
        opened = reader.open_pdf(target)
        try:
            from orion.pdf.renderer import PageRenderer

            renderer = PageRenderer(cache_bytes=4 * 1024 * 1024)
            document = reader.build_document(opened)
            renderer.register_source(next(iter(document.sources.values())), opened)
            found = needle in renderer.page_text(document[0])
            rendered = renderer.render(renderer.request_for(document[0], 1.0))
        finally:
            opened.close()

    if not found:
        raise RuntimeError("the text written to the page could not be read back")
    return (
        f"round trip: wrote {result.bytes_written} bytes, "
        f"read back {result.page_count} page, "
        f"rendered {rendered.width}x{rendered.height}, text found"
    )


def _self_check(app) -> int:
    """Report that Qt came up, on which platform plugin, and that saving works.

    This exists for the release smoke test. ``--version`` is not a smoke test:
    argparse prints and exits before PySide6 is ever imported, so a bundle
    whose Qt platform plugin is missing or unloadable passes it and then fails
    on the user's desktop. Constructing QApplication is the cheapest thing that
    actually proves the plugin loaded — Qt aborts the process if it cannot find
    one — and naming the plugin makes the difference between a real backend and
    a headless fallback visible in the build log rather than assumed.
    """
    from PySide6.QtWidgets import QStyleFactory

    platform = app.platformName()
    print(f"{APP_NAME} {__version__}")
    print(f"platform plugin: {platform}")
    print(f"styles: {', '.join(QStyleFactory.keys())}")
    if not platform:
        log.error("Qt started without a platform plugin")
        return 1

    try:
        print(_round_trip())
    except Exception as exc:
        log.exception("The PDF round trip failed")
        print(f"round trip: FAILED — {exc}")
        return 1
    return 0


def _pin_graphics_backend() -> None:
    """Tell Qt which graphics backend to use, so it does not go and ask.

    Left to itself on Windows, Qt works out what the machine can do before it
    opens a window, and part of that is asking the system about the display
    adapter and its driver. The usual way to ask that question is a WMI query,
    and a WMI query is also how a good deal of reconnaissance starts — so an
    endpoint agent watching a freshly downloaded, unsigned, PyInstaller-built
    executable make one reports enumeration, which is exactly what happened.

    Orion has no use for the answer. Everything it draws goes through
    ``QPainter`` onto a ``QGraphicsView``, which is the raster path; it owns
    no OpenGL widget and no scene graph. Naming the software backend costs it
    nothing and removes the reason to look.

    Set as environment variables because Qt reads them when the platform
    plugin loads, which is during ``QApplication``'s constructor and therefore
    before any attribute could be set on it. Not overwritten if they are
    already there: somebody debugging a display problem has to be able to ask
    for the other path.
    """
    if sys.platform != "win32":
        return
    os.environ.setdefault("QT_OPENGL", "software")
    os.environ.setdefault("QSG_RHI_BACKEND", "software")


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    setup_logging(args.log_level)
    log.info("Starting %s %s", APP_NAME, __version__)

    _pin_graphics_backend()

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

    if args.self_check:
        return _self_check(app)

    from orion.services.clipboard import release_system_clipboard
    from orion.ui.main_window import MainWindow

    app.aboutToQuit.connect(release_system_clipboard)

    _apply_stylesheet(app)

    window = MainWindow()
    _install_exception_hook(window)
    # Always maximised, whatever was saved. The restored geometry is not
    # discarded by this: Qt keeps it as the window's normal size, so
    # un-maximising returns to wherever the last session left it.
    window.showMaximized()

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
