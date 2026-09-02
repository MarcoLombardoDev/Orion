# Developing Orion

A practical companion to [`ARCHITECTURE.md`](ARCHITECTURE.md), which explains
*why* the code is shaped the way it is. This file is about working in it.

## Set up

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
ruff check orion tests
```

On Linux, PySide6 needs a handful of shared libraries that minimal images omit:

```bash
sudo apt install libegl1 libgl1 libxkbcommon0 libdbus-1-3 libfontconfig1
```

Headless? `QT_QPA_PLATFORM=offscreen pytest` runs everything, GUI tests included.

## Running it

```bash
python -m orion                     # or: orion
python -m orion --log-level DEBUG file.pdf
```

`ORION_HOME=/tmp/orion-scratch python -m orion` redirects the settings, cache,
log and recovery directories — useful when you do not want to disturb your real
configuration while testing.

## Where things live

| I want to change… | Look in |
|---|---|
| what a menu or shortcut does | `orion/ui/actions.py` (table) + `MainWindow._connect_actions` |
| where a menu entry appears | `orion/ui/menu.py` (structure only) |
| the toolbar or tool palette | `orion/ui/toolbar.py` |
| how an object is drawn on screen | `orion/ui/object_items.py` |
| how an object is written to PDF | `orion/pdf/writer.py` |
| what an object *is* | `orion/document/objects.py`, `annotations.py` |
| an undoable operation | `orion/commands/` |
| colours | `orion/ui/theme.py` (tokens; everything derives from them) |
| icons | `orion/ui/icons.py` (drawn in code, not files) |
| page layout, zoom, selection | `orion/ui/canvas.py` |
| open / save orchestration | `orion/services/file_service.py` |

## The five rules

1. **The UI never manipulates the PDF file.** It edits the document model.
2. **`document/`, `commands/` and `utils/` never import Qt.** Test with
   `python -c "import orion.document, orion.commands, orion.utils"` in an
   environment without PySide6 if you want to be sure.
3. **Coordinate conversions live in two modules only** —
   `utils/geometry.py` and `pdf/coordinates.py`.
4. **Every user-visible edit is a `Command`.**
5. **Reuse before adding.** Most features are a new row in an existing table.

## Coordinate systems

The one thing worth reading twice.

| Space | Origin | Units |
|---|---|---|
| Base page space | top-left of the page as the *source* displays it | points |
| Scene space | top-left of the page strip | points |
| View space | the widget | pixels |
| PDF content space | mediabox, ignoring `/Rotate` | points |

Two facts drive the design, both pinned by `tests/test_coordinates.py`:

1. Nothing below the conversion is rotation aware. reportlab draws into the
   **unrotated mediabox** and pdfium reports text rectangles there too, so
   `orion/pdf/coordinates.py` maps base page space onto it explicitly, one case
   per `/Rotate` value.
2. The two spaces disagree about rotation twice over. Base space is y-down and
   clockwise-positive (like `QGraphicsItem.setRotation`); content space is y-up
   and counter-clockwise-positive, so angles change sign. And on a quarter turn
   the map *swaps the axes*, so anything with its own up direction — text and
   images — must also be turned by `/Rotate`, or it is written running down the
   page.

Object rectangles are stored in *base* page space, so rotating a page is an
O(1) metadata change and objects stay attached to the content they annotate.
`PageItem`'s content layer carries the display rotation on the canvas; the
writer carries it through the conversion in `orion/pdf/coordinates.py`.

If you touch any of this, `tests/test_coordinates.py` renders the output and
asserts pixel positions. That is deliberate: it fails loudly if a library
upgrade changes the rules — and it is why replacing the PDF engine outright
did not have to change a single one of those assertions.

## Adding a tool

1. A member of `Tool` and an entry in `TOOL_INFO` — `orion/ui/tools.py`.
2. An icon in `ICONS` — `orion/ui/icons.py`.
3. A slot in `ToolPalette.LAYOUT` — `orion/ui/toolbar.py`.
4. Handling in `PdfCanvas.mousePressEvent` / `_commit_draft` if the gesture is
   new.

The action, shortcut and menu entry are generated from those tables.

## Adding an object type

1. A dataclass in `orion/document/objects.py`, plus `register_object_type`.
2. A `QGraphicsItem` in `orion/ui/object_items.py`, registered in `_ITEM_TYPES`.
3. A branch in `_stamp_page` in `orion/pdf/writer.py`.
4. A section in `orion/ui/properties_panel.py` if it has properties of its own.
5. Tests: a serialisation round trip, and a save-pipeline test that reopens the
   written file and checks the object is really there.

## Testing

| File | Covers | Needs a display |
|---|---|---|
| `test_document_model.py` | model, geometry, serialisation | no |
| `test_commands.py` | undo/redo semantics | no |
| `test_operations.py` | merge, split, extract, page ranges | no |
| `test_coordinates.py` | coordinate conversions, by rendering | no |
| `test_save_pipeline.py` | open → edit → save round trips | no |
| `test_recovery.py` | autosave and crash recovery | no |
| `test_page_text_editing.py` | rewriting the document's own text | no |
| `test_redaction.py` | what a redaction removes, proved by reopening | no |
| `test_stamps.py` | watermark fitting, page-number templates | no |
| `test_annotation_import.py` | reading a file's own annotations back | no |
| `test_fonts.py` | system font discovery and subset embedding | no |
| `test_renderer.py` | rasterisation, the cache, and thread safety | no |
| `test_layering.py` | that the Qt-free layers stayed Qt-free | no |
| `test_docs.py` · `test_packaging.py` · `test_release_workflow.py` · `test_third_party_licences.py` | the repository itself: docs, metadata, workflow, licence inventory | no |
| `test_ui.py` | the real widgets, driven offscreen | yes (offscreen is fine) |

`tests/conftest.py` points `ORION_HOME` at a temporary directory for the whole
session, so running the suite never touches your real settings.

## Performance notes

- Only visible pages rasterise; the cache is bounded **by bytes** (256 MB by
  default), not by page count, because the same page at 400% is 256× the size
  of the same page at 25%.
- Rendering runs on a `QThreadPool`, is de-duplicated by cache key, and is
  cancelled wholesale when the zoom changes.
- pdfium is not safe for concurrent access to one document: every engine call holds that
  document's lock. Never call into `orion/pdf` without going through the
  renderer or the writer.
- Thumbnails use a separate small renderer so they cannot evict canvas pages.

## Packaging

`orion.spec` is a PyInstaller spec kept working but not part of the release
process yet:

```bash
pip install pyinstaller
pyinstaller orion.spec
```

The result appears in `dist/`. Packaging is deliberately not a requirement for
building or running Orion.
