# Orion — PDF Editor for Desktop
# Copyright (C) 2026 Marco Lombardo
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# Distributed WITHOUT ANY WARRANTY; see LICENSE for the full terms.
# A commercial licence, without the AGPL's obligations, is available for use
# in proprietary or closed-source products — see COMMERCIAL-LICENSE.md.

"""GUI tests (spec §27 "per la GUI, creare test dove ragionevole").

These drive the real widgets on Qt's offscreen platform, so they exercise the
wiring between the canvas, the model and the command history rather than
mocking it.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QPointF, Qt  # noqa: E402

from orion.document.annotations import AnnotationKind, AnnotationObject  # noqa: E402
from orion.document.objects import ShapeKind, ShapeObject, TextObject  # noqa: E402
from orion.ui.canvas import ZoomMode  # noqa: E402
from orion.ui.page_item import base_to_display_transform  # noqa: E402
from orion.ui.theme import DARK, LIGHT, ThemeMode  # noqa: E402
from orion.ui.tools import Tool  # noqa: E402
from orion.utils.geometry import Point, Rect  # noqa: E402
from tests.conftest import pump, wait_until


def _shape(x: float = 40.0, y: float = 60.0) -> ShapeObject:
    return ShapeObject(
        rect=Rect.from_xywh(x, y, 90.0, 50.0),
        shape=ShapeKind.RECTANGLE,
        stroke_color=(1.0, 0.0, 0.0),
    )


# -- opening -------------------------------------------------------------
def test_opening_populates_every_panel(window, qapp, sample_pdf):
    assert window.open_path(sample_pdf)
    pump(qapp)
    assert window.session is not None
    assert window._canvas.page_count == 3
    assert window._thumbnails.count() == 3
    assert window._status._page.text() == "Page 1 / 3"
    assert window.windowTitle().startswith("sample.pdf")


def test_opening_a_broken_file_leaves_no_session(window, qapp, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "exec", lambda self: QMessageBox.StandardButton.Ok)
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"not a pdf at all")
    assert window.open_path(broken) is False
    assert window.session is None


def test_actions_are_disabled_without_a_document(window):
    assert not window._actions["file.save"].isEnabled()
    assert not window._actions["pages.split"].isEnabled()
    assert window._actions["file.open"].isEnabled()


# -- rendering -----------------------------------------------------------
def test_pages_actually_rasterise(window, qapp, sample_pdf):
    window.open_path(sample_pdf)
    page_item = window._canvas._page_items[0]
    assert wait_until(qapp, lambda: page_item._image is not None), (
        "the page was never rasterised"
    )
    assert page_item._image.width() > 100


# -- zoom ----------------------------------------------------------------
def test_zoom_modes_and_steps(window, qapp, sample_pdf):
    window.open_path(sample_pdf)
    pump(qapp)
    window._canvas.set_zoom(1.0)
    window._canvas.zoom_in()
    assert window._canvas.zoom > 1.0
    window._canvas.zoom_out()
    assert window._canvas.zoom == pytest.approx(1.0)

    window._canvas.set_zoom_mode(ZoomMode.FIT_WIDTH)
    pump(qapp)
    assert window._canvas.zoom_mode is ZoomMode.FIT_WIDTH
    assert window._status._mode.text() == "Fit Width"


# -- object creation through the canvas ----------------------------------
def test_canvas_creates_a_shape_from_a_drag(window, qapp, sample_pdf):
    window.open_path(sample_pdf)
    pump(qapp)
    _drag(window, Tool.RECTANGLE, (40.0, 200.0), (180.0, 280.0))
    pump(qapp)

    objects = window.session.document[0].objects
    assert len(objects) == 1
    shape = objects[0]
    assert isinstance(shape, ShapeObject) and shape.shape is ShapeKind.RECTANGLE
    assert shape.rect.x0 == pytest.approx(40.0, abs=1.5)
    assert shape.rect.width == pytest.approx(140.0, abs=1.5)
    # A one-shot tool hands control back to Select once the object exists.
    assert window._canvas.tool is Tool.SELECT


def test_markup_snaps_to_the_page_text(window, qapp, sample_pdf):
    window.open_path(sample_pdf)
    pump(qapp)
    _drag(window, Tool.HIGHLIGHT, (45.0, 78.0), (200.0, 106.0))
    pump(qapp)

    objects = window.session.document[0].objects
    assert len(objects) == 1
    annotation = objects[0]
    assert isinstance(annotation, AnnotationObject)
    assert annotation.annotation is AnnotationKind.HIGHLIGHT
    assert annotation.quads, "the highlight must snap to real text lines"


def test_text_tool_opens_the_inline_editor(window, qapp, sample_pdf):
    window.open_path(sample_pdf)
    pump(qapp)
    _drag(window, Tool.TEXT, (40.0, 300.0), (260.0, 350.0))
    pump(qapp)

    texts = [o for o in window.session.document[0].objects if isinstance(o, TextObject)]
    assert len(texts) == 1
    item = window._canvas._item_index[texts[0].id]
    assert item.is_editing
    item._editor._item.setPlainText("Typed on the canvas")
    item.end_editing(commit=True)
    assert texts[0].text == "Typed on the canvas"
    assert window.session.history.undo_text == "Edit Text"


# -- selection and clipboard ---------------------------------------------
def test_copy_paste_and_undo(window, qapp, sample_pdf):
    window.open_path(sample_pdf)
    pump(qapp)
    document = window.session.document
    document[0].add_object(_shape())
    document.notify_content_changed(0)
    pump(qapp)

    window._canvas.select_all_on_current_page()
    pump(qapp)
    assert len(window._canvas.selected_objects()) == 1

    window._copy_selection(cut=False)
    window.paste()
    pump(qapp)
    assert len(document[0].objects) == 2
    # The pasted copy is offset so it does not hide the original.
    assert document[0].objects[1].rect.x0 != document[0].objects[0].rect.x0

    window.undo()
    assert len(document[0].objects) == 1
    window.redo()
    assert len(document[0].objects) == 2


def test_delete_and_undo_through_the_window(window, qapp, sample_pdf):
    window.open_path(sample_pdf)
    pump(qapp)
    document = window.session.document
    shape = _shape()
    document[0].add_object(shape)
    document.notify_content_changed(0)
    pump(qapp)

    window._canvas.select_objects([shape.id])
    window.delete_selection()
    pump(qapp)
    assert len(document[0].objects) == 0
    window.undo()
    pump(qapp)
    assert len(document[0].objects) == 1


def test_arrow_keys_nudge_the_selection(window, qapp, sample_pdf):
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QKeyEvent

    window.open_path(sample_pdf)
    pump(qapp)
    document = window.session.document
    shape = _shape()
    document[0].add_object(shape)
    document.notify_content_changed(0)
    pump(qapp)
    window._canvas.select_objects([shape.id])

    event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Right, Qt.KeyboardModifier.NoModifier)
    window._canvas.keyPressEvent(event)
    assert shape.rect.x0 == pytest.approx(41.0)
    window.undo()
    assert shape.rect.x0 == pytest.approx(40.0)


# -- pages ---------------------------------------------------------------
def test_page_rotation_updates_canvas_and_model(window, qapp, sample_pdf):
    window.open_path(sample_pdf)
    pump(qapp)
    window.rotate_pages(90, [0])
    pump(qapp)

    page = window.session.document[0]
    assert page.rotation == 90
    assert page.display_size.width == pytest.approx(600.0)
    item = window._canvas._page_items[0]
    assert item.boundingRect().width() == pytest.approx(600.0)


def test_page_reorder_from_thumbnails(window, qapp, sample_pdf):
    window.open_path(sample_pdf)
    pump(qapp)
    ids = [p.id for p in window.session.document]
    window._on_pages_reordered(0, 2)
    pump(qapp)
    assert [p.id for p in window.session.document] == [ids[1], ids[2], ids[0]]
    window.undo()
    assert [p.id for p in window.session.document] == ids


def test_delete_pages_asks_first(window, qapp, sample_pdf, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    window.open_path(sample_pdf)
    pump(qapp)
    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Cancel
    )
    window.delete_pages([0])
    assert window.session.document.page_count == 3

    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    window.delete_pages([0])
    pump(qapp)
    assert window.session.document.page_count == 2


# -- search --------------------------------------------------------------
def test_search_finds_and_navigates(window, qapp, sample_pdf):
    window.open_path(sample_pdf)
    pump(qapp)
    window._search._search("NEEDLE")
    pump(qapp)
    assert len(window._search._hits) == 3
    assert window._search.current_hit is not None
    first = window._search.current_hit
    window._search.find_next()
    assert window._search.current_hit != first
    assert window._canvas._page_items[0]._search_hits


# -- saving --------------------------------------------------------------
def test_save_round_trip_through_the_window(window, qapp, sample_pdf, tmp_path):
    from tests.conftest import PdfProbe

    window.open_path(sample_pdf)
    pump(qapp)
    document = window.session.document
    document[0].add_object(
        TextObject(rect=Rect.from_xywh(40, 250, 300, 40), text="WINDOW SAVE", font_size=18)
    )
    document.notify_content_changed(0)
    pump(qapp)
    assert window.session.is_modified

    out = tmp_path / "window-save.pdf"
    assert window._write(window.session, out)
    assert not window.session.is_modified
    assert window.windowTitle().startswith("window-save.pdf")

    with PdfProbe(out) as probe:
        assert "WINDOW SAVE" in probe.text(0)


def test_closing_a_modified_document_can_be_cancelled(window, qapp, sample_pdf, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    window.open_path(sample_pdf)
    pump(qapp)
    window.session.document[0].add_object(_shape())
    window.session.document.notify_content_changed(0)

    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: QMessageBox.StandardButton.Cancel)
    assert window.close_document() is False
    assert window.session is not None

    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: QMessageBox.StandardButton.Discard)
    assert window.close_document() is True
    assert window.session is None


# -- theming -------------------------------------------------------------
def test_theme_switch_reaches_every_widget(window, qapp):
    window._apply_theme(ThemeMode.DARK)
    assert window._canvas.theme is DARK
    assert window._thumbnails.theme is DARK
    window._apply_theme(ThemeMode.LIGHT)
    assert window._canvas.theme is LIGHT


# -- coordinate agreement -------------------------------------------------
@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_canvas_transform_matches_the_model(rotation):
    """The Qt transform and ``Page.base_to_display`` must never diverge."""
    from orion.document.page import Page
    from orion.utils.geometry import Size

    page = Page(base_size=Size(400.0, 600.0), rotation=rotation)
    transform = base_to_display_transform(page)
    for point in (Point(0, 0), Point(400, 600), Point(37.5, 211.25)):
        expected = page.base_to_display(point)
        mapped = transform.map(QPointF(point.x, point.y))
        assert mapped.x() == pytest.approx(expected.x, abs=1e-6)
        assert mapped.y() == pytest.approx(expected.y, abs=1e-6)


# -- helpers -------------------------------------------------------------
def _drag(window, tool: Tool, start: tuple[float, float], end: tuple[float, float]) -> None:
    """Simulate press-move-release on the canvas in base page coordinates."""
    from PySide6.QtCore import QEvent, QPoint
    from PySide6.QtGui import QMouseEvent

    window._on_tool_selected(tool)
    view = window._canvas
    # Drag at 100%: one viewport pixel is one PDF point, so the assertions can
    # be exact instead of absorbing the rounding of integer mouse coordinates.
    view.set_zoom(1.0)
    content = view._page_items[0].content

    def viewport_point(base: tuple[float, float]) -> QPointF:
        return QPointF(view.mapFromScene(content.mapToScene(QPointF(*base))))

    p1, p2 = viewport_point(start), viewport_point(end)
    globals_ = view.viewport().mapToGlobal(QPoint(int(p1.x()), int(p1.y())))
    view.mousePressEvent(
        QMouseEvent(
            QEvent.Type.MouseButtonPress, p1, globals_,
            Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
        )
    )
    view.mouseMoveEvent(
        QMouseEvent(
            QEvent.Type.MouseMove, p2, globals_,
            Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
        )
    )
    view.mouseReleaseEvent(
        QMouseEvent(
            QEvent.Type.MouseButtonRelease, p2, globals_,
            Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
        )
    )


# -- shortcut scoping ----------------------------------------------------
def test_canvas_only_shortcuts_do_not_fire_in_text_fields(window, qapp, sample_pdf):
    """Delete must not delete an object while the user is typing in Find."""
    from PySide6.QtCore import Qt

    window.open_path(sample_pdf)
    pump(qapp)
    for key in ("edit.delete", "edit.select_all", "edit.deselect"):
        action = window._actions[key]
        assert action.shortcutContext() == Qt.ShortcutContext.WidgetWithChildrenShortcut
        assert action in window._canvas.actions()
    # The menu still owns them, so they remain reachable and enabled normally.
    assert window._actions["edit.select_all"].isEnabled()


def test_cross_page_selection_deletes_from_both_pages(window, qapp, sample_pdf):
    """A rubber band can span pages; the delete must not silently miss one."""
    window.open_path(sample_pdf)
    pump(qapp)
    document = window.session.document
    first, second = _shape(10.0), _shape(20.0)
    document[0].add_object(first)
    document[1].add_object(second)
    document.notify_content_changed(0)
    document.notify_content_changed(1)
    pump(qapp)

    window._canvas.select_objects([first.id, second.id])
    pump(qapp)
    assert set(window._canvas.selection_by_page()) == {0, 1}

    window.delete_selection()
    pump(qapp)
    assert len(document[0].objects) == 0
    assert len(document[1].objects) == 0

    window.undo()
    pump(qapp)
    assert len(document[0].objects) == 1
    assert len(document[1].objects) == 1


def test_rebuilding_the_scene_keeps_the_reading_position(window, qapp, sample_pdf):
    window.open_path(sample_pdf)
    pump(qapp)
    window._canvas.set_zoom(1.5)
    window._canvas.go_to_page(2)
    pump(qapp)
    assert window._canvas.current_page == 2

    # Rotating a page rebuilds the scene; the reader must stay where they were.
    window.rotate_pages(90, [2])
    pump(qapp)
    assert window._canvas.current_page == 2


# -- password protected documents ----------------------------------------
def _encrypted_pdf(path, password: str = "letmein"):
    from tests.conftest import make_encrypted_pdf

    return make_encrypted_pdf(path, password, width=300.0, height=400.0)


def test_opening_a_protected_file_asks_for_the_password(window, qapp, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QInputDialog

    path = _encrypted_pdf(tmp_path / "locked.pdf")
    asked: list[str] = []

    def fake_get_text(parent, title, label, echo=None, *args, **kwargs):
        asked.append(label)
        return ("letmein", True)

    monkeypatch.setattr(QInputDialog, "getText", staticmethod(fake_get_text))
    assert window.open_path(path) is True
    assert asked and "password" in asked[0].lower()
    assert window.session is not None
    assert window.session.document.page_count == 1


def test_cancelling_the_password_prompt_opens_nothing(window, qapp, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QInputDialog

    path = _encrypted_pdf(tmp_path / "locked.pdf")
    monkeypatch.setattr(
        QInputDialog, "getText", staticmethod(lambda *a, **k: ("", False))
    )
    assert window.open_path(path) is False
    assert window.session is None


def test_a_wrong_password_does_not_loop_forever(window, qapp, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QInputDialog, QMessageBox

    path = _encrypted_pdf(tmp_path / "locked.pdf")
    attempts: list[int] = []

    def fake_get_text(*_args, **_kwargs):
        attempts.append(1)
        return ("wrong", True)

    monkeypatch.setattr(QInputDialog, "getText", staticmethod(fake_get_text))
    monkeypatch.setattr(QMessageBox, "exec", lambda self: QMessageBox.StandardButton.Ok)
    assert window.open_path(path) is False
    assert len(attempts) == 2, "the user should be asked again once, then told no"
    assert window.session is None


# -- system clipboard shutdown -------------------------------------------
def test_releasing_the_clipboard_removes_orions_payload_but_keeps_the_text(
    window, qapp, sample_pdf
):
    """Regression guard for a crash on exit.

    A QMimeData handed to QClipboard.setMimeData is still referenced by the
    clipboard when the QApplication is destroyed, and freeing it then
    segfaults the process — reproduced on PySide6 6.11 on both the offscreen
    platform and a real X11 display, with no Orion code involved.  Orion
    therefore replaces its payload with a plain-text copy on shutdown.
    """
    from PySide6.QtGui import QGuiApplication

    from orion.document.serialization import CLIPBOARD_MIME
    from orion.services.clipboard import release_system_clipboard

    window.open_path(sample_pdf)
    pump(qapp)
    document = window.session.document
    shape = _shape()
    document[0].add_object(shape)
    document.notify_content_changed(0)
    pump(qapp)

    window._canvas.select_objects([shape.id])
    window._copy_selection(cut=False)
    pump(qapp)

    clipboard = QGuiApplication.clipboard()
    if clipboard.mimeData() is None or not clipboard.mimeData().hasFormat(CLIPBOARD_MIME):
        pytest.skip("this platform has no usable system clipboard")

    release_system_clipboard()
    pump(qapp)

    data = clipboard.mimeData()
    assert data is None or not data.hasFormat(CLIPBOARD_MIME)
    # Something a normal application can still paste must survive.
    assert clipboard.text()


def test_releasing_the_clipboard_leaves_other_applications_data_alone(window, qapp):
    from PySide6.QtGui import QGuiApplication

    from orion.services.clipboard import release_system_clipboard

    clipboard = QGuiApplication.clipboard()
    clipboard.setText("something another application copied")
    release_system_clipboard()
    assert clipboard.text() == "something another application copied"


class TestLicenceNotice:
    """The copyright and licence line along the bottom of the window.

    AGPL-3.0 section 5 asks the work to carry Appropriate Legal Notices, and
    section 7(b) lets an author require attribution be preserved. Iris,
    Proteus and Argus have shown this line since their first release; Orion
    shipped v1.0.0 without one, which is what these pin against happening
    again.
    """

    def test_the_status_bar_shows_it(self, qapp):
        from PySide6.QtWidgets import QLabel

        from orion.ui.status_bar import OrionStatusBar

        bar = OrionStatusBar()
        shown = " ".join(label.text() for label in bar.findChildren(QLabel))
        assert "AGPL-3.0" in shown
        assert "Marco Lombardo" in shown

    def test_it_says_where_to_ask_about_a_commercial_licence(self, qapp):
        """"Available on request" tells the one person who might buy one
        nothing about where to ask.

        Asserted against the notice's full text rather than whatever the label
        is showing at this instant: a bar nobody has given a width to may
        already have fallen back to the short form, and that is a question
        about layout, not about whether the address exists.
        """
        from orion import CONTACT_EMAIL
        from orion.ui.status_bar import OrionStatusBar

        bar = OrionStatusBar()
        assert CONTACT_EMAIL in bar._notice_full
        assert f"mailto:{CONTACT_EMAIL}" in bar._notice_full, (
            "the address is not clickable"
        )

    def test_the_notice_survives_a_transient_message(self, qapp):
        """It steps aside while a message is showing, where the two would
        otherwise collide. The message lasts seconds; the notice has to come
        back after it, not be destroyed.
        """
        from PySide6.QtWidgets import QLabel

        from orion.ui.status_bar import OrionStatusBar

        bar = OrionStatusBar()
        bar.flash("something happened", 1)
        bar.clearMessage()
        shown = " ".join(label.text() for label in bar.findChildren(QLabel))
        assert "AGPL-3.0" in shown, "the notice was destroyed rather than hidden"

    def test_it_is_centred_on_the_whole_bar(self, qapp):
        """Not on whatever is left over. A QStatusBar lays normal widgets from
        the left and permanent ones from the right, so a notice in the layout
        slides sideways as the page and zoom indicators appear and disappear.
        The other three products give theirs a strip where nothing competes.
        """
        from PySide6.QtWidgets import QMainWindow

        from orion.ui.status_bar import OrionStatusBar

        window = QMainWindow()
        bar = OrionStatusBar()
        window.setStatusBar(bar)
        window.resize(1400, 800)
        window.show()
        qapp.processEvents()

        def offset() -> float:
            box = bar._notice.geometry()
            return abs((box.x() + box.width() / 2) - bar.width() / 2)

        assert bar._notice.isVisible()
        assert offset() <= 1, "not centred with an empty bar"

        bar.set_page(0, 10)
        bar.set_zoom(1.0, "fit_width")
        bar.set_modified(True)
        qapp.processEvents()
        assert offset() <= 1, "the indicators pushed the notice off centre"
        window.close()

    def test_it_degrades_rather_than_disappearing(self, qapp):
        """A window too narrow for the whole line is a reason to say less, not
        a reason to stop carrying the notice: the copyright and the licence
        are the part AGPL-3.0 section 5 is about.

        Swept rather than sampled at chosen widths. The first version of this
        asserted that 1400 pixels showed the full text and 950 the short one,
        which is a claim about font metrics, not about behaviour: it passed
        where it was written and failed on all three CI platforms, and on
        Windows it was right — Segoe UI made the notice wide enough that the
        address never appeared at all.
        """
        from PySide6.QtWidgets import QMainWindow

        from orion.ui.status_bar import OrionStatusBar

        window = QMainWindow()
        bar = OrionStatusBar()
        window.setStatusBar(bar)
        window.show()

        # With a document open, which is when the indicators take their share
        # of the bar and the notice has least room.
        bar.set_page(0, 10)
        bar.set_zoom(1.0, "fit_width")
        bar.set_modified(True)

        seen = []
        try:
            for width in range(1800, 200, -50):
                window.resize(width, 700)
                qapp.processEvents()
                seen.append(
                    (width, bar._notice.isVisible(), "mailto:" in bar._notice.text())
                )
        finally:
            window.close()

        widest = seen[0]
        assert widest[1], "the notice is not shown even on the widest window"
        assert widest[2], "the widest window does not show the address"

        assert not seen[-1][1], "the narrowest window still claims to show it"

        # Once it goes, it stays gone: no flapping between two adjacent widths.
        visible = [entry[1] for entry in seen]
        assert visible == sorted(visible, reverse=True), (
            f"visibility is not monotone as the window narrows: {seen}"
        )

        # And the same for the address: it is dropped once, not regained.
        addressed = [entry[2] for entry in seen if entry[1]]
        assert addressed == sorted(addressed, reverse=True), (
            f"the address comes and goes as the window narrows: {seen}"
        )

        # The point of the whole thing: there are widths where the notice is
        # still carried without the address, between "everything fits" and
        # "nothing does".
        assert any(vis and not addr for _w, vis, addr in seen), (
            "it never degrades — it goes straight from the full text to nothing"
        )

    def test_it_shows_the_address_whenever_there_is_room_for_it(self, qapp):
        """The bug this replaces, stated without a pixel in it.

        The first version required the *bar-centred* rectangle to clear the
        indicators, and gave up when it did not — so on a window with room for
        the full notice beside them it showed the short one, or nothing. On
        Windows that was a 1400-pixel window. It nudges left now instead of
        giving up, and this is what says so: if the text fits in the strip
        that is free, it must be on screen, whatever the font is doing.
        """
        from PySide6.QtWidgets import QLabel, QMainWindow

        from orion.ui.status_bar import MARGIN, OrionStatusBar

        window = QMainWindow()
        bar = OrionStatusBar()
        window.setStatusBar(bar)
        window.show()
        bar.set_page(0, 10)
        bar.set_zoom(1.0, "fit_width")
        bar.set_modified(True)

        # A label of its own, so measuring cannot disturb what is on screen.
        ruler = QLabel(bar._notice_full)
        ruler.setTextFormat(bar._notice.textFormat())
        ruler.setStyleSheet(bar._notice.styleSheet())
        ruler.setFont(bar._notice.font())

        try:
            for width in range(1800, 400, -50):
                window.resize(width, 700)
                qapp.processEvents()

                occupied = [
                    label.geometry().left()
                    for label in (bar._modified, bar._page, bar._zoom, bar._mode)
                    if label.isVisible() and label.text()
                ]
                free = (min(occupied) if occupied else bar.width()) - 2 * MARGIN
                if ruler.sizeHint().width() > free:
                    continue           # genuinely no room; nothing to prove

                assert bar._notice.isVisible(), (
                    f"hidden at {width}px with {free}px free and "
                    f"{ruler.sizeHint().width()}px needed"
                )
                assert "mailto:" in bar._notice.text(), (
                    f"shortened at {width}px with room for the whole line"
                )
        finally:
            ruler.deleteLater()
            window.close()

    def test_it_never_runs_under_the_indicators(self, qapp):
        """The reason it can be hidden at all. Overlapping them would be worse
        than either.
        """
        from PySide6.QtWidgets import QMainWindow

        from orion.ui.status_bar import OrionStatusBar

        window = QMainWindow()
        bar = OrionStatusBar()
        window.setStatusBar(bar)
        window.show()
        bar.set_page(0, 10)
        bar.set_zoom(1.0, "fit_width")
        bar.set_modified(True)

        try:
            for width in range(1800, 200, -50):
                window.resize(width, 700)
                qapp.processEvents()
                if not bar._notice.isVisible():
                    continue
                box = bar._notice.geometry()
                assert box.left() >= 0, f"off the left edge at {width}px"
                for label in (bar._modified, bar._page, bar._zoom, bar._mode):
                    if label.isVisible() and label.text():
                        assert box.right() <= label.geometry().left(), (
                            f"the notice runs under {label.text()!r} at {width}px"
                        )
        finally:
            window.close()


class TestStartsMaximised:
    """The window opens filling the screen."""

    def test_the_application_shows_it_maximised(self):
        from pathlib import Path

        repo = Path(__file__).resolve().parent.parent
        source = (repo / "orion" / "main.py").read_text(encoding="utf-8")
        assert "window.showMaximized()" in source
        assert "window.show()" not in source, (
            "showing it unmaximised as well would fight the line above"
        )

    def test_maximising_does_not_throw_away_the_remembered_size(self, qapp):
        """Qt keeps the restored geometry as the window's normal size, so
        un-maximising returns to wherever the last session left it. Losing
        that would make "always maximised" mean "the size is forgotten".
        """
        from orion.ui.main_window import MainWindow

        window = MainWindow()
        window.resize(1000, 700)
        window.showMaximized()
        qapp.processEvents()
        assert window.isMaximized()
        assert window.normalGeometry().width() > 0
        window.close()


class TestIconsOnAnActiveButton:
    """A checked toolbar button is filled with the accent. The icon inside it
    has to stop being a dark line drawing at that point, or it disappears into
    the fill — which is what was reported: the button turned blue and the icon
    went with it.
    """

    def test_the_on_state_is_a_light_icon(self, qapp):
        from PySide6.QtGui import QIcon

        from orion.ui.icons import available_icons, icon

        def mean_lightness(pixmap):
            image = pixmap.toImage()
            ink = [
                image.pixelColor(x, y)
                for x in range(image.width())
                for y in range(image.height())
                if image.pixelColor(x, y).alpha() > 128
            ]
            assert ink, "the icon drew nothing at all"
            return sum(colour.lightness() for colour in ink) / len(ink)

        drawn = icon(available_icons()[0], 20)
        off = mean_lightness(drawn.pixmap(20, 20, QIcon.Mode.Normal, QIcon.State.Off))
        on = mean_lightness(drawn.pixmap(20, 20, QIcon.Mode.Normal, QIcon.State.On))

        assert off < 100, "the ordinary icon is not dark"
        assert on > 200, "the icon on an active button is not light"

    def test_a_selected_row_gets_the_light_icon_too(self, qapp):
        """Same problem, same fill: a selected item is painted with the accent
        behind it.
        """
        from PySide6.QtGui import QIcon

        from orion.ui.icons import available_icons, icon

        drawn = icon(available_icons()[0], 20)
        selected = drawn.pixmap(20, 20, QIcon.Mode.Selected, QIcon.State.Off).toImage()
        ink = [
            selected.pixelColor(x, y)
            for x in range(selected.width())
            for y in range(selected.height())
            if selected.pixelColor(x, y).alpha() > 128
        ]
        assert ink and sum(c.lightness() for c in ink) / len(ink) > 200

    def test_an_active_button_is_dark_enough_for_a_white_icon(self, qapp):
        """The other half of it. A light icon on a light fill is the same bug
        the other way round, and the stylesheet is where that would happen.
        """
        from pathlib import Path

        sheet = (Path(__file__).resolve().parent.parent
                 / "resources" / "styles" / "orion.qss").read_text(encoding="utf-8")
        block = sheet.split("QToolButton:pressed", 1)[1].split("}", 1)[0]
        assert "#2c3e50" in block, "the checked fill is not the dark primary"


class TestIconsAreNotScaledTwice:
    """The icons must be the same size on a HiDPI screen as anywhere else.

    Regression test for a reported bug: every toolbar icon appeared blown up
    and cropped, "as if there were a zoom on it". A ``QPainter`` drawing on a
    ``QPixmap`` that carries a device pixel ratio already works in *logical*
    units — its coordinate space is the pixmap's device size divided by the
    ratio — but the renderer was multiplying the normalised (0..1) shapes by
    the device pixel count. So the ratio was applied twice, and the ratio-2
    pixmap, the one Qt picks on a HiDPI display, was drawn at 4x instead of
    2x: an icon twice the size of its button, of which the button showed one
    corner.

    Comparing the two ratios against each other is what makes this stick. An
    absolute assertion about pixel positions would have to be rewritten every
    time a glyph is redrawn; that the same icon covers the same fraction of
    the button whatever the screen is a property that should never change.
    """

    @staticmethod
    def _ink_bounds(pixmap):
        """The drawn area, in *logical* units, or ``None`` if nothing drew."""
        image = pixmap.toImage()
        ratio = pixmap.devicePixelRatio()
        xs = [
            (x, y)
            for y in range(image.height())
            for x in range(image.width())
            if image.pixelColor(x, y).alpha() > 20
        ]
        if not xs:
            return None
        left = min(x for x, _ in xs) / ratio
        right = (max(x for x, _ in xs) + 1) / ratio
        top = min(y for _, y in xs) / ratio
        bottom = (max(y for _, y in xs) + 1) / ratio
        return left, top, right, bottom

    @pytest.mark.parametrize("scale", [1, 2])
    def test_the_pixmap_reports_the_size_that_was_asked_for(self, qapp, scale):
        from PySide6.QtGui import QColor

        from orion.ui.icons import ICONS, _render

        pixmap = _render(ICONS["close"], 20, QColor("#000000"), scale)
        assert pixmap.width() == 20 * scale, "the buffer is not at the device resolution"
        assert pixmap.devicePixelRatio() == float(scale)
        # Qt lays the icon out from this, so it is what the button sees.
        assert pixmap.deviceIndependentSize().toSize().width() == 20

    def test_every_icon_covers_the_same_area_at_both_ratios(self, qapp):
        from PySide6.QtGui import QColor

        from orion.ui.icons import ICONS, _render

        black = QColor("#000000")
        for name, shapes in ICONS.items():
            at_one = self._ink_bounds(_render(shapes, 20, black, 1))
            at_two = self._ink_bounds(_render(shapes, 20, black, 2))
            assert at_one is not None, f"“{name}” drew nothing at ratio 1"
            assert at_two is not None, f"“{name}” drew nothing at ratio 2"
            for logical_one, logical_two, edge in zip(
                at_one, at_two, ("left", "top", "right", "bottom"), strict=True
            ):
                assert logical_two == pytest.approx(logical_one, abs=1.5), (
                    f"“{name}” is drawn at a different size on a HiDPI screen: "
                    f"its {edge} edge is at {logical_one} at ratio 1 and "
                    f"{logical_two} at ratio 2"
                )

    def test_every_icon_stays_centred_in_its_button(self, qapp):
        """The visible half of the bug: what the user actually saw.

        Where the drawing sits is a separate question from how big it is, and
        it is the one that made the report look like a zoom: an icon drawn at
        twice its size is clipped by the pixmap, so the surviving ink is the
        top-left corner of the glyph and its centre of mass slides towards the
        bottom right. Several of these glyphs legitimately reach the border —
        the open-folder is 0.98 wide by design — so the edges cannot be
        asserted directly, but a balanced drawing has its ink near the middle
        whatever the screen.
        """
        from PySide6.QtGui import QColor

        from orion.ui.icons import ICONS, _render

        black = QColor("#000000")
        for name, shapes in ICONS.items():
            for scale in (1, 2):
                pixmap = _render(shapes, 20, black, scale)
                image = pixmap.toImage()
                ratio = pixmap.devicePixelRatio()
                ink = [
                    (x, y)
                    for y in range(image.height())
                    for x in range(image.width())
                    if image.pixelColor(x, y).alpha() > 20
                ]
                assert ink, f"“{name}” drew nothing at ratio {scale}"
                centre_x = sum(x for x, _ in ink) / len(ink) / ratio
                centre_y = sum(y for _, y in ink) / len(ink) / ratio
                assert centre_x == pytest.approx(10.0, abs=3.0), (
                    f"“{name}” sits off to one side at ratio {scale}: "
                    f"its ink is centred at x={centre_x:.1f} of 20"
                )
                assert centre_y == pytest.approx(10.0, abs=3.0), (
                    f"“{name}” sits high or low at ratio {scale}: "
                    f"its ink is centred at y={centre_y:.1f} of 20"
                )


class TestMarkingUpSurvivesReopening:
    """The user's report: a highlight could not be clicked after reopening.

    In one session it always worked — the annotation was an object on the
    canvas like anything else. What broke was the file: nothing read `/Annots`
    back, so a saved highlight came back as part of the page picture. This
    drives the whole path, because the model-level tests in
    ``tests/test_annotation_import.py`` cannot say whether the canvas ends up
    with something to click.
    """

    def test_a_reopened_highlight_can_be_selected_and_deleted(
        self, window, qapp, sample_pdf, tmp_path
    ):
        from orion.document.annotations import AnnotationObject

        window.open_path(sample_pdf)
        pump(qapp)
        _drag(window, Tool.HIGHLIGHT, (45.0, 78.0), (200.0, 106.0))
        pump(qapp)

        saved = tmp_path / "marked.pdf"
        assert window._write(window.session, saved)
        assert window.open_path(saved)
        pump(qapp)

        objects = window.session.document[0].objects
        assert len(objects) == 1, "the saved highlight did not come back as an object"
        annotation = objects[0]
        assert isinstance(annotation, AnnotationObject)

        # It is on the canvas, and clicking it selects it.
        canvas = window._canvas
        assert annotation.id in canvas._item_index
        centre = annotation.rect.center
        _click_at(window, (centre.x, centre.y))
        pump(qapp)
        assert [o.id for o in canvas.selected_objects()] == [annotation.id]

        # And Delete now reaches it, which is what the user was after.
        window._actions["edit.delete"].trigger()
        pump(qapp)
        assert window.session.document[0].objects == []


def _click_at(window, base: tuple[float, float]) -> None:
    """Click once on the canvas, in base page coordinates of the first page."""
    from PySide6.QtCore import QEvent, QPoint
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication

    view = window._canvas
    view.set_zoom(1.0)
    content = view._page_items[0].content
    point = QPointF(view.mapFromScene(content.mapToScene(QPointF(*base))))
    globals_ = view.viewport().mapToGlobal(QPoint(int(point.x()), int(point.y())))
    for event_type, buttons in (
        (QEvent.Type.MouseButtonPress, Qt.MouseButton.LeftButton),
        (QEvent.Type.MouseButtonRelease, Qt.MouseButton.NoButton),
    ):
        QApplication.sendEvent(
            view.viewport(),
            QMouseEvent(
                event_type, point, globals_, Qt.MouseButton.LeftButton, buttons,
                Qt.KeyboardModifier.NoModifier,
            ),
        )


class TestTheCanvasContextMenu:
    """Right-click on the page, which used to do nothing at all.

    It is the gesture people reach for to recolour or delete a mark they made
    — and the reason the reported "I can't click my highlight any more" had a
    second half to it, beyond annotations not surviving a reopen.

    The menu is opened with ``QMenu.exec``, which blocks until the user picks
    something, and PySide6 resolves that call through the C++ slot so it
    cannot be replaced from Python. So the window's handler is unhooked for
    the duration and the two halves are checked separately: that the canvas
    settles the selection and emits, and that the window offers the right
    entries for that selection. The connection between them has a test of its
    own below.
    """

    @pytest.fixture
    def emitted(self, window):
        """Records the menu requests, with the window's own handler unhooked."""
        window._canvas.context_menu_requested.disconnect(window._show_canvas_menu)
        positions: list[object] = []
        window._canvas.context_menu_requested.connect(positions.append)
        yield positions
        window._canvas.context_menu_requested.disconnect(positions.append)
        window._canvas.context_menu_requested.connect(window._show_canvas_menu)

    @staticmethod
    def _right_click(window, base: tuple[float, float]) -> None:
        from PySide6.QtCore import QPoint
        from PySide6.QtGui import QContextMenuEvent

        view = window._canvas
        view.set_zoom(1.0)
        content = view._page_items[0].content
        point = QPointF(view.mapFromScene(content.mapToScene(QPointF(*base))))
        position = QPoint(int(point.x()), int(point.y()))
        view.contextMenuEvent(
            QContextMenuEvent(
                QContextMenuEvent.Reason.Mouse,
                position,
                view.viewport().mapToGlobal(position),
            )
        )

    @staticmethod
    def _entries(window) -> list[str]:
        """The menu the window would open now, by action key.

        Keys rather than labels: every action carries its registry key in
        ``data()``, and a label is free to be reworded.
        """
        menu = window.canvas_menu()
        assert menu is not None, "no menu was offered"
        return [a.data() for a in menu.actions() if not a.isSeparator()]

    def test_right_clicking_an_object_selects_it_and_offers_object_actions(
        self, window, qapp, sample_pdf, emitted
    ):
        window.open_path(sample_pdf)
        pump(qapp)
        _drag(window, Tool.RECTANGLE, (40.0, 200.0), (180.0, 280.0))
        pump(qapp)
        window._canvas.clear_selection()
        pump(qapp)

        self._right_click(window, (110.0, 240.0))
        pump(qapp)

        shape = window.session.document[0].objects[0]
        assert [o.id for o in window._canvas.selected_objects()] == [shape.id]
        assert len(emitted) == 1, "the canvas did not ask for a menu"
        entries = self._entries(window)
        assert "edit.delete" in entries
        assert "pages.rotate_right" not in entries

    def test_right_clicking_empty_space_offers_the_page_actions(
        self, window, qapp, sample_pdf, emitted
    ):
        window.open_path(sample_pdf)
        pump(qapp)
        _drag(window, Tool.RECTANGLE, (40.0, 200.0), (180.0, 280.0))
        pump(qapp)

        self._right_click(window, (330.0, 520.0))
        pump(qapp)

        assert window._canvas.selected_objects() == [], "the click was not on the object"
        entries = self._entries(window)
        assert "pages.rotate_right" in entries
        assert "edit.delete" not in entries, "the page menu must not offer object actions"

    def test_a_multiple_selection_is_kept(self, window, qapp, sample_pdf, emitted):
        """Right-clicking inside a selection must not shrink it to one object.

        Otherwise "delete these six" quietly becomes "delete this one".
        """
        window.open_path(sample_pdf)
        pump(qapp)
        _drag(window, Tool.RECTANGLE, (40.0, 200.0), (180.0, 280.0))
        pump(qapp)
        _drag(window, Tool.ELLIPSE, (40.0, 320.0), (180.0, 400.0))
        pump(qapp)
        window._canvas.select_objects([o.id for o in window.session.document[0].objects])
        pump(qapp)

        self._right_click(window, (110.0, 240.0))
        pump(qapp)
        assert len(window._canvas.selected_objects()) == 2

    def test_an_annotation_offers_its_comment_and_delete(
        self, window, qapp, sample_pdf, emitted
    ):
        """The user's actual errand, reached entirely with the right button."""
        window.open_path(sample_pdf)
        pump(qapp)
        _drag(window, Tool.HIGHLIGHT, (45.0, 78.0), (200.0, 106.0))
        pump(qapp)
        window._canvas.clear_selection()
        pump(qapp)

        annotation = window.session.document[0].objects[0]
        centre = annotation.rect.center
        self._right_click(window, (centre.x, centre.y))
        pump(qapp)

        entries = self._entries(window)
        assert "tools.edit_note" in entries, "no way to edit the comment"
        assert "edit.delete" in entries
        assert "tools.edit_text" not in entries, "an annotation is not a text box"

        window._actions["edit.delete"].trigger()
        pump(qapp)
        assert window.session.document[0].objects == []

    def test_a_text_box_offers_editing_and_an_annotation_does_not(
        self, window, qapp, sample_pdf, emitted
    ):
        window.open_path(sample_pdf)
        pump(qapp)
        _drag(window, Tool.TEXT, (40.0, 300.0), (260.0, 350.0))
        pump(qapp)
        text = window.session.document[0].objects[0]
        window._canvas._item_index[text.id].end_editing(commit=True)
        pump(qapp)

        self._right_click(window, (150.0, 325.0))
        pump(qapp)
        entries = self._entries(window)
        assert "tools.edit_text" in entries
        assert "tools.edit_note" not in entries

    def test_the_window_is_listening_to_the_canvas(self, window):
        """The one line the tests above unhook, checked without opening a menu.

        ``disconnect`` raises if the slot is not connected, which is the whole
        assertion; it is put straight back.
        """
        window._canvas.context_menu_requested.disconnect(window._show_canvas_menu)
        window._canvas.context_menu_requested.connect(window._show_canvas_menu)

    def test_nothing_is_offered_without_a_document(self, window):
        assert window.canvas_menu() is None
