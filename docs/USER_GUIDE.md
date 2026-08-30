# Orion — User Guide

## The window

```
┌──────────────────────────────────────────────────────────────┐
│ File  Edit  View  Pages  Tools  Help                         │
├──────────────────────────────────────────────────────────────┤
│ Toolbar:  open · save · undo · pages · zoom · find           │
├───┬───────────┬──────────────────────────────┬───────────────┤
│ T │           │                              │               │
│ o │Thumbnails │          PDF Canvas          │  Properties   │
│ o │           │                              │               │
│ l │  Page 1   │                              │               │
│ s │  Page 2   │                              │               │
│   │  Page 3   │                              │               │
├───┴───────────┴──────────────────────────────┴───────────────┤
│ Page 3 / 20              Zoom 100%              Fit Width    │
└──────────────────────────────────────────────────────────────┘
```

Both side panels can be hidden — **F9** for the thumbnails, **F10** for the
properties — and dragged to the other side of the window.

## Opening documents

**File ▸ Open** (`Ctrl/Cmd+O`), or drop a PDF onto the window. **File ▸ Open
Recent** lists what you worked on last.

A password-protected document asks for its password. A damaged one says so
plainly rather than failing silently.

## Moving around

| Action | How |
|---|---|
| Scroll | Mouse wheel, or drag with the Pan tool, or hold **Space** and drag |
| Next / previous page | `PgDown` / `PgUp`, or the toolbar arrows |
| First / last page | `Ctrl/Cmd+Home` / `Ctrl/Cmd+End` |
| Jump to a page | `Ctrl/Cmd+G`, or type in the toolbar's page box |
| Zoom | `Ctrl/Cmd + +` / `-`, `Ctrl/Cmd` + wheel, or type a percentage |
| Fit page / fit width | `Ctrl/Cmd+1` / `Ctrl/Cmd+2` |
| Actual size | `Ctrl/Cmd+0` |

## Finding text

`Ctrl/Cmd+F` opens the find bar. Matches are highlighted across the whole
document; the current one is a stronger colour. **Enter** and **Shift+Enter**
(or `F3` / `Shift+F3`) step through them. **Esc** closes the bar.

## The tools

The palette down the left side selects what a click on the page does.

| Tool | Key | What it does |
|---|---|---|
| Select | `V` | Select, move, resize and rotate objects |
| Pan | `H` | Drag to scroll |
| Text | `T` | Click for a default box, or drag one out |
| Image | `I` | Click, then choose a PNG, JPEG or WEBP file |
| Rectangle | `R` | Drag out a rectangle |
| Ellipse | `O` | Drag out an ellipse |
| Line | `L` | Drag from one end to the other |
| Arrow | `A` | Drag from tail to head |
| Highlight | | Drag across text to highlight it |
| Underline | | Drag across text to underline it |
| Strikeout | | Drag across text to strike it out |
| Freehand | `P` | Draw with the mouse held down |
| Comment | | Click to attach a comment |
| Sticky Note | `N` | Click to place a note |

Most tools hand control back to **Select** as soon as the object exists, so you
can position it straight away. Freehand and Pan stay active until you change
them.

Hold **Shift** while dragging a rectangle or ellipse to constrain it to a
square or circle.

### Text

Double-click a text object — or select it and press `F2` or `Enter` — to edit
it in place. **Ctrl/Cmd+Enter** commits; **Esc** cancels; clicking elsewhere
commits.

A small red corner mark means the text does not fit its box: it would be
clipped in the saved file too. Make the box bigger or the text smaller.

Orion 1.0 uses the base-14 PDF fonts (Helvetica, Times, Courier). They need no
embedding, exist in every reader, and mean the text you see is the text that is
written — as *real* text, so it stays selectable and searchable in the result.

### Highlight, underline and strikeout

Drag across the words you want. Orion finds the document's actual text lines
inside your drag and snaps the annotation to them, so the marking follows the
text rather than your hand. If there is no selectable text there — a scanned
page, for example — the status bar says so and nothing is added.

### Comments and sticky notes

Click to place one; a dialog asks for the text. Double-click it later to edit.
Both become standard PDF text annotations, so other readers show them.

### Annotations already in the file

Highlights, underlines, strikeouts, freehand ink and notes are read back when
you open a document, whether Orion wrote them or another program did. Click one
to select it, change its colour or its comment, or press Delete to remove it —
and it is gone from the file you save, not just hidden.

Annotations Orion has no tool for — links, form fields, stamps — are left
exactly as they are. They are not editable here, and saving does not disturb
them.

## Working with objects

Click to select. **Ctrl/Cmd+click** adds to the selection. Dragging on empty
space with the Select tool draws a rubber band.

**Right-click** anything on the page for a menu of what can be done to it:
edit its text or its comment, cut, copy, duplicate, change its stacking, or
delete it. Right-clicking an object that is not selected selects it first;
right-clicking inside a selection of several leaves that selection alone.
Right-click empty space instead and the menu is about the page — paste, select
everything on it, rotate it, duplicate it, delete it.

A selected object shows a bounding box, eight resize handles and a round
rotation handle above it.

| Action | How |
|---|---|
| Move | Drag it, or use the arrow keys (**Shift** for bigger steps) |
| Resize | Drag a handle; **Shift** keeps the proportions |
| Rotate | Drag the round handle; **Shift** snaps to 15° |
| Delete | `Delete` |
| Copy / Cut / Paste | `Ctrl/Cmd+C` / `X` / `V` |
| Duplicate | `Ctrl/Cmd+D` |
| Select everything on the page | `Ctrl/Cmd+A` |
| Deselect | `Esc` |
| Bring to front / send to back | `Ctrl/Cmd+Shift+]` / `Ctrl/Cmd+Shift+[` |

The properties panel on the right changes to match what is selected, and every
field there is undoable — including dragging a value, which counts as one step
rather than fifty.

Copy and paste work between two Orion windows: objects travel as objects, not
as a picture of them.

## Pages

Right-click a thumbnail for the page menu, or use the **Pages** menu. Select
several thumbnails to act on them all at once.

| Action | How |
|---|---|
| Reorder | Drag thumbnails |
| Move current page | `Ctrl/Cmd+Shift+Up` / `Down` |
| Rotate | `Ctrl/Cmd+[` / `Ctrl/Cmd+]`, or Pages ▸ Rotate 180° |
| Insert a blank page | Pages ▸ Insert Blank Page — choose the size and where |
| Duplicate | Pages ▸ Duplicate Page (objects are copied too) |
| Delete | Pages ▸ Delete Page (it asks first, and it is undoable) |

Rotating a page rotates what you added along with the page content, so an
annotation never drifts away from the words it marks.

### Import pages from another PDF

**Pages ▸ Import Pages** picks a document, asks which pages, and asks where to
put them. The pages are *referenced*, not copied, until you save — so importing
five hundred pages is instant.

### Extract pages

**Pages ▸ Extract Pages** writes the pages you choose to a new file. Everything
you have added is included, even if you have not saved yet.

### Split

**Pages ▸ Split PDF** splits every N pages, or by ranges you type
(`1-5, 6-10, 11-20`). The dialog says how many files it will create before you
commit.

### Merge

**File ▸ Merge PDF** collects documents, lets you drag them into order, and
writes the result. "Add Current Document" includes what you have open, unsaved
changes and all.

## Saving

**Ctrl/Cmd+S** saves; **Ctrl/Cmd+Shift+S** saves under a new name.

Orion does not touch your original file until you ask it to. When you do, it
writes a temporary file next to the target, reopens it to check it is a valid
PDF with the right number of pages, and only then puts it in place. If anything
fails, your original is exactly as it was and the temporary file is removed.

A dot before the window title, and "Modified" in the status bar, mean there are
unsaved changes. Closing then offers **Save**, **Don't Save** or **Cancel**.

Saving does not clear your undo history — you can save, keep working, and still
undo past the save.

## If Orion closes unexpectedly

While you have unsaved changes, Orion periodically writes a recovery snapshot —
a separate file, never your PDF. Next time it starts, it offers to restore.
Recovered documents open as unsaved, so use **Save As** to write them out.

## Themes

**View ▸ Theme** offers Light, Dark, or Match System, which follows your
desktop setting.

## When something goes wrong

Orion shows a plain-language message rather than a traceback. The details go to
a log file — **Help ▸ Open Log Folder** shows you where. Include the end of
that file in a bug report.

## All keyboard shortcuts

**Help ▸ Keyboard Shortcuts** lists the current bindings, generated from the
application itself, so it can never be out of date.
