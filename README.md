<h1 align="center">Orion</h1>
<p align="center"><strong>PDF Editor for Desktop</strong></p>

<p align="center">
An offline PDF viewer, editor, annotator and page organiser.<br>
No account. No server. No cloud. No telemetry.
</p>

![Orion, light theme](docs/images/orion-light.png)

<details>
<summary>Dark theme</summary>

![Orion, dark theme](docs/images/orion-dark.png)
</details>

---

## What Orion is

Orion is a desktop application for working on PDF documents: read them, add
things to them, annotate them, and reorganise their pages — then save a normal
PDF that any other reader can open.

It is **not** a wrapper around a web service. Everything happens on your
machine, and your original file is never touched until you press Save.

## Features

**Viewing**
- Open, close and reopen recent documents
- Continuous multi-page view with page thumbnails
- First / previous / next / last page, and go-to-page
- Zoom in and out, an exact zoom percentage, fit page and fit width
- Full-document text search with highlighted results

**Editing**
- **Text** — click or drag to place a text box, then edit it in place. Font,
  size, bold, italic, underline, colour, alignment, line spacing, opacity,
  position, size and rotation. Written as real, selectable, searchable PDF text.
- **Images** — insert PNG, JPEG and WEBP, with aspect-ratio locking, opacity
  and free rotation. Drag an image file onto the page to place it.
- **Shapes** — rectangle, ellipse, line and arrow, with stroke colour and
  width, fill colour, opacity and rotation.
- **Annotations** — highlight, underline and strikeout that snap to the
  document's own text lines, freehand drawing, comments and sticky notes.
  All written as standard PDF annotations, so other readers understand them.

**Working with objects**
- Select one or many; drag-select; Ctrl/Cmd-click to extend a selection
- Move, resize from eight handles, and rotate freely (hold Shift to snap)
- Arrow keys nudge, Shift+arrows nudge further
- Cut, copy, paste and duplicate — including between two Orion windows
- Bring to front and send to back
- Unlimited, per-action undo and redo

**Pages**
- Insert a blank page, duplicate, delete
- Reorder by dragging thumbnails
- Rotate 90°, 180° or 270°
- Import pages from another PDF
- Extract pages into a new PDF
- Split a document every N pages or by explicit page ranges
- Merge several PDFs, in an order you choose

**Files**
- Save and Save As, written atomically so an interrupted save cannot damage
  your document
- Crash recovery: unsaved work is snapshotted separately from your PDF
- Light and dark themes

## Download

Standalone builds for Windows, macOS and Linux are attached to each
[release](https://github.com/MarcoLombardoDev/Orion/releases) — unpack and run,
no installation and no Python needed. They are unsigned, so Windows SmartScreen
and macOS Gatekeeper will warn on first launch.

## Installation from source

Orion needs **Python 3.10 or newer**.

```bash
git clone https://github.com/MarcoLombardoDev/Orion.git
cd Orion
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e .
orion
```

Or without installing:

```bash
pip install -r requirements.txt
python -m orion
```

Open a document straight away with `orion path/to/file.pdf`.

### Linux system packages

PySide6 needs a few shared libraries that some minimal images omit:

```bash
sudo apt install libegl1 libgl1 libxkbcommon0 libdbus-1-3 libfontconfig1
```

## Development

```bash
pip install -e ".[dev]"
pytest                       # the whole suite, GUI tests included
ruff check orion tests       # lint
```

The GUI tests drive the real widgets, so they need a display. On a headless
machine set `QT_QPA_PLATFORM=offscreen`:

```bash
QT_QPA_PLATFORM=offscreen pytest
```

`docs/DEVELOPMENT.md` covers the layout, the conventions and how to add a new
object type or tool. `CONTRIBUTING.md` covers the contribution process.

## Usage

Open a PDF, pick a tool from the palette on the left, and work on the page.
The panel on the right shows the properties of whatever is selected, and the
thumbnails on the left reorder pages by dragging.

A full walkthrough — including every keyboard shortcut — is in
[`docs/USER_GUIDE.md`](docs/USER_GUIDE.md).

The shortcuts you will use most:

| | |
|---|---|
| `Ctrl/Cmd + O` | Open |
| `Ctrl/Cmd + S` | Save |
| `Ctrl/Cmd + Shift + S` | Save As |
| `Ctrl/Cmd + Z` / `Ctrl/Cmd + Y` | Undo / Redo |
| `Ctrl/Cmd + C` / `V` / `X` / `D` | Copy / Paste / Cut / Duplicate |
| `Ctrl/Cmd + F` | Find |
| `Ctrl/Cmd + 1` / `2` / `0` | Fit page / Fit width / 100% |
| `V` `H` `T` `I` `R` `O` `L` `A` `P` `N` | Pick a tool |
| `Delete` | Delete the selection |
| `Esc` | Cancel the current operation |

## Architecture

```
UI  (orion/ui)            Qt widgets, the canvas, the panels
        │
Commands (orion/commands) undo/redo — deltas, not snapshots
        │
Document (orion/document) Document · Page · Text/Image/Shape/Annotation
        │
PDF engine (orion/pdf)    reader · renderer · writer · operations
        │
PyMuPDF · pypdf · Pillow
```

The rule the whole design follows: **the UI never manipulates the PDF file.**
It edits an in-memory document model; the file is read for rendering and
written only when you save. That is what makes undo cheap, autosave a
serialisation, and your original file safe.

`orion/document`, `orion/commands` and `orion/utils` do not import Qt at all,
so the model is testable without a display. The full reasoning, the coordinate
system, and the known technical risks are in
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Roadmap

Orion 1.0 deliberately stops at a solid, offline editor. Planned next:

- Several documents open at once, in tabs
- Embedding arbitrary TrueType fonts in text objects (1.0 uses the base-14 PDF fonts)
- Optional OCR through Tesseract, as a separate module
- Standalone builds for Windows, macOS and Linux (`orion.spec` is already there)
- Form field editing
- Editing the *original* text of a PDF, not only the text Orion adds

Explicitly out of scope: AI features, cloud sync, accounts, telemetry.

## License

Orion is released under the **GNU Affero General Public License, version 3 or
later** — see [`LICENSE`](LICENSE).

This is not a free choice: Orion renders and writes PDFs with **PyMuPDF**,
which its own package metadata describes as *"Dual Licensed — GNU AFFERO GPL
3.0 or Artifex Commercial License"*. Linking it obliges any distributed work to
be AGPL-compatible. Orion's other dependencies are compatible with that:

| Dependency | License, as declared by the package |
|---|---|
| PySide6 / shiboken6 | `LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only` |
| PyMuPDF | Dual Licensed — GNU AFFERO GPL 3.0 or Artifex Commercial License |
| pypdf | `BSD-3-Clause` |
| Pillow | `MIT-CMU` |

These strings were read from the installed packages' metadata at the versions
listed in `requirements.txt`. Verify them yourself before redistributing —
upstream licenses do change, and this table is a convenience, not legal advice.
