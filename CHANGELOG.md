# Changelog

All notable changes to Orion are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

Nothing yet.

## [1.0.0] — 2026-08-22

The first release: a complete, offline PDF viewer, editor, annotator and page
organiser.

### Added

**Viewing**
- Open and close PDF documents, with a recent-files list
- Continuous multi-page view with asynchronous, resolution-aware rendering
- Page thumbnails with their own bounded cache
- First / previous / next / last page and go-to-page
- Zoom in and out, exact zoom percentage, fit page, fit width
- Full-document text search with on-page highlighting and match navigation

**Editing**
- Text objects with in-place editing; font family, size, bold, italic,
  underline, colour, alignment, line spacing, opacity, geometry and rotation.
  Written as real, searchable PDF text using the base-14 fonts
- Image objects from PNG, JPEG and WEBP, with aspect-ratio locking, opacity and
  free rotation
- Rectangle, ellipse, line and arrow shapes with stroke, fill, width, opacity
  and rotation
- Highlight, underline and strikeout annotations that snap to the document's own
  text lines; freehand ink; comments and sticky notes — all written as standard
  PDF annotations
- Single and multiple selection, drag-selection, eight resize handles, a
  rotation handle, arrow-key nudging, and z-order control
- Cut, copy, paste and duplicate, working between Orion windows
- Undo and redo for every action, built on a command pattern that stores deltas

**Pages**
- Insert a blank page, duplicate, delete, reorder by dragging thumbnails
- Rotate by 90°, 180° or 270°
- Import pages from another PDF, referenced without copying until save
- Extract pages to a new PDF
- Split every N pages or by explicit page ranges
- Merge several documents in a chosen order, optionally including the open one

**Files and safety**
- Save and Save As with atomic writes: content is written to a temporary file,
  validated by reopening it, and only then moved into place
- The original PDF is never modified until an explicit save
- Saving over the file being viewed keeps a private copy of the pristine
  original, so objects are never stamped twice and undo survives the save
- Crash recovery from snapshots of the document model, clearly distinguishable
  from the PDF itself
- Typed, readable errors for damaged, protected, missing and unwritable files;
  tracebacks go to a rotating log file, never to the user

**Interface**
- Menu bar, toolbar, vertical tool palette, thumbnails, canvas, properties
  panel and status bar
- Light and dark themes, following the desktop setting by default
- Icons drawn in code, so the repository carries no binary assets
- Keyboard shortcuts for every common action
- Drag and drop of PDF documents and image files onto the window

### Notes

- Orion is licensed **AGPL-3.0-or-later**, because PyMuPDF is AGPL unless a
  commercial licence is bought. See the README for the dependency licence table.
- Text objects use the base-14 PDF fonts. Embedding arbitrary TrueType fonts is
  planned but not in this release.
- OCR, cloud features, accounts and AI features are deliberately absent.
