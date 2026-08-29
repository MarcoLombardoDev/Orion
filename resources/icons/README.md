# Application icon

| File | What it is |
|---|---|
| `orion.png` | 512×512, used for the window and taskbar icon at runtime, and for the executable everywhere except Windows |
| `orion.ico` | 16 to 256 pixels, seven sizes, embedded in the Windows executable and used by Explorer and the taskbar |

Both are drawn by [`tools/make_icon.py`](../../tools/make_icon.py) — the
initial in black on white, in Liberation Serif, which is metric-compatible
with Times New Roman and redistributable. Orion, Iris, Proteus and Argus share
that script and differ only in the letter, so a taskbar with all four open
reads as one family.

They are committed rather than generated during the build, so no release
depends on which fonts a runner happens to have installed.

```sh
python tools/make_icon.py Orion resources/icons
```

Every size is drawn for itself rather than scaled down from one master: a
frame that reads as a hairline at 256 pixels is a smear at 16, and the letter
that has room to breathe at 256 has to fill the square at 16 to still be a
letter. Below 32 pixels there is no frame at all — at that size it costs more
in contrast than it returns in shape.
