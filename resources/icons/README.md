# Icons

Orion's **toolbar and menu icons are drawn in code**, not stored here — see
`orion/ui/icons.py`. They are described as a few primitives in a normalised
0–1 box and painted with `QPainter`.

That is a deliberate choice:

- the repository carries no binary assets to review or license;
- icons stay crisp at any device pixel ratio;
- they recolour automatically when the theme changes, with no second set of
  files to keep in step.

This directory holds only the **application icon**, which the operating system
and the packager need as a real file:

| File | Used by |
|---|---|
| `orion.svg` | source of truth for the application icon |
| `orion.png` | generated from the SVG for PyInstaller (`make-png.py`) |

Regenerate the PNG with:

```bash
python resources/icons/make-png.py
```
