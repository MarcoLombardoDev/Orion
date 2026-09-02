#!/usr/bin/env python
# Orion — PDF Editor for Desktop
# Copyright (C) 2026 Marco Lombardo
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# Distributed WITHOUT ANY WARRANTY; see LICENSE for the full terms.
# A commercial licence, without the AGPL's obligations, is available for use
# in proprietary or closed-source products — see COMMERCIAL-LICENSE.md.

"""Regenerate the screenshots in ``docs/images/``.

Run it rather than taking them by hand::

    python tools/make_screenshots.py

Two reasons. The pictures in a README go stale the moment the interface moves,
and nobody notices because looking at them is not part of anyone's routine; and
a screenshot taken by hand shows whatever document happened to be open, which
is usually somebody's real work. This builds its own document, puts one of
everything on it, and grabs the window in both themes — so the same command a
year from now produces the same picture of whatever Orion has become.

It runs under the offscreen platform, so it needs no display and works in a
container. ``QWidget.grab`` renders the widget tree into a pixmap directly,
which is why that works at all.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

OUTPUT = REPO / "docs" / "images"
SIZE = (1280, 840)


def _sample_document(path: Path) -> Path:
    """A plausible letter, so the screenshot shows Orion doing something."""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    width, height = A4
    pdf = canvas.Canvas(str(path), pagesize=A4)
    for page in range(3):
        pdf.setFont("Helvetica-Bold", 17)
        pdf.drawString(64, height - 96, "Quarterly Review")
        pdf.setFont("Helvetica", 10.5)
        pdf.drawString(64, height - 116, f"Section {page + 1} of 3 — internal circulation")

        pdf.setFont("Helvetica", 11)
        lines = [
            "",
            "The figures below cover the three months to the end of the period and",
            "have not yet been audited. They are circulated for comment only.",
            "",
            "Account manager: Mario Rossi",
            "Reference: RSSMRA-80A01-H501U",
            "",
            "Revenue rose against the same quarter last year, with the increase",
            "concentrated in the second half. Costs were flat in absolute terms.",
            "",
            "The committee is asked to note the position and to confirm that the",
            "reporting timetable for the next quarter remains unchanged.",
        ]
        y = height - 156
        for line in lines:
            pdf.drawString(64, y, line)
            y -= 17
        pdf.showPage()
    pdf.save()
    return path


def _populate(window) -> None:
    """Put one of each kind of object on the first page.

    Chosen to show what Orion is for rather than to fill space: a redaction
    over a name, a highlight on the sentence that matters, a note in the
    margin, and a watermark saying the document is a draft.
    """
    from orion.document.annotations import AnnotationKind, AnnotationObject
    from orion.document.objects import RedactionObject, ShapeKind, ShapeObject
    from orion.pdf.fonts import FontRequest
    from orion.pdf.stamps import WatermarkSpec, watermark_for
    from orion.pdf.text_layout import measure
    from orion.utils.geometry import Rect

    page = window.session.document[0]
    renderer = window._canvas.render_service.renderer

    lines = renderer.source_text_lines(page)
    by_text = {line.text.strip(): line for line in lines}

    name = by_text.get("Account manager: Mario Rossi")
    if name is not None:
        # Measured rather than guessed: the box has to start where the label
        # ends, and a couple of points either way leaves half a letter showing.
        label = "Account manager: "
        request = FontRequest("Helvetica")
        before = measure(label, request, 11.0)
        across = measure(name.text.strip(), request, 11.0)
        page.add_object(
            RedactionObject(
                rect=Rect.from_xywh(
                    name.rect.x0 + before - 1.0,
                    name.hit_box.y0,
                    across - before + 2.0,
                    name.hit_box.height,
                )
            )
        )

    sentence = by_text.get(
        "Revenue rose against the same quarter last year, with the increase"
    )
    if sentence is not None:
        page.add_object(
            AnnotationObject(
                rect=sentence.rect,
                annotation=AnnotationKind.HIGHLIGHT,
                quads=[sentence.rect],
                color=(1.0, 0.92, 0.23),
            )
        )

    page.add_object(
        AnnotationObject(
            rect=Rect.from_xywh(452.0, 236.0, 20.0, 20.0),
            annotation=AnnotationKind.COMMENT,
            contents="Confirm before circulating",
            author="Reviewer",
        )
    )

    # Framing the closing paragraph, so the rectangle reads as a note about
    # something rather than as a stray box laid across the words.
    ask = by_text.get(
        "The committee is asked to note the position and to confirm that the"
    )
    if ask is not None:
        page.add_object(
            ShapeObject(
                rect=Rect.from_xywh(
                    ask.rect.x0 - 6.0,
                    ask.hit_box.y0 - 4.0,
                    ask.rect.width + 12.0,
                    ask.hit_box.height * 2.0 + 8.0,
                ),
                shape=ShapeKind.RECTANGLE,
                stroke_color=(0.11, 0.42, 0.74),
                stroke_width=1.4,
            )
        )

    page.add_object(watermark_for(page, WatermarkSpec(text="DRAFT", font_size=64.0)))
    window._canvas.rebuild()


def main() -> int:
    from PySide6.QtWidgets import QApplication

    from orion.services.settings import Settings
    from orion.ui.canvas import ZoomMode
    from orion.ui.main_window import MainWindow
    from orion.ui.theme import ThemeMode

    application = QApplication.instance() or QApplication([])
    application.setStyle("Fusion")

    import tempfile

    with tempfile.TemporaryDirectory() as scratch:
        scratch_path = Path(scratch)
        sample = _sample_document(scratch_path / "quarterly-review.pdf")
        settings = Settings(scratch_path / "settings.json")
        window = MainWindow(settings)
        window.resize(*SIZE)
        window.show()
        application.processEvents()

        if not window.open_path(sample):
            print("could not open the sample document", file=sys.stderr)
            return 1
        for _ in range(30):
            application.processEvents()
        _populate(window)
        window._canvas.set_zoom_mode(ZoomMode.FIT_PAGE)
        for _ in range(60):
            application.processEvents()

        OUTPUT.mkdir(parents=True, exist_ok=True)
        for mode, name in ((ThemeMode.LIGHT, "orion-light"), (ThemeMode.DARK, "orion-dark")):
            window._apply_theme(mode)
            for _ in range(60):
                application.processEvents()
            target = OUTPUT / f"{name}.png"
            window.grab().save(str(target), "PNG")
            print(f"wrote {target.relative_to(REPO)}")

        window._autosave_timer.stop()
        window._detach_session()
        window.close()
        application.processEvents()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
