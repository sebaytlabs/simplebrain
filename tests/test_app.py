"""Headless end-to-end check of the Qt app in a throwaway vault.
Run: QT_QPA_PLATFORM=offscreen python tests/test_app.py"""
import os
import sys
import tempfile

os.environ["SIMPLEBRAIN_VAULT"] = tempfile.mkdtemp()
HOME = tempfile.mkdtemp()  # PARA folders, Drop and Downloads are looked for under home: never the real one
os.environ["HOME"] = os.environ["USERPROFILE"] = HOME
os.environ["SIMPLEBRAIN_NO_UPDATE"] = "1"  # never pull new code into the checkout under test
os.environ["SIMPLEBRAIN_NO_WATCH"] = "1"
os.environ["SIMPLEBRAIN_NO_MENU"] = "1"  # web-app launchers are tested in simplebrain_desk with a temp home  # the watcher's minutes are driven by hand below, not by the clock
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import simplebrain_app as A  # noqa: E402
from datetime import timedelta as _td0  # noqa: E402
import simplebrain_core as core  # noqa: E402
import simplebrain_recommend as reco  # noqa: E402
from simplebrain_sync import h as devsync_hash  # noqa: E402
from PySide6.QtCore import QPoint, QRectF, Qt, QTimer  # noqa: E402
from PySide6.QtGui import QTextCursor  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QPushButton  # noqa: E402

SETTINGS_DIR = tempfile.mkdtemp()  # never touch the real per-user settings from a test
core.settings_path = lambda search=None: os.path.join(SETTINGS_DIR, "settings.json")
core.user_config_dir = lambda: SETTINGS_DIR  # sync's device key lives here: never the real one
app = QApplication([])
w = A.SimpleBrain()
w.show()


def rows_now():
    """Mentioned in / Related / backlink lines are worked out in the background: wait for them."""
    for _ in range(500):
        app.processEvents()
        if not getattr(w, "_mentions_busy", False):
            break
        QTest.qWait(10)
    app.processEvents()


def today_now():
    """Today is rebuilt in the background: start a rebuild now and wait until it has landed."""
    w._today_busy = False
    if hasattr(w, "_today_debounce"):
        w._today_debounce.stop()
    w.update_today()
    for _ in range(500):
        app.processEvents()
        if not w._today_busy:
            break
        QTest.qWait(10)
    app.processEvents()
app.processEvents()
w.resize(300, 300)
assert w.width() < 1200 and w.height() < 700  # snaps to a half screen; the content scrolls instead of being cut off
for width, cols in ((900, 2), (500, 1), (1500, 4)):  # the bottom panels reflow instead of being cut off
    w.resize(width, 950)
    app.processEvents()
    assert w.bottom_cols == cols and len({w.bottom.getItemPosition(w.bottom.indexOf(p[-1]))[:2] for p in w.panels}) == 4
w.resize(1500, 950)
app.processEvents()
assert w.graph.zoom > 1.0  # a big window scales the graph up to fill it
assert os.path.exists(os.path.join(core.VAULT, "Home.md")) and w.current_note == "Home.md"
w.capture.setText("buy milk")
w.on_capture()
assert core.parse_inbox()[0]["text"] == "buy milk"
w.create_note("Project X")
w.editor.setPlainText("# Project X\n\nsee [[Home]] #work\n- [ ] ship it due:2020-01-01\n")
w.editor.moveCursor(QTextCursor.End)
w.on_cite_found(["Clear, J. (2018). *Atomic Habits*. Avery."], "")  # one match goes straight in at the cursor
assert w.editor.toPlainText().endswith("*Atomic Habits*. Avery.")
w.open_note("Home.md")  # switching notes saves the previous one
assert "\nt ship it due:2020-01-01" in core.read_note("Project X.md")  # old format converted on save
app.processEvents()  # the save refreshes Tasks on its own, no Refresh click
assert w.tasks_list.count() >= 2
# ticking a task: light rows, so a big vault never freezes the window (it took seconds per click before)
import time as _time  # noqa: E402
core.write_note("Many.md", "# Many\n" + "".join(f"t chore {i} due:11-0{1 + i % 5}-2026\n" for i in range(600)))
_t = _time.time()
w.refresh_tasks()
assert _time.time() - _t < 1.5, "Tasks panel rebuild is too slow"
row = next(w.tasks_list.item(i) for i in range(w.tasks_list.count())
           if isinstance(w.tasks_list.item(i).data(Qt.UserRole), dict) and "chore" in w.tasks_list.item(i).text())
assert any("more (the top bar finds any of them)" in w.tasks_list.item(i).text() for i in range(w.tasks_list.count()))
w.tasks_list.setCurrentItem(row)  # the selected task has its Edit/Delete buttons
assert [b.text() for b in w.task_buttons.buttons()] == ["Edit", "Delete"] and w.task_buttons.isVisible()
which = row.data(Qt.UserRole)["text"]
row.setCheckState(Qt.Checked)
app.processEvents()
assert "- [x] " + which in core.read_note("Many.md")
os.remove(os.path.join(core.VAULT, "Many.md"))
w.refresh_tasks()
w.refresh_dataview()
assert w.dv_table.rowCount() == len(core.list_user_notes()) == 2  # Inbox/Calendar hidden
assert w.notes_list.count() == 2
w.dv_tag.setCurrentText("work")
assert w.dv_table.rowCount() == 1
assert w.graph.highlight == {"Project X.md"}  # tag filter lights its notes up in the graph
w.graph.repaint()  # paints the lit/dimmed dots without error
w.graph.recompute()
assert len(w.graph.edges) == 1
# graph zoom keeps the point under the cursor fixed; pan moves; hit-test follows both
g = w.graph
node, (nx, ny) = next(iter(g.pos.items()))
under, z0 = g.to_screen(nx, ny), g.zoom
g.zoom_at(under, 2.0)
assert g.zoom == z0 * 2.0 and abs(g.to_screen(nx, ny).x() - under.x()) < 1e-6
g.offset += A.QPointF(40, -25)
assert g.node_at(g.to_screen(nx, ny)) == node
g.zoom_at(under, 1000)
assert g.zoom == 5.0  # clamped
g.recompute()
assert 1.0 < g.zoom <= 1.5  # a small graph in a big box is scaled up, but not past 1.5x
# a resize re-fits the view but keeps the layout (re-running it per resize event froze the window),
# and a big graph is zoomed out until every dot is on screen
g.pos = {f"n{i}.md": [i * 50.0, (i % 7) * 40.0] for i in range(60)}
layout = g.pos
g.resize(g.width() + 40, g.height())
app.processEvents()
assert g.pos is layout and g.zoom < 1.0
for x, y in g.pos.values():
    s = g.to_screen(x, y)
    assert 0 <= s.x() <= g.width() and 0 <= s.y() <= g.height()
g.recompute()
# Home's "Linked from" shows Project X; a link typed into Home shows live,
# and saving it updates the graph without creating a note first
row_text = lambda row: [row.itemAt(i).widget().text() for i in range(row.count()) if row.itemAt(i).widget()]
assert "Project X" in row_text(w.backlinks_row)
w.editor.setPlainText(w.editor.toPlainText() + "\nsee [[Project X]] and [[Later]]\n")
w.render_links()  # what the typing timer calls
assert {"[[Project X]]", "[[Later]]  + new"} <= set(row_text(w.links_row))
w.editor.setPlainText(w.editor.toPlainText() + "\nfile:: /nonexistent/Guitar.pdf\n")
w.render_links()
assert any("Guitar.pdf" in t and "not found" in t for t in row_text(w.files_row))
w.save_current()
assert len(w.graph.edges) == 2 and w.graph.missing == {"Later.md"}  # [[Later]] is a faded node
w.open_note("Project X.md")
assert "Home" in row_text(w.backlinks_row)
w.open_note("Home.md")
w.show_error = lambda m: setattr(w, "_err", m)
w.create_note("a:b")
assert "valid" in w._err
for bad in ("Inbox", "calendar", "Recommendations", "habits - Answers", ".hidden"):
    w._err = None
    w.create_note(bad)
    assert w._err, bad  # refused with a message
assert not os.path.exists(os.path.join(core.VAULT, ".hidden.md")) and not os.path.exists(os.path.join(core.VAULT, "habits - Answers.md"))
w._err = None
w.open_note("Project X.md")
t = [t for t in core.parse_tasks() if not t["done"]][0]
w.on_task_toggle(t)
assert "[x]" in w.editor.toPlainText()  # editor reloads, won't overwrite the toggle
# edit buttons: inbox item, then a task in the open note (editor must reload)
w.ask_text = lambda *_a: "buy oat milk"
w.on_edit_inbox(core.parse_inbox()[0])
assert core.parse_inbox()[0]["text"] == "buy oat milk"
w.ask_text = lambda *_a: "ship it v2 due:02-03-2020"  # typed US order, stored YYYY-MM-DD
w.on_edit_task(t)
assert "- [x] ship it v2 due:2020-02-03" in w.editor.toPlainText()
w.ask_text = lambda *_a: "bad date due:13-01-2020"
w.on_edit_task([t for t in core.parse_tasks() if t["file"] == "Project X.md"][0])
assert "isn't a date" in w._err and "bad date" not in core.read_note("Project X.md")
# the graph is centered on the open note, and re-centers when another note opens
w.open_note("Home.md")
assert w.graph._to is not None  # the picture glides to the new center...
w.graph.settle()  # ...and the checks below look at where it ends up
assert w.graph.pos["Home.md"] == [w.graph.width() / 2, w.graph.height() / 2]
other = next(n for n in w.graph.pos if n != "Home.md" and n not in w.graph.missing)
w.open_note(other)
w.graph.settle()
assert w.graph.center == other and w.graph.pos[other] == [w.graph.width() / 2, w.graph.height() / 2]
# dragging a dot moves it and its branch, nothing else (real mouse events: Home <- Twig <- Leaf)
core.write_note("Twig.md", "[[Home]]\n")
core.write_note("Leaf.md", "[[Twig]]\n")
# local view: Home is a hub, so it shows its direct notes; Leaf (via Twig) is hidden until "Show all"
w.open_note("Home.md")
w.graph.recompute()
w.graph.settle()
assert "Twig.md" in w.graph.pos and "Leaf.md" not in w.graph.pos
w.open_note("Twig.md")  # a non-hub center walks one step further: its own neighbours and theirs
w.graph.settle()
assert {"Twig.md", "Leaf.md", "Home.md"} <= set(w.graph.pos) and w.graph.center == "Twig.md"
assert w.graph.pos["Twig.md"] == [w.graph.width() / 2, w.graph.height() / 2]  # the open note is the center
w.show_all_box.setChecked(True)  # the full map: what the drag checks below need
w.open_note("Home.md")
w.graph.recompute()
w.graph.settle()
assert w.graph.parent["Twig.md"] == "Home.md" and w.graph.parent["Leaf.md"] == "Twig.md"
before = {n: list(p) for n, p in w.graph.pos.items()}
start = w.graph.to_screen(*before["Twig.md"]).toPoint()
QTest.mousePress(w.graph, Qt.LeftButton, Qt.NoModifier, start)
QTest.mouseMove(w.graph, start + QPoint(40, 25))
QTest.mouseRelease(w.graph, Qt.LeftButton, Qt.NoModifier, start + QPoint(40, 25))
moved = {n for n, p in w.graph.pos.items() if p != before[n]}
assert moved == {"Twig.md", "Leaf.md"}, moved
assert w.current_note == "Home.md"  # a drag is not a click
for f in ("Twig.md", "Leaf.md"):
    os.remove(os.path.join(core.VAULT, f))
w.show_all_box.setChecked(False)
assert not w.graph.show_all
w.graph.recompute()
w.open_note("Home.md")
# selecting a Dataview row lights that note in the graph; clearing it falls back to the filter's matches
w.refresh_dataview()
w.dv_table.selectRow(0)
assert w.graph.highlight == {w.dv_table.item(0, 0).data(Qt.UserRole)}
w.dv_table.clearSelection()
assert w.graph.highlight == w._dv_shown
# unwritten links ask before creating; No leaves nothing behind
w.confirm_create = lambda _f: False
w.open_link("Nope.md")
assert not os.path.exists(os.path.join(core.VAULT, "Nope.md"))
w.confirm_create = lambda _f: True
# Dataview: Linked from column + a menu of connected notes that opens them
w.dv_tag.setCurrentText("All tags")
w.refresh_dataview()
assert w.graph.highlight is None  # no filter, no highlight
home_row = next(i for i in range(w.dv_table.rowCount()) if w.dv_table.item(i, 0).text() == "Home")
assert w.dv_table.item(home_row, 3).data(A.Qt.DisplayRole) == 1  # Project X links Home
menu = w.connections_menu("Home.md")
labels = [a.text() for a in menu.actions()]
assert "Project X" in labels and "Later  (not written yet)" in labels, labels
next(a for a in menu.actions() if a.text() == "Project X").trigger()
assert w.current_note == "Project X.md"
# answer:: lines: saving builds "<Keyword> - Answers"; deleting the last source trashes it
w.create_note("Book")
w.editor.setPlainText("# Book\n[[Focus]]\n1. How?\nanswer:: Block mornings\n")
w.save_current()
assert "Block mornings" in core.read_note("Focus - Answers.md")
assert "Focus - Answers.md" in [w.notes_list.item(i).data(A.Qt.UserRole) for i in range(w.notes_list.count())]
assert "Focus - Answers.md" in w.graph.pos
w.open_note("Focus - Answers.md")
A.QMessageBox.question = staticmethod(lambda *_a: A.QMessageBox.Yes)
w.on_delete_note("Book.md")  # last answer gone: generated note trashed, Home opens
assert not os.path.exists(os.path.join(core.VAULT, "Focus - Answers.md")) and w.current_note == "Home.md"
w.open_note("Project X.md")  # the steps below work on it
# events: far-future one is visible; past one asks first
w.event_date.setText("01-02-2099"); w.event_title.setText("far off")
w.on_add_event()
assert any("far off" in w.calendar_list.itemWidget(w.calendar_list.item(i)).findChild(A.QLabel).text()
           for i in range(w.calendar_list.count()))
assert "- 2099-01-02 far off" in core.read_note(core.CALENDAR_FILE)
assert any("01-02-2099" in w.calendar_list.itemWidget(w.calendar_list.item(i)).findChild(A.QLabel).text()
           for i in range(w.calendar_list.count()))
far = [e for e in core.read_local_events() if e["title"] == "far off"][0]
w.ask_event = lambda _e: ("03-04-2099", "2:30pm", "far off, moved")
w.on_edit_event(far)
assert "- 2099-03-04 14:30 far off, moved" in core.read_note(core.CALENDAR_FILE)
w.ask_event = lambda _e: ("03-04-2099", "noonish", "x")
w.on_edit_event(core.read_local_events()[-1])
assert "isn't a time" in w._err and "noonish" not in core.read_note(core.CALENDAR_FILE)
w.confirm_past_date = lambda _d: False
w.event_date.setText("01-01-2000"); w.event_title.setText("long ago")
w.on_add_event()
assert "long ago" not in core.read_note(core.CALENDAR_FILE)
# delete buttons: confirm, remove the line, keep the open editor in sync
w.confirm_delete = lambda _t: True
w.capture.setText("junk")
w.on_capture()
w.on_delete_inbox([i for i in core.parse_inbox() if i["text"] == "junk"][0])
assert "junk" not in [i["text"] for i in core.parse_inbox()]
w.on_delete_task([t for t in core.parse_tasks() if t["file"] == "Project X.md"][0])
assert "ship it" not in w.editor.toPlainText() and "ship it" not in core.read_note("Project X.md")
# shorthand: t/i/c lines expand on save; a bad c line stays and is reported
w.editor.setPlainText("t pay rent\ni someday idea\nc 01-02-2099 9am trip\nc nope x\n")
w.save_current()
assert w.editor.toPlainText() == "t pay rent\nc nope x\n" == core.read_note("Project X.md")
assert core.parse_inbox()[-1]["text"] == "someday idea"
assert "- 2099-01-02 09:00 trip" in core.read_note(core.CALENDAR_FILE)
assert "nope" in w.save_status.text()
# notes folder: an always-visible button; switching moves every panel and can copy the notes over
assert w.folder_label.isVisible() and w.folder_label.toolTip() == core.VAULT
btn = [b for b in w.findChildren(A.QPushButton) if b.text() == "Change notes folder…"]
assert len(btn) == 1 and btn[0].isVisible()
orig_vault = core.VAULT
new_vault = os.path.join(tempfile.mkdtemp(), "My Notes")
asked = []
A.QMessageBox.question = staticmethod(lambda *a: asked.append(a[2]) or A.QMessageBox.Yes)
w.open_note("Project X.md")
w.editor.setPlainText(w.editor.toPlainText() + "\nunsaved thought\n")
w.switch_vault(new_vault)  # also saves the open note first
assert core.VAULT == os.path.abspath(new_vault) and "copy" in asked[-1].lower()
assert "unsaved thought" in core.read_note("Project X.md")  # copied with its last edit
assert "unsaved thought" in core.read_note("Project X.md", orig_vault)  # and the original is untouched
assert core.resolve_vault({}, core.settings_path()) == os.path.abspath(new_vault)  # remembered for next start
assert w.current_note == "Home.md" and w.folder_label.toolTip() == core.VAULT
assert w.notes_list.count() == len(core.list_user_notes()) and "Project X.md" in core.list_user_notes()
assert os.path.exists(os.path.join(new_vault, ".config"))
core.add_inbox_item("only in the new folder")
assert "only in the new folder" not in core.read_note(core.INBOX_FILE, orig_vault)
w.capture.setText("typed after switching")
w.on_capture()
assert "typed after switching" in core.read_note(core.INBOX_FILE)  # the new folder, not the old one
# a switch to a folder that already has notes asks nothing and copies nothing
asked.clear()
w.switch_vault(orig_vault)
assert core.VAULT == orig_vault and asked == [] and "typed after switching" not in core.read_note(core.INBOX_FILE)
w.switch_vault(orig_vault)  # same folder: nothing happens
assert w.current_note == "Home.md"

# calendar: pick a .csv through the file dialog; it shows read-only next to local events
csv_file = os.path.join(tempfile.mkdtemp(), "work.csv")
soon = (A.date.today() + __import__("datetime").timedelta(days=3)).strftime("%m-%d-%Y")  # feed events show for 14 days
open(csv_file, "w", encoding="utf-8").write(f"Date,Time,Title\n{soon},9am,Quarterly review\n")
A.QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (csv_file, ""))
w.show_error = lambda m: setattr(w, "_err", m)
w.on_choose_calendar_file()
for _ in range(100):  # the fetch runs on a thread
    app.processEvents()
    if "Quarterly review" in "".join(w.calendar_list.itemWidget(w.calendar_list.item(i)).findChild(A.QLabel).text()
                                     for i in range(w.calendar_list.count()) if w.calendar_list.itemWidget(w.calendar_list.item(i))):
        break
    QTest.qWait(20)
else:
    raise AssertionError("calendar file events never appeared")
assert "work.csv" in w.calendar_status.text() and core.get_calendar_file() is not None
A.QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (os.path.join(core.VAULT, "Home.md"), ""))
w.on_choose_calendar_file()  # a note is not a calendar: refused, nothing changed
assert ".ics" in w._err and core.get_calendar_file() is not None
core.set_calendar_file("")
w.refresh_calendar(sync=True)

# recommendations: silent until there is a book note and a yes; then built off the UI thread
reco.open_library_search = lambda kw: [
    {"key": "/works/OL1W", "title": "Tiny Habits", "subject": ["Habit", "Psychology"],
     "want_to_read_count": 50, "author_name": ["B. J. Fogg"]}]
reco.time.sleep = lambda s: None
w.start_recommendations()
assert core.load_settings().get("recommendations") is None  # no book note: no prompt, nothing sent
asked.clear()
w.on_new_learning_note = None
w.ask_text = lambda *_a: "Atomic Habits"
A.SimpleBrain.on_new_learning_note(w)
core.write_note("Atomic Habits.md", core.read_note("Atomic Habits.md").replace(
    "(put each one in double square brackets to link it)\n", "(put each one in double square brackets to link it)\n[[habit]] [[psychology]]\n"))
w.start_recommendations()
assert "recommendations" in asked[-1].lower() or "book" in asked[-1].lower()
assert core.load_settings()["recommendations"] == "on" and w.recommendations_action.isChecked()
def reco_listed():
    return "Recommendations.md" in [w.notes_list.item(i).data(A.Qt.UserRole) for i in range(w.notes_list.count())]
for _ in range(500):  # the note is written, then the list refreshes: wait for both (slow CI runners)
    app.processEvents()
    if os.path.exists(os.path.join(core.VAULT, "Recommendations.md")) and reco_listed():
        break
    QTest.qWait(20)
app.processEvents()
assert "Tiny Habits, B. J. Fogg: matches [[habit]] [[psychology]]" in core.read_note("Recommendations.md")
assert "Recommendations.md" in [w.notes_list.item(i).data(A.Qt.UserRole) for i in range(w.notes_list.count())]
w.open_note("Project X.md")
w.recommendations_action.setChecked(False)  # menu switch turns it off and remembers
assert core.load_settings()["recommendations"] == "off"
os.remove(os.path.join(core.VAULT, "Recommendations.md"))
w.start_recommendations()
QTest.qWait(100)
assert not os.path.exists(os.path.join(core.VAULT, "Recommendations.md"))  # off: nothing built, nothing sent
os.remove(os.path.join(core.VAULT, "Atomic Habits.md"))
w.reload_everything()
w.open_note("Project X.md")  # the steps below work on it

# autosave + device sync (file side; the network is covered by `python simplebrain_sync.py`)
assert w.sync is None and not os.path.exists(os.path.join(SETTINGS_DIR, "simplebrain-sync.json"))  # unused: nothing started, no key made
w.open_note("Project X.md")
w.editor.setPlainText("# Project X\n\ntyped but never saved\n")
w.autosave()  # what was typed reaches disk without Save
assert "typed but never saved" in core.read_note("Project X.md")
w.editor.setPlainText("# Project X\n\ni an idea typed mid-thought\n")
w.autosave()  # a shorthand line would be rewritten by a save, so autosave leaves it for a deliberate save
assert "an idea typed mid-thought" not in core.read_note("Project X.md") and core.parse_inbox()[-1]["text"] != "an idea typed mid-thought"
w.editor.setPlainText("# Project X\n\nback to plain\n")
w.autosave()
# another program edits the open note: shown when nothing is typed ...
core.write_note("Project X.md", "# Project X\n\nedited elsewhere\n")
w.reconcile_outside()
assert w.editor.toPlainText() == "# Project X\n\nedited elsewhere\n"
# ... and with typing in the editor, the typing is kept as its own note and autosave can't overwrite the outside edit
w.editor.setPlainText("# Project X\n\ntyped meanwhile\n")
core.write_note("Project X.md", "# Project X\n\nedited elsewhere again\n")
w.autosave()
assert core.read_note("Project X.md") == "# Project X\n\nedited elsewhere again\n"
copies = [f for f in os.listdir(core.VAULT) if f.startswith("Project X (typed here")]
assert len(copies) == 1 and core.read_note(copies[0]) == "# Project X\n\ntyped meanwhile\n"
assert w.editor.toPlainText() == "# Project X\n\nedited elsewhere again\n" and "typed here" in w.save_status.text()
os.remove(os.path.join(core.VAULT, copies[0]))
w.refresh_notes_list()
av = A.AppVault(w)
assert "Project X.md" in av.snapshot() and "Recommendations.md" not in av.snapshot()
# an incoming change to the open note: applied and shown when the editor is clean ...
disk = core.read_note("Project X.md")
assert av.apply({"Project X.md": "# Project X\n\nfrom the phone\n"}, [], {"Project X.md": devsync_hash(disk)}) == []
assert w.editor.toPlainText() == "# Project X\n\nfrom the phone\n"
# ... but held back while it holds typing that isn't on disk (the next round picks it up)
w.editor.setPlainText("# Project X\n\nhalf-typed local edit")
assert av.apply({"Project X.md": "# Project X\n\nfrom the phone, again\n"}, [], {"Project X.md": devsync_hash(core.read_note("Project X.md"))}) == ["Project X.md"]
assert w.editor.toPlainText().endswith("half-typed local edit") and "again" not in core.read_note("Project X.md")
w.autosave()
assert av.apply({"Phone note.md": "# Phone note\n"}, [], {"Phone note.md": None}) == []  # a new note appears in the sidebar
assert "Phone note.md" in [w.notes_list.item(i).data(A.Qt.UserRole) for i in range(w.notes_list.count())]
w.on_sync_status({"state": "ok", "message": "Up to date", "time": 1700000000})
assert w.sync_label.text().startswith("Sync: up to date")
w.on_sync_status({"state": "offline", "message": "x", "time": None})
assert w.sync_label.text() == "Sync: other device offline"
import simplebrain_sync
qr = A.qr_pixmap(simplebrain_sync.make_code("ab" * 32, "cd" * 16).replace("-", ""))
assert qr.width() == qr.height() and qr.width() > 100  # a pairing code fits one QR picture
w.open_note("Project X.md")

# one look: Glass, always, with nothing to switch it (no Theme box)
assert not hasattr(w, "theme_box") and "Theme:" not in [l.text() for l in w.findChildren(A.QLabel)]
assert w.graph.dot_color != w.graph.DOT and not w.palette().window().texture().isNull()  # Glass, drawn 1:1
assert os.path.exists(os.path.join(SETTINGS_DIR, "glass", "backdrop.png"))
w.apply_theme("holo")  # an old setting or call can't bring anything else back
assert w.graph.dot_color != w.graph.DOT and "#78c8eb" not in w.styleSheet()
w.graph.repaint()
from PySide6.QtGui import QWheelEvent  # noqa: E402
from PySide6.QtCore import QPointF as _QPF  # noqa: E402
combo = w.dv_tag  # the mouse wheel passing over a drop-down never changes it
before_i = combo.currentIndex()
for delta in (-120, 120, -120):
    QApplication.sendEvent(combo, QWheelEvent(_QPF(5, 5), _QPF(combo.mapToGlobal(QPoint(5, 5))), QPoint(0, 0),
                                              QPoint(0, delta), Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False))
assert combo.currentIndex() == before_i
app.processEvents()
# links in a note: underlined, and a plain click opens them in their own window (the opener is recorded here)
import simplebrain_glass as glass  # noqa: E402
assert glass.links_in("see https://edube.org/x. and [[Home]]") == [(4, 23, "url", "https://edube.org/x"),
                                                                   (29, 37, "note", "Home")]
assert glass.links_in("  file:: ~/Videos/a b.mp4 ") == [(9, 25, "file", "~/Videos/a b.mp4")]
opened = []
w.opener = opened.append
_can_embed = A.desk.can_embed  # this part is about opening a file in its own program: on a computer with mpv and X11
A.desk.can_embed = lambda *a, **k: False  # a video would open inside the window instead (tested with the viewer)
vid = os.path.join(tempfile.mkdtemp(), "session 01.mp4")
open(vid, "w").close()
w.on_note_link("file", vid)
w.on_note_link("url", "https://edube.org")
assert opened[0][-1] == vid and opened[1][-1] == "https://edube.org"
w.on_note_link("file", "/nowhere/gone.pdf")
assert len(opened) == 2 and "Not on this computer" in w.save_status.text()
w.on_note_link("note", "Project X")
assert w.current_note == "Project X.md"
w.editor.setPlainText(w.editor.toPlainText().rstrip() + f"\nfile:: {vid}\n")
w.editor.moveCursor(QTextCursor.End)
app.processEvents()
c = w.editor.textCursor()
c.movePosition(QTextCursor.Up)
c.movePosition(QTextCursor.StartOfBlock)
c.movePosition(QTextCursor.Right, n=12)
r = w.editor.cursorRect(c)
QTest.mouseClick(w.editor.viewport(), Qt.LeftButton, pos=r.center())  # a real click on the path
assert opened[-1][-1] == vid and len(opened) == 3
first = QTextCursor(w.editor.document().begin())
QTest.mouseClick(w.editor.viewport(), Qt.LeftButton, pos=w.editor.cursorRect(first).center())
assert len(opened) == 3  # a click off the link only moves the cursor
A.desk.can_embed = _can_embed
# the top bar finds anything: notes first here (no windows offscreen); Enter opens the highlighted one,
# the last row still captures a thought to the Inbox; t/c/i lines never search
w.index = A.find.FileIndex([os.path.dirname(vid)]).build()
def searched():  # the search runs in the background; wait for its answer
    for _ in range(200):
        app.processEvents()
        if w.results.isVisible() and getattr(w, "_hits_text", None) == w.capture.text().strip():
            return
        QTest.qWait(10)
    raise AssertionError("no search results")


w.capture.setText("session")
w.run_search()
searched()
labels = [w.results.item(i).text() for i in range(w.results.count())]
assert w.results.isVisible() and any("session 01.mp4" in l for l in labels)
assert labels[-1].endswith("Capture “session”      to the Inbox") and "Search the web" in labels[-2]
w.capture.setText("project x")
QTest.keyClick(w.capture, Qt.Key_Return)  # Enter before the background answer: it waits, never captures
assert w.current_note == "Project X.md" and not any(i["text"] == "project x" for i in core.parse_inbox())
w.capture.setText("project x")
w.run_search()
searched()
assert w._hits[0][:2] == ("note", "Project X")
QTest.keyClick(w.capture, Qt.Key_Return)
assert w.current_note == "Project X.md" and w.capture.text() == "" and not w.results.isVisible()
w.capture.setText("call mom about sunday")
w.run_search()
searched()
QTest.keyClick(w.capture, Qt.Key_Up)
w.results.setCurrentRow(w.results.count() - 1)
QTest.keyClick(w.capture, Qt.Key_Return)
assert any(i["text"] == "call mom about sunday" for i in core.parse_inbox())
w.capture.setText("t buy stamps")
w.run_search()
assert not w.results.isVisible()
w.on_capture()  # the shortest route: a task at once, no Inbox detour; a date said the way you'd say it
assert any(t["text"] == "buy stamps" for t in core.parse_tasks()) and w.capture.text() == ""
assert "bar_task" in core.load_settings()["learned"]  # Learn one thing moves on by itself
assert A.today_note.next_step(A.today_note.learned())[2] != A.today_note.LEARN[0][1]
w.capture.setText("t call the bank tomorrow")
w.on_capture()
due = A.date.today() + _td0(days=1)
assert any(t["text"] == f"call the bank due:{due.isoformat()}" for t in core.parse_tasks())
w.capture.setText("c tomorrow 2pm dentist")
w.on_capture()
assert any(e["title"] == "dentist" and e["time"] == "14:00" and e["date"] == due for e in core.read_local_events())
assert "On the calendar: dentist" in w.save_status.text()
w.capture.setText("c nonsense here")  # a bad event line: said in the status line, kept in the bar to fix
w.on_capture()
assert w.capture.text() == "c nonsense here" and "write it as c" in w.save_status.text()
w.capture.setText("i maybe learn piano")
w.on_capture()
assert any(i["text"] == "maybe learn piano" for i in core.parse_inbox())
w.capture.clear()
w.open_today()  # File > Today on any system
for _ in range(2):  # the background rebuild (after a task change, or coming back to the window) lands without errors
    w._today_busy = False
    w.update_today()
    for _ in range(300):
        app.processEvents()
        if not w._today_busy:
            break
        QTest.qWait(10)
    assert not w._today_busy and w._today_at > 0
w.open_today()  # again: still the same note: written now, opened, and kept current from then on
assert w.current_note == "Today.md" and "# Today" in w.editor.toPlainText()
w.open_note("Project X.md")
# hundreds of tasks: each group shows the nearest 40 and says how many more, so a refresh stays instant
core.write_note("Lots.md", "".join(f"t chore {i}\n" for i in range(120)))
w.refresh_tasks()
rows = [w.tasks_list.item(i).text() for i in range(w.tasks_list.count())]
assert any(r.startswith("…and ") and "more" in r for r in rows) and w.tasks_list.count() < 160
core.delete_note("Lots.md")
w.refresh_tasks()
w.start_update_check()  # tests never update: SIMPLEBRAIN_NO_UPDATE
assert not w._update_pending and "off" in w.update_state  # Help > About says where updates stand
w.on_update_done("")  # an update landed: it waits for you to step away, never restarts mid-typing
assert w._update_pending and "restarts itself" in w.save_status.text()
w.activateWindow()
w._restart_timer.stop()
w.handle_command("toggle")  # Super+J with the window active: out of the way; again: back
w.handle_command("show")
assert w.isVisible()
# graph icons: an emoji or a round picture replaces the dot and is clickable all over; right-click never opens the note
from PySide6.QtGui import QPixmap  # noqa: E402
g = w.graph
was_open = w.current_note
w.open_note("Home.md")
g.settle()
plain = g.radius("Home.md")
leaf = next(n for n in g.pos if n != "Home.md" and n not in g.missing)
g.set_icon("Home.md", emoji="🏠")
assert core.graph_icons() == {"Home.md": "🏠"} and g.icon("Home.md") == ("emoji", "🏠") and g.radius("Home.md") > plain
pic = os.path.join(tempfile.mkdtemp(), "house.png")
pm = QPixmap(40, 20)
pm.fill(Qt.red)
assert pm.save(pic)
g.set_icon(leaf, picture=pic)
kind, round_pm = g.icon(leaf)
assert kind == "picture" and round_pm.width() == round_pm.height() == 128  # cropped square, not stretched
g.repaint()  # paints emoji, picture and plain dots together without error
opened, menus = [], []
g.on_open = opened.append
s = g.to_screen(*g.pos[leaf])
edge = QPoint(int(s.x() + g.radius(leaf) * g.zoom - 2), int(s.y()))  # near the rim of the picture
assert g.node_at(edge) == leaf


def grab_menu():
    m = QApplication.activePopupWidget()
    if m:
        menus.append([a.text() for a in m.actions()])
        m.close()


QTimer.singleShot(50, grab_menu)
QTest.mouseClick(g, Qt.RightButton, Qt.NoModifier, edge)
app.processEvents()
assert opened == []  # right-click shows the menu, it doesn't move to the note
if menus:  # the platform delivered the context menu: it offers the choices and the way back
    assert any("House" in t for t in menus[0]) and "Picture from a file…" in menus[0] and "Back to a plain dot" in menus[0]
QTest.mouseClick(g, Qt.LeftButton, Qt.NoModifier, edge)
assert opened == [leaf]
g.on_open = w.open_link
os.remove(core.graph_icon_picture(core.graph_icons()[leaf]))
assert g.icon(leaf) is None and g.radius(leaf) == plain - 4  # a lost picture falls back to the dot
g.repaint()
g.set_icon("Home.md")
g.set_icon(leaf)
assert core.graph_icons() == {}
w.open_note("Home.md")  # website checkbox: shows the saved state, and a toggle is saved per note
core.set_public("Home.md", True)
w.open_note("Project X.md")
assert not w.public_box.isChecked()
w.open_note("Home.md")
assert w.public_box.isChecked()
core.set_public("Home.md", False)
w.open_note("Project X.md")
assert w.library_box.isHidden()  # personal/public library: only on book notes
w.create_note("Book Y", content=core.learning_note_template("Book Y"))
assert not w.library_box.isHidden() and not w.library_box.isChecked()
w.library_box.setChecked(True)
assert "library:: personal" in w.editor.toPlainText()
w.save_current()
w.open_note("Project X.md")
w.open_note("Book Y.md")
assert w.library_box.isChecked() and core.library_of(core.read_note("Book Y.md")) == "personal"
w.library_box.setChecked(False)
assert w.editor.toPlainText().count("library::") == 1 and "library:: public" in w.editor.toPlainText()
w.open_note("Project X.md")
# rename from the note list: the pencil changes the name and every link to it, and the editor follows
def pencil(filename):
    """The pencil on that note's row (the row's buttons show when it's selected or hovered)."""
    for i in range(w.notes_list.count()):
        if w.notes_list.item(i).data(Qt.UserRole) == filename:
            w.note_buttons.show_for(w.notes_list.item(i))
            return [b for b in w.note_buttons.buttons() if b.text() == "✎"]
    return None
assert pencil("Home.md") == []  # the starting note keeps its name
core.write_note("Linker.md", "# Linker\nsee [[Project X]]\n")
w.refresh_notes_list()
w.open_note("Linker.md")
w.ask_text = lambda *_a: "Project Y"
QTest.mouseClick(pencil("Project X.md")[0], Qt.LeftButton)
app.processEvents()
assert os.path.exists(os.path.join(core.VAULT, "Project Y.md")) and not os.path.exists(os.path.join(core.VAULT, "Project X.md"))
assert "[[Project Y]]" in core.read_note("Linker.md") and "[[Project Y]]" in w.editor.toPlainText() and w.current_note == "Linker.md"
assert "Renamed to 'Project Y'" in w.save_status.text() and pencil("Project Y.md") and not pencil("Project X.md")
assert "Project Y.md" in {r["file"] for r in core.note_rows()} and w.dv_table.rowCount() == len(core.list_user_notes())
w.open_note("Project Y.md")  # renaming the open note keeps what was typed and keeps it open
w.editor.setPlainText(w.editor.toPlainText() + "typed just before\n")
w.ask_text = lambda *_a: "Project Z"
QTest.mouseClick(pencil("Project Y.md")[0], Qt.LeftButton)
app.processEvents()
assert w.current_note == "Project Z.md" and "typed just before" in core.read_note("Project Z.md") and "typed just before" in w.editor.toPlainText()
assert not os.path.exists(os.path.join(core.VAULT, "Project Y.md")) and "[[Project Z]]" in core.read_note("Linker.md")
w._err = ""
w.ask_text = lambda *_a: "Linker"  # a taken name is refused with a reason and nothing moves
QTest.mouseClick(pencil("Project Z.md")[0], Qt.LeftButton)
assert "already" in w._err and os.path.exists(os.path.join(core.VAULT, "Project Z.md")) and w.current_note == "Project Z.md"
# File > Broken links lists links to notes that don't exist, and opens a note that uses one
core.write_note("Typo Maker.md", "# Typo Maker\nsee [[Nowhere Note]]\n")
shown = {}
def inspect_dialog():
    lst = w.broken_dialog.findChildren(A.QListWidget)[0]
    shown["rows"] = [lst.item(i).text() for i in range(lst.count())]
    mine = [i for i in range(lst.count()) if "Nowhere Note" in lst.item(i).text()][0]
    lst.itemActivated.emit(lst.item(mine))
QTimer.singleShot(100, inspect_dialog)
w.on_broken_links()
assert "[[Nowhere Note]]   used in: Typo Maker" in shown["rows"] and w.current_note == "Typo Maker.md"
os.remove(os.path.join(core.VAULT, "Typo Maker.md"))
w.refresh_notes_list()
w.open_note("Home.md")
# the tutorial, replayed (How to): every step rings something inside the window, keys and buttons move through it,
# Next never waits, Esc leaves, and the practice task it adds goes away
core.save_settings({**core.load_settings(), "tour_done": "yes", "tour_version": w.TOUR_VERSION})
for size in ((1500, 950), (420, 320)):
    w.resize(*size)
    app.processEvents()
    w.start_tour()
    t = w.tour
    assert t is not None and not t.required and t.i == 0 and not t.back_button.isEnabled() and not t.skip_button.isHidden()
    for step in range(len(t.steps)):
        assert not t.target.isNull() and QRectF(t.rect()).contains(t.target), (size, step, t.target)  # something is ringed, within the window
        assert QRectF(t.rect()).contains(QRectF(t.card.geometry())), (size, step)  # and the card can be read
        assert t.count.text() == f"{step + 1} of {len(t.steps)}" and t.next_button.isEnabled()
        t.grab()  # paints the dimmed window and ring without error
        if step < len(t.steps) - 1:
            QTest.keyClick(t, Qt.Key_Right if step % 2 == 0 else Qt.Key_Return)
    assert t.next_button.text() == "Done" and t.i == len(t.steps) - 1
    QTest.keyClick(t, Qt.Key_Left)
    assert t.i == len(t.steps) - 2
    QTest.mouseClick(t.next_button, Qt.LeftButton)
    QTest.mouseClick(t.back_button, Qt.LeftButton)
    assert t.i == len(t.steps) - 2
    QTest.mouseClick(t.skip_button if size[0] > 1000 else t.next_button, Qt.LeftButton)
    if w.tour:  # small window: Next moved to the last step; Esc leaves
        QTest.keyClick(w.tour, Qt.Key_Escape)
    app.processEvents()
    assert w.tour is None and not any(x["text"].strip() == w.PRACTICE_TASK for x in core.parse_tasks())
w.start_tour()  # Help > Take the tour works any time, and a second call doesn't stack another
first = w.tour
w.start_tour()
assert w.tour is first
w.resize(1300, 900)
app.processEvents()
assert first.geometry() == w.rect()  # follows the window
QTest.keyClick(first, Qt.Key_Escape)
app.processEvents()
w.maybe_start_tour()
assert w.tour is None  # seen: not again on the next launch
QTest.mouseClick(w.how_button, Qt.LeftButton)  # the How to button runs it any time
assert w.tour is not None and not w.tour.required
QTest.keyClick(w.tour, Qt.Key_Escape)
app.processEvents()
# the required tutorial (first launch, or an update that changed it): no Skip, Esc and closing don't leave it, and
# each step's Next opens only once you've done the thing
kept = {f: core.read_note(f) if os.path.exists(os.path.join(core.VAULT, f)) else "" for f in (core.INBOX_FILE, core.CALENDAR_FILE)}
s_ = core.load_settings(); s_["tour_version"] = "0.3"; core.save_settings(s_)
w.maybe_start_tour()
t = w.tour
assert t is not None and t.required and t.skip_button.isHidden()
QTest.keyClick(t, Qt.Key_Escape)
w.close()
app.processEvents()
assert w.tour is t and w.isVisible() and "Finish the tutorial first" in t.body.text()
QTest.keyClick(t, Qt.Key_Right)
assert t.i == 1 and not t.next_button.isEnabled() and "i ask the library" in t.try_it.text()
QTest.keyClick(t, Qt.Key_Right)
assert t.i == 1  # not done yet: Next waits
assert not t.mask().contains(t.target.center().toPoint())  # the ringed bar takes clicks through the dimming
def do(action):
    action()
    app.processEvents()
    t.check_step()
    assert t.next_button.isEnabled() and "Done." in t.try_it.text(), (t.i, t.title.text())
    QTest.keyClick(t, Qt.Key_Right)
def bar(line):
    w.capture.setText(line)
    w.on_capture()
do(lambda: bar("i tutorial thought"))
do(lambda: (core.classify_as_task(core.parse_inbox()[-1], None), w.refresh_inbox()))
do(lambda: bar("t tutorial task sat"))
practice_ = next(x for x in core.parse_tasks() if x["text"].strip() == w.PRACTICE_TASK)
do(lambda: w.on_task_toggle(practice_))
assert not any(x["text"].strip() == w.PRACTICE_TASK for x in core.parse_tasks())  # ticked, then gone
do(lambda: bar("c tomorrow 2pm tutorial coffee"))
assert w.current_note != "Home.md"  # the notes step starts somewhere else, so clicking Home is a real step
do(lambda: w.open_note("Home.md"))
do(lambda: w.create_note("Tutorial Book", content=core.learning_note_template("Tutorial Book")))
assert t.step_widgets() == [w.library_box]
do(lambda: w.library_box.setChecked(True))
do(lambda: w.editor.appendPlainText("[[Home]]"))
do(lambda: w.open_note("Home.md"))
do(lambda: w.open_note("Tutorial Book.md"))
while t.i < len(t.steps) - 1:
    assert t.next_button.isEnabled()
    QTest.keyClick(t, Qt.Key_Right)
QTest.mouseClick(t.next_button, Qt.LeftButton)
app.processEvents()
assert w.tour is None and core.load_settings().get("tour_version") == w.TOUR_VERSION
w.open_note("Home.md")
os.remove(os.path.join(core.VAULT, "Tutorial Book.md"))
for f, old in kept.items():
    core.write_note(f, old)
w.refresh_notes_list()
w.refresh_tasks()
w.refresh_inbox()
w.resize(1500, 950)
app.processEvents()
# the watcher: ten minutes of drift bring one card; "Taking a break" keeps it quiet; time running out asks for a line
import simplebrain_watch as watch  # noqa: E402
from datetime import datetime as _dt, timedelta as _td  # noqa: E402
t0 = _dt(2026, 11, 2, 10, 0)
for i in range(11):
    w.on_watch("Reels • Instagram — librewolf", 0, t0 + _td(minutes=i))
assert w.cards and "Ten minutes on Instagram" in w.cards[0].label.text()  # the site, not the browser
assert [b.text() for b in w.cards[0].buttons] == ["Taking a break", "Back to it"]
x = A.Card("closes with ×", [])
x.show()
QTest.mouseClick(x.close_button, Qt.LeftButton)  # every card can be closed right away
assert not x.isVisible()
QTest.mouseClick(w.cards[0].buttons[0], Qt.LeftButton)
assert w.watch_state.get("snooze_until")
for i in range(11, 20):
    w.on_watch("Reels • Instagram — librewolf", 0, t0 + _td(minutes=i))
assert not any(c.isVisible() for c in w.cards)  # quiet during the break
core.write_note("Home.md", core.read_note("Home.md") + "\nlimit:: 25m\n")
w.on_watch("SimpleBrain", 0, t0 + _td(minutes=21))
assert "left" in w.watch_label.text() and w.watch_label.isVisible()
c = w.cards[0]
assert c.entry is not None and "10 minutes of computer time left" in c.label.text()
c.entry.setText("Study Group lesson 3, stopped at lists")
QTest.mouseClick(c.buttons[0], Qt.LeftButton)
assert watch.parked() == "Study Group lesson 3, stopped at lists"
core.write_note("Home.md", core.read_note("Home.md").replace("\nlimit:: 25m\n", "\n"))
assert os.path.exists(os.path.join(SETTINGS_DIR, "watch", "2026-11-02.json"))  # the day log: settings folder, never the vault
# the day's three are fixed at the first Today; one ticked off counts as done
core.write_note("Three.md", "# Three\nt first thing due:01-01-2026\nt second thing due:01-01-2026\n")
w.watch_state["day"] = {"date": _dt.now().date().isoformat(), "focus": 0, "drift": 0, "drift_by": {}}
w.open_today()
today_now()
assert 2 <= len(w.watch_state["day"]["three"]) <= 3, w.watch_state["day"]["three"]
three_task = next(t for t in core.parse_tasks() if t["text"].startswith("first thing"))
w.on_task_toggle(three_task)
w.refresh_tasks()
today_now()
assert w.watch_state["day"]["done"] and "done" not in w.watch_label.text()  # the x/3 count is gone from the top
import simplebrain_today as _today  # noqa: E402
_plan = _today.plan_path
_today.plan_path = lambda *a, **k: "/gone/plan.xlsx"  # the plan turned off or moved: no "all three done" for that
w.check_three()
assert w.watch_state["day"]["plan"] == "/gone/plan.xlsx" and not w.watch_state["day"]["done"]
_today.plan_path = _plan
os.remove(os.path.join(core.VAULT, "Three.md"))
w.refresh_tasks()
# linking like a pro: [[ offers titles, plain mentions become links in a click, related notes show their reason
w.open_note("Linker.md")
w.editor.moveCursor(QTextCursor.End)
QTest.keyClick(w.editor, Qt.Key_Return)
QTest.keyClicks(w.editor, "see [[Proj")
assert w.link_popup.isVisible() and w.link_popup.item(0).text() == "Project Z"
QTest.keyClick(w.editor, Qt.Key_Return)
assert w.editor.toPlainText().endswith("see [[Project Z]]") and not w.link_popup.isVisible()
w.save_current()
core.write_note("Mentioner.md", "# Mentioner\nproject z needs a budget.\nLike the Project Z plan.\n")
w.open_note("Project Z.md")
rows_now()
mention = [w.mentions_row.itemAt(i).widget() for i in range(w.mentions_row.count()) if w.mentions_row.itemAt(i).widget()]
assert any(isinstance(b, QPushButton) and b.text().startswith("Mentioner") for b in mention)
link_all = [b for b in mention if isinstance(b, QPushButton) and b.text() == "Link all"][0]
QTest.mouseClick(link_all, Qt.LeftButton)
assert core.read_note("Mentioner.md").count("[[Project Z]]") == 2
rows_now()
backs = [w.backlinks_row.itemAt(i).widget() for i in range(w.backlinks_row.count())]
assert any(isinstance(b, QPushButton) and "see [[Project Z]]" in b.toolTip() for b in backs)  # the line, not just the name
os.remove(os.path.join(core.VAULT, "Mentioner.md"))
# a workday that doesn't bury you: more than three due -> Spread out; an hour after coffee with someone: how did it go?
core.write_note("Pile.md", "# Pile\n" + "".join(f"t pile {i} due:{A.date.today().isoformat()}\n" for i in range(6)))
w.refresh_tasks()
assert w.spread_button.isVisible() is False or w.spread_button.text().startswith("Spread out (")
assert not w.spread_button.isHidden() and "(" in w.spread_button.text()
QTest.mouseClick(w.spread_button, Qt.LeftButton)
due_now = [t for t in core.parse_tasks() if not t["done"] and t["due"] and t["due"] <= A.date.today()]
assert len(due_now) <= 3 and w.spread_button.isHidden() and "Moved" in w.cards[0].label.text()
os.remove(os.path.join(core.VAULT, "Pile.md"))
w.refresh_tasks()
core.write_note("Dad.md", "# Dad\nevery:: 1 week\n")
now = A.datetime.now().replace(hour=15, minute=0, second=0, microsecond=0)
core.add_local_event(now.date().isoformat(), "13:00", "Coffee with [[Dad]]")
w.follow_up(now)
assert "How did it go?" not in w.cards[0].label.text()  # never on top of a card that's still up
w.cards[0].close()
app.processEvents()
w.follow_up(now)
c = w.cards[0]
assert "How did it go?" in c.label.text() and "Coffee with Dad" in c.label.text()
c.entry.setText("talked about the bond")
QTest.mouseClick(c.buttons[0], Qt.LeftButton)
assert core.read_note("Dad.md").rstrip().endswith(core.show_date(now.date()) + " talked about the bond")
w.follow_up(now)
assert not any(x.isVisible() for x in w.cards if not w._card_gone(x))  # asked once, never again
for i in range(95):  # ninety minutes straight: one card to stand up
    w.on_watch("SimpleBrain", 0, A.datetime(2026, 11, 3, 9, 0) + _td(minutes=i))
assert any("90 minutes straight" in x.label.text() for x in w.cards if not w._card_gone(x))
file_items = [a.text() for a in w.file_menu.actions()]
assert "&Email (connect yours)…" in file_items and "&Money, forward…" in file_items
assert not any("KeePass" in t for t in file_items)  # KeePassXC unlock removed (0.5.2)
assert not any("desktop" in t.lower() for t in file_items)  # an ordinary program: no desktop items (0.5.3)
# connecting your own email and website: steps per service, tried before saving
import simplebrain_setup as S  # noqa: E402
import simplebrain_publish as P  # noqa: E402
dlg = S.EmailSetup(w)
dlg.email.setText("me@gmail.com")
dlg.next()
assert dlg.stack.currentIndex() == 1 and dlg.key() == "gmail" and "app password" in dlg.steps.text()
assert dlg.open_btn.isVisibleTo(dlg) and not dlg.servers.isVisibleTo(dlg) and dlg.next_btn.text() == "Connect"
dlg.next()  # no password yet: says so, nothing saved
assert "Paste the password" in dlg.status.text() and dlg.saved is None
dlg.go(0)
dlg.email.setText("me@hotmail.com")
dlg.next()
assert dlg.key() == "outlook" and not dlg.next_btn.isEnabled() and "Microsoft" in dlg.steps.text()
dlg.reject()
dlg = S.WebsiteSetup(w)
assert [dlg.group.button(i).text().split(":")[0] for i in range(3)] == ["WordPress", "Shopify", "Any other website"]
dlg.group.button(2).setChecked(True)
dlg.next()
assert "index.html" in dlg.steps.text() and not dlg.open_btn.isVisibleTo(dlg)
site_dir = tempfile.mkdtemp()
dlg.folder.setText(site_dir)
dlg.next()  # Connect: tried on a thread, then saved
for _ in range(300):
    app.processEvents()
    if dlg.saved:
        break
    QTest.qWait(10)
assert dlg.saved == {"kind": "folder", "folder": site_dir} and P.site_config() == dlg.saved
dlg = S.WebsiteSetup(w)
assert dlg.kind() == "folder" and "Connected now" in dlg.stack.widget(0).findChildren(S.QLabel)[1].text()  # opens on what's set up
dlg.group.button(0).setChecked(True)
dlg.next()
assert "Application Passwords" in dlg.steps.text() and dlg.open_btn.text() == "Open my WordPress profile"
dlg.next()  # WordPress with nothing filled in
assert "Fill in" in dlg.status.text()
dlg.turn_off()
assert P.site_config() is None
# a course folder: the next session in order, one click; opening it moves Next on
course = tempfile.mkdtemp()
for f in ("Session 10.mp3", "Session 2.mp3", "Session 1.mp3"):
    open(os.path.join(course, f), "w").close()
core.write_note("Course.md", f"# Course\ncourse:: {course}\n")
w.open_note("Course.md")
row_btns = [w.files_row.itemAt(i).widget() for i in range(w.files_row.count()) if w.files_row.itemAt(i).widget()]
nxt = [b for b in row_btns if isinstance(b, QPushButton) and b.text().startswith("▶ Next")]
assert nxt and nxt[0].text() == "▶ Next: Session 1  (1 of 3)"
w.opener = (rec := []).append
QTest.mouseClick(nxt[0], Qt.LeftButton)
w.render_links()
row_btns = [w.files_row.itemAt(i).widget() for i in range(w.files_row.count()) if w.files_row.itemAt(i).widget()]
assert any(isinstance(b, QPushButton) and b.text() == "▶ Next: Session 2  (2 of 3)" for b in row_btns)
os.remove(os.path.join(core.VAULT, "Course.md"))
# a dropped Markdown file becomes a note (yours are never replaced); Settings lines count like Home's
mdf = os.path.join(HOME, "Settings.md")
open(mdf, "w").write("# Settings\napp:: Chime https://app.chime.com\n")
w.file_paths([mdf])
assert os.path.exists(os.path.join(core.VAULT, "Settings.md")) and ("Chime", "https://app.chime.com") in w.web_apps()
for _ in range(100):  # the original is filed by a background thread: let it finish first
    app.processEvents()
    if not os.path.exists(mdf):
        break
    _time.sleep(0.02)
assert w.add_dropped_notes([mdf]) == []  # gone already (filed): no crash
mdf2 = os.path.join(tempfile.mkdtemp(), "Settings.md")
open(mdf2, "w").write("# Settings\nreplaced?\n")
w.add_dropped_notes([mdf2])
assert "Chime" in core.read_note("Settings.md")
os.remove(os.path.join(core.VAULT, "Settings.md"))
for _ in range(50):  # the filing thread finishes
    app.processEvents()
    _time.sleep(0.02)
assert not hasattr(w, "focus_button") and not hasattr(w, "toggle_focus")  # Focus went at the user's request
# an unexpected error: logged and shown in one line, the window stays and the note is saved
try:
    raise ValueError("test boom")
except ValueError:
    A.crash_guard(*sys.exc_info())
assert "Something went wrong" in w.save_status.text() and "test boom" in open(os.path.join(SETTINGS_DIR, "crash.log")).read()
# pictures and videos open inside the window, where the graph is; × goes back to the graph
picf = os.path.join(tempfile.mkdtemp(), "screen shot.png")
pm2 = QPixmap(64, 48)
pm2.fill(Qt.blue)
pm2.save(picf)
w.on_note_link("file", picf)
assert w.viewer.isVisible() and not w.graph.isVisible() and w.viewer.picture.pixmap() is not None
assert w.viewer.title.text() == "screen shot.png" and not w.viewer.host.isVisible()
played = []
w.embed_launcher = played.append
vidf = os.path.join(tempfile.mkdtemp(), "session 02.mp4")
open(vidf, "w").close()
_real_can_embed = A.desk.can_embed
A.desk.can_embed = lambda *a, **k: True
w.on_note_link("file", vidf)
assert played and "--wid=" in " ".join(played[-1]) and played[-1][-1] == vidf and "--no-fullscreen" in played[-1]
assert w.viewer.host.isVisible() and w.viewer.title.text().endswith("session 02.mp4")
QTest.mouseClick(w.viewer.close_button, Qt.LeftButton)
A.desk.can_embed = _real_can_embed
assert w.graph.isVisible() and not w.viewer.isVisible()
# Dataview like Obsidian's: fields become columns by themselves; a query in the box; a ```dataview block in a note
core.write_note("Proj A.md", "# Proj A\nstatus:: active\npriority:: 2\n#project\nt draft plan due:2026-11-03\n")
core.write_note("Proj B.md", "# Proj B\nstatus:: done\npriority:: 1\n#project\n")
w.dv_search.clear()
w.refresh_dataview()
heads = [w.dv_table.horizontalHeaderItem(i).text() for i in range(w.dv_table.columnCount())]
assert heads[:4] == ["Title", "Tags", "Links", "Linked from"] and {"status", "priority"} <= set(heads[4:])
w.dv_search.setText('TABLE status, priority FROM #project WHERE status != "done" SORT priority')
assert [w.dv_table.horizontalHeaderItem(i).text() for i in range(w.dv_table.columnCount())] == ["File", "status", "priority"]
assert w.dv_table.rowCount() == 1 and w.dv_table.item(0, 0).text() == "[[Proj A]]" and w.dv_table.item(0, 0).data(Qt.UserRole) == "Proj A.md"
w.dv_search.setText("TABLE status FROM 42")
assert "Not a query yet" in w.dv_table.item(0, 0).text()  # a typo says so, never a box to click
w.dv_search.clear()
core.write_note("Dash.md", "# Dash\n```dataview\nTABLE status FROM #project SORT file.name\n```\n```dataview\nTASK FROM #project WHERE !completed\n```\n")
w.open_note("Dash.md")
assert w.query_box.isVisible()
views = [w.query_lay.itemAt(i).widget() for i in range(w.query_lay.count())]
table = next(v for v in views if isinstance(v, A.QTableWidget))
assert table.rowCount() == 2 and table.item(1, 1).text() == "done"
tasks = next(v for v in views if isinstance(v, A.QListWidget))
assert tasks.count() == 1 and "draft plan" in tasks.item(0).text()
tasks.item(0).setCheckState(Qt.Checked)  # ticked under the query: written into its own note
app.processEvents()
assert "- [x] draft plan" in core.read_note("Proj A.md")
w.open_note("Home.md")
assert not w.query_box.isVisible()
for f in ("Proj A.md", "Proj B.md", "Dash.md"):
    os.remove(os.path.join(core.VAULT, f))
w.refresh_notes_list()
w.refresh_dataview()
# a plan workbook action due today is in Tasks; ticking it (or its twin task in a note) does both, at once
pdir2 = tempfile.mkdtemp()
A.today_note._write_xlsx(os.path.join(pdir2, "plan.xlsx"), [["Date", "Action", "Status"],
                                                           [core.show_date(A.date.today()), "Phone Screen Time limits", ""]])
core.write_note("Settings.md", f"# Settings\nplan:: {os.path.join(pdir2, 'plan.xlsx')}\n")
core.write_note("Phone.md", f"# Phone\nt Phone Screen Time: downtime 11:30pm due:{A.date.today().isoformat()}\n")
w.refresh_tasks()
plan_row = next(w.tasks_list.item(i) for i in range(w.tasks_list.count())
                if isinstance(w.tasks_list.item(i).data(Qt.UserRole), dict) and w.tasks_list.item(i).data(Qt.UserRole).get("plan"))
assert plan_row.text().endswith("from the plan")
w.tasks_list.setCurrentItem(plan_row)
assert w.task_buttons.buttons() == []  # changed in its workbook, not here
plan_row.setCheckState(Qt.Checked)
app.processEvents()
assert A.today_note.plan_items(os.path.join(pdir2, "plan.xlsx")) == []  # done, without touching the workbook
assert "- [x] Phone Screen Time" in core.read_note("Phone.md")  # and its twin in the note with it
for f in ("Settings.md", "Phone.md"):
    os.remove(os.path.join(core.VAULT, f))
w.refresh_tasks()
# a daily habit: ticked, it's done for today and back tomorrow
core.write_note("Habit.md", f"# Habit\nt Python module every:day due:{A.date.today().isoformat()}\n")
w.refresh_tasks()
hab = next(w.tasks_list.item(i) for i in range(w.tasks_list.count())
           if isinstance(w.tasks_list.item(i).data(Qt.UserRole), dict) and "Python module" in w.tasks_list.item(i).text())
hab.setCheckState(Qt.Checked)
app.processEvents()
tomorrow = (A.date.today() + _td0(days=1)).isoformat()
assert f"t Python module every:day due:{tomorrow}" in core.read_note("Habit.md") and "back" in w.save_status.text()
os.remove(os.path.join(core.VAULT, "Habit.md"))
w.refresh_tasks()
# accounts as apps: an app:: line in Home is found from the top bar and opens in its own window
core.write_note("Apps.md", "# Apps\napp:: Fastmail https://app.fastmail.com\n")
launched = []
w.opener = launched.append
w.capture.setText("fastm")
w.run_search()
for _ in range(300):  # the search answers from a thread
    app.processEvents()
    if getattr(w, "_hits_text", None) == "fastm":
        break
    QTest.qWait(10)
assert w._hits[0][:2] == ("webapp", "Fastmail")
_real_windows, A.desk.windows = A.desk.windows, dict  # a real Fastmail window open on this computer would be raised instead
QTest.keyClick(w.capture, Qt.Key_Return)
A.desk.windows = _real_windows
assert launched and "https://app.fastmail.com" in " ".join(launched[-1])
# mail that needs you: shown as one card, listed in Today; nothing is fetched in tests
w.on_mail(["Riverside College: Your payment plan", "Dad: Bond papers"])
assert "Mail that needs you" in w.cards[0].label.text() and [b.text() for b in w.cards[0].buttons] == ["Open mail"]
w.open_today()
assert "## Mail that needs you\n- Riverside College: Your payment plan" in w.editor.toPlainText()
w.cards[0].close()
os.remove(os.path.join(core.VAULT, "Apps.md"))
# mail inside SimpleBrain: inbox, the whole email, reply, archive, a task and an event from it (fake account, no network)
import simplebrain_mailwin as MW  # noqa: E402


class FakeAccount:
    def __init__(self, *a):
        self.box = [{"id": "m1", "from": "Amy", "email": "amy@x.org", "subject": "Lunch?", "preview": "", "unread": True,
                     "when": "2026-11-01T15:00:00Z"},
                    {"id": "m2", "from": "Bob", "email": "bob@y.com", "subject": "Plan", "preview": "", "unread": False,
                     "when": "2026-11-01T14:00:00Z"}]
        self.read, self.sent, self.moved = [], [], []

    def identities(self):
        return [{"id": "i1", "email": "me@me.com", "name": "Me"}]

    def inbox(self, limit=60):
        return [dict(m) for m in self.box]

    def message(self, eid):
        m = next(x for x in self.box if x["id"] == eid)
        return {"id": eid, "subject": m["subject"], "from": [{"name": m["from"], "email": m["email"]}],
                "to": [{"email": "me@me.com"}], "cc": [], "receivedAt": m["when"], "messageId": ["<x>"],
                "text": f"Hi, {m['subject']} see https://x.org/a", "from_text": m["from"], "to_text": "me@me.com",
                "cc_text": ""}

    def mark_read(self, eid, read=True):
        self.read.append((eid, read))

    def archive(self, eid):
        self.moved.append(("archive", eid))
        self.box = [m for m in self.box if m["id"] != eid]

    def trash(self, eid):
        self.moved.append(("trash", eid))
        self.box = [m for m in self.box if m["id"] != eid]

    def send(self, *a):
        self.sent.append(a)


fake = FakeAccount()
_real_open, _real_cfg = MW.mail.open_account, MW.mail.load_config
MW.mail.open_account, MW.mail.load_config = (lambda cfg: fake), (lambda: {"kind": "jmap", "token": "t", "session": "s"})


def settle(cond):
    for _ in range(300):
        app.processEvents()
        if cond():
            return True
        QTest.qWait(10)
    return False


_now = A.datetime(2026, 11, 1, 18, 0).astimezone()
assert MW.when_text(_now.replace(hour=15, minute=4).isoformat(), _now) == "3:04 PM"
assert MW.when_text((_now - _td0(days=1)).isoformat(), _now) == "Yesterday"
assert MW.when_text(_now.replace(month=10, day=3).isoformat(), _now) == "Oct 3" and MW.when_text("junk") == ""
mw = w.open_mail()
assert settle(lambda: mw.list.count() == 2) and "2, 1 unread" in mw.status.text()
mw.list.setCurrentRow(0)
assert settle(lambda: mw.msg and mw.msg["id"] == "m1") and "Lunch?" in mw.head.text()
assert 'href="https://x.org/a"' in mw.body.toHtml() and settle(lambda: ("m1", True) in fake.read)  # opened = read
assert mw.buttons["Reply"].isEnabled()
_exec = MW.ComposeDialog.exec
seen_compose = []
MW.ComposeDialog.exec = lambda d: (seen_compose.append((d.to.text(), d.subject.text(), d.body.toPlainText())), d.send(),
                                   settle(lambda: fake.sent), 1)[-1]
mw.reply()
assert seen_compose[-1][0] == "Amy <amy@x.org>" and seen_compose[-1][1] == "Re: Lunch?" and "> Hi, Lunch?" in seen_compose[-1][2]
assert fake.sent[-1][0] == "Amy <amy@x.org>" and fake.sent[-1][5]["id"] == "m1"  # threaded as a reply
MW.ComposeDialog.exec = _exec
answers = iter(["fri"])
_ask = w.ask_text
w.ask_text = lambda *a, **k: next(answers)
mw.make_task()
assert "[[Mail - Lunch]]" in core.read_note(core.INBOX_FILE) and os.path.exists(os.path.join(core.VAULT, "Mail - Lunch.md"))
assert "Hi, Lunch?" in core.read_note("Mail - Lunch.md")
answers = iter([(A.date.today() + _td0(days=3)).strftime("%m-%d-%Y"), "2pm", "Lunch with Amy"])
_cpd, w.confirm_past_date = w.confirm_past_date, (lambda _d: True)  # an earlier test left it saying no
mw.make_event()
w.confirm_past_date = _cpd
assert any(e["title"] == "Lunch with Amy [[Mail - Lunch]]" and e["time"] == "14:00" for e in core.read_local_events())
w.ask_text = _ask
mw.archive()
assert settle(lambda: ("archive", "m1") in fake.moved) and settle(lambda: mw.list.count() == 1)
assert settle(lambda: mw.msg and mw.msg["id"] == "m2")  # the next one opens by itself
mw.delete()
assert settle(lambda: ("trash", "m2") in fake.moved) and settle(lambda: mw.list.count() == 0)
fake.inbox = lambda limit=60: (_ for _ in ()).throw(OSError("server down"))  # an error must reach the status line
mw.refresh()
assert settle(lambda: "server down" in mw.status.text())
mw.close()
MW.mail.open_account, MW.mail.load_config = _real_open, _real_cfg
for e in [e for e in core.read_local_events() if "Lunch with Amy" in e["title"]]:
    core.delete_local_event(e)
os.remove(os.path.join(core.VAULT, "Mail - Lunch.md"))
# the calendar inside SimpleBrain: any day, add / edit / delete, a Calendar.md line moved to the real calendar
import simplebrain_calwin as CW  # noqa: E402

D0 = A.date.today() + _td0(days=2)


class FakeCal:
    def __init__(self):
        self.evs = [{"date": D0, "time": "15:00", "end_time": "16:30", "title": "Dentist", "location": "Main St",
                     "notes": "", "repeats": False, "href": "/a.ics", "etag": '"1"', "source": "caldav"},
                    {"date": D0, "time": None, "title": "Trash day", "location": "", "notes": "", "repeats": True,
                     "href": "/r.ics", "etag": '"1"', "source": "caldav"}]
        self.log = []

    def events(self, start, end):
        return [dict(e) for e in self.evs if start <= e["date"] <= end]

    def create(self, ev):
        self.log.append(("create", ev["title"]))
        self.evs.append({**ev, "repeats": False, "href": f"/n{len(self.evs)}.ics", "etag": '"1"', "source": "caldav"})

    def update(self, ref, ev):
        self.log.append(("update", ref["href"], ev["title"]))
        for e in self.evs:
            if e["href"] == ref["href"]:
                e.update({k: v for k, v in ev.items() if not (e["repeats"] and k in ("date", "time", "end_time"))})

    def delete(self, ref):
        self.log.append(("delete", ref["href"]))
        self.evs = [e for e in self.evs if e["href"] != ref["href"]]

    def skip(self, ref):
        self.log.append(("skip", ref["href"], ref["date"]))


fc = FakeCal()
_real_conn = CW.calendar.connected
CW.calendar.connected = lambda *a: fc
core.add_local_event(D0.isoformat(), "09:00", "typed here")
cw = w.open_calendar_window()
cw.month.setSelectedDate(CW.qd(D0))
assert settle(lambda: any(e["title"] == "Dentist" for e in cw.events))


def rows():
    return [cw.list.item(i).text().strip() for i in range(cw.list.count())]


def pick(title):
    for i in range(cw.list.count()):
        e = cw.list.item(i).data(Qt.UserRole)
        if e and e["title"] == title:
            cw.list.setCurrentRow(i)
            return e
    raise AssertionError(f"{title} not listed: {rows()}")


cw.show_days()
assert any("15:00–16:30   Dentist  ·  Main St" in r for r in rows()) and any("typed here" in r for r in rows())
assert cw.month.dateTextFormat(CW.qd(D0)).fontWeight() == CW.QFont.Bold  # days with events stand out
_dlg_exec = CW.EventDialog.exec
edits = []


def fake_exec(d):
    edits.pop(0)(d)
    return 1


CW.EventDialog.exec = fake_exec
pick("Dentist")
assert "Main St" in cw.detail.text() and cw.edit_btn.isEnabled() and not cw.skip_btn.isVisible()
edits.append(lambda d: (d.title.setText("Dentist, moved"), d.place.setText("Elm St")))
cw.edit_event()
assert settle(lambda: ("update", "/a.ics", "Dentist, moved") in fc.log)
assert settle(lambda: any(e["title"] == "Dentist, moved" and e["location"] == "Elm St" for e in cw.events))
edits.append(lambda d: (d.title.setText("Gym"), d.all_day.setChecked(False), d.start.setTime(CW.QTime(18, 0)),
                        d.place.setText("Y")))
cw.new_event(D0)
assert settle(lambda: ("create", "Gym") in fc.log)
assert next(e for e in fc.evs if e["title"] == "Gym")["time"] == "18:00"
assert settle(lambda: any(e["title"] == "Gym" for e in cw.events))
pick("typed here")  # a Calendar.md line, saved here, becomes a real calendar event and the line goes
edits.append(lambda d: d.notes.setPlainText("bring water"))
cw.edit_event()
assert settle(lambda: ("create", "typed here") in fc.log)
assert settle(lambda: not any(e["title"] == "typed here" for e in core.read_local_events()))
assert next(e for e in fc.evs if e["title"] == "typed here")["notes"] == "bring water"
settle(lambda: any(e["title"] == "typed here" and e.get("source") == "caldav" for e in cw.events))
pick("Trash day")
assert cw.skip_btn.isVisible()
cw.skip_date()
assert settle(lambda: ("skip", "/r.ics", D0) in fc.log)
_q = CW.QMessageBox.question
CW.QMessageBox.question = staticmethod(lambda *a: CW.QMessageBox.Yes)
settle(lambda: any(e["title"] == "Gym" for e in cw.events))
pick("Gym")
cw.delete_event()
assert settle(lambda: ("delete", "/n2.ics") in fc.log)
CW.QMessageBox.question = _q
CW.EventDialog.exec = _dlg_exec
fc.events = lambda *a: (_ for _ in ()).throw(OSError("calendar down"))
cw.load()
assert settle(lambda: "calendar down" in cw.status.text())
cw.close()
CW.calendar.connected = _real_conn
# money, forward: the Budget note is made on first open; the ring view projects it; a goal can be left out
mw = w.open_money()
assert os.path.exists(os.path.join(core.VAULT, "Budget.md")) and mw.isVisible()
core.write_note("Budget.md", "# Budget\ncash:: 100\n+ 50 Pay every friday\n- 20 Phone monthly 15\n"
                f"goal:: 5000 Trip {A.core.show_date(A.date.today() + _td(days=10))}\n")
mw.close()
mw = w.open_money()
assert mw.b["cash"] == 100 and any(g["title"] == "Trip" for g in mw.b["goals"])
before = mw.view.p["end"]
chip = [b for b in mw.findChildren(QPushButton) if b.text().startswith("◆ Trip")][0]
trip = next(g for g in mw.view.p["goals"] if g["title"] == "Trip")
assert trip["funded"] is False and trip["short"] > 0 and "needs" not in chip.text()  # a goal that doesn't fit yet
chip.setChecked(False)  # what if I skip it?
assert mw.view.p["end"] == before and "Trip" in mw.skip  # it never sank the projection; now it's just left out
mw.view._anim.setCurrentTime(700)
mw.view.repaint()  # ring, road and goal diamonds paint without error
assert w.money_button.text().startswith("$") or w.money_button.text().startswith("-$")
w.update_money_button()
mw.close()
w.open_today()
assert "**Money:** " in w.editor.toPlainText()
# drop it and it's filed: PARA folders under home, linked from the matching note, Undo puts it back
assert w.para and not os.path.exists(os.path.join(w.para, "Drop")) and w._drop_watch is None  # nothing made at start
A.QDesktopServices.openUrl, _open_url = (lambda *_a: True), A.QDesktopServices.openUrl
w.open_drop_folder()  # first use makes it and starts watching
A.QDesktopServices.openUrl = _open_url
assert os.path.isdir(os.path.join(w.para, "Drop")) and w._drop_watch is not None
os.makedirs(os.path.join(w.para, "Projects", "walker-supply"), exist_ok=True)
dropped = os.path.join(HOME, "walker supply lease.pdf")
open(dropped, "w").close()
done = A.drop.file_all([dropped], w.para)
w.on_filed(done)
assert os.path.exists(os.path.join(w.para, "Projects", "walker-supply", "walker supply lease.pdf"))
assert "Filed 1" in w.cards[0].label.text() and [b.text() for b in w.cards[0].buttons] == ["Undo", "Open folder"]
QTest.mouseClick(w.cards[0].buttons[0], Qt.LeftButton)
assert os.path.exists(dropped)
w.open_note("Project Z.md")
from PySide6.QtCore import QMimeData, QUrl  # noqa: E402
from PySide6.QtGui import QDropEvent  # noqa: E402
md = QMimeData()
md.setUrls([QUrl.fromLocalFile(dropped)])
ev = QDropEvent(A.QPointF(10, 10), Qt.CopyAction, md, Qt.LeftButton, Qt.NoModifier)
assert w.eventFilter(w.editor.viewport(), ev)  # a drop on the open note files it with that note
for _ in range(50):
    app.processEvents()
    _time.sleep(0.02)
    if "walker supply lease.pdf" in core.read_note("Project Z.md"):
        break
assert "file:: " in core.read_note("Project Z.md") and not os.path.exists(dropped)
w.open_note(was_open)  # the closing check below edits the note that was open
w.editor.setPlainText(w.editor.toPlainText() + "\nclosing edit\n")
w.close()
assert "closing edit" in core.read_note("Project X.md")  # quitting saves
print("app test OK")
