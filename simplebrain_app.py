#!/usr/bin/env python3
"""SimpleBrain desktop app (Qt): capture bar; notes | editor | graph; Inbox, Tasks, Calendar, Dataview.
All data logic lives in simplebrain_core; this file is only the UI.

Usage: simplebrain            (installed app)
       python3 simplebrain_app.py [--selftest]
"""
import html
import os
import sys
import threading
import time
from datetime import date, datetime

from PySide6.QtCore import QElapsedTimer, QObject, QPointF, QRectF, QSize, QSizeF, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QAction, QColor, QCursor, QDesktopServices, QIcon, QKeySequence, QPainter, QPainterPath, QPen, QPixmap, QShortcut,
    QRegion, QTextCursor,
)
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QGridLayout,
    QHBoxLayout,
    QFrame, QHeaderView, QInputDialog, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMenu, QMessageBox, QPlainTextEdit, QPushButton,
    QScrollArea, QSizePolicy, QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

import simplebrain_core as core
import simplebrain_dataview as dv
import simplebrain_day as workday
import simplebrain_desk as desk
import simplebrain_drop as drop
import simplebrain_find as find
import simplebrain_budget as budget
import simplebrain_glass as glass
import simplebrain_money as money
import simplebrain_habits as habits
import simplebrain_links as linking
import simplebrain_mail as mail
import simplebrain_mailwin as mailwin
import simplebrain_calwin as calwin
import simplebrain_today as today_note
import simplebrain_update as updater
import simplebrain_watch as watch
import simplebrain_publish as pub
import simplebrain_setup as setup
import simplebrain_recommend as reco
import simplebrain_sync as devsync


def qr_pixmap(text, scale=5):
    """QR code of `text` as a pixmap (black on white with the quiet zone scanners need)."""
    import segno
    rows = segno.make(text, micro=False).matrix
    n = len(rows) + 8
    pm = QPixmap(n * scale, n * scale)
    pm.fill(Qt.white)
    p = QPainter(pm)
    for y, row in enumerate(rows):
        for x, bit in enumerate(row):
            if bit:
                p.fillRect((x + 4) * scale, (y + 4) * scale, scale, scale, Qt.black)
    p.end()
    return pm

APP_NAME = "SimpleBrain"


def resource_path(name):
    """Bundled file path, both from source and inside a PyInstaller build."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)


class Bridge(QObject):
    """Background threads hand results to the UI thread through these signals
    (Qt queues cross-thread signal delivery onto the receiver's thread)."""
    ics_fetched = Signal(object, bool)
    publish_done = Signal(str)  # "" on success, else why the website update failed
    reco_done = Signal(str, str)  # vault it was built for, result
    update_done = Signal(str)  # "" on success, else why it failed
    cite_found = Signal(object, str)  # candidate reference lines, or [] and why the lookup failed
    sync_status = Signal(object)  # {"state", "message", "time"} from the device-sync thread
    sync_paired = Signal(str)  # "" once a device was added, else why it wasn't
    run_ui = Signal(object)  # (fn, box): run fn on the UI thread and hand its result back


def panel_head(title, *header_widgets, hint=None):
    """(title row, grey hint label or None) for a panel."""
    head = QWidget()
    row = QHBoxLayout(head)
    row.setContentsMargins(0, 0, 0, 0)
    row.addWidget(QLabel(f"<b>{title}</b>"), 1)
    for w in header_widgets:
        row.addWidget(w)
    h = None
    if hint:
        h = QLabel(hint)
        h.setWordWrap(True)
        h.setStyleSheet("color: gray")
        h.setAlignment(Qt.AlignTop)
    return head, h


def section(title, *header_widgets, hint=None):
    box = QWidget()
    lay = QVBoxLayout(box)
    lay.setContentsMargins(4, 4, 4, 4)
    for w in panel_head(title, *header_widgets, hint=hint):
        if w:
            lay.addWidget(w)
    return box, lay


def task_lines(text):
    return [l for l in text.splitlines() if core.TASK_RE.match(l)]


class GraphView(QWidget):
    """Mind-map note graph, centered on the open note. Scroll to zoom (toward
    the cursor), drag empty space to pan, drag a dot to move it and its branch,
    click a dot to open its note (which becomes the center), right-click a dot
    to give it an icon or picture."""
    ICON_CHOICES = (("🏠", "House"), ("⭐", "Star"), ("📚", "Books"), ("💡", "Idea"), ("🎯", "Goal"),
                    ("🧠", "Brain"), ("💼", "Work"), ("❤️", "Heart"), ("🌱", "Growth"), ("📅", "Calendar"),
                    ("✅", "Done"), ("🎵", "Music"))

    def __init__(self, on_open):
        super().__init__()
        self.on_open = on_open
        self.icons, self._pictures = {}, {}  # note -> emoji or picture; (path, mtime) -> round pixmap or None
        self.pos, self.edges, self.missing = {}, [], set()
        self.center, self.parent = "Home.md", {}  # center: the open note; parent: each note's place in the tree
        self.show_all = False  # False: only the notes related to the open note
        self._grab = None  # (note, {branch note: its start position}, press point) while a dot is dragged
        self.highlight = None  # notes the Dataview filter matches (None: no filter on)
        self.zoom, self.offset = 1.0, QPointF(0, 0)
        self.dot_color = self.DOT  # the Glass theme warms it
        self._press = None  # (screen point, offset at press) while the mouse is down
        self._dragged = False
        self._to = None  # (positions, zoom, offset) the running glide is heading for
        self._glide_timer = QTimer(self)
        self._glide_timer.setInterval(16)
        self._glide_timer.timeout.connect(self._step)
        self.setMinimumSize(200, 200)
        self.setCursor(Qt.OpenHandCursor)

    GLIDE_MS = 280
    DOT = QColor(51, 102, 230)

    def settle(self):
        """Jump a running glide to its end."""
        if self._to:
            self._glide_timer.stop()
            self.pos, self.zoom, self.offset = self._to
            self._to = None
            self.update()

    def _step(self):
        t = min(1.0, self._clock.elapsed() / self.GLIDE_MS)
        if t >= 1.0:
            return self.settle()
        k = 1 - (1 - t) ** 3  # ease-out: fast start, soft landing
        old_pos, old_zoom, old_off = self._from
        new_pos, new_zoom, new_off = self._to
        self.pos = {n: [a + (b - a) * k for a, b in zip(old_pos.get(n, xy), xy)] for n, xy in new_pos.items()}
        self.zoom = old_zoom + (new_zoom - old_zoom) * k
        self.offset = old_off + (new_off - old_off) * k
        self.update()

    def recompute(self):
        self.settle()
        old = (self.pos, self.zoom, QPointF(self.offset))
        notes, edges, self.missing = core.build_graph()
        self.icons = core.graph_icons()
        if not self.show_all:  # just what is related to the open note, so the map stays readable
            notes, edges = core.local_graph(notes, edges, self.center)
            self.missing = {n for n in self.missing if n in notes}
        self.pos, self.parent = core.mindmap_layout(notes, edges, max(self.width(), 200),
                                                    max(self.height(), 200), pinned=self.center)
        self.edges = edges
        self.fit()
        if old[0] and old[0] != self.pos:  # glide from the old picture to the new one
            self._from, self._to = old, (self.pos, self.zoom, QPointF(self.offset))
            self.zoom, self.offset = old[1], old[2]
            self.pos = {n: list(old[0].get(n, xy)) for n, xy in self._to[0].items()}  # new dots start in place
            self._clock = QElapsedTimer()
            self._clock.start()
            self._glide_timer.start()

    def fit(self):
        """Scale to the box (in up to 1.5x, so a big window is used; out as far as needed) and center so every dot is visible."""
        self.settle()
        if not self.pos:
            self.zoom, self.offset = 1.0, QPointF(0, 0)
            return self.update()
        fm = self.fontMetrics()  # labels sit right of their dot: count them, or the farthest one is cut off
        r = {n: max(9, self.radius(n)) for n in self.pos}
        left = min(x - r[n] for n, (x, _) in self.pos.items())
        right = max(x + r[n] + 3 + fm.horizontalAdvance(core.note_title(n)) for n, (x, _) in self.pos.items())
        top, bottom = min(y - r[n] for n, (_, y) in self.pos.items()), max(y + r[n] for n, (_, y) in self.pos.items())
        margin = 30
        bw, bh = right - left + 2 * margin, bottom - top + 2 * margin
        self.zoom = min(1.5, self.width() / bw, self.height() / bh)
        self.offset = QPointF(self.width() / 2 - (left + right) / 2 * self.zoom,
                              self.height() / 2 - (top + bottom) / 2 * self.zoom)
        self.update()

    def resizeEvent(self, e):
        # a resize only re-fits: re-running the layout on every resize event froze the window
        self.fit() if self.pos else self.recompute()

    def to_screen(self, x, y):
        return QPointF(x * self.zoom + self.offset.x(), y * self.zoom + self.offset.y())

    def zoom_at(self, point, factor):
        """Zoom by factor, keeping the graph point under `point` where it is."""
        new = max(0.05, min(5.0, self.zoom * factor))  # 0.05: a fitted big vault starts below 0.2
        wx, wy = (point.x() - self.offset.x()) / self.zoom, (point.y() - self.offset.y()) / self.zoom
        self.zoom = new
        self.offset = QPointF(point.x() - wx * new, point.y() - wy * new)
        self.update()

    def node_at(self, point):
        for n, (x, y) in self.pos.items():
            s = self.to_screen(x, y)
            reach = max(15, self.radius(n) * self.zoom)  # an icon is bigger than a dot: all of it is clickable
            if (point.x() - s.x()) ** 2 + (point.y() - s.y()) ** 2 <= reach ** 2:
                return n
        return None

    def icon(self, n):
        """("picture", round pixmap), ("emoji", text) or None for a plain dot. A picture that is
        gone or unreadable falls back to the dot rather than showing its file name."""
        icon = self.icons.get(n)
        if not icon or n in self.missing:
            return None
        path = core.graph_icon_picture(icon)
        if path is None:
            return "emoji", icon
        pm = self.round_picture(path)
        return ("picture", pm) if pm else None

    def round_picture(self, path, side=128):
        try:
            key = (path, os.path.getmtime(path))  # a replaced picture is loaded again
        except OSError:
            return None
        if key not in self._pictures:
            src = QPixmap(path)
            out = None
            if not src.isNull():
                src = src.scaled(side, side, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
                out = QPixmap(side, side)
                out.fill(Qt.transparent)
                q = QPainter(out)
                q.setRenderHint(QPainter.Antialiasing)
                clip = QPainterPath()
                clip.addEllipse(0, 0, side, side)
                q.setClipPath(clip)
                q.drawPixmap((side - src.width()) // 2, (side - src.height()) // 2, src)  # crop to the middle
                q.end()
            self._pictures[key] = out
        return self._pictures[key]

    def radius(self, n, lit=False):
        here = n == self.center
        if self.icon(n):
            return 17 if here else 14
        return 10 if here else 9 if lit else 6

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), self.palette().base())
        p.translate(self.offset)
        p.scale(self.zoom, self.zoom)
        pen = QPen(QColor(170, 170, 170), 1)
        pen.setCosmetic(True)  # edges stay 1px at any zoom
        p.setPen(pen)
        faint = QPen(QColor(120, 120, 120, 70), 1)
        faint.setCosmetic(True)
        for a, b in self.edges:
            if a not in self.pos or b not in self.pos:
                continue
            if self.parent.get(a) == b or self.parent.get(b) == a:
                p.setPen(pen)  # a branch of the tree
            elif a.endswith(core.ANSWERS_SUFFIX + ".md") or b.endswith(core.ANSWERS_SUFFIX + ".md"):
                continue  # an Answers roll-up links to everything it summarizes: not drawn
            else:
                p.setPen(faint)  # a cross-link between branches
            p.drawLine(QPointF(*self.pos[a]), QPointF(*self.pos[b]))
        faded = QColor(150, 150, 150)
        label_font = p.font()
        for n, (x, y) in self.pos.items():
            lit = self.highlight is not None and n in self.highlight
            dim = self.highlight is not None and not lit  # a filter is on and this note isn't in it
            here = n == self.center  # the note you are reading
            r = self.radius(n, lit)
            icon = self.icon(n)
            if icon:
                box = QRectF(x - r, y - r, 2 * r, 2 * r)
                p.setOpacity(0.35 if dim else 1.0)
                p.setPen(Qt.NoPen)
                p.setBrush(self.palette().base())  # hides the edges behind it
                p.drawEllipse(box)
                if icon[0] == "picture":
                    p.setRenderHint(QPainter.SmoothPixmapTransform)
                    p.drawPixmap(box, icon[1], QRectF(icon[1].rect()))
                else:
                    font = p.font()
                    font.setPixelSize(max(1, int(r * 1.35)))
                    p.setFont(font)
                    p.setPen(self.palette().text().color())
                    p.drawText(box, Qt.AlignCenter, icon[1])
                ring = QPen(self.palette().highlight().color() if here else QColor(235, 120, 20) if lit
                            else faded if dim else self.dot_color, 3 if here else 2)
                ring.setCosmetic(True)
                p.setPen(ring)
                p.setBrush(Qt.NoBrush)
                p.drawEllipse(box)
                p.setOpacity(1.0)
                label_font.setBold(lit or here)
                p.setFont(label_font)
                p.setPen(faded if dim else self.palette().text().color())
                p.drawText(QPointF(x + r + 3, y + 4), core.note_title(n))
                continue
            if n in self.missing:  # linked but not written yet: hollow grey dot
                ring = QPen(faded, 1.5)
                ring.setCosmetic(True)
                p.setPen(ring)
                p.setBrush(self.palette().base())  # hides the edge behind the ring
            else:
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(235, 120, 20) if lit else faded if dim else self.dot_color)
            if here:
                ring = QPen(self.palette().highlight().color(), 3)
                ring.setCosmetic(True)
                p.setPen(ring)
                p.setBrush(QColor(235, 120, 20) if lit else self.dot_color)
            p.drawEllipse(QPointF(x, y), r, r)
            label_font.setBold(lit or here)
            p.setFont(label_font)  # not p.font(): an emoji before this one left it emoji-sized
            p.setPen(faded if n in self.missing or dim else self.palette().text().color())
            p.drawText(QPointF(x + r + 3, y + 4), core.note_title(n))

    def wheelEvent(self, e):
        self.zoom_at(e.position(), 1.15 ** (e.angleDelta().y() / 120))

    def branch(self, note):
        """`note` and everything below it in the tree."""
        kids = {}
        for n, up in self.parent.items():
            kids.setdefault(up, []).append(n)
        out, todo = {}, [note]
        while todo:
            n = todo.pop()
            out[n] = list(self.pos[n])
            todo += kids.get(n, [])
        return out

    def mousePressEvent(self, e):
        if e.button() != Qt.LeftButton:  # right-click is the icon menu, not a click on the note
            return
        self.settle()
        self._press, self._dragged = (e.position(), QPointF(self.offset)), False
        n = self.node_at(e.position())
        self._grab = (n, self.branch(n)) if n else None

    def mouseMoveEvent(self, e):
        if self._press is None:
            return
        start, offset = self._press
        delta = e.position() - start
        if abs(delta.x()) + abs(delta.y()) > 3:  # a small wobble is still a click
            self._dragged = True
            self.setCursor(Qt.ClosedHandCursor)
        if self._dragged and self._grab:  # carry the dot and its branch
            for n, (x, y) in self._grab[1].items():
                self.pos[n] = [x + delta.x() / self.zoom, y + delta.y() / self.zoom]
            self.update()
        elif self._dragged:
            self.offset = offset + delta
            self.update()

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        if self._press is not None and not self._dragged:
            n = self.node_at(e.position())
            if n:
                self.on_open(n)
        self._press = self._grab = None
        self.setCursor(Qt.OpenHandCursor)

    def contextMenuEvent(self, e):
        n = self.node_at(QPointF(e.pos()))
        if not n or n in self.missing:  # a hollow dot has no note yet to remember an icon for
            return
        menu = QMenu(self)
        menu.addSection(f"Graph icon for {core.note_title(n)}")
        for emoji, name in self.ICON_CHOICES:
            menu.addAction(f"{emoji}   {name}", lambda emoji=emoji: self.set_icon(n, emoji=emoji))
        menu.addSeparator()
        menu.addAction("Other emoji…", lambda: self.ask_emoji(n))
        menu.addAction("Picture from a file…", lambda: self.ask_picture(n))
        if n in self.icons:
            menu.addAction("Back to a plain dot", lambda: self.set_icon(n))
        menu.exec(e.globalPos())

    def ask_emoji(self, n):
        text, ok = QInputDialog.getText(self, "Graph icon", "Type or paste an emoji (Ctrl+. opens the emoji picker on many systems):")
        if ok and text.strip():
            self.set_icon(n, emoji=text.strip()[:8])  # one emoji can be several characters; a sentence isn't an icon

    def ask_picture(self, n):
        exts = " ".join("*" + x for x in core.PICTURE_EXTS)
        path, _ = QFileDialog.getOpenFileName(self, "Choose a picture", os.path.expanduser("~/Pictures"),
                                              f"Pictures ({exts})")
        if not path:
            return
        if QPixmap(path).isNull():
            QMessageBox.warning(self, APP_NAME, "That file couldn't be opened as a picture.")
            return
        self.set_icon(n, picture=path)

    def set_icon(self, n, emoji=None, picture=None):
        try:
            core.set_graph_icon(n, emoji=emoji, picture=picture)
        except (OSError, ValueError) as err:
            QMessageBox.warning(self, APP_NAME, f"Couldn't set that icon: {err}")
            return
        self.icons = core.graph_icons()
        self.update()  # not fit(): that would undo where you had zoomed and panned to


class Tour(QWidget):
    """The tutorial: dims the window, rings one part at a time, says what it is for and has you do one real thing.
    A step with a check (`{"check": ...}`) opens a hole in the dimming so that part can be used, and Next waits until
    the thing is done. `required` (first launch, and after an update that changed it): no Skip, no Esc, the window
    can't be closed or left until the last step. From the How to button it is a replay: Skip, Esc and Next always work.
    Step: (title, text, widgets, try line[, {"start": fn() -> base, "check": fn(base) -> bool, "focus": widget}])."""

    def __init__(self, window, steps, required=False):
        super().__init__(window)
        self.win, self.steps, self.i, self.target = window, steps, 0, QRectF()
        self.required, self.passed, self.base = required, set(), None
        self.setFocusPolicy(Qt.StrongFocus)
        self.card = QFrame(self)
        self.card.setAutoFillBackground(True)
        self.card.setFrameShape(QFrame.StyledPanel)
        self.card.setFixedWidth(360)
        lay = QVBoxLayout(self.card)
        self.title, self.body, self.count = QLabel(), QLabel(), QLabel()
        self.body.setWordWrap(True)
        self.try_it = QLabel()  # one thing to do right now: a tutorial, not just a description
        self.try_it.setWordWrap(True)
        self.try_it.setTextFormat(Qt.RichText)
        self.title.setStyleSheet("font-weight: bold; font-size: 15px")
        self.count.setStyleSheet("color: gray")
        lay.addWidget(self.title)
        lay.addWidget(self.body)
        lay.addWidget(self.try_it)
        buttons = QHBoxLayout()
        buttons.addWidget(self.count, 1)
        self.skip_button = QPushButton("Skip")
        self.skip_button.setVisible(not required)
        self.back_button, self.next_button = QPushButton("Back"), QPushButton("Next")
        for b, slot in ((self.skip_button, self.finish), (self.back_button, self.back), (self.next_button, self.next)):
            b.setFocusPolicy(Qt.NoFocus)  # the keys go to the tour itself, so Enter never "presses" a hidden button twice
            b.clicked.connect(lambda *_, f=slot: f())
            buttons.addWidget(b)
        lay.addLayout(buttons)
        # While a step waits for you, its check is looked at a few times a second (only while the tutorial is up).
        self.poll = QTimer(self, interval=300)
        self.poll.timeout.connect(self.check_step)
        self.setGeometry(window.rect())
        self.show_step()
        self.raise_()
        self.show()

    def opts(self, i=None):
        step = self.steps[self.i if i is None else i]
        return step[4] if len(step) > 4 else {}

    def waiting(self):
        """True while this step's thing isn't done yet (Next is locked only in the required tutorial)."""
        return "check" in self.opts() and self.i not in self.passed

    def show_step(self):
        title, text, widgets, *rest = self.steps[self.i]
        o = self.opts()
        self.base = o["start"]() if "start" in o and self.i not in self.passed else self.base
        self.try_line = rest[0] if rest else ""
        self.title.setText(title)
        self.body.setText(text)
        self.count.setText(f"{self.i + 1} of {len(self.steps)}")
        self.back_button.setEnabled(self.i > 0)
        self.next_button.setText("Done" if self.i == len(self.steps) - 1 else "Next")
        self.place_target()
        self.refresh_state()
        if "check" in o and self.i not in self.passed:
            self.poll.start()
            w = o.get("focus") or next(iter(self.step_widgets()), None)
            if w is not None and w.isVisible():
                w.setFocus()  # type straight into the ringed part
        else:
            self.poll.stop()
            self.setFocus()

    def step_widgets(self):
        widgets = self.steps[self.i][2]
        return [w for w in (widgets() if callable(widgets) else widgets) if w is not None and w.isVisible()]

    def place_target(self):
        widgets = self.step_widgets()
        scroller = self.win.centralWidget()
        if widgets and isinstance(scroller, QScrollArea):
            scroller.ensureWidgetVisible(widgets[0], 0, 40)  # the bottom panels sit below the fold in a short window
        rect = QRectF()
        for w in widgets:
            rect = rect.united(QRectF(w.mapTo(self.win, w.rect().topLeft()), QSizeF(w.size())))
        self.target = rect.adjusted(-6, -6, 6, 6).intersected(QRectF(self.rect())) if not rect.isNull() else QRectF()
        self.card.adjustSize()
        self.place_card()
        # A step you act on has a hole: clicks there reach the window; everywhere else stays blocked.
        region = QRegion(self.rect())
        if "check" in self.opts() and not self.target.isNull():
            region = region.subtracted(QRegion(self.target.toAlignedRect()))
        self.setMask(region.united(QRegion(self.card.geometry())))
        self.update()

    def refresh_state(self):
        if self.waiting():
            self.try_it.setText(f"<b style='color:#c8902e'>Your turn:</b> {self.try_line}"
                                + ("<br><span style='color:gray'>Next opens when you've done it.</span>" if self.required else ""))
        elif "check" in self.opts():
            self.try_it.setText(f"<b style='color:#6fbf73'>✓ Done.</b> {self.try_line}<br>Click <b>Next</b>.")
        else:
            self.try_it.setText(f"<b style='color:#c8902e'>Try it:</b> {self.try_line}" if self.try_line else "")
        self.try_it.setVisible(bool(self.try_line))
        self.next_button.setEnabled(not (self.required and self.waiting()))
        self.card.adjustSize()

    def check_step(self):
        o = self.opts()
        if "check" not in o:
            return
        try:
            ok = bool(o["check"](self.base))
        except Exception:  # a half-written note mid-check is not done yet, never a crash
            ok = False
        if ok and self.i not in self.passed:
            self.passed.add(self.i)
            self.poll.stop()
            if "done" in o:
                o["done"](self.base)
            self.refresh_state()
            self.place_target()
            self.setFocus()  # Enter now goes to Next
        elif not ok:
            self.place_target()  # follow the part if the window changed under it (a new row, a resize)

    def nag(self):
        """Something tried to leave the required tutorial: say so on the card."""
        self.body.setText(self.steps[self.i][1] + "<br><b style='color:#ff8a2a'>Finish the tutorial first: "
                          "it's the way into SimpleBrain.</b>")
        self.card.adjustSize()
        self.place_card()
        self.raise_()

    def place_card(self):
        w, h, room = self.card.width(), self.card.height(), self.rect()
        t = self.target
        if t.isNull():
            x, y = (room.width() - w) / 2, (room.height() - h) / 2
        else:
            x = min(max(t.center().x() - w / 2, 12), room.width() - w - 12)
            if t.bottom() + 14 + h <= room.height():
                y = t.bottom() + 14
            elif t.top() - 14 - h >= 0:
                y = t.top() - 14 - h
            else:  # a target as tall as the window: the card goes inside it, in the corner
                x, y = min(max(t.right() - w - 12, 12), room.width() - w - 12), 12
        self.card.move(int(max(x, 0)), int(max(y, 0)))

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        dim = QPainterPath()
        dim.addRect(QRectF(self.rect()))
        if not self.target.isNull():
            hole = QPainterPath()
            hole.addRoundedRect(self.target, 8, 8)
            dim = dim.subtracted(hole)
        p.fillPath(dim, QColor(0, 0, 0, 150))
        if not self.target.isNull():
            p.setPen(QPen(self.palette().highlight().color(), 3))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(self.target, 8, 8)

    def mousePressEvent(self, e):
        e.accept()  # the dimmed window underneath is not clickable during the tour

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Right, Qt.Key_Down, Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.next()
        elif e.key() in (Qt.Key_Left, Qt.Key_Up, Qt.Key_Backspace):
            self.back()
        elif e.key() == Qt.Key_Escape:
            if self.required:
                self.nag()
            else:
                self.finish()
        else:
            e.ignore()

    def next(self):
        if self.required and self.waiting():
            return
        if self.i == len(self.steps) - 1:
            self.finish()
        else:
            self.i += 1
            self.show_step()

    def back(self):
        if self.i:
            self.i -= 1
            self.show_step()

    def relayout(self):
        self.setGeometry(self.win.rect())
        self.place_target()

    def finish(self):
        self.poll.stop()
        self.hide()
        self.deleteLater()
        self.win.tour_finished(self)


class Viewer(QWidget):
    """Pictures and videos inside SimpleBrain, where the graph is: never full screen, never a window of their own.
    A picture is drawn here; a video or audio file plays in mpv drawn into this area. × goes back to the graph."""

    def __init__(self, on_close, on_outside):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        head = QHBoxLayout()
        self.title = QLabel()
        self.title.setTextFormat(Qt.PlainText)
        head.addWidget(self.title, 1)
        self.outside = QPushButton("Open outside")
        self.outside.setToolTip("Open it in its own program instead")
        self.outside.clicked.connect(lambda *_: on_outside(self.path))
        head.addWidget(self.outside)
        self.close_button = QPushButton("×  Back to the graph")
        self.close_button.clicked.connect(lambda *_: on_close())
        head.addWidget(self.close_button)
        lay.addLayout(head)
        self.picture = QLabel()
        self.picture.setAlignment(Qt.AlignCenter)
        self.picture.setMinimumSize(120, 120)
        self.picture.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        lay.addWidget(self.picture, 1)
        self.text = QPlainTextEdit()  # a call card or other short text file, read right here
        self.text.setReadOnly(True)
        self.text.hide()
        lay.addWidget(self.text, 1)
        self.host = QWidget()  # mpv draws into this widget's own native window
        self.host.setAttribute(Qt.WA_NativeWindow, True)
        self.host.setStyleSheet("background: black")
        self.host.setMinimumSize(160, 90)
        lay.addWidget(self.host, 1)
        self.path, self.pixmap, self.proc = None, None, None

    def show_text(self, path):
        self.stop()
        self.path, self.pixmap = path, None
        try:
            if os.path.getsize(path) > 2_000_000:
                return False
            self.text.setPlainText(core.read_text_file(path))
        except OSError:
            return False
        self.title.setText(os.path.basename(path))
        self.host.hide()
        self.picture.hide()
        self.text.show()
        return True

    def show_picture(self, path):
        self.stop()
        self.path = path
        self.pixmap = QPixmap(path)
        self.title.setText(os.path.basename(path))
        self.host.hide()
        self.text.hide()
        self.picture.show()
        self.fit()
        return not self.pixmap.isNull()

    def fit(self):
        if self.pixmap is not None and not self.pixmap.isNull() and self.picture.isVisible():
            self.picture.setPixmap(self.pixmap.scaled(self.picture.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.fit()

    def play(self, path, launcher):
        self.stop()
        self.path, self.pixmap = path, None
        self.title.setText("▶  " + os.path.basename(path))
        self.picture.hide()
        self.text.hide()
        self.host.show()
        self.proc = launcher(desk.embed_command(path, self.host.winId()))

    def stop(self):
        """Stop what's playing, remembering where it was."""
        proc, self.proc = self.proc, None
        if proc is None:
            return
        if not desk.mpv_quit():
            try:
                proc.terminate()
            except (OSError, AttributeError):
                pass


class NoWheel(QObject):
    """The wheel never changes a drop-down (rolling it over the old Theme box switched the look and saved it): a click
    and a pick do."""

    def eventFilter(self, obj, e):
        return e.type() == e.Type.Wheel


class RowButtons(QWidget):
    """Buttons for the selected (or hovered) row of a long list, floating over the row's right end. One widget
    instead of one per row: building a widget per row took seconds per refresh on a big vault."""

    def __init__(self, lst, make):
        super().__init__(lst.viewport())
        self.lst, self.make, self.item = lst, make, None
        self.lay = QHBoxLayout(self)
        self.lay.setContentsMargins(0, 0, 2, 0)
        self.lay.setSpacing(4)
        self.hide()
        lst.setMouseTracking(True)
        lst.currentItemChanged.connect(lambda cur, _prev: self.show_for(cur))
        lst.itemEntered.connect(self.show_for)
        lst.verticalScrollBar().valueChanged.connect(lambda *_: self.place())

    def show_for(self, item):
        while self.lay.count():
            w = self.lay.takeAt(0).widget()
            if w:
                w.hide()
                w.deleteLater()
        self.item = item
        buttons = self.make(item) if item is not None else []
        if not buttons:
            self.hide()
            return
        for b in buttons:
            self.lay.addWidget(b)
        self.adjustSize()
        self.place()

    def place(self):
        if self.item is None:
            return
        try:
            r = self.lst.visualItemRect(self.item)
        except RuntimeError:  # the list was rebuilt under it
            self.item = None
            self.hide()
            return
        if not r.isValid() or r.height() == 0:
            self.hide()
            return
        h = min(r.height(), self.sizeHint().height())
        self.setGeometry(r.right() - self.sizeHint().width() - 2, r.top() + (r.height() - h) // 2, self.sizeHint().width(), h)
        self.show()
        self.raise_()

    def buttons(self):
        return [self.lay.itemAt(i).widget() for i in range(self.lay.count()) if self.lay.itemAt(i).widget()]


class Card(QWidget):
    """One small card in the corner of the screen, above every window, that never takes the keyboard away:
    the watcher's nudge, welcome back, wrap-up and all-done. A choice or two (or × to close it), then it's gone."""
    STYLE = ("#card { background: #1f1b17; border: 1px solid rgba(227,178,90,0.55); border-radius: 14px; }"
             "#card QLabel { color: #f2ede4; font-size: 14px; background: transparent; }"
             "#card QPushButton { background: rgba(255,248,238,0.06); color: #f2ede4; border: 1px solid rgba(255,248,238,0.18);"
             " border-radius: 10px; padding: 6px 14px; font-weight: 600; }"
             "#card QPushButton:hover { background: rgba(227,178,90,0.18); border-color: #e3b25a; color: #e3b25a; }"
             "#card QPushButton#cardclose { padding: 0; border: none; background: transparent; font-size: 18px;"
             " color: rgba(242,237,228,0.6); }"
             "#card QPushButton#cardclose:hover { color: #e3b25a; background: rgba(227,178,90,0.12); border-radius: 13px; }"
             "#card QLineEdit { background: rgba(255,248,238,0.07); color: #f2ede4; border: 1px solid rgba(255,248,238,0.15);"
             " border-radius: 10px; padding: 6px; }")

    def __init__(self, text, buttons, entry=None, seconds=90):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setObjectName("card")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        if entry is None:
            self.setAttribute(Qt.WA_ShowWithoutActivating, True)  # never steals what you're typing
        self.setStyleSheet(self.STYLE)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        self.label = QLabel(text)
        self.label.setWordWrap(True)
        self.label.setTextFormat(Qt.RichText)
        top = QHBoxLayout()
        top.addWidget(self.label, 1)
        self.close_button = QPushButton("×")  # gone now, without waiting it out
        self.close_button.setObjectName("cardclose")
        self.close_button.setToolTip("Close")
        self.close_button.setCursor(Qt.PointingHandCursor)
        self.close_button.setFixedSize(26, 26)
        self.close_button.clicked.connect(self.close)
        top.addWidget(self.close_button, 0, Qt.AlignTop)
        lay.addLayout(top)
        self.entry = None
        if entry is not None:
            self.entry = QLineEdit()
            self.entry.setPlaceholderText(entry)
            lay.addWidget(self.entry)
        row = QHBoxLayout()
        row.addStretch(1)
        self.buttons = []
        for label, fn in buttons:
            b = QPushButton(label)
            b.clicked.connect(lambda *_, fn=fn: (fn(self), self.close()))
            row.addWidget(b)
            self.buttons.append(b)
        lay.addLayout(row)
        self.setFixedWidth(380)
        self.adjustSize()
        g = QApplication.primaryScreen().availableGeometry()
        self.move(g.right() - self.width() - 24, g.bottom() - self.height() - 24)
        QTimer.singleShot(seconds * 1000, self.close)


class AppVault(devsync.DiskVault):
    """Device sync's view of the vault, with the file work done on the UI thread so a sync can
    never interleave with what is being typed."""

    def __init__(self, window):
        super().__init__(core.VAULT)
        self.w = window

    def snapshot(self):
        def work():
            self.w.autosave()  # what was just typed is part of what gets compared
            return devsync.DiskVault.snapshot(self)
        return self.w.on_ui(work)

    def apply(self, writes, deletes, expect):
        return self.w.on_ui(lambda: self.w.apply_synced(self, writes, deletes, expect))


class SimpleBrain(QMainWindow):
    def __init__(self):
        super().__init__()
        core.ensure_vault()
        core.expand_shorthand_in_vault()  # t/i/c lines typed outside the app
        core.sync_answer_notes()  # catches notes edited outside the app
        self.setWindowTitle(APP_NAME)
        self.setMinimumSize(400, 300)  # small enough to snap to a half or quarter screen; the content scrolls
        self.resize(1500, 950)
        self.current_note = None
        self._disk_text = ""  # the open note as last read from or written to disk
        self.bridge = Bridge()
        self.bridge.ics_fetched.connect(self.on_ics_fetched)
        self.bridge.reco_done.connect(self.on_reco_done)
        self.bridge.update_done.connect(self.on_update_done)
        self.bridge.cite_found.connect(self.on_cite_found)
        self.bridge.sync_status.connect(self.on_sync_status)
        self.bridge.sync_paired.connect(self.on_sync_paired)
        self.bridge.run_ui.connect(self._run_ui)
        self.bridge.publish_done.connect(self.on_publish_done)
        self._publishing, self._publish_again = False, False
        self.tour = None  # the walkthrough overlay while it is showing
        self.sync = None  # the device-sync service; started once a device is paired or Sync… is opened
        self._ics_text, self._ics_fetch_attempted, self._syncing = None, False, False
        self._resync = False  # a Sync/Connect asked for while one was already running
        self._update_pending, self.server = False, None
        self._today_busy, self._today_at = False, 0.0
        self._search_seq = 0  # the newest search; older answers arriving late are dropped
        self.opener = desk.launch  # tests swap this for a recorder
        self._place = None  # (windows before, give up at, rect) while a file opened from a note comes up
        self._place_timer = QTimer(self, interval=200)
        self._place_timer.timeout.connect(self._place_tick)
        self.index = find.FileIndex(cache=os.path.join(core.user_config_dir(), "files.txt"))  # walked on first search

        self.build_menu()
        root = QWidget()
        lay = QVBoxLayout(root)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.addLayout(self.build_capture_bar())

        top = QSplitter(Qt.Horizontal)
        top.addWidget(self.build_notes_sidebar())
        top.addWidget(self.build_editor())
        self.graph = GraphView(self.open_link)
        self.show_all_box = QCheckBox("Show all notes")
        self.show_all_box.setToolTip("Off: only the open note and what is connected to it")
        self.show_all_box.toggled.connect(self.on_show_all)
        graph_box, graph_lay = section("Graph", self.show_all_box,
                                       self._button("Recompute layout", self.graph.recompute),
                                       hint="Shows the open note (ringed) and what is connected to it; click a dot to move there. "
                                            "Scroll to zoom, drag to move around. Hollow dots are links to notes "
                                            "you haven't written yet; click one to create it. "
                                            "Right-click a dot to give it an icon or picture.")
        graph_lay.addWidget(self.graph, 1)
        self.viewer = Viewer(self.close_viewer, self.open_outside)  # pictures and videos open here, in the graph's place
        self.viewer.hide()
        graph_lay.addWidget(self.viewer, 1)
        self.embed_launcher = lambda cmd: __import__("subprocess").Popen(
            cmd, stdout=__import__("subprocess").DEVNULL, stderr=__import__("subprocess").DEVNULL)
        self.graph_box = graph_box
        top.addWidget(graph_box)
        top.setSizes([220, 650, 600])
        lay.addWidget(top, 1)

        # One grid for the four bottom panels: title / hint / controls / list rows
        # are shared, so the lists line up at the same top, height and width.
        self.bottom = QGridLayout()
        self.bottom.setHorizontalSpacing(12)
        self.panels = (self.build_inbox(), self.build_tasks(), self.build_calendar(), self.build_dataview())
        for parts in self.panels:
            for w in parts:
                if w is not None:
                    w.setSizePolicy(QSizePolicy.Ignored, w.sizePolicy().verticalPolicy())
        self.bottom_cols = 0
        self.reflow_bottom()
        lay.addLayout(self.bottom)
        root.setMinimumWidth(600)  # narrower than this the top row is cut off; the window then scrolls
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setObjectName("glassScroll")  # names the Glass theme makes see-through
        root.setObjectName("glassRoot")
        scroll.setWidget(root)
        self.setCentralWidget(scroll)

        self.refresh_notes_list()
        self.refresh_inbox()
        self.refresh_tasks()
        self.refresh_calendar()
        self.refresh_dataview()
        self._today_timer = QTimer(self, interval=30 * 60 * 1000)  # a new day gets a new Today note
        self._today_timer.timeout.connect(self.update_today)
        self._today_timer.start()
        self.open_note("Home.md")
        self.apply_theme()  # Glass needs the panels built
        self.start_recommendations()
        self.start_update_check()
        self.start_watch()
        self.start_drop()
        self.update_money_button()
        QTimer.singleShot(3000, self.sync_web_apps)
        if devsync.paired_devices():
            self.start_sync()

    # -- helpers --
    def _button(self, label, slot):
        b = QPushButton(label)
        b.clicked.connect(lambda *_: slot())
        if label in ("×", "✎"):
            b.setObjectName("iconButton")  # the Glass theme keeps these compact
            b.setFixedWidth(28)
            b.setToolTip("Delete" if label == "×" else "Rename")
        return b

    def _small_button(self, label, slot):
        """Compact button for list rows, so a row fits a narrow panel."""
        b = self._button(label, slot)
        b.setStyleSheet("padding: 1px 6px")
        return b

    def reflow_bottom(self):
        """Four panels across when wide, 2x2 when medium, stacked when narrow. Each panel keeps its
        title / hint / controls / list rows, so the lists still line up within a block of panels."""
        cols = 4 if self.width() >= 1200 else 2 if self.width() >= 760 else 1
        if cols == self.bottom_cols:
            return
        self.bottom_cols = cols
        for r in range(2 * 4 * 4):
            self.bottom.setRowStretch(r, 0)
        for c in range(4):
            self.bottom.setColumnStretch(c, 1 if c < cols else 0)
        for i, parts in enumerate(self.panels):
            parts[-1].setMinimumHeight(220 if cols == 4 else 120)  # reflowed, the lists share a short window
            parts[-1].sizeHint = lambda: QSize(256, 120)  # else the default ~190 px hint beats the minimum
            for row, w in enumerate(parts):
                if w is not None:
                    self.bottom.removeWidget(w)
                    self.bottom.addWidget(w, i // cols * 4 + row, i % cols)
        for block in range(4 // cols):
            self.bottom.setRowStretch(block * 4 + 3, 1)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        gs = getattr(self, "_glass_size", None)
        if gs and not self.styleSheet() == "" and (self.width() > gs.width() or self.height() > gs.height()):
            # grown past the Glass background: make it big enough, so it never repeats
            glass.apply(self, True)
        if hasattr(self, "bottom"):
            self.reflow_bottom()
        if self.tour:
            self.tour.relayout()

    def ask_text(self, title, placeholder, default=""):
        text, ok = QInputDialog.getText(self, title, placeholder, QLineEdit.Normal, default)
        return text if ok else None

    def edit_in_file(self, filename, change):
        """Run a core edit on a note file without the open editor overwriting
        it on the next save: save first, then reload the editor from disk."""
        if filename == self.current_note:
            self.save_current()
        result = change()
        if filename == self.current_note:
            self._disk_text = core.read_note(filename)
            self.editor.setPlainText(self._disk_text)
        return result

    def ask_edited_text(self, title, current):
        """New single-line text, or None if cancelled/blank/unchanged."""
        text = self.ask_text(title, "Text", current)
        text = (text or "").strip()
        return text if text and text != current else None

    def confirm_delete(self, text):
        return QMessageBox.question(
            self, APP_NAME, f"Delete '{text}'?\n\nA copy is kept in the vault's .trash/{core.DELETED_ITEMS}.") \
            == QMessageBox.Yes

    def confirm_past_date(self, d):
        """A past event never shows in the calendar, so saving one silently
        looks like losing it."""
        if d >= date.today():
            return True
        return QMessageBox.question(
            self, APP_NAME, f"{core.show_date(d)} is in the past, so this event won't show in the calendar. "
                            "Save it anyway?") == QMessageBox.Yes

    def read_time(self, s, consequence):
        """The typed time as HH:MM, or None after telling the user why."""
        t = core.parse_time(s)
        if t is None:
            self.show_error(f"'{s}' isn't a time (e.g. 14:30 or 2:30pm): {consequence}")
        return t

    def read_date(self, s, consequence):
        """The typed date (fri, nov 5, MM-DD-YYYY…), or None after telling the user why."""
        d = core.parse_date(s)
        if d is None:
            self.show_error(f"'{s}' isn't a date (try fri, tomorrow, nov 5 or MM-DD-YYYY): {consequence}")
        return d

    STALE_MSG = "That item changed on disk since the list was shown. The list is refreshed; nothing was overwritten."

    def show_error(self, message):
        QMessageBox.critical(self, APP_NAME, message)

    # -- menu --
    def build_menu(self):
        m = self.menuBar()
        file_menu = self.file_menu = m.addMenu("&File")
        for label, slot, key in (("New &Learning Note", self.on_new_learning_note, QKeySequence.New),
                                 ("New &Blank Note", self.on_new_blank_note, None),
                                 ("&Save", self.save_current, QKeySequence.Save),
                                 ("Open vault &folder", self.open_vault_folder, None),
                                 ("&Quit", self.close, QKeySequence.Quit)):
            act = QAction(label, self)
            if key is not None:
                act.setShortcut(key)
            act.triggered.connect(lambda *_, s=slot: s())
            file_menu.addAction(act)
        file_menu.insertAction(file_menu.actions()[-1], self._recommendations_action())
        web = QAction("&Website (connect yours)…", self)
        web.triggered.connect(lambda *_: self.on_website_setup())
        file_menu.insertAction(file_menu.actions()[-1], web)
        broken = QAction("Broken &links…", self)
        broken.triggered.connect(lambda *_: self.on_broken_links())
        file_menu.insertAction(file_menu.actions()[-1], broken)
        mail_act = QAction("&Email (connect yours)…", self)
        mail_act.triggered.connect(lambda *_: self.on_mail_setup())
        file_menu.insertAction(file_menu.actions()[-1], mail_act)
        money_act = QAction("&Money, forward…", self)
        money_act.triggered.connect(lambda *_: self.open_money())
        file_menu.insertAction(file_menu.actions()[0], money_act)
        today_act = QAction("&Today", self)
        today_act.triggered.connect(lambda *_: self.open_today())
        file_menu.insertAction(file_menu.actions()[0], today_act)
        help_menu = m.addMenu("&Help")
        help_menu.addAction("Take the &tour").triggered.connect(lambda *_: self.start_tour())
        help_menu.addAction("&About SimpleBrain").triggered.connect(lambda *_: self.show_about())

    def _recommendations_action(self):
        act = QAction("Book &recommendations (uses Open Library)", self)
        act.setCheckable(True)
        act.setChecked(core.load_settings().get("recommendations") == "on")
        act.toggled.connect(self.on_toggle_recommendations)
        self.recommendations_action = act
        return act

    def apply_theme(self, mode="glass"):
        """One look: Glass (warm dark, one gold accent). There is no theme to pick, so nothing can switch it."""
        QApplication.styleHints().setColorScheme(Qt.ColorScheme.Dark)
        if hasattr(self, "links"):  # the first call comes before the panels exist; __init__ calls again
            glass.apply(self, True)

    def on_show_all(self, on):
        self.graph.show_all = on
        self.graph.recompute()

    def open_vault_folder(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(core.VAULT))

    def show_about(self):
        QMessageBox.about(self, f"About {APP_NAME}",
                          f"<b>{APP_NAME} {core.VERSION}</b><br>Notes, tasks, calendar and graph.<br><br>"
                          f"Updates: {html.escape(getattr(self, 'update_state', 'Not checked yet'))}<br>"
                          f"Your notes: {html.escape(core.VAULT)}")

    # -- capture bar --
    def build_capture_bar(self):
        row = QHBoxLayout()
        row.addWidget(QLabel("Capture:"))
        self.capture = QLineEdit()
        self.capture.setPlaceholderText("Find or open anything · type a thought and press Enter · "
                                        "t call the bank fri · c tomorrow 2pm dentist")
        self.capture.returnPressed.connect(self.on_capture)
        row.addWidget(self.capture, 1)
        # Search as you type: the results float under the bar; Enter opens the highlighted one, and the last
        # row is always "capture this", so a thought still goes to the Inbox the way it always did.
        self.results = QListWidget(self)
        self.results.setObjectName("results")
        self.results.hide()
        self.results.itemActivated.connect(lambda it: self.on_result(self.results.row(it)))
        self.results.itemClicked.connect(lambda it: self.on_result(self.results.row(it)))
        self._hits = []
        self._search_timer = QTimer(self, singleShot=True, interval=140)
        self._search_timer.timeout.connect(self.run_search)
        self.capture.textEdited.connect(lambda *_: self._search_timer.start())
        self.capture.installEventFilter(self)
        self.watch_label = QLabel()  # computer time left (simplebrain_watch); hidden without a limit:: line
        self.watch_label.setObjectName("watchLine")
        self.watch_label.setToolTip("Computer time left today, from the 'limit:: 3h' or 'limit:: until 9pm' line in Home.")
        self.watch_label.hide()
        row.addWidget(self.watch_label)
        self.drop_button = self._button("⇣ Drop", self.open_drop_folder)
        self.drop_button.setObjectName("dropButton")
        self.drop_button.setToolTip("Drop files or folders anywhere on this window (or into the Drop folder this opens): "
                                    "each one is filed into your Projects, Areas or Resources folder and linked from "
                                    "its note. Drop on the open note to file it with that note.")
        row.addWidget(self.drop_button)
        self.money_button = self._button("Money", self.open_money)
        self.money_button.setObjectName("moneyButton")
        self.money_button.setToolTip("Money, forward: how far your money lasts, what you end with, and which goals are "
                                     "funded. Comes from your Budget note.")
        row.addWidget(self.money_button)
        self.mail_button = self._button("Mail", self.open_mail)
        self.mail_button.setObjectName("mailButton")
        self.mail_button.setToolTip("Your email, right here: read, reply, archive, delete, or make a task or event "
                                    "from it. No browser, no sign-in.")
        row.addWidget(self.mail_button)
        self.cal_button = self._button("Calendar", self.open_calendar_window)
        self.cal_button.setObjectName("calButton")
        self.cal_button.setToolTip("Your whole calendar: any day or month, and add, change or delete any event, "
                                   "the ones made on your phone or in your email account too.")
        row.addWidget(self.cal_button)
        self.how_button = self._button("How to", self.start_tour)
        self.how_button.setToolTip("The tutorial again: every part of SimpleBrain, one real thing to do at each step")
        row.addWidget(self.how_button)
        self.folder_label = QLabel()
        row.addWidget(self.folder_label)
        self.sync_label = QLabel("Sync: off")
        row.addWidget(self.sync_label)
        row.addWidget(self._button("Sync…", self.on_sync_dialog))
        row.addWidget(self._button("Change notes folder…", self.on_change_folder))
        self.update_folder_label()
        self._no_wheel = NoWheel(self)
        self.apply_theme()
        return row

    def update_folder_label(self):
        self.folder_label.setText(f"Notes: <b>{html.escape(os.path.basename(core.VAULT) or core.VAULT)}</b>")
        self.folder_label.setToolTip(core.VAULT)

    def on_change_folder(self):
        path = QFileDialog.getExistingDirectory(self, "Choose your notes folder", core.VAULT)
        if path:
            self.switch_vault(path)

    def switch_vault(self, path):
        """Move the whole app to another notes folder: notes, tasks, inbox, calendar settings and
        recommendations all live inside it, so they come along. An empty folder can be filled with a
        copy of the current notes (the originals stay where they were)."""
        path, old = os.path.abspath(path), core.VAULT
        if os.path.normcase(path) == os.path.normcase(old):
            return
        self.save_current()
        try:
            os.makedirs(path, exist_ok=True)
            empty = not any(f.endswith(".md") for f in os.listdir(path))
            if empty and core.list_user_notes(old) and QMessageBox.question(
                    self, APP_NAME, "That folder has no notes yet.\n\nCopy your current notes into it? "
                                    "The originals stay where they are.") == QMessageBox.Yes:
                core.copy_vault(old, path)
            core.set_vault(path)
        except OSError as e:
            self.show_error(f"Couldn't use that folder: {e}")
            return
        self.reload_everything()

    def reload_everything(self):
        """Redraw every panel from the (new) vault without writing the old note into it."""
        self.current_note = None
        self._ics_text, self._ics_fetch_attempted = None, False
        core.expand_shorthand_in_vault()
        core.sync_answer_notes()
        if self.sync:
            self.sync.vault_obj = AppVault(self)
        self.update_folder_label()
        self.refresh_notes_list()
        self.refresh_inbox()
        self.refresh_tasks()
        self.refresh_calendar()
        self.refresh_dataview()
        self.graph.center = "Home.md"
        self.graph.recompute()
        self.open_note("Home.md")
        self.start_recommendations()

    # -- recommendations (background; see simplebrain_recommend) --
    def on_toggle_recommendations(self, on):
        self.save_setting("recommendations", "on" if on else "off")
        if on:
            self.start_recommendations()

    def save_setting(self, key, value):
        try:
            data = core.load_settings()
            data[key] = value
            core.save_settings(data)
        except OSError:  # read-only drive: the choice just isn't remembered
            pass

    def start_recommendations(self):
        """Rebuild Recommendations.md off the UI thread. Nothing happens (and nothing is sent) until
        the vault holds a book note and the user has said yes once."""
        vault = core.VAULT
        if not reco.books(vault):
            return
        setting = core.load_settings().get("recommendations")
        if setting is None:
            yes = QMessageBox.question(
                self, APP_NAME,
                "SimpleBrain can suggest books based on the keywords in your Learning notes.\n\n"
                "It sends only those keywords, one at a time, to openlibrary.org (a free public library "
                "catalog). Your notes and titles are never sent.\n\nTurn book recommendations on?"
            ) == QMessageBox.Yes
            setting = "on" if yes else "off"
            self.save_setting("recommendations", setting)
            self.recommendations_action.blockSignals(True)
            self.recommendations_action.setChecked(yes)
            self.recommendations_action.blockSignals(False)
        if setting != "on":
            return

        def work():
            try:
                result = reco.refresh(vault)
            except Exception as e:  # never let the helper take the app down
                result = f"error: {e}"
            self.bridge.reco_done.emit(vault, result)
        threading.Thread(target=work, daemon=True).start()

    def on_reco_done(self, vault, result):
        if vault != core.VAULT or not (result.startswith("ok") or result == "failed"):
            return  # switched folders meanwhile, or nothing changed on disk
        self.refresh_notes_list()
        self.graph.recompute()
        self.refresh_dataview()
        if self.current_note == reco.OUT_NAME and os.path.exists(os.path.join(core.VAULT, reco.OUT_NAME)):
            self._disk_text = core.read_note(reco.OUT_NAME)
            self.editor.setPlainText(self._disk_text)  # generated note: no edits to lose

    # -- updates install themselves (simplebrain_update): no question, no click --
    def start_update_check(self):
        """At start and every few hours: a git checkout fast-forwards to GitHub when nothing of yours is in
        the way; an installed copy (AppImage, install.sh, Windows installer, Mac app) downloads the newest
        release, checks it, and puts it in place. Either way it then restarts itself the next time you're
        not using the window. No question, no click; Help > About says where things stand."""
        if not hasattr(self, "_update_timer"):
            self._update_timer = QTimer(self, interval=updater.CHECK_EVERY_MIN * 60 * 1000)
            self._update_timer.timeout.connect(self.start_update_check)
            self._update_timer.start()
            self._staged = None  # (kind, file) of a Windows/Mac update waiting for the restart
            self.update_state = "Not checked yet"
        repo = updater.checkout_dir(__file__)
        kind = None if repo else updater.install_kind()
        if os.environ.get("SIMPLEBRAIN_NO_UPDATE"):
            self.update_state = "Updates are off (SIMPLEBRAIN_NO_UPDATE)"
            return
        if not (repo or kind):
            self.update_state = ("A copy on a drive: replace it with the newest download to update"
                                 if getattr(sys, "frozen", False) else "Run from a folder without git: updates are off")
            return
        if self._update_pending:
            return
        self.save_current()  # what's typed is on disk before any file changes under it
        say = lambda text: self.bridge.run_ui.emit((lambda: setattr(self, "update_state", text), {"done": threading.Event()}))

        def work():
            stamp = datetime.now().strftime("%I:%M %p").lstrip("0")
            if repo:
                state, changed = updater.git_update(repo)
                if state != "updated":
                    say({"current": f"Up to date (checked {stamp})", "offline": "Couldn't check for a newer version; it tries again later"}
                        .get(state, f"Not updated: {state} in the code folder"))
                    return
                cmd = updater.pip_command(repo, changed)
                if cmd:
                    import subprocess
                    try:
                        subprocess.run(cmd, capture_output=True, timeout=1800)
                    except (OSError, subprocess.SubprocessError):
                        pass  # the restart still runs the new code; a missing package shows as an error there
                self.bridge.update_done.emit("")
                return
            info = updater.release_info()
            if not info:
                say("Couldn't check for a newer version; it tries again later")
                return
            if not core.update_available(info["tag"]):
                say(f"Up to date (checked {stamp})")
                return
            try:
                staged = updater.stage_update(info, kind, updater.staging_dir())
                if not updater.apply_now(kind, staged):
                    self._staged = (kind, staged)
            except (OSError, ValueError) as e:
                self.bridge.update_done.emit(str(e))
                return
            say(f"{info['tag']} is ready; it starts the next time you step away")
            self.bridge.update_done.emit("")
        threading.Thread(target=work, daemon=True).start()

    def on_update_done(self, error):
        if error:
            self.update_state = f"Update not installed ({error}); it tries again later"
            self.save_status.setText(f"Update not installed ({html.escape(error)}); you're still on {core.VERSION}.")
            return
        self._update_pending = True
        self.save_status.setText("SimpleBrain was updated. It restarts itself the next time you step away from it.")
        if os.environ.get("SIMPLEBRAIN_DEV"):
            return  # dev.sh restarts it on the changed files by itself
        self._restart_timer = QTimer(self, interval=30000)
        self._restart_timer.timeout.connect(self.restart_if_idle)
        self._restart_timer.start()

    def restart_if_idle(self):
        """Restart into the new version once you've stepped away: two minutes without a key or a click."""
        idle = watch.idle_seconds()  # 0 when this desktop can't tell: then a window you're not in counts as away
        if not (idle >= 120 or (idle == 0 and not self.isActiveWindow())):
            return
        self.save_current()
        if self.sync:
            self.sync.stop()
        if self.server:
            self.server.close()
        args = [a for a in sys.argv[1:]]
        staged = getattr(self, "_staged", None)
        if staged:  # Windows / macOS: a helper swaps the program in once this one has quit, then starts it
            import subprocess
            exe = os.path.abspath(sys.executable)
            app_path = exe if staged[0] == "windows" else exe[:exe.find(".app") + 4]
            cmd = updater.restart_command(staged[0], staged[1], app_path, args)
            flags = {"creationflags": 0x00000008 | 0x00000200} if os.name == "nt" else {"start_new_session": True}
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **flags)
            os._exit(0)
        if os.environ.get("APPIMAGE"):  # the new AppImage file, not the old one still mounted
            os.execv(os.environ["APPIMAGE"], [os.environ["APPIMAGE"], *args])
        exe = sys.executable
        args = args if getattr(sys, "frozen", False) else [os.path.abspath(__file__), *args]
        os.execv(exe, [exe, *args])

    def on_cite(self):
        query = self.ask_text("Cite source", "Article or book title, or a web address:")
        if not query or not query.strip():
            return
        self.save_status.setText("Looking up source…")

        def work():
            try:
                self.bridge.cite_found.emit(core.find_sources(query), "")
            except ValueError as e:
                self.bridge.cite_found.emit([], str(e))
        threading.Thread(target=work, daemon=True).start()

    def on_cite_found(self, refs, error):
        self.save_status.setText("")
        if error:
            QMessageBox.warning(self, APP_NAME, error)
            return
        if len(refs) > 1:  # a title can match several works: the user picks, never a silent guess
            ref, ok = QInputDialog.getItem(self, "Cite source", "Which one?", refs, 0, False)
            if not ok:
                return
        else:
            ref = refs[0]
        self.editor.textCursor().insertText(ref)  # at the cursor, where the user was writing

    # -- the watcher (simplebrain_watch): drift, time left, the day's three, the score --
    def start_watch(self):
        self.watch_state = {"day": {**watch.load_day(date.today()), "date": date.today().isoformat()}}
        self.cards = []  # the cards showing, so a second nudge never stacks on the first
        self._watch_busy = False
        self._watch_timer = QTimer(self, interval=watch.TICK_S * 1000)
        self._watch_timer.timeout.connect(self.watch_tick)
        if not os.environ.get("SIMPLEBRAIN_NO_WATCH"):
            self._watch_timer.start()
        self.show_watch_line()

    def watch_tick(self):
        """Read the screen off the UI thread (an X call that hangs must never freeze the window)."""
        if self._watch_busy:
            return
        self._watch_busy = True

        def work():
            try:
                title, idle = watch.active_title(), watch.idle_seconds()
            except Exception:  # never let the watcher take the app down
                title, idle = "", 0
            self.bridge.run_ui.emit((lambda: self.on_watch(title, idle), {"done": threading.Event()}))
        threading.Thread(target=work, daemon=True).start()

    def today_words(self):
        items = today_note.today_items()
        return set().union(*(today_note.words(core.DUE_RE.sub("", t["text"])) for t in items)) if items else set()

    def on_watch(self, title, idle, now=None):
        self._watch_busy = False
        now = now or datetime.now()
        st = self.watch_state
        if st["day"].get("date") != now.date().isoformat():  # a new day starts a new log
            st.clear()
            st["day"] = {**watch.load_day(now.date()), "date": now.date().isoformat()}
        try:
            quiet = watch.in_shift(core.read_local_events(), now)
            used = st["day"].get("focus", 0) + st["day"].get("drift", 0)
            left = watch.limit_seconds(now=now, used_s=used)
            st, event = watch.tick(st, title, idle, now, self.today_words(), watch.home_words(), quiet, left)
            watch.save_day(now.date(), st["day"])
        except OSError:
            return
        self.show_watch_line(left)
        if event:
            self.watch_event(event, title)
        elif not quiet:
            self.follow_up(now)
            self.check_mail(now)

    def follow_up(self, now=None):
        """An hour after an event with someone ([[Dad]] in its title): how did it go? One line, dated, into their note."""
        day = self.watch_state["day"]
        try:
            ups = workday.follow_ups(now=now, asked=day.get("asked", []))
        except (OSError, ValueError):
            return
        if not ups or any(c.isVisible() for c in self.cards if not self._card_gone(c)):
            return
        up = ups[0]
        day.setdefault("asked", []).append(up["key"])

        def save(c, note=up["note"]):
            if c.entry.text().strip():
                self.edit_in_file(note + ".md", lambda: workday.log_contact(note, c.entry.text()))
                self.save_status.setText(f"Saved to {html.escape(note)}: it counts as your last check-in.")
        self.card(f"<b>How did it go?</b><br>{html.escape(up['title'])}", [("Save to their note", save)],
                  entry="one line: what you talked about, what's next", seconds=900)

    @staticmethod
    def _card_gone(c):
        try:
            c.isVisible()
            return False
        except RuntimeError:  # closed and deleted
            return True

    def show_watch_line(self, left=False):
        """Time left from a limit:: line (the x/3 done count went: it read as a puzzle). Redraws keep the last reading."""
        if left is not False:
            self._time_left = left
        left = getattr(self, "_time_left", None)
        parts = []
        if left is not None:
            parts.append(f"⏱ {watch.mins(left)} left")
        self.watch_label.setText("  ·  ".join(parts))
        self.watch_label.setVisible(bool(parts))

    def card(self, text, buttons, entry=None, seconds=90):
        if entry is None and any(c.entry is not None and c.isVisible() for c in self.cards if not self._card_gone(c)):
            return None  # a card asking you to write something is never covered by a nudge
        for c in self.cards:
            try:
                c.close()
            except RuntimeError:
                pass
        c = Card(text, buttons, entry, seconds)
        self.cards = [c]
        c.show()
        return c

    def first_thing(self):
        items = today_note.today_items()
        return core.REPEAT_RE.sub("", core.DUE_RE.sub("", items[0]["text"])).strip() if items else None

    def watch_event(self, event, title=""):
        if event in ("nudge", "welcome", "stretch") and watch.nudges_off():
            return  # `nudges:: off` in Home: no drift, welcome-back or stand-up cards
        first = self.first_thing()
        day = self.watch_state["day"]
        if event == "nudge":
            where = html.escape(watch.drift_label(title, watch.home_words()))
            self.card(f"<b>Ten minutes on {where}.</b>" + (f"<br>Up first today: {html.escape(first)}" if first else ""),
                      [("Taking a break", lambda c: watch.snooze(self.watch_state, datetime.now())),
                       ("Back to it", lambda c: self.back_to_it())])
        elif event == "welcome" and first and os.path.exists(os.path.join(core.VAULT, today_note.note_name())):
            self.back_to_it()
            self.card(f"<b>Welcome back.</b><br>Up first: {html.escape(first)}", [("OK", lambda c: None)], seconds=20)
        elif event == "wrap_up":
            self.save_current()
            self.card("<b>10 minutes of computer time left.</b> Everything is saved.<br>"
                      f"{watch.score_line(day, day.get('three'), day.get('done'))}<br><br>Where did you stop? "
                      "Tomorrow's Today opens with it.",
                      [("Save for tomorrow", lambda c: c.entry.text().strip() and watch.park(c.entry.text()))],
                      entry="e.g. Study Group lesson 3, stopped at lists", seconds=600)
        elif event == "stretch":
            self.card("<b>90 minutes straight.</b><br>Stand up, drink some water, look out a window for five minutes. "
                      "Everything is saved.", [("Back in 5", lambda c: watch.snooze(self.watch_state, datetime.now(), 300))],
                      seconds=120)
        elif event == "all_done":
            self.card("<b>All three done.</b><br>The rest of the day is yours.", [("Nice", lambda c: None)], seconds=30)

    def back_to_it(self):
        """'Back to it': SimpleBrain up on Today with the first thing's file or card open beside it."""
        self.handle_command("show")
        self.open_today()
        first = today_note.first_material()
        if first:
            self.open_beside(first)

    def check_three(self):
        """The supervisor's part: the day's three things are fixed at the first Today of the day; each one that's
        no longer open counts as done (ticked here, or marked Done in the plan workbook)."""
        day = self.watch_state["day"]
        try:
            plan = today_note.plan_path() or ""
            if not day.get("three") or day.get("plan", plan) != plan:  # the plan turned off or moved: its actions
                day["three"] = [t["text"] for t in today_note.today_items()]  # left the list, they weren't done
                day["plan"], day["done"] = plan, []
            if not day["three"]:
                return
            before = len(day.get("done", []))
            day["done"] = watch.done_of_three(day["three"], today_note.open_texts(), day.get("ticked_texts", []))
            watch.save_day(date.fromisoformat(day["date"]), day)
        except (OSError, ValueError):
            return
        self.show_watch_line()
        if len(day["done"]) == len(day["three"]) > before:  # no count on the way: the tick itself says done
            self.watch_event("all_done")

    # -- money, forward (simplebrain_budget + simplebrain_money) --
    def budget_now(self):
        return budget.load(plan=today_note.plan_path())

    def update_money_button(self):
        if not os.path.exists(os.path.join(core.VAULT, budget.NOTE)):
            self.money_button.setText("Money")
            return
        try:
            p = budget.project(self.budget_now())
        except (OSError, ValueError):
            return
        self.money_button.setIcon(money.ring_icon(budget.runway(p)))
        self.money_button.setText(budget.money(p["end"]))
        self.money_button.setToolTip(budget.summary(p) + "\nClick for the whole picture.")

    def open_money(self):
        self.save_current()
        made = not os.path.exists(os.path.join(core.VAULT, budget.NOTE))
        budget.ensure_note()
        if made:
            self.refresh_notes_list()
        b = self.budget_now()
        p = budget.project(b)
        seen = core.load_settings().get("money_seen")
        delta = round(p["end"] - seen, 2) if isinstance(seen, (int, float)) and abs(p["end"] - seen) >= 1 else None
        self.save_setting("money_seen", p["end"])
        self.learned("money")
        self.money_window = money.MoneyWindow(self, self.open_note)
        self.money_window.show_budget(b, delta)
        self.money_window.show()
        self.update_money_button()
        return self.money_window

    # -- your accounts as apps (simplebrain_desk) and mail that needs you (simplebrain_mail) --
    def web_apps(self):
        texts = []
        for n in (*core.SETTINGS_NOTES, "Apps.md"):
            if os.path.exists(os.path.join(core.VAULT, n)):
                texts.append(core.read_note(n))
        return desk.web_apps(texts)

    def web_profile(self):
        return os.path.join(core.user_config_dir(), "web")  # one sign-in for every app window, kept between restarts

    def open_web_app(self, name, url):
        """The account in its own window; if it's already open, brought up instead of a second copy."""
        habits.record("url", name, url)
        open_ = [w for w, t in desk.windows().items() if name.lower() in t.lower()]
        if open_:
            desk.activate(open_[0])
            return
        cmd = desk.webapp_command(url, self.web_profile())
        if cmd:
            self.opener(cmd)
        else:
            QDesktopServices.openUrl(QUrl(url))

    def sync_web_apps(self):
        if sys.platform.startswith("linux") and not os.environ.get("SIMPLEBRAIN_NO_MENU"):
            try:
                desk.sync_launchers(self.web_apps(), self.web_profile())
            except OSError:
                pass

    def on_mail_setup(self):
        """Any email service, in steps (simplebrain_setup): once connected, the digest comes twice a day by itself."""
        dlg = setup.EmailSetup(self)
        if dlg.exec() != QDialog.Accepted:
            return
        self.save_status.setText(html.escape(dlg.result_line))
        if getattr(self, "mail_window", None) is not None:
            self.mail_window.account = None  # the next action logs in with the new setup
        if dlg.saved:
            self.check_mail(force=True)

    def check_mail(self, now=None, force=False):
        cfg = mail.load_config()
        if not cfg or getattr(self, "_mail_busy", False):
            return
        last, _ = mail.last_digest()
        if not force and not mail.due(now, last):
            return
        self._mail_busy = True
        vip = mail.important()

        def work():
            try:
                items = mail.lines(mail.needs_you(mail.fetch_any(cfg), vip))
                err = ""
            except (OSError, ValueError, KeyError, IndexError) as e:
                items, err = [], str(e)
            self.bridge.run_ui.emit((lambda: self.on_mail(items, err), {"done": threading.Event()}))
        threading.Thread(target=work, daemon=True).start()

    def open_calendar_window(self):
        """The whole calendar in its own SimpleBrain window (simplebrain_calwin)."""
        w = getattr(self, "cal_window", None)
        if w is None or not w.isVisible():
            self.cal_window = w = calwin.CalendarWindow(self)
        else:
            w.load()
        w.show()
        w.raise_()
        w.activateWindow()
        return w

    def open_mail(self):
        """Mail in its own SimpleBrain window (simplebrain_mailwin): no browser, no web mail."""
        w = getattr(self, "mail_window", None)
        if w is None or not w.isVisible():
            self.mail_window = w = mailwin.MailWindow(self)
        else:
            w.refresh()
        w.show()
        w.raise_()
        w.activateWindow()
        return w

    def on_mail(self, items, err=""):
        self._mail_busy = False
        if err:
            self.save_status.setText(f"Email digest: couldn't reach your email ({html.escape(err[:80])}). It tries again later.")
            return
        mail.save_digest(items)
        self.update_today()
        self.card("<b>Mail that needs you</b><br>" + ("<br>".join(html.escape(x) for x in items) if items
                                                      else "Nothing. Your inbox can wait."),
                  [("Open mail", lambda c: self.open_mail())] if items else [("Good", lambda c: None)], seconds=60)

    # -- drop it and it's filed (simplebrain_drop): PARA folders, linked from notes, Undo --
    def start_drop(self):
        self.setAcceptDrops(True)
        self.editor.viewport().installEventFilter(self)  # a drop on the open note files it with that note
        self.drop_overlay = QLabel("Drop to file it\nProjects · Areas · Resources", self)
        self.drop_overlay.setObjectName("dropOverlay")
        self.drop_overlay.setAlignment(Qt.AlignCenter)
        self.drop_overlay.setStyleSheet("#dropOverlay { background: rgba(8,14,20,0.82); color: #e6eef5; font-size: 26px;"
                                        " font-weight: 600; border: 2px dashed #78c8eb; border-radius: 18px; }")
        self.drop_overlay.hide()
        self._drop_watch = None
        self._drop_timer = QTimer(self, singleShot=True, interval=3000)  # a copy into Drop finishes first
        self._drop_timer.timeout.connect(self.file_drop_folder)
        try:  # no folders are made at start: Drop and the PARA folders appear the first time they're used
            self.para, self.para_yours = drop.para_root(create=False)
        except OSError:
            self.para = None
            return
        self._watch_drop()
        if drop.downloads_on(was_yours=self.para_yours) and core.load_settings().get("downloads_filed") != date.today().isoformat():
            QTimer.singleShot(60000, self.file_downloads)  # once a day, after start-up has settled

    def _watch_drop(self):
        """Watch the Drop folder once it exists (the system tells us; nothing polls)."""
        folder = os.path.join(self.para, drop.DROP) if self.para else ""
        if self._drop_watch is None and os.path.isdir(folder):
            from PySide6.QtCore import QFileSystemWatcher
            self._drop_watch = QFileSystemWatcher([folder], self)
            self._drop_watch.directoryChanged.connect(lambda *_: self._drop_timer.start())
            QTimer.singleShot(5000, self.file_drop_folder)  # what landed there while SimpleBrain was closed

    def open_drop_folder(self):
        if self.para:
            QDesktopServices.openUrl(QUrl.fromLocalFile(drop.drop_dir(self.para)))
            self._watch_drop()

    def file_paths(self, paths, note=None, quiet=False):
        """File these off the UI thread (a folder onto another drive takes a while), then say where each went.
        A dropped Markdown file also becomes a note (unless you have one by that name: yours is never replaced)."""
        if not self.para or not paths:
            return
        self.save_current()
        if not quiet:
            added = self.add_dropped_notes(paths)
            if added:
                self.refresh_notes_list()
                self.refresh_tasks()
                self.refresh_calendar()
                self.graph.recompute()
                self.update_money_button()
                self.sync_web_apps()
                self.save_status.setText("New notes: " + html.escape(", ".join(added)))

        def work():
            try:
                done = drop.file_all(paths, self.para, note=note)
            except OSError as e:
                why = str(e)  # `e` is gone once the except block ends; the lambda runs later on the UI thread
                self.bridge.run_ui.emit((lambda: self.save_status.setText(f"Couldn't file that: {html.escape(why)}"),
                                         {"done": threading.Event()}))
                return
            self.bridge.run_ui.emit((lambda: self.on_filed(done, quiet), {"done": threading.Event()}))
        threading.Thread(target=work, daemon=True).start()

    def add_dropped_notes(self, paths):
        added = []
        for p in paths:
            try:  # a file can be gone a moment later (moved by its own program, or filed already)
                if not p.lower().endswith(".md") or not os.path.isfile(p) or os.path.getsize(p) > 2_000_000:
                    continue
            except OSError:
                continue
            title = os.path.splitext(os.path.basename(p))[0]
            if not core.is_safe_note_title(title) or os.path.exists(os.path.join(core.VAULT, title + ".md")):
                continue
            try:
                core.write_note_with_shorthand(title + ".md", core.read_text_file(p))
            except (OSError, ValueError):
                continue
            added.append(title)
        return added

    def on_filed(self, done, quiet=False):
        if not done:
            return
        if not quiet:
            self.learned("drop")
        sheets = [e["to"] for e in done if budget.is_budget_file(e["to"]) and not quiet]
        if sheets:  # a bank export or the plan workbook: today's cash comes from it, where it now lives
            try:
                budget.link_file(sheets[0])
                self.refresh_notes_list()
                self.update_money_button()
            except OSError:
                pass
        if self.current_note and any(e.get("note") and e["note"] + ".md" == self.current_note for e in done):
            self.reconcile_outside()  # its new file:: line shows at once
        self.render_links()
        rel = lambda p: os.path.relpath(os.path.dirname(p), self.para)
        lines = "<br>".join(f"{html.escape(os.path.basename(e['to']))} → <b>{html.escape(rel(e['to']))}</b>"
                            + (f" · linked from [[{html.escape(e['note'])}]]" if e.get("note") else "") for e in done[:5])
        more = f"<br>…and {len(done) - 5} more" if len(done) > 5 else ""
        msg = f"Filed {len(done)}: " + ", ".join(os.path.basename(e["to"]) for e in done[:3])
        self.save_status.setText(html.escape(msg))
        if quiet:
            return
        self.card(f"<b>Filed {len(done)}</b><br>{lines}{more}",
                  [("Undo", lambda c, d=done: self.undo_filed(d)),
                   ("Open folder", lambda c, d=done: QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(d[0]["to"]))))],
                  seconds=25)

    def undo_filed(self, done):
        n = drop.undo(done)
        self.reconcile_outside()
        self.render_links()
        self.save_status.setText(f"Put {n} back where {'it was' if n == 1 else 'they were'}.")

    def file_drop_folder(self):
        if self.para and os.path.isdir(os.path.join(self.para, drop.DROP)):
            self.file_paths(drop.drop_folder_items(self.para))

    def file_downloads(self):
        self.save_setting("downloads_filed", date.today().isoformat())
        self.file_paths(drop.settled_downloads(), quiet=True)

    def _local_paths(self, e):
        md = e.mimeData()
        return [u.toLocalFile() for u in md.urls() if u.isLocalFile() and u.toLocalFile()] if md.hasUrls() else []

    def dragEnterEvent(self, e):
        if self._local_paths(e) and self.para:
            e.acceptProposedAction()
            self.drop_overlay.setGeometry(self.rect().adjusted(40, 60, -40, -40))
            self.drop_overlay.show()
            self.drop_overlay.raise_()

    def dragLeaveEvent(self, e):
        self.drop_overlay.hide()

    def dropEvent(self, e):
        self.drop_overlay.hide()
        paths = self._local_paths(e)
        if paths:
            e.acceptProposedAction()
            self.file_paths(paths)

    # -- find anything (simplebrain_find) --
    KIND_MARK = {"webapp": "◈  ", "window": "▣  ", "note": "✎  ", "app": "◆  ", "file": "▤  ", "web": "↗  ", "capture": "＋  "}

    def run_search(self):
        text = self.capture.text().strip()
        if not self.is_search(text):
            self.results.hide()  # a 't …' / 'c …' / 'i …' line is a capture, not a search
            return
        self._search_seq += 1
        seq, vault, index = self._search_seq, core.VAULT, self.index.ensure()

        def work():
            try:
                hits = find.search(text, vault, index=index, limit=7, habits=habits.boost())
            except Exception:
                hits = []
            self.bridge.run_ui.emit((lambda: self.show_results(seq, text, hits), {"done": threading.Event()}))
        threading.Thread(target=work, daemon=True).start()

    def show_results(self, seq, text, hits):
        """The search thread's answer; a stale one (the text changed meanwhile) is dropped."""
        if seq != self._search_seq or text != self.capture.text().strip():
            return
        self._hits_text = text
        q = text.lower()
        apps = [("webapp", name, "your account, its own window", url) for name, url in self.web_apps()
                if q in name.lower() or q in url.lower()][:3]
        self._hits = apps + hits + [("web", f"Search the web for “{text}”", "new browser window",
                        "https://duckduckgo.com/?q=" + QUrl.toPercentEncoding(text).data().decode()),
                       ("capture", f"Capture “{text}”", "to the Inbox", text)]
        self.results.clear()
        for kind, label, detail, _ in self._hits:
            it = QListWidgetItem(f"{self.KIND_MARK[kind]}{label}" + (f"      {detail}" if detail else ""))
            it.setToolTip(detail)
            self.results.addItem(it)
        self.results.setCurrentRow(0)
        top_left = self.capture.mapTo(self, self.capture.rect().bottomLeft())
        h = min(len(self._hits), 9) * (self.results.sizeHintForRow(0) + 2) + 10
        self.results.setGeometry(top_left.x(), top_left.y() + 4, self.capture.width(), h)
        self.results.show()
        self.results.raise_()

    def is_search(self, text):
        return len(text) >= 2 and not core.SHORTHAND_RE.match(text) and not text.startswith("t ")

    def eventFilter(self, obj, e):
        if hasattr(self, "link_popup") and obj is self.editor and e.type() == e.Type.KeyPress and self.link_popup.isVisible():
            k = e.key()
            if k in (Qt.Key_Down, Qt.Key_Up):
                self.link_popup.setCurrentRow(max(0, min(self.link_popup.count() - 1,
                                                         self.link_popup.currentRow() + (1 if k == Qt.Key_Down else -1))))
                return True
            if k in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Tab):
                self.accept_link(self.link_popup.currentItem().text())
                return True
            if k == Qt.Key_Escape:
                self.link_popup.hide()
                return True
        if hasattr(self, "editor") and obj is self.editor.viewport() and e.type() in (e.Type.DragEnter, e.Type.DragMove, e.Type.Drop):
            paths = self._local_paths(e) if getattr(self, "para", None) else []
            if paths and self.current_note:
                e.acceptProposedAction()
                if e.type() == e.Type.Drop:
                    self.file_paths(paths, note=core.note_title(self.current_note))
                return True
        if (obj is self.capture and e.type() == e.Type.KeyPress and e.key() in (Qt.Key_Return, Qt.Key_Enter)
                and self.is_search(t := self.capture.text().strip()) and getattr(self, "_hits_text", None) != t):
            # Enter beat the background search: answer now, so a search never lands in the Inbox by accident
            self._search_timer.stop()
            self._search_seq += 1
            self.show_results(self._search_seq, t, find.search(t, index=self.index.ensure(), limit=7,
                                                               habits=habits.boost()))
            self.on_result(self.results.currentRow())
            return True
        if obj is self.capture and e.type() == e.Type.KeyPress and self.results.isVisible():
            k = e.key()
            if k in (Qt.Key_Down, Qt.Key_Up):
                self.results.setCurrentRow(max(0, min(self.results.count() - 1,
                                                      self.results.currentRow() + (1 if k == Qt.Key_Down else -1))))
                return True
            if k in (Qt.Key_Return, Qt.Key_Enter):
                self.on_result(self.results.currentRow())
                return True
            if k == Qt.Key_Escape:
                self.results.hide()
                return True
        return super().eventFilter(obj, e)

    def on_result(self, i):
        if not 0 <= i < len(self._hits):
            return
        kind, label, _, target = self._hits[i]
        self.results.hide()
        if kind in ("note", "app", "file"):
            habits.record(kind, label, os.path.join(core.VAULT, target) if kind == "note" else target)
        if kind == "capture":
            self.on_capture()
            return
        self.capture.clear()
        if kind == "webapp":
            self.open_web_app(label, target)
            return
        if kind == "window":
            desk.activate(target)
        elif kind == "note":
            self.open_note(target)
            self.editor.setFocus()
        elif kind == "app":
            open_ = [w for w, t in desk.windows().items() if label.lower() in t.lower()]
            if open_:  # already running: bring it up instead of a second copy
                desk.activate(open_[0])
            elif cmd := find.app_command(target):
                self.opener(cmd)
        else:  # a file or a web search: its own window, beside the notes
            self.open_beside(target)

    def on_capture(self):
        """The shortest route for each thing: 't call the bank fri' is a task at once, 'c tomorrow 2pm dentist'
        an event at once; anything else (or 'i …') waits in the Inbox to be decided later."""
        text = self.capture.text().strip()
        if not text:
            return
        if text.startswith("t ") and text[2:].strip():
            what, due = core.trailing_date(text[2:].strip())
            core.add_task(what, due)
            self.learned("bar_task")
            self.capture.clear()
            self.refresh_tasks()
            self.save_status.setText(f"Task: {html.escape(what)}" + (f" · due {due.strftime('%a %b')} {due.day}" if due else ""))
            return
        if text.startswith("c "):
            _, _, events, problems = core.expand_shorthand(text)
            if problems or not events:  # said in the status line; the text stays in the bar to fix (no box to click)
                self.save_status.setText(f"<span style='color:#ff8a2a'>{html.escape(problems[0] if problems else 'Not an event')}</span>")
                return
            for d, t, title in events:
                core.add_local_event(d, t, title)
            self.learned("bar_event")
            self.capture.clear()
            self.refresh_calendar()
            self.update_today()
            d = core.parse_date(events[0][0])
            self.save_status.setText(f"On the calendar: {html.escape(events[0][2])} · {d.strftime('%a %b')} {d.day}"
                                     + (f" {events[0][1]}" if events[0][1] else ""))
            return
        core.add_inbox_item(text[2:].strip() if text.startswith("i ") else text)
        self.capture.clear()
        self.refresh_inbox()

    # -- notes sidebar --
    def build_notes_sidebar(self):
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        self.learning_button = self._button("+ New Learning Note", self.on_new_learning_note)
        lay.addWidget(self.learning_button)
        lay.addWidget(self._button("+ New Blank Note", self.on_new_blank_note))
        self.notes_list = QListWidget()
        self.notes_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.notes_list.itemClicked.connect(lambda it: self.open_note(it.data(Qt.UserRole)))
        self.notes_list.setUniformItemSizes(True)  # one height for every row: a big vault lays out at once
        self.note_buttons = RowButtons(self.notes_list, self.note_row_buttons)
        lay.addWidget(self.notes_list, 1)
        return box

    def refresh_notes_list(self):
        """One light row per note; the pencil and × sit on the selected or hovered row (RowButtons)."""
        lst = self.notes_list
        lst.setUpdatesEnabled(False)
        lst.clear()
        for n in core.list_user_notes():
            item = QListWidgetItem(core.note_title(n))
            item.setData(Qt.UserRole, n)
            item.setToolTip(core.note_title(n))
            lst.addItem(item)
            if n == self.current_note:
                lst.setCurrentItem(item)
        lst.setUpdatesEnabled(True)
        self.note_buttons.show_for(lst.currentItem())

    def note_row_buttons(self, item):
        n = item.data(Qt.UserRole)
        if not n:
            return []
        out = []
        if n != "Home.md":  # the app's own starting note keeps its name
            out.append(self._button("✎", lambda n=n: self.on_rename_note(n)))
        out.append(self._button("×", lambda n=n: self.on_delete_note(n)))
        return out

    def on_delete_note(self, filename):
        if QMessageBox.question(self, APP_NAME, f"Move '{core.note_title(filename)}' to the vault's .trash?") \
                != QMessageBox.Yes:
            return
        if self.current_note == filename:
            self.current_note = None  # don't re-save it after it's moved
        core.delete_note(filename)
        core.set_public(filename, False)
        self._publish_timer.start()  # takes its page off the website
        self.sync_answers()
        self.refresh_notes_list()
        self.graph.recompute()
        self.refresh_dataview()
        if self.current_note is None:
            self.open_note("Home.md")

    def on_rename_note(self, filename):
        old = core.note_title(filename)
        new = self.ask_text("Rename note", "New name (every link to it is changed too)", old)
        new = (new or "").strip()
        if not new or new == old:
            return
        self.save_current()  # typing reaches the disk first, so the rename carries it
        try:
            new_file, changed = core.rename_note(filename, new)
        except ValueError as e:
            self.show_error(str(e))
            return
        except OSError as e:
            self.show_error(f"Couldn't rename the note: {e}")
            return
        reopen = new_file if self.current_note == filename else self.current_note
        self.current_note = None  # the editor still holds the old text and old links: don't write them back
        if self.graph.center == filename:
            self.graph.center = new_file
        self.sync_answers()
        self.refresh_notes_list()
        self.refresh_inbox()
        self.refresh_calendar()
        self.refresh_tasks()
        self.refresh_dataview()
        self.graph.recompute()
        self._publish_timer.start()  # a published note moves to a page with the new name
        if self.sync:
            self.sync.poke()
        if reopen:
            self.open_note(reopen)
        self.save_status.setText(f"Renamed to '{new}'" + (f"; {changed} other note{'s' * (changed != 1)} now link to the new name." if changed else "."))

    def on_broken_links(self):
        broken = core.broken_links()
        dlg = QDialog(self)
        dlg.setWindowTitle("Broken links")
        lay = QVBoxLayout(dlg)
        lay.addWidget(QLabel("Links to notes that don't exist. Usually a typo: double-click one to open a note that uses it."
                             if broken else "No broken links: every [[link]] opens a note."))
        listing = QListWidget()
        for title, users in broken.items():
            item = QListWidgetItem(f"[[{title}]]   used in: " + ", ".join(core.note_title(n) for n in users))
            item.setData(Qt.UserRole, users[0])
            listing.addItem(item)
        listing.itemActivated.connect(lambda it: (dlg.accept(), self.open_note(it.data(Qt.UserRole))))
        listing.setVisible(bool(broken))
        lay.addWidget(listing)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(dlg.reject)
        lay.addWidget(buttons)
        dlg.resize(560, 320)
        self.broken_dialog = dlg  # for the test; a modal dialog has no other handle
        dlg.exec()

    # -- guided tour --
    TOUR_VERSION = "0.5"  # a tour that changes this is shown once more after the update

    PRACTICE_TASK = "Practice from the tutorial: tick me"

    def tour_steps(self):
        """The tutorial, in the order you'd use it: each step says what a part is for and has you do it for real.
        The things you type are yours and stay; only the practice task goes away once ticked."""
        panel = lambda i: [w for w in self.panels[i] if w is not None]
        inbox = lambda: len(core.parse_inbox())
        tasks = lambda: len(core.parse_tasks())
        cal = lambda: core.read_note(core.CALENDAR_FILE) if os.path.exists(os.path.join(core.VAULT, core.CALENDAR_FILE)) else ""
        note = lambda: self.current_note
        text = lambda: self.editor.toPlainText()

        def practice():
            if not any(t["text"].strip() == self.PRACTICE_TASK and not t["done"] for t in core.parse_tasks()):
                core.add_task(self.PRACTICE_TASK)
            self.refresh_tasks()

        def away_from_home():
            if self.current_note in (None, "Home.md"):
                self.open_today()
            return self.current_note

        return [
            ("Welcome to SimpleBrain", "This tutorial shows you every part of SimpleBrain, one at a time. At each step "
             "you do one real thing, so by the end you've used all of it. It takes about five minutes. "
             "The ringed part is the only thing you can click; Next opens once you've done the step.",
             [self.how_button], "read this, then click <b>Next</b>. (After the tutorial, this How to button shows it again.)"),
            ("The bar: get it out of your head", "Everything starts in this bar. Type a thought and it waits in "
             "your Inbox, so you can stop holding it in your head and decide later.",
             [self.capture], "click the bar, type <b>i</b>, a space and something you want to remember "
             "(like <b>i ask the library about my hold</b>), then press <b>Enter</b>.",
             {"start": inbox, "check": lambda n: inbox() > n, "focus": self.capture}),
            ("The Inbox: decide later", "What you typed is here. When you have a minute, file each thing: "
             "a Task (something to do), an Event (a date on the calendar) or a Thought/Note (to keep).",
             lambda: panel(0), "under what you just typed, click <b>Task</b>. It asks for a due date: type <b>fri</b> "
             "(or leave it blank) and click <b>OK</b>.",
             {"start": inbox, "check": lambda n: inbox() < n}),
            ("A task in one line", "Skip the Inbox when you already know it's a task: start the line with <b>t</b>. "
             "Write the day the way you'd say it: today, tomorrow, fri, next mon, nov 5, in 3 days.",
             [self.capture], "type <b>t</b>, a space, something you need to do and a day, like "
             "<b>t return library books sat</b>, then press <b>Enter</b>.",
             {"start": tasks, "check": lambda n: tasks() > n, "focus": self.capture}),
            ("Tasks: tick it when it's done", "Every task from every note, by date: overdue, today, upcoming. "
             "Ticking one marks it done in its note. If too much is due today, Spread out moves the extras.",
             lambda: panel(1), f"find <b>{self.PRACTICE_TASK}</b> in the list and tick its box.",
             {"start": practice, "check": lambda _: not any(t["text"].strip() == self.PRACTICE_TASK and not t["done"]
                                                             for t in core.parse_tasks()),
              "done": lambda _: self.remove_practice_task()}),
            ("An event in one line", "Start the line with <b>c</b> to put it on the calendar: the day, an optional "
             "time, then what it is.",
             [self.capture], "type <b>c tomorrow 2pm coffee with a friend</b> (or something you really have coming up) "
             "and press <b>Enter</b>.",
             {"start": cal, "check": lambda old: cal() != old, "focus": self.capture}),
            ("Your notes", "Every note you have, in one list. Click one to open it. Hover a note for the pencil "
             "(rename) and the × (to the trash, never gone for good). Home explains everything in short lines.",
             [self.notes_list], "click <b>Home</b> in the list.",
             {"start": away_from_home, "check": lambda _: self.current_note == "Home.md"}),
            ("A note for a book", "A Learning Note is a page for a book you're studying, in three short sittings: "
             "a first look and your questions, the answers the next day, then saying it back from memory. Each "
             "sitting is a task: tick it and the next one appears on its day.",
             [self.learning_button], "click <b>+ New Learning Note</b>, type the title of a book you're reading, "
             "and click <b>OK</b>.",
             {"start": note, "check": lambda old: self.current_note != old and core.is_book_note(text())}),
            ("Personal or public library", "On a book note, this box says where the book came from. Ticked: it's "
             "yours. Unticked: it's from the public library. The note keeps it as a library:: line.",
             lambda: [self.library_box if self.library_box.isVisible() else self.editor], "if the book is yours, click the box. If it's borrowed, click it twice (on, then off): "
             "the note then says public.",
             {"check": lambda _: core.library_of(text()) is not None, "focus": self.library_box}),
            ("Writing and links", "Write here; it saves by itself. Linking notes is how SimpleBrain connects your "
             "ideas: type two square brackets and a few letters of another note's name.",
             [self.editor], "click at the end of the note, type <b>[[Ho</b> and press <b>Enter</b> to pick Home.",
             {"start": lambda: len(core.parse_links(text())), "check": lambda n: len(core.parse_links(text())) > n,
              "focus": self.editor}),
            ("Under the note", "The links in this note, notes that link here, files, notes that mention it without "
             "a link (one click links them) and related notes.",
             [self.links_scroll], "click the <b>[[Home]]</b> button in the Links row to go there.",
             {"start": note, "check": lambda old: self.current_note != old}),
            ("The graph", "Your notes as dots, the open one in the middle; lines are links. Click a dot to go there.",
             [self.graph_box], "click any dot other than the middle one.",
             {"start": note, "check": lambda old: self.current_note != old}),
            ("Drop and Money", "Drop: drag a file onto this window and it's put in the right folder and linked from "
             "its note, with Undo. Money: write your cash and paychecks in the Budget note and see how far it lasts.",
             [self.drop_button, self.money_button], "remember these two for later, then click <b>Next</b>."),
            ("Time left today", "Add a line like <b>limit:: 3h</b> (or <b>limit:: until 9pm</b>) to your Home note "
             "and the top bar shows how much computer time is left today.",
             [self.watch_label if self.watch_label.isVisible() else self.capture], "click <b>Next</b>."),
            ("Calendar and Dataview", "Your events (and a calendar you link), and every note in a table you can "
             "filter by #tag.", lambda: panel(2) + panel(3), "find the event you made in step 5, then click <b>Next</b>."),
            ("You're ready", "You've used every part: the bar, the Inbox, tasks, events, notes, book notes, links and the "
             "graph. Your Today note (File › Today) picks three things a day and ends with one small thing to "
             "learn. The How to button runs this tutorial again any time.",
             [self.how_button], "click <b>Done</b> to start using SimpleBrain."),
        ]

    def remove_practice_task(self):
        for t in core.parse_tasks():
            if t["text"].strip() == self.PRACTICE_TASK:
                core.delete_task(t)
                break  # line numbers move after a delete; one practice task at a time
        self.refresh_tasks()

    def learned(self, key):
        """Note that a step of 'Learn one thing' was done, so Today shows the next one."""
        done = core.load_settings().get("learned", [])
        if key not in done:
            self.save_setting("learned", done + [key])
            self.update_today()

    def start_tour(self, required=False):
        if self.tour:
            return
        self.save_current()
        self.tour = Tour(self, self.tour_steps(), required)

    def maybe_start_tour(self):
        """On the first launch, and once after an update that changed it, the tutorial is the way in: it can't be
        skipped or left (Tour.required). Only reaching Done counts as seen."""
        s = core.load_settings()
        if s.get("tour_done") != "yes" or s.get("tour_version") != self.TOUR_VERSION:
            self.showNormal()
            self.raise_()
            self.activateWindow()
            self.start_tour(required=True)

    def tutorial_locked(self):
        tour = getattr(self, "tour", None)  # changeEvent runs before __init__ has set it
        return bool(tour and tour.required)

    def tour_finished(self, tour):
        if tour is self.tour:
            self.tour = None
        while any(t["text"].strip() == self.PRACTICE_TASK for t in core.parse_tasks()):  # a replay left early
            self.remove_practice_task()
        self.save_setting("tour_done", "yes")
        self.save_setting("tour_version", self.TOUR_VERSION)
        self.editor.setFocus()

    def on_new_learning_note(self):
        title = self.ask_text("New Learning Note", "Book or topic title")
        if title and title.strip():
            self.create_note(title.strip(), content=core.learning_note_template(title.strip()))

    def on_new_blank_note(self):
        title = self.ask_text("New Blank Note", "Note title")
        if title and title.strip():
            self.create_note(title.strip(), content=core.blank_note_template(title.strip()))

    def create_note(self, title, content=None):
        if not core.is_safe_note_title(title):
            self.show_error(f"'{title}' isn't a valid note title "
                            "(it can't contain / \\ : * ? \" < > |, start with a dot, or end with a dot or space).")
            return
        if core.is_reserved_title(title):
            self.show_error(f"'{title}' is a name SimpleBrain uses itself. Pick a different title.")
            return
        filename = title + ".md"
        if not os.path.exists(os.path.join(core.VAULT, filename)):
            core.write_note(filename, content if content is not None else f"# {title}\n\n")
            self.refresh_notes_list()
            self.graph.recompute()
            self.refresh_dataview()
        self.open_note(filename)

    # -- editor --
    def build_editor(self):
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        self.title_label = QLabel()
        lay.addWidget(self.title_label)
        self.public_box = QCheckBox("Show this note on my website")
        self.public_box.toggled.connect(self.on_toggle_public)
        lay.addWidget(self.public_box)
        # On a book note: ticked, it's yours; unticked, it's from the public library. Kept as a library:: line.
        self.library_box = QCheckBox("From my personal library (unticked: public library)")
        self.library_box.toggled.connect(self.on_toggle_library)
        self.library_box.hide()
        lay.addWidget(self.library_box)
        self.editor = QPlainTextEdit()
        lay.addWidget(self.editor, 1)
        # Typing [[ offers your notes' titles (simplebrain_links.complete); Enter or Tab puts one in.
        self.link_popup = QListWidget(self)
        self.link_popup.setObjectName("results")
        self.link_popup.hide()
        self.link_popup.itemClicked.connect(lambda it: self.accept_link(it.text()))
        self.editor.textChanged.connect(self.suggest_links)
        self.editor.installEventFilter(self)
        # Web links, file:: paths and [[notes]] in the text open on a click, in their own windows.
        self.links = glass.LinkHighlighter(self.editor.document(), self.palette().link().color().name())
        glass.LinkClicks(self.editor, self.on_note_link)
        QShortcut(QKeySequence("Ctrl+T"), self.editor, activated=self.insert_video_time)
        # Links follow typing (debounced), so a new [[link]] shows without reopening.
        self._links_timer = QTimer(self, singleShot=True, interval=300)
        self._links_timer.timeout.connect(self.render_links)
        self.editor.textChanged.connect(self._links_timer.start)
        # Typing is written to disk shortly after you stop, so the other device never waits on a Save.
        self._autosave_timer = QTimer(self, singleShot=True, interval=2500)
        self._autosave_timer.timeout.connect(self.autosave)
        self.editor.textChanged.connect(self._autosave_timer.start)
        # Website updates wait for a pause too, so a burst of saves is one trip to the website.
        self._publish_timer = QTimer(self, singleShot=True, interval=8000)
        self._publish_timer.timeout.connect(self.publish_now)
        # A note changed by another program is picked up here, not overwritten by the next autosave.
        self._outside_timer = QTimer(self, interval=2000)
        self._outside_timer.timeout.connect(self.reconcile_outside)
        self._outside_timer.start()
        links_holder = QWidget()
        links_holder.setObjectName("glassRoot")  # see-through in Glass, like the rest of the window
        rows = QVBoxLayout(links_holder)
        rows.setContentsMargins(4, 2, 4, 2)
        self.links_row, self.backlinks_row, self.files_row = QHBoxLayout(), QHBoxLayout(), QHBoxLayout()
        self.mentions_row, self.related_row = QHBoxLayout(), QHBoxLayout()  # simplebrain_links
        rows.addLayout(self.links_row)
        rows.addLayout(self.backlinks_row)
        rows.addLayout(self.files_row)
        rows.addLayout(self.mentions_row)
        rows.addLayout(self.related_row)
        scroll = QScrollArea()
        scroll.setWidget(links_holder)
        scroll.setWidgetResizable(True)
        scroll.setFixedHeight(170)
        scroll.setObjectName("glassScroll")
        scroll.setFrameShape(QFrame.NoFrame)
        self.links_scroll = scroll
        # ```dataview blocks in the open note: their live results, here under the note (simplebrain_dataview)
        self.query_box = QWidget()
        self.query_lay = QVBoxLayout(self.query_box)
        self.query_lay.setContentsMargins(4, 2, 4, 2)
        self.query_box.hide()
        lay.addWidget(self.query_box)
        lay.addWidget(scroll)
        save_row = QHBoxLayout()
        save_row.addWidget(self._button("Save (Ctrl+S)", self.save_current))
        save_row.addWidget(self._button("Cite source…", self.on_cite))
        save_row.addWidget(self._button("Link file…", self.on_link_file))
        self.save_status = QLabel()
        save_row.addWidget(self.save_status, 1)
        lay.addLayout(save_row)
        return box

    def open_link(self, filename):
        """Open a linked note; a link to a note that doesn't exist yet asks
        before creating it (graph dots, link buttons, Dataview)."""
        if not os.path.exists(os.path.join(core.VAULT, filename)) and not self.confirm_create(filename):
            return
        self.open_note(filename)

    def confirm_create(self, filename):
        return QMessageBox.question(self, APP_NAME, f"'{core.note_title(filename)}' doesn't exist yet. "
                                    "Create it?") == QMessageBox.Yes

    def open_note(self, filename):
        if not core.is_safe_note_title(core.note_title(filename)):
            self.show_error(f"'{core.note_title(filename)}' isn't a valid note title.")
            return
        if not os.path.exists(os.path.join(core.VAULT, filename)):
            self.create_note(core.note_title(filename))
            return
        self.save_current()
        self.current_note = filename
        self.title_label.setText(f"<b>{core.note_title(filename)}</b>")
        text = self._disk_text = core.read_note(filename)
        self._saved_links, self._saved_tasks = set(core.parse_links(text)), task_lines(text)
        self._saved_answers = core.parse_answers(text)
        self.editor.setPlainText(text)
        self.public_box.blockSignals(True)  # showing the saved state isn't a change to publish
        self.public_box.setChecked(core.is_public(filename))
        self.public_box.blockSignals(False)
        self.show_library(text)
        self._links_timer.stop()
        self._mentions_note = None
        self.render_links()
        self.render_queries()
        if self.graph.center != filename:  # the graph centers on the note you're reading
            self.graph.center = filename
            self.graph.recompute()
        for i in range(self.notes_list.count()):
            if self.notes_list.item(i).data(Qt.UserRole) == filename:
                self.notes_list.setCurrentRow(i)

    def render_links(self):
        """Links row from the editor's current text; Linked-from row from the
        saved notes on disk (only other notes' saves can change it)."""
        for row in (self.links_row, self.backlinks_row, self.files_row):
            while row.count():
                w = row.takeAt(0).widget()
                if w:
                    w.hide()  # gone now: deleteLater alone left the old labels drawn under the new ones
                    w.deleteLater()
        if self.current_note:
            self.show_library(self.editor.toPlainText())  # a [[Learning]] link or library:: line typed just now
        self.links_row.addWidget(QLabel("Links:"))
        for link in sorted(set(core.parse_links(self.editor.toPlainText()))):
            missing = not os.path.exists(os.path.join(core.VAULT, link + ".md"))
            b = self._button(f"[[{link}]]" + ("  + new" if missing else ""),
                             lambda l=link: self.open_link(l + ".md"))
            if missing:
                b.setToolTip(f"'{link}' doesn't exist yet: click to create it")
            self.links_row.addWidget(b)
        self.links_row.addStretch(1)
        self.backlinks_row.addWidget(QLabel("Linked from:"))
        for n in core.backlinks(self.current_note) if self.current_note else []:
            b = self._button(core.note_title(n), lambda n=n: self.open_note(n))
            b.setProperty("note", n)  # render_mentions adds the line that links here as its tooltip
            self.backlinks_row.addWidget(b)
        self.backlinks_row.addStretch(1)
        self.files_row.addWidget(QLabel("Files:"))
        refs = list(dict.fromkeys(core.parse_files(self.editor.toPlainText())))
        if len(refs) > 12:  # a folder's worth of files: buttons for the first few, every line still clicks in the note
            self.files_row.addWidget(QLabel(f"<span style='color:gray'>{len(refs) - 12} more in the note</span>"))
        for ref in refs[:12]:
            path = core.resolve_file(ref)
            missing = not os.path.exists(path)
            b = self._button(os.path.basename(ref.rstrip("/")) + ("  (not found)" if missing else ""),
                             lambda p=path: self.open_beside(p))
            b.setToolTip(f"{path}" + ("\nNot found on this device." if missing else ""))
            self.files_row.addWidget(b)
        m = today_note.FOLDER_LINE.search(self.editor.toPlainText())
        if m:  # a course folder: the next session, in order, one click away (opening it counts as done)
            folder = os.path.normpath(core.resolve_file(m.group(1)))
            files = today_note.sessions(folder) if os.path.isdir(folder) else []
            seen = today_note.opened_files()
            nxt = next((f for f in files if os.path.normpath(f) not in seen), None)
            if nxt:
                done = sum(1 for f in files if os.path.normpath(f) in seen)
                b = self._button(f"▶ Next: {os.path.splitext(os.path.basename(nxt))[0]}  ({done + 1} of {len(files)})",
                                 lambda p=nxt: self.on_note_link("file", p))
                b.setToolTip(nxt)
                self.files_row.addWidget(b)
            elif files:
                self.files_row.addWidget(QLabel(f"✓ all {len(files)} done"))
        self.files_row.addStretch(1)
        if getattr(self, "_mentions_note", None) != self.current_note:
            self.render_mentions()  # once per note opened (and on save): typing here can't change other notes
        else:
            self.show_backlink_lines()

    def render_queries(self):
        """Each ```dataview block in the open note, run now and shown under it: a table, a list, or tasks you can tick."""
        while self.query_lay.count():
            w = self.query_lay.takeAt(0).widget()
            if w:
                w.hide()
                w.deleteLater()
        queries = dv.blocks(self.editor.toPlainText()) if self.current_note else []
        self.query_box.setVisible(bool(queries))
        if not queries:
            return
        try:
            all_pages = dv.pages()
        except OSError:
            return
        for q in queries[:4]:
            head = QLabel(f"<span style='color:gray'>Query:</span> {html.escape(q.splitlines()[0])}")
            self.query_lay.addWidget(head)
            try:
                res = dv.run(q, this=self.current_note, all_pages=all_pages)
            except dv.DQLError as e:
                err = QLabel(f"<span style='color:#e58a6e'>{html.escape(str(e))}</span>")
                err.setWordWrap(True)
                self.query_lay.addWidget(err)
                continue
            if res["type"] == "TASK" and not res["grouped"]:
                lst = QListWidget()
                for t in res["items"]:
                    it = QListWidgetItem(f"{core.due_for_display(t['text'])}   · {t['file']['name']}")
                    it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
                    it.setCheckState(Qt.Checked if t["completed"] else Qt.Unchecked)
                    it.setData(Qt.UserRole, {"file": t["path"], "line": t["line"], "done": t["completed"], "text": t["text"]})
                    lst.addItem(it)
                lst.itemChanged.connect(self.on_query_task)
                view = lst
            else:
                headers, rows = self.result_table(res)
                view = QTableWidget(len(rows), len(headers))
                view.setHorizontalHeaderLabels(headers)
                view.verticalHeader().hide()
                view.setEditTriggers(QTableWidget.NoEditTriggers)
                view.horizontalHeader().setStretchLastSection(True)
                for i, (path, cells) in enumerate(rows):
                    for j, text in enumerate(cells):
                        item = QTableWidgetItem(text)
                        item.setData(Qt.UserRole, path)
                        view.setItem(i, j, item)
                view.cellDoubleClicked.connect(lambda r, _c, v=view: v.item(r, 0) and v.item(r, 0).data(Qt.UserRole)
                                               and self.open_note(v.item(r, 0).data(Qt.UserRole)))
                view.resizeColumnsToContents()
            n = max(1, view.count() if isinstance(view, QListWidget) else view.rowCount())
            view.setFixedHeight(min(220, 34 + n * 26))
            self.query_lay.addWidget(view)

    def on_query_task(self, item):
        t = item.data(Qt.UserRole)
        if not t:
            return
        if not t["done"] and item.checkState() == Qt.Checked:
            self.learned("tick")
            if hasattr(self, "watch_state"):
                watch.tick_done(self.watch_state["day"])
        self.edit_in_file(t["file"], lambda: core.toggle_task(t))
        QTimer.singleShot(0, self.refresh_tasks)
        QTimer.singleShot(0, self.render_queries)

    def render_mentions(self):
        """Mentioned in: notes that name this one without a link (click: it becomes a [[link]]). Related: notes
        about the same things, not linked yet, with the words they share. Linked from: the line that links here.
        All three read every note, so they're worked out in the background: opening a note never waits on them."""
        self._mentions_note = note = self.current_note
        self._mentions_seq = getattr(self, "_mentions_seq", 0) + 1
        for row in (self.mentions_row, self.related_row):
            while row.count():
                w = row.takeAt(0).widget()
                if w:
                    w.hide()
                    w.deleteLater()
        if not note or not os.path.exists(os.path.join(core.VAULT, note)):
            return
        self._mentions_busy = True
        if not hasattr(self, "_mentions_timer"):  # clicking through notes starts nothing until you rest on one
            self._mentions_timer = QTimer(self, singleShot=True, interval=400)
            self._mentions_timer.timeout.connect(self._start_mentions)
        self._mentions_timer.start()

    def _start_mentions(self):
        if getattr(self, "_mentions_running", False):  # one at a time: it starts again when this one lands
            self._mentions_timer.start()
            return
        note, seq, vault = self._mentions_note, self._mentions_seq, core.VAULT
        if note != self.current_note:
            return
        self._mentions_running = True

        def work():
            try:
                context = {}
                for n, line in linking.backlinks_in_context(note, vault):
                    context.setdefault(n, []).append(line)
                found = (context, linking.unlinked_mentions(note, vault), linking.related(note, vault))
            except Exception:  # an odd note never takes the window down
                found = ({}, [], [])
            self.bridge.run_ui.emit((lambda: self.show_mentions(seq, note, *found), {"done": threading.Event()}))
        threading.Thread(target=work, daemon=True).start()

    def show_mentions(self, seq, note, context, mentions, rel):
        self._mentions_running = False
        if seq != self._mentions_seq or note != self.current_note:
            return  # another note was opened meanwhile
        self._mentions_busy = False
        self._backlink_lines = context
        self.show_backlink_lines()
        title = core.note_title(note)
        if mentions:
            self.mentions_row.addWidget(QLabel("Mentioned in:"))
            for n, i, line in mentions[:6]:
                b = self._button(f"{core.note_title(n)}  ＋link", lambda n=n, i=i: self.on_link_mention(n, i, title))
                b.setToolTip(f"{line}\n\nClick to make this mention a [[{title}]] link.")
                self.mentions_row.addWidget(b)
            if len(mentions) > 1:
                self.mentions_row.addWidget(self._button("Link all", lambda m=mentions: self.on_link_all(m, title)))
            self.mentions_row.addStretch(1)
        if rel:
            self.related_row.addWidget(QLabel("Related:"))
            for n, shared in rel:
                b = self._button(core.note_title(n), lambda n=n: self.open_note(n))
                b.setToolTip("Shares: " + ", ".join(shared) + "\nNot linked yet.")
                self.related_row.addWidget(b)
            self.related_row.addStretch(1)

    def show_backlink_lines(self):
        lines = getattr(self, "_backlink_lines", {})
        for i in range(self.backlinks_row.count()):
            b = self.backlinks_row.itemAt(i).widget()
            if isinstance(b, QPushButton) and b.property("note") in lines:  # why it links here, not just who
                b.setToolTip("\n".join(lines[b.property("note")][:4]))

    def on_link_mention(self, note, line_no, title):
        self.learned("mention")
        if self.edit_in_file(note, lambda: linking.link_mention(note, line_no, title)):
            self.save_status.setText(f"Linked {html.escape(core.note_title(note))} to {html.escape(title)}.")
        self._mentions_note = None
        self.render_links()
        self.graph.recompute()

    def on_link_all(self, mentions, title):
        done = 0
        self.learned("mention")
        for n, i, _ in sorted(mentions, key=lambda m: -m[1]):  # bottom up: line numbers stay right
            done += bool(self.edit_in_file(n, lambda n=n, i=i: linking.link_mention(n, i, title)))
        self.save_status.setText(f"Linked {done} mention{'s' if done != 1 else ''} of {html.escape(title)}.")
        self._mentions_note = None
        self.render_links()
        self.graph.recompute()

    def suggest_links(self):
        c = self.editor.textCursor()
        typed = linking.typing_link(c.block().text()[:c.positionInBlock()])
        if typed is None:
            self.link_popup.hide()
            return
        titles = [core.note_title(n) for n in core.list_notes()]
        hits = linking.complete(typed, titles)
        if typed.strip() and typed.strip() not in titles:
            hits.append(f"{typed.strip()}  (new note)")
        if not hits:
            self.link_popup.hide()
            return
        self.link_popup.clear()
        self.link_popup.addItems(hits)
        self.link_popup.setCurrentRow(0)
        r = self.editor.cursorRect(c)
        top_left = self.editor.viewport().mapTo(self, r.bottomLeft())
        h = min(len(hits), 8) * (self.link_popup.sizeHintForRow(0) + 2) + 10
        self.link_popup.setGeometry(top_left.x(), top_left.y() + 4, 320, h)
        self.link_popup.show()
        self.link_popup.raise_()

    def accept_link(self, text):
        title = text.replace("  (new note)", "")
        c = self.editor.textCursor()
        typed = linking.typing_link(c.block().text()[:c.positionInBlock()]) or ""
        c.movePosition(c.MoveOperation.Left, c.MoveMode.KeepAnchor, len(typed))
        after = c.block().text()[c.positionInBlock() + len(typed):]
        c.insertText(title + ("" if after.startswith("]]") else "]]"))
        self.editor.setTextCursor(c)
        self.link_popup.hide()
        self.learned("link_complete")

    # -- links in a note open in their own windows, beside the note (simplebrain_desk) --
    def on_note_link(self, kind, target):
        if kind == "note":
            habits.record("note", target, os.path.join(core.VAULT, target + ".md"))
            self.open_link(target + ".md")
        else:
            habits.record("url" if kind == "url" else "file", os.path.basename(target.rstrip("/")) or target,
                          target if kind == "url" else core.resolve_file(target))
            self.open_beside(target if kind == "url" else core.resolve_file(target))

    def open_beside(self, target):
        """Pictures and videos open inside SimpleBrain, where the graph is (the viewer); anything else (a PDF, a web
        link, video where mpv can't be drawn inside) in its own window placed there, so the notes list and the note
        you're writing stay in view."""
        url = target.startswith(("http://", "https://"))
        if not url and not os.path.exists(target):
            self.save_status.setText(f"<span style='color:#e58a6e'>Not on this computer: {html.escape(target)}</span>")
            return
        ext = os.path.splitext(target)[1].lower()
        if not url and ext in desk.IMAGE_EXTS and self.show_in_viewer(lambda: self.viewer.show_picture(target)):
            return
        if not url and ext in (".md", ".txt") and self.show_in_viewer(lambda: self.viewer.show_text(target)):
            return  # a call card or a script: read it right here, beside the note
        if not url and ext in desk.MEDIA_EXTS and desk.can_embed():
            self.show_in_viewer(lambda: self.viewer.play(target, self.embed_launcher) or True)
            return
        self.open_outside(target)

    def show_in_viewer(self, load):
        self.graph.hide()
        self.viewer.show()
        if load():
            return True
        self.close_viewer()
        return False

    def close_viewer(self):
        self.viewer.stop()
        self.viewer.hide()
        self.graph.show()

    def open_outside(self, target):
        """In its own program, placed where the graph is (wmctrl), never full screen."""
        if not target:
            return
        url = target.startswith(("http://", "https://"))
        cmd = desk.open_command(target)
        before = set(desk.windows())
        if cmd:
            self.opener(cmd)
        else:
            QDesktopServices.openUrl(QUrl(target) if url else QUrl.fromLocalFile(target))
        if desk.x11() and desk.have("wmctrl"):
            g = self.screen().availableGeometry()
            edge = self.editor.mapToGlobal(self.editor.rect().topRight()).x() + 8
            rect = desk.beside((g.x(), g.y(), g.width(), g.height()), edge)
            import time
            self._place = (before, time.time() + 12, rect)
            self._place_timer.start()

    def _place_tick(self):
        import time
        before, until, rect = self._place
        new = [w for w, title in desk.windows().items() if w not in before and title != APP_NAME]
        if new or time.time() > until:
            self._place_timer.stop()
            if new:
                desk.place(new[0], rect)

    def insert_video_time(self):
        """'12:34 — ' on a new line: where the video opened from a note is right now (Ctrl+T)."""
        t = desk.video_time()
        if not t:
            self.save_status.setText("No video playing from a note.")
            return
        c = self.editor.textCursor()
        if not c.atBlockStart():
            c.insertText("\n")
        c.insertText(f"{t} — ")
        self.editor.setTextCursor(c)

    def open_today(self):
        """File > Today: the Today note, written now."""
        self.save_current()
        name, _ = today_note.update(ics_text=self._ics_text)
        self.refresh_notes_list()
        self.open_note(name)

    def handle_command(self, cmd):
        """From a second `simplebrain …` (its icon clicked again, or `--toggle` on a key of your own) to the one
        already running."""
        if cmd == "toggle" and self.isActiveWindow() and not self.tutorial_locked():
            self.showMinimized()
        else:
            self.showNormal()
            self.raise_()
            self.activateWindow()
            if desk.x11() and desk.have("wmctrl"):  # Xfce's focus guard would otherwise only blink the taskbar
                desk.activate(hex(int(self.winId())))

    def on_link_file(self):
        """Record where a file lives (it stays put) as a `file::` line at the cursor."""
        path, _ = QFileDialog.getOpenFileName(self, "Link a file to this note", os.path.expanduser("~"))
        if not path:
            return
        cur = self.editor.textCursor()
        lead = "" if cur.atBlockStart() else "\n"
        cur.insertText(f"{lead}{core.file_line(path)}\n")
        self.editor.setTextCursor(cur)
        self.render_links()

    def save_current(self):
        if self.current_note is None:
            return
        kept = self.reconcile_outside()
        typed = self.editor.toPlainText()
        try:
            text, problems = core.write_note_with_shorthand(self.current_note, typed)
            self._disk_text = text
            self.save_status.setText("<span style='color:red'>Not added to Calendar: "
                                     f"{html.escape('; '.join(problems))}</span>" if problems else "" if not kept else self.save_status.text())
        except OSError as e:
            # A save failure must be visible, or the user keeps typing believing it saved.
            self.save_status.setText(f"<span style='color:red'>Save failed: {e}</span>")
            return
        if text != typed:  # t/i/c shorthand expanded: show it, keep the cursor near where it was
            pos = self.editor.textCursor().position()
            self.editor.setPlainText(text)
            cursor = self.editor.textCursor()
            cursor.setPosition(min(pos, self.editor.document().characterCount() - 1))
            self.editor.setTextCursor(cursor)
            QTimer.singleShot(0, self.refresh_inbox)
            QTimer.singleShot(0, self.refresh_calendar)
        links, answers = set(core.parse_links(text)), core.parse_answers(text)
        if links != self._saved_links or answers != self._saved_answers:
            notes_changed = self.sync_answers()
            if links != self._saved_links or notes_changed:  # only re-layout when links/notes changed
                self.graph.recompute()
                self.refresh_dataview()
            self._saved_links, self._saved_answers = links, answers
        if task_lines(text) != self._saved_tasks:  # new/edited task lines show in Tasks
            self._saved_tasks = task_lines(text)
            QTimer.singleShot(0, self.refresh_tasks)  # deferred: may be inside a Tasks-row click
        if self.current_note == budget.NOTE:
            self.update_money_button()
        if "```dataview" in text or self.query_box.isVisible():
            QTimer.singleShot(0, self.render_queries)
        if self.current_note in (*core.SETTINGS_NOTES, "Apps.md") and "app::" in text:
            self.sync_web_apps()
        if self.sync:
            self.sync.poke()  # tell the other device soon, not at the next timer tick
        if self.public_box.isChecked():
            self._publish_timer.start()

    # -- personal or public library --
    def show_library(self, text):
        """The tick shows on book notes only, and follows a library:: line typed by hand."""
        self.library_box.setVisible(core.is_book_note(text))
        self.library_box.blockSignals(True)
        self.library_box.setChecked(core.library_of(text) == "personal")
        self.library_box.blockSignals(False)

    def on_toggle_library(self, on):
        if self.current_note is None:
            return
        old = self.editor.toPlainText()
        new = core.set_library(old, on)
        if new == old:
            return
        pos = self.editor.textCursor().position()
        cur = self.editor.textCursor()
        cur.select(QTextCursor.Document)
        cur.insertText(new)  # one edit, so Ctrl+Z takes it back; autosave writes it like typing
        cur.setPosition(min(pos + (len(new) - len(old) if new.find("library::") < pos else 0), len(new)))
        self.editor.setTextCursor(cur)

    # -- website --
    def on_toggle_public(self, on):
        if self.current_note is None:
            return
        if on and not pub.site_config():
            self.public_box.blockSignals(True)
            self.public_box.setChecked(False)
            self.public_box.blockSignals(False)
            self.on_website_setup()
            return
        core.set_public(self.current_note, on)
        self._publish_timer.start(0)

    def on_website_setup(self):
        """WordPress, Shopify or any other site (a folder of pages), in steps (simplebrain_setup)."""
        dlg = setup.WebsiteSetup(self)
        if dlg.exec() == QDialog.Accepted:
            self.save_status.setText(html.escape(dlg.result_line))
            if dlg.saved:
                self._publish_timer.start(0)

    def publish_now(self):
        """Bring the store's pages in line with the public notes, off the UI thread; one run at a time."""
        if self._publishing:
            self._publish_again = True
            return
        cfg = pub.site_config()
        if not cfg:
            return
        self._publishing = True
        vault = core.VAULT

        def work():
            try:
                pub.publish(vault, cfg)
                self.bridge.publish_done.emit("")
            except Exception as e:  # never let the website take the app down
                self.bridge.publish_done.emit(str(e))
        threading.Thread(target=work, daemon=True).start()

    def on_publish_done(self, error):
        self._publishing = False
        if error:
            self.save_status.setText(f"<span style='color:red'>Website not updated: {html.escape(error)}</span>")
        if self._publish_again:
            self._publish_again = False
            self._publish_timer.start()

    def reconcile_outside(self):
        """The open note was changed on disk by another program. With nothing typed since the last
        save, show the new text; with typing, keep that typing as its own note and show the disk text,
        so neither version is lost and autosave never overwrites the outside edit."""
        if self.current_note is None:
            return False
        try:
            disk = core.read_note(self.current_note)
        except (OSError, ValueError):
            return False  # deleted or unreadable: a save recreates it, as before
        known, self._disk_text = self._disk_text, disk
        typed = self.editor.toPlainText()
        if disk == known or typed == disk:
            return False
        kept = typed != known
        if kept:  # typing nobody has saved: keep it as its own note
            copy = core.edited_elsewhere_name(self.current_note)
            core.write_note(copy, typed)
            self.save_status.setText("<span style='color:red'>This note was changed outside SimpleBrain "
                                     f"while you were typing. Your typing is saved as '{html.escape(core.note_title(copy))}'.</span>")
            self.refresh_notes_list()
        self._saved_links, self._saved_tasks = set(core.parse_links(disk)), task_lines(disk)
        self._saved_answers = core.parse_answers(disk)
        self.editor.setPlainText(disk)
        self.render_links()
        self.graph.recompute()
        self.refresh_dataview()
        self.refresh_tasks()
        return kept

    def autosave(self):
        """Write the open note if it differs from disk, unless saving would rewrite it (a t/i/c
        shorthand line moves things): those wait for a deliberate save, so text never jumps while typing."""
        if self.current_note is None:
            return
        typed = self.editor.toPlainText()
        try:
            if core.read_note(self.current_note) == typed or core.expand_shorthand(typed)[0] != typed:
                return
        except (OSError, ValueError):
            return
        self.save_current()

    def sync_answers(self):
        """Rebuild the "<Keyword> - Answers" notes; True if any changed. The
        open note is reloaded if it was one of them (or Home opened if it went)."""
        changed = core.sync_answer_notes()
        if self.current_note in changed:
            if os.path.exists(os.path.join(core.VAULT, self.current_note)):
                self._disk_text = core.read_note(self.current_note)
                self.editor.setPlainText(self._disk_text)
            else:
                self.current_note = None
                self.open_note("Home.md")
        if changed:
            self.refresh_notes_list()
        return bool(changed)

    def closeEvent(self, e):
        if self.tutorial_locked() and not QApplication.instance().isSavingSession():  # logging out still works
            e.ignore()
            self.tour.nag()
            return
        self.viewer.stop()
        self.save_current()
        if self.sync:
            self.sync.stop()
        e.accept()

    # -- device sync (see simplebrain_sync) --
    def on_ui(self, fn):
        """Run fn on the UI thread and return its result: how the sync thread touches notes."""
        if QThread.currentThread() == self.thread():
            return fn()
        box = {"done": threading.Event()}
        self.bridge.run_ui.emit((fn, box))
        if not box["done"].wait(30):
            raise TimeoutError("the app didn't respond")
        if "error" in box:
            raise box["error"]
        return box["result"]

    def _run_ui(self, job):
        fn, box = job
        try:
            box["result"] = fn()
        except Exception as e:  # handed back to the sync thread, which reports it
            box["error"] = e
        box["done"].set()

    def apply_synced(self, av, writes, deletes, expect):
        """Put the other device's changes on disk. The open note is left alone while it holds typing
        that isn't saved yet; the next round picks it up. Returns the names not applied."""
        hold = set()
        if self.current_note in writes or self.current_note in deletes:
            try:
                if core.read_note(self.current_note) != self.editor.toPlainText():
                    hold.add(self.current_note)
            except (OSError, ValueError):
                pass
        writes = {n: t for n, t in writes.items() if n not in hold}
        deletes = [n for n in deletes if n not in hold]
        skipped = devsync.DiskVault.apply(av, writes, deletes, expect) + sorted(hold)
        changed = [n for n in list(writes) + deletes if n not in skipped]
        if changed:
            self.after_sync(changed)
        return skipped

    def after_sync(self, changed):
        """Redraw whatever the incoming notes touched; the open note is reloaded if it was one of them."""
        if self.current_note in changed:
            path = os.path.join(core.VAULT, self.current_note)
            if os.path.exists(path):
                text = self._disk_text = core.read_note(self.current_note)
                self._saved_links, self._saved_tasks = set(core.parse_links(text)), task_lines(text)
                self._saved_answers = core.parse_answers(text)
                pos = self.editor.textCursor().position()
                self.editor.setPlainText(text)
                cursor = self.editor.textCursor()
                cursor.setPosition(min(pos, self.editor.document().characterCount() - 1))
                self.editor.setTextCursor(cursor)
            else:
                self.current_note = None
                self.open_note("Home.md")
        self.sync_answers()
        self.refresh_notes_list()
        self.graph.recompute()
        self.refresh_dataview()
        self.refresh_tasks()
        if core.INBOX_FILE in changed:
            self.refresh_inbox()
        if core.CALENDAR_FILE in changed:
            self.refresh_calendar()
        self.render_links()

    def start_sync(self):
        if self.sync is None and not devsync.available():
            self.sync_label.setText("Sync: not on this system")
            return None
        if self.sync is None:
            self.sync = devsync.SyncService(AppVault(self), on_status=self.bridge.sync_status.emit)
            self.sync.start()
            self.sync_label.setText("Sync: connecting…")
        return self.sync

    def on_sync_status(self, s):
        when = f" {datetime.fromtimestamp(s['time']).strftime('%H:%M')}" if s["state"] == "ok" and s.get("time") else ""
        text = {"ok": "Sync: up to date" + when + (" (some notes not synced)" if "not synced" in s["message"] else ""), "offline": "Sync: other device offline", "idle": "Sync: no device yet",
                "starting": "Sync: connecting…", "error": "Sync: unavailable"}.get(s["state"], "Sync: " + s["message"])
        self.sync_label.setText(text)
        self.sync_label.setToolTip(s["message"])

    def on_sync_paired(self, error):
        if error:
            QMessageBox.warning(self, APP_NAME, error)
        else:
            QMessageBox.information(self, APP_NAME, "Device added. Your notes will now stay in step whenever both "
                                    "devices have SimpleBrain open.")

    def on_sync_dialog(self):
        svc = self.start_sync()
        if svc is None:
            self.show_error("Device sync isn't available on this computer yet (its sync library has no build for it). "
                            "Everything else works; your notes are plain files you can copy.")
            return
        try:
            code = svc.code()
        except Exception as e:  # iroh not installed in this build
            self.show_error(f"Sync isn't available in this copy of SimpleBrain ({e}).")
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("Sync devices")
        dlg.setMinimumWidth(560)
        lay = QVBoxLayout(dlg)
        lay.addWidget(QLabel("<b>This device's code</b><br>On your other device, open Sync… and enter this under "
                             "“Add a device”. Anyone with this code can join your notes, so only share it with yourself."))
        row = QHBoxLayout()
        box = QLineEdit(code)
        box.setReadOnly(True)
        row.addWidget(box, 1)

        def new_code():
            if QMessageBox.question(dlg, APP_NAME, "Make a new code? The old one stops working for adding "
                                    "devices. Devices already added stay added.") == QMessageBox.Yes:
                box.setText(svc.new_code())
                show_qr()

        def copy():
            QApplication.clipboard().setText(box.text())
            copy_btn.setText("Copied")

        copy_btn = self._button("Copy", copy)
        row.addWidget(copy_btn)
        row.addWidget(self._button("New code", new_code))
        lay.addLayout(row)
        qr = QLabel()
        qr.setAlignment(Qt.AlignCenter)

        def show_qr():
            try:  # the typed/pasted code always works; the picture is a convenience
                qr.setPixmap(qr_pixmap(box.text().replace("-", "")))
                qr.setToolTip("The same code as a QR picture, for scanning from another device")
            except ImportError:
                qr.hide()
        show_qr()
        lay.addWidget(qr)
        lay.addWidget(QLabel("<b>Add a device</b><br>Enter the code shown on the other device:"))
        row2 = QHBoxLayout()
        entry = QLineEdit()
        entry.setPlaceholderText("Paste the other device's code")
        row2.addWidget(entry, 1)

        def add():
            text = entry.text()
            try:
                devsync.parse_code(text)
            except ValueError as e:
                QMessageBox.warning(dlg, APP_NAME, str(e))
                return
            entry.clear()
            self.sync_label.setText("Sync: adding device…")

            def work():
                try:
                    svc.pair(text)
                    self.bridge.sync_paired.emit("")
                except Exception as e:  # offline, wrong code, other device not open
                    self.bridge.sync_paired.emit(str(e) or "Couldn't reach that device. Is SimpleBrain open "
                                                 "there, and are both online?")
            threading.Thread(target=work, daemon=True).start()

        row2.addWidget(self._button("Add device", add))
        lay.addLayout(row2)
        peers = len(svc.peers())
        lay.addWidget(QLabel(f"Devices added: {peers}. Both devices need SimpleBrain open to sync; "
                             "one that's off catches up when it's back."))
        row3 = QHBoxLayout()
        row3.addStretch(1)
        row3.addWidget(self._button("Sync now", svc.sync_now))
        row3.addWidget(self._button("Close", dlg.accept))
        lay.addLayout(row3)
        dlg.exec()

    # -- inbox --
    def build_inbox(self):
        self.inbox_list = QListWidget()
        return (*panel_head("Inbox", hint="Everything you capture lands here. File it as a Task, Event or Note."),
                None, self.inbox_list)

    def refresh_inbox(self):
        self.inbox_list.clear()
        pending = core.parse_inbox()
        if not pending:
            self.inbox_list.addItem("Inbox clear — type above to capture something.")
        for item in pending:
            w = QWidget()
            col = QVBoxLayout(w)
            col.setContentsMargins(4, 2, 4, 2)
            top = QHBoxLayout()
            lbl = QLabel(item["text"])
            lbl.setWordWrap(True)
            top.addWidget(lbl, 1)
            for label, handler in (("Edit", self.on_edit_inbox), ("Delete", self.on_delete_inbox)):
                top.addWidget(self._small_button(label, lambda h=handler, it=item: h(it)))
            col.addLayout(top)
            row = QHBoxLayout()
            row.addWidget(QLabel("File as:"))
            for label, handler in (("Task", self.on_classify_task), ("Event", self.on_classify_event),
                                   ("Thought/Note", self.on_classify_note)):
                row.addWidget(self._small_button(label, lambda h=handler, it=item: h(it)))
            row.addStretch(1)
            col.addLayout(row)
            li = QListWidgetItem()
            li.setSizeHint(w.sizeHint())
            self.inbox_list.addItem(li)
            self.inbox_list.setItemWidget(li, w)

    def on_edit_inbox(self, item):
        text = self.ask_edited_text("Edit Inbox item", item["text"])
        if text is None:
            return
        if not self.edit_in_file(core.INBOX_FILE, lambda: core.edit_inbox_item(item, text)):
            self.show_error(self.STALE_MSG)
        self.refresh_inbox()

    def on_delete_inbox(self, item):
        if not self.confirm_delete(item["text"]):
            return
        if not self.edit_in_file(core.INBOX_FILE, lambda: core.delete_inbox_item(item)):
            self.show_error(self.STALE_MSG)
        self.refresh_inbox()

    def on_classify_task(self, item):
        due = self.ask_text("Due date (optional)", "fri, tomorrow, nov 5 or MM-DD-YYYY; blank for none")
        if due is None:
            return
        due = due.strip()
        if due and not (due := self.read_date(due, "item stays in Inbox, nothing was lost.")):
            return
        if core.classify_as_task(item, due.isoformat() if due else None) is False:
            self.show_error(self.STALE_MSG)
        self.refresh_inbox()
        self.refresh_tasks()

    def on_classify_event(self, item):
        d = self.ask_text("Event date", "fri, tomorrow, nov 5 or MM-DD-YYYY")
        if not d or not d.strip():
            return
        d = self.read_date(d.strip(), "item stays in Inbox, nothing was lost.")
        if not d or not self.confirm_past_date(d):
            return
        t = (self.ask_text("Event time (optional)", "e.g. 14:30 or 2:30pm, blank for all-day") or "").strip()
        if t and not (t := self.read_time(t, "item stays in Inbox, nothing was lost.")):
            return
        if core.classify_as_event(item, d.isoformat(), t or None) is False:
            self.show_error(self.STALE_MSG)
        self.refresh_inbox()
        self.refresh_calendar()

    def on_classify_note(self, item):
        if core.classify_as_note(item) is None:
            self.show_error(self.STALE_MSG)
        self.refresh_notes_list()
        self.graph.recompute()
        self.refresh_dataview()
        self.refresh_inbox()

    # -- tasks --
    def build_tasks(self):
        self.tasks_list = QListWidget()
        self.tasks_list.setWordWrap(True)  # long tasks wrap instead of running off the panel
        self.tasks_list.itemChanged.connect(self.on_task_item_changed)
        self.task_buttons = RowButtons(self.tasks_list, self.task_row_buttons)
        self.spread_button = self._button("Spread out", self.on_spread_out)
        self.spread_button.setToolTip("More is due by today than one day holds. This moves the extras to the lightest "
                                      "days this week (never a shift day, never more than three a day).")
        self.spread_button.hide()
        return (*panel_head("Tasks", self.spread_button, self._button("Refresh", self.refresh_tasks),
                            hint="Every line starting 't ' in your notes. "
                                 "Add due:MM-DD-YYYY to give it a date. 'i …' sends a line to the Inbox, "
                                 "'c MM-DD-YYYY [time] title' to the Calendar."),
                None, self.tasks_list)

    TASK_ROWS = 40  # per group: enough to see what's coming, few enough to redraw at once

    def refresh_tasks(self):
        """Every open task as a light checkable row: a widget per task made one tick on a big vault freeze the
        window for seconds. The selected row gets its Edit and Delete buttons (task_row_buttons)."""
        lst = self.tasks_list
        lst.blockSignals(True)
        lst.setUpdatesEnabled(False)
        lst.clear()
        self.task_buttons.show_for(None)
        buckets = core.bucket_tasks(core.parse_tasks())
        try:  # the plan workbook's actions due by today, tickable here like any task (simplebrain_today.plan_items)
            plan = today_note.plan_path()
            acts = today_note.plan_items(plan) if plan else []
        except (OSError, ValueError):
            acts = []
        for a in acts:
            a["plan"] = True
            buckets["Overdue" if a["due"] < date.today() else "Today"].insert(0, a)
        more_due = len(buckets["Overdue"]) + len(buckets["Today"])  # counted before the lists are cut to TASK_ROWS
        if not any(buckets.values()):
            lst.addItem("No open tasks — you're clear.")
        for bucket in ("Overdue", "Today", "Upcoming", "No date"):
            if not buckets[bucket]:
                continue
            more = len(buckets[bucket]) - self.TASK_ROWS
            if more > 0:  # a row is a handful of widgets: hundreds of them made every refresh take seconds
                buckets[bucket] = sorted(buckets[bucket], key=lambda t: (t["due"] or date.max, t["file"]))[:self.TASK_ROWS]
            head = QListWidgetItem(bucket)
            f = head.font()
            f.setBold(True)
            head.setFont(f)
            head.setFlags(Qt.ItemIsEnabled)  # not selectable, but not greyed out
            lst.addItem(head)
            for t in buckets[bucket]:
                li = QListWidgetItem(f"{core.due_for_display(t['text'])}   · " +
                                     ("from the plan" if t.get("plan") else core.note_title(t["file"])))
                li.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable)
                li.setCheckState(Qt.Unchecked)
                li.setData(Qt.UserRole, t)
                li.setToolTip(f"From {core.note_title(t['file'])}. Tick it when it's done.")
                lst.addItem(li)
            if more > 0:
                tail = QListWidgetItem(f"…and {more} more (the top bar finds any of them)")
                tail.setFlags(Qt.ItemIsEnabled)
                tail.setForeground(QColor("gray"))
                lst.addItem(tail)
        lst.setUpdatesEnabled(True)
        lst.blockSignals(False)
        due_now = more_due
        self.spread_button.setVisible(due_now > workday.PER_DAY)
        self.spread_button.setText(f"Spread out ({due_now - workday.PER_DAY})" if due_now > workday.PER_DAY else "Spread out")
        self.schedule_today()  # every task change passes through here

    def on_spread_out(self):
        self.save_current()
        moved = workday.spread_out()
        if self.current_note:
            self.reconcile_outside()
        self.refresh_tasks()
        if moved:
            self.card(f"<b>Moved {len(moved)} to lighter days</b><br>" + "<br>".join(
                f"{html.escape(t)} → {d.strftime('%a %b')} {d.day}" for t, d in moved[:6]) +
                "<br>Today is three things again.", [("OK", lambda c: None)], seconds=20)
        else:
            self.save_status.setText("No room in the coming week; nothing moved.")

    def on_task_item_changed(self, item):
        t = item.data(Qt.UserRole)
        if isinstance(t, dict) and item.checkState() == Qt.Checked:
            self.plan_tick(t) if t.get("plan") else self.on_task_toggle(t)

    def plan_tick(self, act):
        """A workbook action ticked here: done in SimpleBrain (the workbook is never written), and the same thing written
        as a task in a note is ticked with it, so nothing has to be marked twice."""
        today_note.mark_plan_done(act)
        self.learned("tick")
        if hasattr(self, "watch_state"):
            watch.tick_done(self.watch_state["day"], act["text"])
        for t in core.parse_tasks():  # its twin in a note, whatever date each was given
            if not t["done"] and today_note.same_action(t["text"], act["text"]):
                self.edit_in_file(t["file"], lambda t=t: core.toggle_task(t))
        self.after_tick()

    def after_tick(self):
        QTimer.singleShot(0, self.refresh_tasks)
        if hasattr(self, "watch_state"):
            self.check_three()  # the count at the top moves the moment you tick, not after Today is rebuilt

    def task_row_buttons(self, item):
        """Edit and Delete for the selected or hovered task (RowButtons); a plan action is changed in its workbook."""
        t = item.data(Qt.UserRole)
        if not isinstance(t, dict) or t.get("plan"):
            return []
        return [self._small_button("Edit", lambda t=t: self.on_edit_task(t)),
                self._small_button("Delete", lambda t=t: self.on_delete_task(t))]

    def changeEvent(self, e):
        """Coming back to SimpleBrain picks up what changed elsewhere, like a plan item marked Done in the workbook."""
        super().changeEvent(e)
        if self.tutorial_locked() and (self.isMinimized() or (e.type() == e.Type.ActivationChange
                                                               and QApplication.activeWindow() is None)):
            QTimer.singleShot(250, self.back_to_tutorial)  # the tutorial is the way in: not minimized, not left
        if (e.type() == e.Type.ActivationChange and self.isActiveWindow() and hasattr(self, "notes_list")
                and time.monotonic() - self._today_at > 120):  # not on every click back into the window
            self.schedule_today(0)

    def back_to_tutorial(self):
        if not self.tutorial_locked() or QApplication.activeWindow() is not None:
            return  # done meanwhile, or one of SimpleBrain's own boxes (a due date, a title) has the keys
        self.showNormal()
        self.raise_()
        self.activateWindow()
        if desk.x11() and desk.have("wmctrl"):  # Xfce's focus guard would otherwise only blink the taskbar
            desk.activate(hex(int(self.winId())))
        self.tour.nag()

    def schedule_today(self, ms=1500):
        """Today is rebuilt off the UI thread, once things settle: never in the way of a click."""
        if not hasattr(self, "_today_debounce"):
            self._today_debounce = QTimer(self, singleShot=True)
            self._today_debounce.timeout.connect(self.update_today)
        self._today_debounce.start(ms)

    def update_today(self):
        """Rebuild the Today note (simplebrain_today) in the background; reload it here if it changed. Only once
        there is one (File > Today makes it): SimpleBrain makes no notes you didn't ask for."""
        if not os.path.exists(os.path.join(core.VAULT, today_note.note_name())):
            return
        if self._today_busy:
            self.schedule_today()  # one at a time; try again when this one is done
            return
        self._today_busy, self._today_at = True, time.monotonic()
        vault, ics = core.VAULT, self._ics_text

        def work():
            try:
                result = today_note.update(vault, ics_text=ics)
            except Exception:  # a broken workbook or note never takes the window down
                result = None
            self.bridge.run_ui.emit((lambda: self.today_done(vault, result), {"done": threading.Event()}))
        threading.Thread(target=work, daemon=True).start()

    def today_done(self, vault, result):
        self._today_busy = False
        if not result or vault != core.VAULT:
            return
        name, wrote = result
        if hasattr(self, "watch_state"):
            self.check_three()
        if wrote:
            if name == self.current_note:
                self.reconcile_outside()
            elif self.notes_list.count() and not any(self.notes_list.item(i).data(Qt.UserRole) == name
                                                     for i in range(self.notes_list.count())):
                QTimer.singleShot(0, self.refresh_notes_list)

    def on_task_toggle(self, task):
        self.learned("tick")
        if hasattr(self, "watch_state") and not task.get("done"):
            watch.tick_done(self.watch_state["day"], task["text"])  # the score counts what got done, not time at a window
        nxt = self.edit_in_file(task["file"], lambda: core.toggle_task(task))
        if nxt:
            self.save_status.setText(f"Done for today; back {nxt.strftime('%a %b')} {nxt.day}.")
        if not task.get("done"):  # the same action in the plan workbook is done with it, whatever its date
            try:
                plan = today_note.plan_path()
                for a in today_note.plan_items(plan, everything=True) if plan else []:
                    if today_note.same_action(task["text"], a["text"]):
                        today_note.mark_plan_done(a)
            except (OSError, ValueError):
                pass
        self.after_tick()

    def on_edit_task(self, task):
        text = self.ask_edited_text("Edit task (due date: due:MM-DD-YYYY)", core.due_for_display(task["text"]))
        if text is None:
            return
        due = core.DUE_RE.search(text)
        if due and not self.read_date(due.group(1), "task was not changed."):
            return
        text = core.due_for_storage(text)
        if not self.edit_in_file(task["file"], lambda: core.edit_task(task, text)):
            self.show_error(self.STALE_MSG)
        QTimer.singleShot(0, self.refresh_tasks)

    def on_delete_task(self, task):
        if not self.confirm_delete(task["text"]):
            return
        if not self.edit_in_file(task["file"], lambda: core.delete_task(task)):
            self.show_error(self.STALE_MSG)
        QTimer.singleShot(0, self.refresh_tasks)

    # -- calendar --
    def build_calendar(self):
        self.sync_button = self._button("Sync", lambda: self.refresh_calendar(sync=True))
        controls = QWidget()
        lay = QVBoxLayout(controls)
        lay.setContentsMargins(0, 0, 0, 0)
        self.calendar_status = QLabel()
        self.calendar_status.setWordWrap(True)
        lay.addWidget(self.calendar_status)
        add = QHBoxLayout()
        self.event_date = QLineEdit()
        self.event_date.setPlaceholderText("fri, nov 5…")
        self.event_date.setMaximumWidth(110)
        self.event_title = QLineEdit()
        self.event_title.setPlaceholderText("Event title")
        add.addWidget(self.event_date)
        add.addWidget(self.event_title, 1)
        add.addWidget(self._button("+ Add", self.on_add_event))
        lay.addLayout(add)
        self.calendar_list = QListWidget()
        return (*panel_head("Calendar", self._button("Choose file…", self.on_choose_calendar_file),
                            self._button("Link…", self.on_connect_calendar), self.sync_button,
                            hint="Your events, plus a calendar file (.ics, or .csv with Date and Title "
                                 "columns) or link for the next 14 days. "
                                 "Put [[Note Name]] in a title to get a button that opens that note."),
                controls, self.calendar_list)

    def on_choose_calendar_file(self):
        current = core.resolve_calendar_file()
        start = os.path.dirname(current) if current else os.path.expanduser("~")
        path, _ = QFileDialog.getOpenFileName(self, "Choose a calendar file", start,
                                              "Calendars (*.ics *.csv);;All files (*)")
        if not path:
            return
        try:
            core.set_calendar_file(path)
        except ValueError as err:
            self.show_error(str(err))
            return
        self._ics_text = None
        self.refresh_calendar(sync=True)

    def on_connect_calendar(self):
        # Blank field on purpose: the stored URL is a secret and is never shown back.
        url = self.ask_text("Connect external calendar",
                            "Paste the calendar address: an iCal/.ics link is read-only; a CalDAV address "
                            "(Fastmail, iCloud, Nextcloud…) goes both ways, so the events you add here are sent to it.\n"
                            "Treat it like a password. Leave blank to disconnect.")
        if url is None:
            return
        try:
            if core.caldav_needs_login(url):
                pw, ok = QInputDialog.getText(self, "Calendar password", "App password for this calendar:",
                                              QLineEdit.Password)
                if not ok:
                    return
                url = core.caldav_with_login(url, pw)
            core.set_ics_url(url)
        except ValueError as err:
            self.show_error(str(err))
            return
        self._ics_text = None
        self.refresh_calendar(sync=True)

    def on_add_event(self):
        d, title = self.event_date.text().strip(), self.event_title.text().strip()
        if not (d and title):
            return
        d = self.read_date(d, "event was not added.")
        if not d or not self.confirm_past_date(d):
            return
        core.add_local_event(d.isoformat(), None, title)
        self.event_date.clear()
        self.event_title.clear()
        self.refresh_calendar()

    def refresh_calendar(self, sync=False):
        # One fetch in flight at a time, and
        # "never fetched" triggers once, not on every local edit.
        if not core.should_start_ics_fetch(sync, self._syncing, self._ics_fetch_attempted):
            if self._syncing:
                self._resync = self._resync or sync  # run again when the current fetch lands
            else:
                self.render_calendar()
            return
        self._ics_fetch_attempted = self._syncing = True
        self.calendar_status.setText("Syncing…")
        self.sync_button.setEnabled(False)

        def work():
            try:
                text, live = core.fetch_ics()
            except Exception:
                text, live = None, False
            self.bridge.ics_fetched.emit(text, live)
        threading.Thread(target=work, daemon=True).start()

    def on_ics_fetched(self, text, live):
        self._syncing = False
        self._ics_text = text
        self.sync_button.setEnabled(True)
        if text is None:
            self.calendar_status.setText("<span style='color:#c33'>No calendar feed configured or reachable — "
                                         "showing local events only.</span>")
        elif not live:
            self.calendar_status.setText("<span style='color:#c80'>Offline — showing last synced calendar, "
                                         "not live.</span>")
        else:
            f = core.resolve_calendar_file()
            self.calendar_status.setText(f"Loaded {html.escape(os.path.basename(f))}." if f else "Synced.")
        self.render_calendar()
        if self._resync:  # the source changed (or Sync was clicked) while that fetch was running
            self._resync = False
            self.refresh_calendar(sync=True)

    def render_calendar(self):
        self.calendar_list.clear()
        events = core.upcoming_events(ics_text=self._ics_text)
        if not events:
            self.calendar_list.addItem("No upcoming events (synced feed: next 14 days).")
        for e in events:
            when = core.show_date(e["date"]) + (f" {e['time']}" if e["time"] else "")
            tag = "synced" if e["source"] == "ics" else "local"
            w = QWidget()
            row = QHBoxLayout(w)
            row.setContentsMargins(4, 0, 4, 0)
            lbl = QLabel(f"[{tag}] {when} — {e['title']}")
            lbl.setWordWrap(False)  # one line per event: wrapped text spilled over the next row (its full title: hover)
            lbl.setToolTip(e["title"])
            lbl.setSizePolicy(QSizePolicy.Ignored, lbl.sizePolicy().verticalPolicy())
            row.addWidget(lbl, 1)
            for link in sorted(set(core.parse_links(e["title"]))):  # [[Note]] in a title opens that note
                row.addWidget(self._button(f"[[{link}]]", lambda l=link: self.open_link(l + ".md")))
            if e["source"] == "local":
                row.addWidget(self._button("Edit", lambda e=e: self.on_edit_event(e)))
                row.addWidget(self._button("×", lambda e=e: self.on_delete_event(e)))
            li = QListWidgetItem()
            li.setSizeHint(w.sizeHint())
            self.calendar_list.addItem(li)
            self.calendar_list.setItemWidget(li, w)

    def on_delete_event(self, event):
        if not self.confirm_delete(event["title"]):
            return
        if not self.edit_in_file(core.CALENDAR_FILE, lambda: core.delete_local_event(event)):
            self.show_error(self.STALE_MSG)
        self.refresh_calendar()

    def ask_event(self, event):
        """(date, time, title) as typed in one dialog, or None if cancelled."""
        dlg = QDialog(self)
        dlg.setWindowTitle("Edit event")
        form = QFormLayout(dlg)
        fields = (QLineEdit(core.show_date(event["date"])), QLineEdit(event["time"] or ""),
                  QLineEdit(event["title"]))
        fields[1].setPlaceholderText("e.g. 14:30 or 2:30pm, blank for all-day")
        for label, f in zip(("Date (MM-DD-YYYY)", "Time", "Title"), fields):
            form.addRow(label, f)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        form.addRow(buttons)
        fields[2].setMinimumWidth(320)
        return tuple(f.text().strip() for f in fields) if dlg.exec() == QDialog.Accepted else None

    def on_edit_event(self, event):
        answer = self.ask_event(event)
        if answer is None:
            return
        ds, ts, title = answer
        if not title:
            self.show_error("An event needs a title — event was not changed.")
            return
        d = self.read_date(ds, "event was not changed.")
        if not d:
            return
        if ts and not (ts := self.read_time(ts, "event was not changed.")):
            return
        if not self.confirm_past_date(d):
            return
        if not self.edit_in_file(core.CALENDAR_FILE,
                                 lambda: core.edit_local_event(event, d.isoformat(), ts or None, title)):
            self.show_error(self.STALE_MSG)
        self.refresh_calendar()

    # -- dataview --
    def build_dataview(self):
        controls = QWidget()
        filters = QHBoxLayout(controls)
        filters.setContentsMargins(0, 0, 0, 0)
        filters.addWidget(QLabel("Tag:"))
        self.dv_tag = QComboBox()
        self.dv_tag.installEventFilter(NoWheel(self.dv_tag))
        self.dv_tag.setFocusPolicy(Qt.ClickFocus)
        self.dv_tag.currentIndexChanged.connect(lambda *_: self.refresh_dataview())
        filters.addWidget(self.dv_tag)
        self.dv_search = QLineEdit()
        self.dv_search.setPlaceholderText("Search title, or a query: TABLE status, due FROM #project SORT due")
        self.dv_search.setToolTip("Type part of a title, or a Dataview query (TABLE, LIST or TASK, as in Obsidian):\n"
                                  "TABLE status, due FROM #project WHERE status != \"done\" SORT due\n"
                                  "LIST FROM [[Walker Supply]]\nTASK WHERE !completed AND due <= date(today)")
        self.dv_search.textChanged.connect(lambda *_: self.refresh_dataview())
        filters.addWidget(self.dv_search, 1)
        self.dv_table = QTableWidget(0, 4)
        self.dv_table.setHorizontalHeaderLabels(["Title", "Tags", "Links", "Linked from"])
        header = self.dv_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeToContents)  # full text; a wide table scrolls sideways
        header.setStretchLastSection(True)
        self.dv_table.setHorizontalScrollMode(QTableWidget.ScrollPerPixel)
        self.dv_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.dv_table.itemSelectionChanged.connect(self.light_graph)
        self.dv_table.verticalHeader().hide()
        self.dv_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.dv_table.setSortingEnabled(True)
        self.dv_table.cellDoubleClicked.connect(
            lambda r, _c: self.dv_table.item(r, 0) and self.dv_table.item(r, 0).data(Qt.UserRole)
            and self.open_note(self.dv_table.item(r, 0).data(Qt.UserRole)))
        self.dv_table.cellClicked.connect(self.on_dv_cell_clicked)
        return (*panel_head("Dataview", hint="Every note. Filter by #tag or title, or click a row; those notes light up "
                                             "orange in the graph. Double-click to open. Click a Links or Linked from "
                                             "number to see those notes. Fields you write (status:: active) become "
                                             "columns by themselves; a query in the box works as in Obsidian."),
                controls, self.dv_table)

    def on_dv_cell_clicked(self, r, c):
        if dv.is_query(self.dv_search.text()):
            return  # a query's columns are its own
        if c in (2, 3):  # Links / Linked from: list the connected notes to jump to
            menu = self.connections_menu(self.dv_table.item(r, 0).data(Qt.UserRole))
            menu.exec(QCursor.pos())

    def connections_menu(self, filename):
        row = self._dv_rows[filename]
        menu = QMenu(self)
        for heading, files in (("Links to", [t + ".md" for t in row["links"]]),
                               ("Linked from", row["linked_from"])):
            menu.addSection(heading)
            if not files:
                menu.addAction("(none)").setEnabled(False)
            for f in files:
                missing = not os.path.exists(os.path.join(core.VAULT, f))
                act = menu.addAction(core.note_title(f) + ("  (not written yet)" if missing else ""))
                act.triggered.connect(lambda *_, f=f: self.open_link(f))
        return menu

    def refresh_dataview(self):
        query = self.dv_search.text().strip()
        if dv.is_query(query):
            return self.show_dataview_query(query)
        rows = core.note_rows()
        self._dv_rows = {r["file"]: r for r in rows}
        options = ["All tags"] + sorted({t for r in rows for t in r["tags"]})
        current = self.dv_tag.currentText()
        self.dv_tag.blockSignals(True)
        self.dv_tag.clear()
        self.dv_tag.addItems(options)
        self.dv_tag.setCurrentIndex(options.index(current) if current in options else 0)
        self.dv_tag.blockSignals(False)
        tag = self.dv_tag.currentText()
        shown = core.filter_note_rows(rows, tag=None if tag == "All tags" else tag,
                                      search=self.dv_search.text().strip())
        try:  # the fields your notes use become columns by themselves (Dataview's inline fields: status:: active)
            pages = {p["file"]["path"]: p for p in dv.pages()}
            extra = dv.common_fields(all_pages=list(pages.values()))
        except OSError:
            pages, extra = {}, []
        self.dv_table.setColumnCount(4 + len(extra))
        self.dv_table.setHorizontalHeaderLabels(["Title", "Tags", "Links", "Linked from"] + extra)
        self.dv_table.setSortingEnabled(False)
        header = self.dv_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)  # sized once after filling, not on every cell (13 s at 600 notes)
        self.dv_table.setRowCount(len(shown))
        for i, r in enumerate(shown):
            title = QTableWidgetItem(r["title"])
            title.setData(Qt.UserRole, r["file"])
            links, linked_from = QTableWidgetItem(), QTableWidgetItem()
            links.setData(Qt.DisplayRole, r["link_count"])  # numeric sort
            linked_from.setData(Qt.DisplayRole, len(r["linked_from"]))
            for cell in (links, linked_from):
                cell.setToolTip("Click to see the connected notes")
            for col, item in enumerate((title, QTableWidgetItem(", ".join(r["tags"])), links, linked_from)):
                self.dv_table.setItem(i, col, item)
            page = pages.get(r["file"], {})
            for j, key in enumerate(extra):
                cell = QTableWidgetItem()
                val = dv.get(page, key)
                sortable = dv.as_cmp(val)[1] if isinstance(val, (int, float)) and not isinstance(val, bool) else dv.show(val)
                cell.setData(Qt.DisplayRole, sortable if val is not None else "")
                self.dv_table.setItem(i, 4 + j, cell)
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        self.dv_table.setSortingEnabled(True)
        filtering = tag != "All tags" or self.dv_search.text().strip()
        self._dv_shown = {r["file"] for r in shown} if filtering else None
        self.light_graph()

    def show_dataview_query(self, query):
        """A Dataview query typed in the panel's box: its table, list or tasks in the panel's table."""
        self._dv_rows = getattr(self, "_dv_rows", {})
        self.dv_table.setSortingEnabled(False)
        try:
            res = dv.run(query, this=self.current_note)
        except dv.DQLError as e:
            self.dv_table.setColumnCount(1)
            self.dv_table.setHorizontalHeaderLabels(["Query"])
            self.dv_table.setRowCount(1)
            self.dv_table.setItem(0, 0, QTableWidgetItem(f"Not a query yet: {e}"))
            return
        headers, rows = self.result_table(res)
        self.dv_table.setColumnCount(len(headers))
        self.dv_table.setHorizontalHeaderLabels(headers)
        self.dv_table.setRowCount(len(rows))
        for i, (path, cells) in enumerate(rows):
            for j, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if j == 0:
                    item.setData(Qt.UserRole, path)
                self.dv_table.setItem(i, j, item)
        self.dv_table.setSortingEnabled(True)
        self._dv_shown = {p for p, _ in rows if p}
        self.light_graph()

    @staticmethod
    def result_table(res):
        """(headers, [(note file or None, [cell texts])]) for any query result."""
        if res["type"] == "TASK":
            return ["Task", "Note"], [(t["path"], [("✓ " if t["completed"] else "☐ ") + core.due_for_display(t["text"]),
                                                   t["file"]["name"]]) for t in res["items"]] if not res["grouped"] else \
                (["Group", "Tasks"], [(None, [dv.show(c) for c in r]) for r in res["rows"]])
        headers = res["headers"] or (["File"] + (["Value"] if res["rows"] and len(res["rows"][0]) > 1 else []))
        out = []
        for r in res["rows"]:
            first = r[0] if r else None
            path = first.path if isinstance(first, dv.Link) else None
            out.append((path, [dv.show(c) for c in r]))
        return headers, out

    def light_graph(self):
        """Selected table rows light up in the graph; with none selected, the filter's matches do."""
        picked = {self.dv_table.item(r, 0).data(Qt.UserRole) for r in {i.row() for i in self.dv_table.selectedItems()}}
        self.graph.highlight = picked or self._dv_shown
        self.graph.update()


def crash_guard(kind, value, tb):
    """An unexpected error is written to crash.log in the settings folder and shown in one line; the window stays
    up and nothing typed is lost (it's saved first)."""
    import traceback
    text = "".join(traceback.format_exception(kind, value, tb))
    try:
        path = os.path.join(core.user_config_dir(), "crash.log")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"--- {datetime.now().isoformat(timespec='seconds')} {core.VERSION}\n{text}\n")
    except OSError:
        pass
    sys.__stderr__ and sys.__stderr__.write(text)
    for w in QApplication.topLevelWidgets():
        if isinstance(w, SimpleBrain):
            try:
                w.save_current()
                w.save_status.setText(f"<span style='color:#ff8a2a'>Something went wrong ({html.escape(str(value)[:80])}); "
                                      "your notes are saved. Details: crash.log in the settings folder.</span>")
            except Exception:
                pass


def instance_name():
    import getpass
    return f"simplebrain-{getpass.getuser()}"


def tell_running(cmd):
    """Hand a command to the SimpleBrain already running (one window); False when none is."""
    sock = QLocalSocket()
    sock.connectToServer(instance_name())
    if not sock.waitForConnected(500):
        return False
    sock.write((cmd + "\n").encode())
    sock.flush()
    sock.waitForBytesWritten(1000)
    sock.disconnectFromServer()
    return True


def listen_for_commands(win):
    server = QLocalServer(win)
    QLocalServer.removeServer(instance_name())  # a crashed run leaves its socket file behind
    server.listen(instance_name())

    def on_connection():
        c = server.nextPendingConnection()
        c.readyRead.connect(lambda: [win.handle_command(x) for x in bytes(c.readAll()).decode(errors="ignore").split()])
    server.newConnection.connect(on_connection)
    return server


def main():
    if "--selftest" in sys.argv:
        core.selftest()
        import simplebrain_ics
        simplebrain_ics.selftest()  # also proves the time-zone database made it into the build
        return 0
    if "--version" in sys.argv:
        print(core.VERSION)
        return 0
    if (sys.platform.startswith("linux") and os.environ.get("XDG_SESSION_TYPE") == "wayland"
            and os.environ.get("DISPLAY") and not os.environ.get("QT_QPA_PLATFORM")):
        os.environ["QT_QPA_PLATFORM"] = "xcb"  # through XWayland, so files open beside the note
    app = QApplication(sys.argv)
    sys.excepthook = crash_guard
    cmd = "toggle" if "--toggle" in sys.argv else "show"
    if tell_running(cmd):  # opened again from its icon or the menu: the running one answers
        return 0
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(core.VERSION)
    app.setDesktopFileName("simplebrain")
    icon = resource_path("icon.png")
    if os.path.exists(icon):
        app.setWindowIcon(QIcon(icon))
    win = SimpleBrain()
    win.server = listen_for_commands(win)
    if os.environ.get("APPIMAGE"):
        desk.appimage_menu_entry(os.environ["APPIMAGE"], resource_path("icon.png"))
    win.show()
    QTimer.singleShot(400, win.maybe_start_tour)  # after the window has its real size
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
