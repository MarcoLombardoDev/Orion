# Contributing to Orion

Thanks for wanting to help. This file describes how the project works so a
patch has a good chance of being merged quickly.

## Ground rules

Orion is an **offline desktop application**. Contributions that add network
access, accounts, telemetry, analytics, cloud storage or a licensing system
will not be merged, regardless of how well they are written. If a feature needs
one of those, open an issue and let's discuss it before writing code.

By contributing you agree that your contribution is licensed under the
**AGPL-3.0-or-later**, the same as the rest of the project.

## Getting set up

```bash
git clone https://github.com/MarcoLombardoDev/Orion.git
cd Orion
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

On a machine without a display, run the GUI tests offscreen:

```bash
QT_QPA_PLATFORM=offscreen pytest
```

## Before you write code

Please read [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) first. Orion's value
is in its layering, and a patch that cuts across it costs more to review than it
saves. In particular:

1. **The UI never manipulates the PDF file.** It edits the document model.
   The PDF is read for rendering and written on Save.
2. **`orion/document`, `orion/commands` and `orion/utils` must not import Qt.**
   The test suite depends on that; so does the ability to reuse the model.
3. **Coordinate conversions live in `orion/utils/geometry.py` and
   `orion/pdf/coordinates.py`.** Do not write a conversion anywhere else.
4. **Every user-visible edit is a `Command`.** If it changes the document and
   is not undoable, it is a bug.
5. **Look for the component that already does this.** Most additions are a new
   entry in an existing table, not a new module.

## Adding things

**A new tool** — add a member to `Tool` and an entry to `TOOL_INFO` in
`orion/ui/tools.py`, and an icon to `ICONS` in `orion/ui/icons.py`. The action,
the shortcut, the menu entry and the palette button are all generated from
those tables.

**A new object type** — add the dataclass to `orion/document/objects.py`, call
`register_object_type` so it deserialises, add a `QGraphicsItem` to
`orion/ui/object_items.py` and register it in `_ITEM_TYPES`, and add the
writing branch in `orion/pdf/writer.py`. Add a serialisation round-trip test
and a save-pipeline test.

**A new menu entry** — add an `ActionSpec` to `ACTIONS` in
`orion/ui/actions.py`, place its key in the structure in `orion/ui/menu.py`,
and connect it in `MainWindow._connect_actions`.

## Style

- `ruff check orion tests` must pass; the configuration is in `pyproject.toml`.
- Type annotations on public functions; `from __future__ import annotations` at
  the top of every module.
- Comments explain *why*, not *what*. If a line encodes a non-obvious fact
  about PyMuPDF or Qt, say so — the next person will not rediscover it.
- User-facing strings are sentences, not error codes. A user must never see a
  Python traceback; raise something from `orion/pdf/errors.py` instead.

## Tests

New behaviour needs a test. The suite is fast (a few seconds) so there is no
excuse to skip it.

- Model, command and engine tests need no display and belong in
  `tests/test_document_model.py`, `tests/test_commands.py`,
  `tests/test_operations.py` or `tests/test_save_pipeline.py`.
- Anything touching coordinates belongs in `tests/test_coordinates.py`, which
  renders the output and asserts *pixel positions* — that is deliberate, and it
  is what catches a PyMuPDF behaviour change.
- GUI tests go in `tests/test_ui.py` and drive the real widgets offscreen.

## Commits and pull requests

- One logical change per commit; a message that says what changed and why.
- Describe the user-visible effect in the pull request, and say how you tested it.
- If you changed anything architectural, update `docs/ARCHITECTURE.md` in the
  same pull request.
- Add an entry to `CHANGELOG.md` under *Unreleased*.

## Reporting bugs

Include your operating system, your Python version, what you did, what you
expected and what happened. Orion writes a log file — **Help ▸ Open Log
Folder** shows you where — and the tail of it is usually the fastest route to a
diagnosis. If a specific PDF triggers the problem and you can share it, that
helps enormously; if you cannot, say so and describe the document instead.
