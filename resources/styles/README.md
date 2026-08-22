# Styles

Orion's appearance comes from `orion/ui/theme.py`, which defines each theme as
a set of colour **tokens** and derives the `QPalette` and the stylesheet from
them. There are no `.qss` files to keep in step with the palette, and adding a
theme is a data change rather than a code change.

Drop a `.qss` file here only if you need to override something the token system
cannot express, and load it *after* `apply_theme` so it wins.
