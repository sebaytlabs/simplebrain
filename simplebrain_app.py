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
from datetime import date

from PySide6.QtCore import QObject, QPointF, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QColor, QCursor, QDesktopServices, QIcon, QKeySequence, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QGridLayout,
    QHBoxLayout,
    QHeaderView, QInputDialog, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMenu, QMessageBox, QPlainTextEdit, QPushButton,
    QScrollArea, QSizePolicy, QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

import simplebrain_core as core

APP_NAME = "SimpleBrain"


def resource_path(name):
    """Bundled file path, both from source and inside a PyInstaller build."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)


class Bridge(QObject):
    """Background threads hand results to the UI thread through these signals
    (Qt queues cross-thread signal delivery onto the receiver's thread)."""
    ics_fetched = Signal(object, bool)


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
    """Force-directed note graph. Scroll to zoom (toward the cursor), drag
    empty space to pan, click a dot to open its note."""
    def __init__(self, on_open):
        super().__init__()
        self.on_open = on_open
        self.pos, self.edges, self.missing = {}, [], set()
        self.highlight = None  # notes the Dataview filter matches (None: no filter on)
        self.zoom, self.offset = 1.0, QPointF(0, 0)
        self._press = None  # (screen point, offset at press) while the mouse is down
        self._dragged = False
        self.setMinimumSize(200, 200)
        self.setCursor(Qt.OpenHandCursor)

    def recompute(self):
        notes, edges, self.missing = core.build_graph()
        self.pos = core.force_layout(notes, edges, max(self.width(), 200), max(self.height(), 200),
                                     pinned="Home.md")
        self.edges = edges
        self.fit()

    def fit(self):
        """Zoom out (never in past 1x) and center so every dot is visible."""
        if not self.pos:
            self.zoom, self.offset = 1.0, QPointF(0, 0)
            return self.update()
        xs, ys = [x for x, _ in self.pos.values()], [y for _, y in self.pos.values()]
        margin = 30
        bw, bh = max(xs) - min(xs) + 2 * margin, max(ys) - min(ys) + 2 * margin
        self.zoom = min(1.0, self.width() / bw, self.height() / bh)
        self.offset = QPointF(self.width() / 2 - (min(xs) + max(xs)) / 2 * self.zoom,
                              self.height() / 2 - (min(ys) + max(ys)) / 2 * self.zoom)
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
            if (point.x() - s.x()) ** 2 + (point.y() - s.y()) ** 2 <= 15 ** 2:
                return n
        return None

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), self.palette().base())
        p.translate(self.offset)
        p.scale(self.zoom, self.zoom)
        pen = QPen(QColor(170, 170, 170), 1)
        pen.setCosmetic(True)  # edges stay 1px at any zoom
        p.setPen(pen)
        for a, b in self.edges:
            if a in self.pos and b in self.pos:
                p.drawLine(QPointF(*self.pos[a]), QPointF(*self.pos[b]))
        faded = QColor(150, 150, 150)
        for n, (x, y) in self.pos.items():
            lit = self.highlight is not None and n in self.highlight
            dim = self.highlight is not None and not lit  # a filter is on and this note isn't in it
            if n in self.missing:  # linked but not written yet: hollow grey dot
                ring = QPen(faded, 1.5)
                ring.setCosmetic(True)
                p.setPen(ring)
                p.setBrush(self.palette().base())  # hides the edge behind the ring
            else:
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(235, 120, 20) if lit else faded if dim else QColor(51, 102, 230))
            r = 9 if lit else 6
            p.drawEllipse(QPointF(x, y), r, r)
            font = p.font()
            font.setBold(lit)
            p.setFont(font)
            p.setPen(faded if n in self.missing or dim else self.palette().text().color())
            p.drawText(QPointF(x + r + 3, y + 4), core.note_title(n))

    def wheelEvent(self, e):
        self.zoom_at(e.position(), 1.15 ** (e.angleDelta().y() / 120))

    def mousePressEvent(self, e):
        self._press, self._dragged = (e.position(), QPointF(self.offset)), False

    def mouseMoveEvent(self, e):
        if self._press is None:
            return
        start, offset = self._press
        delta = e.position() - start
        if abs(delta.x()) + abs(delta.y()) > 3:  # a small wobble is still a click
            self._dragged = True
            self.setCursor(Qt.ClosedHandCursor)
        if self._dragged:
            self.offset = offset + delta
            self.update()

    def mouseReleaseEvent(self, e):
        if self._press is not None and not self._dragged:
            n = self.node_at(e.position())
            if n:
                self.on_open(n)
        self._press = None
        self.setCursor(Qt.OpenHandCursor)


class SimpleBrain(QMainWindow):
    def __init__(self):
        super().__init__()
        core.ensure_vault()
        core.expand_shorthand_in_vault()  # t/i/c lines typed outside the app
        core.sync_answer_notes()  # catches notes edited outside the app
        self.setWindowTitle(APP_NAME)
        self.resize(1500, 950)
        self.current_note = None
        self.bridge = Bridge()
        self.bridge.ics_fetched.connect(self.on_ics_fetched)
        self._ics_text, self._ics_fetch_attempted, self._syncing = None, False, False

        self.build_menu()
        root = QWidget()
        lay = QVBoxLayout(root)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.addLayout(self.build_capture_bar())

        top = QSplitter(Qt.Horizontal)
        top.addWidget(self.build_notes_sidebar())
        top.addWidget(self.build_editor())
        self.graph = GraphView(self.open_link)
        graph_box, graph_lay = section("Graph", self._button("Recompute layout", self.graph.recompute),
                                       hint="Scroll to zoom, drag to move around, click a dot to open it. Hollow dots are links to notes "
                                            "you haven't written yet; click one to create it.")
        graph_lay.addWidget(self.graph, 1)
        top.addWidget(graph_box)
        top.setSizes([220, 650, 600])
        lay.addWidget(top, 1)

        # One grid for the four bottom panels: title / hint / controls / list rows
        # are shared, so the lists line up at the same top, height and width.
        bottom = QGridLayout()
        bottom.setHorizontalSpacing(12)
        for col, parts in enumerate((self.build_inbox(), self.build_tasks(), self.build_calendar(),
                                     self.build_dataview())):
            for row, w in enumerate(parts):
                if w is not None:
                    w.setSizePolicy(QSizePolicy.Ignored, w.sizePolicy().verticalPolicy())
                    bottom.addWidget(w, row, col)
            bottom.setColumnStretch(col, 1)
            parts[-1].setMinimumHeight(220)
        bottom.setRowStretch(3, 1)
        lay.addLayout(bottom)
        self.setCentralWidget(root)

        self.refresh_notes_list()
        self.refresh_inbox()
        self.refresh_tasks()
        self.refresh_calendar()
        self.refresh_dataview()
        self.open_note("Home.md")

    # -- helpers --
    def _button(self, label, slot):
        b = QPushButton(label)
        b.clicked.connect(lambda *_: slot())
        if label == "×":
            b.setFixedWidth(28)
            b.setToolTip("Delete")
        return b

    def _small_button(self, label, slot):
        """Compact button for list rows, so a row fits a narrow panel."""
        b = self._button(label, slot)
        b.setStyleSheet("padding: 1px 6px")
        return b

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
            self.editor.setPlainText(core.read_note(filename))
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
            self.show_error(f"'{s}' isn't a time (e.g. 14:30 or 2:30pm) — {consequence}")
        return t

    def read_date(self, s, consequence):
        """The typed date (MM-DD-YYYY), or None after telling the user why."""
        d = core.parse_date(s)
        if d is None:
            self.show_error(f"'{s}' isn't a valid date (need MM-DD-YYYY) — {consequence}")
        return d

    STALE_MSG = "That item changed on disk since the list was shown. The list is refreshed; nothing was overwritten."

    def show_error(self, message):
        QMessageBox.critical(self, APP_NAME, message)

    # -- menu --
    def build_menu(self):
        m = self.menuBar()
        file_menu = m.addMenu("&File")
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
        help_menu = m.addMenu("&Help")
        help_menu.addAction("&About SimpleBrain").triggered.connect(lambda *_: self.show_about())

    def open_vault_folder(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(core.VAULT))

    def show_about(self):
        QMessageBox.about(self, f"About {APP_NAME}",
                          f"<b>{APP_NAME} {core.VERSION}</b><br>Notes, tasks, calendar and graph.<br><br>"
                          f"Your notes: {core.VAULT}")

    # -- capture bar --
    def build_capture_bar(self):
        row = QHBoxLayout()
        row.addWidget(QLabel("Capture:"))
        self.capture = QLineEdit()
        self.capture.setPlaceholderText("Type anything, hit Enter — sort it into Task/Event/Note below")
        self.capture.returnPressed.connect(self.on_capture)
        row.addWidget(self.capture, 1)
        return row

    def on_capture(self):
        text = self.capture.text().strip()
        if text:
            core.add_inbox_item(text)
            self.capture.clear()
            self.refresh_inbox()

    # -- notes sidebar --
    def build_notes_sidebar(self):
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self._button("+ New Learning Note", self.on_new_learning_note))
        lay.addWidget(self._button("+ New Blank Note", self.on_new_blank_note))
        self.notes_list = QListWidget()
        self.notes_list.itemClicked.connect(lambda it: self.open_note(it.data(Qt.UserRole)))
        lay.addWidget(self.notes_list, 1)
        return box

    def refresh_notes_list(self):
        self.notes_list.clear()
        for n in core.list_user_notes():
            item = QListWidgetItem()
            item.setData(Qt.UserRole, n)
            w = QWidget()
            row = QHBoxLayout(w)
            row.setContentsMargins(4, 0, 4, 0)
            row.addWidget(QLabel(core.note_title(n)), 1)
            row.addWidget(self._button("×", lambda n=n: self.on_delete_note(n)))
            item.setSizeHint(w.sizeHint())
            self.notes_list.addItem(item)
            self.notes_list.setItemWidget(item, w)
            if n == self.current_note:
                self.notes_list.setCurrentItem(item)

    def on_delete_note(self, filename):
        if QMessageBox.question(self, APP_NAME, f"Move '{core.note_title(filename)}' to the vault's .trash?") \
                != QMessageBox.Yes:
            return
        if self.current_note == filename:
            self.current_note = None  # don't re-save it after it's moved
        core.delete_note(filename)
        self.sync_answers()
        self.refresh_notes_list()
        self.graph.recompute()
        self.refresh_dataview()
        if self.current_note is None:
            self.open_note("Home.md")

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
                            "(it can't contain / \\ : * ? \" < > | or end with a dot or space).")
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
        self.editor = QPlainTextEdit()
        lay.addWidget(self.editor, 1)
        # Links follow typing (debounced), so a new [[link]] shows without reopening.
        self._links_timer = QTimer(self, singleShot=True, interval=300)
        self._links_timer.timeout.connect(self.render_links)
        self.editor.textChanged.connect(self._links_timer.start)
        links_holder = QWidget()
        rows = QVBoxLayout(links_holder)
        rows.setContentsMargins(4, 2, 4, 2)
        self.links_row, self.backlinks_row = QHBoxLayout(), QHBoxLayout()
        rows.addLayout(self.links_row)
        rows.addLayout(self.backlinks_row)
        scroll = QScrollArea()
        scroll.setWidget(links_holder)
        scroll.setWidgetResizable(True)
        scroll.setFixedHeight(84)
        lay.addWidget(scroll)
        save_row = QHBoxLayout()
        save_row.addWidget(self._button("Save (Ctrl+S)", self.save_current))
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
        text = core.read_note(filename)
        self._saved_links, self._saved_tasks = set(core.parse_links(text)), task_lines(text)
        self._saved_answers = core.parse_answers(text)
        self.editor.setPlainText(text)
        self._links_timer.stop()
        self.render_links()
        for i in range(self.notes_list.count()):
            if self.notes_list.item(i).data(Qt.UserRole) == filename:
                self.notes_list.setCurrentRow(i)

    def render_links(self):
        """Links row from the editor's current text; Linked-from row from the
        saved notes on disk (only other notes' saves can change it)."""
        for row in (self.links_row, self.backlinks_row):
            while row.count():
                w = row.takeAt(0).widget()
                if w:
                    w.deleteLater()
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
            self.backlinks_row.addWidget(self._button(core.note_title(n), lambda n=n: self.open_note(n)))
        self.backlinks_row.addStretch(1)

    def save_current(self):
        if self.current_note is None:
            return
        typed = self.editor.toPlainText()
        try:
            text, problems = core.write_note_with_shorthand(self.current_note, typed)
            self.save_status.setText("<span style='color:red'>Not added to Calendar: "
                                     f"{html.escape('; '.join(problems))}</span>" if problems else "")
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

    def sync_answers(self):
        """Rebuild the "<Keyword> - Answers" notes; True if any changed. The
        open note is reloaded if it was one of them (or Home opened if it went)."""
        changed = core.sync_answer_notes()
        if self.current_note in changed:
            if os.path.exists(os.path.join(core.VAULT, self.current_note)):
                self.editor.setPlainText(core.read_note(self.current_note))
            else:
                self.current_note = None
                self.open_note("Home.md")
        if changed:
            self.refresh_notes_list()
        return bool(changed)

    def closeEvent(self, e):
        self.save_current()
        e.accept()

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
        due = self.ask_text("Due date (optional)", "MM-DD-YYYY, blank for none")
        if due is None:
            return
        due = due.strip()
        if due and not (due := self.read_date(due, "item stays in Inbox, nothing was lost.")):
            return
        core.classify_as_task(item, due.isoformat() if due else None)
        self.refresh_inbox()
        self.refresh_tasks()

    def on_classify_event(self, item):
        d = self.ask_text("Event date", "MM-DD-YYYY")
        if not d or not d.strip():
            return
        d = self.read_date(d.strip(), "item stays in Inbox, nothing was lost.")
        if not d or not self.confirm_past_date(d):
            return
        t = (self.ask_text("Event time (optional)", "e.g. 14:30 or 2:30pm, blank for all-day") or "").strip()
        if t and not (t := self.read_time(t, "item stays in Inbox, nothing was lost.")):
            return
        core.classify_as_event(item, d.isoformat(), t or None)
        self.refresh_inbox()
        self.refresh_calendar()

    def on_classify_note(self, item):
        core.classify_as_note(item)
        self.refresh_inbox()

    # -- tasks --
    def build_tasks(self):
        self.tasks_list = QListWidget()
        return (*panel_head("Tasks", self._button("Refresh", self.refresh_tasks),
                            hint="Every line starting 't ' in your notes. "
                                 "Add due:MM-DD-YYYY to give it a date. 'i …' sends a line to the Inbox, "
                                 "'c MM-DD-YYYY [time] title' to the Calendar."),
                None, self.tasks_list)

    def refresh_tasks(self):
        self.tasks_list.clear()
        buckets = core.bucket_tasks(core.parse_tasks())
        if not any(buckets.values()):
            self.tasks_list.addItem("No open tasks — you're clear.")
        for bucket in ("Overdue", "Today", "Upcoming", "No date"):
            if not buckets[bucket]:
                continue
            head = QListWidgetItem(bucket)
            f = head.font()
            f.setBold(True)
            head.setFont(f)
            head.setFlags(Qt.ItemIsEnabled)  # not selectable, but not greyed out
            self.tasks_list.addItem(head)
            for t in buckets[bucket]:
                w = QWidget()
                row = QHBoxLayout(w)
                row.setContentsMargins(0, 0, 4, 0)
                cb = QCheckBox()  # text in a separate label so long tasks wrap
                cb.toggled.connect(lambda _c, t=t: self.on_task_toggle(t))
                row.addWidget(cb)
                lbl = QLabel(f"{html.escape(core.due_for_display(t['text']))}  "
                             f"<span style='color:gray'>({html.escape(core.note_title(t['file']))})</span>")
                lbl.setTextFormat(Qt.RichText)
                lbl.setWordWrap(True)
                row.addWidget(lbl, 1)
                row.addWidget(self._small_button("Edit", lambda t=t: self.on_edit_task(t)))
                row.addWidget(self._small_button("Delete", lambda t=t: self.on_delete_task(t)))
                li = QListWidgetItem()
                li.setSizeHint(w.sizeHint())
                self.tasks_list.addItem(li)
                self.tasks_list.setItemWidget(li, w)

    def on_task_toggle(self, task):
        self.edit_in_file(task["file"], lambda: core.toggle_task(task))
        QTimer.singleShot(0, self.refresh_tasks)

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
        self.event_date.setPlaceholderText("MM-DD-YYYY")
        self.event_date.setMaximumWidth(110)
        self.event_title = QLineEdit()
        self.event_title.setPlaceholderText("Event title")
        add.addWidget(self.event_date)
        add.addWidget(self.event_title, 1)
        add.addWidget(self._button("+ Add", self.on_add_event))
        lay.addLayout(add)
        self.calendar_list = QListWidget()
        return (*panel_head("Calendar", self.sync_button,
                            hint="Your events, plus the synced calendar for the next 14 days."),
                controls, self.calendar_list)

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
            if not self._syncing:
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
            self.calendar_status.setText("Synced.")
        self.render_calendar()

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
            row.addWidget(QLabel(f"[{tag}] {when} — {e['title']}"), 1)
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
        self.dv_tag.currentIndexChanged.connect(lambda *_: self.refresh_dataview())
        filters.addWidget(self.dv_tag)
        self.dv_search = QLineEdit()
        self.dv_search.setPlaceholderText("Search title...")
        self.dv_search.textChanged.connect(lambda *_: self.refresh_dataview())
        filters.addWidget(self.dv_search, 1)
        self.dv_table = QTableWidget(0, 4)
        self.dv_table.setHorizontalHeaderLabels(["Title", "Tags", "Links", "Linked from"])
        header = self.dv_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeToContents)  # counts/dates stay visible
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        self.dv_table.verticalHeader().hide()
        self.dv_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.dv_table.setSortingEnabled(True)
        self.dv_table.cellDoubleClicked.connect(
            lambda r, _c: self.open_note(self.dv_table.item(r, 0).data(Qt.UserRole)))
        self.dv_table.cellClicked.connect(self.on_dv_cell_clicked)
        return (*panel_head("Dataview", hint="Every note. Filter by #tag or title; matches light up orange in the "
                                             "graph. Double-click to open. Click a Links or Linked from "
                                             "number to see those notes."),
                controls, self.dv_table)

    def on_dv_cell_clicked(self, r, c):
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
        self.dv_table.setSortingEnabled(False)
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
        self.dv_table.setSortingEnabled(True)
        filtering = tag != "All tags" or self.dv_search.text().strip()
        self.graph.highlight = {r["file"] for r in shown} if filtering else None
        self.graph.update()


def main():
    if "--selftest" in sys.argv:
        core.selftest()
        return 0
    if "--version" in sys.argv:
        print(core.VERSION)
        return 0
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(core.VERSION)
    app.setDesktopFileName("simplebrain")
    icon = resource_path("icon.png")
    if os.path.exists(icon):
        app.setWindowIcon(QIcon(icon))
    win = SimpleBrain()
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
