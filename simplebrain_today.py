#!/usr/bin/env python3
"""The Today note: built from your own tasks each time SimpleBrain starts and whenever a task changes.
The three things to do (overdue and due today first, then the nearest coming up), each with the files,
videos and web links that sit with it in its note, so they're one click away (and the first one is
already open when SimpleBrain is the desktop). Today's calendar under them. No new kind of data: it
only reads the notes; editing it is pointless, it's rebuilt.

Run: python simplebrain_today.py   (selftest)
"""
import os
import re
import zipfile
from datetime import date, datetime, timedelta
from xml.etree import ElementTree

import simplebrain_budget as budget
import simplebrain_core as core
import simplebrain_day as workday
import simplebrain_habits as habits
import simplebrain_mail as mail
import simplebrain_watch as watch

TITLE = "Today"
MARK = "_SimpleBrain writes this note from your tasks. Change them in their own notes; this one is rewritten._"
URL_RE = re.compile(r"https?://[^\s<>\])]+")
MAX_THINGS = 3  # more than this and nothing gets done


def note_name(vault=None):
    """Today.md unless that's a note you wrote yourself."""
    vault = vault or core.VAULT
    path = os.path.join(vault, TITLE + ".md")
    if not os.path.exists(path) or MARK in core.read_note(TITLE + ".md", vault):
        return TITLE + ".md"
    return TITLE + " (SimpleBrain).md"


def things(vault=None, today=None, limit=MAX_THINGS):
    vault = vault or core.VAULT
    b = core.bucket_tasks([t for t in core.parse_tasks(vault) if MARK not in core.read_note(t["file"], vault)], today)
    up = sorted(b["Upcoming"], key=lambda t: t["due"])
    out = sorted(b["Overdue"], key=lambda t: t["due"]) + b["Today"] + up
    return out[:limit] if limit else out


def material(task, vault=None):
    """What goes with a task: the file:: lines and web links right under it in its note (up to the next
    task or blank line); if there are none, the note's own file:: lines; plus those of notes the task
    links to. Paths are resolved, duplicates dropped."""
    vault = vault or core.VAULT
    lines = core.read_note(task["file"], vault).splitlines()
    files, urls = [], URL_RE.findall(task["text"])
    for line in lines[task["line"] + 1:]:
        if not line.strip() or core.TASK_RE.match(line):
            break
        f = core.FILE_RE.match(line)
        if f:
            files.append(f.group(1))
        else:
            urls += URL_RE.findall(line)
    if not files and not urls and sum(1 for l in lines if core.TASK_RE.match(l)) <= 1:
        files = core.parse_files("\n".join(lines))[:3]  # one task in the note: its files are that task's
    for link in core.parse_links(task["text"]):
        if os.path.exists(os.path.join(vault, link + ".md")):
            files += core.parse_files(core.read_note(link + ".md", vault))[:3]
    files = [os.path.normpath(core.resolve_file(f, vault)) for f in dict.fromkeys(files)]  # one slash style
    return files, list(dict.fromkeys(u.rstrip(".,;:!?") for u in urls))


# ---------- your favorite problems (Feynman's 12 questions, as Tiago Forte puts it) ----------

QUESTION_NOTE_RE = re.compile(r"favou?rite problems|questions", re.I)
STOP = set("about after again being could does doing every first from have into just make more most much need "
           "other over should some such than that their them then there these they thing this those through "
           "very what when where which while will with would your yours".split())


def questions(vault=None):
    """[(note, question)] from a note titled like '12 Favorite Problems' or 'My Questions': its numbered lines."""
    vault = vault or core.VAULT
    out = []
    for n in core.list_user_notes(vault):
        if not QUESTION_NOTE_RE.search(core.note_title(n)) or n.endswith(core.ANSWERS_SUFFIX + ".md"):
            continue
        for line in core.read_note(n, vault).splitlines():
            m = re.match(r"^\s*\d+[.)]\s*(\S.*)$", line)
            if m:
                out.append((n, m.group(1).strip()))
    return out


def words(text):
    """Meaningful words, lowercased, a plural 's' dropped: enough to tell what a line is about."""
    out = set()
    for w in re.findall(r"[A-Za-z][A-Za-z'-]{3,}", core.WIKILINK_RE.sub(lambda m: m.group(1), text)):
        w = w.lower().strip("'-")
        if w not in STOP:
            out.add(w[:-1] if w.endswith("s") and len(w) > 4 else w)
    return out


def feeds(text, qs):
    """The question a line of work moves forward: most words in common, and at least two (one word, like
    'student', is chance), or all of a very short question's. None when nothing fits."""
    best, score = None, 0
    tw = words(text)
    for q in qs:
        qw = words(q[1])
        n = len(tw & qw)
        if n >= min(2, len(qw)) and n > score:
            best, score = q, n
    return best


# ---------- the plan workbook (Money-Plan.xlsx): read where it is, never imported ----------

PLAN_LINE = re.compile(r"^\s*plan::\s*(.+?)\s*$", re.MULTILINE)

_NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
       "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
       "rel": "http://schemas.openxmlformats.org/package/2006/relationships"}
XLSX_MAX = 20 * 1024 * 1024  # per part, unpacked: a plan is far smaller; a zip bomb isn't


def _part(z, name):
    info = z.getinfo(name)
    if info.file_size > XLSX_MAX:
        raise ValueError(f"{name} is too big for a plan")
    return ElementTree.fromstring(z.read(name))


def _col(ref):
    n = 0
    for ch in re.match(r"[A-Z]+", ref).group():
        n = n * 26 + ord(ch) - 64
    return n - 1


def read_xlsx(path):
    """{sheet name: [rows as lists of str/float/None]}."""
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
        shared = []
        if "xl/sharedStrings.xml" in names:
            for si in _part(z, "xl/sharedStrings.xml").findall("m:si", _NS):
                shared.append("".join(t.text or "" for t in si.iter(f"{{{_NS['m']}}}t")))
        rels = {r.get("Id"): r.get("Target") for r in _part(z, "xl/_rels/workbook.xml.rels").findall("rel:Relationship", _NS)}
        out = {}
        for s in _part(z, "xl/workbook.xml").find("m:sheets", _NS):
            target = rels.get(s.get(f"{{{_NS['r']}}}id"), "")
            target = target.lstrip("/") if target.startswith("/") else "xl/" + target
            if target not in names:
                continue
            rows = []
            for row in _part(z, target).iter(f"{{{_NS['m']}}}row"):
                vals = []
                for c in row.findall("m:c", _NS):
                    i = _col(c.get("r", "A"))
                    vals.extend([None] * (i + 1 - len(vals)))
                    t, v = c.get("t"), c.findtext("m:v", None, _NS)
                    if t == "s" and v is not None:
                        vals[i] = shared[int(v)]
                    elif t == "inlineStr":
                        vals[i] = "".join(x.text or "" for x in c.iter(f"{{{_NS['m']}}}t"))
                    elif t in ("str", "e"):
                        vals[i] = v
                    elif t == "b":
                        vals[i] = v == "1"
                    elif v is not None:
                        try:
                            vals[i] = float(v)
                        except ValueError:
                            vals[i] = v
                rows.append(vals)
            out[s.get("name")] = rows
    return out


def _cell_date(v):
    if isinstance(v, float) and 20000 < v < 80000:  # an Excel day number
        return date(1899, 12, 30) + timedelta(days=int(v))
    if isinstance(v, str):
        return core.parse_date(v.split()[0]) if v.strip() else None
    return None


def plan_path(vault=None):
    """The workbook a `plan:: path` line in Home or Settings names, or None. Only ever the one you name: SimpleBrain
    doesn't go looking through your folders for spreadsheets."""
    vault = vault or core.VAULT
    try:
        m = PLAN_LINE.search(core.settings_text(vault))
    except OSError:
        m = None
    if not m:
        return None
    path = os.path.normpath(core.resolve_file(m.group(1), vault))  # one slash style, on Windows too
    return path if os.path.isfile(path) else None


# ---------- plan actions ticked in SimpleBrain (the workbook itself is never written) ----------

def plan_done_path():
    return os.path.join(core.user_config_dir(), "plan-done.json")


def plan_key(t):
    return f"{t['due'].isoformat() if t.get('due') else ''}|{' '.join(t['text'].lower().split())}"


def plan_done_keys():
    import json
    try:
        with open(plan_done_path(), encoding="utf-8") as f:
            return set(json.load(f))
    except (OSError, ValueError, TypeError):
        return set()


def mark_plan_done(t, done=True):
    """Tick a workbook action in SimpleBrain: it stops showing as open here (no need to also type Done in the
    workbook, though that works too)."""
    import json
    keys = plan_done_keys()
    (keys.add if done else keys.discard)(plan_key(t))
    os.makedirs(os.path.dirname(plan_done_path()), exist_ok=True)
    core.write_atomic(plan_done_path(), json.dumps(sorted(keys)))


def same_action(a, b):
    """Two lines that are the same thing to do (the workbook's 'Call Riverside to stop the draft' and a note's
    't 9am: Call Riverside (866) …: stop the draft'): most of their words in common, at least two."""
    wa, wb = words(core.DUE_RE.sub("", a)), words(core.DUE_RE.sub("", b))
    return len(wa & wb) >= max(2, 0.6 * min(len(wa), len(wb)))


def plan_items(path, today=None, everything=False):
    """Open actions of yours from the plan's Checklist (a sheet with Date, Action and Status columns), due
    today or earlier: [{"text", "due", "file", "area", "notes"}]. Rows for Jarvis/Claude alone are left out, and so
    are rows marked Done in the workbook or ticked in SimpleBrain."""
    today = today or date.today()
    ticked = plan_done_keys()
    try:
        sheets = read_xlsx(path)
    except (OSError, zipfile.BadZipFile, KeyError, IndexError, ValueError, ElementTree.ParseError):
        return []
    for rows in sheets.values():
        for hi, row in enumerate(rows[:15]):
            head = [str(c).strip().lower() if c is not None else "" for c in row]
            if "date" not in head or "action" not in head:
                continue
            col = {k: head.index(k) if k in head else None for k in ("date", "action", "area", "who", "status")}
            notes = next((i for i, h in enumerate(head) if h.startswith("notes")), None)
            get = lambda r, i: r[i] if i is not None and i < len(r) else None
            out = []
            for r in rows[hi + 1:]:
                action, d = get(r, col["action"]), _cell_date(get(r, col["date"]))
                status = str(get(r, col["status"]) or "").strip().lower()
                who = str(get(r, col["who"]) or "").strip().lower()
                if not action or not d or (d > today and not everything) or status in ("done", "skipped") \
                        or who in ("jarvis", "claude", "ai", "assistant"):
                    continue
                item = {"text": " ".join(str(action).split()), "due": d, "file": path,
                        "area": str(get(r, col["area"]) or "").strip(), "notes": str(get(r, notes) or "").strip()}
                if plan_key(item) not in ticked:
                    out.append(item)
            return out
    return []


TIME_AT_START = re.compile(r"^(\d{1,2})(?::(\d{2}))?\s*([ap]m)\b", re.I)


def urgency(t):
    """Today's things with a time ('8am: call …') first, by time; then the rest of today; then what's
    overdue, newest first (yesterday's slip is likelier still to matter than last week's)."""
    today_ = t["due"] == date.today() if "_today" not in t else t["_today"]
    m = TIME_AT_START.match(t["text"])
    if today_ and m:
        h = int(m.group(1)) % 12 + (12 if m.group(3).lower() == "pm" else 0)
        return (0, h * 60 + int(m.group(2) or 0), 0)
    return (1, 0, 0) if today_ else (2, -t["due"].toordinal(), 0)


def cards_for(text, path, limit=1):
    """Call scripts and step lists in the plan's cards/ folder that share a word with the action."""
    folder = os.path.join(os.path.dirname(path), "cards")
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return []
    verbs = {"call", "email", "text", "send", "check", "book", "meet", "card", "step", "list", "draft"}
    stem = lambda t: {w[:5] for w in words(t) if w not in verbs}  # 'rehab' finds 'rehabilitation'
    stems = stem(text)
    hits = [(len(stems & stem(os.path.splitext(n)[0].replace("-", " ").replace("_", " "))), n)
            for n in names if not n.startswith(".")]
    return [os.path.join(folder, n) for k, n in sorted(hits, key=lambda h: -h[0]) if k][:limit]


# ---------- people: keep in touch without keeping track ----------

EVERY_RE = re.compile(r"^\s*every::\s*(\d+)?\s*(day|week|month|year)s?\s*$", re.I | re.M)
BIRTHDAY_RE = re.compile(r"^\s*birthday::\s*(\d{1,2})[-/](\d{1,2})", re.I | re.M)
DATE_IN_LINE = re.compile(r"\b(\d{4}-\d{2}-\d{2}|\d{1,2}[-/]\d{1,2}[-/]\d{4})\b")
UNIT_DAYS = {"day": 1, "week": 7, "month": 30, "year": 365}


def people(vault=None, today=None):
    """[{"note", "every", "last", "due_ratio", "birthday"}] for notes with an `every::` line. The last
    contact is the newest past date written in the note (a line like '11-02-2026 called about the bond')
    or the newest past calendar event that links to it."""
    vault = vault or core.VAULT
    today = today or date.today()
    events = core.read_local_events(vault)
    out = []
    for n in core.list_user_notes(vault):
        text = core.read_note(n, vault)
        m = EVERY_RE.search(text)
        if not m:
            continue
        every = int(m.group(1) or 1) * UNIT_DAYS[m.group(2).lower()]
        dates = [d for line in core.without_code(text).splitlines() if not BIRTHDAY_RE.match(line)
                 for x in DATE_IN_LINE.findall(line) if (d := core.parse_date(x)) and d <= today]
        title = core.note_title(n)
        dates += [e["date"] for e in events if e["date"] <= today and title in core.parse_links(e["title"])]
        last = max(dates) if dates else None
        b = BIRTHDAY_RE.search(text)
        bday = None
        if b:
            try:
                bday = date(today.year, int(b.group(1)), int(b.group(2)))
                if bday < today:
                    bday = date(today.year + 1, bday.month, bday.day)
            except ValueError:
                pass
        ratio = ((today - last).days / every) if last else 99.0
        out.append({"note": n, "every": every, "last": last, "due_ratio": ratio, "birthday": bday})
    return out


def every_text(days):
    for unit, k in (("year", 365), ("month", 30), ("week", 7)):
        if days % k == 0:
            n = days // k
            return f"every {unit}" if n == 1 else f"every {n} {unit}s"
    return f"every {days} days"


def free_stretch(events, today, start_h=8, end_h=22, now=None):
    """The longest gap today between timed events (each taken as an hour, a shift as eight), from now
    or 8am to 10pm: (start, end) as datetimes, or None if under an hour."""
    now = now or datetime.now()
    begin = max(datetime.combine(today, datetime.min.time()).replace(hour=start_h),
                now if now.date() == today else datetime.min)
    stop = datetime.combine(today, datetime.min.time()).replace(hour=end_h)
    busy = []
    for e in events:
        if e["date"] == today and e["time"]:
            a = datetime.combine(today, datetime.strptime(e["time"], "%H:%M").time())
            busy.append((a, a + timedelta(hours=8 if re.search(r"\bshift\b", e["title"], re.I) else 1)))
    best, cur = None, begin
    for a, b in sorted(busy) + [(stop, stop)]:
        if a > cur and (best is None or a - cur > best[1] - best[0]):
            best = (cur, min(a, stop))
        cur = max(cur, b)
    return best if best and best[1] - best[0] >= timedelta(hours=1) else None


def clock(t):
    return t.strftime("%I:%M %p").lstrip("0").replace(":00", "")


def today_items(vault=None, today=None):
    """The three things: from the plan workbook and your notes' tasks, today's timed ones first."""
    vault = vault or core.VAULT
    today = today or date.today()
    plan = plan_path(vault)
    items = things(vault, today, limit=None if plan else MAX_THINGS)  # with a plan, every task due is in the running
    if plan:  # the plan's actions due by today join your notes' tasks due by today
        acts = plan_items(plan, today)
        items = [t for t in items if not any(same_action(t["text"], a["text"]) for a in acts)]  # in both: shown once
        pool = acts + [t for t in items if t["due"] and t["due"] <= today]
        for t in pool:
            t["_today"] = t["due"] == today
        items = (sorted(pool, key=urgency) + [t for t in items if not (t["due"] and t["due"] <= today)])[:MAX_THINGS]
    return items


def home_short(path):
    """~/… for a file in your home folder: the note reads shorter and still opens it."""
    home, norm = os.path.normpath(os.path.expanduser("~")), os.path.normpath(path)  # one slash style on Windows
    return "~" + norm[len(home):] if norm.startswith(home + os.sep) else path


# ---------- courses in order, and folders worth a look ----------

FOLDER_LINE = re.compile(r"^\s*course::\s*(.+?)\s*$", re.I | re.M)  # only a note you call a course: a folder:: line
# (the old trial's Videos note had one) is just a folder, never a list of sessions to push on you
AFTER_LINE = re.compile(r"^\s*after::\s*\[\[([^\]]+)\]\]", re.I | re.M)
WATCH_LINE = re.compile(r"^\s*watch::\s*(.+?)\s*$", re.I | re.M)
SESSION_EXTS = {".mp3", ".m4a", ".m4b", ".wav", ".ogg", ".opus", ".flac", ".aac", ".mp4", ".m4v", ".mkv", ".webm",
                ".avi", ".mov", ".pdf", ".epub"}


def natural_key(name):
    """'Session 2' before 'Session 10': numbers compared as numbers."""
    return [int(x) if x.isdigit() else x.lower() for x in re.split(r"(\d+)", name)]


def sessions(folder):
    """Every session file in a course folder (and its subfolders), in the order a person would take them."""
    out = []
    for d, sub, files in os.walk(folder):
        sub[:] = sorted((x for x in sub if not x.startswith(".")), key=natural_key)
        out += [os.path.join(d, f) for f in files if os.path.splitext(f)[1].lower() in SESSION_EXTS and not f.startswith(".")]
    return sorted(out, key=lambda p: natural_key(os.path.relpath(p, folder)))


def opened_files(habits_log=None):
    """Every file opened through SimpleBrain (from a note, Today or the top bar): what counts as a session done."""
    return {os.path.normpath(e["x"]) for e in habits.entries(habits_log) if e.get("k") == "file" and e.get("x")}


def next_sessions(vault=None, habits_log=None):
    """[(note, next file, done count, total)] for notes with a `course::` line: the first session not opened through
    SimpleBrain yet. A course with `after:: [[Other]]` waits until Other is finished."""
    vault = vault or core.VAULT
    opened = opened_files(habits_log)
    courses = {}
    for n in core.list_user_notes(vault):
        text = core.read_note(n, vault)
        m = FOLDER_LINE.search(text)
        if not m:
            continue
        folder = os.path.normpath(core.resolve_file(m.group(1), vault))
        files = sessions(folder) if os.path.isdir(folder) else []
        if not files:
            continue
        nxt = next((f for f in files if os.path.normpath(f) not in opened), None)
        done = sum(1 for f in files if os.path.normpath(f) in opened)
        after = AFTER_LINE.search(text)
        courses[core.note_title(n)] = (n, nxt, done, len(files), after.group(1).strip() if after else None)
    out = []
    for title, (n, nxt, done, total, after) in courses.items():
        if nxt is None:
            continue  # finished
        if after and after in courses and courses[after][1] is not None:
            continue  # the course before it isn't finished yet
        out.append((n, nxt, done, total))
    return out


def fresh_in_watched(vault=None, now=None, days=2, n=5):
    """New things in the folders Home watches (`watch:: ~/Videos/ready`): [(path)] from the last two days."""
    vault = vault or core.VAULT
    now = now or datetime.now()
    try:
        home = core.settings_text(vault)
    except OSError:
        return []
    cutoff = (now - timedelta(days=days)).timestamp()
    out = []
    for raw in WATCH_LINE.findall(home):
        folder = os.path.normpath(core.resolve_file(raw, vault))
        try:
            for f in os.listdir(folder):
                p = os.path.join(folder, f)
                if not f.startswith(".") and os.path.getmtime(p) >= cutoff:
                    out.append(p)
        except OSError:
            continue
    return sorted(out, key=os.path.getmtime, reverse=True)[:n]


# ---------- learn one thing: a single next step, gone once you've done it ----------

LEARN = (  # (what SimpleBrain notices, the step): in the order that pays off fastest
    ("bar_task", "In the bar at the top, type `t call mom fri` and press Enter: a task, due Friday, in one line."),
    ("tick", "Tick a task in the Tasks list when it's done: it's checked off in its note too."),
    ("bar_event", "Type `c tomorrow 2pm coffee with Dad` in the top bar: it's on the calendar at once."),
    ("link_complete", "In any note type two square brackets and a few letters of another note's name, then Enter."),
    ("drop", "Drag a file from your Downloads onto this window: it's filed into the project it belongs to and linked."),
    ("money", "Click Money at the top: write your cash and one paycheck, and watch how far it lasts."),
    ("limit", "Add a line `limit:: 3h` to Home: the top bar shows the computer time you have left today."),
    ("people", "Make a note for someone you want to keep up with and add `every:: 2 weeks` to it."),
    ("mention", "Open a note that other notes mention by name: under the editor, Mentioned in links them in one click."),
    ("answer", "Under a question in a note, write `answer:: your answer`: linked notes collect every answer."),
)


def learned(vault=None, settings=None):
    """What you've already done, from what SimpleBrain noticed and from what's in your notes."""
    vault = vault or core.VAULT
    done = set((settings if settings is not None else core.load_settings()).get("learned", []))
    try:
        home = core.settings_text(vault)
    except OSError:
        home = ""
    if watch.LIMIT_RE.search(home):
        done.add("limit")
    for n in core.list_user_notes(vault):
        text = core.read_note(n, vault)
        if EVERY_RE.search(text):
            done.add("people")
        if core.ANSWER_RE.search(text) and "answer::" in text.lower():
            done.add("answer")
    return done


def next_step(done):
    """(number, of how many, the step) for the first thing not done yet, or None once everything is."""
    for i, (key, text) in enumerate(LEARN, 1):
        if key not in done:
            return i, len(LEARN), text
    return None


def build(vault=None, now=None, ics_text=None, habits_log=None, watch_base=None):
    vault = vault or core.VAULT
    now = now or datetime.now()
    today = now.date()
    out = [f"# {TITLE}", now.strftime("%A, %B ") + str(now.day), ""]
    left = watch.parked(now, base=watch_base)
    if left:  # what you wrote when time ran out: the first thing you read
        out += [f"**Pick up here:** {left}", ""]
    y = watch.load_day(today - timedelta(days=1), watch_base)
    if y.get("done") or y.get("ticked"):  # a zero is no way to start a day: only what got done
        out += [f"Yesterday: {watch.score_line(y, y.get('three'), y.get('done'))}", ""]
    when, mail_items = mail.last_digest()
    if when and when.date() == today and mail_items:  # read twice a day by the app; never fetched from here
        out.append("## Mail that needs you")
        out += [f"- {m}" for m in mail_items]
        out.append("")
    if os.path.exists(os.path.join(vault, budget.NOTE)):
        try:
            b = budget.load(vault, today, plan_path(vault))
            out += [f"**Money:** {budget.summary(budget.project(b, today), today)} ([[Budget]])", ""]
        except (OSError, ValueError):
            pass
    items = today_items(vault, today)
    plan = plan_path(vault)
    qs = questions(vault)
    extra = workday.overload(vault, today)
    if extra:  # more than three due: they're not hidden, they're waiting; Spread out moves them to lighter days
        out.append(f"*{len(extra)} more due by today wait in Tasks. **Spread out** (Tasks panel) gives them lighter days.*\n")
    if not items:
        out.append("Nothing due. The day is yours.\n")
    for i, t in enumerate(items, 1):
        text = core.DUE_RE.sub("", t["text"]).strip()
        q = feeds(text + " " + core.note_title(t["file"]), qs)
        d = t["due"]
        when = "overdue" if d and d < today else "today" if d == today else \
            (d.strftime("%a %b ") + str(d.day)) if d else "no date"
        rep = core.REPEAT_RE.search(text)
        if rep:  # a habit: 'every:day' reads as plain words
            text = core.REPEAT_RE.sub("", text).strip() + f" ({'every ' + rep.group(1).lower() if rep.group(1).lower() != 'weekday' else 'every weekday'})"
        out.append(f"## {i}. {text}")
        if "area" in t:  # from the plan workbook
            out.append(f"From the plan ({t['area'] or 'Checklist'}) · {when}" + (f" · {t['notes']}" if t["notes"] else ""))
            out += [f"file:: {home_short(c)}" for c in cards_for(text, t["file"])]
            out.append("")
            continue
        out.append(f"From [[{core.note_title(t['file'])}]] · {when}")
        if q:
            out.append(f"Moves your question forward: *{q[1]}* ([[{core.note_title(q[0])}]])")
        files, urls = material(t, vault)
        out += [f"file:: {home_short(f)}" for f in files] + urls
        out.append("")
    if any("area" in t for t in items):  # the workbook once, for ticking things off there
        out.append(f"Done one from the plan? Tick it in Tasks (or mark it Done in the workbook):\nfile:: {home_short(plan)}\n")
    nexts = next_sessions(vault, habits_log)[:2]  # two courses at most: more is a list, not a plan
    if nexts:
        out.append("## Up next in your courses")
        for n, f, done, total in nexts:
            out.append(f"[[{core.note_title(n)}]] · {done} of {total} done · next: {os.path.splitext(os.path.basename(f))[0]}")
            out.append(f"file:: {home_short(f)}")
        out.append("")
    fresh = fresh_in_watched(vault, now)
    if fresh:
        out.append("## New in your folders")
        out += [f"file:: {home_short(p)}" for p in fresh]
        out.append("")
    shown = "\n".join(out)
    usual = [u for u in habits.usual(now, path=habits_log) if u[2] not in shown and u[0] != "app"]
    if usual:  # learned from what you open through SimpleBrain: the next thing before you go looking
        out.append("## Around now you usually open")
        for kind, label, target in usual:
            out.append(f"[[{core.note_title(os.path.basename(target))}]]" if kind == "note" else
                       f"file:: {target}" if kind == "file" else target)
        out.append("")
    if qs:
        touched = [feeds(core.DUE_RE.sub("", t["text"]) + " " + (t.get("area") or core.note_title(t["file"])), qs)
                   for t in items]
        if not any(touched):  # nothing today feeds one: keep one in mind anyway, a different one each day
            q = qs[today.toordinal() % len(qs)]
            out.append("## A question to keep in mind")
            out.append(f"*{q[1]}* ([[{core.note_title(q[0])}]])")
            related = [n for n in core.list_user_notes(vault) if n != q[0] and MARK not in core.read_note(n, vault)
                       and len(words(core.note_title(n)) & words(q[1])) >= 1][:3]
            if related:
                out.append("Notes that touch it: " + ", ".join(f"[[{core.note_title(n)}]]" for n in related))
            out.append("")
    try:
        events = core.upcoming_events(vault, days=1, ics_text=ics_text, today=today)
    except Exception:  # a broken feed never stops the note
        events = core.upcoming_events(vault, today=today)
    events = [e for e in events if e["date"] == today]
    folks = people(vault, today)
    late = sorted((p for p in folks if p["due_ratio"] >= 1), key=lambda p: -p["due_ratio"])
    soon = sorted((p for p in folks if p["birthday"] and (p["birthday"] - today).days <= 7), key=lambda p: p["birthday"])
    gap0 = free_stretch(events, today, now=now)
    suggested = [x for x in workday.suggest_people(vault, today) if not late or x[0] != late[0]["note"]][:1]
    if late or soon or suggested:  # one person a day is a habit; a list of ten is a guilt trip
        out.append("## People")
        for p in soon:
            days = (p["birthday"] - today).days
            out.append(f"[[{core.note_title(p['note'])}]]'s birthday " +
                       ("is today" if days == 0 else "is tomorrow" if days == 1 else p["birthday"].strftime("on %a %b ") + str(p["birthday"].day)))
        if late:
            p = late[0]
            since = f"{(today - p['last']).days} days since you were last in touch" if p["last"] else "no contact written down yet"
            out.append(f"Reach out to [[{core.note_title(p['note'])}]] · {since} ({every_text(p['every'])})")
            if gap0:
                out.append(f"A good time: {clock(gap0[0])}, the start of your free stretch.")
            out.append(f"When you do, add a line with today's date to their note ({core.show_date(today)} called …).")
        for note, days in suggested:  # written about lately, not talked to in a while: before it's overdue
            since = f"{days} days since you were in touch" if days is not None else "no contact written down yet"
            out.append(f"You've been writing about [[{core.note_title(note)}]] · {since}. A quick check-in?")
        out.append("")
    gap = free_stretch(events, today, now=now)
    if gap and not items:
        out.append(f"Free {clock(gap[0])} to {clock(gap[1])}: yours.\n")
    elif gap:
        limit = watch.limit_seconds(vault, now=now.replace(hour=0, minute=0), used_s=0)
        if limit is not None:  # a computer-time limit: that, not a free afternoon, is the time there is
            out.append(f"## Your time\n{watch.mins(limit)} at the computer today: the three things first.\n")
        else:
            out.append(f"## Your time\nLongest free stretch: {clock(gap[0])} to {clock(gap[1])}. Learn something, or rest.\n")
    if events:
        out.append("## Calendar")
        for e in events:
            if e["time"]:
                h, m = map(int, e["time"].split(":"))
                out.append(f"- {(h % 12) or 12}:{m:02d} {'AM' if h < 12 else 'PM'}  {e['title']}")
            else:
                out.append(f"- {e['title']}")
        out.append("")
    step = next_step(learned(vault))
    if step:  # one at a time: a list of ten tips is a wall; one is a two-minute win
        out.append(f"## Learn one thing ({step[0]} of {step[1]})")
        out.append(step[2] + " This line moves on by itself once you've done it.")
        out.append("")
    out.append(MARK)
    return "\n".join(out).rstrip("\n") + "\n"


def update(vault=None, now=None, ics_text=None, habits_log=None, watch_base=None):
    """Rewrite the Today note if it changed. Returns its filename and whether it was written."""
    vault = vault or core.VAULT
    name = note_name(vault)
    text = build(vault, now, ics_text, habits_log, watch_base)
    path = os.path.join(vault, name)
    if os.path.exists(path) and core.read_note(name, vault) == text:
        return name, False
    core.write_note(name, text, vault)
    return name, True


def open_texts(vault=None, today=None):
    """Every open task and plan action: what the watcher compares the day's three against to see what got done."""
    vault = vault or core.VAULT
    out = [t["text"] for t in core.parse_tasks(vault) if not t["done"]]
    plan = plan_path(vault)
    return out + ([t["text"] for t in plan_items(plan, today)] if plan else [])


def first_material(vault=None, today=None):
    """The first file or link of the first thing: what's already open when SimpleBrain is the desktop."""
    for t in today_items(vault, today):
        if "area" in t:  # from the plan: its card, if there is one
            cards = cards_for(core.DUE_RE.sub("", t["text"]), t["file"])
            if cards:
                return cards[0]
            continue
        files, urls = material(t, vault)
        for f in files:
            if os.path.exists(f):
                return f
        if urls:
            return urls[0]
    return None


def _write_xlsx(path, rows, sheet="Checklist"):
    """A minimal workbook (inline strings, numbers), enough to test the reader."""
    def cell(r, c, v):
        ref = f"{chr(65 + c)}{r + 1}"
        if isinstance(v, (int, float)):
            return f'<c r="{ref}"><v>{v}</v></c>'
        from xml.sax.saxutils import escape
        return f'<c r="{ref}" t="inlineStr"><is><t>{escape(str(v))}</t></is></c>'
    data = "".join(f'<row r="{r + 1}">' + "".join(cell(r, c, v) for c, v in enumerate(row) if v is not None) + "</row>"
                   for r, row in enumerate(rows))
    m = _NS["m"]
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("xl/workbook.xml", f'<workbook xmlns="{m}" xmlns:r="{_NS["r"]}"><sheets>'
                                      f'<sheet name="{sheet}" sheetId="1" r:id="rId1"/></sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels", f'<Relationships xmlns="{_NS["rel"]}"><Relationship Id="rId1" '
                                                 'Type="worksheet" Target="worksheets/sheet1.xml"/></Relationships>')
        z.writestr("xl/worksheets/sheet1.xml", f'<worksheet xmlns="{m}"><sheetData>{data}</sheetData></worksheet>')


def selftest():
    import shutil
    import tempfile
    v = tempfile.mkdtemp()
    watch_tmp = tempfile.mkdtemp()  # the watcher's day log: never the real one
    real_log_dir = watch.log_dir
    watch.log_dir = lambda base=None: real_log_dir(base or watch_tmp)
    # nothing of the real computer: no real 'ticked in SimpleBrain' list, no real habit log
    real_cfg, real_habits = core.user_config_dir, habits.log_path
    core.user_config_dir = lambda: watch_tmp
    habits.log_path = lambda: os.path.join(watch_tmp, "habits.log")
    try:
        core.ensure_vault(v)
        vid = os.path.join(v, "media", "guitar-02.mp3")
        os.makedirs(os.path.dirname(vid))
        open(vid, "w").close()
        core.write_note("Guitar.md", "# Guitar\n\nt Session 2 due:2026-11-02\nfile:: media/guitar-02.mp3\n"
                        "https://lessons.example.com/notes.\n\nt Session 3 due:2026-11-09\nfile:: media/x.mp3\n", v)
        core.write_note("Riverside.md", "# Riverside\nfile:: card-riverside.pdf\n\nt Call Student Accounts due:2026-11-01\n", v)
        core.write_note("Python.md", "# Python\n\nt Module 1, see [[Edube]] due:2026-11-04\n- [x] done thing\n", v)
        core.write_note("Edube.md", "# Edube\nfile:: https-not-a-file.pdf\n", v)
        core.write_note("Someday.md", "t no date at all\n", v)
        core.add_local_event("2026-11-02", "08:00", "Call Riverside [[Riverside]]", v)
        core.add_local_event("2026-11-03", None, "Cafe orientation", v)
        now = datetime(2026, 11, 2, 7, 30)
        name, wrote = update(v, now)
        text = core.read_note(name, v)
        assert name == "Today.md" and wrote and MARK in text
        assert text.index("## 1. Call Student Accounts") < text.index("## 2. Session 2") < text.index("## 3. Module 1")
        assert "From [[Riverside]] · overdue" in text and f"file:: {home_short(vid)}" in text
        assert "https://lessons.example.com/notes\n" in text  # the sentence's full stop left off
        assert f"file:: {home_short(os.path.join(v, 'card-riverside.pdf'))}" in text  # nothing under the task: the note's files
        assert f"file:: {home_short(os.path.join(v, 'https-not-a-file.pdf'))}" in text  # a linked note's files come along
        assert "Session 3" not in text and "no date" not in text  # three things, never more
        assert "- 8:00 AM  Call Riverside [[Riverside]]" in text and "orientation" not in text
        assert not any(t["file"] == name for t in core.parse_tasks(v))  # it lists tasks, it doesn't copy them
        assert update(v, now) == (name, False)  # unchanged: not rewritten (no sync, no reload)
        assert first_material(v, now.date()) == vid  # the PDF isn't on disk, so the video comes first
        core.write_note("Today.md", "# Today\nmy own note\n", v)
        assert note_name(v) == "Today (SimpleBrain).md"  # a note you wrote is never overwritten
        # the 12 favorite problems: each thing says which question it feeds; with none fed, one to keep in mind
        core.write_note("12 Favorite Problems.md", "# 12 Favorite Problems\n1. How can working adults learn from "
                        "professional reading faster?\n2. How do I pay off my truck loans?\n3) What makes a good shop?\n", v)
        assert [q[1][:6] for q in questions(v)] == ["How ca", "How do", "What m"]
        text = build(v, now)
        assert "Moves your question forward: *How do I pay off my truck loans?*" not in text  # Riverside call: no shared words
        core.write_note("Loans.md", "t Call the lender about the truck loans due:2026-11-02\n", v)
        text = build(v, now)
        assert "## 3. Call the lender about the truck loans\nFrom [[Loans]] · today\n" \
               "Moves your question forward: *How do I pay off my truck loans?* ([[12 Favorite Problems]])" in text
        assert feeds("Guitar session 2, professional reading", questions(v))[1].startswith("How can")
        quiet = tempfile.mkdtemp()
        core.ensure_vault(quiet)
        core.write_note("Favorite Problems.md", "1. What makes a good operator?\n", quiet)
        core.write_note("Operator notes.md", "x\n", quiet)
        assert "## A question to keep in mind\n*What makes a good operator?*" in build(quiet, now)
        assert "Notes that touch it: [[Operator notes]]" in build(quiet, now)
        shutil.rmtree(quiet)
        # the plan workbook: its due actions come first, with the matching call card and the workbook itself
        pdir = os.path.join(v, "money-plan")
        os.makedirs(os.path.join(pdir, "cards"))
        for n in ("riverside-call.md", "car-loan-refinance.md", "jobs.md"):
            open(os.path.join(pdir, "cards", n), "w").close()
        wb = os.path.join(pdir, "Money-Plan.xlsx")
        _write_xlsx(wb, [["Actions, by date"], ["Date", "Action", "Area", "Who", "$ impact", "Status", "Notes / evidence"],
                         [46328, "8am: Call Riverside Student Accounts", "Money", "You", 35, "To do", "Avoids a fee"],
                         [46328, "Jarvis drafts the resume", "Jobs", "Jarvis", 0, "To do"],
                         [46327, "Run setup.sh", "Focus", "You", 0, "Done"],
                         [46340, "Later thing", "Life", "You", 0, "To do"]])
        core.write_note("Home.md", "# Home\nplan:: money-plan/Money-Plan.xlsx\n", v)
        assert plan_path(v) == wb and [x["text"] for x in plan_items(wb, date(2026, 11, 2))] == ["8am: Call Riverside Student Accounts"]
        text = build(v, now)
        assert text.index("## 1. 8am: Call Riverside Student Accounts\nFrom the plan (Money) · today · Avoids a fee\n"
                          f"file:: {home_short(os.path.join(pdir, 'cards', 'riverside-call.md'))}\n") >= 0
        assert text.count(f"file:: {home_short(wb)}") == 1 and "Done one from the plan? Tick it in Tasks" in text
        assert first_material(v, date(2026, 11, 2)) == os.path.join(pdir, "cards", "riverside-call.md")
        assert home_short(os.path.expanduser("~/x/y.pdf")) == os.path.join("~", "x", "y.pdf")
        assert home_short("/media/a.pdf") == "/media/a.pdf"  # outside home: as it was
        assert len(re.findall(r"^## \d\. ", text, re.M)) == 3  # still three, never more
        assert "Jarvis drafts" not in text and "Later thing" not in text and "Run setup" not in text
        core.write_note("Elsewhere.md", "# Elsewhere\n", os.path.join(v, "empty")) if os.makedirs(os.path.join(v, "empty"), exist_ok=True) is None else None
        assert plan_path(os.path.join(v, "empty")) is None  # no plan:: line, no plan: a workbook lying around is never picked up
        assert cards_for("Call the lender: request REFINANCING", wb) == [
            os.path.join(pdir, "cards", "car-loan-refinance.md")]
        bad = os.path.join(v, "bad.xlsx")
        open(bad, "w").write("not a zip")
        assert plan_items(bad) == []
        # people: the most overdue one, birthdays within a week, a dated line or a linked event counts as contact
        core.write_note("Mom.md", "# Mom\nevery:: 2 weeks\nbirthday:: 11-05\n\n10-01-2026 called, she's good\n", v)
        core.write_note("Dad.md", "# Dad\nevery:: week\n10-30-2026 Walker Supply bond talk\n", v)
        core.write_note("Scott Lyons.md", "# Scott Lyons\nevery:: 3 months\n", v)
        core.add_local_event("2026-10-29", "12:00", "Lunch with [[Mom]]", v)
        ps = {p["note"]: p for p in people(v, date(2026, 11, 2))}
        assert ps["Mom.md"]["last"] == date(2026, 10, 29) and ps["Mom.md"]["birthday"] == date(2026, 11, 5)
        assert ps["Dad.md"]["due_ratio"] < 1 and ps["Scott Lyons.md"]["last"] is None
        text = build(v, now)
        assert "## People\n[[Mom]]'s birthday on Thu Nov 5\nReach out to [[Scott Lyons]] · no contact written down yet (every 3 months)" in text
        assert "[[Dad]]" not in text.split("## People")[1].split("##")[0]  # not due yet
        assert every_text(14) == "every 2 weeks" and every_text(30) == "every month" and every_text(10) == "every 10 days"
        ev = [{"date": date(2026, 11, 2), "time": "14:00", "title": "Cafe shift"}]
        g = free_stretch(ev, date(2026, 11, 2), now=datetime(2026, 11, 2, 9, 0))
        assert (g[0].hour, g[1].hour) == (9, 14)  # from now to the shift; the shift runs to 10pm
        assert free_stretch(ev, date(2026, 11, 2), now=datetime(2026, 11, 2, 21, 30)) is None
        hl = os.path.join(v, "habits.jsonl")
        for k in range(3):
            habits.record("note", "Edube", os.path.join(v, "Edube.md"), (now.timestamp() - k * 86400 * 7), hl)
        assert "## Around now you usually open\n[[Edube]]" in build(v, now, habits_log=hl)
        empty = tempfile.mkdtemp()
        core.ensure_vault(empty)
        assert "Nothing due" in build(empty, now)
        shutil.rmtree(empty)
        # the watcher's part: the line left when time ran out comes first, and yesterday's score under it
        watch.park("Study Group: stopped at lists", now=datetime(2026, 11, 1, 20, 50))
        watch.save_day(date(2026, 11, 1), {"focus": 5400, "drift": 600, "drift_by": {}, "three": ["a", "b", "c"], "done": ["a"],
                                           "ticked": 4})
        text = build(v, datetime(2026, 11, 2, 7, 30))
        assert text.split("\n")[3] == "**Pick up here:** Study Group: stopped at lists"
        assert "Yesterday: 1 of 3 done · 4 tasks ticked" in text and "Focused" not in text
        assert "Call the lender about the truck loans" in " ".join(open_texts(v, date(2026, 11, 2)))
        # learning one thing at a time: the first step not done yet, gone once done (noticed or found in the notes)
        assert next_step(set())[:2] == (1, len(LEARN)) and "t call mom fri" in next_step(set())[2]
        assert next_step({k for k, _ in LEARN}) is None
        assert next_step({"bar_task"})[0] == 2
        quiet2 = tempfile.mkdtemp()
        core.ensure_vault(quiet2)
        core.write_note("Home.md", "# Home\nlimit:: 3h\n", quiet2)
        core.write_note("Dad.md", "# Dad\nevery:: 1 week\n", quiet2)
        assert {"limit", "people"} <= learned(quiet2, settings={"learned": ["bar_task"]})
        assert "## Learn one thing (" in build(quiet2, datetime(2026, 11, 2, 9))
        shutil.rmtree(quiet2, ignore_errors=True)
        # courses in order: the first session not opened yet; a course 'after' another waits for it; watched folders
        cv = tempfile.mkdtemp()
        core.ensure_vault(cv)
        base_dir, later_dir = os.path.join(cv, "base"), os.path.join(cv, "later")
        os.makedirs(base_dir)
        os.makedirs(later_dir)
        for f in ("guitar-10 Review.mp3", "guitar-2 Prepare.mp3", "guitar-1 Intro.mp3", "notes.txt"):
            open(os.path.join(base_dir, f), "w").close()
        open(os.path.join(later_dir, "rs-1.mp4"), "w").close()
        core.write_note("Guitar Basics.md", f"# Guitar Basics\ncourse:: {base_dir}\n", cv)
        core.write_note("Guitar Advanced.md", f"# Guitar Advanced\ncourse:: {later_dir}\nafter:: [[Guitar Basics]]\n", cv)
        assert [os.path.basename(x) for x in sessions(base_dir)] == ["guitar-1 Intro.mp3", "guitar-2 Prepare.mp3",
                                                                    "guitar-10 Review.mp3"]
        hl = os.path.join(cv, "habits.log")
        nx = next_sessions(cv, hl)
        assert [(core.note_title(n), os.path.basename(f), d, t) for n, f, d, t in nx] == \
            [("Guitar Basics", "guitar-1 Intro.mp3", 0, 3)]  # the later course waits
        for f in sessions(base_dir)[:2]:
            habits.record("file", os.path.basename(f), f, path=hl)
        assert os.path.basename(next_sessions(cv, hl)[0][1]) == "guitar-10 Review.mp3"
        habits.record("file", "x", sessions(base_dir)[2], path=hl)
        assert [core.note_title(n) for n, *_ in next_sessions(cv, hl)] == ["Guitar Advanced"]  # base done: next course
        text = build(cv, datetime(2026, 11, 2, 9), habits_log=hl)
        assert "## Up next in your courses\n[[Guitar Advanced]] · 0 of 1 done · next: rs-1" in text
        core.write_note("Videos.md", f"# Videos\nfolder:: {base_dir}\n", cv)  # a plain folder:: line is not a course
        assert "Videos" not in build(cv, datetime(2026, 11, 2, 9), habits_log=hl)
        ready = os.path.join(cv, "ready")
        os.makedirs(os.path.join(ready, "2026-11-02_reading"))
        core.write_note("Home.md", f"# Home\nwatch:: {ready}\n", cv)
        assert [os.path.basename(p) for p in fresh_in_watched(cv)] == ["2026-11-02_reading"]
        shutil.rmtree(cv, ignore_errors=True)
        # a note with several tasks: a task with nothing under it doesn't borrow another task's card
        mv = tempfile.mkdtemp()
        core.ensure_vault(mv)
        core.write_note("Plan.md", "# Plan\nt call Riverside due:2026-11-02\nfile:: cards/riverside.md\n"
                        "t screen time due:2026-11-08\nfile:: cards/phone.md\nt call loans due:2026-11-02\n", mv)
        tasks = {t["text"].split(" due")[0]: t for t in core.parse_tasks(mv)}
        assert material(tasks["call loans"], mv) == ([], [])
        assert [os.path.basename(f) for f in material(tasks["call Riverside"], mv)[0]] == ["riverside.md"]
        shutil.rmtree(mv, ignore_errors=True)
        # the same action in the plan workbook and in a note shows once
        dv = tempfile.mkdtemp()
        core.ensure_vault(dv)
        wbk = os.path.join(dv, "plan.xlsx")
        _write_xlsx(wbk, [["Date", "Action", "Status"], ["11-02-2026", "Call Riverside to stop the draft", ""]])
        core.write_note("Home.md", f"# Home\nplan:: {wbk}\n", dv)
        core.write_note("Plan.md", "# Plan\nt 9am: Call Riverside (555) 010-0199: stop the draft due:2026-11-02\nt other thing due:2026-11-02\n", dv)
        got = [t["text"] for t in today_items(dv, date(2026, 11, 2))]
        assert sum("Riverside" in g for g in got) == 1 and any("other thing" in g for g in got), got
        shutil.rmtree(dv, ignore_errors=True)
        # an example date in code (`11-02-2026 called …`) isn't a contact; a day with nothing done isn't shown as a zero
        pv = tempfile.mkdtemp()
        core.ensure_vault(pv)
        core.write_note("Dad.md", "# Dad\nevery:: 1 week\nWrite a line like `11-02-2026 talked about the bond`.\n", pv)
        assert people(pv, date(2026, 11, 2))[0]["last"] is None
        watch.save_day(date(2026, 11, 1), {"three": ["a", "b", "c"], "done": []})
        assert "Yesterday" not in build(pv, datetime(2026, 11, 2, 8))
        assert "Cafe" in plan_items(_write_xlsx(os.path.join(pv, "p.xlsx"), [["Date", "Action"], ["11-02-2026", "Cafe shift"]]) or
                                   os.path.join(pv, "p.xlsx"), date(2026, 11, 2))[0]["text"]  # & in a cell
        shutil.rmtree(pv, ignore_errors=True)
        # a workbook action ticked in SimpleBrain is done here, without typing Done in the workbook
        tv = tempfile.mkdtemp()
        core.ensure_vault(tv)
        wbk2 = os.path.join(tv, "plan.xlsx")
        _write_xlsx(wbk2, [["Date", "Action", "Status"], ["11-02-2026", "Phone Screen Time limits", ""]])
        real_cfg = core.user_config_dir
        core.user_config_dir = lambda: tv
        try:
            act = plan_items(wbk2, date(2026, 11, 2))[0]
            mark_plan_done(act)
            assert plan_items(wbk2, date(2026, 11, 2)) == []
            mark_plan_done(act, False)
            assert len(plan_items(wbk2, date(2026, 11, 2))) == 1
        finally:
            core.user_config_dir = real_cfg
        assert same_action("Phone Screen Time limits", "Phone Screen Time: downtime 11:30pm-7am due:11-08-2026")
        assert not same_action("Call Riverside to stop the draft", "Email Pat at the print shop about the invoice")
        shutil.rmtree(tv, ignore_errors=True)
        # with a plan, a task due today isn't cut before the plan's actions are weighed in
        cv2 = tempfile.mkdtemp()
        core.ensure_vault(cv2)
        _write_xlsx(os.path.join(cv2, "p.xlsx"), [["Date", "Action"], ["11-04-2026", "Sign the lease"]])
        core.write_note("Home.md", f"# Home\nplan:: {os.path.join(cv2, 'p.xlsx')}\n", cv2)
        core.write_note("N.md", "t old one due:2026-11-01\nt old two due:2026-11-02\nt old three due:2026-11-03\n"
                        "t Python module every:day due:2026-11-04\n", cv2)
        assert "Python module every:day due:2026-11-04" in [t["text"] for t in today_items(cv2, date(2026, 11, 4))]
        shutil.rmtree(cv2, ignore_errors=True)
        # a habit reads as words; with a computer-time limit, Your time says that
        hv = tempfile.mkdtemp()
        core.ensure_vault(hv)
        core.write_note("Home.md", "# Home\nlimit:: 3h\n", hv)
        core.write_note("H.md", "t Python module every:day due:2026-11-02\n", hv)
        text = build(hv, datetime(2026, 11, 2, 8))
        assert "## 1. Python module (every day)" in text and "3h 00m at the computer today" in text and "free stretch" not in text
        shutil.rmtree(hv, ignore_errors=True)
    finally:
        core.user_config_dir, habits.log_path = real_cfg, real_habits
        watch.log_dir = real_log_dir
        shutil.rmtree(watch_tmp, ignore_errors=True)
        shutil.rmtree(v, ignore_errors=True)
    print("today selftest OK")


if __name__ == "__main__":
    selftest()
