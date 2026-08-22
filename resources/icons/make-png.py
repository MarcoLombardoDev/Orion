"""Render ``orion.svg`` to ``orion.png`` for packaging.

Kept as a script rather than a build step so the PNG stays a reviewable,
reproducible artefact instead of a mystery binary.
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SIZE = 512


def main() -> int:
    from PySide6.QtCore import QSize, Qt
    from PySide6.QtGui import QGuiApplication, QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer

    app = QGuiApplication(sys.argv[:1])  # noqa: F841 - required for QImage
    renderer = QSvgRenderer(str(HERE / "orion.svg"))
    if not renderer.isValid():
        print("orion.svg could not be parsed", file=sys.stderr)
        return 1

    image = QImage(QSize(SIZE, SIZE), QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    renderer.render(painter)
    painter.end()

    target = HERE / "orion.png"
    if not image.save(str(target)):
        print(f"could not write {target}", file=sys.stderr)
        return 1
    print(f"wrote {target} ({SIZE}x{SIZE})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
