#!/usr/bin/env python3
"""What you open through SimpleBrain, and when: notes, files, videos, apps, web links. Kept on this
computer only (the settings folder, never the notes folder, never synced) and only what you opened
here: nothing watches the screen. From it SimpleBrain learns your day: what you usually open around
this hour on this kind of day (weekday or weekend) comes up first in search and in the Today note.

Run: python simplebrain_habits.py   (selftest)
"""
import json
import math
import os
import time
from datetime import datetime

import simplebrain_core as core

KEEP = 5000  # the last few months of opens; older ones fade out anyway
HALF_LIFE_DAYS = 14  # a habit from two weeks ago counts half as much as one from today


def log_path():
    return os.path.join(core.user_config_dir(), "habits.jsonl")


def record(kind, label, target, when=None, path=None):
    """One open. kind: note, file, app, url. A failure to write is never the user's problem."""
    path = path or log_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"t": int(when or time.time()), "k": kind, "l": label, "x": target}) + "\n")
        if os.path.getsize(path) > KEEP * 400:  # trim now and then, not on every open
            with open(path, encoding="utf-8") as f:
                lines = f.readlines()[-KEEP:]
            core.write_atomic(path, "".join(lines))
    except OSError:
        pass


def entries(path=None):
    path = path or log_path()
    out = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    e = json.loads(line)
                    if {"t", "k", "l", "x"} <= e.keys():
                        out.append(e)
                except ValueError:
                    continue  # a half-written line from a crash
    except OSError:
        pass
    return out


def weights(now=None, path=None, window_h=1.5):
    """{target: (weight, kind, label)} for what you open around this time of day on this kind of day,
    recent days counting more. Things opened at other hours still count a little (they're yours)."""
    now = now or datetime.now()
    weekend = now.weekday() >= 5
    out = {}
    for e in entries(path):
        when = datetime.fromtimestamp(e["t"])
        age_days = max(0.0, (now - when).total_seconds() / 86400)
        w = 0.5 ** (age_days / HALF_LIFE_DAYS)
        gap = abs((when.hour + when.minute / 60) - (now.hour + now.minute / 60))
        gap = min(gap, 24 - gap)
        near = gap <= window_h and (when.weekday() >= 5) == weekend
        w *= 1.0 if near else 0.15
        prev = out.get(e["x"], (0.0, e["k"], e["l"]))
        out[e["x"]] = (prev[0] + w, e["k"], e["l"])
    return out


def usual(now=None, path=None, n=3, minimum=1.5, exists=os.path.exists):
    """The few things you usually open around now: [(kind, label, target)], strongest first. Needs a
    habit (a few opens around this time), not a one-off; files no longer there are left out."""
    w = weights(now, path)
    ranked = sorted(w.items(), key=lambda kv: -kv[1][0])
    out = []
    for target, (score, kind, label) in ranked:
        if score < minimum:
            break
        if kind in ("file", "note") and not exists(target):
            continue
        out.append((kind, label, target))
        if len(out) == n:
            break
    return out


def boost(now=None, path=None):
    """{target: how far up search moves it}: small, so a habit helps but never hides the best match."""
    return {t: min(0.9, 0.3 * math.log1p(s)) for t, (s, _, _) in weights(now, path).items()}


def selftest():
    import tempfile
    d = tempfile.mkdtemp()
    log = os.path.join(d, "habits.jsonl")
    try:
        mon9 = datetime(2026, 11, 5, 9, 0)  # a Thursday; the three days before are weekdays too
        day = 86400
        base = mon9.timestamp()
        for k in range(4):  # four weekdays running: the Python course around 9am
            record("file", "module-01.mp4", "/c/module-01.mp4", base - k * day, log)
        record("note", "Python", "Python.md", base - day, log)
        record("note", "Python", "Python.md", base - 2 * day + 600, log)
        record("url", "YouTube", "https://youtube.com", base - 10 * 3600, log)  # late at night, once
        with open(log, "a") as f:
            f.write('{"t": 1, "k"\n')  # a crash mid-line is skipped, not fatal
        u = usual(mon9, log, exists=lambda p: True)
        assert [x[1] for x in u] == ["module-01.mp4", "Python"]  # the habit, strongest first; the one-off isn't
        assert usual(datetime(2026, 11, 7, 9, 0), log, exists=lambda p: True) == []  # Saturday is another day
        assert usual(mon9, log, exists=lambda p: False) == []  # moved or deleted files drop out
        b = boost(mon9, log)
        assert b["/c/module-01.mp4"] > b["https://youtube.com"] > 0 and max(b.values()) <= 0.9
        assert usual(mon9, os.path.join(d, "none.jsonl")) == []
    finally:
        import shutil
        shutil.rmtree(d, ignore_errors=True)
    print("habits selftest OK")


if __name__ == "__main__":
    selftest()
