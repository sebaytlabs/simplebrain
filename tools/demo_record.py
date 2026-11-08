"""Records SimpleBrain for the store: a clean copy (throwaway vault, settings and home, so nothing of yours shows) goes
through the whole required tutorial on screen, typing and clicking like a person, while ffmpeg films the window.
Screenshots of every step and a few views after it land beside the video.
Run: .venv/bin/python tools/demo_record.py OUT_DIR   (needs an X display and ffmpeg; moves the mouse while it runs)"""
import os
import shutil
import subprocess
import sys
import tempfile

OUT = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else "demo-out")
ROOT = tempfile.mkdtemp(prefix="simplebrain-demo-")
os.environ.update(SIMPLEBRAIN_VAULT=os.path.join(ROOT, "vault"), HOME=os.path.join(ROOT, "home"),
                  XDG_CONFIG_HOME=os.path.join(ROOT, "home", ".config"), SIMPLEBRAIN_NO_UPDATE="1",
                  SIMPLEBRAIN_NO_WATCH="1", SIMPLEBRAIN_NO_MENU="1")
os.makedirs(os.environ["HOME"])
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import simplebrain_core as core  # noqa: E402

core.ensure_vault()
core.save_settings({"desktop_offer": "asked", "recommendations": "off", "missions_trial_cleaned": "yes"})
SAMPLES = {  # a lived-in vault: two books, a project, tasks, so the graph and lists aren't empty
    "Atomic Habits.md": core.set_library(core.learning_note_template("Atomic Habits"), False).replace(
        "## One Sentence Summary::\n", "## One Sentence Summary::\nSmall habits, repeated, compound.\n").replace(
        "(put each one in double square brackets to link it)\n", "(put each one in double square brackets to link it)\n"
        "[[Habits]] [[Learning]]\n"),
    "Mind Mapping.md": core.set_library(core.learning_note_template("Mind Mapping"), True).replace(
        "(put each one in double square brackets to link it)\n", "(put each one in double square brackets to link it)\n"
        "[[Learning]] [[Garden Plan]]\n"),
    "Habits.md": "# Habits\n\n[[Home]]\n\nWhat I want to do every day.\n\nt walk 20 minutes due:" +
                 core.date.today().isoformat() + "\n",
    "Learning.md": "# Learning\n\n[[Home]]\n\nBooks I'm studying.\n",
    "Garden Plan.md": "# Garden Plan\n\n[[Home]]\n\nt buy tomato seedlings due:" +
                      (core.date.today() + core.timedelta(days=2)).isoformat() + "\nt build the raised bed\n",
}
for name, text in SAMPLES.items():
    core.write_note(name, text)

import simplebrain_app as A  # noqa: E402
from PySide6.QtCore import QPoint, Qt, QTimer  # noqa: E402
from PySide6.QtGui import QCursor  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialogButtonBox, QLineEdit, QPushButton  # noqa: E402

os.makedirs(os.path.join(OUT, "screenshots"), exist_ok=True)
app = QApplication(sys.argv)
app.setApplicationName(A.APP_NAME)
w = A.SimpleBrain()
w.setGeometry(160, 70, 1600, 940)
w.show()
rec = None
shots = []


def shot(name):
    """The window as it is on screen, any dialog over it included."""
    g = w.geometry()
    path = os.path.join(OUT, "screenshots", f"{len(shots) + 1:02d}-{name}.png")
    app.primaryScreen().grabWindow(0, g.x(), g.y(), g.width(), g.height()).save(path)
    shots.append(path)


def glide(widget, pos=None):
    """Move the real pointer to a spot on a widget, so the video shows where the click goes."""
    pos = pos or widget.rect().center()
    end = widget.mapToGlobal(pos)
    start = QCursor.pos()
    for k in range(1, 13):
        QCursor.setPos(QPoint(int(start.x() + (end.x() - start.x()) * k / 12),
                              int(start.y() + (end.y() - start.y()) * k / 12)))
        yield 25
    yield 150


def click(widget, pos=None):
    yield from glide(widget, pos)
    QTimer.singleShot(0, lambda: QTest.mouseClick(widget, Qt.LeftButton, Qt.NoModifier, pos or widget.rect().center()))
    yield 500  # deferred: a click that opens a box runs it from the event loop, not inside this script


def typing(widget, text, gap=75):
    widget.setFocus()
    for ch in text:
        if ch == "\n":
            QTest.keyClick(widget, Qt.Key_Return)
        else:
            QTest.keyClicks(widget, ch)
        yield gap


def answer_box(text):
    """Type into the box SimpleBrain just asked with, then OK."""
    for _ in range(50):
        box = QApplication.activeModalWidget()
        if box:
            break
        yield 100
    field = box.findChild(QLineEdit)
    yield from typing(field, text)
    yield 600
    shot("asking")
    ok = box.findChild(QDialogButtonBox).button(QDialogButtonBox.Ok)
    yield from click(ok)
    yield 700


def button(parent, label):
    return next(b for b in parent.findChildren(QPushButton) if b.text() == label and b.isVisible())


def next_step(t, name, read=2600):
    yield read
    shot(name)
    yield from click(t.next_button)
    yield 500


def script():
    global rec
    yield 800
    g = w.geometry()
    rec = subprocess.Popen(
        ["ffmpeg", "-loglevel", "error", "-y", "-f", "x11grab", "-framerate", "30", "-draw_mouse", "1",
         "-video_size", f"{g.width() // 2 * 2}x{g.height() // 2 * 2}", "-i", f"{os.environ.get('DISPLAY', ':0')}+{g.x()},{g.y()}",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
         os.path.join(OUT, "simplebrain-tutorial.mp4")], stdin=subprocess.PIPE)
    yield 1000
    w.maybe_start_tour()
    t = w.tour
    yield 600
    yield from next_step(t, "welcome", 4000)
    # 1. the bar -> Inbox
    shot("bar")
    yield from click(w.capture)
    yield from typing(w.capture, "i ask the library about my hold\n")
    yield from next_step(t, "bar-done", 1800)
    # 2. Inbox: file it as a task
    shot("inbox")
    yield 1500
    yield from click(button(w.inbox_list, "Task"))
    yield from answer_box("fri")
    yield from next_step(t, "inbox-done", 1800)
    # 3. a task in one line
    yield 1500
    yield from click(w.capture)
    yield from typing(w.capture, "t return library books sat\n")
    yield from next_step(t, "task-done", 1800)
    # 4. tick the practice task
    yield 1500
    lst = w.tasks_list
    item = next(lst.item(i) for i in range(lst.count()) if w.PRACTICE_TASK in lst.item(i).text())
    r = lst.visualItemRect(item)
    yield from glide(lst.viewport(), QPoint(r.left() + 12, r.center().y()))
    shot("tasks")
    item.setCheckState(Qt.Checked)
    yield 600
    yield from next_step(t, "tick-done", 1800)
    # 5. an event in one line
    yield 1500
    yield from click(w.capture)
    yield from typing(w.capture, "c tomorrow 2pm coffee with a friend\n")
    yield from next_step(t, "event-done", 1800)
    # 6. notes: click Home
    yield 1500
    lst = w.notes_list
    home = next(lst.item(i) for i in range(lst.count()) if lst.item(i).data(Qt.UserRole) == "Home.md")
    shot("notes")
    yield from click(lst.viewport(), lst.visualItemRect(home).center())
    yield from next_step(t, "notes-done", 1800)
    # 7. a book note
    yield 1500
    yield from click(w.learning_button)
    yield from answer_box("The Art of Learning")
    yield from next_step(t, "book-done", 1800)
    # 8. personal library
    yield 1200
    shot("library")
    yield from click(w.library_box, QPoint(9, w.library_box.height() // 2))
    yield from next_step(t, "library-done", 2200)
    # 9. a link while writing
    yield 1500
    ed = w.editor
    c = ed.textCursor()
    c.movePosition(c.MoveOperation.End)
    ed.setTextCursor(c)
    yield from click(ed, ed.cursorRect().center())
    yield from typing(ed, "\nRelated: [[Ho", 110)
    yield 900
    shot("link-popup")
    QTest.keyClick(ed, Qt.Key_Return)
    yield 700
    yield from next_step(t, "link-done", 1800)
    # 10. under the note: the [[Home]] link
    yield 1500
    yield from click(button(w.links_scroll, "[[Home]]"))
    yield from next_step(t, "under-done", 1800)
    # 11. the graph: a dot that isn't the middle one
    yield 1800
    g = w.graph
    target = next((n for n in ("Mind Mapping.md", "Learning.md", "Garden Plan.md") if n in g.pos and n != g.center),
                  next(n for n in g.pos if n != g.center))
    s = g.to_screen(*g.pos[target])
    yield from click(g, QPoint(int(s.x()), int(s.y())))
    yield from next_step(t, "graph-done", 2000)
    while t.i < len(t.steps) - 1:  # what's left reads, then Next
        yield from next_step(t, t.title.text().split(". ", 1)[-1].lower().replace(" ", "-"), 4000)
    yield 3000
    shot("ready")
    yield from click(t.next_button)
    yield 1500
    # after the tutorial: the window as you'd use it
    w.open_note("Mind Mapping.md")
    yield 1800
    shot("book-note-personal-library")
    w.open_note("Home.md")
    yield 1800
    shot("main-window")
    yield 1500
    rec.stdin.write(b"q")
    rec.stdin.flush()
    rec.wait(30)
    print("\n".join(shots))
    print(os.path.join(OUT, "simplebrain-tutorial.mp4"))
    shutil.rmtree(ROOT, ignore_errors=True)
    app.quit()


def run(gen):
    def step():
        try:
            ms = next(gen)
        except StopIteration:
            return
        except Exception:
            if rec:
                rec.stdin.write(b"q")
                rec.stdin.flush()
            app.quit()
            raise
        QTimer.singleShot(ms or 0, step)
    QTimer.singleShot(0, step)


run(script())
app.exec()
