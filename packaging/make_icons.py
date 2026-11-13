"""Render the SVG icon to PNG/ICO (and ICNS on macOS) for packaging.

Usage: python packaging/make_icons.py
Requires PySide6 (QtSvg) and Pillow.
"""

import os
import subprocess
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RES = os.path.join(ROOT, "comitra", "ui", "resources")
OUT = os.path.join(HERE, "build-icons")


def render(size: int, path: str) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer

    r = QSvgRenderer(os.path.join(RES, "icon.svg"))
    img = QImage(size, size, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    r.render(p)
    p.end()
    img.save(path)


def main() -> None:
    from PySide6.QtGui import QGuiApplication

    app = QGuiApplication(sys.argv)
    app.setApplicationName("comitra-icons")
    os.makedirs(OUT, exist_ok=True)
    render(512, os.path.join(RES, "icon.png"))
    render(256, os.path.join(OUT, "comitra-256.png"))
    from PIL import Image

    img = Image.open(os.path.join(RES, "icon.png"))
    img.save(os.path.join(OUT, "comitra.ico"), sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    if sys.platform == "darwin":
        iconset = os.path.join(OUT, "comitra.iconset")
        os.makedirs(iconset, exist_ok=True)
        for s in (16, 32, 128, 256, 512):
            render(s, os.path.join(iconset, f"icon_{s}x{s}.png"))
            render(s * 2, os.path.join(iconset, f"icon_{s}x{s}@2x.png"))
        subprocess.run(["iconutil", "-c", "icns", iconset, "-o", os.path.join(OUT, "comitra.icns")], check=True)
    print("icons written to", OUT)


if __name__ == "__main__":
    main()
