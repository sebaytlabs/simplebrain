"""SimpleBrain core: the vault, notes, links, tasks, inbox and calendar.
No UI imports: the Qt app is only the UI on top of it.

Self-test: python3 simplebrain_core.py
"""
import base64
import difflib
import hashlib
import html
import itertools
import json
import os
import re
import sys
import math
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from xml.etree import ElementTree
from datetime import date, datetime, timedelta

from simplebrain_ics import parse_ics

VERSION = "0.6.0"

INBOX_FILE = "Inbox.md"
CALENDAR_FILE = "Calendar.md"
DEFAULT_VAULT = os.path.expanduser("~/Documents/SimpleBrain")
SETTINGS_NAME = "simplebrain-settings.json"


# ---------- settings: where the vault lives (portable: travels with the app) ----------

def app_dir():
    """Folder the app was started from: beside the .AppImage, the .exe or the .app, so a
    copy on a USB drive finds its own settings. From source, the folder of this file."""
    if os.environ.get("APPIMAGE"):
        return os.path.dirname(os.path.abspath(os.environ["APPIMAGE"]))
    if getattr(sys, "frozen", False):
        d = os.path.dirname(os.path.abspath(sys.executable))
        parts = d.split(os.sep)
        for i, part in enumerate(parts):  # macOS: SimpleBrain.app/Contents/MacOS/SimpleBrain
            if part.endswith(".app"):
                return os.sep.join(parts[:i]) or os.sep
        return d
    return os.path.dirname(os.path.abspath(__file__))


def user_config_dir():
    """Per-user settings home, used when there is no settings file beside the app."""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "SimpleBrain")


def settings_path(search=None):
    """The settings file in use: beside the app (or one folder up, so one file can serve
    Windows/, Mac/ and Linux/ build folders on a drive), else the per-user one. Beside-the-app
    wins, and its presence is what switches the app into portable mode."""
    here = search if search is not None else app_dir()
    for d in (here, os.path.dirname(here)):
        p = os.path.join(d, SETTINGS_NAME)
        if os.path.isfile(p):
            return p
    return os.path.join(user_config_dir(), "settings.json")


def load_settings(path=None):
    path = path or settings_path()
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_settings(data, path=None):
    path = path or settings_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)  # a crash mid-save can't leave half a settings file


def resolve_vault(env=None, settings_file=None):
    """SIMPLEBRAIN_VAULT, else the saved folder (relative paths count from the settings
    file, so a drive can change letter), else Documents/SimpleBrain."""
    env = os.environ if env is None else env
    if env.get("SIMPLEBRAIN_VAULT"):
        return env["SIMPLEBRAIN_VAULT"]
    sf = settings_file or settings_path()
    saved = load_settings(sf).get("vault")
    if saved:
        return os.path.normpath(os.path.join(os.path.dirname(sf), os.path.expanduser(saved)))
    return DEFAULT_VAULT


def vault_setting_text(vault, settings_file=None):
    """How a vault folder is written into settings: relative to the settings file when it is
    on the same drive (so the pair can move together), else absolute."""
    sf = settings_file or settings_path()
    if os.path.dirname(sf) == user_config_dir():  # per-user settings: not tied to a drive layout
        return os.path.abspath(vault)
    try:
        return os.path.relpath(vault, os.path.dirname(sf))
    except ValueError:  # Windows: different drive letters
        return os.path.abspath(vault)


VAULT = resolve_vault()


def set_vault(path, settings_file=None, remember=True):
    """Point the app at another notes folder (created if needed) and remember it.
    Every core function reads VAULT when called, so the switch is immediate."""
    global VAULT
    path = os.path.abspath(os.path.expanduser(path))
    ensure_vault(path)
    VAULT = path
    if remember:
        sf = settings_file or settings_path()
        data = load_settings(sf)
        data["vault"] = vault_setting_text(path, sf)
        save_settings(data, sf)
    return VAULT


def copy_vault(src, dst):
    """Copy notes and settings (not the cache or .trash) from one folder into another,
    never overwriting a file already there. Returns how many files were copied."""
    n = 0
    for name in os.listdir(src):
        if name in (".trash", ".calendar-cache.ics") or name.endswith(".tmp"):
            continue
        s, d = os.path.join(src, name), os.path.join(dst, name)
        if os.path.isfile(s) and not os.path.exists(d):
            shutil.copy2(s, d)
            n += 1
        elif name == GRAPH_ICON_DIR and os.path.isdir(s):  # the pictures .graph-icons.json points at
            os.makedirs(d, exist_ok=True)
            n += copy_vault(s, d)
    return n

HOME_GUIDE = """# Home

Welcome to SimpleBrain. This is an ordinary note: change it however you like. Everything below is the shortest way to get something done. (The **How to** button at the top walks you through the window, with one thing to try at each step.)

## Get it out of your head (one line, Enter)
In the bar at the top:
- `t call the bank fri` → a task, due Friday. Dates the way you say them: today, tomorrow, fri, next mon, nov 5, in 3 days.
- `c tomorrow 2pm dentist` → on the calendar.
- anything else → the Inbox, to decide later (one click: Task, Event or Note).
- or start typing a name: notes, files on any drive, apps and open windows come up. Enter opens it.

The same `t …` and `c …` lines work inside any note; they're filed when it saves.

## Know what to do now
- **Today** (File → Today, and at login): three things, never more, each with its files and links already one click away. Your money, the line you left yesterday, people to reach, your longest free stretch.
- Tick a task when it's done: it's checked off in its note too.
- `limit:: 3h` (or `limit:: until 9pm`) in this note: time left shows at the top, and 10 minutes before the end SimpleBrain asks where you stopped; tomorrow's Today opens with it.
- Drifting (email, video, social) for 10 minutes brings one small card: Back to it, or Taking a break.
  `focus:: youtube python` here means a title with those words is never drift.

## Connect your thinking
- Type two square brackets and a few letters: pick the note from the list. Clicking a link opens it (or creates it).
- Under the editor: **Linked from** (hover: the line that links here), **Mentioned in** (notes that name this one without a link: one click links them), **Related** (notes about the same things, not linked yet).
- **Graph**: the open note and what's connected to it. **Dataview**: every note in a table (filter it by a `#tag`); the fields you write, like `status:: active`, become columns, and you can type an Obsidian-style query (`TABLE status FROM #project`).
- Under a question, `answer:: your answer`: each note you link gets a "<name> - Answers" note collecting them.

## Files, without moving them by hand
- Drop files or folders on the window: each goes into your Projects, Areas or Resources folder (the one it matches by name) and is linked from its note. Drop on the open note to file it with that note. Undo is right there.
- `file:: ~/path/to/file` in a note, or **Link file…**: click it to open it beside your notes.

## Money, forward
The Money button at the top (it shows your balance on a ring; or File → Money, forward) opens a Budget note: `cash:: 250`, `+ 280 pay every friday`,
`- 199 Lawyer 11-22-2026`, `goal:: 345 Python exam 12-19-2026`. You see how far the money lasts, what you end with, and which goals are funded. Drop a bank export on the window to update today's cash.

## People
In a person's note: `every:: 2 weeks` and `birthday:: 03-14`. Today tells you who's due for a check-in; a line with the date (`11-02-2026 called about the bond`) counts as one.

## Your notes are safe
- Plain Markdown files in a folder you own. A note is saved in one step; deleted notes go to `.trash`.
- **Sync…** keeps two computers the same, no account. If both changed a note, you keep both versions.
- Updates install themselves; Help → About says you're on the latest.
"""
# Earlier wording of the starter note: a device that still has one of these untouched has not edited Home.
OLD_HOME_GUIDES = (
    """# Home

Welcome to SimpleBrain. This is an ordinary note: change it however you like. Everything below is the shortest way
to get something done. (Help → Take the tour shows the window piece by piece.)

## Get it out of your head (one line, Enter)
In the bar at the top:
- `t call the bank fri` → a task, due Friday. Dates the way you say them: today, tomorrow, fri, next mon, nov 5, in 3 days.
- `c tomorrow 2pm dentist` → on the calendar.
- anything else → the Inbox, to decide later (one click: Task, Event or Note).
- or start typing a name: notes, files on any drive, apps and open windows come up. Enter opens it.
The same `t …` and `c …` lines work inside any note; they're filed when it saves.

## Know what to do now
- **Today** (File → Today, and at login): three things, never more, each with its files and links already one click
  away. Your money, the line you left yesterday, people to reach, your longest free stretch.
- Tick a task when it's done. The count at the top says how many of today's three are done.
- `limit:: 3h` (or `limit:: until 9pm`) in this note: time left shows at the top, and 10 minutes before the end
  SimpleBrain asks where you stopped; tomorrow's Today opens with it.
- Drifting (email, video, social) for 10 minutes brings one small card: Back to it, or Taking a break.
  `focus:: youtube python` here means a title with those words is never drift.

## Connect your thinking
- Type two square brackets and a few letters: pick the note from the list. Clicking a link opens it (or creates it).
- Under the editor: **Linked from** (hover: the line that links here), **Mentioned in** (notes that name this one
  without a link: one click links them), **Related** (notes about the same things, not linked yet).
- **Graph**: the open note and what's connected to it. **Dataview**: every note, filtered by #tag.
- Under a question, `answer:: your answer`: each note you link gets a "<name> - Answers" note collecting them.

## Files, without moving them by hand
- Drop files or folders on the window: each goes into your Projects, Areas or Resources folder (the one it matches
  by name) and is linked from its note. Drop on the open note to file it with that note. Undo is right there.
- `file:: ~/path/to/file` in a note, or **Link file…**: click it to open it beside your notes.

## Money, forward
The Money button at the top (it shows your balance on a ring; or File → Money, forward) opens a Budget note: `cash:: 250`, `+ 280 pay every friday`,
`- 199 Lawyer 11-22-2026`, `goal:: 345 Python exam 12-19-2026`. You see how far the money lasts, what you end
with, and which goals are funded. Drop a bank export on the window to update today's cash.

## People
In a person's note: `every:: 2 weeks` and `birthday:: 03-14`. Today tells you who's due for a check-in; a line with
the date (`11-02-2026 called about the bond`) counts as one.

## Your notes are safe
- Plain Markdown files in a folder you own. A note is saved in one step; deleted notes go to `.trash`.
- **Sync…** keeps two computers the same, no account. If both changed a note, you keep both versions.
- Updates install themselves; Help → About says you're on the latest.
""",  # 0.4.0's, hard-wrapped
    '# Home\n\nWelcome to SimpleBrain. This is an ordinary note: change it however you like.\n\n## How it fits together\n- **Capture** (bar at the top): type a thought and press Enter. It lands in the Inbox.\n- **Inbox** (bottom): file each item as a Task, Event or Note with one click, or Edit/Delete it.\n- **Tasks**: every line starting `t ` in any note, like `t call the bank due:10-01-2026`. Tick it when done.\n- **Shorthand**: start a line with `i ` (Inbox) or `c 10-05-2026 2pm ` (Calendar, time optional); it moves there when you save.\n- **Calendar**: your events, plus a synced calendar feed if you set one in `.config`.\n- **Links**: put a note\'s name in double square brackets to link to it. The link appears under the editor; click it to open that note, or create it if it doesn\'t exist yet.\n- **Linked from**: under the editor, the notes that link to the one you\'re reading.\n- **Graph**: every note and link. Click a dot to open it.\n- **Answers**: under a question, write `answer:: your answer`. Every note you link to gets a "<name> - Answers" note that collects the answers from all the notes linking to it.\n',  # the first release's
    """# Home

Welcome to SimpleBrain. This is an ordinary note: change it however you like. (Help → Take the tour shows the window piece by piece.)

## The basics
- **Capture** (bar at the top): type a thought and press Enter. It lands in the Inbox.
- **Inbox** (bottom): file each item as a Task, Event or Note with one click, or Edit/Delete it. A Thought/Note becomes its own note, titled with the start of the thought.
- **Tasks**: every line starting `t ` in any note, like `t call the bank due:10-01-2026`. Tick it when done.
- **Shorthand**: start a line with `i ` (Inbox) or `c 10-05-2026 2pm ` (Calendar, time optional); it moves there when you save.
- **Calendar**: your events, plus an outside calendar shown next to them: click **Link…** and paste its iCal (.ics) link (treat the link like a password), or **Choose file…** for an .ics or .csv file. Times from other time zones show on this computer's clock. Put a note's name in double square brackets in an event title to get a button that opens that note.

## Notes and links
- **Links**: put a note's name in double square brackets to link to it. The link appears under the editor; click it to open that note, or create it if it doesn't exist yet.
- **Linked from**: under the editor, the notes that link to the one you're reading.
- **Files**: **Link file…** adds a `file::` line pointing at a document on your computer; click it under the editor to open it.
- **Rename**: the pencil next to a note in the list. Every link to the note is changed to the new name for you.
- **Broken links**: File → Broken links… lists links to notes that don't exist yet, and which notes use them. A typo in a link shows up here.
- **Graph**: the open note and the notes connected to it; tick **Show all notes** for everything. Click a dot to open it.
- **Dataview**: every note in a table; filter by #tag or title.
- **Answers**: under a question, write `answer:: your answer`. Every note you link to gets a "<name> - Answers" note that collects the answers from all the notes linking to it.

## Your notes are safe
- A note is saved in one step, so a crash or a pulled USB stick can't leave half a note.
- Deleted notes go to `.trash` inside your notes folder, never straight to oblivion.
- **Sync…** (top) keeps two computers the same. If both changed a note, you get both versions: one under its name and one as `Note (conflict …)`.
""",
    """# Home

Welcome to SimpleBrain. This is an ordinary note: change it however you like.

## How it fits together
- **Capture** (bar at the top): type a thought and press Enter. It lands in the Inbox.
- **Inbox** (bottom): file each item as a Task, Event or Note with one click, or Edit/Delete it. A Thought/Note becomes its own note, titled with the start of the thought.
- **Tasks**: every line starting `t ` in any note, like `t call the bank due:10-01-2026`. Tick it when done.
- **Shorthand**: start a line with `i ` (Inbox) or `c 10-05-2026 2pm ` (Calendar, time optional); it moves there when you save.
- **Calendar**: your events, plus an external calendar: click **Connect…** and paste its iCal (.ics) link (read-only; treat the link like a password). Put a note's name in double square brackets in an event title to get a button that opens that note.
- **Links**: put a note's name in double square brackets to link to it. The link appears under the editor; click it to open that note, or create it if it doesn't exist yet.
- **Linked from**: under the editor, the notes that link to the one you're reading.
- **Graph**: every note and link. Click a dot to open it.
- **Answers**: under a question, write `answer:: your answer`. Every note you link to gets a "<name> - Answers" note that collects the answers from all the notes linking to it.
""",
    """# Home

Welcome to SimpleBrain. This is an ordinary note: change it however you like.

## How it fits together
- **Capture** (bar at the top): type a thought and press Enter. It lands in the Inbox.
- **Inbox** (bottom): file each item as a Task, Event or Note with one click, or Edit/Delete it. A Thought/Note becomes its own note, titled with the start of the thought.
- **Tasks**: every line starting `t ` in any note, like `t call the bank due:10-01-2026`. Tick it when done.
- **Shorthand**: start a line with `i ` (Inbox) or `c 10-05-2026 2pm ` (Calendar, time optional); it moves there when you save.
- **Calendar**: your events, plus an external calendar: click **Link…** and paste its iCal (.ics) link (read-only; treat the link like a password). Put a note's name in double square brackets in an event title to get a button that opens that note.
- **Links**: put a note's name in double square brackets to link to it. The link appears under the editor; click it to open that note, or create it if it doesn't exist yet.
- **Linked from**: under the editor, the notes that link to the one you're reading.
- **Graph**: the open note and the notes connected to it; tick **Show all notes** for everything. Click a dot to open it.
- **Answers**: under a question, write `answer:: your answer`. Every note you link to gets a "<name> - Answers" note that collects the answers from all the notes linking to it.
""",
    HOME_GUIDE.replace("- Tick a task when it's done: it's checked off in its note too.\n",
                       "- Tick a task when it's done. The count at the top says how many of today's three are done.\n"),
)


def get_ics_url(vault=None):
    """Calendar feed URL lives outside the repo, in a gitignored local
    config file (the URL itself is a bearer token - never hardcode it)."""
    vault = vault or VAULT
    path = os.path.join(vault, ".config")
    if not os.path.exists(path):
        return None
    for line in open(path, encoding="utf-8"):
        if line.startswith("ICS_URL="):
            return line[len("ICS_URL="):].strip() or None
    return None

def set_ics_url(url, vault=None):
    """Connect (or, with a blank url, disconnect) the external calendar feed.
    Returns the stored URL, or raises ValueError for anything but http(s)
    (urlopen would also read file:// paths). webcal:// is what calendar apps
    hand out for the same feed over https. The old cache goes too, so a
    failed fetch can't show the previous calendar as 'offline'."""
    vault = vault or VAULT
    url = url.strip()
    if url.lower().startswith("webcal://"):
        url = "https://" + url[len("webcal://"):]
    if url and not re.match(r"https?://\S+$", url, re.IGNORECASE):
        raise ValueError("The feed address must start with https:// (or webcal://).")
    if re.match(r"http://[^/]*@", url, re.IGNORECASE):
        raise ValueError("A link with a login in it must start with https://.")
    path = os.path.join(vault, ".config")
    keep = []
    keep = _config_lines_without(path, ("ICS_URL=", "CALENDAR_FILE="))
    if url:
        keep.append(f"ICS_URL={url}")
    _write_config(path, keep)
    _drop_calendar_cache(vault)
    return url or None


def _config_lines_without(path, keys):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [l for l in f.read().splitlines() if not l.lstrip("# ").startswith(keys)]


def _write_config(path, lines):
    write_atomic(path, "\n".join(lines) + "\n" if lines else "")


def _drop_calendar_cache(vault):
    cache = os.path.join(vault, ".calendar-cache.ics")
    if os.path.exists(cache):
        os.remove(cache)


CALENDAR_FILE_TYPES = (".ics", ".csv")
CALENDAR_FILE_MAX = 5 * 1024 * 1024  # a personal calendar export is far smaller


def get_calendar_file(vault=None):
    """The calendar file as stored in .config (relative to the vault when it sits near it)."""
    vault = vault or VAULT
    path = os.path.join(vault, ".config")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.startswith("CALENDAR_FILE="):
                return line[len("CALENDAR_FILE="):].strip() or None
    return None


def resolve_calendar_file(vault=None):
    """Absolute path of the connected calendar file, or None."""
    vault = vault or VAULT
    stored = get_calendar_file(vault)
    return os.path.normpath(os.path.join(vault, os.path.expanduser(stored))) if stored else None


def set_calendar_file(path, vault=None):
    """Connect (or, with a blank path, disconnect) a calendar file: .ics, or a .csv with Date
    and Title columns. Raises ValueError for anything else. Stored relative to the vault when
    possible, so the vault and its calendar can move together (a USB drive changing letter).
    One source at a time: this also drops a connected link."""
    vault = vault or VAULT
    path = (path or "").strip()
    stored = None
    if path:
        full = os.path.abspath(os.path.expanduser(path))
        if not os.path.isfile(full):
            raise ValueError("That file doesn't exist.")
        if not full.lower().endswith(CALENDAR_FILE_TYPES):
            raise ValueError("Choose an .ics calendar file or a .csv with Date and Title columns.")
        if os.path.getsize(full) > CALENDAR_FILE_MAX:
            raise ValueError("That file is over 5 MB: too big to be a calendar.")
        try:
            stored = os.path.relpath(full, vault)
        except ValueError:  # Windows: different drive letters
            stored = full
        if full.lower().endswith(".csv"):
            csv_to_ics(read_text_file(full))  # raises ValueError now, not at the next sync
    cfg = os.path.join(vault, ".config")
    keep = _config_lines_without(cfg, ("ICS_URL=", "CALENDAR_FILE="))
    if stored:
        keep.append(f"CALENDAR_FILE={stored}")
    _write_config(cfg, keep)
    _drop_calendar_cache(vault)
    return stored


def read_text_file(path):
    with open(path, encoding="utf-8-sig", errors="replace") as f:  # -sig: Excel's BOM
        return f.read()


_CSV_TITLE = ("subject", "title", "summary", "event", "name")
_CSV_DATE = ("start date", "date", "start", "startdate", "begin")
_CSV_TIME = ("start time", "time", "starttime")


def csv_to_ics(text):
    """A calendar CSV (Google/Outlook/Excel exports, or by hand) as minimal .ics text, so one
    parser serves both. Needs a header row with a date column (Date, Start Date...) and a title
    column (Title, Subject, Summary...); a time column (Time, Start Time) is optional. Rows with
    an unreadable date or no title are skipped."""
    import csv
    import io
    rows = list(csv.reader(io.StringIO(text), dialect=_sniff(text)))
    if not rows:
        raise ValueError("The CSV file is empty.")
    head = [h.strip().lower() for h in rows[0]]
    col = lambda names: next((head.index(n) for n in names if n in head), None)
    c_title, c_date, c_time = col(_CSV_TITLE), col(_CSV_DATE), col(_CSV_TIME)
    if c_title is None or c_date is None:
        raise ValueError("The CSV needs a header row with Date and Title columns "
                         "(e.g. Date, Time, Title).")
    out = ["BEGIN:VCALENDAR"]
    for r in rows[1:]:
        if len(r) <= max(c_title, c_date):
            continue
        d, title = parse_date(r[c_date]), r[c_title].strip()
        if d is None or not title:
            continue
        t = parse_time(r[c_time]) if c_time is not None and c_time < len(r) and r[c_time].strip() else None
        title = " ".join(title.split())
        if t:
            start = f"DTSTART:{d:%Y%m%d}T{t.replace(':', '')}00"
        else:
            start = f"DTSTART;VALUE=DATE:{d:%Y%m%d}"
        out += ["BEGIN:VEVENT", f"SUMMARY:{title}", start, "END:VEVENT"]
    out.append("END:VCALENDAR")
    return "\n".join(out) + "\n"


def _sniff(text):
    import csv
    try:
        return csv.Sniffer().sniff(text[:2048], delimiters=",;\t")
    except csv.Error:
        return csv.excel


WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")
TAG_RE = re.compile(r"#([\w/-]+)")
# A task: "t text" (open), or a "- [x] text" checkbox once ticked. Groups:
# indent, marker, checkbox mark (None for t), text.
TASK_RE = re.compile(r"^(\s*)(t +|-\s\[([ xX])\]\s*)(.*)$")
OPEN_BOX_RE = re.compile(r"^(\s*)-\s\[ \]\s*(\S.*)$")  # old open-task format, converted to t
DUE_RE = re.compile(r"due:(\d{4}-\d{2}-\d{2}|\d{1,2}[-/]\d{1,2}[-/]\d{4})")
# Pending: "- text". Not pending: the checkbox forms "- [-]" (filed) and
# "- [x]"/"- [ ]" (tasks). Text like "[link] idea" is still pending.
INBOX_PENDING_RE = re.compile(r"^-\s+(?!\[[-xX ]\])(.*)$")
CAL_LINE_RE = re.compile(r"^-\s+(\d{4}-\d{2}-\d{2})(?:\s+(\d{2}:\d{2}))?\s+(.*)$")
ANSWER_RE = re.compile(r"^\s*answer::(.*)$", re.IGNORECASE)
QUESTION_RE = re.compile(r"^\s*(\d+\.\s*.*)$")
SHORTHAND_RE = re.compile(r"^([ic]) +(\S.*)$")
ANSWERS_SUFFIX = " - Answers"
ANSWERS_MARK = "<!-- SimpleBrain builds this note from answer:: lines; edits here get replaced -->"


# ---------- pure data layer (no UI) ----------

def ensure_vault(vault=None):
    vault = vault or VAULT
    os.makedirs(vault, exist_ok=True)
    home = os.path.join(vault, "Home.md")
    if not os.path.exists(home):
        with open(home, "w", encoding="utf-8", newline="\n") as f:
            f.write(HOME_GUIDE)
    else:  # a starter note you never edited gets the current wording; one you changed is yours
        try:
            if pristine_home(read_note("Home.md", vault)):
                write_atomic(home, HOME_GUIDE)
        except (OSError, ValueError):
            pass
    for name in (INBOX_FILE, CALENDAR_FILE):
        path = os.path.join(vault, name)
        if not os.path.exists(path):
            open(path, "w", encoding="utf-8", newline="\n").close()
    if not os.path.exists(os.path.join(vault, ".config")):
        with open(os.path.join(vault, ".config"), "w", encoding="utf-8", newline="\n") as f:
            f.write("# ICS_URL=https://your-calendar-feed.ics\n")


SETTINGS_NOTES = ("Home.md", "Settings.md")  # where setting lines (plan::, limit::, focus::, app:: …) are read


def settings_text(vault=None):
    """Home and a note called Settings together: the lines SimpleBrain reads its few settings from. Raises OSError
    only when neither can be read."""
    vault = vault or VAULT
    parts, err = [], None
    for n in SETTINGS_NOTES:
        try:
            parts.append(read_note(n, vault))
        except FileNotFoundError:
            continue
        except OSError as e:
            err = e
    if not parts and err:
        raise err
    return "\n".join(parts)


def _plain(text):
    return "\n".join(line.rstrip() for line in text.strip().splitlines())


def pristine_home(text):
    """True when Home is one of SimpleBrain's own starter texts, untouched (a stray trailing space or blank line
    doesn't count as an edit)."""
    return _plain(text) in {_plain(g) for g in OLD_HOME_GUIDES}


def list_notes(vault=None):
    vault = vault or VAULT
    return sorted(f for f in os.listdir(vault)
                  if f.endswith(".md") and not f.startswith("."))


def list_user_notes(vault=None):
    """Notes the user writes. Inbox.md and Calendar.md are the files behind
    the Inbox and Calendar panels - listed as notes they just confuse, so
    they're hidden from the sidebar, graph and Dataview (tasks in them still
    count: parse_tasks uses list_notes)."""
    vault = vault or VAULT
    return [n for n in list_notes(vault) if n not in (INBOX_FILE, CALENDAR_FILE)]


def backlinks(filename, vault=None):
    """Notes that link to this one with [[Title]]."""
    vault = vault or VAULT
    title = note_title(filename)
    return [n for n in list_user_notes(vault)
            if n != filename and title in parse_links(read_note(n, vault))]


def note_title(filename):
    return filename[:-3]


def read_note(filename, vault=None):
    vault = vault or VAULT
    with open(os.path.join(vault, filename), "rb") as f:
        data = f.read()
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:  # saved by another program as Windows-1252: show it readably instead of failing the whole app
        text = data.decode("cp1252", errors="replace")
    return text.replace("\r\n", "\n").replace("\r", "\n")  # what text mode used to do


def edited_elsewhere_name(filename, vault=None, today=None):
    """A free name for typing that lost to an outside edit of `filename`."""
    vault = vault or VAULT
    stamp = (today or date.today()).isoformat()
    cand, i = f"{filename[:-3]} (typed here {stamp}).md", 2
    while os.path.exists(os.path.join(vault, cand)):
        cand = f"{filename[:-3]} (typed here {stamp} {i}).md"
        i += 1
    return cand


def replace_retrying(src, dst, tries=20):
    """os.replace, waiting out Windows' sharing lock: a note another thread (or the indexer, or a virus scanner)
    is reading for a moment refuses the swap with Access denied. Elsewhere the first try works."""
    for i in range(tries):
        try:
            return os.replace(src, dst)
        except PermissionError:
            if sys.platform != "win32" or i == tries - 1:
                raise
            time.sleep(0.05)


def write_atomic(path, text):
    """Write to a side file, then swap it in: a crash, a full disk or a pulled USB stick
    leaves the old text, never half of the new. The side file is made the ordinary way
    (not mkstemp) so the note keeps the permissions a normal save gives it."""
    path = os.path.realpath(path)  # a symlinked note stays a link
    tmp = f"{os.path.dirname(path)}{os.sep}.{os.path.basename(path)}.{os.getpid()}.{threading.get_ident()}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        replace_retrying(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def write_note(filename, text, vault=None):
    vault = vault or VAULT
    write_atomic(os.path.join(vault, filename), text)


def note_trash_path(filename, vault=None):
    """Reversible trash: move, don't delete,
    dedup on collision instead of overwriting."""
    vault = vault or VAULT
    trash_dir = os.path.join(vault, ".trash")
    os.makedirs(trash_dir, exist_ok=True)
    dest = os.path.join(trash_dir, filename)
    base, ext = os.path.splitext(filename)
    i = 1
    while os.path.exists(dest):
        dest = os.path.join(trash_dir, f"{base} ({i}){ext}")
        i += 1
    return dest


def delete_note(filename, vault=None):
    vault = vault or VAULT
    dest = note_trash_path(filename, vault)
    shutil.move(os.path.join(vault, filename), dest)
    return dest


# What a graph dot shows instead of plain blue: {note file: emoji, or "pictures/<file>" under GRAPH_ICON_DIR}.
# Hidden, beside the notes (so it moves with the folder) but never inside one: notes stay plain Markdown.
GRAPH_ICONS = ".graph-icons.json"
GRAPH_ICON_DIR = ".graph-icons"
PICTURE_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")


def graph_icons(vault=None):
    vault = vault or VAULT
    data = load_settings(os.path.join(vault, GRAPH_ICONS))
    return {k: v for k, v in data.items() if isinstance(v, str) and v}


def graph_icon_picture(icon, vault=None):
    """Full path of a picture icon, or None for an emoji."""
    if not icon.startswith("pictures/"):
        return None
    return os.path.join(vault or VAULT, GRAPH_ICON_DIR, os.path.basename(icon))


def set_graph_icon(filename, emoji=None, picture=None, vault=None):
    """Give `filename`'s dot an emoji, or a copy of the picture file at `picture`; neither clears it.
    The copy means the icon survives the original being moved or deleted."""
    vault = vault or VAULT
    ext = os.path.splitext(picture)[1].lower() if picture else ""
    if picture and ext not in PICTURE_EXTS:  # checked first: a refused file leaves the old icon as it was
        raise ValueError(f"not a picture: {picture}")
    icons = graph_icons(vault)
    old = icons.pop(filename, None)
    if old and (path := graph_icon_picture(old, vault)) and os.path.exists(path):
        os.remove(path)  # a replaced picture would otherwise pile up unseen
    if picture:
        os.makedirs(os.path.join(vault, GRAPH_ICON_DIR), exist_ok=True)
        name = hashlib.sha1(filename.encode()).hexdigest()[:12] + ext  # any note title makes a safe file name
        shutil.copyfile(picture, os.path.join(vault, GRAPH_ICON_DIR, name))
        icons[filename] = "pictures/" + name
    elif emoji and emoji.strip():
        icons[filename] = emoji.strip()
    save_settings(icons, os.path.join(vault, GRAPH_ICONS))
    return icons.get(filename)


# Which notes may go on the website. Opt-in, hidden beside the notes like the graph icons: notes stay plain Markdown.
PUBLIC_FILE = ".public.json"


def public_notes(vault=None):
    """Note files marked public that still exist."""
    vault = vault or VAULT
    data = load_settings(os.path.join(vault, PUBLIC_FILE))
    return sorted(n for n, on in data.items() if on is True and os.path.exists(os.path.join(vault, n)))


def is_public(filename, vault=None):
    return filename in public_notes(vault)


def set_public(filename, on, vault=None):
    vault = vault or VAULT
    path = os.path.join(vault, PUBLIC_FILE)
    data = load_settings(path)
    if on:
        data[filename] = True
    else:
        data.pop(filename, None)
    save_settings(data, path)


def link_target(inner):
    """The note a link points at: '[[Note|shown text]]' and '[[Note#Heading]]' both mean Note (as in Obsidian)."""
    return inner.split("|")[0].split("#")[0].strip()


def parse_links(text):
    """The notes a text links to, in order. A link to a heading of the note itself ('[[#Heading]]') names none."""
    return [t for m in WIKILINK_RE.finditer(text) if (t := link_target(m.group(1)))]


FILE_RE = re.compile(r"^\s*file::\s*(.+?)\s*$", re.MULTILINE)


def parse_files(text):
    """Where a note says its outside files are: every `file:: path` line."""
    return FILE_RE.findall(text)


def file_line(path, vault=None):
    """The `file:: ` line for a chosen file; relative when it sits inside the vault, so it moves with the folder."""
    vault = os.path.abspath(vault or VAULT)
    path = os.path.abspath(path)
    if path.startswith(vault + os.sep):
        path = os.path.relpath(path, vault).replace(os.sep, "/")  # "/" so the line reads the same on every system
    return "file:: " + path


def resolve_file(ref, vault=None):
    return os.path.join(vault or VAULT, os.path.expanduser(ref))  # an absolute ref wins the join


def broken_links(vault=None):
    """{missing title: [notes that link to it]}, sorted: links that open a blank page because no
    note has that name (usually a typo). Inbox and Calendar are panels, not notes, so a link to
    them is not broken."""
    vault = vault or VAULT
    have = {note_title(n) for n in list_user_notes(vault)} | {note_title(INBOX_FILE), note_title(CALENDAR_FILE)}
    out = {}
    for n in list_user_notes(vault):
        for link in dict.fromkeys(parse_links(read_note(n, vault))):
            if link not in have:
                out.setdefault(link, []).append(n)
    return dict(sorted(out.items(), key=lambda kv: kv[0].casefold()))


def rename_note(filename, new_title, vault=None):
    """Rename a note and point every [[link]] to it at the new name. Returns (new file name,
    how many other notes were changed). ValueError, with a sentence for the user, if the name
    can't be used; nothing is touched then."""
    vault = vault or VAULT
    new_title = new_title.strip()
    old_title = note_title(filename)
    if filename in (INBOX_FILE, CALENDAR_FILE, "Home.md") or ANSWERS_MARK in read_note(filename, vault):
        raise ValueError("The app manages this note, so it can't be renamed.")
    if not is_safe_note_title(new_title):
        raise ValueError('A name can\'t be empty, start or end with a dot or space, or contain / \\ : * ? " < > |')
    if is_reserved_title(new_title):
        raise ValueError(f'"{new_title}" is a name the app uses itself. Pick another.')
    new_file = new_title + ".md"
    if new_title == old_title:
        return filename, 0
    if any(n.casefold() == new_file.casefold() and n != filename for n in os.listdir(vault)):  # casefold: a vault moves between systems
        raise ValueError(f'There is already a note called "{new_title}".')
    os.rename(os.path.join(vault, filename), os.path.join(vault, new_file))
    for settings in (PUBLIC_FILE, GRAPH_ICONS):  # these remember notes by file name
        path = os.path.join(vault, settings)
        data = load_settings(path)
        if filename in data:
            data[new_file] = data.pop(filename)
            save_settings(data, path)
    changed = 0  # links last: if this is cut short, Broken links lists what is left
    for n in list_notes(vault):
        text = read_note(n, vault)
        fixed = WIKILINK_RE.sub(lambda m: m.group(0) if link_target(m.group(1)) != old_title else
                                "[[" + new_title + m.group(1)[len(m.group(1).split("|")[0].split("#")[0]):] + "]]", text)
        if fixed != text:
            write_note(n, fixed, vault)
            changed += n != new_file
    return new_file, changed


CODE_RE = re.compile(r"^```.*?^```[ \t]*$|`[^`\n]+`", re.S | re.M)


def without_code(text):
    """The text minus ```code blocks``` and `inline code`: a #tag or field shown as an example, or inside a dataview
    query, isn't one (as in Obsidian)."""
    return CODE_RE.sub(" ", text)


def parse_tags(text):
    """#tags in the text, not the '#' inside a file:: path or a web address ('Lesson #10.mp4' is no tag), nor in code."""
    text = re.sub(r"https?://\S+", " ", FILE_RE.sub("", without_code(text)))
    return sorted(set(TAG_RE.findall(text)))


def should_start_ics_fetch(sync, syncing, fetch_attempted):
    """The exact condition that had 3 real bugs in it: a fetch already in
    flight must block a new one (else concurrent threads race on
    the cache file), and "never fetched" must be a ONE-TIME trigger, not
    re-armed by every unrelated local calendar edit forever."""
    return not syncing and (sync or not fetch_attempted)


# A book is studied in three short sittings and two checks from memory. Only the next one is ever a task: ticking
# it writes the one after, due this many days later (toggle_task), so a book never floods the list and the gaps
# follow what was really done. The questions are written a day before their answers, every answer is typed with the
# book closed and then checked, and the checks come back spaced out: asking first, recalling and spacing are what
# make reading stick.
LEARNING_SITTINGS = (  # (days after the one before was ticked, the task)
    (0, "First look, 20 minutes"),
    (1, "Find the answers, 25 minutes"),
    (2, "Say it back, 20 minutes"),
    (7, "Check from memory, a week on"),
    (21, "Check from memory, a month on"),
)
# The template's own guidance lines. Kept out of a published page (publish.strip_private), word for word, so
# nothing the user wrote is ever dropped.
LEARNING_HINTS = (
    "(Three short sittings and two checks. Tick the task below when it's done and the next one appears on its "
    "day. One book at a time works best. After a sitting, take five quiet minutes away from the screen.)",
    "(First look. Finish the line: I want ... so that I can ...)",
    "(One minute with the cover and the contents: how is the book built, and what's your guess at what it says?)",
    "(After your first pass through the whole book: 10 to 25 words that keep coming up.)",
    "(3 to 5 things you want this book to answer, why and how questions most of all. Type each question after its "
    "number, its answer after answer::. Leave the answers empty today and sleep on it.)",
    "(Find the answers, the next day. One question at a time, five minutes each, with a timer:",
    "1) Say your guess before you look. A wrong guess still helps.",
    "2) Pick the chapter that should hold it, from the contents or the index.",
    "3) Run your eyes down the middle of its pages. If something pulls you, go there. If nothing does, read the "
    "first sentence of each paragraph.",
    "4) Read the page or two that answers it at your normal pace. Going back over a hard sentence is fine.",
    "5) Close the book. Type the answer in your own words after answer::, with the page number and why it matters "
    "to you. Then open the book and check it.",
    "Out of time? Type \"not found yet\" and go on to the next question.)",
    "(Say it back, two days later, with the book closed: two minutes out loud, as if telling a friend what the book "
    "says and what you're taking from it. Then cover your answers and answer each question again. Fix what you "
    "got wrong and look up anything still \"not found yet\".)",
    "(The two checks: cover your answers and answer every question from memory. Look up any you miss, cover it, "
    "and answer it again, until each one has come out right once.)",
)


def learning_note_template(title, today=None):
    """A book-study note: Prepare / Preview / Postview / Your Questions / Activation / Next Steps, with the
    sittings as dated tasks at the top (LEARNING_SITTINGS) and one line of guidance per part (LEARNING_HINTS)."""
    today = today or date.today()
    h = LEARNING_HINTS
    sittings = f"t {LEARNING_SITTINGS[0][1]}: {title} due:{today.isoformat()}\n"
    return (
        f"# {title}\n\n"
        "[[Home]]\n\n"
        f"{h[0]}\n{sittings}\n"
        "# Prepare\n"
        f"{h[1]}\n"
        "## Your Initial Purpose::\n\n\n"
        "# Preview\n"
        f"{h[2]}\n"
        "## One Sentence Summary::\n\n\n"
        "# Postview\n"
        f"{h[3]}\n"
        "## Trigger Words or Phrases:: (put each one in double square brackets to link it)\n\n\n"
        "# Your Questions\n"
        f"{h[4]}\n"
        + "".join(f"{i}.\nanswer::\n\n" for i in range(1, 6)) + "\n"
        "# Activation\n"
        + "\n".join(h[5:12]) + "\n\n"
        f"{h[12]}\n"
        "## One Sentence Summary, Now::\n\n"
        "## Your New Purpose, if it has changed::\n\n"
        f"{h[13]}\n\n\n"
        "# Next Steps\n"
        "## What you'll do with this:: (one per line: t task due:MM-DD-YYYY, i for the Inbox, c MM-DD-YYYY event for the Calendar)\n"
    )


# Where a book came from, as a field in the note (it syncs, and dataview can list `WHERE library = "personal"`).
LIBRARY_RE = re.compile(r"^library::[ \t]*(\w*).*$", re.M | re.I)
BOOK_RE = re.compile(r"^#+ *(trigger words|your initial purpose)|\[\[\s*learning\s*(\||\]\])", re.M | re.I)


def is_book_note(text):
    """A Learning Note (its template's headings, or a [[Learning]] link), or one already marked with library::."""
    return bool(BOOK_RE.search(text) or LIBRARY_RE.search(text))


def library_of(text):
    """"personal", "public" or None when the note doesn't say."""
    m = LIBRARY_RE.search(text)
    return m.group(1).lower() or None if m else None


def set_library(text, personal):
    """The text with its library:: line saying personal or public: replaced where it is, else put under the title
    and its [[Home]] line."""
    line = "library:: " + ("personal" if personal else "public")
    if LIBRARY_RE.search(text):
        return LIBRARY_RE.sub(line, text, count=1)
    lines = text.split("\n")
    at = 1 if lines and lines[0].startswith("# ") else 0
    while at < len(lines) and not lines[at].strip():
        at += 1
    if at < len(lines) and lines[at].strip() == "[[Home]]":
        at += 1
    if at == 0:
        return line + "\n\n" + text
    return "\n".join(lines[:at] + [line] + lines[at:])


def blank_note_template(title):
    """Same header as the learning note (title, [[Home]] link), no sections."""
    return f"# {title}\n\n[[Home]]\n\n"


BAD_TITLE_CHARS = set('/\\:*?"<>|')


def is_safe_note_title(title):
    """Rejects a title that would escape the vault via os.path.join (a
    stray '/' or '..') or that Windows/macOS can't use as a file name -
    both the New Note dialog and clicking a [[wikilink]] from note
    content route through this check. Same rule on every OS, so a vault
    copied between machines never holds a note one of them can't open."""
    return (title.strip() not in ("", ".", "..") and not BAD_TITLE_CHARS & set(title) and title.isprintable()
            and len(title.encode()) <= 200  # file names cap at 255 bytes; leaves room for ".md" and sync's conflict suffix
            and not title.endswith((".", " ")) and not title.startswith("."))  # a leading dot hides the note


# Names the app's own files use (Recommendations is written by simplebrain_recommend). Case-insensitive so a
# vault copied to Windows/macOS never holds a note that collides with them.
RESERVED_TITLES = {"inbox", "calendar", "recommendations"}


def is_reserved_title(title):
    """True for a title a new note must not take: it would open or overwrite a file the app manages."""
    t = title.strip()
    return t.casefold() in RESERVED_TITLES or t.endswith(ANSWERS_SUFFIX)


def parse_date(s):
    """A date as the user types it (MM-DD-YYYY or M/D/YYYY, US order) or as
    files store it (YYYY-MM-DD); None if it isn't a real date. Files always
    get YYYY-MM-DD written (sorts, and is what CAL_LINE_RE reads); the UI
    shows show_date()."""
    for fmt in ("%m-%d-%Y", "%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s.strip(), fmt).date()
        except ValueError:
            pass
    return natural_date(s)


WEEKDAY_NAMES = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
MONTH_NAMES = ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
               "november", "december")


def _named(word, names):
    """Index of a day or month written whole or cut short ('fri', 'thur', 'sept'), or None."""
    word = word.rstrip(".")
    if len(word) < 3:
        return None
    return next((i for i, n in enumerate(names) if n.startswith(word)), None)


def natural_date(s, today=None):
    """Dates the way people say them: today, tomorrow, fri, next mon, in 3 days, in 2 weeks, nov 5, 5 nov,
    11-5 (this year, or next once it's passed). None if it isn't one."""
    today = today or date.today()
    t = " ".join(str(s).strip().lower().replace(",", " ").split())
    if t in ("today", "tonight"):
        return today
    if t in ("tomorrow", "tmrw", "tmr"):  # not "tom": that's someone's name
        return today + timedelta(days=1)
    m = re.fullmatch(r"in (\d{1,3}) (day|week|month)s?", t)
    if m:
        return today + timedelta(days=int(m.group(1)) * {"day": 1, "week": 7, "month": 30}[m.group(2)])
    m = re.fullmatch(r"(next |this )?([a-z.]+)", t)
    if m and (wd := _named(m.group(2), WEEKDAY_NAMES)) is not None:
        ahead = (wd - today.weekday()) % 7
        return today + timedelta(days=ahead + (7 if m.group(1) == "next " else 0))
    m = re.fullmatch(r"(\d{1,2})[/-](\d{1,2})", t)
    parts = None
    if m:
        parts = (int(m.group(1)), int(m.group(2)))
    else:
        m = re.fullmatch(r"([a-z.]+) (\d{1,2})(?:st|nd|rd|th)?", t) or re.fullmatch(r"(\d{1,2})(?:st|nd|rd|th)? ([a-z.]+)", t)
        if m:
            word, num = (m.group(1), m.group(2)) if m.group(1)[0].isalpha() else (m.group(2), m.group(1))
            mo = _named(word, MONTH_NAMES)
            parts = (mo + 1, int(num)) if mo is not None else None
    if parts:
        for year in (today.year, today.year + 1):
            try:
                d = date(year, *parts)
            except ValueError:
                return None
            if d >= today:
                return d
    return None


def split_date(text, today=None):
    """(date, the rest) when `text` starts with a date in any form ('next fri 2pm dentist'), else (None, text)."""
    words = text.split()
    for n in (3, 2, 1):
        if len(words) > n - 1:
            head = " ".join(words[:n])
            d = natural_date(head, today)  # first: 'fri' counts from `today`, not from the clock
            if n == 1 and d is None:
                d = parse_date(head)
            if d:
                return d, " ".join(words[n:])
    return None, text


def trailing_date(text, today=None):
    """(the text, date) when it ends with a date ('call the bank fri', '… due:11-06-2026'), else (text, None)."""
    m = re.search(r"\s*\bdue:(\S+)\s*$", text)
    if m:
        d = parse_date(m.group(1).replace("-", " ") if not re.match(r"\d", m.group(1)) else m.group(1)) \
            or natural_date(m.group(1).replace("-", " "), today)
        return (text[:m.start()].strip(), d) if d else (text, None)
    words = text.split()
    for n in (3, 2, 1):
        if len(words) > n:
            tail = " ".join(words[-n:])
            d = natural_date(tail, today) or (parse_date(tail) if n == 1 else None)
            if d:
                return " ".join(words[:-n]), d
    return text, None


WORD_DUE_RE = re.compile(r"\bdue:((?:next-|this-|in-\d+-(?:days?|weeks?)\b)?[A-Za-z][A-Za-z.]*(?:-\d{1,2})?|\d{1,2}[-/]\d{1,2}(?![-/\d]))")


def concrete_due(line, today=None):
    """'t call the bank due:fri' -> 't call the bank due:2026-11-06' (any natural date after due:)."""
    def fix(m):
        d = natural_date(m.group(1).replace("-", " ") if not re.match(r"\d", m.group(1)) else m.group(1), today)
        return f"due:{d.isoformat()}" if d else m.group()
    return WORD_DUE_RE.sub(fix, line)


def add_task(text, due=None, vault=None):
    """A task straight from the top bar: a 't …' line in the Inbox note, the same place a filed Inbox item goes."""
    vault = vault or VAULT
    ensure_vault(vault)
    old = read_note(INBOX_FILE, vault).rstrip("\n")
    write_note(INBOX_FILE, old + f"\nt {text}" + (f" due:{due.isoformat()}" if due else "") + "\n", vault)


def show_date(d):
    return d.strftime("%m-%d-%Y")


def _swap_due(text, fmt):
    return DUE_RE.sub(lambda m: "due:" + (d.strftime(fmt) if (d := parse_date(m.group(1))) else m.group(1)),
                      text)


def due_for_display(text):
    """Task text with its due: date in US order, for showing/editing."""
    return _swap_due(text, "%m-%d-%Y")


def due_for_storage(text):
    """Task text with its due: date back in YYYY-MM-DD, for writing."""
    return _swap_due(text, "%Y-%m-%d")


def valid_date(s):
    """A malformed date silently vanishes from the calendar view (the
    regex parser just never matches it back out) - so this must be
    checked before writing, not discovered later by "where did my
    event go?" """
    try:
        datetime.strptime(s, "%Y-%m-%d")
        return True
    except ValueError:
        return False


_PARSED = {}  # note path -> ((mtime_ns, size), (links, tags)): what note_rows last read from it


def _links_and_tags(filename, vault):
    """(sorted links, tags) of a note, re-read only when the file changed. The search box
    asks for every note on every keystroke; a file touched in the last couple of seconds is
    never trusted from here, since a coarse-clock drive (FAT) could show the same stamp twice."""
    path = os.path.join(vault, filename)
    st = os.stat(path)
    stamp = (st.st_mtime_ns, st.st_size)
    hit = _PARSED.get(path)
    if hit and hit[0] == stamp:
        return hit[1]
    text = read_note(filename, vault)
    parsed = (sorted(set(parse_links(text))), parse_tags(text))
    if time.time() - st.st_mtime > 2:
        _PARSED[path] = (stamp, parsed)
    else:
        _PARSED.pop(path, None)
    return parsed


def note_rows(vault=None):
    """One row per note: the data behind the Dataview table. No query
    language - filtering happens with a dropdown + search box in the UI."""
    vault = vault or VAULT
    parsed = {n: _links_and_tags(n, vault) for n in list_user_notes(vault)}
    linkers = {}  # title -> notes linking to it: one pass, not every note against every other
    for m, (links, _) in parsed.items():
        for t in links:
            linkers.setdefault(t, []).append(m)
    rows = []
    for n, (links, tags) in parsed.items():
        title = note_title(n)
        rows.append({
            "file": n,
            "title": title,
            "tags": tags,
            "links": links,  # titles this note links to (may not exist yet)
            "linked_from": [m for m in linkers.get(title, []) if m != n],
            "link_count": len(links),
        })
    return rows


def filter_note_rows(rows, tag=None, search=None):
    out = rows
    if tag:
        out = [r for r in out if tag in r["tags"]]
    if search:
        s = search.lower()
        out = [r for r in out if s in r["title"].lower()]
    return out


def parse_answers(text):
    """[(question, answer)] from 'answer:: ...' lines, each paired with the
    numbered question line above it ('' if none since the last heading).
    Blank answers (the template's placeholders) are skipped."""
    out, question = [], ""
    for line in text.splitlines():
        if m := ANSWER_RE.match(line):
            if m.group(1).strip():
                out.append((question, m.group(1).strip()))
        elif m := QUESTION_RE.match(line):
            question = m.group(1).strip()
        elif line.startswith("#"):
            question = ""
    return out


def answers_note_text(keyword, linkers, answers):
    lines = [f"# {keyword}{ANSWERS_SUFFIX}", "", ANSWERS_MARK, "",
             f"Every note that links to [[{keyword}]], then the answers in those notes.", "",
             "## Linked from"]
    lines += [f"- [[{note_title(n)}]]" for n in linkers]
    lines += ["", "## Answers"]
    for n in linkers:
        if answers[n]:
            lines += ["", f"### [[{note_title(n)}]]", ""]
            for q, a in answers[n]:
                lines += ([f"**{q}**"] if q else []) + [a, ""]
    return "\n".join(lines).rstrip() + "\n"


def sync_answer_notes(vault=None):
    """Rebuild the "<Keyword> - Answers" notes: one per [[link]] made by a
    note holding answer:: lines, Home included.
    Writes only what changed, trashes one whose keyword lost its last
    answer, and never touches a same-named note the user wrote (no
    ANSWERS_MARK). Returns the files written or trashed.
    ponytail: re-reads the whole vault per call; go incremental if saves lag."""
    vault = vault or VAULT
    texts = {n: read_note(n, vault) for n in list_user_notes(vault)}
    generated = {n for n, t in texts.items() if ANSWERS_MARK in t}
    sources = [n for n in texts if n not in generated]
    answers = {n: parse_answers(texts[n]) for n in sources}
    linkers = {}  # keyword -> notes linking to it, in sidebar order
    for n in sources:
        for k in dict.fromkeys(parse_links(texts[n])):
            linkers.setdefault(k, []).append(n)
    skip = {note_title(INBOX_FILE), note_title(CALENDAR_FILE)}
    wanted = {k + ANSWERS_SUFFIX + ".md": answers_note_text(k, ns, answers)
              for k, ns in linkers.items()
              if k not in skip and k + ".md" not in generated and is_safe_note_title(k + ANSWERS_SUFFIX)
              and any(answers[n] for n in ns)}
    changed = []
    for f in sorted(set(wanted) | generated):
        old = texts.get(f)
        if old is not None and f not in generated:
            continue  # the user's own note with this name
        if f not in wanted:
            delete_note(f, vault)
        elif old != wanted[f]:
            write_note(f, wanted[f], vault)
        else:
            continue
        changed.append(f)
    return changed


def build_graph(vault=None):
    """(nodes, edges, missing). Nodes are every note plus every [[link]] to a
    note that doesn't exist yet (`missing`, drawn faded like Obsidian; clicking
    one creates it) - without them, notes that only share a not-yet-written
    link look unconnected."""
    vault = vault or VAULT
    notes = list_user_notes(vault)
    titles = {note_title(n): n for n in notes}
    hidden = {note_title(INBOX_FILE), note_title(CALENDAR_FILE)}
    missing, edges, seen = [], [], set()
    for n in notes:
        for link in _links_and_tags(n, vault)[0]:  # re-read only when the note changed
            target = titles.get(link)
            if target is None:
                if link in hidden or not is_safe_note_title(link):
                    continue
                target = link + ".md"
                if target not in seen:
                    seen.add(target)
                    missing.append(target)
            if target != n and (n, target) not in seen and (target, n) not in seen:
                seen.add((n, target))
                edges.append((n, target))
    return notes + missing, edges, set(missing)


def parse_tasks(vault=None):
    vault = vault or VAULT
    tasks = []
    for n in list_notes(vault):
        for i, line in enumerate(read_note(n, vault).splitlines()):
            m = TASK_RE.match(line)
            if not m:
                continue
            done = (m.group(3) or "").lower() == "x"
            body = m.group(4)
            due_m = DUE_RE.search(body)
            due = parse_date(due_m.group(1)) if due_m else None  # a bad date = no date, not a crash
            tasks.append({"file": n, "line": i, "text": body, "due": due, "done": done})
    return tasks


def bucket_tasks(tasks, today=None):
    today = today or date.today()
    buckets = {"Overdue": [], "Today": [], "Upcoming": [], "No date": []}
    for t in tasks:
        if t["done"]:
            continue
        if t["due"] is None:
            buckets["No date"].append(t)
        elif t["due"] < today:
            buckets["Overdue"].append(t)
        elif t["due"] == today:
            buckets["Today"].append(t)
        else:
            buckets["Upcoming"].append(t)
    return buckets


REPEAT_RE = re.compile(r"\bevery:(day|weekday|week|month|mon|tue|wed|thu|fri|sat|sun)\b", re.I)


def next_due(rule, after):
    """The next date a repeating task is due, after `after`."""
    rule = rule.lower()
    if rule == "day":
        return after + timedelta(days=1)
    if rule == "weekday":
        d = after + timedelta(days=1)
        while d.weekday() >= 5:
            d += timedelta(days=1)
        return d
    if rule == "week":
        return after + timedelta(days=7)
    if rule == "month":
        y, m = after.year + after.month // 12, after.month % 12 + 1
        return date(y, m, min(after.day, [31, 29 if y % 4 == 0 and (y % 100 or y % 400 == 0) else 28, 31, 30, 31,
                                         30, 31, 31, 30, 31, 30, 31][m - 1]))
    wd = ("mon", "tue", "wed", "thu", "fri", "sat", "sun").index(rule)
    return after + timedelta(days=(wd - after.weekday() - 1) % 7 + 1)


def next_sitting(body, lines, today):
    """The task line that follows a ticked sitting of a book ('First look, 20 minutes: Deep Work' -> 'Find the
    answers …' due tomorrow), or None: not a sitting, the last one, or the next is already in the note."""
    for i, (_, what) in enumerate(LEARNING_SITTINGS[:-1]):
        if body.startswith(what + ": "):
            title = DUE_RE.sub("", body[len(what) + 2:]).strip()
            gap, then = LEARNING_SITTINGS[i + 1]
            if not title or any(f"{then}: {title}" in l for l in lines):
                return None
            return f"t {then}: {title} due:{(today + timedelta(days=gap)).isoformat()}"
    return None


def toggle_task(task, vault=None, today=None):
    """Tick a task done (or back). A repeating one (`every:day`, `every:weekday`, `every:week`, `every:mon` …) stays
    open and moves to its next date: done today, back tomorrow. Returns the new due date for a repeat, else None."""
    vault = vault or VAULT
    today = today or date.today()
    lines, m = _matching_line(task["file"], task["line"], TASK_RE, 4, task["text"], vault)
    if not m:
        return None  # the note changed since the list was drawn: the refreshed list shows what's there now
    rep = REPEAT_RE.search(m.group(4))
    if rep and not task["done"]:
        due = DUE_RE.search(m.group(4))
        start = max(today, parse_date(due.group(1)) or today) if due else today
        nxt = next_due(rep.group(1), start)
        body = DUE_RE.sub(f"due:{nxt.isoformat()}", m.group(4)) if due else f"{m.group(4)} due:{nxt.isoformat()}"
        lines[task["line"]] = m.group(1) + m.group(2) + body
        write_note(task["file"], "\n".join(lines) + "\n", vault)
        return nxt
    lines[task["line"]] = m.group(1) + ("t " if task["done"] else "- [x] ") + m.group(4)
    if not task["done"] and (then := next_sitting(m.group(4), lines, today)):
        lines.insert(task["line"] + 1, m.group(1) + then)  # a book's next sitting, on its day
    write_note(task["file"], "\n".join(lines) + "\n", vault)
    return None


def _matching_line(filename, i, regex, group, expected, vault=None):
    """(lines, match) if line i of the file still holds the expected item,
    else (lines, None): the file changed since the list was drawn, and a
    stale line number would edit or delete the wrong line."""
    vault = vault or VAULT
    lines = read_note(filename, vault).splitlines()
    m = regex.match(lines[i]) if i < len(lines) else None
    return lines, (m if m and m.group(group) == expected else None)


DELETED_ITEMS = "deleted-items.md"


def _delete_line(filename, lines, i, vault=None):
    """Remove line i, but log it to .trash/deleted-items.md first (same
    never-straight-to-oblivion rule as delete_note): copy it back to undo."""
    vault = vault or VAULT
    trash_dir = os.path.join(vault, ".trash")
    os.makedirs(trash_dir, exist_ok=True)
    with open(os.path.join(trash_dir, DELETED_ITEMS), "a", encoding="utf-8", newline="\n") as f:
        f.write(f"{lines[i]}  <!-- from {filename}, deleted {datetime.now():%Y-%m-%d %H:%M} -->\n")
    del lines[i]
    write_note(filename, "\n".join(lines) + ("\n" if lines else ""), vault)


def edit_task(task, new_text, vault=None):
    """Replace a task's text, keeping its t / checkbox. False (nothing written)
    if that line no longer holds this task."""
    vault = vault or VAULT
    lines, m = _matching_line(task["file"], task["line"], TASK_RE, 4, task["text"], vault)
    if not m:
        return False
    lines[task["line"]] = m.group(1) + m.group(2) + new_text
    write_note(task["file"], "\n".join(lines) + "\n", vault)
    return True


def delete_task(task, vault=None):
    """Remove a task's line from its note. False if the line changed."""
    vault = vault or VAULT
    lines, m = _matching_line(task["file"], task["line"], TASK_RE, 4, task["text"], vault)
    if not m:
        return False
    _delete_line(task["file"], lines, task["line"], vault)
    return True


GRAPH_HUBS = ("Home.md", "Learning.md", "Recommendations.md")  # linked from nearly everything


def local_graph(notes, edges, center, depth=2, hubs=GRAPH_HUBS):
    """The part of the graph related to one note: what it links to or is linked from, and
    (depth 2) the notes sharing a link with those, so two books that share a keyword show up
    together. Hub notes (Home, Recommendations) and generated Answers roll-ups are shown when
    adjacent but never walked through, or "related" would mean the whole vault. A hub that is
    itself the center shows its direct neighbours only. Returns (nodes, edges) in the original
    order; a center that isn't in the graph returns everything."""
    if center not in notes:
        return list(notes), list(edges)
    adj = {n: set() for n in notes}
    for a, b in edges:
        if a in adj and b in adj:
            adj[a].add(b)
            adj[b].add(a)
    roll = ANSWERS_SUFFIX + ".md"
    seen, frontier = {center}, [center]
    for step in range(depth):
        nxt = []
        for n in frontier:
            if step and (n in hubs or n.endswith(roll)):
                continue  # adjacent, shown, but not a bridge to unrelated notes
            for m in sorted(adj[n]):
                if m not in seen:
                    seen.add(m)
                    nxt.append(m)
        if center in hubs and step == 0:
            break  # a hub center: direct neighbours only
        frontier = nxt
    return [n for n in notes if n in seen], [(a, b) for a, b in edges if a in seen and b in seen]


def mindmap_layout(notes, edges, width=760, height=560, pinned=None):
    """Mind-map positions: `pinned` (e.g. Home.md) at the center, the notes it
    links to on a ring around it, theirs on the next ring, each branch in its
    own wedge. Same links always give the same picture. A note with several
    paths hangs off the first one found; notes not connected to the center
    become their own branches on the first ring (cross links are still drawn
    as edges). Unbounded, like before: the graph view zooms to fit.
    A generated "<Keyword> - Answers" roll-up hangs off its keyword note only
    (it links to every note it summarizes, which would tangle the picture).
    Returns (positions, parent of each note) so the view can tell tree lines
    from cross-links and move a whole branch."""
    if not notes:
        return {}, {}
    adj = {n: set() for n in notes}
    roll = ANSWERS_SUFFIX + ".md"
    for a, b in edges:
        if a in adj and b in adj and a != b and not (a.endswith(roll) or b.endswith(roll)):
            adj[a].add(b)
            adj[b].add(a)
    for n in notes:
        keyword = n[:-len(roll)] + ".md"
        if n.endswith(roll) and keyword in adj and keyword != n:
            adj[n].add(keyword)
            adj[keyword].add(n)
    root = pinned if pinned in adj else max(sorted(notes), key=lambda n: len(adj[n]))
    parent, depth, children, order = {root: None}, {root: 0}, {n: [] for n in notes}, [root]

    def grow(start):  # breadth-first, so a note sits as close to the center as its links allow
        queue = [start]
        for n in queue:
            for m in sorted(adj[n]):
                if m not in parent:
                    parent[m], depth[m] = n, depth[n] + 1
                    children[n].append(m)
                    queue.append(m)
                    order.append(m)
    grow(root)
    for n in sorted(notes):
        if n not in parent:
            parent[n], depth[n] = root, 1
            children[root].append(n)
            order.append(n)
            grow(n)
    leaves = {}
    for n in reversed(order):  # children are listed after their parent
        leaves[n] = sum(leaves[c] for c in children[n]) or 1
    # Ring spacing grows with the number of leaves so the outermost ring has room for them.
    step = max(140, leaves[root] * 70 / (2 * math.pi) / max(depth.values() or [1]) if len(order) > 1 else 140)
    cx, cy = width / 2, height / 2
    span = {root: (0.0, 2 * math.pi)}
    pos = {}
    for n in order:
        a0, a1 = span[n]
        mid = (a0 + a1) / 2
        r = depth[n] * step
        pos[n] = [cx + r * math.cos(mid), cy + r * math.sin(mid)]
        at = a0
        for c in children[n]:
            share = (a1 - a0) * leaves[c] / leaves[n]
            span[c] = (at, at + share)
            at += share
    return pos, parent


# -- Inbox: capture now, classify later with a click (no ::tag typing) --

def parse_inbox(vault=None):
    vault = vault or VAULT
    lines = read_note(INBOX_FILE, vault).splitlines()
    return [{"line": i, "text": m.group(1)}
            for i, line in enumerate(lines) if (m := INBOX_PENDING_RE.match(line))]


def _inbox_line(text):
    """'- text', with a leading checkbox like '[x]' escaped so the item
    isn't mistaken for a filed one or a task and hidden."""
    return f"- \\{text}" if re.match(r"\[[-xX ]\]", text) else f"- {text}"


def add_inbox_item(text, vault=None):
    vault = vault or VAULT
    path = os.path.join(vault, INBOX_FILE)
    with open(path, "a", encoding="utf-8", newline="\n") as f:
        f.write(_inbox_line(text) + "\n")


def _rewrite_inbox_line(item, new_line, vault=None):
    """False (nothing written) when that line no longer holds this item: the Inbox changed since it was listed."""
    vault = vault or VAULT
    lines, m = _matching_line(INBOX_FILE, item["line"], INBOX_PENDING_RE, 1, item["text"], vault)
    if not m:
        return False
    lines[item["line"]] = new_line
    write_note(INBOX_FILE, "\n".join(lines) + ("\n" if lines else ""), vault)
    return True


def edit_inbox_item(item, new_text, vault=None):
    """Replace a pending Inbox item's text. False (nothing written) if that
    line no longer holds this item."""
    vault = vault or VAULT
    return _rewrite_inbox_line(item, _inbox_line(new_text), vault)


def delete_inbox_item(item, vault=None):
    """Remove a pending Inbox item. False if the line changed."""
    vault = vault or VAULT
    lines, m = _matching_line(INBOX_FILE, item["line"], INBOX_PENDING_RE, 1, item["text"], vault)
    if not m:
        return False
    _delete_line(INBOX_FILE, lines, item["line"], vault)
    return True


def classify_as_task(item, due, vault=None):
    vault = vault or VAULT
    suffix = f" due:{due}" if due else ""
    return _rewrite_inbox_line(item, f"t {item['text']}{suffix}", vault)


def classify_as_event(item, event_date, event_time, vault=None):
    vault = vault or VAULT
    if not _rewrite_inbox_line(item, f"- [-] {item['text']}", vault):
        return False
    add_local_event(event_date, event_time, item["text"], vault)
    return True


def classify_as_note(item, vault=None):
    """Files the thought as its own note (title = its first ~60 safe chars,
    numbered if taken) and marks the Inbox line filed. Returns the filename."""
    vault = vault or VAULT
    text = item["text"]
    if not _matching_line(INBOX_FILE, item["line"], INBOX_PENDING_RE, 1, text, vault)[1]:
        return None  # the Inbox changed since it was listed: nothing made
    title = "".join(" " if c in BAD_TITLE_CHARS else c for c in text.splitlines()[0])
    title = " ".join(title.split())[:60].rstrip(". ") or "Thought"
    if title in (".", ".."):
        title = "Thought"
    name, n = title, 1
    while os.path.exists(os.path.join(vault, name + ".md")):
        n += 1
        name = f"{title} {n}"
    body = "- " + text if SHORTHAND_RE.match(text) else text  # keep 'i '/'c ' from re-filing on save
    write_note(name + ".md", blank_note_template(name) + body + "\n", vault)
    _rewrite_inbox_line(item, f"- [-] {text}", vault)
    return name + ".md"


# -- One-letter shorthand at the start of a line, in any note --

def expand_shorthand(text, today=None):
    """An old open task '- [ ] call bank' becomes 't call bank'; 'i idea' moves
    to the Inbox; 'c 10-05-2026 [2pm] dentist' moves to the Calendar. Lowercase only,
    so 'I think...' is left alone. Returns (new text, inbox texts, events as
    (iso date, time, title), problems); a 'c' line with a bad or past date
    stays in the note and is reported (a past event would never show)."""
    today = today or date.today()
    out, inbox, events, problems = [], [], [], []
    for line in text.split("\n"):
        if box := OPEN_BOX_RE.match(line):
            out.append(f"{box.group(1)}t {box.group(2)}")
            continue
        m = SHORTHAND_RE.match(line)
        if not m:
            out.append(concrete_due(line, today) if TASK_RE.match(line) and "due:" in line else line)
            continue
        kind, rest = m.groups()
        if kind == "i":
            inbox.append(rest)
        else:
            d, after = split_date(rest, today)  # 'c 10-05-2026 …', 'c fri 2pm …', 'c next tue …', 'c nov 5 …'
            ts, _, title = after.partition(" ")
            t = parse_time(ts) if title.strip() else None
            bad_time = t is None and bool(title.strip()) and re.fullmatch(r"\d{1,2}:\d{2}(?:\s?[ap]m)?", ts, re.I) is not None
            title = (title if t else after).strip()
            if d is None or not title:
                problems.append(f"'{line}': write it as c <date> [time] title (a date like 10-05-2026, fri or nov 5)")
            elif bad_time:  # looks like a time but isn't one: don't file it as part of the title
                problems.append(f"'{line}': '{ts}' isn't a time (e.g. 14:30 or 2:30pm)")
            elif d < today:
                problems.append(f"'{line}': {show_date(d)} is in the past")
            else:
                events.append((d.isoformat(), t, title))
                continue
            out.append(line)
    return "\n".join(out), inbox, events, problems


def write_note_with_shorthand(filename, text, vault=None, today=None):
    """write_note after expand_shorthand. Inbox/Calendar get their lines only
    once the note is written (else the next save would add them twice).
    Generated Answers notes are written as-is. Returns (written text, problems)."""
    vault = vault or VAULT
    if ANSWERS_MARK in text:
        write_note(filename, text, vault)
        return text, []
    text, inbox, events, problems = expand_shorthand(text, today)
    write_note(filename, text, vault)
    for item in inbox:
        add_inbox_item(item, vault)
    for d, t, title in events:
        add_local_event(d, t, title, vault)
    return text, problems


def expand_shorthand_in_vault(vault=None, today=None):
    """Same for every note (Inbox.md too: its filed tasks), catching ones
    edited outside the app or written in the old '- [ ]' format."""
    vault = vault or VAULT
    for n in list_notes(vault):
        text = read_note(n, vault)
        if any(SHORTHAND_RE.match(l) or OPEN_BOX_RE.match(l) for l in text.splitlines()):
            write_note_with_shorthand(n, text, vault, today)


# -- Calendar: local events + real ICS feed merged in one list --

def read_local_events(vault=None):
    vault = vault or VAULT
    events = []
    for i, line in enumerate(read_note(CALENDAR_FILE, vault).splitlines()):
        m = CAL_LINE_RE.match(line)
        if m:
            y, mo, d = map(int, m.group(1).split("-"))
            events.append({"date": date(y, mo, d), "time": m.group(2),
                            "title": m.group(3), "source": "local", "line": i})
    return events


def _event_line(event_date, event_time, title):
    return f"- {event_date}" + (f" {event_time}" if event_time else "") + f" {title}"


def add_local_event(event_date, event_time, title, vault=None):
    vault = vault or VAULT
    with open(os.path.join(vault, CALENDAR_FILE), "a", encoding="utf-8", newline="\n") as f:
        f.write(_event_line(event_date, event_time, title) + "\n")


def _event_still_there(event, lines):
    """Same stale-line guard as tasks: the line must still hold this event."""
    i = event["line"]
    return i < len(lines) and lines[i] == _event_line(event["date"].isoformat(), event["time"], event["title"])


def edit_local_event(event, event_date, event_time, title, vault=None):
    """Rewrite an event in place. False (nothing written) if its line changed."""
    vault = vault or VAULT
    lines = read_note(CALENDAR_FILE, vault).splitlines()
    if not _event_still_there(event, lines):
        return False
    lines[event["line"]] = _event_line(event_date, event_time, title)
    write_note(CALENDAR_FILE, "\n".join(lines) + "\n", vault)
    return True


def delete_local_event(event, vault=None):
    """False (nothing deleted) if the event's line changed."""
    vault = vault or VAULT
    lines = read_note(CALENDAR_FILE, vault).splitlines()
    if not _event_still_there(event, lines):
        return False
    _delete_line(CALENDAR_FILE, lines, event["line"], vault)
    return True


def parse_time(s):
    """'HH:MM' (24h, as files store it) from 14:30, 9:30, 2:30pm or 2pm;
    None if it isn't a time."""
    for fmt in ("%H:%M", "%I:%M%p", "%I%p"):
        try:
            return datetime.strptime(s.strip().replace(" ", "").upper(), fmt).strftime("%H:%M")
        except ValueError:
            pass
    return None


def _caldav_split(url):
    """(url without the login, Authorization header) for a link like
    https://user:app-password@host/dav/calendars/...; (url, None) for a plain feed."""
    p = urllib.parse.urlsplit(url)
    if not p.username:
        return url, None
    host = p.hostname + (f":{p.port}" if p.port else "")
    login = f"{urllib.parse.unquote(p.username)}:{urllib.parse.unquote(p.password or '')}"
    return (urllib.parse.urlunsplit((p.scheme, host, p.path, p.query, "")),
            "Basic " + base64.b64encode(login.encode()).decode())


def caldav_needs_login(url):
    """True for a CalDAV address pasted as the calendar shows it: https, a /dav/ path, no login yet."""
    p = urllib.parse.urlsplit(url.strip())
    return (p.scheme == "https" and not p.username and not p.path.lower().endswith(".ics")
            and ("/dav/" in p.path.lower() or "caldav" in (p.hostname or "")))


def caldav_with_login(url, password):
    """The address with the login added. The user name is the e-mail inside the path (Fastmail
    puts it there); shortcut: other servers that don't, take the full user:password@ form."""
    p = urllib.parse.urlsplit(url.strip())
    user = next((s for s in urllib.parse.unquote(p.path).split("/") if "@" in s), None)
    if not user:
        raise ValueError("No user name found in that address; paste it as https://user:app-password@host/path/")
    q = lambda s: urllib.parse.quote(s, safe="")
    return urllib.parse.urlunsplit((p.scheme, f"{q(user)}:{q(password)}@{p.netloc}", p.path, p.query, ""))


def _event_uid(e):
    # Derived from the line itself: no state needed to PUT it again, and an edit becomes delete + new.
    return "sb-" + hashlib.sha1(_event_line(e["date"].isoformat(), e["time"], e["title"]).encode()).hexdigest()[:20]


def _event_ics(uid, e):
    # shortcut: floating local time, 1 h long, no recurrence; add TZID/duration if events land off.
    if e["time"]:
        start = datetime.combine(e["date"], datetime.strptime(e["time"], "%H:%M").time())
        when = f"DTSTART:{start:%Y%m%dT%H%M%S}\r\nDTEND:{start + timedelta(hours=1):%Y%m%dT%H%M%S}"
    else:
        when = f"DTSTART;VALUE=DATE:{e['date']:%Y%m%d}\r\nDTEND;VALUE=DATE:{e['date'] + timedelta(days=1):%Y%m%d}"
    title = re.sub(r"([\\;,])", r"\\\1", e["title"])
    return ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//SimpleBrain//EN\r\nBEGIN:VEVENT\r\n"
            f"UID:{uid}\r\nDTSTAMP:{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}\r\n{when}\r\n"
            f"SUMMARY:{title}\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")


def caldav_sync(url, vault=None, timeout=8, today=None):
    """Two-way sync with a CalDAV calendar. Local events (Calendar.md) are pushed, edits and
    deletes included, then the calendar is pulled and returned as .ics text. Events SimpleBrain
    pushed are left out of the pull so they don't show twice; other events stay read-only here.
    Raises on any network error (the caller falls back to the cache)."""
    vault = vault or VAULT
    base, auth = _caldav_split(url)
    base = base.rstrip("/") + "/"

    def call(method, target, body=None, headers=None):
        req = urllib.request.Request(target, data=body.encode() if body else None, method=method,
                                     headers=headers or {})
        req.add_unredirected_header("Authorization", auth)  # never follows a redirect to another host
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")

    state = os.path.join(vault, ".caldav-pushed.json")  # a dotfile: sync never sends it, each device keeps its own
    try:
        with open(state, encoding="utf-8") as f:
            pushed = set(json.load(f))
    except (OSError, ValueError):
        pushed = set()
    local = {_event_uid(e): e for e in read_local_events(vault)}
    try:
        for uid in pushed - local.keys():
            try:
                call("DELETE", f"{base}{uid}.ics")
            except urllib.error.HTTPError as err:
                if err.code != 404:  # already gone is fine
                    raise
            pushed.discard(uid)
        for uid in local.keys() - pushed:
            call("PUT", f"{base}{uid}.ics", _event_ics(uid, local[uid]), {"Content-Type": "text/calendar"})
            pushed.add(uid)
    finally:  # keep what did get through, so a retry doesn't redo it
        with open(state, "w", encoding="utf-8", newline="\n") as f:
            json.dump(sorted(pushed), f)

    today = today or date.today()
    stamp = lambda d: (datetime.combine(d, datetime.min.time())).strftime("%Y%m%dT%H%M%SZ")
    xml = call("REPORT", base, (
        '<?xml version="1.0"?><c:calendar-query xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
        '<d:prop><c:calendar-data/></d:prop><c:filter><c:comp-filter name="VCALENDAR">'
        f'<c:comp-filter name="VEVENT"><c:time-range start="{stamp(today - timedelta(days=1))}" '
        f'end="{stamp(today + timedelta(days=121))}"/></c:comp-filter></c:comp-filter></c:filter></c:calendar-query>'),
        {"Depth": "1", "Content-Type": "application/xml"})
    parts = []
    for r in ElementTree.fromstring(xml).iter("{DAV:}response"):
        data = r.find(".//{urn:ietf:params:xml:ns:caldav}calendar-data")
        if data is not None and data.text and not (r.findtext("{DAV:}href") or "").rsplit("/", 1)[-1].startswith("sb-"):
            parts.append(data.text)
    return "\n".join(parts)


def fetch_ics(url=None, timeout=8, vault=None):
    """Returns (text, live) - live=False means a network/parse failure fell
    back to the cached copy (or no cache/URL exists), so the caller can show
    that to the user instead of silently passing off stale data as fresh."""
    vault = vault or VAULT
    cache = os.path.join(vault, ".calendar-cache.ics")
    url = url or get_ics_url(vault)
    if not url:
        path = resolve_calendar_file(vault)  # a connected file is always read fresh
        if not path:
            return None, False
        try:
            text = read_text_file(path)
            return (csv_to_ics(text) if path.lower().endswith(".csv") else text), True
        except (OSError, ValueError):
            return None, False  # moved or deleted: say "not reachable", don't show stale data
    try:
        if _caldav_split(url)[1]:
            text = caldav_sync(url, vault, timeout)
        else:
            with urllib.request.urlopen(url, timeout=timeout) as resp:
                text = resp.read().decode("utf-8", errors="replace")
        with open(cache, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        return text, True
    except Exception:
        if os.path.exists(cache):
            with open(cache, encoding="utf-8") as f:
                return f.read(), False
        return None, False


def upcoming_events(vault=None, days=14, ics_text=None, today=None):
    """Every local event from today on, however far out (one the user typed
    must never go invisible); the synced feed only for the next `days`, since
    a recurring feed event would otherwise flood the list."""
    vault = vault or VAULT
    today = today or date.today()
    events = [e for e in read_local_events(vault) if e["date"] >= today]
    if ics_text:
        cutoff = today + timedelta(days=days)
        events += [e for e in parse_ics(ics_text, window_days=days, today=today)
                   if today <= e["date"] <= cutoff]
    events.sort(key=lambda e: (e["date"], e["time"] or ""))
    return events


# ---------- self-update: the pieces simplebrain_update builds on ----------

REPO = "sebaytlabs/simplebrain"


def version_key(tag):
    return tuple(int(n) for n in re.findall(r"\d+", tag))


def update_available(tag, current=None):
    return bool(tag) and version_key(tag) > version_key(current or VERSION)


def install_update_from(image, dest=None):
    """Unpack a checked AppImage and swap its app folder into `dest` (install.sh's folder). "" on success,
    else why; `dest` is left untouched on any failure."""
    dest = dest or app_dir()
    work = tempfile.mkdtemp(prefix="simplebrain-update-", dir=os.path.dirname(dest))
    try:
        os.chmod(image, 0o755)
        r = subprocess.run([image, "--appimage-extract"], cwd=work, capture_output=True, text=True, timeout=300)
        new = os.path.join(work, "squashfs-root", "SimpleBrain")
        if r.returncode or not os.access(os.path.join(new, "SimpleBrain"), os.X_OK):
            return "could not unpack the download"
        old = dest + ".old"
        shutil.rmtree(old, ignore_errors=True)
        os.rename(dest, old)
        try:
            os.rename(new, dest)
        except OSError:
            os.rename(old, dest)  # keep the working install
            raise
        shutil.rmtree(old, ignore_errors=True)
        return ""
    except (OSError, subprocess.SubprocessError, ValueError) as e:
        return str(e)
    finally:
        shutil.rmtree(work, ignore_errors=True)


# ---------- citations: give a title or a web address, get a formatted reference ----------

def _initials(given):
    return " ".join(p[0].upper() + "." for p in re.split(r"[\s.]+", given) if p)


def _authors(names):
    """APA-style 'Smith, J. A., Lee, K., & Park, R.' from (family, given) pairs."""
    out = [f"{fam}, {_initials(giv)}".rstrip(", ") for fam, giv in names if fam]
    return ", ".join(out[:-1]) + (", & " if len(out) > 1 else "") + out[-1] if out else ""


def format_crossref(msg):
    year = ((msg.get("issued", {}).get("date-parts") or [[None]])[0] or [None])[0]
    who = _authors([(a.get("family", a.get("name", "")), a.get("given", "")) for a in msg.get("author", [])])
    journal = html.unescape((msg.get("container-title") or [""])[0])
    where = f"*{journal}*" if journal else ""
    if msg.get("volume"):
        where += f", {msg['volume']}" + (f"({msg['issue']})" if msg.get("issue") else "")
    if msg.get("page"):
        where += f", {msg['page']}"
    title = html.unescape((msg.get("title") or [""])[0]).strip().rstrip(".")
    return " ".join(p for p in [who, f"({year or 'n.d.'}).", f"{title}.", where + "." if where else "",
                                f"https://doi.org/{msg['DOI']}"] if p)


def format_openlibrary(doc):
    names = [(w[-1], " ".join(w[:-1])) for a in doc.get("author_name", []) if (w := a.split())]
    pub = (doc.get("publisher") or [""])[0]
    return " ".join(p for p in [_authors(names), f"({doc.get('first_publish_year') or 'n.d.'}).",
                                f"*{html.unescape(doc.get('title', '')).strip()}*.", f"{pub}." if pub else ""] if p)


def format_web(page, url, today=None):
    meta = {}
    for tag in re.findall(r"<meta\b[^>]*>", page, re.I):
        a = {k.lower(): html.unescape(v) for k, _, v in re.findall(r"""([\w:-]+)\s*=\s*(["'])(.*?)\2""", tag)}
        if key := a.get("property") or a.get("name"):
            meta.setdefault(key.lower(), a.get("content", ""))
    m = re.search(r"<title[^>]*>(.*?)</title>", page, re.S | re.I)
    host = urllib.parse.urlsplit(url).hostname or url
    title = " ".join((meta.get("og:title") or (html.unescape(m.group(1)) if m else "")).split()) or host
    who = meta.get("author") or ""
    who = "" if who.startswith("http") else who.strip()
    year = re.match(r"\d{4}", meta.get("article:published_time") or meta.get("date") or meta.get("pubdate") or "")
    when = f"({year.group() if year else 'n.d.'})"
    title = title.rstrip(".")
    lead = f"{who}. {when}. {title}." if who else f"{title}. {when}."
    today = today or date.today()
    return f"{lead} {meta.get('og:site_name') or host}. {url} (accessed {today.strftime('%B')} {today.day}, {today.year})"


def format_youtube(info, url):
    return f"{info.get('author_name', 'Unknown channel')}. (n.d.). *{info.get('title', '').strip()}* [Video]. YouTube. {url}"


def _get(url, timeout, limit=400_000):
    req = urllib.request.Request(url, headers={"User-Agent": "SimpleBrain-citations/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(limit).decode("utf-8", errors="replace")


def rank_by_title(query, items):
    """Source records, closest title to the query first; ties go to records that name an author."""
    def key(x):
        t = x.get("title") or ""
        t = t[0] if isinstance(t, list) else t
        return (-difflib.SequenceMatcher(None, query.lower(), html.unescape(t).lower()).ratio(),
                not (x.get("author") or x.get("author_name")))
    return sorted(items, key=key)


def find_sources(query, timeout=15):
    """Candidate reference lines for a web address (one) or an article/book title (up to a few,
    for the user to choose from). Raises ValueError with a plain-English reason."""
    q = query.strip()
    try:
        if re.match(r"https?://", q, re.I):  # not file:// - urlopen would read local files
            if (urllib.parse.urlsplit(q).hostname or "").removeprefix("www.").removeprefix("m.") in ("youtube.com", "youtu.be"):
                info = json.loads(_get("https://www.youtube.com/oembed?format=json&url=" + urllib.parse.quote(q, safe=""), timeout))
                return [format_youtube(info, q)]
            return [format_web(_get(q, timeout), q)]
        if not q or re.match(r"[a-z][a-z0-9+.-]*://", q, re.I):
            raise ValueError("Type an article or book title, or paste a web address starting with http.")
        found, errors = [], []
        # Ask for more than shown, then put the closest titles first (the sources' own order often isn't).
        for url, pick, fmt in (
            ("https://api.crossref.org/works?rows=12&select=DOI,title,author,issued,container-title,volume,issue,page&query.title="
             + urllib.parse.quote(q), lambda d: d["message"]["items"], format_crossref),
            ("https://openlibrary.org/search.json?limit=12&fields=title,author_name,first_publish_year,publisher&title="
             + urllib.parse.quote(q), lambda d: d["docs"], format_openlibrary),
        ):
            try:
                found.append([fmt(x) for x in rank_by_title(q, pick(json.loads(_get(url, timeout))))[:4]])
            except Exception as e:
                errors.append(e)
        if len(errors) == 2:
            raise ValueError(_lookup_error(errors[0]))
        out = list(dict.fromkeys(c for row in itertools.zip_longest(*found) for c in row if c))  # alternate articles/books
        if not out:
            raise ValueError("No article or book found with that title.")
        return out
    except ValueError:
        raise
    except Exception as e:  # offline, page not found, timeout
        raise ValueError(_lookup_error(e)) from e


def _lookup_error(e):
    """What the user reads when a source lookup fails: no library error text."""
    if isinstance(e, urllib.error.HTTPError):
        return f"The site answered with an error ({e.code}). Check the address and try again."
    if isinstance(e, (urllib.error.URLError, OSError)):
        return "Couldn't connect. Check your internet connection and try again."
    return f"Could not look that up ({e})."


# ---------- self-test (no UI/network needed) ----------

def selftest():
    with tempfile.TemporaryDirectory() as d:  # Windows' sharing lock is waited out; a real refusal still raises
        a, b = os.path.join(d, "a"), os.path.join(d, "b")
        open(a, "w").close()
        replace_retrying(a, b)
        assert os.path.exists(b) and not os.path.exists(a)
        try:
            replace_retrying(a, b)
            raise AssertionError("a missing file was swapped in")
        except FileNotFoundError:
            pass
    with tempfile.TemporaryDirectory() as d:  # a repeating task: done today, back on its next day
        write_note("Habits.md", "t Python module every:day due:2026-11-02\nt run every:weekday due:2026-11-06\nt once due:2026-11-02\n", d)
        ts = {t["text"].split(" every")[0].split(" due")[0]: t for t in parse_tasks(d)}
        assert toggle_task(ts["Python module"], d, today=date(2026, 11, 4)) == date(2026, 11, 5)  # overdue: from today
        assert toggle_task(ts["run"], d, today=date(2026, 11, 6)) == date(2026, 11, 9)  # Friday -> Monday
        assert toggle_task(ts["once"], d, today=date(2026, 11, 2)) is None
        text = read_note("Habits.md", d)
        assert "t Python module every:day due:2026-11-05" in text and "- [x] once" in text
        assert next_due("mon", date(2026, 11, 2)) == date(2026, 11, 9) and next_due("month", date(2026, 1, 31)) == date(2026, 2, 28)
    assert parse_tags("#real `#example` x\n```dataview\nLIST FROM #project\n```\n#also") == ["also", "real"]
    assert parse_tags(HOME_GUIDE) == []  # the guide's `#tag` example doesn't tag Home
    with tempfile.TemporaryDirectory() as d:  # setting lines may sit in Home or in a note called Settings
        ensure_vault(d)
        write_note("Settings.md", "# Settings\nlimit:: 3h\n", d)
        assert "limit:: 3h" in settings_text(d) and "# Home" in settings_text(d)
    assert parse_links(HOME_GUIDE) == [] and not SHORTHAND_RE.search(HOME_GUIDE)  # the guide itself files nothing
    with tempfile.TemporaryDirectory() as d:  # an untouched old starter Home is upgraded; an edited one never is
        write_note("Home.md", OLD_HOME_GUIDES[0], d)
        ensure_vault(d)
        assert read_note("Home.md", d) == HOME_GUIDE
        first = next(g for g in OLD_HOME_GUIDES if "a synced calendar feed if you set one" in g)
        write_note("Home.md", first.replace("\n", "  \n") + "\n\n", d)  # the first release's, with stray spaces
        ensure_vault(d)
        assert read_note("Home.md", d) == HOME_GUIDE
        assert any("a synced calendar feed if you set one in `.config`" in g for g in OLD_HOME_GUIDES)
        write_note("Home.md", OLD_HOME_GUIDES[1] + "my line\n", d)
        ensure_vault(d)
        assert read_note("Home.md", d).endswith("my line\n")
    sun = date(2026, 11, 1)  # a Sunday
    nd = lambda x: natural_date(x, sun)
    assert nd("today") == sun and nd("Tomorrow") == date(2026, 11, 2) and nd("fri") == date(2026, 11, 6)
    assert nd("friday") == nd("Fri.") == date(2026, 11, 6) and nd("next fri") == date(2026, 11, 13)
    assert nd("sun") == sun and nd("next sunday") == date(2026, 11, 8) and nd("thur") == date(2026, 11, 5)
    assert nd("in 3 days") == date(2026, 11, 4) and nd("in 2 weeks") == date(2026, 11, 15)
    assert nd("nov 5") == nd("5 november") == nd("11-5") == nd("11/5") == date(2026, 11, 5)
    assert nd("oct 3") == date(2027, 10, 3) and nd("dec 31st") == date(2026, 12, 31)  # passed: next year
    assert nd("fr") is None and nd("call") is None and nd("2 apples") is None and nd("13-40") is None and nd("feb 30") is None
    assert split_date("next fri 2pm dentist", sun) == (date(2026, 11, 13), "2pm dentist")
    assert split_date("11-20-2026 Conference", sun) == (date(2026, 11, 20), "Conference")
    assert split_date("dentist", sun) == (None, "dentist")
    assert trailing_date("call the bank fri", sun) == ("call the bank", date(2026, 11, 6))
    assert trailing_date("pay rent due:12-01-2026", sun) == ("pay rent", date(2026, 12, 1))
    assert trailing_date("read chapter 5", sun) == ("read chapter 5", None)
    assert trailing_date("call mom next sunday", sun) == ("call mom", date(2026, 11, 8))
    assert concrete_due("t call bank due:fri", sun) == "t call bank due:2026-11-06"
    assert concrete_due("t x due:next-mon", sun) == "t x due:2026-11-09" and concrete_due("t x due:11-5", sun) == "t x due:2026-11-05"
    assert concrete_due("t x due:11-05-2026", sun) == "t x due:11-05-2026"  # a full date is left as typed
    text, _, events, problems = expand_shorthand("c fri 2pm dentist\nt call bank due:tomorrow\nc nov 3 Cafe orientation", sun)
    assert events == [("2026-11-06", "14:00", "dentist"), ("2026-11-03", None, "Cafe orientation")] and not problems
    assert text == "t call bank due:2026-11-02"
    assert parse_tags("#work x\nfile:: /v/Lesson #10-a.mp4\nsee https://x.org/#top #later") == ["later", "work"]
    assert parse_files("x\n  file:: /a/b c.pdf \nfile::~/n.txt\nnot file:: z\n") == ["/a/b c.pdf", "~/n.txt"]
    v, o = os.path.abspath("v"), os.path.abspath("o")
    assert file_line(os.path.join(v, "sub", "a.pdf"), v) == "file:: sub/a.pdf" and file_line(os.path.join(o, "a.pdf"), v) == "file:: " + os.path.join(o, "a.pdf")
    assert resolve_file("sub/a.pdf", v) == os.path.join(v, "sub/a.pdf") and resolve_file(os.path.join(o, "a.pdf"), v) == os.path.join(o, "a.pdf")
    assert format_crossref({"DOI": "10.1/x", "author": [{"family": "Smith", "given": "Jane Ann"}, {"family": "Lee", "given": "Kim"}], "title": ["Sleep and memory"],
                            "issued": {"date-parts": [[2019, 3]]}, "container-title": ["Nature"], "volume": "5", "issue": "2", "page": "10-20"}) \
        == "Smith, J. A., & Lee, K. (2019). Sleep and memory. *Nature*, 5(2), 10-20. https://doi.org/10.1/x"
    ranked = rank_by_title("Thinking, Fast and Slow", [{"title": "Study guide for Thinking, Fast and Slow: a long subtitle"},
             {"title": "Thinking, Fast and Slow", "author_name": ["D. Kahneman"]}, {"title": "Fast and Slow Thinking"}])
    assert [x["title"] for x in ranked][0] == "Thinking, Fast and Slow"
    assert format_crossref({"DOI": "10.1/y", "title": ["Untitled study"]}) == "(n.d.). Untitled study. https://doi.org/10.1/y"
    assert format_openlibrary({"title": "Atomic Habits", "author_name": ["James Clear"], "first_publish_year": 2018, "publisher": ["Avery"]}) \
        == "Clear, J. (2018). *Atomic Habits*. Avery."
    page = '<meta property="og:title" content="Sleep &amp; you"><meta name="author" content="Ann Lee"><meta property="article:published_time" content="2021-05-02T10:00"><title>x</title>'
    assert format_web(page, "https://x.org/p", date(2026, 10, 15)) == "Ann Lee. (2021). Sleep & you. x.org. https://x.org/p (accessed October 15, 2026)"
    assert format_web("<title>Plain\n page</title>", "https://x.org/p", date(2026, 10, 15)) == "Plain page. (n.d.). x.org. https://x.org/p (accessed October 15, 2026)"
    assert format_youtube({"title": "How sleep works", "author_name": "SciShow"}, "https://youtu.be/a") == "SciShow. (n.d.). *How sleep works* [Video]. YouTube. https://youtu.be/a"
    for bad in ("", "file:///etc/passwd"):
        try:
            find_sources(bad)
            raise AssertionError(bad)
        except ValueError:
            pass
    with tempfile.TemporaryDirectory() as d:  # broken links, and rename rewriting every link to the note
        write_note("Home.md", "# Home\n[[Plan]] [[Inbox]] [[Typo]]\n", d)
        write_note("Plan.md", "# Plan\nsee [[ Plan ]] and [[Other]] and [[Plan]]\nt call\n", d)
        write_note("Other.md", "# Other\n[[Plan]] [[Plan B]]\n", d)
        write_note("Plan - Answers.md", ANSWERS_MARK + "\n", d)
        write_note(INBOX_FILE, "- look at [[Plan]]\n", d)
        write_note(CALENDAR_FILE, "- 2099-01-01 review [[Plan]]\n", d)
        assert broken_links(d) == {"Plan B": ["Other.md"], "Typo": ["Home.md"]}  # Inbox is a panel; a blank-padded link counts as Plan
        set_public("Plan.md", True, d)
        set_graph_icon("Plan.md", emoji="*", vault=d)
        assert rename_note("Plan.md", "Roadmap", d) == ("Roadmap.md", 4)  # Home, Other, Inbox and Calendar changed; the note itself is not counted
        assert not os.path.exists(os.path.join(d, "Plan.md"))
        assert read_note("Roadmap.md", d) == "# Plan\nsee [[Roadmap]] and [[Other]] and [[Roadmap]]\nt call\n"  # its own links follow too, padding and all
        assert "[[Roadmap]] [[Inbox]] [[Typo]]" in read_note("Home.md", d) and "[[Roadmap]] [[Plan B]]" in read_note("Other.md", d)
        assert "[[Roadmap]]" in read_note(INBOX_FILE, d) and "[[Roadmap]]" in read_note(CALENDAR_FILE, d)
        assert public_notes(d) == ["Roadmap.md"] and list(graph_icons(d)) == ["Roadmap.md"]  # the website tick and the graph icon stay with it
        assert "Plan" not in broken_links(d) and broken_links(d)["Plan B"] == ["Other.md"]
        for old, new, why in (("Roadmap.md", "Other", "already"), ("Roadmap.md", "other", "already"),  # capitals alone don't make a different note (other systems would clash)
                              ("Roadmap.md", "a/b", "can't"), ("Roadmap.md", "  ", "can't"), ("Roadmap.md", "Inbox", "uses itself"),
                              ("Roadmap.md", "X - Answers", "uses itself"), ("Home.md", "Start", "manages"), ("Plan - Answers.md", "Mine", "manages"),
                              (INBOX_FILE, "Todo", "manages")):
            before = sorted(os.listdir(d))
            try:
                rename_note(old, new, d)
                raise AssertionError(new)
            except ValueError as e:
                assert why in str(e), (new, str(e))
            assert sorted(os.listdir(d)) == before  # a refused name changes nothing
        assert rename_note("Roadmap.md", "Roadmap", d) == ("Roadmap.md", 0)
        assert rename_note("Roadmap.md", "roadmap", d)[0] == "roadmap.md"  # changing only the capitals is fine
    with tempfile.TemporaryDirectory() as d:  # saving is all-or-nothing
        write_note("N.md", "old\n", d)
        write_note("N.md", "new\n", d)
        assert read_note("N.md", d) == "new\n" and os.listdir(d) == ["N.md"]  # no side file left behind
        if os.name == "posix":
            um = os.umask(0o022)
            os.umask(um)
            assert os.stat(os.path.join(d, "N.md")).st_mode & 0o777 == 0o666 & ~um  # an ordinary save's permissions
        real_replace, os.replace = os.replace, lambda *a: (_ for _ in ()).throw(OSError("disk went away"))
        try:
            write_note("N.md", "half", d)
            raise AssertionError("a failed swap must raise")
        except OSError:
            pass
        finally:
            os.replace = real_replace
        assert read_note("N.md", d) == "new\n" and os.listdir(d) == ["N.md"]  # the old text survives, the side file is cleaned up
    with tempfile.TemporaryDirectory() as d:  # found by stress testing: odd files must not take the app down
        with open(os.path.join(d, "Old.md"), "wb") as f:
            f.write("caf\xe9\r\nline2".encode("latin-1"))
        assert read_note("Old.md", d) == "café\nline2"  # a Windows-1252 note opens; it isn't a crash
        assert not is_safe_note_title("a\x00b") and not is_safe_note_title("tab\there") and is_safe_note_title("日本語 😀")
        assert not is_safe_note_title("x" * 201) and is_safe_note_title("x" * 200)
        ics = ("BEGIN:VEVENT\nDTSTART:20261225T1900\nSUMMARY:odd\nEND:VEVENT\nBEGIN:VEVENT\nDTSTART:20261226\nSUMMARY:fine\nEND:VEVENT\n")
        assert [e["title"] for e in parse_ics(ics, today=date(2026, 12, 20))] == ["fine"]
        busy = "BEGIN:VEVENT\nDTSTART:20200101T000000Z\nRRULE:FREQ=SECONDLY\nSUMMARY:busy\nEND:VEVENT\n"
        t0 = time.time()
        parse_ics(busy, today=date(2026, 12, 20))
        assert time.time() - t0 < 5  # a per-second recurrence must not freeze the app  # one odd event doesn't blank the feed
    assert update_available("v0.10.0", "0.9.1") and not update_available("v0.2.0", "0.2.0") and not update_available(None)
    if os.name == "posix":  # the fake AppImage is a shell script
        with tempfile.TemporaryDirectory() as d:  # install_update_from: a checked download swapped in, the old one gone
            image = "#!/bin/sh\nmkdir -p squashfs-root/SimpleBrain && echo '#!/bin/sh' > squashfs-root/SimpleBrain/SimpleBrain && chmod +x squashfs-root/SimpleBrain/SimpleBrain\n"
            os.makedirs(os.path.join(d, "app"))
            with open(os.path.join(d, "img"), "w") as f:
                f.write(image)
            assert install_update_from(os.path.join(d, "img"), os.path.join(d, "app")) == ""
            assert os.access(os.path.join(d, "app", "SimpleBrain"), os.X_OK)
            assert not os.path.exists(os.path.join(d, "app.old"))
    assert natural_date("tom") is None and trailing_date("call Tom", date(2026, 11, 9)) == ("call Tom", None)
    assert natural_date("tmrw", date(2026, 11, 9)) == date(2026, 11, 10)
    assert parse_links("[[Note|shown]] [[Other#Part]] [[#here]] [[ Plain ]]") == ["Note", "Other", "Plain"]
    with tempfile.TemporaryDirectory() as d:  # a rename keeps each link's shown text and heading; a stale tick or filing does nothing
        write_note("Old.md", "# Old\n", d)
        write_note("Uses.md", "[[Old]] [[Old|the old one]] [[Old#Part]] [[Older]]\nt first\n", d)
        write_note(INBOX_FILE, "- one\n- two\n", d)
        assert rename_note("Old.md", "New", d) == ("New.md", 1)
        assert read_note("Uses.md", d).startswith("[[New]] [[New|the old one]] [[New#Part]] [[Older]]")
        stale = parse_tasks(d)[0]
        write_note("Uses.md", "a new first line\n" + read_note("Uses.md", d), d)
        assert toggle_task(stale, d) is None and "t first" in read_note("Uses.md", d)
        item = parse_inbox(d)[1]
        write_note(INBOX_FILE, "- two\n", d)  # 'one' was filed elsewhere: line 1 is gone
        assert classify_as_task(item, None, d) is False and classify_as_note(item, d) is None
        assert classify_as_event(item, "2026-12-01", None, d) is False and read_note(INBOX_FILE, d) == "- two\n"
        assert classify_as_task(parse_inbox(d)[0], None, d) is True and read_note(INBOX_FILE, d) == "t two\n"
    with tempfile.TemporaryDirectory() as d:
        write_note("A.md", "# A\n\nSee [[B]]. #work\n\n- [ ] write intro due:2020-01-01\n", d)
        write_note("B.md", "# B\n\nBack to [[A]]. #personal\n\n- [x] done thing\n- [ ] no date task\n", d)
        write_note(INBOX_FILE, "", d)
        write_note(CALENDAR_FILE, "", d)

        assert backlinks("A.md", d) == ["B.md"] and backlinks("B.md", d) == ["A.md"]
        write_note(INBOX_FILE, "- [ ] see [[A]]\n", d)
        assert backlinks("A.md", d) == ["B.md"]  # the Inbox file isn't a note
        assert list_user_notes(d) == ["A.md", "B.md"]
        assert any(t["file"] == INBOX_FILE for t in parse_tasks(d))  # its tasks still count
        write_note(INBOX_FILE, "", d)

        notes, edges, missing = build_graph(d)
        assert missing == set()
        assert {"A.md", "B.md"} <= set(notes)
        assert edges == [("A.md", "B.md")], edges

        tasks = parse_tasks(d)
        assert len(tasks) == 3
        buckets = bucket_tasks(tasks, today=date(2024, 1, 1))
        assert len(buckets["Overdue"]) == 1
        assert len(buckets["No date"]) == 1
        assert sum(len(v) for v in buckets.values()) == 2

        undone = [t for t in tasks if not t["done"] and t["due"] is not None][0]
        toggle_task(undone, d)
        assert parse_tasks(d)[0]["done"] is True

        pos, _ = mindmap_layout(notes, edges, 400, 300)
        assert set(pos) == set(notes)
        pos, _ = mindmap_layout(notes, edges, 400, 300, pinned="B.md")
        assert pos["B.md"] == [200, 150]
        assert mindmap_layout(notes, edges, 400, 300, pinned="B.md")[0] == pos  # same links, same picture
        # a big vault spreads out instead of piling into the box, and no two dots land on each other
        many = [f"n{i}.md" for i in range(80)]
        pos, _ = mindmap_layout(many, [(many[0], m) for m in many[1:]], 200, 150, pinned=many[0])
        assert max(x for x, _ in pos.values()) - min(x for x, _ in pos.values()) > 400
        pts = list(pos.values())
        assert all(math.dist(p, q) >= 12 for i, p in enumerate(pts) for q in pts[i + 1:])
        # a branch sits on the next ring out from its parent; an unlinked note still gets a spot
        tree = ["h.md", "a.md", "b.md", "a1.md", "lone.md"]
        pos, up = mindmap_layout(tree, [("h.md", "a.md"), ("h.md", "b.md"), ("a.md", "a1.md")], 0, 0, pinned="h.md")
        ring = lambda n: math.dist(pos[n], pos["h.md"])
        assert ring("h.md") == 0 and abs(ring("a.md") - ring("b.md")) < 1e-6 < ring("a1.md") and "lone.md" in pos
        assert up["a1.md"] == "a.md" and up["h.md"] is None
        # a generated Answers note hangs off its keyword; its many links don't pull it elsewhere
        rolls = ["Home.md", "A.md", "B.md", "Home - Answers.md"]
        _, up = mindmap_layout(rolls, [("A.md", "Home.md"), ("B.md", "Home.md"), ("Home - Answers.md", "A.md"),
                                       ("Home - Answers.md", "B.md"), ("Home - Answers.md", "Home.md")],
                               0, 0, pinned="Home.md")
        assert up["Home - Answers.md"] == "Home.md"

        # local graph: only what is related to the open note; hubs are shown but never bridged through
        gn = ["Home.md", "A.md", "B.md", "C.md", "D.md", "E.md", "Kw.md", "Far.md", "Lone.md"]
        ge = [("A.md", "Home.md"), ("B.md", "Home.md"), ("C.md", "Home.md"), ("D.md", "Home.md"),
              ("E.md", "Home.md"), ("A.md", "Kw.md"), ("B.md", "Kw.md"), ("C.md", "Far.md")]
        n_, e_ = local_graph(gn, ge, "A.md")
        # A: Home and Kw directly, B via the shared keyword; C/D/E only meet A through Home: hidden
        assert n_ == ["Home.md", "A.md", "B.md", "Kw.md"], n_
        assert e_ == [("A.md", "Home.md"), ("B.md", "Home.md"), ("A.md", "Kw.md"), ("B.md", "Kw.md")], e_
        assert local_graph(gn, ge, "A.md", depth=1)[0] == ["Home.md", "A.md", "Kw.md"]
        assert local_graph(gn, ge, "Home.md")[0] == ["Home.md", "A.md", "B.md", "C.md", "D.md", "E.md"]  # hub: direct only
        assert local_graph(gn, ge, "Lone.md")[0] == ["Lone.md"]  # unconnected note: just itself
        assert local_graph(gn, ge, "Nope.md") == (gn, ge)  # center not in the graph: everything
        assert local_graph(gn, ge, "C.md")[0] == ["Home.md", "C.md", "Far.md"]  # Far is 1 hop; Home isn't bridged
        # an Answers roll-up links everything it summarizes and must not bridge either
        rn = ["X.md", "Y.md", "Z.md", "Kw - Answers.md"]
        re_ = [("X.md", "Kw - Answers.md"), ("Y.md", "Kw - Answers.md"), ("Z.md", "Kw - Answers.md")]
        assert local_graph(rn, re_, "X.md")[0] == ["X.md", "Kw - Answers.md"]

        # inbox capture + one-click classify
        add_inbox_item("call the bank", d)
        add_inbox_item("flight to Vegas", d)
        pending = parse_inbox(d)
        assert [p["text"] for p in pending] == ["call the bank", "flight to Vegas"]

        # edit an inbox item in place; a stale item (text changed) is refused
        assert edit_inbox_item(pending[0], "call the bank re: card", d) is True
        assert edit_inbox_item(pending[0], "overwrite", d) is False
        pending = parse_inbox(d)
        assert [p["text"] for p in pending] == ["call the bank re: card", "flight to Vegas"]
        assert edit_inbox_item({"line": 99, "text": "x"}, "y", d) is False

        # delete an inbox item: gone from Inbox, logged in .trash, stale refused
        add_inbox_item("junk", d)
        junk = parse_inbox(d)[2]
        assert delete_inbox_item(junk, d) is True
        assert delete_inbox_item(junk, d) is False
        assert [p["text"] for p in parse_inbox(d)] == ["call the bank re: card", "flight to Vegas"]
        assert "- junk  <!-- from Inbox.md" in open(os.path.join(d, ".trash", DELETED_ITEMS)).read()

        classify_as_task(pending[0], "2026-05-01", d)
        assert parse_inbox(d) == [{"line": 1, "text": "flight to Vegas"}]
        assert any(t["text"].startswith("call the bank") and t["due"] == date(2026, 5, 1)
                   for t in parse_tasks(d))

        # text starting with "[" stays in the Inbox; a literal checkbox is escaped
        n_tasks = len(parse_tasks(d))
        add_inbox_item("[link] idea", d)
        add_inbox_item("[x] not a task", d)
        extra = parse_inbox(d)[1:]
        assert [p["text"] for p in extra] == ["[link] idea", "\\[x] not a task"]
        assert len(parse_tasks(d)) == n_tasks
        for p in reversed(extra):
            assert delete_inbox_item(p, d) is True
        assert parse_inbox(d) == [{"line": 1, "text": "flight to Vegas"}]

        # edit a task: text and due date change, checkbox state is kept
        t = next(t for t in parse_tasks(d) if t["text"].startswith("call the bank"))
        assert edit_task(t, "call the bank due:2026-05-03", d) is True
        assert edit_task(t, "stale overwrite", d) is False
        t2 = next(t for t in parse_tasks(d) if t["file"] == INBOX_FILE)
        assert t2["text"] == "call the bank due:2026-05-03" and t2["due"] == date(2026, 5, 3)
        assert t2["done"] is False and t2["line"] == t["line"]
        done = next(t for t in parse_tasks(d) if t["done"])
        assert edit_task(done, "done thing, renamed", d) is True
        assert "- [x] done thing, renamed" in read_note(done["file"], d)

        # delete a task: line removed from its note, others untouched, logged
        before = read_note("B.md", d).splitlines()
        nodate = next(t for t in parse_tasks(d) if t["text"] == "no date task")
        assert delete_task(nodate, d) is True
        assert read_note("B.md", d).splitlines() == [l for l in before if l != "- [ ] no date task"]
        assert delete_task(nodate, d) is False
        assert "- [ ] no date task  <!-- from B.md" in open(os.path.join(d, ".trash", DELETED_ITEMS)).read()

        classify_as_event(pending[1], "2026-06-01", "14:00", d)
        assert parse_inbox(d) == []
        local = read_local_events(d)
        assert local == [{"date": date(2026, 6, 1), "time": "14:00",
                           "title": "flight to Vegas", "source": "local", "line": 0}]

        # local events show however far out; past ones and far-off feed events don't
        add_local_event("2026-05-31", None, "yesterday", d)
        ics = "BEGIN:VEVENT\nSUMMARY:Far feed\nDTSTART;VALUE=DATE:20261201\nEND:VEVENT\n"
        shown = upcoming_events(d, ics_text=ics, today=date(2026, 6, 1))
        assert [e["title"] for e in shown] == ["flight to Vegas"]
        shown = upcoming_events(d, today=date(2026, 1, 1))
        assert [e["title"] for e in shown] == ["yesterday", "flight to Vegas"]
        delete_local_event(read_local_events(d)[1], d)
        local = read_local_events(d)

        # edit an event: date/time/title rewritten in place; stale edit refused
        assert edit_local_event(local[0], "2026-06-02", None, "flight to Vegas (moved)", d) is True
        assert edit_local_event(local[0], "2026-06-03", None, "stale", d) is False
        moved = read_local_events(d)
        assert moved == [{"date": date(2026, 6, 2), "time": None, "title": "flight to Vegas (moved)",
                          "source": "local", "line": 0}]
        assert delete_local_event(local[0], d) is False  # stale: refuses to delete
        assert parse_time("9:30") == "09:30" and parse_time("2:30 pm") == "14:30" and parse_time("2pm") == "14:00"
        assert parse_time("25:00") is None and parse_time("soon") is None

        assert delete_local_event(moved[0], d) is True
        assert read_local_events(d) == []

        # connecting an external calendar: stored in .config, other lines kept, bad schemes refused
        assert get_ics_url(d) is None
        assert set_ics_url("webcal://cal.example/x.ics", d) == "https://cal.example/x.ics"
        assert get_ics_url(d) == "https://cal.example/x.ics"
        for bad in ("file:///etc/passwd", "ftp://x/y.ics", "not a url"):
            try:
                set_ics_url(bad, d)
                raise AssertionError(bad)
            except ValueError:
                pass
        assert get_ics_url(d) == "https://cal.example/x.ics"  # refused input changes nothing
        assert set_ics_url("", d) is None and get_ics_url(d) is None

        # thought/note classification creates its own note and files the Inbox line
        add_inbox_item("random thought", d)
        item = parse_inbox(d)[0]
        assert classify_as_note(item, d) == "random thought.md"
        assert parse_inbox(d) == []
        assert "random thought" in read_note("random thought.md", d)
        add_inbox_item("random thought", d)
        assert classify_as_note(parse_inbox(d)[0], d) == "random thought 2.md"  # no overwrite
        add_inbox_item('what/why? i:x', d)
        assert classify_as_note(parse_inbox(d)[0], d) == "what why i x.md"  # unsafe chars out

        # shorthand: t → task in place, i → Inbox, c → Calendar; bad/past c stays
        today = date(2026, 10, 1)
        note = ("I think t\nt call bank due:10-05-2026\ni idea\nc 10-05-2026 2pm dentist\n"
                "c 10-06-2026 lunch\nc 13-01-2026 x\nc 09-01-2026 old\n")
        new, inbox, events, problems = expand_shorthand(note, today)
        assert new == ("I think t\nt call bank due:10-05-2026\nc 13-01-2026 x\nc 09-01-2026 old\n")
        assert expand_shorthand("- [ ] old\n  - [ ] sub\n- [x] done\n- [ ]\n")[0] == "t old\n  t sub\n- [x] done\n- [ ]\n"
        assert inbox == ["idea"] and events == [("2026-10-05", "14:00", "dentist"), ("2026-10-06", None, "lunch")]
        assert len(problems) == 2 and "past" in problems[1]
        write_note("S.md", "i from outside\nc 10-05-2026 trip\n- [ ] old task\n", d)
        expand_shorthand_in_vault(d, today)
        assert read_note("S.md", d) == "t old task\n"
        s_task = next(t for t in parse_tasks(d) if t["file"] == "S.md")
        assert s_task["text"] == "old task" and not s_task["done"]
        toggle_task(s_task, d)
        assert read_note("S.md", d) == "- [x] old task\n"
        toggle_task(next(t for t in parse_tasks(d) if t["file"] == "S.md"), d)
        assert read_note("S.md", d) == "t old task\n" and parse_inbox(d)[-1]["text"] == "from outside"
        assert read_local_events(d)[-1]["title"] == "trip"
        assert write_note_with_shorthand("S.md", ANSWERS_MARK + "\nt x\n", d)[0].endswith("\nt x\n")
        os.remove(os.path.join(d, "S.md"))
        write_note(INBOX_FILE, "", d)
        write_note(CALENDAR_FILE, "", d)

        # dataview: filter by tag / search, no query syntax
        rows = note_rows(d)
        assert {"A.md", "B.md"} <= {r["file"] for r in rows}
        a_row = next(r for r in rows if r["file"] == "A.md")
        assert a_row["tags"] == ["work"] and a_row["link_count"] == 1
        assert a_row["links"] == ["B"] and a_row["linked_from"] == ["B.md"]
        assert {r["file"] for r in filter_note_rows(rows, tag="personal")} == {"B.md"}
        assert {r["file"] for r in filter_note_rows(rows, search="a")} <= {r["file"] for r in rows}
        assert filter_note_rows(rows, tag="nonexistent") == []
        # unchanged notes are not re-read on the next keystroke; a changed one is
        old_stamp = time.time() - 60
        for n in ("A.md", "B.md"):
            os.utime(os.path.join(d, n), (old_stamp, old_stamp))  # old enough to be trusted from the cache
        note_rows(d)
        reads = []
        real_read = read_note
        globals()["read_note"] = lambda *a, **k: (reads.append(a[0]), real_read(*a, **k))[1]
        try:
            assert note_rows(d) == rows and "A.md" not in reads and "B.md" not in reads
            write_note("A.md", "# A\n\nSee [[Home]]. #other\n", d)
            os.utime(os.path.join(d, "A.md"), (old_stamp + 5, old_stamp + 5))
            a_row = next(r for r in note_rows(d) if r["file"] == "A.md")
            assert reads.count("A.md") == 1 and "B.md" not in reads and a_row["links"] == ["Home"] and a_row["tags"] == ["other"]
        finally:
            globals()["read_note"] = real_read
        write_note("A.md", "# A\n\nJust written\n", d)
        assert next(r for r in note_rows(d) if r["file"] == "A.md")["links"] == []  # a note touched this second is never served stale
        write_note("A.md", "# A\n\nSee [[B]]. #work\n\n- [ ] write intro due:2020-01-01\n", d)

        # ICS parsing: one plain event, one weekly recurring event
        sample_ics = (
            "BEGIN:VCALENDAR\n"
            "BEGIN:VEVENT\nSUMMARY:Dentist\nDTSTART;VALUE=DATE:20260601\nEND:VEVENT\n"
            "BEGIN:VEVENT\nSUMMARY:Standup\nDTSTART:20260601T090000\n"
            "RRULE:FREQ=WEEKLY;COUNT=3\nEND:VEVENT\n"
            "END:VCALENDAR\n"
        )
        parsed = parse_ics(sample_ics, window_days=30, today=date(2026, 6, 1))
        titles = sorted(e["title"] for e in parsed)
        assert titles.count("Standup") == 3 and titles.count("Dentist") == 1
        dentist = next(e for e in parsed if e["title"] == "Dentist")
        assert dentist["time"] is None and dentist["date"] == date(2026, 6, 1)

        # should_start_ics_fetch: the exact 3-bug regression from eng review
        assert should_start_ics_fetch(sync=False, syncing=False, fetch_attempted=False) is True
        # Bug 1: never re-arm on every local edit once a fetch has been tried,
        # even if it permanently failed (fetch_attempted=True regardless of outcome)
        assert should_start_ics_fetch(sync=False, syncing=False, fetch_attempted=True) is False
        # Bug 2: never start a second fetch while one is already in flight
        assert should_start_ics_fetch(sync=True, syncing=True, fetch_attempted=True) is False
        # explicit Sync click always re-fetches once the in-flight one finishes
        assert should_start_ics_fetch(sync=True, syncing=False, fetch_attempted=True) is True

        # links to notes that don't exist yet are faded "missing" nodes with edges,
        # so two notes that both link [[Later]] show as connected through it
        write_note("Home.md", "home\n", d)  # thought notes link [[Home]]
        write_note("C.md", "[[Later]] [[Inbox]] [[a/b]]\n", d)
        write_note("D.md", "[[Later]]\n", d)
        notes, edges, missing = build_graph(d)
        assert missing == {"Later.md"} and "Later.md" in notes
        assert ("C.md", "Later.md") in edges and ("D.md", "Later.md") in edges
        assert not any("Inbox.md" in e or "a/b.md" in e for e in edges)  # hidden/unsafe skipped
        os.remove(os.path.join(d, "C.md"))
        os.remove(os.path.join(d, "D.md"))

        tmpl = learning_note_template("Deep Work", date(2026, 11, 10))
        assert tmpl.startswith("# Deep Work\n")
        # only the first sitting is a task; no guidance line files itself anywhere
        assert [l for l in tmpl.splitlines() if TASK_RE.match(l)] == ["t First look, 20 minutes: Deep Work due:2026-11-10"]
        assert all(h in tmpl.splitlines() for h in LEARNING_HINTS)
        assert not any(SHORTHAND_RE.match(l) or ANSWER_RE.match(l) and l.strip() != "answer::" for l in tmpl.splitlines())
        assert expand_shorthand(tmpl, date(2026, 11, 10))[0] == tmpl and "photoread" not in tmpl.lower()
        for section in ("# Prepare", "# Preview", "# Postview", "# Your Questions", "# Activation",
                        "# Next Steps"):
            assert section in tmpl
        assert tmpl.rstrip().splitlines()[-2] == "# Next Steps"  # last section
        # personal or public library: one line under the title, flipped in place, read back
        assert is_book_note(tmpl) and not is_book_note("# Groceries\n\n[[Home]]\n") and library_of(tmpl) is None
        mine = set_library(tmpl, True)
        assert mine.startswith("# Deep Work\n\n[[Home]]\nlibrary:: personal\n") and library_of(mine) == "personal"
        back = set_library(mine, False)
        assert back.count("library::") == 1 and library_of(back) == "public" and back.replace("public", "personal") == mine
        assert library_of(set_library("no title", True)) == "personal" and is_book_note("library:: public\n")
        assert parse_links(tmpl) == ["Home"]  # no accidental links (was [[brackets]])
        # ticking a sitting writes the next one on its day, once: three sittings, two checks, then nothing
        write_note("Deep Work.md", tmpl, d)
        mine = lambda: [t for t in parse_tasks(d) if t["file"] == "Deep Work.md"]
        for day, then in ((11, "Find the answers, 25 minutes: Deep Work due:2026-11-12"),
                          (12, "Say it back, 20 minutes: Deep Work due:2026-11-14"),
                          (14, "Check from memory, a week on: Deep Work due:2026-11-21"),
                          (21, "Check from memory, a month on: Deep Work due:2026-12-12")):
            toggle_task([t for t in mine() if not t["done"]][0], d, date(2026, 11, day))
            assert [t["text"] for t in mine() if not t["done"]] == [then], mine()
        first = mine()[0]
        toggle_task(first, d)  # un-ticked and ticked again: no second copy of what follows
        toggle_task(mine()[0], d)
        assert len(mine()) == 5 and sum(t["done"] for t in mine()) == 4
        toggle_task([t for t in mine() if not t["done"]][0], d)
        assert len(mine()) == 5 and all(t["done"] for t in mine())  # the last check ends it
        assert next_sitting("call the bank", [], date(2026, 11, 10)) is None
        os.remove(os.path.join(d, "Deep Work.md"))
        blank = blank_note_template("Ideas")
        assert blank.startswith("# Ideas\n") and parse_links(blank) == ["Home"]

        # answer:: lines: paired with the question above, collected per [[keyword]]
        assert parse_answers("1. Why?\nanswer:: because\n2.\nanswer::\n# Next\nAnswer:: loose\n") == \
            [("1. Why?", "because"), ("", "loose")]
        assert parse_answers(tmpl) == []  # the template's blanks aren't answers
        write_note("Book1.md", "[[Home]] [[Focus]]\n1. How?\nanswer:: Block mornings\n", d)
        write_note("Book2.md", "[[Focus]] [[Grit]]\n1. Why?\nanswer:: Small wins\n", d)
        write_note("Book3.md", "[[Focus]]\n", d)  # linked, no answers: listed, adds nothing
        assert sync_answer_notes(d) == ["Focus - Answers.md", "Grit - Answers.md", "Home - Answers.md"]
        focus = read_note("Focus - Answers.md", d)
        assert "- [[Book3]]" in focus and "**1. How?**\nBlock mornings" in focus and "Small wins" in focus
        assert "### [[Book3]]" not in focus and not parse_answers(focus)
        # every linked note gets one, Home too (a Learning Note links only [[Home]] until trigger words are added)
        assert "**1. How?**\nBlock mornings" in read_note("Home - Answers.md", d)
        assert sync_answer_notes(d) == []  # nothing changed; generated notes aren't sources
        write_note("Book2.md", "[[Focus]]\n", d)  # answer gone: Focus rebuilt, Grit trashed
        assert sync_answer_notes(d) == ["Focus - Answers.md", "Grit - Answers.md"]
        assert "Small wins" not in read_note("Focus - Answers.md", d)
        assert "Grit - Answers.md" not in list_notes(d)
        write_note("Grit - Answers.md", "my own note\n", d)  # user-written, same name
        write_note("Book2.md", "[[Grit]]\nanswer:: x\n", d)
        assert "Grit - Answers.md" not in sync_answer_notes(d) and read_note("Grit - Answers.md", d) == "my own note\n"
        for n in ("Book1.md", "Book2.md", "Book3.md", "Focus - Answers.md", "Grit - Answers.md", "Home - Answers.md"):
            os.remove(os.path.join(d, n))

        # delete_note: reversible (moved to .trash, not removed), dedup on collision
        write_note("ToDelete.md", "# ToDelete\n", d)
        dest1 = delete_note("ToDelete.md", d)
        assert os.path.exists(dest1) and "ToDelete.md" not in list_notes(d)
        write_note("ToDelete.md", "# ToDelete again\n", d)
        dest2 = delete_note("ToDelete.md", d)
        assert dest1 != dest2 and os.path.exists(dest1) and os.path.exists(dest2)

        assert is_safe_note_title("Meeting notes") is True
        assert is_safe_note_title("9/21 standup") is False  # stray slash
        assert is_safe_note_title("../../etc/passwd") is False
        assert is_safe_note_title("..") is False
        assert is_safe_note_title("Q3: plan") is False and is_safe_note_title("a\\b") is False
        assert is_safe_note_title("trailing dot.") is False
        assert is_safe_note_title(".hidden") is False and is_safe_note_title("a.b") is True
        assert all(is_reserved_title(x) for x in ("Inbox", "calendar", " Recommendations ", "habits - Answers"))
        assert not is_reserved_title("Inbox notes") and not is_reserved_title("Weekly Review")
        assert expand_shorthand("c 12-31-2099 25:00 dinner", date(2026, 1, 1))[3][0].endswith("isn't a time (e.g. 14:30 or 2:30pm)")
        assert expand_shorthand("c 12-31-2099 25:00 dinner", date(2026, 1, 1))[2] == []
        assert expand_shorthand("c 12-31-2099 2pm dinner", date(2026, 1, 1))[2] == [("2099-12-31", "14:00", "dinner")]
        assert expand_shorthand("c 12-31-2099 9 dinner", date(2026, 1, 1))[2] == [("2099-12-31", None, "9 dinner")]
        assert "internet" in _lookup_error(urllib.error.URLError("refused")) and "404" in _lookup_error(
            urllib.error.HTTPError("u", 404, "nf", None, None))

        # notes are UTF-8 on every OS (Windows' default encoding would mangle these)
        write_note("Unicode.md", "café — naïve 🚀\n", d)
        with open(os.path.join(d, "Unicode.md"), "rb") as f:
            assert f.read() == "café — naïve 🚀\n".encode("utf-8")

        assert parse_date("11-22-2026") == parse_date("11/22/2026") == parse_date("2026-11-22") == date(2026, 11, 22)
        assert parse_date("1/5/2026") == date(2026, 1, 5)
        assert parse_date("22-11-2026") is None and parse_date("2026-13-01") is None and parse_date("x") is None
        assert show_date(date(2026, 1, 5)) == "01-05-2026"
        assert due_for_display("pay rent due:2026-10-01") == "pay rent due:10-01-2026"
        assert due_for_storage("pay rent due:10/1/2026") == "pay rent due:2026-10-01"
        assert due_for_storage("no date here") == "no date here"
        write_note("C.md", "- [ ] typed US due:10-01-2026\n- [ ] typo due:13-45-2026\n", d)
        us, typo = [t for t in parse_tasks(d) if t["file"] == "C.md"]
        assert us["due"] == date(2026, 10, 1) and typo["due"] is None
        os.remove(os.path.join(d, "C.md"))

        assert valid_date("2026-09-21") is True
        assert valid_date("not-a-date") is False
        assert valid_date("2026-13-01") is False  # month 13 doesn't exist

        # fetch_ics: unreachable URL -> live=False, never raises; the cache lives in the vault
        text, live = fetch_ics(url="http://127.0.0.1:1/does-not-exist", timeout=1, vault=d)
        assert (text, live) == (None, False)
        with open(os.path.join(d, ".calendar-cache.ics"), "w", encoding="utf-8") as f:
            f.write("BEGIN:VEVENT\nSUMMARY:cached\nDTSTART;VALUE=DATE:20990101\nEND:VEVENT\n")
        text, live = fetch_ics(url="http://127.0.0.1:1/does-not-exist", timeout=1, vault=d)
        assert live is False and "cached" in text  # offline: last copy, flagged not-live

        # a calendar file: .ics read as-is, .csv converted; stored relative to the vault; one source
        ics_path = os.path.join(d, "mycal.ics")
        with open(ics_path, "w", encoding="utf-8") as f:
            f.write("BEGIN:VCALENDAR\nBEGIN:VEVENT\nSUMMARY:From file\nDTSTART:20990305T140000\nEND:VEVENT\nEND:VCALENDAR\n")
        assert set_ics_url("https://cal.example/x.ics", d)
        assert set_calendar_file(ics_path, d) == "mycal.ics"  # relative: the vault can move
        assert get_ics_url(d) is None and get_calendar_file(d) == "mycal.ics"  # file replaced the link
        assert resolve_calendar_file(d) == os.path.normpath(ics_path)
        text, live = fetch_ics(vault=d)
        assert live is True and parse_ics(text, 5000, today=date(2099, 1, 1))[0]["title"] == "From file"
        assert not os.path.exists(os.path.join(d, ".calendar-cache.ics"))  # connecting dropped it
        for bad, why in (("/no/such/file.ics", "exist"), (os.path.join(d, "A.md"), ".ics")):
            try:
                set_calendar_file(bad, d)
                raise AssertionError(bad)
            except ValueError as e:
                assert why in str(e)
        assert get_calendar_file(d) == "mycal.ics"  # refused input changes nothing
        csv_path = os.path.join(d, "cal.csv")
        with open(csv_path, "w", encoding="utf-8-sig") as f:  # Excel writes a BOM
            f.write('Subject,Start Date,Start Time\n"Dentist, Dr. Lee",03/05/2099,2:30 PM\nTrip,2099-04-01,\n'
                    'Bad date,someday,\n,03/06/2099,\n')
        assert set_calendar_file(csv_path, d) == "cal.csv"
        text, live = fetch_ics(vault=d)
        ev = sorted(parse_ics(text, 5000, today=date(2099, 1, 1)), key=lambda e: e["date"])
        assert live and [(e["date"], e["time"], e["title"]) for e in ev] == \
            [(date(2099, 3, 5), "14:30", "Dentist, Dr. Lee"), (date(2099, 4, 1), None, "Trip")]
        assert csv_to_ics("Date;Title\n03-05-2099;semi\n").count("BEGIN:VEVENT") == 1  # ; delimiter
        for bad_csv in ("", "foo,bar\n1,2\n"):
            try:
                csv_to_ics(bad_csv)
                raise AssertionError(bad_csv)
            except ValueError:
                pass
        os.remove(csv_path)
        assert fetch_ics(vault=d) == (None, False)  # file went missing: not reachable, no crash
        assert set_calendar_file("", d) is None and get_calendar_file(d) is None
        os.remove(ics_path)

        # CalDAV: a fake server on localhost keeps what is PUT, plus one event made elsewhere
        import http.server
        import threading
        store, seen_auth = {}, set()

        class Fake(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def reply(self, code, body=b""):
                self.send_response(code)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_PUT(self):
                seen_auth.add(self.headers["Authorization"])
                store[self.path.rsplit("/", 1)[-1]] = self.rfile.read(int(self.headers["Content-Length"])).decode()
                self.reply(201)

            def do_DELETE(self):
                self.reply(204 if store.pop(self.path.rsplit("/", 1)[-1], None) else 404)

            def do_REPORT(self):
                self.rfile.read(int(self.headers["Content-Length"]))
                items = dict(store, **{"phone.ics": "BEGIN:VEVENT\nSUMMARY:Made on phone\nDTSTART:20990105T090000\nEND:VEVENT\n"})
                body = "".join(f"<d:response><d:href>/cal/{k}</d:href><d:propstat><d:prop><c:calendar-data>"
                               f"{html.escape(v)}</c:calendar-data></d:prop></d:propstat></d:response>" for k, v in items.items())
                self.reply(207, ('<d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
                                 + body + "</d:multistatus>").encode())

        srv = http.server.HTTPServer(("127.0.0.1", 0), Fake)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        link = f"http://me%40x.example:pw@127.0.0.1:{srv.server_port}/cal/"
        for ev in (("2099-01-04", "14:30", "Dentist, Dr. Lee"), ("2099-01-06", None, "Trip")):
            add_local_event(*ev, vault=d)
        text = caldav_sync(link, d, today=date(2099, 1, 1))
        assert sorted(store) == sorted(f"{_event_uid(e)}.ics" for e in read_local_events(d))  # both pushed
        assert "DTSTART:20990104T143000" in "".join(store.values()) and "Dr. Lee" in "".join(store.values()).replace("\\,", ",")
        assert seen_auth == {"Basic " + base64.b64encode(b"me@x.example:pw").decode()}  # the login came from the link
        assert [e["title"] for e in parse_ics(text, 5000, today=date(2099, 1, 1))] == ["Made on phone"]  # ours not echoed back
        old = read_local_events(d)[1]
        assert edit_local_event(old, "2099-01-07", None, "Trip", d)  # an edit replaces the pushed event
        delete_local_event(read_local_events(d)[0], d)
        caldav_sync(link, d, today=date(2099, 1, 1))
        assert [v.count("SUMMARY:") for v in store.values()] == [1] and "20990107" in "".join(store.values())
        assert caldav_sync(link, d, today=date(2099, 1, 1)) and len(store) == 1  # nothing left to push
        srv.shutdown()
        assert _caldav_split("https://cal.example/x.ics") == ("https://cal.example/x.ics", None)
        try:
            set_ics_url("http://u:p@cal.example/x", d)
            raise AssertionError("login over http")
        except ValueError:
            pass
        assert set_ics_url("https://u:p@cal.example/cal/", d) and set_ics_url("", d) is None
        fm = "https://caldav.fastmail.com/dav/calendars/user/me@x.example/abc-1/"  # as Fastmail shows it
        assert caldav_needs_login(fm) and not caldav_needs_login("https://cal.example/x.ics")
        assert not caldav_needs_login("https://u:p@caldav.fastmail.com/dav/x/")
        full = caldav_with_login(fm, "p w:1")
        assert full == "https://me%40x.example:p%20w%3A1@caldav.fastmail.com/dav/calendars/user/me@x.example/abc-1/"
        assert _caldav_split(full)[1] == "Basic " + base64.b64encode(b"me@x.example:p w:1").decode()
        try:
            caldav_with_login("https://h.example/dav/cal/", "x")
            raise AssertionError("no user name")
        except ValueError:
            pass
        for name in os.listdir(d):  # the calendar events above were only for this test
            if name in (CALENDAR_FILE, ".caldav-pushed.json"):
                os.remove(os.path.join(d, name))

        assert os.path.isdir(app_dir())  # in a frozen build this is the folder holding the program
        # settings: env > saved folder > Documents; saved paths are relative to the settings file
        drive = os.path.join(d, "drive")
        os.makedirs(os.path.join(drive, "Windows"))
        sf = os.path.join(drive, SETTINGS_NAME)
        assert settings_path(os.path.join(drive, "Windows")) == os.path.join(
            user_config_dir(), "settings.json")  # no file yet: per-user
        open(sf, "w").close()
        assert settings_path(os.path.join(drive, "Windows")) == sf  # found one folder up
        assert resolve_vault({}, sf) == DEFAULT_VAULT  # empty settings file: default
        v1 = os.path.join(drive, "Vault")
        shown = set_vault(v1, settings_file=sf, remember=True)
        assert shown == v1 and os.path.exists(os.path.join(v1, "Home.md"))
        assert load_settings(sf) == {"vault": "Vault"}  # relative: the drive can change letter
        assert resolve_vault({}, sf) == v1
        moved = os.path.join(d, "moved-drive")
        os.rename(drive, moved)  # "plugged into another machine"
        sf2 = os.path.join(moved, SETTINGS_NAME)
        assert resolve_vault({}, sf2) == os.path.join(moved, "Vault")  # still finds its notes
        assert resolve_vault({"SIMPLEBRAIN_VAULT": "/x"}, sf2) == "/x"  # env var wins
        open(sf2, "w").write("not json")
        assert load_settings(sf2) == {} and resolve_vault({}, sf2) == DEFAULT_VAULT  # corrupt: no crash
        # switching at runtime: every function follows, nothing keeps reading the old folder
        keep = VAULT
        try:
            elsewhere = os.path.join(d, "elsewhere")
            set_vault(elsewhere, remember=False)
            write_note("OnlyThere.md", "# x\n")
            assert list_user_notes() == ["Home.md", "OnlyThere.md"]
            assert list_user_notes(d) != list_user_notes()  # the explicit vault still wins
            add_inbox_item("goes to the new vault")
            assert parse_inbox()[0]["text"] == "goes to the new vault" and parse_inbox(d) == []
        finally:
            set_vault(keep, remember=False)
        # copy_vault: notes and .config come across, nothing is overwritten, cache/trash stay home
        src, dst = os.path.join(d, "src"), os.path.join(d, "dst")
        os.makedirs(os.path.join(src, ".trash"))
        os.makedirs(dst)
        for name, text in (("A.md", "a"), ("B.md", "b"), (".config", "ICS_URL=https://x.example/y.ics\n"),
                           (".calendar-cache.ics", "cache"), (".trash/old.md", "t")):
            open(os.path.join(src, name), "w").write(text)
        open(os.path.join(dst, "B.md"), "w").write("keep me")
        assert copy_vault(src, dst) == 2  # A.md and .config
        assert sorted(os.listdir(dst)) == [".config", "A.md", "B.md"]
        assert open(os.path.join(dst, "B.md")).read() == "keep me"
        # graph icons: emoji or a copied picture, replace removes the old copy, and they move with the folder
        assert graph_icons(src) == {}
        assert set_graph_icon("A.md", emoji=" 🏠 ", vault=src) == "🏠" and graph_icons(src) == {"A.md": "🏠"}
        assert graph_icon_picture("🏠", src) is None
        pic = os.path.join(d, "Cat.PNG")
        open(pic, "wb").write(b"not really a png")
        icon = set_graph_icon("B: odd/name.md", picture=pic, vault=src)
        first = graph_icon_picture(icon, src)
        assert icon.startswith("pictures/") and first.endswith(".png") and open(first, "rb").read() == b"not really a png"
        os.remove(pic)  # the original going away doesn't take the icon with it
        assert os.path.exists(first)
        assert set_graph_icon("B: odd/name.md", emoji="⭐", vault=src) == "⭐" and not os.path.exists(first)
        open(pic, "wb").write(b"png")
        set_graph_icon("A.md", picture=pic, vault=src)
        before = graph_icons(src)
        try:
            set_graph_icon("A.md", picture=os.path.join(d, "notes.txt"), vault=src)
            raise AssertionError("a non-picture was accepted")
        except ValueError:
            pass
        assert graph_icons(src) == before and os.path.exists(graph_icon_picture(before["A.md"], src))
        assert set_graph_icon("B: odd/name.md", vault=src) is None and list(graph_icons(src)) == ["A.md"]
        dst2 = os.path.join(d, "dst2")
        os.makedirs(dst2)
        copy_vault(src, dst2)
        assert graph_icons(dst2) == graph_icons(src) and os.path.exists(graph_icon_picture(graph_icons(dst2)["A.md"], dst2))

    print("selftest OK")


if __name__ == "__main__":
    selftest()
