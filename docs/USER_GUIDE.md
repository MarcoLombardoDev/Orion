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

Neither side panel has a heading over it; each says what it is by what it
holds. Both can be hidden — **F9** for the pages, **F10** for the properties —
and dragged to the other side of the window.

There are two strips of icons on the left, separated by a rule. The first is
the **tools**: what the next click on a page does. The second belongs to the
**pages** beside it, and holds everything under the Pages menu — insert,
duplicate, delete, rotate, reorder, import, extract and split — so the verbs
are next to the thing they act on rather than up in the menu bar.

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
| Redact | | Drag over anything that must leave the file |
| Freehand | `P` | Draw with the mouse held down |
| Sticky Note | `N` | Click to place a note |

Most tools hand control back to **Select** as soon as the object exists, so you
can position it straight away. Freehand and Pan stay active until you change
them.

Hold **Shift** while dragging a rectangle or ellipse to constrain it to a
square or circle.

### Text

Double-click a text object — or select it and press `F2` or `Enter` — to edit
it in place. While you are typing, **Enter** starts a new line;
**Ctrl/Cmd+Enter** commits; **Esc** cancels; clicking elsewhere commits.

The text stays the size it will be in the saved file the whole time. What you
type is what the writer lays out, at the size the canvas is already showing.

A small red corner mark means the text does not fit its box: it would be
clipped in the saved file too. Make the box bigger or the text smaller.

The font list starts with **Helvetica, Times and Courier** — the fonts built
into every PDF reader. They add nothing to the file, there is no licence to
think about, and they are what a text box uses unless you choose otherwise.

Below them is **every font installed on this computer** that Orion can embed.
Pick one and a subset of it is written into the file, so the document looks the
same on a machine that does not have it. Two things follow from that, and the
panel says both when they apply: the file gets bigger, and distributing it
means the font's licence is yours to check. Fonts Orion cannot embed —
PostScript-outline OpenType, colour emoji fonts — are left out of the list
rather than offered and then failing when you save.

Either way the result is *real* text: selectable, searchable, and wrapped
where the canvas wrapped it.

If you open a document that names a font this machine does not have, the name
is kept and the panel says Helvetica is standing in for it. A family that has
no italic, or no bold, is shown upright or regular on the canvas too, so the
screen does not promise something the saved file will not have.

### Highlight, underline and strikeout

Drag across the words you want. Orion finds the document's actual text lines
inside your drag and snaps the annotation to them, so the marking follows the
text rather than your hand. If there is no selectable text there — a scanned
page, for example — the status bar says so and nothing is added.

### Sticky notes

Click to place one; a dialog asks for the text. Double-click it later to edit.
It becomes a standard PDF text annotation, so other readers show it.

Notes a *file* already carries are read back and editable in the same way,
including the ones other programs label comments rather than notes.

### Annotations already in the file

Highlights, underlines, strikeouts, freehand ink and notes are read back when
you open a document, whether Orion wrote them or another program did. Click one
to select it, change its colour or its comment, or press Delete to remove it —
and it is gone from the file you save, not just hidden.

Annotations Orion has no tool for — links, form fields, stamps — are left
exactly as they are. They are not editable here, and saving does not disturb
them.

### Redacting

The Redact tool takes something out of the file. Drag a box over it and Orion
draws an opaque rectangle there — but the rectangle is the smaller half of what
happens. When you save, everything the box covers is deleted from the page:
the text objects, the images, the drawings. What is left is a black box with
nothing underneath it.

That is the difference between this and drawing a filled rectangle over a name.
A rectangle hides the name on screen and leaves it in the file, where copying
the page, or opening it in any other editor, brings it straight back. This does
not.

Two things follow:

* A redaction is an ordinary object until you save. Move it, resize it, undo
  it — the removal is decided at save time by where the box has ended up, not
  by where you first drew it.
* Anything the box **touches** goes, not only what it fully contains. Half a
  word is not a redaction, so Orion errs towards taking the whole object. If
  something disappeared that you wanted, undo, make the box smaller and try
  again.

The box is black by default. The properties panel changes its colour — white
is the other useful answer, when the point is to remove something without
announcing that anything was removed.

Redaction removes what is on the page. It does not touch the document's
metadata; **File ▸ Document Properties** is where an author's name lives.

## Working with objects

Click to select. **Ctrl/Cmd+click** adds to the selection. Dragging on empty
space with the Select tool draws a rubber band.

The properties panel has a **Delete** button at the bottom for whatever is
selected, one object or several.

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

## Stamping a whole run of pages

Two jobs that would otherwise mean placing the same text box eighty times.

### Watermark

**Tools ▸ Watermark** puts a word across a range of pages: the text, its size,
colour, opacity and angle, and which pages get it. It lands in the middle of
each page, turned as you asked.

The size you choose is a starting point rather than a promise. A word too wide
for the page is shrunk until it fits, measured on the diagonal it will actually
sit on, so a long word turned at 45° keeps more of its size than the same word
lying flat.

### Page numbers

**Tools ▸ Page Numbers** numbers a range. Choose one of six positions, and a
template: `{n}` is the number and `{total}` the count, so `Page {n} of {total}`
gives what it says. Numbering starts at 1 by default; **Start at** changes that
when the first numbered page is not the first page of the file.

Both write **real text**, not a picture of it — selectable, searchable, and
ordinary objects afterwards. A page number that lands on top of an existing
footer can be dragged out of the way, restyled, or deleted one page at a time,
and the whole run is a single undo.

## What the document says about itself

**File ▸ Document Properties** shows the title, author, subject and keywords —
the fields a reader's own Properties window shows — and lets you change them.
Emptying a field removes it rather than writing a blank one.

Everything else the file carries is listed below, read-only, so it is at least
visible. Orion has always kept these across a save; this is where you can see
what it is keeping. A file that came from somewhere else may well have someone
else's name on it.

## Exporting pages as images

**File ▸ Export as Images** writes the pages you choose as PNG or JPEG files,
at a resolution you pick between 72 and 600 DPI.

The images are rendered from the document as it would be saved, so what you
have added is in them, whether or not you have saved yet.

## Finding a command

`Ctrl/Cmd+Shift+P` opens a box; type a few letters and the matching commands
are listed, best first. **Enter** runs the top one.

Matching is by letters in order rather than whole words, so `wm` finds
Watermark and `epg` finds Export Pages. Commands that cannot run right now —
Save with nothing open, Delete with nothing selected — are left out rather than
shown greyed, so what the list offers is what will work.

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

## Language

**Help ▸ Language** offers **English** and **Italiano**, and switches with the
window open — no restart.

On a first run Orion asks the desktop: an Italian system gets Italian, and
every other language gets English. Once you choose from the menu, that choice
is what it remembers.

Both languages are listed under their own name rather than translated, because
somebody who has landed in the wrong one is looking for the word they
recognise.

## Themes

**Help ▸ Theme** offers Light, Dark, or Match System, which follows your
desktop setting.

## When something goes wrong

Orion shows a plain-language message rather than a traceback. The details go to
a log file — **Help ▸ Open Log Folder** shows you where. Include the end of
that file in a bug report.

## All keyboard shortcuts

**Help ▸ Keyboard Shortcuts** lists the current bindings, generated from the
application itself, so it can never be out of date.
