**Orion — PDF Editor for Desktop.** An offline PDF viewer, editor, annotator and page
organiser. No account, no server, no cloud, no telemetry: everything happens on your
machine, and your original file is untouched until you press Save.

- **Edit** — text boxes written as real, selectable, searchable PDF text; PNG, JPEG and
  WEBP images; rectangles, ellipses, lines and arrows. Move, resize and rotate anything,
  with unlimited undo and redo.
- **Annotate** — highlight, underline and strikeout that snap to the document's own text
  lines, freehand ink, comments and sticky notes, all written as standard PDF annotations
  that other readers understand.
- **Pages** — insert, duplicate, delete, reorder, rotate, import from another PDF,
  extract, split and merge.

## Download

| Platform | File |
|---|---|
| Windows (x64) | `Orion-{{VERSION}}-windows-x64.zip` |
| macOS (Apple silicon) | `Orion-{{VERSION}}-macos-arm64.zip` |
| Linux (x64) | `Orion-{{VERSION}}-linux-x64.tar.gz` |

Each archive is built on that platform's own runner — no cross-compilation, no emulation.
Unpack and run: no installation, and no Python needed.

Each unpacks to a single `Orion/` folder. Start it with the script beside the program —
`start.cmd` on Windows, `start.command` on macOS, `start.sh` on Linux. It checks the
program against the digest recorded when the archive was built and stops rather than
launching if they disagree, which is how a truncated download gets caught at the point of
launch instead of somewhere further in. The program still starts on its own if you prefer.

### Windows will say the publisher is unknown

It is meant to. These builds carry **no code-signing certificate**, so Microsoft Defender
SmartScreen shows *"Windows protected your PC"* and offers only **Don't run**. Click
**More info**, then **Run anyway**. Nothing is wrong with the download; SmartScreen is
reporting that it has never seen this publisher, which is true.

Because that warning asks you to trust a file you cannot check by looking at it, the
SHA-256 of all three archives is listed under **Checksums** at the bottom of these notes.
In PowerShell:

```powershell
Get-FileHash .\Orion-{{VERSION}}-windows-x64.zip -Algorithm SHA256
```

If what it prints matches the line below, the file is byte for byte what the build
produced. Those digests are here rather than in the archives on purpose: one that travels
with the file it describes can only tell you the file is undamaged.

On **macOS**, Gatekeeper refuses an unidentified developer the same way: right-click the
app and choose **Open**, or run `xattr -dr com.apple.quarantine Orion.app`.

Running from source instead is described in the
[README](https://github.com/MarcoLombardoDev/Orion/blob/{{TAG}}/README.md).

## Changes

See [CHANGELOG.md](https://github.com/MarcoLombardoDev/Orion/blob/{{TAG}}/CHANGELOG.md).

## Licence

Licensed **AGPL-3.0-or-later** — see
[LICENSE](https://github.com/MarcoLombardoDev/Orion/blob/{{TAG}}/LICENSE). A commercial
licence, without the AGPL's obligations, is available for closed-source and redistribution
use: see
[COMMERCIAL-LICENSE.md](https://github.com/MarcoLombardoDev/Orion/blob/{{TAG}}/COMMERCIAL-LICENSE.md).
