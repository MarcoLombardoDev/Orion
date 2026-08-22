"""The Orion main window (spec §7, §19, §21, §22, §25).

The window owns exactly one :class:`~orion.services.file_service.DocumentSession`.
Everything below it — the model, the history, the renderer — is reached through
that session, which is what keeps multi-document support (spec §21) a matter of
holding a list here rather than an architectural change.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from pathlib import Path

from PySide6.QtCore import QByteArray, Qt, QTimer
from PySide6.QtGui import QCloseEvent, QGuiApplication
from PySide6.QtWidgets import (
    QDialog,
    QDockWidget,
    QFileDialog,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from orion import APP_NAME, APP_SUBTITLE
from orion.commands.object_commands import (
    DeleteObjectsCommand,
    PasteObjectsCommand,
    RaiseObjectCommand,
)
from orion.commands.page_commands import (
    DeletePagesCommand,
    DuplicatePageCommand,
    ImportPagesCommand,
    InsertPageCommand,
    MovePageCommand,
    RotatePagesCommand,
)
from orion.document.annotations import AnnotationObject
from orion.document.document import Document
from orion.document.objects import ImageObject, TextObject
from orion.pdf.errors import OrionPdfError, PdfPasswordRequired, describe_exception
from orion.services.autosave import list_recoverable
from orion.services.clipboard import ObjectClipboard
from orion.services.export_service import ExportService
from orion.services.file_service import DocumentSession, FileService
from orion.services.recent_files import RecentFiles
from orion.services.settings import Settings
from orion.services.settings import settings as global_settings
from orion.ui.actions import ActionRegistry
from orion.ui.canvas import PdfCanvas, ZoomMode
from orion.ui.dialogs import (
    AboutDialog,
    GoToPageDialog,
    ImportPagesDialog,
    InsertPageDialog,
    MergeDialog,
    NoteDialog,
    PageSelectionDialog,
    RecoveryDialog,
    SplitDialog,
)
from orion.ui.dialogs.merge_dialog import CURRENT_DOCUMENT
from orion.ui.icons import set_icon_theme
from orion.ui.menu import build_menu_bar
from orion.ui.object_items import ObjectItem
from orion.ui.properties_panel import PropertiesPanel
from orion.ui.search_panel import SearchHit, SearchPanel
from orion.ui.status_bar import OrionStatusBar
from orion.ui.theme import ThemeMode, apply_theme, resolve_theme
from orion.ui.thumbnails import ThumbnailPanel
from orion.ui.toolbar import MainToolBar, ToolPalette
from orion.ui.tools import Tool
from orion.utils.geometry import Point, Rect, Size
from orion.utils.image_utils import (
    SUPPORTED_EXTENSIONS,
    UnsupportedImageError,
    load_image_bytes,
)
from orion.utils.paths import log_dir

log = logging.getLogger(__name__)

__all__ = ["MainWindow"]

PDF_FILTER = "PDF documents (*.pdf);;All files (*)"
IMAGE_FILTER = "Images (*.png *.jpg *.jpeg *.webp);;All files (*)"
#: Longest edge of a freshly placed image, in points.
IMAGE_PLACEMENT_SIZE = 220.0


class MainWindow(QMainWindow):
    def __init__(self, settings: Settings | None = None) -> None:
        super().__init__()
        self._settings = settings or global_settings()
        self._files = FileService(
            cache_bytes=int(self._settings.get("render_cache_mb", 256)) * 1024 * 1024
        )
        self._export = ExportService()
        self._clipboard = ObjectClipboard()
        self._recent = RecentFiles(self._settings)
        self._session: DocumentSession | None = None
        self._theme_mode = ThemeMode(self._settings.get("theme", "system"))

        self.setWindowTitle(f"{APP_NAME} — {APP_SUBTITLE}")
        self.setMinimumSize(900, 620)
        self.setAcceptDrops(True)

        self._actions = ActionRegistry(self)
        self._build_ui()
        self._connect_actions()
        self._apply_theme(self._theme_mode)
        self._restore_window_state()

        self._autosave_timer = QTimer(self)
        self._autosave_timer.setInterval(
            max(15, int(self._settings.get("autosave_interval_seconds", 60))) * 1000
        )
        self._autosave_timer.timeout.connect(self._autosave_tick)
        if self._settings.get("autosave_enabled", True):
            self._autosave_timer.start()

        self._update_ui_state()
        QTimer.singleShot(250, self._offer_recovery)

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        menu_bar, self._menus = build_menu_bar(self, self._actions)
        self.setMenuBar(menu_bar)

        self._toolbar = MainToolBar(self._actions, self)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, self._toolbar)
        self._tool_palette = ToolPalette(self._actions, self)
        self.addToolBar(Qt.ToolBarArea.LeftToolBarArea, self._tool_palette)

        central = QWidget(self)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._search = SearchPanel(central)
        layout.addWidget(self._search)

        self._canvas = PdfCanvas(central)
        layout.addWidget(self._canvas, 1)

        self._placeholder = _Placeholder(central)
        layout.addWidget(self._placeholder, 1)
        self.setCentralWidget(central)

        self._thumbnails = ThumbnailPanel(self)
        self._thumbnail_dock = QDockWidget("Pages", self)
        self._thumbnail_dock.setObjectName("thumbnails_dock")
        self._thumbnail_dock.setWidget(self._thumbnails)
        self._thumbnail_dock.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea
        )
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self._thumbnail_dock)

        self._properties = PropertiesPanel(self)
        self._properties_dock = QDockWidget("Properties", self)
        self._properties_dock.setObjectName("properties_dock")
        self._properties_dock.setWidget(self._properties)
        self._properties_dock.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea
        )
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self._properties_dock)

        self._status = OrionStatusBar(self)
        self.setStatusBar(self._status)
        self._actions.bind_canvas_shortcuts(self._canvas)
        self.resizeDocks(
            [self._thumbnail_dock, self._properties_dock], [190, 300], Qt.Orientation.Horizontal
        )
        self._wire_widgets()
        self._show_document_widgets(False)

    def _wire_widgets(self) -> None:
        self._toolbar.zoom_entered.connect(lambda zoom: self._canvas.set_zoom(zoom))
        self._toolbar.page_entered.connect(self._canvas.go_to_page)

        self._tool_palette.tool_selected.connect(self._on_tool_selected)

        self._canvas.current_page_changed.connect(self._on_current_page_changed)
        self._canvas.zoom_changed.connect(self._on_zoom_changed)
        self._canvas.selection_changed.connect(self._on_selection_changed)
        self._canvas.object_geometry_committed.connect(self._properties.refresh)
        self._canvas.note_edit_requested.connect(self._edit_note)
        self._canvas.image_requested.connect(self._insert_image_at)
        self._canvas.status_message.connect(self._status.flash)
        self._canvas.tool_finished.connect(self._return_to_select_tool)
        self._canvas.files_dropped.connect(self._on_files_dropped)

        self._thumbnails.page_activated.connect(self._canvas.go_to_page)
        self._thumbnails.pages_reordered.connect(self._on_pages_reordered)
        self._thumbnails.context_action.connect(self._on_thumbnail_action)

        self._properties.arrange_requested.connect(self._arrange_selection)

        self._search.hits_changed.connect(self._canvas.set_search_hits)
        self._search.current_hit_changed.connect(self._on_search_hit)
        self._search.closed.connect(self._canvas.clear_search_hits)

        self._thumbnail_dock.visibilityChanged.connect(
            lambda visible: self._actions["view.thumbnails"].setChecked(visible)
        )
        self._properties_dock.visibilityChanged.connect(
            lambda visible: self._actions["view.properties"].setChecked(visible)
        )

    def _connect_actions(self) -> None:
        connect = self._actions.connect
        # File
        connect("file.new", self.new_document)
        connect("file.open", self.open_document)
        connect("file.close", lambda: self.close_document())
        connect("file.save", self.save_document)
        connect("file.save_as", self.save_document_as)
        connect("file.merge", self.merge_documents)
        connect("file.clear_recent", self._clear_recent)
        connect("file.quit", self.close)
        # Edit
        connect("edit.undo", self.undo)
        connect("edit.redo", self.redo)
        connect("edit.cut", lambda: self._copy_selection(cut=True))
        connect("edit.copy", lambda: self._copy_selection(cut=False))
        connect("edit.paste", self.paste)
        connect("edit.duplicate", self.duplicate_selection)
        connect("edit.delete", self.delete_selection)
        connect("edit.select_all", lambda: self._canvas.select_all_on_current_page())
        connect("edit.deselect", lambda: self._canvas.clear_selection())
        connect("edit.bring_front", lambda: self._arrange_selection(True))
        connect("edit.send_back", lambda: self._arrange_selection(False))
        # View
        connect("view.zoom_in", lambda: self._canvas.zoom_in())
        connect("view.zoom_out", lambda: self._canvas.zoom_out())
        connect("view.zoom_reset", lambda: self._canvas.set_zoom(1.0))
        connect("view.fit_page", lambda: self._canvas.set_zoom_mode(ZoomMode.FIT_PAGE))
        connect("view.fit_width", lambda: self._canvas.set_zoom_mode(ZoomMode.FIT_WIDTH))
        connect("view.first_page", lambda: self._canvas.go_to_page(0))
        connect(
            "view.previous_page",
            lambda: self._canvas.go_to_page(self._canvas.current_page - 1),
        )
        connect("view.next_page", lambda: self._canvas.go_to_page(self._canvas.current_page + 1))
        connect("view.last_page", lambda: self._canvas.go_to_page(self._canvas.page_count - 1))
        connect("view.go_to_page", self.go_to_page)
        connect("view.search", self.show_search)
        connect("view.find_next", self._search.find_next)
        connect("view.find_previous", self._search.find_previous)
        connect("view.thumbnails", lambda checked: self._thumbnail_dock.setVisible(checked))
        connect("view.properties", lambda checked: self._properties_dock.setVisible(checked))
        connect("view.theme_light", lambda: self._apply_theme(ThemeMode.LIGHT))
        connect("view.theme_dark", lambda: self._apply_theme(ThemeMode.DARK))
        connect("view.theme_system", lambda: self._apply_theme(ThemeMode.SYSTEM))
        # Pages
        connect("pages.insert", self.insert_blank_page)
        connect("pages.duplicate", self.duplicate_page)
        connect("pages.delete", self.delete_pages)
        connect("pages.rotate_left", lambda: self.rotate_pages(-90))
        connect("pages.rotate_right", lambda: self.rotate_pages(90))
        connect("pages.rotate_180", lambda: self.rotate_pages(180))
        connect("pages.move_up", lambda: self.move_page(-1))
        connect("pages.move_down", lambda: self.move_page(1))
        connect("pages.import", self.import_pages)
        connect("pages.extract", self.extract_pages)
        connect("pages.split", self.split_document)
        # Tools
        connect("tools.insert_image", self.insert_image)
        connect("tools.edit_text", lambda: self._canvas.edit_selected_text())
        # Help
        connect("help.shortcuts", self.show_shortcuts)
        connect("help.log", self.open_log_folder)
        connect("help.about", lambda: AboutDialog(self).exec())

        self._recent.changed.connect(self._rebuild_recent_menu)
        self._rebuild_recent_menu(self._recent.paths)

        self._actions["view.thumbnails"].setChecked(
            bool(self._settings.get("show_thumbnails", True))
        )
        self._actions["view.properties"].setChecked(
            bool(self._settings.get("show_properties", True))
        )
        self._thumbnail_dock.setVisible(self._actions["view.thumbnails"].isChecked())
        self._properties_dock.setVisible(self._actions["view.properties"].isChecked())

    # ------------------------------------------------------------------
    # Theme
    # ------------------------------------------------------------------
    def _apply_theme(self, mode: ThemeMode) -> None:
        self._theme_mode = mode
        theme = resolve_theme(mode)
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is not None:
            apply_theme(app, theme)
        set_icon_theme(theme)
        self._actions.refresh_icons()
        self._canvas.apply_theme(theme)
        self._thumbnails.apply_theme(theme)
        for key, value in (
            ("view.theme_light", ThemeMode.LIGHT),
            ("view.theme_dark", ThemeMode.DARK),
            ("view.theme_system", ThemeMode.SYSTEM),
        ):
            self._actions[key].setChecked(mode is value)
        self._settings.set("theme", mode.value)

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------
    @property
    def session(self) -> DocumentSession | None:
        return self._session

    def _attach_session(self, session: DocumentSession) -> None:
        self._detach_session()
        self._session = session
        session.history.changed.connect(self._on_history_changed)
        session.history.clean_changed.connect(self._on_clean_changed)
        session.document.modified_changed.connect(self._on_modified_changed)
        session.document.pages_changed.connect(self._on_pages_changed)

        self._canvas.set_session(session)
        self._thumbnails.set_session(session)
        self._properties.set_session(session)
        self._search.set_session(session)

        self._show_document_widgets(True)
        self._on_tool_selected(Tool.SELECT)
        self._tool_palette.set_tool(Tool.SELECT)
        self._canvas.set_zoom_mode(ZoomMode(self._settings.get("zoom_mode", "fit_width")))
        self._canvas.go_to_page(0)
        # go_to_page(0) is a no-op signal-wise when the page is already 0, so
        # the page counters are refreshed explicitly on attach.
        self._refresh_page_display()
        self._update_ui_state()
        self._update_title()

    def _detach_session(self) -> None:
        if self._session is None:
            return
        self._search.close_session()
        self._properties.close_session()
        self._thumbnails.close_session()
        self._canvas.close_session()
        self._session.close()
        self._session = None
        self._show_document_widgets(False)
        self._status.clear_document()
        self._update_title()

    def _show_document_widgets(self, visible: bool) -> None:
        self._canvas.setVisible(visible)
        self._placeholder.setVisible(not visible)
        if not visible:
            self._search.setVisible(False)

    # -- open --------------------------------------------------------------
    def new_document(self) -> None:
        if not self._confirm_discard():
            return
        session = self._files.create_blank()
        self._attach_session(session)
        self._status.flash("New empty document created.")

    def open_document(self) -> None:
        start = self._settings.get("last_directory", "") or str(Path.home())
        path, _ = QFileDialog.getOpenFileName(self, "Open PDF", start, PDF_FILTER)
        if path:
            self.open_path(Path(path))

    def open_path(self, path: Path, *, password: str | None = None) -> bool:
        if not self._confirm_discard():
            return False
        try:
            session = self._files.open(path, password)
        except PdfPasswordRequired as exc:
            entered, accepted = QInputDialog.getText(
                self,
                "Password Required",
                exc.message,
                QLineEdit.EchoMode.Password,
            )
            if not accepted or not entered:
                return False
            if password is not None and entered == password:
                # The same wrong password twice: stop rather than loop.
                self._report(exc, title="Cannot Open Document")
                return False
            return self.open_path(path, password=entered)
        except OrionPdfError as exc:
            self._report(exc, title="Cannot Open Document")
            self._recent.remove(path)
            return False
        except Exception as exc:  # pragma: no cover - unexpected engine failure
            log.exception("Unexpected error while opening %s", path)
            self._report(exc, title="Cannot Open Document")
            return False

        self._attach_session(session)
        self._recent.add(path)
        self._settings.set("last_directory", str(path.parent))
        self._status.flash(f"Opened {path.name}")
        return True

    def close_document(self) -> bool:
        if not self._confirm_discard():
            return False
        self._detach_session()
        self._update_ui_state()
        return True

    # -- save --------------------------------------------------------------
    def save_document(self) -> bool:
        session = self._session
        if session is None:
            return False
        if session.path is None:
            return self.save_document_as()
        if not session.is_modified:
            # Spec §19: an unmodified document is not rewritten for nothing.
            self._status.flash("No changes to save.")
            return True
        return self._write(session, session.path)

    def save_document_as(self) -> bool:
        session = self._session
        if session is None:
            return False
        suggestion = session.path or Path(
            self._settings.get("last_directory", "") or str(Path.home())
        ) / "Untitled.pdf"
        path, _ = QFileDialog.getSaveFileName(self, "Save PDF As", str(suggestion), PDF_FILTER)
        if not path:
            return False
        target = Path(path)
        if target.suffix.lower() != ".pdf":
            target = target.with_suffix(".pdf")
        return self._write(session, target)

    def _write(self, session: DocumentSession, path: Path) -> bool:
        QGuiApplication.setOverrideCursor(Qt.CursorShape.BusyCursor)
        try:
            self._files.save_as(session, path)
        except OrionPdfError as exc:
            self._report(exc, title="Cannot Save Document")
            return False
        except Exception as exc:  # pragma: no cover - unexpected engine failure
            log.exception("Unexpected error while saving to %s", path)
            self._report(exc, title="Cannot Save Document")
            return False
        finally:
            QGuiApplication.restoreOverrideCursor()

        self._recent.add(path)
        self._settings.set("last_directory", str(path.parent))
        self._update_title()
        self._update_ui_state()
        self._status.flash(f"Saved {path.name}")
        return True

    def _confirm_discard(self) -> bool:
        """Ask before losing unsaved changes (spec §19)."""
        session = self._session
        if session is None or not session.is_modified:
            return True
        answer = QMessageBox.warning(
            self,
            "Unsaved Changes",
            f"“{session.display_name}” has unsaved changes.\n\nDo you want to save them?",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )
        if answer == QMessageBox.StandardButton.Cancel:
            return False
        if answer == QMessageBox.StandardButton.Save:
            return self.save_document()
        return True

    # ------------------------------------------------------------------
    # Editing
    # ------------------------------------------------------------------
    def undo(self) -> None:
        if self._session is None:
            return
        try:
            command = self._session.history.undo()
        except Exception as exc:  # pragma: no cover - defensive
            self._report(exc, title="Cannot Undo")
            return
        if command is not None:
            self._status.flash(f"Undid {command.text}")
        self._after_model_change()

    def redo(self) -> None:
        if self._session is None:
            return
        try:
            command = self._session.history.redo()
        except Exception as exc:  # pragma: no cover - defensive
            self._report(exc, title="Cannot Redo")
            return
        if command is not None:
            self._status.flash(f"Redid {command.text}")
        self._after_model_change()

    def _copy_selection(self, *, cut: bool) -> None:
        objects = self._canvas.selected_objects()
        if not objects or self._session is None:
            return
        count = self._clipboard.copy(objects)
        if cut:
            self._delete_grouped_selection("Cut")
        self._status.flash(f"{'Cut' if cut else 'Copied'} {count} object(s).")
        self._update_ui_state()

    def paste(self) -> None:
        if self._session is None:
            return
        objects = self._clipboard.paste()
        if not objects:
            self._status.flash("The clipboard has no Orion objects.")
            return
        page_index = self._canvas.current_page
        page = self._session.document.page_at(page_index)
        if page is None:
            return
        bounds = Rect.from_xywh(0, 0, page.base_size.width, page.base_size.height)
        for obj in objects:
            obj.rect = obj.rect.clamped_to(bounds)
        self._session.history.push(
            PasteObjectsCommand(self._session.document, page_index, objects, text="Paste")
        )
        self._canvas.select_objects(obj.id for obj in objects)
        self._status.flash(f"Pasted {len(objects)} object(s).")

    def duplicate_selection(self) -> None:
        session = self._session
        if session is None or not self._canvas.selected_objects():
            return
        created: list[str] = []
        session.history.begin_macro("Duplicate")
        try:
            for page_index, ids in self._canvas.selection_by_page().items():
                page = session.document.page_at(page_index)
                if page is None:
                    continue
                copies = [
                    obj.clone(new_id=True, offset=(12.0, 12.0))
                    for object_id in ids
                    if (obj := page.find_object(object_id)) is not None
                ]
                created.extend(obj.id for obj in copies)
                session.history.push(
                    PasteObjectsCommand(
                        session.document, page_index, copies, text="Duplicate"
                    )
                )
        finally:
            session.history.end_macro()
        self._canvas.select_objects(created)

    def delete_selection(self) -> None:
        count = len(self._canvas.selected_objects())
        if not count:
            return
        self._delete_grouped_selection(
            "Delete Object" if count == 1 else f"Delete {count} Objects"
        )

    def _delete_grouped_selection(self, text: str) -> None:
        """Delete the selection, which may span more than one page."""
        session = self._session
        if session is None:
            return
        grouped = self._canvas.selection_by_page()
        if not grouped:
            return
        if len(grouped) == 1:
            page_index, ids = next(iter(grouped.items()))
            session.history.push(
                DeleteObjectsCommand(session.document, page_index, ids, text=text)
            )
            return
        session.history.begin_macro(text)
        try:
            for page_index, ids in grouped.items():
                session.history.push(
                    DeleteObjectsCommand(session.document, page_index, ids, text=text)
                )
        finally:
            session.history.end_macro()

    def _arrange_selection(self, to_front: bool) -> None:
        if self._session is None or not self._canvas.selected_objects():
            return
        history = self._session.history
        history.begin_macro("Bring to Front" if to_front else "Send to Back")
        try:
            for page_index, ids in self._canvas.selection_by_page().items():
                for object_id in ids:
                    history.push(
                        RaiseObjectCommand(
                            self._session.document, page_index, object_id, to_top=to_front
                        )
                    )
        finally:
            history.end_macro()

    # -- images ------------------------------------------------------------
    def insert_image(self) -> None:
        if self._session is None:
            return
        page = self._session.document.page_at(self._canvas.current_page)
        if page is None:
            return
        centre = Point(page.base_size.width / 2.0, page.base_size.height / 2.0)
        self._insert_image_at(self._canvas.current_page, centre)

    def _insert_image_at(self, page_index: int, position: Point) -> None:
        start = self._settings.get("last_directory", "") or str(Path.home())
        path, _ = QFileDialog.getOpenFileName(self, "Insert Image", start, IMAGE_FILTER)
        self._return_to_select_tool()
        if not path:
            return
        self._place_image(Path(path), page_index, position)

    def _place_image(self, path: Path, page_index: int, position: Point) -> None:
        if self._session is None:
            return
        try:
            data, image_format, natural = load_image_bytes(path)
        except UnsupportedImageError as exc:
            QMessageBox.warning(self, "Cannot Insert Image", str(exc))
            return

        scale = IMAGE_PLACEMENT_SIZE / max(natural.width, natural.height, 1.0)
        size = Size(natural.width * scale, natural.height * scale)
        rect = Rect.from_xywh(position.x, position.y, size.width, size.height)

        page = self._session.document.page_at(page_index)
        if page is not None:
            rect = rect.clamped_to(
                Rect.from_xywh(0, 0, page.base_size.width, page.base_size.height)
            )

        obj = ImageObject(
            rect=rect,
            data=data,
            image_format=image_format,
            natural_size=natural,
            source_name=path.name,
        )
        from orion.commands.object_commands import AddObjectCommand

        self._session.history.push(
            AddObjectCommand(self._session.document, page_index, obj, text="Add Image")
        )
        self._canvas.select_objects([obj.id])
        self._settings.set("last_directory", str(path.parent))

    def _edit_note(self, item: ObjectItem) -> None:
        obj = item.object
        if not isinstance(obj, AnnotationObject) or self._session is None:
            return
        dialog = NoteDialog(
            obj.contents,
            obj.author or str(self._settings.get("default_author", "")),
            title=obj.annotation.value.replace("_", " ").title(),
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        from orion.commands.object_commands import ModifyObjectCommand

        self._session.history.push(
            ModifyObjectCommand(
                self._session.document,
                item.page_index,
                obj.id,
                {"contents": dialog.text, "author": dialog.author},
                text="Edit Comment",
                mergeable=False,
            )
        )
        if dialog.author:
            self._settings.set("default_author", dialog.author)
            self._canvas.tool_state.author = dialog.author

    # ------------------------------------------------------------------
    # Pages
    # ------------------------------------------------------------------
    def _target_pages(self) -> list[int]:
        """Pages the page commands act on: the thumbnail selection, or the current page."""
        selected = self._thumbnails.selected_pages()
        if selected:
            return selected
        return [self._canvas.current_page]

    def insert_blank_page(self) -> None:
        if self._session is None:
            return
        document = self._session.document
        current = self._canvas.current_page
        page = document.page_at(current)
        default = page.display_size if page else Size(595.0, 842.0)
        dialog = InsertPageDialog(document.page_count, current, default, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        command = InsertPageCommand(document, dialog.index, dialog.size)
        self._session.history.push(command)
        self._canvas.go_to_page(command.index)

    def duplicate_page(self) -> None:
        if self._session is None:
            return
        index = self._target_pages()[0]
        self._session.history.push(DuplicatePageCommand(self._session.document, index))
        self._canvas.go_to_page(index + 1)

    def delete_pages(self, indices: Sequence[int] | None = None) -> None:
        if self._session is None:
            return
        document = self._session.document
        targets = list(indices) if indices is not None else self._target_pages()
        if not targets:
            return
        if len(targets) >= document.page_count:
            QMessageBox.information(
                self, "Cannot Delete", "A document must keep at least one page."
            )
            return
        label = "this page" if len(targets) == 1 else f"these {len(targets)} pages"
        answer = QMessageBox.question(
            self,
            "Delete Pages",
            f"Delete {label}? You can undo this afterwards.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Yes,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._session.history.push(DeletePagesCommand(document, targets))
        self._canvas.go_to_page(min(targets[0], document.page_count - 1))

    def rotate_pages(self, delta: int, indices: Sequence[int] | None = None) -> None:
        if self._session is None:
            return
        targets = list(indices) if indices is not None else self._target_pages()
        if not targets:
            return
        self._session.history.push(
            RotatePagesCommand(self._session.document, targets, delta)
        )

    def move_page(self, delta: int) -> None:
        if self._session is None:
            return
        index = self._canvas.current_page
        target = index + delta
        if not 0 <= target < self._session.document.page_count:
            return
        self._session.history.push(MovePageCommand(self._session.document, index, target))
        self._canvas.go_to_page(target)

    def _on_pages_reordered(self, from_index: int, to_index: int) -> None:
        if self._session is None:
            return
        # The view has already moved the row; rebuild from the model afterwards.
        self._session.history.push(
            MovePageCommand(self._session.document, from_index, to_index)
        )
        self._canvas.go_to_page(to_index)

    def import_pages(self) -> None:
        if self._session is None:
            return
        start = self._settings.get("last_directory", "") or str(Path.home())
        path, _ = QFileDialog.getOpenFileName(self, "Import Pages From", start, PDF_FILTER)
        if not path:
            return
        source_path = Path(path)
        try:
            source, pages = self._files.import_pages(self._session, source_path)
        except OrionPdfError as exc:
            self._report(exc, title="Cannot Import Pages")
            return

        dialog = ImportPagesDialog(
            source_path,
            len(pages),
            self._canvas.current_page + 1,
            self._session.document.page_count,
            self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            chosen = [pages[index] for index in dialog.indices() if 0 <= index < len(pages)]
        except ValueError as exc:
            QMessageBox.warning(self, "Cannot Import Pages", str(exc))
            return
        if not chosen:
            return
        self._session.history.push(
            ImportPagesCommand(self._session.document, dialog.insert_index, source, chosen)
        )
        self._status.flash(f"Imported {len(chosen)} page(s) from {source_path.name}")

    def extract_pages(self, indices: Sequence[int] | None = None) -> None:
        if self._session is None:
            return
        document = self._session.document
        from orion.pdf.operations import format_page_ranges

        preset = format_page_ranges(list(indices)) if indices else ""
        dialog = PageSelectionDialog(
            document.page_count,
            title="Extract Pages",
            prompt="Pages to extract",
            initial=preset or f"1-{document.page_count}",
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            chosen = dialog.indices()
        except ValueError as exc:
            QMessageBox.warning(self, "Cannot Extract Pages", str(exc))
            return

        stem = (document.path.stem if document.path else "document") + "-extract"
        suggestion = (document.path.parent if document.path else Path.home()) / f"{stem}.pdf"
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Extracted Pages", str(suggestion), PDF_FILTER
        )
        if not path:
            return
        try:
            output = self._export.extract(document, chosen, path)
        except OrionPdfError as exc:
            self._report(exc, title="Cannot Extract Pages")
            return
        self._status.flash(f"Extracted {len(chosen)} page(s) to {output.name}")

    def split_document(self) -> None:
        if self._session is None:
            return
        document = self._session.document
        default_dir = document.path.parent if document.path else Path.home()
        dialog = SplitDialog(document.page_count, default_dir, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            groups = dialog.groups()
            if groups is None:
                results = self._export.split_every(document, dialog.every, dialog.output_dir)
            else:
                results = self._export.split_by_ranges(document, groups, dialog.output_dir)
        except (OrionPdfError, ValueError) as exc:
            self._report(exc, title="Cannot Split Document")
            return
        QMessageBox.information(
            self,
            "Split Complete",
            f"{len(results)} files were written to:\n{dialog.output_dir}",
        )

    def merge_documents(self) -> None:
        current_name = self._session.display_name if self._session else None
        dialog = MergeDialog(self, current_name=current_name)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        items = dialog.items()
        suggestion = Path(
            self._settings.get("last_directory", "") or str(Path.home())
        ) / "merged.pdf"
        path, _ = QFileDialog.getSaveFileName(self, "Save Merged PDF", str(suggestion), PDF_FILTER)
        if not path:
            return
        try:
            output = self._export.merge(
                items,
                path,
                document=self._session.document if self._session else None,
                current_marker=CURRENT_DOCUMENT,
            )
        except OrionPdfError as exc:
            self._report(exc, title="Cannot Merge Documents")
            return

        answer = QMessageBox.question(
            self,
            "Merge Complete",
            f"{output.name} was created.\n\nOpen it now?",
            QMessageBox.StandardButton.Open | QMessageBox.StandardButton.Close,
            QMessageBox.StandardButton.Open,
        )
        if answer == QMessageBox.StandardButton.Open:
            self.open_path(output)

    def _on_thumbnail_action(self, name: str, rows: list[int]) -> None:
        if name == "rotate_left":
            self.rotate_pages(-90, rows)
        elif name == "rotate_right":
            self.rotate_pages(90, rows)
        elif name == "duplicate":
            if self._session is not None:
                self._session.history.push(DuplicatePageCommand(self._session.document, rows[0]))
        elif name == "insert_after":
            if self._session is not None:
                page = self._session.document.page_at(rows[-1])
                size = page.display_size if page else Size(595.0, 842.0)
                self._session.history.push(
                    InsertPageCommand(self._session.document, rows[-1] + 1, size)
                )
        elif name == "extract":
            self.extract_pages(rows)
        elif name == "delete":
            self.delete_pages(rows)

    # ------------------------------------------------------------------
    # Navigation and search
    # ------------------------------------------------------------------
    def go_to_page(self) -> None:
        if self._session is None:
            return
        dialog = GoToPageDialog(
            self._session.document.page_count, self._canvas.current_page, self
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._canvas.go_to_page(dialog.page_index)

    def show_search(self) -> None:
        if self._session is None:
            return
        self._search.activate()

    def _on_search_hit(self, hit: SearchHit | None) -> None:
        if hit is None:
            return
        self._canvas.set_search_hits(
            self._search.grouped_hits(), (hit.page_index, hit.hit_index)
        )
        self._canvas.reveal_rect(hit.page_index, hit.rect)

    # ------------------------------------------------------------------
    # Signals from the canvas
    # ------------------------------------------------------------------
    def _on_tool_selected(self, tool: Tool) -> None:
        self._canvas.set_tool(tool)
        info_hint = {
            Tool.SELECT: "",
            Tool.HAND: "Drag to scroll. Hold Space with any tool to pan.",
        }.get(tool)
        if info_hint is None:
            from orion.ui.tools import TOOL_INFO

            info_hint = TOOL_INFO[tool].hint
        if info_hint:
            self._status.flash(info_hint, 3000)

    def _return_to_select_tool(self) -> None:
        """Most tools are one-shot; go back to Select once the object exists."""
        if self._canvas.tool in (Tool.SELECT, Tool.HAND, Tool.FREEHAND):
            return
        self._tool_palette.set_tool(Tool.SELECT)
        self._canvas.set_tool(Tool.SELECT)

    def _on_current_page_changed(self, index: int) -> None:
        self._refresh_page_display(index)
        self._thumbnails.set_current_page(index)
        self._update_ui_state()

    def _refresh_page_display(self, index: int | None = None) -> None:
        page = self._canvas.current_page if index is None else index
        total = self._canvas.page_count
        self._toolbar.set_page(page, total)
        self._status.set_page(page, total)

    def _on_zoom_changed(self, zoom: float, mode: str) -> None:
        self._toolbar.set_zoom(zoom)
        self._status.set_zoom(zoom, mode)
        self._actions["view.fit_page"].setChecked(mode == "fit_page")
        self._actions["view.fit_width"].setChecked(mode == "fit_width")
        self._settings.set("zoom_mode", mode)
        if mode == "custom":
            self._settings.set("zoom", zoom)

    def _on_selection_changed(self, objects: list) -> None:
        self._properties.show_selection(objects, self._canvas.current_page)
        self._update_ui_state()

    def _on_files_dropped(self, paths: list[str], page_index: int, position: Point) -> None:
        for raw in paths:
            path = Path(raw)
            suffix = path.suffix.lower()
            if suffix == ".pdf":
                self.open_path(path)
                return
            if suffix in SUPPORTED_EXTENSIONS and self._session is not None:
                self._place_image(path, page_index, position)
                return
        self._status.flash("Drop a PDF file, or a PNG, JPEG or WEBP image.")

    # ------------------------------------------------------------------
    # Model change plumbing
    # ------------------------------------------------------------------
    def _on_history_changed(self, _history) -> None:
        self._update_ui_state()

    def _on_clean_changed(self, _is_clean: bool) -> None:
        self._update_title()
        self._update_ui_state()

    def _on_modified_changed(self, modified: bool) -> None:
        self._status.set_modified(modified and self._session is not None)
        self._update_title()

    def _on_pages_changed(self, _document: Document) -> None:
        self._thumbnails.reload()
        self._refresh_page_display()
        self._update_ui_state()

    def _after_model_change(self) -> None:
        self._properties.refresh()
        self._thumbnails.refresh_all()
        self._update_ui_state()

    # ------------------------------------------------------------------
    # UI state
    # ------------------------------------------------------------------
    def _update_title(self) -> None:
        if self._session is None:
            self.setWindowTitle(f"{APP_NAME} — {APP_SUBTITLE}")
            return
        marker = "• " if self._session.is_modified else ""
        self.setWindowTitle(f"{marker}{self._session.display_name} — {APP_NAME}")

    def _update_ui_state(self) -> None:
        session = self._session
        has_document = session is not None
        self._actions.set_document_open(has_document)

        if session is None:
            self._status.set_modified(False)
            return

        history = session.history
        undo = self._actions["edit.undo"]
        redo = self._actions["edit.redo"]
        undo.setEnabled(history.can_undo)
        redo.setEnabled(history.can_redo)
        undo.setText(f"&Undo {history.undo_text}".rstrip())
        redo.setText(f"&Redo {history.redo_text}".rstrip())

        has_selection = bool(self._canvas.selected_objects())
        for key in ("edit.cut", "edit.copy", "edit.duplicate", "edit.delete",
                    "edit.bring_front", "edit.send_back"):
            self._actions[key].setEnabled(has_selection)
        self._actions["edit.paste"].setEnabled(not self._clipboard.is_empty)
        self._actions["tools.edit_text"].setEnabled(
            any(isinstance(obj, TextObject) for obj in self._canvas.selected_objects())
        )

        index, total = self._canvas.current_page, self._canvas.page_count
        self._actions["view.first_page"].setEnabled(index > 0)
        self._actions["view.previous_page"].setEnabled(index > 0)
        self._actions["view.next_page"].setEnabled(index < total - 1)
        self._actions["view.last_page"].setEnabled(index < total - 1)
        self._actions["pages.move_up"].setEnabled(index > 0)
        self._actions["pages.move_down"].setEnabled(index < total - 1)
        self._actions["pages.delete"].setEnabled(total > 1)
        self._actions["file.save"].setEnabled(session.is_modified or session.path is None)
        self._status.set_modified(session.is_modified)

    def _rebuild_recent_menu(self, paths) -> None:
        menu = self._menus.recent
        if menu is None:
            return
        menu.clear()
        entries = list(paths)
        if not entries:
            action = menu.addAction("No recent files")
            action.setEnabled(False)
            return
        for path in entries:
            action = menu.addAction(path.name)
            action.setToolTip(str(path))
            action.setData(str(path))
            action.triggered.connect(
                lambda _checked=False, target=Path(path): self.open_path(target)
            )
        menu.addSeparator()
        menu.addAction(self._actions["file.clear_recent"])

    def _clear_recent(self) -> None:
        self._recent.clear()

    # ------------------------------------------------------------------
    # Autosave and recovery
    # ------------------------------------------------------------------
    def _autosave_tick(self) -> None:
        if self._session is None:
            return
        if self._session.autosave.maybe_save(self._session.document):
            log.debug("Autosave snapshot written")

    def _offer_recovery(self) -> None:
        try:
            snapshots = list_recoverable()
        except Exception:  # pragma: no cover - unreadable recovery folder
            log.debug("Could not list recovery snapshots", exc_info=True)
            return
        if not snapshots:
            return
        dialog = RecoveryDialog(snapshots, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        snapshot = dialog.selected()
        if snapshot is None:
            return
        try:
            document = snapshot.load()
        except Exception as exc:
            self._report(exc, title="Cannot Recover Document")
            return
        session = self._files.new_session(document, document.path)
        self._attach_session(session)
        document.set_modified(True)
        snapshot.discard()
        self._status.flash("Recovered document — use Save As to write it to a file.")

    # ------------------------------------------------------------------
    # Help
    # ------------------------------------------------------------------
    def show_shortcuts(self) -> None:
        rows = self._actions.shortcut_table()
        body = "\n".join(f"{name:<28}{sequence}" for name, sequence in rows)
        box = QMessageBox(self)
        box.setWindowTitle("Keyboard Shortcuts")
        box.setText("Orion keyboard shortcuts")
        box.setDetailedText(body)
        box.setIcon(QMessageBox.Icon.Information)
        box.exec()

    def open_log_folder(self) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        QDesktopServices.openUrl(QUrl.fromLocalFile(str(log_dir())))

    # ------------------------------------------------------------------
    # Errors
    # ------------------------------------------------------------------
    def _report(self, error: BaseException, *, title: str = "Orion") -> None:
        """Show a friendly message; the traceback goes to the log only (spec §25)."""
        message = describe_exception(error)
        detail = getattr(error, "detail", "") or ""
        log.error("%s: %s%s", title, message, f" ({detail})" if detail else "")
        box = QMessageBox(self)
        box.setWindowTitle(title)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setText(message)
        if detail:
            box.setDetailedText(detail)
        box.exec()

    # ------------------------------------------------------------------
    # Window lifecycle
    # ------------------------------------------------------------------
    def _restore_window_state(self) -> None:
        geometry = self._settings.get("window_geometry")
        state = self._settings.get("window_state")
        try:
            if geometry:
                self.restoreGeometry(QByteArray.fromBase64(geometry.encode("ascii")))
            else:
                self.resize(1280, 840)
            if state:
                self.restoreState(QByteArray.fromBase64(state.encode("ascii")))
        except Exception:  # pragma: no cover - corrupt settings must not block start-up
            log.debug("Could not restore window state", exc_info=True)
            self.resize(1280, 840)

    def _store_window_state(self) -> None:
        self._settings.update(
            {
                "window_geometry": bytes(self.saveGeometry().toBase64()).decode("ascii"),
                "window_state": bytes(self.saveState().toBase64()).decode("ascii"),
                "show_thumbnails": self._thumbnail_dock.isVisible(),
                "show_properties": self._properties_dock.isVisible(),
            }
        )

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt naming
        if not self._confirm_discard():
            event.ignore()
            return
        self._autosave_timer.stop()
        self._store_window_state()
        self._detach_session()
        event.accept()

    # -- drag and drop on the window itself --------------------------------
    def dragEnterEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802 - Qt naming
        paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        if paths:
            event.acceptProposedAction()
            self._on_files_dropped(paths, self._canvas.current_page, Point(72.0, 72.0))


class _Placeholder(QWidget):
    """What the window shows when nothing is open."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        title = QLabel(APP_NAME)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size: 40px; font-weight: 700;")
        layout.addWidget(title)

        subtitle = QLabel(APP_SUBTITLE)
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setProperty("role", "hint")
        layout.addWidget(subtitle)

        hint = QLabel("Open a PDF with Ctrl+O, or drop one here.")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setProperty("role", "hint")
        layout.addWidget(hint)
