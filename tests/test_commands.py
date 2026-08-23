# Orion — PDF Editor for Desktop
# Copyright (C) 2026 Marco Lombardo
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# Distributed WITHOUT ANY WARRANTY; see LICENSE for the full terms.
# A commercial licence, without the AGPL's obligations, is available for use
# in proprietary or closed-source products — see COMMERCIAL-LICENSE.md.

"""Undo/redo tests (spec §27)."""

from __future__ import annotations

import pytest

from orion.commands import (
    AddObjectCommand,
    DeleteObjectsCommand,
    DeletePagesCommand,
    DuplicatePageCommand,
    History,
    ImportPagesCommand,
    InsertPageCommand,
    MacroCommand,
    ModifyObjectCommand,
    MoveObjectsCommand,
    MovePageCommand,
    RotatePagesCommand,
    TransformObjectsCommand,
)
from orion.commands.page_commands import ReorderPagesCommand
from orion.document.document import Document, DocumentSource
from orion.document.objects import ShapeKind, ShapeObject, TextObject
from orion.document.page import Page, PageSource
from orion.utils.geometry import Rect, Size


@pytest.fixture
def document() -> Document:
    return Document.blank(page_count=3)


@pytest.fixture
def history() -> History:
    return History()


def _shape(x: float = 10.0, y: float = 20.0) -> ShapeObject:
    return ShapeObject(rect=Rect.from_xywh(x, y, 50.0, 30.0), shape=ShapeKind.RECTANGLE)


# -- objects -------------------------------------------------------------
def test_add_and_undo_object(document, history):
    shape = _shape()
    history.push(AddObjectCommand(document, 0, shape))
    assert len(document[0]) == 1
    history.undo()
    assert len(document[0]) == 0
    history.redo()
    assert document[0].find_object(shape.id) is not None


def test_delete_restores_z_order(document, history):
    a, b, c = _shape(0), _shape(1), _shape(2)
    for obj in (a, b, c):
        document[0].add_object(obj)
    history.push(DeleteObjectsCommand(document, 0, [b.id]))
    assert [o.id for o in document[0]] == [a.id, c.id]
    history.undo()
    assert [o.id for o in document[0]] == [a.id, b.id, c.id]


def test_consecutive_moves_merge_into_one_undo_step(document, history):
    shape = _shape()
    document[0].add_object(shape)
    for _ in range(10):
        history.push(MoveObjectsCommand(document, 0, [shape.id], 1.0, 2.0))
    assert history.depth == 1
    assert shape.rect.x0 == pytest.approx(20.0)
    history.undo()
    assert shape.rect.x0 == pytest.approx(10.0)


def test_moves_of_a_different_selection_do_not_merge(document, history):
    a, b = _shape(0), _shape(1)
    document[0].add_object(a)
    document[0].add_object(b)
    history.push(MoveObjectsCommand(document, 0, [a.id], 5.0, 0.0))
    history.push(MoveObjectsCommand(document, 0, [b.id], 5.0, 0.0))
    assert history.depth == 2


def test_transform_records_before_and_after(document, history):
    shape = _shape()
    document[0].add_object(shape)
    before = {shape.id: (shape.rect, shape.rotation)}
    after = {shape.id: (Rect.from_xywh(0, 0, 100, 100), 45.0)}
    history.push(TransformObjectsCommand(document, 0, before, after, text="Resize"))
    assert shape.rotation == 45.0
    history.undo()
    assert shape.rotation == 0.0
    assert shape.rect.width == pytest.approx(50.0)


def test_modify_object_merges_same_property(document, history):
    text = TextObject(rect=Rect.from_xywh(0, 0, 100, 20), text="hi")
    document[0].add_object(text)
    for size in (11.0, 12.0, 13.0):
        history.push(ModifyObjectCommand(document, 0, text.id, {"font_size": size}))
    assert history.depth == 1
    assert text.font_size == pytest.approx(13.0)
    history.undo()
    assert text.font_size == pytest.approx(12.0)


def test_modify_object_does_not_merge_different_properties(document, history):
    text = TextObject(rect=Rect.from_xywh(0, 0, 100, 20), text="hi")
    document[0].add_object(text)
    history.push(ModifyObjectCommand(document, 0, text.id, {"font_size": 20.0}))
    history.push(ModifyObjectCommand(document, 0, text.id, {"bold": True}))
    assert history.depth == 2


# -- pages ---------------------------------------------------------------
def test_insert_and_delete_pages(document, history):
    history.push(InsertPageCommand(document, 1))
    assert document.page_count == 4
    history.undo()
    assert document.page_count == 3

    ids = [p.id for p in document]
    history.push(DeletePagesCommand(document, [0, 2]))
    assert document.page_count == 1
    history.undo()
    assert [p.id for p in document] == ids


def test_duplicate_page_places_copy_after_original(document, history):
    document[1].add_object(_shape())
    history.push(DuplicatePageCommand(document, 1))
    assert document.page_count == 4
    assert len(document[2]) == 1
    assert document[2].id != document[1].id
    # The copy must be independent of the original.
    assert document[2].objects[0].id != document[1].objects[0].id
    history.undo()
    assert document.page_count == 3


def test_move_and_reorder_pages(document, history):
    ids = [p.id for p in document]
    history.push(MovePageCommand(document, 0, 2))
    assert [p.id for p in document] == [ids[1], ids[2], ids[0]]
    history.undo()
    assert [p.id for p in document] == ids

    history.push(ReorderPagesCommand(document, [2, 0, 1]))
    assert [p.id for p in document] == [ids[2], ids[0], ids[1]]
    history.undo()
    assert [p.id for p in document] == ids


def test_rotate_pages(document, history):
    history.push(RotatePagesCommand(document, [0, 1], 90))
    assert document[0].rotation == 90
    assert document[2].rotation == 0
    assert document[0].display_size == Size(842.0, 595.0)
    history.undo()
    assert document[0].rotation == 0


def test_import_pages(document, history):
    source = DocumentSource(key="other", label="other.pdf")
    imported = [
        Page(base_size=Size(200.0, 300.0), source=PageSource("other", i)) for i in range(2)
    ]
    history.push(ImportPagesCommand(document, 1, source, imported))
    assert document.page_count == 5
    assert document[1].base_size == Size(200.0, 300.0)
    assert "other" in document.sources
    history.undo()
    assert document.page_count == 3
    assert "other" not in document.sources


# -- history semantics ---------------------------------------------------
def test_clean_marker_tracks_saves(document, history):
    assert history.is_clean
    history.push(AddObjectCommand(document, 0, _shape()))
    assert not history.is_clean
    history.mark_clean()
    assert history.is_clean
    history.undo()
    assert not history.is_clean
    history.redo()
    assert history.is_clean


def test_redo_stack_is_dropped_on_a_new_edit(document, history):
    history.push(AddObjectCommand(document, 0, _shape()))
    history.undo()
    assert history.can_redo
    history.push(AddObjectCommand(document, 0, _shape(99)))
    assert not history.can_redo


def test_macro_groups_commands(document, history):
    history.begin_macro("Paste")
    history.push(AddObjectCommand(document, 0, _shape(1)))
    history.push(AddObjectCommand(document, 0, _shape(2)))
    history.end_macro()
    assert history.depth == 1
    assert len(document[0]) == 2
    history.undo()
    assert len(document[0]) == 0


def test_macro_rolls_back_on_failure(document):
    class Boom(Exception):
        pass

    class Failing(AddObjectCommand):
        def execute(self) -> None:
            raise Boom

    good = AddObjectCommand(document, 0, _shape(1))
    macro = MacroCommand([good, Failing(document, 0, _shape(2))], "Broken")
    with pytest.raises(Boom):
        macro.execute()
    assert len(document[0]) == 0


def test_history_limit_drops_oldest(document):
    history = History(limit=5)
    for index in range(10):
        history.push(AddObjectCommand(document, 0, _shape(index)))
    assert history.depth == 5


def test_history_limit_invalidates_a_lost_clean_marker(document):
    history = History(limit=3)
    history.mark_clean()
    for index in range(6):
        history.push(AddObjectCommand(document, 0, _shape(index)))
    while history.can_undo:
        history.undo()
    assert not history.is_clean


def test_separate_drags_stay_separate_undo_steps(document, history):
    """A completed gesture is one undo step; the next gesture is another."""
    shape = _shape()
    document[0].add_object(shape)
    history.push(
        MoveObjectsCommand(document, 0, [shape.id], 5.0, 0.0, allow_merge=False)
    )
    history.push(
        MoveObjectsCommand(document, 0, [shape.id], 7.0, 0.0, allow_merge=False)
    )
    assert history.depth == 2
    history.undo()
    assert shape.rect.x0 == pytest.approx(15.0)
    history.undo()
    assert shape.rect.x0 == pytest.approx(10.0)


def test_separate_transform_gestures_stay_separate(document, history):
    shape = _shape()
    document[0].add_object(shape)
    first = {shape.id: (shape.rect, 0.0)}
    second = {shape.id: (shape.rect, 30.0)}
    third = {shape.id: (shape.rect, 60.0)}
    history.push(
        TransformObjectsCommand(document, 0, first, second, text="Rotate", allow_merge=False)
    )
    history.push(
        TransformObjectsCommand(document, 0, second, third, text="Rotate", allow_merge=False)
    )
    assert history.depth == 2
