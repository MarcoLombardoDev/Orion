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

Two PyMuPDF behaviours drive the design, both verified experimentally and both
pinned by `tests/test_coordinates.py`:

1. PyMuPDF's content API (`draw_*`, `insert_text`, `insert_image`,
   `add_*_annot`, `search_for`) works in **unrotated mediabox space** — it is
   *not* rotation aware. Only `page.rect` and `get_pixmap()` reflect `/Rotate`.
2. `pymupdf.Matrix(a)` rotates **counter-clockwise** on screen; Orion (like
   `QGraphicsItem.setRotation`) is clockwise-positive.

Object rectangles are stored in *base* page space, so rotating a page is an
O(1) metadata change and objects stay attached to the content they annotate.
`PageItem`'s content layer carries the display rotation on the canvas; the
writer carries it through `derotation_matrix`.

If you touch any of this, `tests/test_coordinates.py` renders the output and
asserts pixel positions. That is deliberate: it fails loudly if a PyMuPDF
upgrade changes the rules.

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
| `test_ui.py` | the real widgets, driven offscreen | yes (offscreen is fine) |

`tests/conftest.py` points `ORION_HOME` at a temporary directory for the whole
session, so running the suite never touches your real settings.

## Performance notes

- Only visible pages rasterise; the cache is bounded **by bytes** (256 MB by
  default), not by page count, because the same page at 400% is 256× the size
  of the same page at 25%.
- Rendering runs on a `QThreadPool`, is de-duplicated by cache key, and is
  cancelled wholesale when the zoom changes.
- PyMuPDF is not thread-safe per document: every engine call holds that
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
