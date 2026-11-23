"""Renders packaging/icon.svg (the app icon: notes linked to a gold hub) to packaging/icon.png.
Re-run only if the design changes; the PNG is committed and PyInstaller converts it to .ico/.icns at build time."""
import os
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

app = QGuiApplication(sys.argv)
HERE = os.path.dirname(os.path.abspath(__file__))
img = QImage(512, 512, QImage.Format_ARGB32)
img.fill(Qt.transparent)
p = QPainter(img)
p.setRenderHint(QPainter.Antialiasing)
QSvgRenderer(os.path.join(HERE, "icon.svg")).render(p)
p.end()
img.save(os.path.join(HERE, "icon.png"))
print(os.path.join(HERE, "icon.png"))
