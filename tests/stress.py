"""Stress test: a big vault, rapid clicks, odd files and bad input, timed. Finds where SimpleBrain breaks or drags.
Run: QT_QPA_PLATFORM=offscreen python tests/stress.py [notes]     (default 3000 notes, two tasks each)"""
import os
import random
import sys
import tempfile
import time

HOME = tempfile.mkdtemp()
os.environ.update(HOME=HOME, USERPROFILE=HOME, SIMPLEBRAIN_VAULT=os.path.join(HOME, "vault"), SIMPLEBRAIN_NO_UPDATE="1",
                  SIMPLEBRAIN_NO_WATCH="1", SIMPLEBRAIN_NO_MENU="1")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import simplebrain_core as core  # noqa: E402

SD = tempfile.mkdtemp()
core.settings_path = lambda search=None: os.path.join(SD, "settings.json")
core.user_config_dir = lambda: SD
LIMITS = {}  # what each action may take, seconds, on this (fast) machine; an old one is ~3x slower
SLOW = []


SETTLE = []  # set to a function that waits for background work (the window's Today and rows-under-the-note jobs)


def timed(label, fn, limit, settle=True):
    """One action, timed after the previous one's background work has finished (a person doesn't click in the same
    millisecond); the rapid-clicking burst is timed without settling, on purpose."""
    if settle and SETTLE:
        SETTLE[0]()
    t = time.time()
    out = fn()
    dt = time.time() - t
    LIMITS[label] = (dt, limit)
    print(f"  {'SLOW ' if dt > limit else 'ok   '}{dt:7.3f}s  (limit {limit:.2f})  {label}")
    if dt > limit:
        SLOW.append(label)
    return out


def build_vault(n):
    v = core.VAULT
    core.ensure_vault(v)
    rnd = random.Random(1)
    words = ("supply lease bond permit python exam lists modules riverside payment car loan reading session "
             "guitar course budget shift bookstore chase account letter credit spanish test video clip").split()
    for i in range(n):
        body = " ".join(rnd.choice(words) for _ in range(120))
        links = " ".join(f"[[Note {rnd.randrange(n)}]]" for _ in range(3))
        core.write_note(f"Note {i}.md", f"# Note {i}\n{links} #t{i % 9}\n{body}\nNote {rnd.randrange(n)} mentioned here.\n"
                        f"t task {i}a due:{(core.date.today() + core.timedelta(days=i % 20 - 5)).isoformat()}\n"
                        f"t task {i}b\n", v)
    return v


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 3000
    print(f"building a vault of {n} notes …")
    build_vault(n)
    import simplebrain_app as A
    import simplebrain_budget as budget
    import simplebrain_drop as drop
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
    app = QApplication([])
    core.save_settings({"tour_done": "yes", "recommendations": "off"})
    w = timed("start-up", lambda: A.SimpleBrain(), 6.0)
    w.resize(1500, 950)
    w.show()
    app.processEvents()

    def settle():
        end = time.time() + 5
        while time.time() < end:
            app.processEvents()
            timers = [getattr(w, n, None) for n in ("_mentions_timer", "_today_debounce")]
            if not (getattr(w, "_mentions_running", False) or getattr(w, "_today_busy", False)
                    or any(t is not None and t.isActive() for t in timers)):
                return
            time.sleep(0.02)
    SETTLE.append(settle)
    timed("open a note", lambda: (w.open_note("Note 7.md"), app.processEvents()), 0.6)
    timed("redraw the rows under the note (every pause in typing)", w.render_links, 0.4)
    timed("typing pause: links follow", lambda: (w.editor.insertPlainText(" more [[Note 9]]"), w.render_links()), 0.4)
    timed("save", w.save_current, 1.0)
    timed("rebuild Tasks", w.refresh_tasks, 1.0)
    t = next(t for t in A.core.parse_tasks() if not t["done"])
    timed("tick one task", lambda: (w.on_task_toggle(t), app.processEvents()), 1.5)
    timed("Today", w.open_today, 2.0)

    def burst():
        for i in range(30):
            w.open_note(f"Note {i}.md")
            app.processEvents()
    timed("30 notes opened in a row (rapid clicking)", burst, 12.0, settle=False)

    def ticks():
        for row in range(w.tasks_list.count())[:200]:
            it = w.tasks_list.item(row)
            if isinstance(it.data(Qt.UserRole), dict):
                w.tasks_list.setCurrentItem(it)
        app.processEvents()
    timed("moving through 200 task rows", ticks, 2.0)
    w.capture.setText("guitar")
    timed("search as you type", w.run_search, 1.0)
    timed("Spread out", w.on_spread_out, 6.0)
    timed("Money window", lambda: w.open_money().close(), 2.0)
    # odd files and bad input: none of these may raise
    v = core.VAULT
    with open(os.path.join(v, "Binary.md"), "wb") as f:
        f.write(os.urandom(4096))
    with open(os.path.join(v, "Huge.md"), "w") as f:
        f.write("# Huge\n" + ("a line of text with [[Note 1]] in it\n" * 120_000))
    with open(os.path.join(v, "Windows.md"), "wb") as f:
        f.write("﻿# Windows\r\nt crlf task due:fri\r\nc tomorrow 2pm crlf event\r\n".encode("utf-8"))
    core.write_note("Budget.md", "# Budget\ncash:: lots\n+ abc\n- 1e9 Huge monthly 99\n+ 12 x every 0 weeks\n"
                    "goal:: 5 thing 02-30-2026\nuntil:: 13-45-2026\n+ 10 pay every funday\n")
    core.write_note("Settings.md", "# Settings\nlimit:: forever\nlimit:: 99999h\npara:: /nonexistent/x\nfocus::\n"
                    "app:: Broken notaurl\nwatch:: /nope\nplan:: /nope.xlsx\nmail::\n")
    timed("odd notes: list, tasks, graph, Today", lambda: (w.refresh_notes_list(), w.refresh_tasks(), w.graph.recompute(),
                                                           w.open_today()), 8.0)
    timed("open a 5 MB note", lambda: w.open_note("Huge.md"), 3.0)
    timed("rows under a 5 MB note", w.render_links, 3.0)
    timed("open a binary file named .md", lambda: w.open_note("Binary.md"), 2.0)
    timed("money from a garbage Budget note", lambda: budget.project(budget.load()), 1.0)
    w.show_error = lambda msg: print("  (an error box would say:", msg[:70], ")")  # a box nobody clicks would hang the run
    w.on_watch("SimpleBrain", 0)
    for bad in ("", "   ", "t ", "c ", "c nonsense", "c 02-30-2026 x", "t x due:", "t x due:13-45-2026", "i "):
        w.capture.setText(bad)
        w.on_capture()
    assert drop.file_all(["/does/not/exist"], w.para or HOME) == []
    inside = os.path.join(w.para, "Projects", "loop")
    os.makedirs(inside, exist_ok=True)
    assert drop.file_one(os.path.join(w.para, "Projects"), w.para) is None  # dropping Projects itself never moves it
    assert os.path.isdir(os.path.join(w.para, "Projects"))
    w.close()
    print()
    print(f"{len(LIMITS) - len(SLOW)} of {len(LIMITS)} within their limits" + (f"; slow: {', '.join(SLOW)}" if SLOW else ""))
    print("stress OK" if not SLOW else "stress: too slow")
    return 1 if SLOW else 0


if __name__ == "__main__":
    sys.exit(main())
