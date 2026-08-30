# Orion — PDF Editor for Desktop
# Copyright (C) 2026 Marco Lombardo
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# Distributed WITHOUT ANY WARRANTY; see LICENSE for the full terms.
# A commercial licence, without the AGPL's obligations, is available for use
# in proprietary or closed-source products — see COMMERCIAL-LICENSE.md.

"""Open / Save / Save As orchestration and file safety (spec §19, §20)."""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from orion.commands.history import History
from orion.document.document import Document, DocumentSource
from orion.document.page import Page
from orion.pdf import reader as pdf_reader
from orion.pdf import writer as pdf_writer
from orion.pdf.errors import PdfWriteError
from orion.pdf.renderer import PageRenderer
from orion.services.autosave import AutosaveService
from orion.utils.events import Event
from orion.utils.fileio import remove_quietly
from orion.utils.paths import cache_dir

log = logging.getLogger(__name__)

__all__ = ["DocumentSession", "FileService"]


@dataclass
class DocumentSession:
    """Everything belonging to one open document.

    Bundling these together is what keeps multi-document support (spec §21) a
    UI change rather than an architectural one: today the window holds one
    session, tomorrow it holds a list of them.
    """

    document: Document
    history: History
    renderer: PageRenderer
    autosave: AutosaveService
    path: Path | None = None
    #: Sources copied aside because the user saved over them (see FileService).
    shadowed_sources: dict[str, Path] = field(default_factory=dict)

    @property
    def display_name(self) -> str:
        return self.path.name if self.path else "Untitled"

    @property
    def is_modified(self) -> bool:
        return not self.history.is_clean or self.document.modified

    def mark_saved(self, path: Path) -> None:
        self.path = path
        self.document.path = path
        self.history.mark_clean()
        self.document.set_modified(False)
        self.autosave.discard()

    def close(self) -> None:
        self.renderer.close_all()
        self.autosave.discard()
        for shadow in self.shadowed_sources.values():
            remove_quietly(shadow)
        self.shadowed_sources.clear()


class FileService:
    """Creates and saves :class:`DocumentSession` objects."""

    def __init__(self, *, cache_bytes: int | None = None) -> None:
        self._cache_bytes = cache_bytes
        self.session_opened = Event("session_opened")
        self.session_saved = Event("session_saved")

    # -- opening ---------------------------------------------------------
    def new_session(self, document: Document, path: Path | None = None) -> DocumentSession:
        from orion.pdf.renderer import DEFAULT_CACHE_BYTES

        renderer = PageRenderer(self._cache_bytes or DEFAULT_CACHE_BYTES)
        renderer.register_document(document)
        session = DocumentSession(
            document=document,
            history=History(),
            renderer=renderer,
            autosave=AutosaveService(document.id),
            path=path,
        )
        self.session_opened.emit(session)
        return session

    def open(self, path: str | Path, password: str | None = None) -> DocumentSession:
        """Open a PDF and return a ready-to-edit session."""
        document, opened = pdf_reader.load_document(path, password)
        from orion.pdf.renderer import DEFAULT_CACHE_BYTES

        renderer = PageRenderer(self._cache_bytes or DEFAULT_CACHE_BYTES)
        source = next(iter(document.sources.values()))
        renderer.register_source(source, opened)

        session = DocumentSession(
            document=document,
            history=History(),
            renderer=renderer,
            autosave=AutosaveService(document.id),
            path=Path(path),
        )
        session.history.mark_clean()
        self.session_opened.emit(session)
        return session

    def create_blank(self, page_count: int = 1) -> DocumentSession:
        return self.new_session(Document.blank(page_count=page_count))

    # -- importing -------------------------------------------------------
    def import_pages(
        self, session: DocumentSession, path: str | Path, indices: list[int] | None = None
    ) -> tuple[DocumentSource, list[Page]]:
        """Prepare pages of another PDF for insertion (no copying yet)."""
        opened = pdf_reader.open_pdf(path)
        try:
            source = DocumentSource.for_path(Path(path))
            pages = pdf_reader.build_pages(opened, source.key, indices)
            session.renderer.register_source(source, opened)
            return source, pages
        except Exception:
            opened.close()
            raise

    # -- saving ----------------------------------------------------------
    def save(self, session: DocumentSession) -> Path:
        """Save to the session's own path (spec §19)."""
        if session.path is None:
            raise PdfWriteError("This document has never been saved; use Save As.")
        return self.save_as(session, session.path)

    def save_as(self, session: DocumentSession, path: str | Path) -> Path:
        """Write the document to *path*.

        Saving **over a file the document still reads from** needs care.  The
        model keeps its objects as a live overlay on top of the original page
        content, so if the original were replaced by the stamped result, the
        objects would be rendered twice on screen and stamped twice on the next
        save.  Before overwriting, the pristine original is therefore copied to
        a private shadow file and the source re-pointed at it, which keeps the
        model — and the whole undo history — valid across saves.
        """
        path = Path(path)
        threatened = [
            source
            for source in session.document.sources.values()
            if source.path is not None and _same_file(source.path, path)
        ]

        for source in threatened:
            self._shadow(session, source)

        # The renderer holds file handles; on Windows an open handle blocks
        # replacement, so release them for the duration of the write.
        session.renderer.close_all()
        try:
            pdf_writer.save_document(session.document, path)
        finally:
            session.renderer.register_document(session.document)

        session.mark_saved(path)
        self.session_saved.emit(session, path)
        log.info("Session saved to %s", path)
        return path

    def _shadow(self, session: DocumentSession, source: DocumentSource) -> None:
        """Copy a source aside so the original content survives being overwritten."""
        if source.key in session.shadowed_sources or source.path is None:
            return
        try:
            directory = cache_dir() / "shadow"
            directory.mkdir(parents=True, exist_ok=True)
            shadow = directory / f"{session.document.id}-{source.key}.pdf"
            shutil.copy2(source.path, shadow)
        except OSError as exc:
            raise PdfWriteError(
                "A working copy of the original document could not be made, "
                "so the file was not overwritten.",
                detail=str(exc),
            ) from exc
        session.renderer.close_source(source.key)
        source.path = shadow
        session.shadowed_sources[source.key] = shadow
        log.debug("Shadowed %s -> %s", source.display_name, shadow)


def _same_file(a: Path, b: Path) -> bool:
    try:
        if a.exists() and b.exists():
            return a.samefile(b)
    except OSError:  # pragma: no cover - network paths
        pass
    try:
        return a.resolve() == b.resolve()
    except OSError:  # pragma: no cover
        return str(a) == str(b)
