"""Headless end-to-end check of the Qt app in a throwaway vault.
Run: QT_QPA_PLATFORM=offscreen python tests/test_app.py"""
import os
import sys
import tempfile

os.environ["SIMPLEBRAIN_VAULT"] = tempfile.mkdtemp()
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import simplebrain_app as A  # noqa: E402
import simplebrain_core as core  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication([])
w = A.SimpleBrain()
w.show()
app.processEvents()
assert os.path.exists(os.path.join(core.VAULT, "Home.md")) and w.current_note == "Home.md"
w.capture.setText("buy milk")
w.on_capture()
assert core.parse_inbox()[0]["text"] == "buy milk"
w.create_note("Project X")
w.editor.setPlainText("# Project X\n\nsee [[Home]] #work\n- [ ] ship it due:2020-01-01\n")
w.open_note("Home.md")  # switching notes saves the previous one
assert "\nt ship it due:2020-01-01" in core.read_note("Project X.md")  # old format converted on save
app.processEvents()  # the save refreshes Tasks on its own, no Refresh click
assert w.tasks_list.count() >= 2
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
under = g.to_screen(nx, ny)
g.zoom_at(under, 2.0)
assert g.zoom == 2.0 and abs(g.to_screen(nx, ny).x() - under.x()) < 1e-6
g.offset += A.QPointF(40, -25)
assert g.node_at(g.to_screen(nx, ny)) == node
g.zoom_at(under, 1000)
assert g.zoom == 5.0  # clamped
g.recompute()
assert g.zoom == 1.0
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
w.save_current()
assert len(w.graph.edges) == 2 and w.graph.missing == {"Later.md"}  # [[Later]] is a faded node
w.open_note("Project X.md")
assert "Home" in row_text(w.backlinks_row)
w.open_note("Home.md")
w.show_error = lambda m: setattr(w, "_err", m)
w.create_note("a:b")
assert "valid" in w._err
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
assert "isn't a valid date" in w._err and "bad date" not in core.read_note("Project X.md")
# Home is pinned to the graph's center
w.graph.recompute()
assert w.graph.pos["Home.md"] == [w.graph.width() / 2, w.graph.height() / 2]
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
app.processEvents()
w.editor.setPlainText(w.editor.toPlainText() + "\nclosing edit\n")
w.close()
assert "closing edit" in core.read_note("Project X.md")  # quitting saves
print("app test OK")
