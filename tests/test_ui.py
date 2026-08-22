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
from tests.conftest import pump


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
    for _ in range(80):
        qapp.processEvents()
        if page_item._image is not None:
            break
    assert page_item._image is not None
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
    import pymupdf

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

    with pymupdf.open(out) as doc:
        assert "WINDOW SAVE" in doc.load_page(0).get_text()


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
