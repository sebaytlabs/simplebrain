"""Money, forward (Qt): the ring of how far the money lasts and the road ahead, from the Budget note
(simplebrain_budget). Drawn in Glass's warm colors: dark, off-white, one gold accent, coral when money runs short.
"""
import math

from PySide6.QtCore import QPointF, QRectF, Qt, QVariantAnimation, QEasingCurve
from PySide6.QtGui import QColor, QFont, QIcon, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QRadialGradient
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

import simplebrain_budget as budget

# ---------- money, forward ----------
# Drawn in Glass's warm colors whatever the theme: dark, off-white, one gold accent; coral when money runs short.
M_BG, M_INK, M_MUTED, M_GOLD, M_WARN, M_BAD = "#14120f", "#f2ede4", "#a39b8f", "#e3b25a", "#e58a6e", "#d9534f"
M_GOLD_DIM = "rgba(227,178,90,0.45)"

def ring_color(frac):
    return QColor(M_GOLD) if frac >= 0.999 else QColor(M_WARN) if frac >= 0.35 else QColor(M_BAD)


def ring_icon(frac, side=22):
    """The small ring on the top bar's money button: how far the money lasts, at a glance."""
    pm = QPixmap(side * 2, side * 2)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    r = QRectF(5, 5, side * 2 - 10, side * 2 - 10)
    p.setPen(QPen(QColor(227, 178, 90, 60), 5))
    p.drawEllipse(r)
    p.setPen(QPen(ring_color(frac), 5, Qt.SolidLine, Qt.FlatCap))
    p.drawArc(r, 90 * 16, -int(360 * 16 * max(0.02, frac)))
    p.end()
    return QIcon(pm)


class MoneyView(QWidget):
    """The arc ring (how far the money lasts, what you end with) and the road ahead (balance day by day, goals as
    diamonds that light up when funded). Changes animate, so a paycheck or a skipped goal is something you see move."""

    def __init__(self):
        super().__init__()
        self.setMinimumSize(640, 360)
        self.p, self.frac, self.shown_end, self.delta = None, 1.0, 0.0, None
        self._anim = QVariantAnimation(self, duration=700, easingCurve=QEasingCurve.OutCubic)
        self._anim.valueChanged.connect(self._tick)
        self._from = (1.0, 0.0)
        self._k = 1.0

    def set_projection(self, p, delta=None):
        old = (self.frac, self.shown_end)
        self.p, self.delta = p, delta
        self._target = (budget.runway(p), p["end"])
        self._from = old
        self._anim.stop()
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.start()

    def _tick(self, k):
        self._k = k
        a, b = self._from, self._target
        self.frac = a[0] + (b[0] - a[0]) * k
        self.shown_end = a[1] + (b[1] - a[1]) * k
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        p.fillRect(self.rect(), QColor(M_BG))
        if not self.p or not self.p["series"]:
            p.setPen(QColor(M_MUTED))
            p.drawText(self.rect(), Qt.AlignCenter, "Write cash:: and a few + / - lines in the Budget note")
            return
        side = min(h - 40, int(w * 0.38))
        cx, cy = 20 + side / 2, h / 2
        self.paint_ring(p, QPointF(cx, cy), side / 2)
        self.paint_road(p, QRectF(side + 50, 30, w - side - 70, h - 70))

    def paint_ring(self, p, c, R):
        col = ring_color(self.frac)
        p.setPen(Qt.NoPen)
        halo = QRadialGradient(c, R * 1.1)
        halo.setColorAt(0.55, QColor(col.red(), col.green(), col.blue(), 40))
        halo.setColorAt(1, QColor(col.red(), col.green(), col.blue(), 0))
        p.setBrush(halo)
        p.drawEllipse(c, R * 1.1, R * 1.1)
        segs = 48
        lit = int(round(segs * self.frac))
        for i in range(segs):  # segmented outer ring, lit as far as the money lasts
            a = math.radians(90 - i * 360 / segs)
            a2 = math.radians(90 - (i + 0.72) * 360 / segs)
            path = QPainterPath()
            r1, r2 = R * 0.80, R * 0.97
            path.moveTo(c.x() + r1 * math.cos(a), c.y() - r1 * math.sin(a))
            path.lineTo(c.x() + r2 * math.cos(a), c.y() - r2 * math.sin(a))
            path.lineTo(c.x() + r2 * math.cos(a2), c.y() - r2 * math.sin(a2))
            path.lineTo(c.x() + r1 * math.cos(a2), c.y() - r1 * math.sin(a2))
            path.closeSubpath()
            p.fillPath(path, col if i < lit else QColor(227, 178, 90, 28))
        p.setPen(QPen(QColor(227, 178, 90, 90), 1))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(c, R * 0.74, R * 0.74)
        p.setPen(QPen(QColor(227, 178, 90, 40), 1, Qt.DashLine))
        p.drawEllipse(c, R * 0.62, R * 0.62)
        f = QFont(self.font())
        f.setPixelSize(max(18, int(R * 0.30)))
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor(M_INK) if self.shown_end >= 0 else QColor(M_BAD))
        p.drawText(QRectF(c.x() - R, c.y() - R * 0.30, 2 * R, R * 0.40), Qt.AlignCenter, budget.money(self.shown_end))
        f.setPixelSize(max(11, int(R * 0.09)))
        f.setBold(False)
        p.setFont(f)
        p.setPen(QColor(M_MUTED))
        end = self.p["series"][-1][0]
        p.drawText(QRectF(c.x() - R, c.y() + R * 0.10, 2 * R, R * 0.16), Qt.AlignCenter,
                   f"ON {end.strftime('%b').upper()} {end.day}")
        p.setPen(QColor(col))
        sub = "LASTS ALL THE WAY" if not self.p["out_on"] else \
            f"SHORT FROM {self.p['out_on'].strftime('%b').upper()} {self.p['out_on'].day}"
        p.drawText(QRectF(c.x() - R, c.y() + R * 0.26, 2 * R, R * 0.16), Qt.AlignCenter, sub)
        if self.delta:
            p.setPen(QColor(M_GOLD) if self.delta > 0 else QColor(M_WARN))
            p.drawText(QRectF(c.x() - R, c.y() - R * 0.52, 2 * R, R * 0.18), Qt.AlignCenter,
                       ("▲ " if self.delta > 0 else "▼ ") + budget.money(self.delta, True) + " SINCE YOU LAST LOOKED")

    def paint_road(self, p, box):
        s = self.p["series"]
        vals = [v for _, v in s]
        lo, hi = min(min(vals), 0), max(max(vals), 1)
        span = hi - lo or 1
        n = max(1, len(s) - 1)
        X = lambda i: box.left() + box.width() * i / n
        Y = lambda v: box.bottom() - box.height() * (v - lo) / span
        p.setPen(QPen(QColor(227, 178, 90, 30), 1))
        for k in range(5):
            y = box.top() + box.height() * k / 4
            p.drawLine(QPointF(box.left(), y), QPointF(box.right(), y))
        p.setPen(QPen(QColor(M_WARN), 1, Qt.DashLine))
        p.drawLine(QPointF(box.left(), Y(0)), QPointF(box.right(), Y(0)))
        shown = max(2, int(len(s) * min(1.0, 0.25 + self._k)))  # the line draws itself in when it changes
        line = QPainterPath(QPointF(X(0), Y(vals[0])))
        for i in range(1, shown):
            line.lineTo(X(i), Y(vals[i]))
        area = QPainterPath(line)
        area.lineTo(X(shown - 1), Y(lo))
        area.lineTo(X(0), Y(lo))
        area.closeSubpath()
        g = QLinearGradient(0, box.top(), 0, box.bottom())
        g.setColorAt(0, QColor(227, 178, 90, 70))
        g.setColorAt(1, QColor(227, 178, 90, 0))
        p.fillPath(area, g)
        p.setPen(QPen(QColor(227, 178, 90, 70), 6))
        p.drawPath(line)
        p.setPen(QPen(QColor(M_GOLD), 2))
        p.drawPath(line)
        f = QFont(self.font())
        f.setPixelSize(12)
        p.setFont(f)
        index = {d: i for i, (d, _) in enumerate(s)}
        p.setPen(QColor(M_MUTED))
        p.drawText(QPointF(box.left() - 4 - p.fontMetrics().horizontalAdvance("$0"), Y(0) + 4), "$0")
        top = budget.money(hi)
        p.drawText(QPointF(box.left() - 4 - p.fontMetrics().horizontalAdvance(top), box.top() + 4), top)
        placed = []
        for gl in self.p["goals"]:  # goals: amber diamonds when the money is there, hollow red when it isn't
            i = index.get(gl["date"])
            if i is None or gl["funded"] is None:
                continue
            x, y = X(i), Y(vals[i])
            d = QPainterPath()
            d.moveTo(x, y - 8)
            d.lineTo(x + 8, y)
            d.lineTo(x, y + 8)
            d.lineTo(x - 8, y)
            d.closeSubpath()
            if gl["funded"]:
                p.fillPath(d, QColor(M_GOLD))
            p.setPen(QPen(QColor(M_GOLD) if gl["funded"] else QColor(M_BAD), 2))
            p.drawPath(d)
            label = gl["title"] if gl["funded"] else f"{gl['title']}: needs {budget.money(gl['short'])} more"
            lw = p.fontMetrics().horizontalAdvance(label)
            ly = y - 12
            while any(abs(ly - py) < 16 and abs(x - px) < max(lw, pw) for px, py, pw in placed):
                ly -= 16  # stack labels that would sit on each other
            lx = min(x + 10, box.right() - lw)
            p.drawText(QPointF(lx, max(box.top() + 12, ly)), label)
            placed.append((x, ly, lw))
        ld, lv = self.p["low"]
        i = index.get(ld, 0)
        p.setPen(QColor(M_MUTED))
        low = f"lowest {budget.money(lv)} · {ld.strftime('%b')} {ld.day}"
        lw = p.fontMetrics().horizontalAdvance(low)
        p.drawText(QPointF(min(X(i) + 6, box.right() - lw), min(Y(lv) + 18, box.bottom() - 6)), low)
        p.setPen(QColor(M_INK))
        p.drawText(QPointF(box.left(), box.top() - 8), "THE ROAD AHEAD")
        p.setPen(QColor(M_MUTED))
        p.drawText(QPointF(box.left(), box.bottom() + 20), f"{s[0][0].strftime('%b')} {s[0][0].day}")
        end = f"{s[-1][0].strftime('%b')} {s[-1][0].day}"
        p.drawText(QPointF(box.right() - p.fontMetrics().horizontalAdvance(end), box.bottom() + 20), end)


class MoneyWindow(QDialog):
    """Money, forward: the view, the goals to switch on and off, and the note it comes from."""

    def __init__(self, parent, on_open_note):
        super().__init__(parent)
        self.setWindowTitle("Money, forward")
        self.resize(1000, 600)
        self.setStyleSheet(f"QDialog {{ background: {M_BG}; }} QLabel {{ color: {M_INK}; }}"
                           f"QPushButton {{ background: rgba(120,200,235,0.06); color: {M_INK}; border: 1px solid {M_GOLD_DIM};"
                           f" border-radius: 3px; padding: 6px 12px; font-weight: 600; }}"
                           f"QPushButton:checked {{ border-color: {M_GOLD}; color: {M_GOLD}; }}"
                           f"QPushButton:hover {{ border-color: {M_GOLD}; }}")
        lay = QVBoxLayout(self)
        self.view = MoneyView()
        lay.addWidget(self.view, 1)
        self.line = QLabel()
        self.line.setWordWrap(True)
        lay.addWidget(self.line)
        self.goals_row = QHBoxLayout()
        lay.addLayout(self.goals_row)
        bottom = QHBoxLayout()
        hint = QLabel("Click a goal to leave it out and see what changes. Drop a bank export or your plan workbook on "
                      "SimpleBrain to update today's cash.")
        hint.setStyleSheet(f"color: {M_MUTED}")
        hint.setWordWrap(True)
        bottom.addWidget(hint, 1)
        edit = QPushButton("Edit the Budget note")
        edit.clicked.connect(lambda *_: (on_open_note(budget.NOTE), self.close()))
        bottom.addWidget(edit)
        lay.addLayout(bottom)
        self.skip = set()
        self.b = None

    def show_budget(self, b, delta=None):
        self.b = b
        while self.goals_row.count():
            w = self.goals_row.takeAt(0).widget()
            if w:
                w.deleteLater()
        self.goals_row.addWidget(QLabel("GOALS"))
        self.chips = {}
        for g in b["goals"]:
            btn = QPushButton(f"◆ {g['title']}  {budget.money(-g['amount'])}  {g['date'].strftime('%b')} {g['date'].day}")
            btn.setCheckable(True)
            btn.setChecked(g["title"] not in self.skip)
            btn.toggled.connect(lambda on, t=g["title"]: self.toggle(t, on))
            self.goals_row.addWidget(btn)
            self.chips[g["title"]] = btn
        self.goals_row.addStretch(1)
        self.refresh(delta)

    def toggle(self, title, on):
        (self.skip.discard if on else self.skip.add)(title)
        self.refresh()

    def refresh(self, delta=None):
        p = budget.project(self.b, skip=self.skip)
        self.view.set_projection(p, delta)
        for g in p["goals"]:  # amber when it fits, red when it needs more, plain when left out
            chip = getattr(self, "chips", {}).get(g["title"])
            if chip:
                chip.setStyleSheet("" if g["funded"] is None else f"color: {M_GOLD}; border-color: {M_GOLD};" if g["funded"]
                                   else f"color: {M_BAD}; border-color: {M_BAD};")
                chip.setToolTip("Left out" if g["funded"] is None else "The money is there" if g["funded"]
                                else f"Needs {budget.money(g['short'])} more by then")
        funded = sum(1 for g in p["goals"] if g["funded"])
        counted = sum(1 for g in p["goals"] if g["funded"] is not None)
        self.line.setText(f"<b>{budget.summary(p)}</b>" + (f"  ·  {funded} of {counted} goals funded" if counted else ""))
        return p
