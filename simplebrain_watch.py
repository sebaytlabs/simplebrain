#!/usr/bin/env python3
"""The watcher: keeps you on the day's three things without you keeping track. No Qt here.

Once a minute the app hands it the active window's title (read on this computer, never sent or synced) and how
long the keyboard and mouse have been idle. From that it keeps a day log in the settings folder (never the vault):
drift time (for the nudge), time away, tasks ticked and which of the day's three things got done. It answers with at most one
event per tick, and the app turns that into one small card:

- 'nudge'        about 10 minutes of drift (email, video sites, social, shuffling files, a blocked page):
                 "Back to it" or "Taking a break" (quiet for 15 minutes). Quiet during a shift in your calendar.
- 'welcome'      back after 15+ minutes away: today's first thing comes up (no blank start).
- 'wrap_up'      10 minutes before your computer time runs out (`limit:: 3h` or `limit:: until 9pm` in Home):
                 write one line about where you stopped; tomorrow's Today opens with it.
- 'all_done'     the day's three things are done.
- 'stretch'      90 minutes at the screen without five minutes away: stand up, drink water.

What counts as drift can be tuned in Home: `focus:: youtube python` (never drift when the title has those words),
`drift:: chess.com` (always drift). A title that shares words with one of today's three things is focus anyway.

Run: python simplebrain_watch.py   (selftest)
"""
import ctypes
import ctypes.util
import json
import os
import re
import subprocess
import sys
from datetime import date, datetime, timedelta

import simplebrain_core as core

DRIFT_AFTER_S = 10 * 60  # one nudge after this much drift in a row; never more often
BREAK_S = 15 * 60  # "Taking a break" keeps it quiet this long
AWAY_S = 15 * 60  # idle this long is away; coming back opens today's first thing
WRAP_UP_S = 10 * 60  # warned this long before the day's computer time runs out
STRETCH_S = 90 * 60  # this long at the screen without five minutes away: time to stand up
REST_S = 5 * 60  # five minutes idle counts as that break
TICK_S = 60  # how often the app asks (one cheap title read: no short polling)
SHIFT_RE = re.compile(r"\b(shift|work)\b", re.I)

DRIFT = ("youtube", "instagram", "reddit", "facebook", "threads", "tiktok", "twitter", " / x", "netflix", "twitch",
         "hulu", "9gag", "imgur", "pinterest", "tumblr", "snapchat",
         "fastmail", "betterbird", "thunderbird", "gmail", "outlook", "proton mail", "inbox (",
         "thunar", "nautilus", "nemo", "caja", "dolphin", "file manager", "finder", "file explorer",
         "blocked", "access denied", "this site can")
NEUTRAL = ("simplebrain", "lock screen", "screensaver", "xfce4-panel", "desktop")
NUDGES_OFF = re.compile(r"^\s*nudges::\s*off\s*$", re.I | re.M)


def nudges_off(vault=None):
    """`nudges:: off` in Home (or Settings): no drift, welcome-back or stand-up cards. Time left and the day's
    three still work."""
    try:
        return bool(NUDGES_OFF.search(core.settings_text(vault or core.VAULT)))
    except OSError:
        return False


LIMIT_RE = re.compile(r"^\s*limit::\s*(?:(\d+(?:\.\d+)?)\s*h(?:ours?)?\s*(?:(\d+)\s*m(?:in)?)?|(\d+)\s*m(?:in(?:utes)?)?|"
                      r"until\s+(\d{1,2})(?::(\d{2}))?\s*([ap]m)?)\s*$", re.I | re.M)
WORDS_RE = {"focus": re.compile(r"^\s*focus::\s*(.+?)\s*$", re.I | re.M),
            "drift": re.compile(r"^\s*drift::\s*(.+?)\s*$", re.I | re.M)}


# ---------- reading the screen: the active window's title, and idle time ----------

def active_title(platform=None):
    """Title of the window you're in (plus its program name on Linux), or "" when it can't be read."""
    platform = platform or sys.platform
    try:
        if platform == "win32":
            u = ctypes.windll.user32
            h = u.GetForegroundWindow()
            n = u.GetWindowTextLengthW(h)
            buf = ctypes.create_unicode_buffer(n + 1)
            u.GetWindowTextW(h, buf, n + 1)
            return buf.value
        if platform == "darwin":
            r = subprocess.run(["osascript", "-e", 'tell application "System Events" to get name of first process '
                                "whose frontmost is true"], capture_output=True, text=True, timeout=3)
            return r.stdout.strip()
        if not os.environ.get("DISPLAY"):
            return ""
        root = subprocess.run(["xprop", "-root", "_NET_ACTIVE_WINDOW"], capture_output=True, text=True, timeout=2).stdout
        m = re.search(r"window id # (0x[0-9a-f]+)", root)
        if not m or m.group(1) == "0x0":
            return ""
        out = subprocess.run(["xprop", "-id", m.group(1), "_NET_WM_NAME", "WM_CLASS"], capture_output=True,
                             text=True, timeout=2).stdout
        names = re.findall(r'"([^"]*)"', out)
        return " — ".join(dict.fromkeys(names))
    except (OSError, subprocess.SubprocessError, AttributeError, ValueError):
        return ""


class _XSSInfo(ctypes.Structure):
    _fields_ = [("window", ctypes.c_ulong), ("state", ctypes.c_int), ("kind", ctypes.c_int),
                ("til_or_since", ctypes.c_ulong), ("idle", ctypes.c_ulong), ("eventMask", ctypes.c_ulong)]


_X = {}


def idle_seconds(platform=None):
    """Seconds since the last key press or mouse move anywhere on the computer (0 when it can't be told)."""
    platform = platform or sys.platform
    try:
        if platform == "win32":
            class LII(ctypes.Structure):
                _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]
            li = LII(ctypes.sizeof(LII), 0)
            ctypes.windll.user32.GetLastInputInfo(ctypes.byref(li))
            return max(0, (ctypes.windll.kernel32.GetTickCount() - li.dwTime) // 1000)
        if platform == "darwin":
            out = subprocess.run(["ioreg", "-c", "IOHIDSystem"], capture_output=True, text=True, timeout=3).stdout
            m = re.search(r'"HIDIdleTime" = (\d+)', out)
            return int(m.group(1)) // 1_000_000_000 if m else 0
        if not os.environ.get("DISPLAY"):
            return 0
        if "dpy" not in _X:  # libXss is on every Xfce/GNOME desktop; opened once
            xlib = ctypes.cdll.LoadLibrary(ctypes.util.find_library("X11") or "libX11.so.6")
            xss = ctypes.cdll.LoadLibrary(ctypes.util.find_library("Xss") or "libXss.so.1")
            xlib.XOpenDisplay.restype = ctypes.c_void_p
            xlib.XDefaultRootWindow.restype = ctypes.c_ulong
            xlib.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
            xss.XScreenSaverAllocInfo.restype = ctypes.POINTER(_XSSInfo)
            xss.XScreenSaverQueryInfo.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(_XSSInfo)]
            dpy = xlib.XOpenDisplay(None)
            _X.update(dpy=dpy, root=xlib.XDefaultRootWindow(dpy) if dpy else 0, xss=xss,
                      info=xss.XScreenSaverAllocInfo())
        if not _X["dpy"]:
            return 0
        _X["xss"].XScreenSaverQueryInfo(_X["dpy"], _X["root"], _X["info"])
        return _X["info"].contents.idle // 1000
    except (OSError, subprocess.SubprocessError, AttributeError, ValueError):
        _X.setdefault("dpy", None)
        return 0


# ---------- what a title is: focus, drift or neither ----------

def home_words(vault=None):
    """{'focus': [...], 'drift': [...]} from `focus::` / `drift::` lines in Home (comma or space separated)."""
    try:
        text = core.settings_text(vault or core.VAULT)
    except OSError:
        text = ""
    return {k: [w.strip().lower() for line in r.findall(text) for w in re.split(r"[,;]", line) if w.strip()]
            for k, r in WORDS_RE.items()}


DRIFT_NAMES = {"youtube": "YouTube", "instagram": "Instagram", "reddit": "Reddit", "facebook": "Facebook",
               "threads": "Threads", "tiktok": "TikTok", "twitter": "X", " / x": "X", "netflix": "Netflix",
               "twitch": "Twitch", "hulu": "Hulu", "fastmail": "email", "betterbird": "email", "thunderbird": "email",
               "gmail": "email", "outlook": "email", "proton mail": "email", "inbox (": "email", "thunar": "moving files",
               "nautilus": "moving files", "nemo": "moving files", "caja": "moving files", "dolphin": "moving files",
               "file manager": "moving files", "finder": "moving files", "file explorer": "moving files",
               "blocked": "a blocked page", "access denied": "a blocked page", "this site can": "a blocked page"}


def drift_label(title, words=None):
    """What the drift is, in a word (Instagram, email, moving files), never the browser's name."""
    t = (title or "").lower()
    for w in (words or {}).get("drift", []):
        if w in t:
            return w
    for k, name in DRIFT_NAMES.items():
        if k in t:
            return name
    return re.split(r" [—–-] ", title)[0][:40] if title else "something else"


def classify(title, today_words=(), words=None):
    """'focus', 'drift' or 'neutral' for one window title. Your own words win, then today's things, then the list."""
    t = (title or "").lower()
    words = words or {"focus": [], "drift": []}
    if not t.strip():
        return "neutral"
    if any(w in t for w in words["focus"]):
        return "focus"
    if any(w in t for w in words["drift"]):
        return "drift"
    tw = set(re.findall(r"[a-z][a-z'-]{3,}", t))
    if len(tw & set(today_words)) >= 2:
        return "focus"  # a video or page about one of today's things is the work itself
    if any(w in t for w in NEUTRAL):
        return "focus" if "simplebrain" in t else "neutral"
    return "drift" if any(w in t for w in DRIFT) else "focus"


# ---------- the day log ----------

def log_dir(base=None):
    return os.path.join(base or core.user_config_dir(), "watch")


def load_day(day, base=None):
    try:
        with open(os.path.join(log_dir(base), f"{day.isoformat()}.json"), encoding="utf-8") as f:
            d = json.load(f)
            if isinstance(d, dict):
                return d
    except (OSError, ValueError):
        pass
    return {"focus": 0, "drift": 0, "away": 0, "drift_by": {}, "three": [], "done": [], "events": []}


def save_day(day, data, base=None):
    os.makedirs(log_dir(base), exist_ok=True)
    core.write_atomic(os.path.join(log_dir(base), f"{day.isoformat()}.json"), json.dumps(data, indent=1))


def limit_seconds(vault=None, now=None, used_s=0):
    """Seconds of computer time left today from Home's `limit::` line, or None without one.
    `limit:: 3h` (or `2h 30m`, `90m`) counts the time you've been active; `limit:: until 9pm` is a clock time."""
    now = now or datetime.now()
    try:
        m = LIMIT_RE.search(core.settings_text(vault or core.VAULT))
    except OSError:
        return None
    if not m:
        return None
    if m.group(4):
        h = int(m.group(4)) % 12 + (12 if (m.group(6) or "").lower() == "pm" else 0) if m.group(6) else int(m.group(4))
        end = now.replace(hour=h % 24, minute=int(m.group(5) or 0), second=0, microsecond=0)
        return max(0, int((end - now).total_seconds()))
    total = float(m.group(1)) * 3600 + int(m.group(2) or 0) * 60 if m.group(1) else int(m.group(3)) * 60
    return max(0, int(total - used_s))


def in_shift(events, now):
    """True during a calendar event titled with 'shift' or 'work' (as long as the title says, '2pm-8pm', or 8 hours)."""
    for e in events:
        if e["date"] != now.date() or not e.get("time") or not SHIFT_RE.search(e["title"]):
            continue
        start = datetime.combine(e["date"], datetime.strptime(e["time"], "%H:%M").time())
        end = start + timedelta(hours=8)
        m = re.search(r"-\s*(\d{1,2})(?::(\d{2}))?\s*([ap]m)", e["title"], re.I)
        if m:
            h = int(m.group(1)) % 12 + (12 if m.group(3).lower() == "pm" else 0)
            end = start.replace(hour=h, minute=int(m.group(2) or 0))
        if start <= now < end:
            return True
    return False


def tick(state, title, idle_s, now, today_words=(), words=None, quiet=False, left_s=None):
    """One minute of watching. `state` is the running memory (the app keeps it); returns (state, event or None).
    Pure: no files, no clock, so the rules can be tested line by line."""
    last = state.get("last")
    step = min(TICK_S * 3, max(0, (now - last).total_seconds())) if last else 0  # a suspend isn't screen time
    state["last"] = now
    day = state.setdefault("day", {"focus": 0, "drift": 0, "away": 0, "drift_by": {}})
    event = None
    if idle_s >= REST_S:
        state["run"] = 0  # a real break resets the stretch
    if idle_s >= AWAY_S:
        day["away"] = day.get("away", 0) + step
        state["away"], state["streak"] = True, 0
        return state, None
    state["run"] = state.get("run", 0) + (step if idle_s < REST_S else 0)
    if state.pop("away", False):
        event = "welcome"
    kind = classify(title, today_words, words)
    if kind == "drift":
        day["drift"] = day.get("drift", 0) + step
        label = drift_label(title, words)
        day["drift_by"][label] = day["drift_by"].get(label, 0) + step
        state["streak"] = state.get("streak", 0) + step
    elif kind == "focus":
        day["focus"] = day.get("focus", 0) + step
        state["streak"] = 0
    snoozed = state.get("snooze_until") and now < state["snooze_until"]
    if state.get("streak", 0) >= DRIFT_AFTER_S and not quiet and not snoozed and event is None:
        event, state["streak"] = "nudge", 0
    if left_s is not None and left_s <= WRAP_UP_S and not state.get("warned") and event is None:
        event, state["warned"] = "wrap_up", True
    near_end = left_s is not None and left_s <= 2 * WRAP_UP_S  # time's nearly up: the wrap-up matters, not a stretch
    if state["run"] >= STRETCH_S and event is None and not quiet and not near_end:
        event, state["run"] = "stretch", 0  # burnout starts with skipped breaks
    return state, event


def snooze(state, now, seconds=BREAK_S):
    state["snooze_until"] = now + timedelta(seconds=seconds)
    state["streak"] = 0
    return state


def done_of_three(three, open_texts, ticked=()):
    """Which of the day's three things are done: those ticked today (a repeating task stays open, so that's how it
    counts), or no longer among the open tasks and plan actions."""
    open_ = {norm(t) for t in open_texts}
    done = {norm(t) for t in ticked}
    return [t for t in three if norm(t) not in open_ or norm(t) in done]


def norm(text):
    return " ".join(core.DUE_RE.sub("", text).lower().split())


def mins(s):
    s = int(s) // 60
    return f"{s // 60}h {s % 60:02d}m" if s >= 60 else f"{s}m"


def score_line(day, three=None, done=None):
    """'2 of 3 done · 5 tasks ticked': the day's score is what got done, never time spent in front of a window
    (that counted talking to someone in a browser as focus, and anyone can sit in front of a window)."""
    parts = []
    if three:
        parts.append(f"{len(done or [])} of {len(three)} done")
    ticked = day.get("ticked", 0)
    if ticked:
        parts.append(f"{ticked} task{'s' if ticked != 1 else ''} ticked")
    return " · ".join(parts) or "nothing ticked"


def tick_done(day, text=None):
    """A task ticked done today: the only thing the score counts."""
    day["ticked"] = day.get("ticked", 0) + 1
    if text:
        day.setdefault("ticked_texts", []).append(text)
    return day


# ---------- the line you leave for tomorrow ----------

def park_path(base=None):
    return os.path.join(log_dir(base), "parked.json")


def park(text, now=None, base=None):
    os.makedirs(log_dir(base), exist_ok=True)
    core.write_atomic(park_path(base), json.dumps({"text": text.strip(), "when": (now or datetime.now()).isoformat()}))


def parked(now=None, base=None, max_days=4):
    """The line you left when time ran out: shown on the next day you open SimpleBrain (all that day), then gone.
    A line from Tuesday doesn't greet you again on Thursday."""
    now = now or datetime.now()
    try:
        with open(park_path(base), encoding="utf-8") as f:
            d = json.load(f)
        when = datetime.fromisoformat(d["when"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if not d.get("text") or not timedelta(0) <= now - when <= timedelta(days=max_days):
        return None
    if when.date() == now.date():
        return d["text"]  # written today (a short day): it's still the line for next time
    shown = d.get("shown")
    if shown and shown != now.date().isoformat():
        return None  # it had its day
    if not shown:
        d["shown"] = now.date().isoformat()
        try:
            core.write_atomic(park_path(base), json.dumps(d))
        except OSError:
            pass
    return d["text"]


def selftest():
    import shutil
    import tempfile
    base = tempfile.mkdtemp()
    v = os.path.join(base, "vault")
    try:
        core.ensure_vault(v)
        w = {"focus": [], "drift": []}
        assert classify("Shorts - YouTube — librewolf", (), w) == "drift"
        assert classify("Python Essentials 1: lists - YouTube — librewolf", {"python", "essentials"}, w) == "focus"
        assert classify("Inbox (12) – Fastmail", (), w) == "drift" and classify("Projects — Thunar", (), w) == "drift"
        assert classify("myRC — Riverside College — librewolf", (), w) == "focus"
        assert classify("SimpleBrain", (), w) == "focus" and classify("", (), w) == "neutral"
        assert drift_label("Inbox (14) – Fastmail — LibreWolf") == "email" and drift_label("Reels • Instagram — LibreWolf") == "Instagram"
        assert drift_label("Projects — Thunar") == "moving files"  # the site or habit, never the browser's name
        core.write_note("Home.md", "# Home\nfocus:: youtube python, edube\ndrift:: chess.com\nlimit:: 3h\n", v)
        hw = home_words(v)
        assert hw == {"focus": ["youtube python", "edube"], "drift": ["chess.com"]}
        assert classify("Youtube Python crash course", (), hw) == "focus" and classify("chess.com - Play", (), hw) == "drift"
        # ten minutes of drift: one nudge, then quiet; a break keeps it quiet; away then back: today's first thing
        st, t0 = {}, datetime(2026, 11, 2, 10, 0)
        events = []
        for i in range(25):
            st, e = tick(st, "Reels • Instagram — librewolf", 0, t0 + timedelta(minutes=i))
            events.append(e)
        assert events.count("nudge") == 2 and events.index("nudge") == 10  # every ten minutes at most
        st = snooze(st, t0 + timedelta(minutes=25))
        quiet = [tick(st, "Reels • Instagram", 0, t0 + timedelta(minutes=26 + i))[1] for i in range(14)]
        assert "nudge" not in quiet
        assert st["day"]["drift"] >= 30 * 60 and st["day"]["drift_by"]
        st, e = tick(st, "x", AWAY_S + 5, t0 + timedelta(minutes=60))
        st, e = tick(st, "SimpleBrain", 0, t0 + timedelta(minutes=61))
        assert e == "welcome"
        f0 = st["day"]["focus"]
        st, e = tick(st, "SimpleBrain", 0, t0 + timedelta(hours=5))
        assert st["day"]["focus"] - f0 == TICK_S * 3  # a laptop asleep for hours isn't counted as work
        quiet_st, qe = {}, []
        for i in range(15):
            quiet_st, e = tick(quiet_st, "YouTube", 0, t0 + timedelta(minutes=i), quiet=True)
            qe.append(e)
        assert "nudge" not in qe  # quiet during a shift
        # computer time: 3h a day counts active time; 'until 9pm' is a clock time; one warning, then the line for tomorrow
        assert limit_seconds(v, used_s=3600) == 2 * 3600
        core.write_note("Home.md", "# Home\nNudges:: OFF\n", v)
        assert nudges_off(v)
        core.write_note("Home.md", "# Home\nnudges:: on\nabout nudges:: off in a sentence\n", v)
        assert not nudges_off(v)
        core.write_note("Home.md", "# Home\nlimit:: until 9pm\n", v)
        assert limit_seconds(v, now=datetime(2026, 11, 2, 20, 45)) == 15 * 60
        core.write_note("Home.md", "# Home\nlimit:: 90m\n", v)
        assert limit_seconds(v, used_s=80 * 60) == 600
        core.write_note("Home.md", "# Home\n", v)
        assert limit_seconds(v) is None
        st2, ev = {}, []
        for i in range(3):
            st2, e = tick(st2, "SimpleBrain", 0, t0 + timedelta(minutes=i), left_s=500 - i * 60)
            ev.append(e)
        assert ev.count("wrap_up") == 1
        st3, ev3 = {}, []
        for i in range(100):  # 90 minutes straight: one 'stretch'; five idle minutes reset the count
            st3, e = tick(st3, "SimpleBrain", 0, t0 + timedelta(minutes=i))
            ev3.append(e)
        assert ev3.count("stretch") == 1 and ev3.index("stretch") == 90
        st4, ev4 = {"run": STRETCH_S}, []
        st4, e4 = tick(st4, "SimpleBrain", 0, t0, left_s=WRAP_UP_S + 60)
        assert e4 is None  # 11 minutes left: no stretch card in the way of the wrap-up
        st3, _ = tick(st3, "SimpleBrain", REST_S, t0 + timedelta(minutes=101))
        assert st3["run"] == 0
        park("Python: stopped at lists, page 40", now=t0, base=base)
        assert parked(t0 + timedelta(days=1), base=base) == "Python: stopped at lists, page 40"
        assert parked(t0 + timedelta(days=9), base=base) is None
        assert parked(t0 + timedelta(days=1, hours=3), base=base)  # all of the next day ...
        assert parked(t0 + timedelta(days=3), base=base) is None  # ... and not again two days later
        # shifts in the calendar keep it quiet
        ev_list = [{"date": date(2026, 11, 2), "time": "14:00", "title": "Cafe shift 2pm-8pm"}]
        assert in_shift(ev_list, datetime(2026, 11, 2, 19, 30)) and not in_shift(ev_list, datetime(2026, 11, 2, 20, 30))
        assert in_shift([{"date": date(2026, 11, 2), "time": "09:00", "title": "work"}], datetime(2026, 11, 2, 16))
        # the checklist: which of the three are done, and the score
        three = ["Call Riverside due:2026-11-02", "Study Group lesson 3", "Close old pet store"]
        done = done_of_three(three, ["Study Group lesson 3 due:2026-11-04", "something else"])
        assert done == ["Call Riverside due:2026-11-02", "Close old pet store"]
        assert done_of_three(three, ["Study Group lesson 3 due:2026-11-05"], ticked=["Study Group lesson 3 due:2026-11-04"]) == three
        day = {"focus": 7800, "drift": 1500, "drift_by": {"Instagram": 1200, "Fastmail": 300}}
        assert score_line(day, three, done) == "2 of 3 done"  # time in front of a window never counts
        assert score_line(tick_done(tick_done(dict(day))), three, done) == "2 of 3 done · 2 tasks ticked"
        assert score_line({}) == "nothing ticked"
        save_day(date(2026, 11, 2), {**day, "three": three}, base)
        assert load_day(date(2026, 11, 2), base)["three"] == three and load_day(date(2026, 11, 3), base)["focus"] == 0
        for plat in (None, "win32", "darwin", "linux"):  # every system's branch, on any system: answers, never raises
            assert isinstance(active_title(plat), str) and isinstance(idle_seconds(plat), int), plat
    finally:
        shutil.rmtree(base, ignore_errors=True)
    print("watch selftest OK")


if __name__ == "__main__":
    selftest()
