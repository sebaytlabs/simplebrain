"""Draws the app icon (a small linked-notes graph) to packaging/icon.png.
Re-run only if the design changes; the PNG is committed and PyInstaller
converts it to .ico/.icns at build time."""
import os
import sys

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QBrush, QColor, QGuiApplication, QImage, QPainter, QPen

app = QGuiApplication(sys.argv)
S = 512
img = QImage(S, S, QImage.Format_ARGB32)
img.fill(Qt.transparent)
p = QPainter(img)
p.setRenderHint(QPainter.Antialiasing)
p.setPen(Qt.NoPen)
p.setBrush(QColor("#1f2a44"))
p.drawRoundedRect(16, 16, S - 32, S - 32, 96, 96)
nodes = [QPointF(150, 170), QPointF(340, 140), QPointF(380, 330), QPointF(190, 370), QPointF(265, 255)]
p.setPen(QPen(QColor("#8fa8d8"), 18, Qt.SolidLine, Qt.RoundCap))
for a, b in [(0, 4), (1, 4), (2, 4), (3, 4), (0, 1), (2, 3)]:
    p.drawLine(nodes[a], nodes[b])
p.setPen(Qt.NoPen)
for i, n in enumerate(nodes):
    p.setBrush(QBrush(QColor("#ffd166" if i == 4 else "#3366e6")))
    r = 58 if i == 4 else 40
    p.drawEllipse(n, r, r)
p.end()
out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.png")
img.save(out)
print(out)
