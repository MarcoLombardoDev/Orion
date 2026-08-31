# Changelog

All notable changes to Orion are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] — 2026-08-30

Everything below shipped after the first v1.0.0 build and under the same
version number: the tag is re-cut as the work continues rather than advanced,
so what a download contains is told apart by the date above rather than by the
number.

### Added
- **Editing the text that is already in the PDF.** Until now Orion could put a
  box of new text on top of a page and nothing else: correcting a figure in a
  contract meant covering it with a white rectangle and retyping beside it.
  The **Edit Page Text** tool turns a line of the document's own text into an
  editable text box — same position, same size, same colour, the baseline
  landing where the original's did — and the original glyphs are removed from
  the saved file rather than hidden underneath. It works on documents whose
  font is only inside the file, which is most of them. Three consequences the
  user guide and the status bar both spell out: the line is redrawn in one of
  Orion's fonts, so it changes appearance when the document's font is not
  installed here; a line of mixed styles becomes one style; and the replaced
  line is drawn last, so a screen reader meets it at the end of the page.
- **Every font on the machine, not just three.** Orion wrote with the base-14
  PDF fonts and offered nothing else, so a text box could be Helvetica, Times
  or Courier and that was the whole list. Any installed family Orion can embed
  is now offered too, subset into the file so the document travels. The three
  built-ins still lead the list and are still the default — they add nothing
  to the file and carry no licence to check — and the panel says when a font
  is being embedded, when the document names a family this machine does not
  have, and when a family has no italic or bold face of its own. Fonts that
  cannot be embedded, PostScript-outline OpenType and colour emoji among them,
  are left out of the list rather than offered and then failing at save time.
  Finding the installed families costs about fifteen milliseconds, because it
  reads the name table out of each file and nothing else.
- **A Delete button in the properties panel.** Deleting was on the Del key and
  in the right-click menu and nowhere in the panel a user is looking while
  they work on an object, which is the moment they decide it is wrong. It
  takes a selection of several as readily as one.
- **A right-click menu on the page.** The canvas answered nothing at all to
  the right button, anywhere, which is the gesture people reach for to
  recolour or remove a mark they have just made — the other half of the
  report that a highlight could not be modified. Right-clicking an object
  offers what can be done to it, right-clicking the page offers what can be
  done to the page, and the entries are the window's own actions rather than
  copies of them, so each carries its shortcut and its enabled state and
  cannot drift away from the menu bar. Includes **Edit Comment…**, which is
  new: a comment could be written when a note was placed, and after that only
  reached by double-clicking the note itself.
- **The annotations already in a PDF are read back, and are editable.** Orion
  wrote highlights, underlines, strikeouts, ink and notes as standard PDF
  annotations from the start, and never read one. So marking up a document
  worked until it was closed: reopen it and the highlight was still drawn —
  pdfium draws annotations — with nothing behind it to select, recolour or
  delete. Deleting one somebody else had put in a contract was impossible in a
  PDF *editor*, and a highlight of your own became permanent the moment you
  saved. They now arrive as ordinary objects, from any program's file, and the
  writer drops the originals it took ownership of so an edit replaces rather
  than duplicates. Ownership is recorded as the `/Annots` indices the model
  took, not guessed from the subtype at save time: an annotation Orion cannot
  model — a link, a form field, a markup kind it has no tool for, one too
  damaged to read — is neither imported nor touched. Pages imported from
  another PDF come in the same way, so inserting somebody's page no longer
  flattens their markup.
- **A palette, where Orion had none.** `resources/styles/` held a README and
  nothing else, so the interface came up in whatever the platform's default
  was. It now carries the same colours Iris and Proteus get from
  ttkbootstrap's "flatly": a white ground, near-black text, a dark navy on
  anything primary, flat controls with no bevel. Those two are Tk and this is
  Qt, so the library cannot be shared — only the numbers can, and they are the
  numbers that matter. Deliberately restrained: the ground, the text, the
  buttons and the rules, and the page view untouched, because a PDF has to be
  shown as it is rather than as the theme would prefer it.
- **The copyright and licence notice, along the bottom of the window.** Iris,
  Proteus and Argus have shown one since their first release; Orion shipped
  v1.0.0 without it. AGPL-3.0 section 5 asks the work to carry Appropriate
  Legal Notices, so this was a compliance gap rather than a cosmetic one. The
  commercial licensing address is a link rather than plain text: the person
  running the application is exactly the person who might need to buy a
  licence, and "available on request" tells them nothing about where to ask.
- **One icon across the four products: the initial, in black, on white, in a
  serif face.** Drawn by `tools/make_icon.py`, which the four share and which
  differs only in the letter, so a taskbar with all of them open reads as one
  family instead of four unrelated programs. The face is Liberation Serif,
  metric-compatible with Times New Roman and redistributable, where Times New
  Roman itself is neither free nor present on the machines that build these.

  Every size is drawn for itself rather than scaled down from a single master:
  a frame that reads as a hairline at 256 pixels is a smear at 16, and the
  letter that has room to breathe at 256 has to fill the square at 16 to still
  be a letter. Below 32 pixels there is no frame at all. Both files are
  committed rather than generated during the build, so no release depends on
  which fonts a runner happens to have.
- **A start script and the program's own checksum, inside the archive.** Every
  archive now unpacks to a folder holding the program, `start.cmd`,
  `start.command` or `start.sh` beside it, and the digest that script checks.
  Starting through it recomputes the program's SHA-256 and refuses to launch on
  a mismatch, which turns a truncated download or a half-finished unpack into
  one sentence at the point of launch instead of a program that misbehaves
  later for no visible reason. `ORION_SKIP_VERIFY=1` skips the check for
  anyone who has changed the executable deliberately.

  It is deliberately modest about what it proves. That digest travels in the
  same archive as the program, so it catches damage and not tampering — whoever
  could replace one could replace the other. The `.sha256` published as a
  separate release asset is the one that answers that question, because it
  reaches you by a different route, and the launcher, the README and the
  release notes all say so rather than implying more.

  Added by the workflow rather than by `orion.spec`, because PyInstaller 6 puts
  everything a spec declares as `datas` under `_internal/` — the one place a
  launcher must not be. The release run starts the bundle through the script,
  and then corrupts the recorded digest and checks that it refuses: a launcher
  that verifies nothing would pass the first half on its own.
- **A SHA-256 checksum beside every archive.** These builds are unsigned, so
  Windows tells whoever downloads one that the publisher is unknown and offers
  only "Don't run". Nothing in this repository can remove that — a
  code-signing certificate is the only thing that does — but the warning asks
  a question a checksum can answer: is this the file the build produced. Each
  archive now ships with a `.sha256` in the format `sha256sum -c` reads, and
  the release notes say how to use it and how to get past the warning rather
  than only that the build is unsigned.
- **Real builds for Windows, macOS and Linux.** `.github/workflows/release.yml`
  builds each platform on its own GitHub runner — PyInstaller does not
  cross-compile, so this is the only way each binary can be genuine — and
  attaches one archive per platform to the release.
- Every bundle is **smoke-tested on its own platform** before it is offered for
  download: it has to answer `--version` cleanly, or the asset is not published.
- `.github/release-body.md`, so the description a downloader reads lives in the
  repository and can be edited without touching a workflow.
- `tests/test_release_workflow.py`, which parses the workflow and the release
  body so a download table can never again promise a platform that is not built.
- **`THIRD-PARTY-LICENSES.md`**, an inventory of every third-party binary the
  release archives contain — 519 of them across the three platforms, from
  roughly a hundred projects — each attributed to the wheel, interpreter or
  system package that put it there, and each citing where its licence
  determination came from. Generated by `tools/licence_inventory.py` from an
  extracted release archive rather than maintained by hand, because
  PyInstaller collects whatever the build machine's linker resolved and a
  hand-written list is stale one runner-image bump later.
- **Licence texts inside the archives.** The v1.0.0 archives contained no
  `LICENSE`, `COPYING` or `NOTICE` file at all, which LGPL-3.0 §4, the AGPL and
  every BSD and MIT notice in the bundle require. `tools/collect_licences.py`
  now assembles them and the bundle ships them as `licenses/` — 87 files on a
  Linux build. The PySide6 wheels declare LGPL-3.0 and ship no licence file, so
  that text is supplied from `licenses/` in this repository, together with the
  GPL-3.0 it builds on.
- `orion --self-check`, which starts Qt, reports the platform plugin in use,
  and writes a small document and reads it back — all without opening a window.
  The release workflow runs it on each platform's own bundle, so a build that
  cannot save is caught before it is published rather than by the first user
  who presses Save. Starting Qt alone would not catch it: a frozen application
  breaks by missing a file, and that surfaces at save time, not at startup.
- **`COMMERCIAL-LICENSE.md` and `CLA.md`.** Orion is now dual-licensed on the
  same terms as its three sibling products: AGPL-3.0 for everyone, and a
  commercial licence for closed-source and redistribution use. The document
  follows the 14-section layout shared by Orion, Iris, Proteus and Argus, with
  the same six tiers — Commercial Small / Medium / Large / Enterprise and
  Redistribution Standard / Enterprise — plus a perpetual option at three times
  the annual rate of the same tier.

### Changed
- **One interface font across the four, named rather than left to a
  default.** Segoe UI where the machine has it, with the equivalent on macOS
  and Linux behind it, resolved once from a list the four products share.
  Nothing depends any more on which family the toolkit happened to pick.
- **The window opens maximised.** All four now fill the screen at start-up
  rather than opening at a fixed size in the corner. Deliberately maximised
  and not true full screen: that hides the title bar and the way out of it,
  which is right for a slideshow and wrong for a tool somebody works in
  alongside other windows. The size each window returns to when un-maximised
  is the one it used to open at.
- **The release now fails if the tag and the program disagree about the
  version.** Nothing checked it, which is exactly how a `v1.0.0` tag could
  produce `Orion-1.0.0-windows-x64.zip` containing a program that answers
  `--version` with something else — a download whose name and contents
  contradict each other. The smoke test compares the two on every platform and
  stops the release rather than publishing that.
- **The Windows start script waits for the window instead of vanishing.** It
  handed off and closed at once, which left whoever double-clicked it staring
  at an empty desktop for however long Windows took to scan the folder — most
  of a minute, the first time. It now says what it is waiting for and closes
  itself the moment the program is actually on screen, using
  `WaitForInputIdle`, which is Windows' own answer to "has it finished
  starting". Without PowerShell to ask, it hands off as before rather than
  guessing.
- **The archives' checksums moved from the download list into the release
  notes.** Three `.sha256` files beside three archives doubled the length of
  the list for no one's benefit. The digests are now printed under
  **Checksums** in the notes, which keeps the property that matters — a
  checksum is only evidence if it reaches you by a route the archive did not —
  and takes the clutter away. `tests/test_release_workflow.py` pins that they
  are written after all three builds, and that a re-run rewrites the block
  rather than stacking a second one under it.
- **Every Python source file carries the same seven-line licence header**, in
  the same place: the product name, the copyright line, an
  `SPDX-License-Identifier: AGPL-3.0-or-later` a tool can read, a pointer to
  LICENSE for the warranty disclaimer, and a pointer to COMMERCIAL-LICENSE.md
  for the commercial option.
  None of Orion's 74 files had one.
  The `# -*- coding: utf-8 -*-` declarations went with it: they have meant
  nothing since Python 3, and Orion's ruff configuration flags them as UP009.
  Nothing but comments changed — the parsed syntax tree of all 152 files is
  identical before and after, which is how that was checked rather than
  assumed.
- `README.md` follows the section skeleton shared by the four products, and
  gained the Screenshots, Testing, Contributing and Disclaimer sections the
  others already had.
- Release assets are now archives named `Orion-<version>-<platform>.zip` /
  `.tar.gz`, and the Windows archive keeps its top-level folder, as the macOS
  and Linux ones already did.
- **The release smoke test now starts Qt.** It ran `--version`, which argparse
  prints and exits on before PySide6 is ever imported — so a bundle with a
  missing or unloadable Qt platform plugin passed it and would then have failed
  on the user's desktop. It now runs `--self-check`, which constructs a
  QApplication, and on Linux does so under a virtual X server against the real
  `xcb` backend rather than `offscreen`, which loads none of the X libraries.
  A bundle that comes up on anything other than its platform's own plugin fails
  the release.
- **`COMMERCIAL-LICENSE.md` §11 describes what a redistributor actually
  receives.** It listed six components — Orion's source dependencies — for a
  product whose downloadable builds contain 519 native binaries, and marked
  most of them ✅ in a column headed "Commercial redistribution", in the one
  section whose purpose is to say that no such permission is granted. Each row
  now states what the component asks of the reader, the obligations that reach
  the archives and appeared nowhere before are named, and MuPDF's position has
  its own subsection: Orion cannot sublicense Artifex's code, so a
  Redistribution licence still hands the buyer AGPL MuPDF and its obligations.
- **The PDF engine was replaced.** Orion rendered and wrote PDFs with MuPDF,
  through PyMuPDF, which Artifex licenses under the AGPL-3.0 or a commercial
  licence of its own. Orion held no right to sublicense it, so a customer who
  bought a commercial or redistribution licence still received AGPL MuPDF and
  still carried its obligations — the single reason those tiers did not work.
  The job is now split between **pypdfium2** (Google's PDFium) for rendering,
  text extraction and search, **pypdf** for document assembly, page operations
  and annotations, and **reportlab** for drawing added text, shapes and images.
  All three are BSD or Apache licensed; Qt is now the only copyleft dependency,
  and LGPL has always been workable. The build is **46.6 MB smaller unpacked
  and 20.6 MB compressed**, measured by building both engines in the same
  environment.

  The port was checked against the engine it replaced rather than only against
  the test suite: the same documents were saved through both writers and the
  rendered pages compared pixel by pixel. Rectangles, rotated objects,
  highlights and images came out identical on all four page rotations.

### Fixed
- **macOS's hidden system fonts were offered in the font picker.** A family
  whose name begins with a dot is one Apple's own text engine keeps out of
  every picker on the platform, and they are frequently partial: the runner's
  ".ADT Slab Numeric" has the digits and hardly any letters, so a line set in
  it loses most of itself. Alphabetical order put it first in the list, which
  made it the worst available default. Found by CI on macOS, which is the only
  machine in the loop that has them.
- **Icons were drawn twice as large as their buttons on a HiDPI screen.** The
  renderer allocated the pixmap at `size × ratio` device pixels, set its device
  pixel ratio, and then handed that same device pixel count to the shape
  painter — but a `QPainter` on a pixmap carrying a ratio already works in
  logical units. The normalised shapes were multiplied by the ratio a second
  time, so the ratio-2 pixmap, the one Qt picks on a HiDPI display, came out at
  4× instead of 2×: an icon twice the size of its button, of which the button
  showed one corner. It looked like the toolbar had been zoomed into.
- **Saving could write a reference to an annotation that was not in the
  file.** pypdf's `compress_identical_objects()` deduplicates and drops
  orphans in one pass, and that pass marks an object as referenced under its
  *old* number before redirecting the reference to the survivor — so a live
  object merged onto an unreferenced twin left the survivor looking
  unreferenced, dropped, and referenced from the page anyway. Dropping an
  imported annotation from a copied page creates exactly that pair, since the
  copy Orion writes from the model is usually identical to the original. The
  two jobs are now done in separate passes that cannot interact, for the same
  output size.
- **The licence notice disappeared from a window with room for it.** Placing
  it required the *bar-centred* rectangle to clear the page and zoom
  indicators, and gave up when it did not — so a window wide enough for the
  whole line beside them showed the short form, or nothing. On Windows, where
  Segoe UI makes both the notice and the indicators wider than the font this
  was written against, that was a 1400-pixel window: the commercial licensing
  address never appeared at all. It is nudged left to clear them now, by the
  smallest amount that does, and only shortened or dropped when there is
  genuinely no room.
- **A dark icon on an active button.** A checked toolbar button is filled with
  the accent, and the icon stayed the text colour: a dark line drawing on a
  dark fill, which is the same as no icon at all. `icons.py` draws a second
  copy in the accent's text colour and hangs it on the states Qt paints that
  way — `State.On` for anything checkable, `Mode.Selected` for a selected row.
  Measured rather than eyeballed: the ordinary icon comes out at a mean
  lightness of about 30, the one on an active button at 255.
- **The icon lost its frame below 32 pixels, so the four did not match.** The
  frame was dropped at the small sizes on the reasoning that it costs more in
  contrast than it returns in shape — a judgement about one icon rather than
  about four. The products draw their window icon from different sources: Qt
  scales the 512-pixel PNG, Tk picks the matching frame out of the `.ico`. So
  the same product looked like two and the four looked like four families, one
  with a black border and one without. One shape now, one letter apart, at
  every size, and `tests/test_packaging.py` checks the frame is there in each
  frame of the `.ico`.
- **The licence notice is centred on the whole status bar.** It was laid out
  as a normal status-bar widget, which centres it in whatever the page and
  zoom indicators leave over and slides it sideways as they come and go. It is
  positioned directly now, so it stays on the centre of the window. A window
  too narrow for the whole line drops the invitation to write rather than the
  notice: the copyright and the licence are the part AGPL-3.0 section 5 is
  about.
- **The `.ico` used PNG compression at every size.** Windows has accepted
  PNG-compressed icon frames since Vista, but the format every icon editor
  produces — and the one the shell has always read — is an uncompressed DIB
  below 256 pixels, with PNG only for the 256, which is the size where the
  compression saves something worth saving. Explorer showing a stale or
  generic icon for an executable whose resources are demonstrably correct is
  exactly the shape of problem that convention exists to avoid, so
  `tools/make_icon.py` now assembles the `.ico` itself and writes the
  conventional thing. `tests/test_packaging.py` pins the format.
- **The Windows start script waited on the wrong process.** It called
  `WaitForInputIdle` on what `Start-Process` handed back, which is right for
  one process and wrong for two: a onefile build starts a bootloader that
  unpacks itself and re-runs itself, and the copy that opens the window is its
  child. The bootloader has no message loop, so the wait ran out its whole
  timeout while the program sat there on screen, and the console then
  announced that nothing had happened and asked for a keypress. It now polls
  for a main window on any process with the program's image name, which covers
  both shapes, and reads "it stopped" from the process handle rather than from
  a name disappearing.
- **The release now runs the start script the way a user does.** Every check
  passed it arguments, and the no-argument path -- the double-click, the one
  that waits for the window -- was the one nobody ran. The release now takes it
  too, on Windows, and fails if the launcher reports failure while the program
  is running. It also runs on a copy of the staging directory rather than in
  it, so anything a program writes on first start cannot end up inside the
  archive.
- **The Windows archive unpacked one folder deeper than the other two.** `7z`
  stores the path it is given, so `7z a out.zip dist/Orion` produced a zip
  rooted at `dist/Orion/` while the Linux tarball was rooted at `Orion/`.
  v1.0.0 shipped that way. 7z now runs from inside the payload's parent, and
  `tests/test_release_workflow.py` pins it — found by downloading the published
  zip and listing it, which is the only thing that would have found it.
- **`tools/licence_inventory.py` crashed on any machine without dpkg.**
  `subprocess.run` raises on a missing executable rather than returning
  non-zero, so running the inventory on Windows or macOS died instead of
  reporting what it could not resolve. Guarded, and given its own exit code
  for "the report was written and some rows need a human" — 1 could not mean
  that, since an uncaught exception exits 1 too. Found on Proteus, where the
  release workflow does run it per platform; Orion's runs by hand, so nothing
  it published was affected.
- **A GPL-3.0 library was being shipped inside archives offered for commercial
  redistribution.** PyInstaller collects the standard library's optional
  `readline` extension by default, and it links `libreadline` —
  GPL-3.0-or-later, with no linking exception. THIRD-PARTY-LICENSES.md had
  recorded the row since it was first generated, directly under a sentence
  saying nothing in the closure is copyleft but Qt; the table was about the
  bundle and the sentence about the dependencies, and between them nobody read
  it. `libpython` does not link it — only that module does, and Orion never
  reads a line from an interactive prompt — so it and `rlcompleter` are now
  excluded in `orion.spec`, `libtinfo` leaves with them, and the same build
  drops from 199 native binaries to 185. `tests/test_packaging.py` pins the
  exclusion. The v1.0.0 archives still contain it, which §11 and the inventory
  now both say.
- **Text on a rotated page was saved running down the page.** Found by that
  comparison. Base page space is the page as displayed, and the old writer put
  text into the unrotated mediabox without turning it to match the page's own
  `/Rotate` — so a text box on a page carrying `/Rotate 90` was written
  sideways, and the reader then turned it again. It reproduced on 90, 180 and
  270 and not on 0, which is why it went unnoticed: an upright page is the one
  everybody checks. Images were already handled correctly, which is what
  confirmed the diagnosis.

### Removed
- **PyMuPDF**, and with it `rotate_image`/`apply_opacity` in
  `orion/utils/image_utils.py`. Those existed only because the old engine could
  rotate an image in 90-degree steps and had no opacity parameter, so any other
  angle was baked into the pixels with Pillow — resampling the image on every
  save. reportlab does both in the content stream, so nothing calls them now.
- **Qt PDF, Qt Network and the Kerberos stack behind them.** `libQt6Pdf`
  reached the archives because Qt's `qpdf` *image-format* plugin links it; it
  embeds PDFium and its own third-party dependencies, so a second PDF engine
  and a second set of licence obligations were shipping for a code path that
  never runs. It also pulled in `libQt6Network`, and with it the Kerberos
  libraries — including `libcom_err`, whose licence Ubuntu's copyright file and
  upstream e2fsprogs disagree about. 9.0 MB smaller unpacked and 4.3 MB
  compressed, net of the licence texts added at the same time.


## [1.0.0] — 2026-08-22 · first build

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
