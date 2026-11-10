"""The calendar inside SimpleBrain (Qt): a month to pick a day, that day and the week after it, and add / edit /
delete for every event, Fastmail's included (simplebrain_calendar talks CalDAV, off the UI thread).
Events typed into Calendar.md show here too; saving one from this window moves it to the real calendar with its
place and notes, and the Calendar.md line goes.
"""
import html
import threading
from datetime import date, timedelta

from PySide6.QtCore import QDate, Qt, QTime
from PySide6.QtGui import QFont, QTextCharFormat
from PySide6.QtWidgets import (QCalendarWidget, QCheckBox, QDateEdit, QDialog, QFormLayout, QHBoxLayout, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton,
                               QSplitter, QTimeEdit, QVBoxLayout, QWidget)

import simplebrain_calendar as calendar
import simplebrain_core as core
from simplebrain_mailwin import _Back  # one way to hand thread results to the UI


def qd(d):
    return QDate(d.year, d.month, d.day)


def pyd(q):
    return date(q.year(), q.month(), q.day())


def span(e):
    if not e.get("time"):
        return "All day" + (f" to {e['end_date']:%b} {e['end_date'].day}" if e.get("end_date") else "")
    return e["time"] + (f"–{e['end_time']}" if e.get("end_time") else "")


class EventDialog(QDialog):
    """Title, date, all day or start–end, place, notes. A repeating event keeps its dates (title/place/notes change)."""

    def __init__(self, parent, ev=None, day=None):
        super().__init__(parent)
        ev = ev or {}
        self.setWindowTitle("Edit event" if ev.get("title") else "New event")
        self.resize(560, 480)
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.title = QLineEdit(ev.get("title", ""))
        self.title.setPlaceholderText("What is it?")
        self.day = QDateEdit(qd(ev.get("date") or day or date.today()))
        self.day.setCalendarPopup(True)
        self.day.setDisplayFormat("ddd MM-dd-yyyy")
        self.all_day = QCheckBox("All day")
        self.all_day.setChecked(bool(ev) and not ev.get("time"))
        t0 = ev.get("time") or "09:00"
        t1 = ev.get("end_time") or f"{(int(t0[:2]) + 1) % 24:02d}{t0[2:]}"
        self.start, self.end = QTimeEdit(QTime.fromString(t0, "HH:mm")), QTimeEdit(QTime.fromString(t1, "HH:mm"))
        for w in (self.start, self.end):
            w.setDisplayFormat("h:mm AP")
        self.start.timeChanged.connect(self._keep_length)
        self._len = QTime.fromString(t0, "HH:mm").secsTo(QTime.fromString(t1, "HH:mm"))
        times = QHBoxLayout()
        times.addWidget(self.all_day)
        times.addWidget(self.start)
        times.addWidget(QLabel("to"))
        times.addWidget(self.end)
        times.addStretch(1)
        self.place = QLineEdit(ev.get("location", ""))
        self.place.setPlaceholderText("Where (optional)")
        self.notes = QPlainTextEdit(ev.get("notes", ""))
        self.notes.setPlaceholderText("Notes (optional)")
        form.addRow("Title", self.title)
        form.addRow("Date", self.day)
        form.addRow("When", times)
        form.addRow("Place", self.place)
        lay.addLayout(form)
        lay.addWidget(self.notes, 1)
        if ev.get("repeats"):
            for w in (self.day, self.all_day, self.start, self.end):
                w.setEnabled(False)
            lay.addWidget(QLabel("This event repeats: the title, place and notes change for every date."))
        self.all_day.toggled.connect(lambda on: (self.start.setEnabled(not on), self.end.setEnabled(not on)))
        self.all_day.toggled.emit(self.all_day.isChecked())
        row = QHBoxLayout()
        self.msg = QLabel("")
        row.addWidget(self.msg, 1)
        cancel, save = QPushButton("Cancel"), QPushButton("Save")
        cancel.clicked.connect(self.reject)
        save.clicked.connect(self.check)
        save.setDefault(True)
        row.addWidget(cancel)
        row.addWidget(save)
        lay.addLayout(row)
        self.repeats = bool(ev.get("repeats"))

    def _keep_length(self, t):
        self.end.setTime(t.addSecs(self._len if self._len > 0 else 3600))

    def check(self):
        if not self.title.text().strip():
            self.msg.setText("Give it a title.")
            return
        self.accept()

    def value(self):
        ev = {"title": self.title.text().strip(), "date": pyd(self.day.date()), "location": self.place.text().strip(),
              "notes": self.notes.toPlainText().strip(), "time": None, "end_time": None}
        if not self.all_day.isChecked():
            ev["time"], ev["end_time"] = self.start.time().toString("HH:mm"), self.end.time().toString("HH:mm")
        return ev


class CalendarWindow(QDialog):
    DAYS = 7  # the picked day and the six after it

    def __init__(self, app_window):
        super().__init__(app_window, Qt.Window)
        self.app = app_window
        self.setWindowTitle("Calendar")
        self.resize(1150, 720)
        self.events, self.cal = [], None
        self._back = _Back()
        self._back.done.connect(lambda f: f())
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        self.status = QLabel("")
        top.addWidget(self.status, 1)
        for label, slot in (("Today", self.go_today), ("New event", self.new_event), ("Refresh", self.load)):
            b = QPushButton(label)
            b.clicked.connect(lambda *_, s=slot: s())
            top.addWidget(b)
        lay.addLayout(top)
        split = QSplitter(Qt.Horizontal)
        self.month = QCalendarWidget()
        self.month.setGridVisible(False)
        self.month.setVerticalHeaderFormat(QCalendarWidget.NoVerticalHeader)
        self.month.selectionChanged.connect(self.show_days)
        self.month.currentPageChanged.connect(lambda *_: self.load())
        self.month.activated.connect(lambda q: self.new_event(pyd(q)))  # double-click a day: a new event on it
        split.addWidget(self.month)
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(lambda *_: self.edit_event())
        self.list.currentItemChanged.connect(lambda *_: self._enable())
        rl.addWidget(self.list, 1)
        self.detail = QLabel("")
        self.detail.setWordWrap(True)
        self.detail.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.LinksAccessibleByMouse)
        self.detail.setOpenExternalLinks(True)
        rl.addWidget(self.detail)
        acts = QHBoxLayout()
        self.edit_btn, self.del_btn, self.skip_btn = QPushButton("Edit"), QPushButton("Delete"), QPushButton("Skip this date")
        self.edit_btn.clicked.connect(lambda *_: self.edit_event())
        self.del_btn.clicked.connect(lambda *_: self.delete_event())
        self.skip_btn.clicked.connect(lambda *_: self.skip_date())
        for b in (self.edit_btn, self.del_btn, self.skip_btn):
            acts.addWidget(b)
        acts.addStretch(1)
        rl.addLayout(acts)
        split.addWidget(right)
        split.setSizes([480, 670])
        lay.addWidget(split, 1)
        self._enable()
        self.load()

    # -- data --
    def bg(self, fn, then, doing=""):
        if doing:
            self.status.setText(doing)

        def work():
            try:
                r = fn()
                self._back.done.emit(lambda: then(r))
            except Exception as e:  # network, auth, a calendar that refused the change: say so, keep the window
                why = str(e)  # `e` is cleared when the except block ends; the lambda runs later
                self._back.done.emit(lambda: self.status.setText(
                    f"<span style='color:#e58a6e'>Calendar: {html.escape(why)[:180]}</span>"))
        threading.Thread(target=work, daemon=True).start()

    def window_dates(self):
        first = date(self.month.yearShown(), self.month.monthShown(), 1)
        return first - timedelta(days=7), first + timedelta(days=45)

    def load(self):
        start, end = self.window_dates()

        def fetch():
            self.cal = self.cal or calendar.connected()
            remote = self.cal.events(start, end) if self.cal else []
            local = [{**e, "location": "", "notes": "", "repeats": False} for e in core.read_local_events()
                     if start <= e["date"] <= end]
            return sorted(remote + local, key=lambda e: (e["date"], e["time"] or ""))
        self.bg(fetch, self.loaded, "Loading your calendar…")

    def loaded(self, events):
        self.events = events
        self.month.setDateTextFormat(QDate(), QTextCharFormat())  # clear old bold days
        bold = QTextCharFormat()
        bold.setFontWeight(QFont.Bold)
        for e in events:
            self.month.setDateTextFormat(qd(e["date"]), bold)
        self.status.setText("" if self.cal else "Only SimpleBrain's own events: connect a CalDAV calendar to see and "
                                                "change the rest (Link… in the Calendar panel).")
        self.show_days()

    def show_days(self):
        day = pyd(self.month.selectedDate())
        self.list.clear()
        for i in range(self.DAYS):
            d = day + timedelta(days=i)
            head = QListWidgetItem(("Today · " if d == date.today() else "") + f"{d:%A, %B} {d.day}")
            f = head.font()
            f.setBold(True)
            head.setFont(f)
            head.setFlags(Qt.NoItemFlags)
            self.list.addItem(head)
            todays = [e for e in self.events if e["date"] == d]
            for e in todays:
                it = QListWidgetItem(f"   {span(e)}   {e['title']}" + (f"  ·  {e['location']}" if e.get("location") else "")
                                     + ("  ↻" if e.get("repeats") else ""))
                it.setData(Qt.UserRole, e)
                self.list.addItem(it)
            if not todays:
                none = QListWidgetItem("   —")
                none.setFlags(Qt.NoItemFlags)
                self.list.addItem(none)
        self._enable()

    def current(self):
        it = self.list.currentItem()
        return it.data(Qt.UserRole) if it else None

    def _enable(self):
        e = self.current()
        self.edit_btn.setEnabled(bool(e))
        self.del_btn.setEnabled(bool(e))
        self.skip_btn.setVisible(bool(e and e.get("repeats")))
        if not e:
            self.detail.setText("")
            return
        bits = [f"<b>{html.escape(e['title'])}</b>", f"{e['date']:%A, %B} {e['date'].day} · {span(e)}"]
        if e.get("location"):
            bits.append(html.escape(e["location"]))
        if e.get("notes"):
            bits.append(html.escape(e["notes"]).replace("\n", "<br>"))
        if e.get("repeats"):
            bits.append("<i>Repeats.</i>")
        self.detail.setText("<br>".join(bits))

    def go_today(self):
        self.month.setSelectedDate(QDate.currentDate())
        self.month.showToday()

    def changed(self, what):
        self.status.setText(what)
        self.app.refresh_calendar(sync=True)  # the side panel and Today see it too
        self.load()

    # -- actions --
    def new_event(self, day=None):
        d = EventDialog(self, day=day or pyd(self.month.selectedDate()))
        if not d.exec():
            return
        ev = d.value()
        if self.cal:
            self.bg(lambda: self.cal.create(ev), lambda _: self.changed(f"Added “{ev['title']}”."), "Saving…")
        else:
            core.add_local_event(ev["date"].isoformat(), ev["time"], ev["title"])
            self.changed(f"Added “{ev['title']}”.")

    def edit_event(self):
        e = self.current()
        if not e:
            return
        d = EventDialog(self, e)
        if not d.exec():
            return
        ev = d.value()
        if e.get("source") == "caldav":
            self.bg(lambda: self.cal.update(e, ev), lambda _: self.changed("Saved."), "Saving…")
        elif self.cal:  # a Calendar.md line: it moves to the real calendar, with its place and notes
            def move():
                self.cal.create(ev)
                return core.delete_local_event(e)
            self.bg(move, lambda ok: self.changed("Saved." if ok else "Saved; the old Calendar.md line had changed, "
                                                  "so it's still there."), "Saving…")
        else:
            ok = core.edit_local_event(e, ev["date"].isoformat(), ev["time"], ev["title"])
            self.changed("Saved." if ok else "That line changed in Calendar.md meanwhile; nothing was overwritten.")

    def delete_event(self):
        e = self.current()
        if not e:
            return
        if e.get("repeats"):
            q = QMessageBox(QMessageBox.Question, "Delete", f"“{e['title']}” repeats.", parent=self)
            one = q.addButton("Only this date", QMessageBox.AcceptRole)
            q.addButton("Every date", QMessageBox.DestructiveRole)
            cancel = q.addButton(QMessageBox.Cancel)
            q.exec()
            if q.clickedButton() is cancel:
                return
            if q.clickedButton() is one:
                return self.skip_date()
        elif QMessageBox.question(self, "Delete", f"Delete “{e['title']}” on {core.show_date(e['date'])}?") \
                != QMessageBox.Yes:
            return
        if e.get("source") == "caldav":
            self.bg(lambda: self.cal.delete(e), lambda _: self.changed("Deleted."), "Deleting…")
        else:
            ok = core.delete_local_event(e)
            self.changed("Deleted." if ok else "That line changed in Calendar.md meanwhile; nothing was deleted.")

    def skip_date(self):
        e = self.current()
        if e and e.get("repeats"):
            self.bg(lambda: self.cal.skip(e), lambda _: self.changed(f"Skipped {core.show_date(e['date'])}."), "Saving…")
