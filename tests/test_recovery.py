# Orion — PDF Editor for Desktop
# Copyright (C) 2026 Marco Lombardo
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# Distributed WITHOUT ANY WARRANTY; see LICENSE for the full terms.
# A commercial licence, without the AGPL's obligations, is available for use
# in proprietary or closed-source products — see COMMERCIAL-LICENSE.md.

"""Autosave and crash recovery (spec §32)."""

from __future__ import annotations

import json
import os

import pytest

from orion.document.document import Document
from orion.document.objects import ShapeObject, TextObject
from orion.services.autosave import (
    SNAPSHOT_SUFFIX,
    AutosaveService,
    _process_alive,
    discard_all,
    list_recoverable,
)
from orion.utils.geometry import Rect


@pytest.fixture
def recovery_dir(tmp_path):
    directory = tmp_path / "recovery"
    directory.mkdir()
    return directory


def _document() -> Document:
    """A document with unsaved edits, marked the way the commands mark it."""
    document = Document.blank(page_count=2)
    document[0].add_object(
        TextObject(rect=Rect.from_xywh(10, 10, 200, 40), text="unsaved work")
    )
    document[1].add_object(ShapeObject(rect=Rect.from_xywh(5, 5, 50, 50)))
    document.notify_content_changed(0)
    return document


def test_nothing_is_written_for_an_unmodified_document(recovery_dir):
    service = AutosaveService("session-a", directory=recovery_dir)
    document = Document.blank()
    assert document.modified is False
    assert service.maybe_save(document) is False
    assert list(recovery_dir.iterdir()) == []


def test_snapshot_is_written_and_can_be_restored(recovery_dir):
    service = AutosaveService("session-a", directory=recovery_dir)
    document = _document()
    assert service.maybe_save(document) is True
    assert service.snapshot_path.exists()

    # The snapshot is JSON, not a PDF: it can never be mistaken for the original.
    payload = json.loads(service.snapshot_path.read_text(encoding="utf-8"))
    assert payload["pages"][0]["objects"][0]["text"] == "unsaved work"

    restored = Document.from_dict(payload)
    assert restored.page_count == 2
    assert restored[0].objects[0].text == "unsaved work"


def test_discard_removes_the_snapshot_and_its_metadata(recovery_dir):
    service = AutosaveService("session-a", directory=recovery_dir)
    service.maybe_save(_document())
    assert list(recovery_dir.iterdir())
    service.discard()
    assert list(recovery_dir.iterdir()) == []


def test_disabling_autosave_discards_what_it_wrote(recovery_dir):
    service = AutosaveService("session-a", directory=recovery_dir)
    service.maybe_save(_document())
    service.set_enabled(False)
    assert list(recovery_dir.iterdir()) == []
    assert service.maybe_save(_document()) is False


def test_list_recoverable_finds_a_snapshot_from_a_dead_process(recovery_dir):
    service = AutosaveService("session-dead", directory=recovery_dir)
    service.maybe_save(_document())

    # Rewrite the metadata as if it came from a process that no longer exists.
    meta = recovery_dir / f"session-dead{SNAPSHOT_SUFFIX}.meta"
    info = json.loads(meta.read_text(encoding="utf-8"))
    info["pid"] = 999_999_999
    meta.write_text(json.dumps(info), encoding="utf-8")

    snapshots = list_recoverable(recovery_dir)
    assert len(snapshots) == 1
    assert snapshots[0].page_count == 2
    assert snapshots[0].load()[0].objects[0].text == "unsaved work"
    assert "ago" in snapshots[0].age_text


def test_a_snapshot_from_a_live_process_is_left_alone(recovery_dir):
    service = AutosaveService("session-live", directory=recovery_dir)
    service.maybe_save(_document())
    meta = recovery_dir / f"session-live{SNAPSHOT_SUFFIX}.meta"
    info = json.loads(meta.read_text(encoding="utf-8"))
    assert info["pid"] == os.getpid()
    # Our own process is alive, so this snapshot is in use, not recoverable.
    assert list_recoverable(recovery_dir) == []


def test_the_current_session_can_exclude_itself(recovery_dir):
    AutosaveService("session-a", directory=recovery_dir).maybe_save(_document())
    assert list_recoverable(recovery_dir, exclude_session="session-a") == []


def test_discard_all_clears_the_directory(recovery_dir):
    for name in ("one", "two"):
        service = AutosaveService(name, directory=recovery_dir)
        service.maybe_save(_document())
        meta = recovery_dir / f"{name}{SNAPSHOT_SUFFIX}.meta"
        info = json.loads(meta.read_text(encoding="utf-8"))
        info["pid"] = 999_999_999
        meta.write_text(json.dumps(info), encoding="utf-8")

    assert len(list_recoverable(recovery_dir)) == 2
    discard_all(recovery_dir)
    assert list_recoverable(recovery_dir) == []


def test_autosave_never_raises_when_the_directory_is_unusable(recovery_dir, monkeypatch):
    service = AutosaveService("session-a", directory=recovery_dir / "gone")

    def explode(*_args, **_kwargs):
        raise OSError("disk on fire")

    monkeypatch.setattr(
        "orion.services.autosave.save_document_snapshot", explode
    )
    # Autosave must never interrupt the user, whatever the file system does.
    assert service.maybe_save(_document()) is False


def test_a_corrupt_snapshot_is_reported_but_still_listed(recovery_dir):
    """A truncated snapshot must not crash the recovery listing."""
    broken = recovery_dir / f"broken{SNAPSHOT_SUFFIX}"
    broken.write_text("{ not json", encoding="utf-8")
    snapshots = list_recoverable(recovery_dir)
    assert len(snapshots) == 1
    with pytest.raises(ValueError):
        snapshots[0].load()


# -- process liveness ----------------------------------------------------
def test_process_liveness_probe():
    """This decides whether a snapshot belongs to a running instance."""
    assert _process_alive(os.getpid()) is True
    assert _process_alive(999_999_999) is False
    assert _process_alive(0) is False
    assert _process_alive(-1) is False


def test_the_liveness_probe_never_signals_the_process():
    """Regression guard: ``os.kill(pid, 0)`` *terminates* the process on Windows.

    Only that is asserted here.  What the probe *answers* on the Windows path
    depends on whether a real kernel32 is there to ask — it is, on Windows,
    where a missing pid correctly comes back as not-alive; it is not, on this
    machine, where the conservative fallback says alive.  The answer itself is
    checked natively in :func:`test_process_liveness_probe`.
    """
    import orion.services.autosave as autosave

    called: list[tuple[int, int]] = []
    original = os.kill

    def spy(pid, signal_number):
        called.append((pid, signal_number))
        return original(pid, signal_number)

    monkeypatched = pytest.MonkeyPatch()
    try:
        monkeypatched.setattr(autosave.os, "kill", spy)
        monkeypatched.setattr(autosave.sys, "platform", "win32")
        result = autosave._process_alive(999_999_999)
    finally:
        monkeypatched.undo()

    assert isinstance(result, bool)
    assert called == [], "the Windows path must never signal a foreign process"
