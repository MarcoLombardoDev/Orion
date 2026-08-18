# Orion — Architecture

> This document is the answer to the "first required activity": requirement analysis,
> definitive architecture, directory layout, main classes and responsibilities,
> dependencies, license compatibility, milestones and known technical risks.

---

## 1. Design goals

Orion is an **offline desktop PDF editor**. No server, no account, no database, no cloud.

The single most important architectural rule:

> **The GUI never manipulates the PDF file.**
> The GUI manipulates an in-memory **Document Model**. The PDF file is only read
> (for rendering) and only written on an explicit *Save* / *Save As*.

Everything else follows from that rule: undo/redo becomes cheap, autosave becomes
a model serialization, the original file is never at risk, and the PDF engine can be
replaced without touching the UI.

---

## 2. Layering

```
┌──────────────────────────────────────────────────────────────┐
│ UI  (orion/ui)                                               │
│ MainWindow · Canvas · Thumbnails · PropertiesPanel · Dialogs │
└───────────────┬──────────────────────────────────────────────┘
                │ reads model, emits Commands
┌───────────────▼──────────────────────────────────────────────┐
│ Commands (orion/commands)      History · undo/redo            │
└───────────────┬──────────────────────────────────────────────┘
                │ mutates
┌───────────────▼──────────────────────────────────────────────┐
│ Document Model (orion/document)                              │
│ Document ─ Page ─ PageObject{Text, Image, Shape, Annotation} │
└───────────────┬──────────────────────────────────────────────┘
                │ read on open / write on save
┌───────────────▼──────────────────────────────────────────────┐
│ PDF Engine (orion/pdf)                                       │
│ reader · renderer · writer · operations                      │
└───────────────┬──────────────────────────────────────────────┘
                │
┌───────────────▼──────────────────────────────────────────────┐
│ PyMuPDF · pypdf · Pillow                                     │
└──────────────────────────────────────────────────────────────┘
```

Dependency direction is strictly downward. Concretely:

* `orion/document`, `orion/commands`, `orion/utils` **do not import Qt at all.**
  They are plain Python and are unit-testable without a GUI or a display server.
* `orion/pdf` imports PyMuPDF/Pillow but not Qt (the renderer returns raw RGB
  buffers; the Qt conversion lives in `orion/ui/render_bridge.py`).
* `orion/ui` is the only Qt-aware layer.

Model → UI notification uses a tiny dependency-free observer (`orion/utils/events.py`),
not Qt signals, so the model stays framework-neutral.

### Editing data flow

```
        original PDF (read-only)         Document Model (mutable)
                  │                                │
      renderer ───┴──> page raster ───┐            ├──> object items
                                      ▼            ▼
                                    Canvas (QGraphicsScene)
                                      │
                                      ▼
                                     GUI
```

### Save data flow

```
Document Model ──> pdf/writer.py ──> temp file ──> validate ──> os.replace ──> final PDF
```

---

## 3. Coordinate systems  (the single most error-prone area)

Three spaces exist and **all conversions live in `orion/utils/geometry.py` and
`orion/pdf/coordinates.py`**. No conversion formula is duplicated anywhere else.

| Space | Origin | Units | Where used |
|---|---|---|---|
| **Base page space** | top-left of the page *as the source PDF displays it* | PostScript points (1/72") | `Page.objects`, all model geometry |
| **Scene space** | top-left of the whole document strip | points | `QGraphicsScene` |
| **View/device space** | widget | pixels | Qt, after `zoom` transform |
| **PDF content space** | bottom-left / mediabox | points | inside `pdf/writer.py` only |

Key decisions, each verified experimentally against PyMuPDF 1.28 (see
`tests/test_coordinates.py`, which re-verifies them on every run):

1. **PyMuPDF's content API is *not* rotation-aware.** `draw_*`, `insert_text`,
   `insert_image`, `add_*_annot` and `search_for` all work in the **unrotated
   mediabox space**; only `page.rect` and `get_pixmap()` reflect `/Rotate`.
   Therefore the writer converts base-page coordinates with
   `page.derotation_matrix` before drawing, and the search feature converts the
   other way with `page.rotation_matrix`.
2. **`pymupdf.Matrix(a)` rotates counter-clockwise on screen.** Orion uses the
   graphics-editor convention (clockwise-positive, same as `QGraphicsItem.setRotation`),
   so the writer passes `-angle`.
3. **Objects are stored in *base* page space, not in the rotated view space.**
   Rotating a page is therefore an O(1) metadata change and objects stay glued to
   the content they annotate. The page rotation is applied by the canvas
   (`PageItem` transform) and by the writer (`/Rotate`), never by rewriting objects.
4. A page's `/Rotate` from the source file and Orion's own rotation are kept
   separate and summed only at write time.

---

## 4. Directory structure

The specification suggested `orion/app/...`. A top-level package literally named
`app` is not safely importable/installable (name collisions on `pip install`), so
the package root is `orion/` itself and `app/` is dropped — every other name is kept.
This is the only structural deviation.

```
Orion/
├── orion/
│   ├── __init__.py            app name / version / metadata
│   ├── __main__.py            python -m orion
│   ├── main.py                QApplication bootstrap, crash guard, logging init
│   │
│   ├── ui/                    ── Qt layer (the only layer that imports Qt)
│   │   ├── main_window.py     MainWindow, wiring, document lifecycle
│   │   ├── actions.py         single QAction registry shared by menu + toolbar
│   │   ├── menu.py            menu bar construction
│   │   ├── toolbar.py         toolbar + tool selection
│   │   ├── canvas.py          PdfCanvas (QGraphicsView) + PdfScene
│   │   ├── page_item.py       PageItem: renders the original PDF raster
│   │   ├── object_items.py    Text/Image/Shape/Annotation QGraphicsItems + handles
│   │   ├── tools.py           tool state machine (select, text, image, shapes…)
│   │   ├── thumbnails.py      ThumbnailPanel (async, drag&drop reorder)
│   │   ├── properties_panel.py dynamic per-type property editor
│   │   ├── search_panel.py    text search UI
│   │   ├── render_bridge.py   raw RGB buffer -> QImage, Qt render worker
│   │   ├── icons.py           procedurally drawn theme-aware icons (no binary blobs)
│   │   ├── theme.py           light / dark palettes + stylesheet
│   │   └── dialogs/           merge, split, extract, import pages, go-to-page, about
│   │
│   ├── document/              ── model (Qt-free)
│   │   ├── document.py        Document, DocumentSource
│   │   ├── page.py            Page, PageSource
│   │   ├── objects.py         PageObject, TextObject, ImageObject, ShapeObject
│   │   ├── annotations.py     AnnotationObject + kinds
│   │   └── serialization.py   model <-> JSON (autosave, clipboard, tests)
│   │
│   ├── pdf/                   ── engine (Qt-free)
│   │   ├── errors.py          typed, user-presentable errors
│   │   ├── reader.py          open/validate/decrypt, build Document from a file
│   │   ├── renderer.py        page rasterisation + LRU cache + thread safety
│   │   ├── coordinates.py     base-space <-> PDF-content-space conversions
│   │   ├── writer.py          Document -> PDF (atomic write)
│   │   └── operations.py      merge / split / extract / import (file level)
│   │
│   ├── commands/              ── undo-redo (Qt-free)
│   │   ├── base.py            Command ABC, MacroCommand
│   │   ├── history.py         History (undo/redo stacks, clean marker)
│   │   ├── object_commands.py Add/Delete/Move/Resize/Rotate/Modify object
│   │   └── page_commands.py   Add/Delete/Duplicate/Move/Rotate/Import page
│   │
│   ├── services/
│   │   ├── file_service.py    open/save/save-as orchestration + safety
│   │   ├── clipboard.py       object clipboard (in-app + JSON on system clipboard)
│   │   ├── export_service.py  extract/split/merge orchestration
│   │   ├── recent_files.py    recent file list
│   │   ├── autosave.py        crash-recovery snapshots
│   │   └── settings.py        QSettings-free JSON settings store
│   │
│   └── utils/
│       ├── geometry.py        Point, Size, Rect, Transform (Qt-free)
│       ├── image_utils.py     decode/normalise/rotate images via Pillow
│       ├── logging.py         rotating file log + console
│       └── paths.py           cross-platform config/cache/recovery dirs
│
├── tests/                     pytest suite (model/engine tests need no display)
├── resources/                 icons/, styles/
├── docs/                      ARCHITECTURE.md, USER_GUIDE.md, DEVELOPMENT.md
├── pyproject.toml · requirements.txt · README.md · LICENSE
├── CONTRIBUTING.md · CHANGELOG.md · .gitignore
```

---

## 5. Main classes and responsibilities

### Document model

| Class | Responsibility |
|---|---|
| `Document` | Ordered list of `Page`s, source registry, modified flag, observers. Knows nothing about files beyond the paths it references. |
| `DocumentSource` | A source PDF referenced by pages (`key`, `path`, `bytes`). Allows pages imported from other PDFs to keep their provenance until save. |
| `Page` | `source` (or blank), `base_size`, Orion `rotation`, ordered `objects`. Objects are stored in base page space. |
| `PageObject` | Base: `id`, `rect`, `rotation`, `opacity`, `locked`, `z`. Provides `clone()`, `to_dict()`, `from_dict()`. |
| `TextObject` | text, font family/size/bold/italic/underline, colour, alignment, line spacing. Rendered as **real PDF text** (base-14 fonts) → stays selectable and searchable in the output. |
| `ImageObject` | Encoded source bytes (PNG/JPEG/WEBP), natural size, `keep_aspect`. Bytes live in the model so clipboard/autosave are self-contained. |
| `ShapeObject` | `RECT` / `ELLIPSE` / `LINE` / `ARROW`, stroke colour+width, fill, line endpoints as normalised fractions of the rect (so a line supports every direction while still using generic rect resize/rotate). |
| `AnnotationObject` | `HIGHLIGHT` / `UNDERLINE` / `STRIKEOUT` / `INK` / `COMMENT` / `STICKY_NOTE`. Written as **standard PDF annotations**, so other readers see them natively. |

### PDF engine

| Class | Responsibility |
|---|---|
| `PdfReader` | Opens a file, handles encryption/corruption, produces a `Document`. |
| `PageRenderer` | `render(source, index, rotation, scale) -> RenderedPage` (raw RGB). Size-bounded LRU cache, one lock per opened `pymupdf.Document` (PyMuPDF is not thread-safe per document). |
| `PdfWriter` | Assembles the output: copies source page runs, appends blank pages, applies rotation, stamps objects, adds annotations, writes atomically. |
| `operations` | `merge_files`, `split_by_ranges`, `split_every`, `extract_pages` — file-level, reusable by both the UI and (future) a CLI. |

### Commands

`Command` = `{ text, execute(), undo() }` plus optional `merge_with()` so a
drag produces **one** undo entry instead of hundreds. `History` keeps two stacks,
a size limit, and a *clean index* used to derive the document's `modified` state.
No whole-document snapshots are taken.

### Threading

Only rasterisation is off-thread. `RenderWorker` runs on a `QThreadPool`; results
are delivered back to the GUI thread via a Qt signal. Model mutation always happens
on the GUI thread, so no model locking is needed.

---

## 6. Dependencies and license compatibility

Versions and license strings below were read from the installed package metadata,
not from memory. **Verify them again before publishing** — upstream licenses change.

| Package | Version tested | License (from package metadata) |
|---|---|---|
| PySide6 / shiboken6 | 6.11.2 | `LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only` |
| PyMuPDF | 1.28.2 | `Dual Licensed - GNU AFFERO GPL 3.0 or Artifex Commercial License` |
| pypdf | 6.16.1 | `BSD-3-Clause` |
| Pillow | 12.3.0 | `MIT-CMU` |

**Consequence — this is a hard constraint, not a preference:**
PyMuPDF is **AGPL-3.0** unless a commercial Artifex license is purchased. AGPL-3.0
is the strongest copyleft here, and a work that links it must be distributed under
AGPL-3.0-compatible terms. Orion therefore ships under **AGPL-3.0-or-later**.
LGPL-3.0 (PySide6, used unmodified and dynamically linked), BSD-3-Clause and MIT-CMU
are all compatible with that outcome.

If a permissive license is ever required for Orion, PyMuPDF must be replaced
(rendering would move to e.g. `pypdfium2`, Apache-2.0/BSD-3). The engine boundary in
`orion/pdf/` exists partly to keep that swap feasible.

`pypdf` is used for the file-level page operations (merge/split/extract) and
`PyMuPDF` for rendering and content writing. Both are kept behind `orion/pdf/`.

**Optional, not a V1 requirement:** OCR is deliberately left out. A
`orion/pdf/ocr.py` module based on Tesseract can be added later behind a feature
check; nothing in V1 depends on it.

---

## 7. Milestones

| # | Milestone | Contents |
|---|---|---|
| 1 | Foundation | project skeleton, logging, main window, menus, toolbar, open PDF, render, navigation, thumbnails, zoom |
| 2 | Canvas | scene/graphics layer, coordinate system, selection, object layer, rubber band, panning |
| 3 | Text | text object, creation, inline editing, move/resize/rotate, properties, write to PDF |
| 4 | Images | import PNG/JPEG/WEBP, image object, aspect lock, opacity, write to PDF |
| 5 | Shapes & annotations | rect/ellipse/line/arrow, highlight/underline/strikeout, freehand ink, comment, sticky note |
| 6 | History | command pattern, undo/redo, clipboard, copy/paste/cut/duplicate |
| 7 | Page management | delete, duplicate, reorder, rotate, insert blank, import pages, extract |
| 8 | PDF operations | merge, split, save, save as, atomic write |
| 9 | Polish | error handling, performance, shortcuts, logging, tests, docs, dark theme, autosave |

---

## 8. Known technical risks and how they are handled

1. **PyMuPDF rotation semantics** (§3) — the most likely source of silent
   coordinate bugs. Mitigation: one conversion module + regression tests that
   *render* and assert pixel positions, so a PyMuPDF behaviour change fails loudly.
2. **Memory on zoom.** A 200-page document rendered at 400% would be gigabytes.
   Mitigation: only visible pages are rendered; the cache is bounded **by bytes**
   (default 256 MB) not by page count, and evicts LRU. Thumbnails use a separate
   tiny fixed-scale cache.
3. **PyMuPDF thread-safety.** Documented as not thread-safe for concurrent access
   to the same document. Mitigation: one `RLock` per open document, held for the
   duration of every engine call.
4. **Saving over the file being viewed.** The renderer holds the file open.
   Mitigation: write to a temp file in the same directory, validate by reopening,
   close all engine handles, `os.replace`, then reopen. `os.replace` is atomic on
   POSIX and on Windows for same-volume paths.
5. **Font fidelity.** Qt renders the on-screen text; PyMuPDF renders the PDF text.
   To keep them equivalent V1 restricts text objects to the **base-14** PDF fonts,
   which need no embedding and exist on every platform. Arbitrary TTF embedding is
   a documented follow-up, not a rewrite.
6. **Arbitrary-angle images.** PyMuPDF's `insert_image` only supports 90° steps.
   Mitigation: for non-multiples of 90 the raster is pre-rotated with Pillow and
   inserted into its expanded bounding box; exact multiples take the lossless path.
7. **Very large documents.** Page geometry is computed lazily and thumbnails are
   rendered on demand, so opening is O(1) in page count apart from reading the
   page sizes.

## 9. Deliberately out of scope for V1

AI/LLM features, Ask-PDF, PDF→Word/Excel/HTML conversion, advanced OCR, editing the
*original* text of the PDF, advanced digital signatures, cloud/accounts/database/sync,
backend services, batch automation, SaaS or licensing systems.

The layering above is what makes them addable later: a new feature is a new module
under `pdf/` or `services/` plus UI, never a rewrite.

## 10. Multi-document readiness

V1 exposes exactly one active document. `MainWindow` holds a `DocumentSession`
(document + history + file path + autosave). Making that a list behind a `QTabBar`
is a UI change only — no model or engine change — because nothing in the lower
layers is a global singleton.
