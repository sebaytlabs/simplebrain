"""The Glass look (SimpleBrain's only one) and clickable links in the editor. Same window, same panels:
only the look changes. Warm dark with light and grain of its own, off-white type, one
gold accent. Links in a note (web addresses, file:: paths, [[notes]]) are underlined and open on a click.
"""
import os
import random
import re

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QBrush, QColor, QFontDatabase, QImage, QPainter, QPalette, QPixmap, QRadialGradient, \
    QSyntaxHighlighter, QTextCharFormat
from PySide6.QtWidgets import QApplication

import simplebrain_core as core

INK, MUTED, GOLD, GOLD_DIM = "#f2ede4", "#a39b8f", "#e3b25a", "rgba(227,178,90,0.55)"
BG = "#14120f"

LINK_RE = re.compile(r"https?://[^\s<>\]\)]+|\[\[[^\]]+\]\]")
FILE_LINE_RE = re.compile(r"^(\s*file::\s*)(.+?)\s*$")


def links_in(line):
    """[(start, end, kind, target)] for the clickable parts of one line of a note."""
    out = []
    m = FILE_LINE_RE.match(line)
    if m:
        out.append((m.start(2), m.end(2), "file", m.group(2)))
        return out
    for m in LINK_RE.finditer(line):
        t = m.group()
        if t.startswith("[["):
            target = t[2:-2].split("|")[0].split("#")[0].strip()  # [[Note|shown text]], [[Note#Heading]]
            if target:
                out.append((m.start(), m.end(), "note", target))
        else:
            t = t.rstrip(".,;:!?")  # the sentence's full stop isn't part of the address
            out.append((m.start(), m.start() + len(t), "url", t))
    return out


class LinkHighlighter(QSyntaxHighlighter):
    def __init__(self, doc, color):
        super().__init__(doc)
        self.fmt = QTextCharFormat()
        self.fmt.setForeground(QColor(color))
        self.fmt.setFontUnderline(True)

    def set_color(self, color):
        self.fmt.setForeground(QColor(color))
        self.rehighlight()

    def highlightBlock(self, text):
        for a, b, _, _ in links_in(text):
            self.setFormat(a, b - a, self.fmt)


class LinkClicks(QObject):
    """A plain click on a link opens it (no Ctrl needed); a drag or a click on ordinary text is left
    to the editor. The pointer turns into a hand over a link."""

    def __init__(self, editor, on_link):
        super().__init__(editor)
        self.editor, self.on_link, self._down = editor, on_link, None
        editor.viewport().setMouseTracking(True)
        editor.viewport().installEventFilter(self)

    def link_at(self, pos):
        c = self.editor.cursorForPosition(pos)
        block = c.block()
        col = c.positionInBlock()
        # cursorForPosition snaps to the nearest gap: a click on a link's last letter lands after it
        rect = self.editor.cursorRect(c)
        if pos.x() < rect.x() and col > 0:
            col -= 1
        for a, b, kind, target in links_in(block.text()):
            if a <= col < b:
                return kind, target
        return None

    def eventFilter(self, obj, e):
        t = e.type()
        if t == QEvent.MouseMove:
            obj.setCursor(Qt.PointingHandCursor if self.link_at(e.position().toPoint()) else Qt.IBeamCursor)
        elif t == QEvent.MouseButtonPress and e.button() == Qt.LeftButton:
            self._down = e.position().toPoint()
        elif t == QEvent.MouseButtonRelease and e.button() == Qt.LeftButton and self._down is not None:
            moved = (e.position().toPoint() - self._down).manhattanLength() > 4
            self._down = None
            hit = None if moved or e.modifiers() & Qt.ShiftModifier else self.link_at(e.position().toPoint())
            if hit and not self.editor.textCursor().hasSelection():
                self.on_link(*hit)
                return True
        return False


def ui_font():
    have = set(QFontDatabase.families())
    for fam in ("Inter Variable", "Inter", "Ubuntu", "Noto Sans", "Cantarell", "DejaVu Sans"):
        if fam in have:
            return fam
    return None


def backdrop(size, picture=None, seed=7):
    """The window's background: warm dark of its own (the wallpaper never shows through: SimpleBrain is the
    desktop, not something over it), light from the top left, a vignette and fine grain, so flat panels read
    as glass on a surface. `picture`, if given, is laid under it blurred."""
    w, h = max(1, size.width()), max(1, size.height())
    img = QImage(w, h, QImage.Format_RGB32)
    img.fill(QColor(BG))
    p = QPainter(img)
    pic = QPixmap(picture) if picture else QPixmap()
    if not pic.isNull():
        small = pic.scaled(max(1, w // 28), max(1, h // 28), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        small = small.scaled(max(1, w // 7), max(1, h // 7), Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        p.drawPixmap(0, 0, small.scaled(w, h, Qt.IgnoreAspectRatio, Qt.SmoothTransformation))
        p.fillRect(0, 0, w, h, QColor(14, 12, 10, 200))
    glow = QRadialGradient(w * 0.25, h * 0.0, w * 0.75)
    glow.setColorAt(0, QColor(227, 178, 90, 30))
    glow.setColorAt(1, QColor(227, 178, 90, 0))
    p.fillRect(0, 0, w, h, glow)
    vig = QRadialGradient(w / 2, h / 2, max(w, h) * 0.75)
    vig.setColorAt(0.55, QColor(0, 0, 0, 0))
    vig.setColorAt(1, QColor(0, 0, 0, 110))
    p.fillRect(0, 0, w, h, vig)
    rnd = random.Random(seed)
    tile = QImage(128, 128, QImage.Format_ARGB32)
    for y in range(128):
        for x in range(128):
            v = rnd.randint(0, 255)
            tile.setPixelColor(x, y, QColor(v, v, v, rnd.randint(0, 8)))
    p.drawTiledPixmap(0, 0, w, h, QPixmap.fromImage(tile))
    p.end()
    return img


def palette():
    pal = QPalette()
    for role, color in ((QPalette.Window, BG), (QPalette.WindowText, INK), (QPalette.Base, "#1c1915"),
                        (QPalette.AlternateBase, "#221e19"), (QPalette.Text, INK), (QPalette.Button, "#26221c"),
                        (QPalette.ButtonText, INK), (QPalette.Highlight, GOLD), (QPalette.HighlightedText, "#1a1206"),
                        (QPalette.ToolTipBase, "#26221c"), (QPalette.ToolTipText, INK), (QPalette.Link, GOLD),
                        (QPalette.PlaceholderText, "#7d756a"), (QPalette.BrightText, "#ffffff")):
        pal.setColor(role, QColor(color))
    pal.setColor(QPalette.Disabled, QPalette.Text, QColor("#6e675e"))
    pal.setColor(QPalette.Disabled, QPalette.ButtonText, QColor("#6e675e"))
    return pal


def stylesheet(bg_path):
    fam = ui_font()
    font = f'font-family: "{fam}";' if fam else ""
    return f"""
    QWidget {{ {font} color: {INK}; }}
    #glassScroll, #glassScroll > QWidget, #glassRoot {{ background: transparent; border: none; }}
    QSplitter, QSplitter > QWidget {{ background: transparent; }}
    QSplitter::handle {{ background: transparent; }}
    QMenuBar {{ background: transparent; color: {MUTED}; }}
    QMenuBar::item:selected {{ background: rgba(255,248,238,0.08); color: {INK}; border-radius: 6px; }}
    QMenu {{ background: #1f1b17; border: 1px solid rgba(255,248,238,0.10); border-radius: 10px; padding: 6px; }}
    QMenu::item {{ padding: 6px 18px; border-radius: 6px; }}
    QMenu::item:selected {{ background: rgba(227,178,90,0.18); color: {INK}; }}
    QDialog, QMessageBox, QInputDialog, QFileDialog {{ background: #1b1814; }}
    QLabel {{ background: transparent; }}
    QPlainTextEdit, QListWidget, QTableWidget {{
        background: rgba(255,248,238,0.055); border: 1px solid rgba(255,248,238,0.10); border-radius: 14px;
        padding: 6px; selection-background-color: rgba(227,178,90,0.32); selection-color: {INK}; }}
    QPlainTextEdit {{ padding: 12px 14px; font-size: 15px; }}
    QListWidget::item {{ border-radius: 8px; padding: 2px; }}
    QListWidget::item:selected {{ background: rgba(227,178,90,0.18); color: {INK}; }}
    QListWidget::item:hover {{ background: rgba(255,248,238,0.05); }}
    QListWidget::indicator {{ width: 15px; height: 15px; border-radius: 4px; border: 1.5px solid {MUTED};
        background: transparent; }}
    QListWidget::indicator:checked {{ background: {GOLD}; border-color: {GOLD}; }}
    QListWidget::indicator:hover {{ border-color: {GOLD}; }}
    QHeaderView::section {{ background: transparent; color: {MUTED}; border: none;
        border-bottom: 1px solid rgba(255,248,238,0.10); padding: 6px; font-weight: 600; }}
    QTableWidget {{ gridline-color: rgba(255,248,238,0.06); }}
    QTableCornerButton::section {{ background: transparent; border: none; }}
    QLineEdit, QComboBox {{
        background: rgba(255,248,238,0.07); border: 1px solid rgba(255,248,238,0.13); border-radius: 12px;
        padding: 6px 12px; color: {INK}; }}
    QLineEdit:focus, QComboBox:focus {{ border-color: {GOLD_DIM}; background: rgba(255,248,238,0.10); }}
    QComboBox::drop-down {{ border: none; width: 22px; }}
    QComboBox QAbstractItemView {{ background: #1f1b17; border: 1px solid rgba(255,248,238,0.10);
        selection-background-color: rgba(227,178,90,0.25); }}
    QPushButton {{
        background: rgba(255,248,238,0.06); border: 1px solid rgba(255,248,238,0.12); border-radius: 10px;
        padding: 5px 12px; color: {INK}; }}
    QPushButton:hover {{ border-color: {GOLD_DIM}; color: {GOLD}; background: rgba(227,178,90,0.08); }}
    QPushButton:pressed {{ background: rgba(227,178,90,0.18); }}
    #iconButton {{ padding: 2px 0; border-radius: 8px; }}
    QCheckBox {{ background: transparent; spacing: 8px; }}
    QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 5px; border: 1.5px solid {MUTED};
        background: transparent; }}
    QCheckBox::indicator:checked {{ background: {GOLD}; border-color: {GOLD}; }}
    QCheckBox::indicator:hover {{ border-color: {GOLD}; }}
    QScrollArea {{ background: transparent; }}
    QScrollBar:vertical {{ background: transparent; width: 9px; margin: 4px 1px; }}
    QScrollBar:horizontal {{ background: transparent; height: 9px; margin: 1px 4px; }}
    QScrollBar::handle {{ background: rgba(255,248,238,0.16); border-radius: 4px; min-height: 28px; min-width: 28px; }}
    QScrollBar::handle:hover {{ background: rgba(227,178,90,0.45); }}
    QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{ height: 0; width: 0; background: none; }}
    #results {{ background: #1f1b17; border: 1px solid rgba(227,178,90,0.35); border-radius: 14px; padding: 6px;
        font-size: 14px; }}
    #results::item {{ padding: 7px 10px; border-radius: 8px; }}
    #results::item:selected {{ background: rgba(227,178,90,0.20); color: {INK}; }}
    QToolTip {{ background: #26221c; color: {INK}; border: 1px solid rgba(255,248,238,0.12); border-radius: 6px; padding: 4px 8px; }}
    """


def apply(window, on):
    """Glass on (or off, back to the system look) for the whole app."""
    app = QApplication.instance()
    if not hasattr(window, "_plain_palette"):
        window._plain_palette = app.palette()
    if not on:
        app.setPalette(window._plain_palette)
        window.setPalette(window._plain_palette)
        window.setStyleSheet("")
        window.graph.dot_color = window.graph.DOT
        window.links.set_color(window.palette().link().color().name())
        return
    cache = os.path.join(core.user_config_dir(), "glass")
    os.makedirs(cache, exist_ok=True)
    screen = window.screen()
    size = (screen.geometry().size() if screen else window.size()).expandedTo(window.size())  # never tiles
    window._glass_size = size
    bg = os.path.join(cache, "backdrop.png")
    backdrop(size).save(bg)
    app.setPalette(palette())
    # The backdrop is the window's own background brush, drawn 1:1: a stylesheet image is rescaled on every
    # repaint, which made the whole window lag on an older computer.
    pal = palette()
    pal.setBrush(QPalette.Window, QBrush(QPixmap(bg)))
    window.setPalette(pal)
    window.setAutoFillBackground(True)
    window.setStyleSheet(stylesheet(bg.replace("\\", "/")))
    window.graph.dot_color = QColor("#d9cbb4")
    window.links.set_color(GOLD)
    window.graph.update()
