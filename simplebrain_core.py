"""SimpleBrain core: the vault, notes, links, tasks, inbox and calendar.
No UI imports: the Qt app is only the UI on top of it.

Self-test: python3 simplebrain_core.py
"""
import os
import re
import sys
import math
import random
import shutil
import tempfile
import urllib.request
from datetime import date, datetime, timedelta

from dateutil.rrule import rrulestr

VERSION = "0.1.0"

VAULT = os.environ.get("SIMPLEBRAIN_VAULT") or os.path.expanduser("~/Documents/SimpleBrain")
INBOX_FILE = "Inbox.md"
CALENDAR_FILE = "Calendar.md"
ICS_CONFIG = os.path.join(VAULT, ".config")
ICS_CACHE = os.path.join(VAULT, ".calendar-cache.ics")

HOME_GUIDE = """# Home

Welcome to SimpleBrain. This is an ordinary note: change it however you like.

## How it fits together
- **Capture** (bar at the top): type a thought and press Enter. It lands in the Inbox.
- **Inbox** (bottom): file each item as a Task, Event or Note with one click, or Edit/Delete it.
- **Tasks**: every line starting `t ` in any note, like `t call the bank due:10-01-2026`. Tick it when done.
- **Shorthand**: start a line with `i ` (Inbox) or `c 10-05-2026 2pm ` (Calendar, time optional); it moves there when you save.
- **Calendar**: your events, plus a synced calendar feed if you set one in `.config`.
- **Links**: put a note's name in double square brackets to link to it. The link appears under the editor; click it to open that note, or create it if it doesn't exist yet.
- **Linked from**: under the editor, the notes that link to the one you're reading.
- **Graph**: every note and link. Click a dot to open it.
- **Answers**: under a question, write `answer:: your answer`. Every note you link to gets a "<name> - Answers" note that collects the answers from all the notes linking to it.
"""


def get_ics_url(vault=VAULT):
    """Calendar feed URL lives outside the repo, in a gitignored local
    config file (the URL itself is a bearer token - never hardcode it)."""
    path = os.path.join(vault, ".config")
    if not os.path.exists(path):
        return None
    for line in open(path, encoding="utf-8"):
        if line.startswith("ICS_URL="):
            return line[len("ICS_URL="):].strip() or None
    return None

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

def ensure_vault(vault=VAULT):
    os.makedirs(vault, exist_ok=True)
    home = os.path.join(vault, "Home.md")
    if not os.path.exists(home):
        with open(home, "w", encoding="utf-8") as f:
            f.write(HOME_GUIDE)
    for name in (INBOX_FILE, CALENDAR_FILE):
        path = os.path.join(vault, name)
        if not os.path.exists(path):
            open(path, "w", encoding="utf-8").close()
    if not os.path.exists(os.path.join(vault, ".config")):
        with open(os.path.join(vault, ".config"), "w", encoding="utf-8") as f:
            f.write("# ICS_URL=https://your-calendar-feed.ics\n")


def list_notes(vault=VAULT):
    return sorted(f for f in os.listdir(vault)
                  if f.endswith(".md") and not f.startswith("."))


def list_user_notes(vault=VAULT):
    """Notes the user writes. Inbox.md and Calendar.md are the files behind
    the Inbox and Calendar panels - listed as notes they just confuse, so
    they're hidden from the sidebar, graph and Dataview (tasks in them still
    count: parse_tasks uses list_notes)."""
    return [n for n in list_notes(vault) if n not in (INBOX_FILE, CALENDAR_FILE)]


def backlinks(filename, vault=VAULT):
    """Notes that link to this one with [[Title]]."""
    title = note_title(filename)
    return [n for n in list_user_notes(vault)
            if n != filename and title in parse_links(read_note(n, vault))]


def note_title(filename):
    return filename[:-3]


def read_note(filename, vault=VAULT):
    with open(os.path.join(vault, filename), "r", encoding="utf-8") as f:
        return f.read()


def write_note(filename, text, vault=VAULT):
    with open(os.path.join(vault, filename), "w", encoding="utf-8") as f:
        f.write(text)


def note_trash_path(filename, vault=VAULT):
    """Reversible trash: move, don't delete,
    dedup on collision instead of overwriting."""
    trash_dir = os.path.join(vault, ".trash")
    os.makedirs(trash_dir, exist_ok=True)
    dest = os.path.join(trash_dir, filename)
    base, ext = os.path.splitext(filename)
    i = 1
    while os.path.exists(dest):
        dest = os.path.join(trash_dir, f"{base} ({i}){ext}")
        i += 1
    return dest


def delete_note(filename, vault=VAULT):
    dest = note_trash_path(filename, vault)
    shutil.move(os.path.join(vault, filename), dest)
    return dest


def parse_links(text):
    return [m.group(1).strip() for m in WIKILINK_RE.finditer(text)]


def parse_tags(text):
    return sorted(set(TAG_RE.findall(text)))


def should_start_ics_fetch(sync, syncing, fetch_attempted):
    """The exact condition that had 3 real bugs in it: a fetch already in
    flight must block a new one (else concurrent threads race on
    ICS_CACHE), and "never fetched" must be a ONE-TIME trigger, not
    re-armed by every unrelated local calendar edit forever."""
    return not syncing and (sync or not fetch_attempted)


def learning_note_template(title):
    """A book-study note: Prepare / Preview / Postview / Your Questions /
    Activation / Next Steps."""
    return (
        f"# {title}\n\n"
        "[[Home]]\n\n"
        "# Prepare\n"
        "## Your Initial Purpose::\n\n\n"
        "# Preview\n"
        "## One Sentence Summary::\n\n\n"
        "# Postview\n"
        "## Trigger Words or Phrases:: (put each one in double square brackets to link it)\n\n\n"
        "# Your Questions\n"
        "(type each question after its number, its answer after answer::)\n"
        + "".join(f"{i}.\nanswer::\n\n" for i in range(1, 6)) + "\n"
        "# Activation\n"
        "## Your New Purpose, if it has changed::\n\n\n"
        "# Next Steps\n"
        "## What you'll do with this:: (one per line: t task due:MM-DD-YYYY, i for the Inbox, c MM-DD-YYYY event for the Calendar)\n"
    )


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
    return (title.strip() not in ("", ".", "..") and not BAD_TITLE_CHARS & set(title)
            and not title.endswith((".", " ")))


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
    return None


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


def note_rows(vault=VAULT):
    """One row per note: the data behind the Dataview table. No query
    language - filtering happens with a dropdown + search box in the UI."""
    texts = {n: read_note(n, vault) for n in list_user_notes(vault)}
    links = {n: sorted(set(parse_links(t))) for n, t in texts.items()}
    rows = []
    for n, text in texts.items():
        rows.append({
            "file": n,
            "title": note_title(n),
            "tags": parse_tags(text),
            "links": links[n],  # titles this note links to (may not exist yet)
            "linked_from": [m for m in texts if m != n and note_title(n) in links[m]],
            "link_count": len(links[n]),
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


def sync_answer_notes(vault=VAULT):
    """Rebuild the "<Keyword> - Answers" notes: one per [[link]] made by a
    note holding answer:: lines (not Home: it would collect everything).
    Writes only what changed, trashes one whose keyword lost its last
    answer, and never touches a same-named note the user wrote (no
    ANSWERS_MARK). Returns the files written or trashed.
    ponytail: re-reads the whole vault per call; go incremental if saves lag."""
    texts = {n: read_note(n, vault) for n in list_user_notes(vault)}
    generated = {n for n, t in texts.items() if ANSWERS_MARK in t}
    sources = [n for n in texts if n not in generated]
    answers = {n: parse_answers(texts[n]) for n in sources}
    linkers = {}  # keyword -> notes linking to it, in sidebar order
    for n in sources:
        for k in dict.fromkeys(parse_links(texts[n])):
            linkers.setdefault(k, []).append(n)
    skip = {"Home", note_title(INBOX_FILE), note_title(CALENDAR_FILE)}
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


def build_graph(vault=VAULT):
    """(nodes, edges, missing). Nodes are every note plus every [[link]] to a
    note that doesn't exist yet (`missing`, drawn faded like Obsidian; clicking
    one creates it) - without them, notes that only share a not-yet-written
    link look unconnected."""
    notes = list_user_notes(vault)
    titles = {note_title(n): n for n in notes}
    hidden = {note_title(INBOX_FILE), note_title(CALENDAR_FILE)}
    missing, edges = [], []
    for n in notes:
        for link in parse_links(read_note(n, vault)):
            target = titles.get(link)
            if target is None:
                if link in hidden or not is_safe_note_title(link):
                    continue
                target = link + ".md"
                if target not in missing:
                    missing.append(target)
            if target != n and (n, target) not in edges and (target, n) not in edges:
                edges.append((n, target))
    return notes + missing, edges, set(missing)


def parse_tasks(vault=VAULT):
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


def toggle_task(task, vault=VAULT):
    lines = read_note(task["file"], vault).splitlines()
    m = TASK_RE.match(lines[task["line"]])
    lines[task["line"]] = m.group(1) + ("t " if task["done"] else "- [x] ") + m.group(4)
    write_note(task["file"], "\n".join(lines) + "\n", vault)


def _matching_line(filename, i, regex, group, expected, vault=VAULT):
    """(lines, match) if line i of the file still holds the expected item,
    else (lines, None): the file changed since the list was drawn, and a
    stale line number would edit or delete the wrong line."""
    lines = read_note(filename, vault).splitlines()
    m = regex.match(lines[i]) if i < len(lines) else None
    return lines, (m if m and m.group(group) == expected else None)


DELETED_ITEMS = "deleted-items.md"


def _delete_line(filename, lines, i, vault=VAULT):
    """Remove line i, but log it to .trash/deleted-items.md first (same
    never-straight-to-oblivion rule as delete_note): copy it back to undo."""
    trash_dir = os.path.join(vault, ".trash")
    os.makedirs(trash_dir, exist_ok=True)
    with open(os.path.join(trash_dir, DELETED_ITEMS), "a", encoding="utf-8") as f:
        f.write(f"{lines[i]}  <!-- from {filename}, deleted {datetime.now():%Y-%m-%d %H:%M} -->\n")
    del lines[i]
    write_note(filename, "\n".join(lines) + ("\n" if lines else ""), vault)


def edit_task(task, new_text, vault=VAULT):
    """Replace a task's text, keeping its t / checkbox. False (nothing written)
    if that line no longer holds this task."""
    lines, m = _matching_line(task["file"], task["line"], TASK_RE, 4, task["text"], vault)
    if not m:
        return False
    lines[task["line"]] = m.group(1) + m.group(2) + new_text
    write_note(task["file"], "\n".join(lines) + "\n", vault)
    return True


def delete_task(task, vault=VAULT):
    """Remove a task's line from its note. False if the line changed."""
    lines, m = _matching_line(task["file"], task["line"], TASK_RE, 4, task["text"], vault)
    if not m:
        return False
    _delete_line(task["file"], lines, task["line"], vault)
    return True


def force_layout(notes, edges, width=760, height=560, iterations=150, pinned=None):
    """`pinned` (e.g. Home.md) sits fixed at the center; the rest arrange
    around it. Unbounded: a big vault spreads past width x height instead of
    piling up against the edges - the graph view zooms to fit it.
    ponytail: O(n^2) repulsion, ~0.5s at 200 notes; Barnes-Hut if vaults reach thousands."""
    if not notes:
        return {}
    idx = {n: i for i, n in enumerate(notes)}
    count = len(notes)
    xs = [random.uniform(0, width) for _ in notes]
    ys = [random.uniform(0, height) for _ in notes]
    links = [(idx[a], idx[b]) for a, b in edges if a in idx and b in idx]
    repel, link_dist, link_strength, center = 6000, 140, 0.03, 0.01
    cx, cy = width / 2, height / 2
    pin = idx.get(pinned)
    if pin is not None:
        xs[pin], ys[pin] = cx, cy
    for _ in range(iterations):
        mx, my = [0.0] * count, [0.0] * count
        for i in range(count):
            xi, yi = xs[i], ys[i]
            fx = fy = 0.0
            for j in range(i + 1, count):
                dx, dy = xi - xs[j], yi - ys[j]
                dist2 = dx * dx + dy * dy or 0.01
                k = repel / (dist2 * math.sqrt(dist2))  # repel/dist2, along the unit vector
                fx += k * dx
                fy += k * dy
                mx[j] -= k * dx
                my[j] -= k * dy
            mx[i] += fx
            my[i] += fy
        for a, b in links:
            dx, dy = xs[b] - xs[a], ys[b] - ys[a]
            dist = math.sqrt(dx * dx + dy * dy) or 0.01
            k = (dist - link_dist) * link_strength / dist
            mx[a] += k * dx
            my[a] += k * dy
            mx[b] -= k * dx
            my[b] -= k * dy
        for i in range(count):
            xs[i] += max(-10, min(10, mx[i] + (cx - xs[i]) * center))
            ys[i] += max(-10, min(10, my[i] + (cy - ys[i]) * center))
        if pin is not None:
            xs[pin], ys[pin] = cx, cy
    return {n: [xs[i], ys[i]] for n, i in idx.items()}


# -- Inbox: capture now, classify later with a click (no ::tag typing) --

def parse_inbox(vault=VAULT):
    lines = read_note(INBOX_FILE, vault).splitlines()
    return [{"line": i, "text": m.group(1)}
            for i, line in enumerate(lines) if (m := INBOX_PENDING_RE.match(line))]


def _inbox_line(text):
    """'- text', with a leading checkbox like '[x]' escaped so the item
    isn't mistaken for a filed one or a task and hidden."""
    return f"- \\{text}" if re.match(r"\[[-xX ]\]", text) else f"- {text}"


def add_inbox_item(text, vault=VAULT):
    path = os.path.join(vault, INBOX_FILE)
    with open(path, "a", encoding="utf-8") as f:
        f.write(_inbox_line(text) + "\n")


def _rewrite_inbox_line(item, new_line, vault=VAULT):
    lines = read_note(INBOX_FILE, vault).splitlines()
    lines[item["line"]] = new_line
    write_note(INBOX_FILE, "\n".join(lines) + ("\n" if lines else ""), vault)


def edit_inbox_item(item, new_text, vault=VAULT):
    """Replace a pending Inbox item's text. False (nothing written) if that
    line no longer holds this item."""
    _, m = _matching_line(INBOX_FILE, item["line"], INBOX_PENDING_RE, 1, item["text"], vault)
    if not m:
        return False
    _rewrite_inbox_line(item, _inbox_line(new_text), vault)
    return True


def delete_inbox_item(item, vault=VAULT):
    """Remove a pending Inbox item. False if the line changed."""
    lines, m = _matching_line(INBOX_FILE, item["line"], INBOX_PENDING_RE, 1, item["text"], vault)
    if not m:
        return False
    _delete_line(INBOX_FILE, lines, item["line"], vault)
    return True


def classify_as_task(item, due, vault=VAULT):
    suffix = f" due:{due}" if due else ""
    _rewrite_inbox_line(item, f"t {item['text']}{suffix}", vault)


def classify_as_event(item, event_date, event_time, vault=VAULT):
    _rewrite_inbox_line(item, f"- [-] {item['text']}", vault)
    add_local_event(event_date, event_time, item["text"], vault)


def classify_as_note(item, vault=VAULT):
    _rewrite_inbox_line(item, f"- [-] {item['text']}", vault)


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
            out.append(line)
            continue
        kind, rest = m.groups()
        if kind == "i":
            inbox.append(rest)
        else:
            ds, _, after = rest.partition(" ")
            ts, _, title = after.partition(" ")
            t = parse_time(ts) if title.strip() else None
            title = (title if t else after).strip()
            d = parse_date(ds)
            if d is None or not title:
                problems.append(f"'{line}': write it as c MM-DD-YYYY [time] title")
            elif d < today:
                problems.append(f"'{line}': {show_date(d)} is in the past")
            else:
                events.append((d.isoformat(), t, title))
                continue
            out.append(line)
    return "\n".join(out), inbox, events, problems


def write_note_with_shorthand(filename, text, vault=VAULT, today=None):
    """write_note after expand_shorthand. Inbox/Calendar get their lines only
    once the note is written (else the next save would add them twice).
    Generated Answers notes are written as-is. Returns (written text, problems)."""
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


def expand_shorthand_in_vault(vault=VAULT, today=None):
    """Same for every note (Inbox.md too: its filed tasks), catching ones
    edited outside the app or written in the old '- [ ]' format."""
    for n in list_notes(vault):
        text = read_note(n, vault)
        if any(SHORTHAND_RE.match(l) or OPEN_BOX_RE.match(l) for l in text.splitlines()):
            write_note_with_shorthand(n, text, vault, today)


# -- Calendar: local events + real ICS feed merged in one list --

def read_local_events(vault=VAULT):
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


def add_local_event(event_date, event_time, title, vault=VAULT):
    with open(os.path.join(vault, CALENDAR_FILE), "a", encoding="utf-8") as f:
        f.write(_event_line(event_date, event_time, title) + "\n")


def _event_still_there(event, lines):
    """Same stale-line guard as tasks: the line must still hold this event."""
    i = event["line"]
    return i < len(lines) and lines[i] == _event_line(event["date"].isoformat(), event["time"], event["title"])


def edit_local_event(event, event_date, event_time, title, vault=VAULT):
    """Rewrite an event in place. False (nothing written) if its line changed."""
    lines = read_note(CALENDAR_FILE, vault).splitlines()
    if not _event_still_there(event, lines):
        return False
    lines[event["line"]] = _event_line(event_date, event_time, title)
    write_note(CALENDAR_FILE, "\n".join(lines) + "\n", vault)
    return True


def delete_local_event(event, vault=VAULT):
    """False (nothing deleted) if the event's line changed."""
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


def _unfold_ics(text):
    lines = []
    for raw in text.splitlines():
        if raw.startswith((" ", "\t")) and lines:
            lines[-1] += raw[1:]
        else:
            lines.append(raw)
    return lines


def _parse_ics_dt(value):
    value = value.rstrip("Z")
    y, mo, d = int(value[0:4]), int(value[4:6]), int(value[6:8])
    if len(value) == 8:
        return datetime(y, mo, d)
    hh, mm, ss = int(value[9:11]), int(value[11:13]), int(value[13:15])
    return datetime(y, mo, d, hh, mm, ss)


def parse_ics(text, window_days=120, today=None):
    """SUMMARY/DTSTART/RRULE only (no EXDATE/RDATE/timezone conversion -
    ponytail: good enough for a personal read-only feed; add if events
    look off for a specific TZ)."""
    today = today or date.today()
    window_end = datetime.combine(today + timedelta(days=window_days), datetime.min.time())
    events = []
    block = None
    for line in _unfold_ics(text):
        if line == "BEGIN:VEVENT":
            block = {}
        elif line == "END:VEVENT":
            if block and "DTSTART" in block and "SUMMARY" in block:
                key, val = block["DTSTART"]
                all_day = "VALUE=DATE" in key and "VALUE=DATE-TIME" not in key
                start = _parse_ics_dt(val)
                title = block["SUMMARY"][1]
                if "RRULE" in block:
                    try:
                        rule = rrulestr(block["RRULE"][1], dtstart=start)
                        occurrences = rule.between(datetime.combine(today, datetime.min.time()),
                                                    window_end, inc=True)
                    except Exception:
                        occurrences = [start] if start >= datetime.combine(today, datetime.min.time()) else []
                else:
                    occurrences = [start] if datetime.combine(today, datetime.min.time()) <= start <= window_end else []
                for occ in occurrences:
                    events.append({
                        "date": occ.date(),
                        "time": None if all_day else occ.strftime("%H:%M"),
                        "title": title,
                        "source": "ics",
                    })
            block = None
        elif block is not None and ":" in line:
            key, _, val = line.partition(":")
            base_key = key.split(";")[0]
            block[base_key] = (key, val)
    return events


def fetch_ics(url=None, timeout=8):
    """Returns (text, live) - live=False means a network/parse failure fell
    back to the cached copy (or no cache/URL exists), so the caller can show
    that to the user instead of silently passing off stale data as fresh."""
    url = url or get_ics_url()
    if not url:
        return None, False
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            text = resp.read().decode("utf-8", errors="replace")
        with open(ICS_CACHE, "w", encoding="utf-8") as f:
            f.write(text)
        return text, True
    except Exception:
        if os.path.exists(ICS_CACHE):
            with open(ICS_CACHE, encoding="utf-8") as f:
                return f.read(), False
        return None, False


def upcoming_events(vault=VAULT, days=14, ics_text=None, today=None):
    """Every local event from today on, however far out (one the user typed
    must never go invisible); the synced feed only for the next `days`, since
    a recurring feed event would otherwise flood the list."""
    today = today or date.today()
    events = [e for e in read_local_events(vault) if e["date"] >= today]
    if ics_text:
        cutoff = today + timedelta(days=days)
        events += [e for e in parse_ics(ics_text, window_days=days, today=today)
                   if today <= e["date"] <= cutoff]
    events.sort(key=lambda e: (e["date"], e["time"] or ""))
    return events


# ---------- self-test (no UI/network needed) ----------

def selftest():
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

        pos = force_layout(notes, edges, 400, 300, iterations=20)
        assert set(pos) == set(notes)
        pos = force_layout(notes, edges, 400, 300, iterations=20, pinned="B.md")
        assert pos["B.md"] == [200, 150]
        # a big vault spreads out instead of piling into the box (the old clamp stacked dots on the edges)
        random.seed(0)
        many = [f"n{i}.md" for i in range(80)]
        pos = force_layout(many, [(many[0], m) for m in many[1:]], 200, 150, pinned=many[0])
        assert max(x for x, _ in pos.values()) - min(x for x, _ in pos.values()) > 400
        pts = list(pos.values())
        assert all(math.dist(p, q) >= 12 for i, p in enumerate(pts) for q in pts[i + 1:])

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

        # thought/note classification just files it, no move
        add_inbox_item("random thought", d)
        item = parse_inbox(d)[0]
        classify_as_note(item, d)
        assert parse_inbox(d) == []

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
        write_note("C.md", "[[Later]] [[Inbox]] [[a/b]]\n", d)
        write_note("D.md", "[[Later]]\n", d)
        notes, edges, missing = build_graph(d)
        assert missing == {"Later.md"} and "Later.md" in notes
        assert ("C.md", "Later.md") in edges and ("D.md", "Later.md") in edges
        assert not any("Inbox.md" in e or "a/b.md" in e for e in edges)  # hidden/unsafe skipped
        os.remove(os.path.join(d, "C.md"))
        os.remove(os.path.join(d, "D.md"))

        tmpl = learning_note_template("Deep Work")
        assert tmpl.startswith("# Deep Work\n")
        for section in ("# Prepare", "# Preview", "# Postview", "# Your Questions", "# Activation",
                        "# Next Steps"):
            assert section in tmpl
        assert tmpl.rstrip().splitlines()[-2] == "# Next Steps"  # last section
        assert parse_links(tmpl) == ["Home"]  # no accidental links (was [[brackets]])
        assert not any(TASK_RE.match(l) for l in tmpl.splitlines())  # the hint isn't a task
        blank = blank_note_template("Ideas")
        assert blank.startswith("# Ideas\n") and parse_links(blank) == ["Home"]

        # answer:: lines: paired with the question above, collected per [[keyword]]
        assert parse_answers("1. Why?\nanswer:: because\n2.\nanswer::\n# Next\nAnswer:: loose\n") == \
            [("1. Why?", "because"), ("", "loose")]
        assert parse_answers(tmpl) == []  # the template's blanks aren't answers
        write_note("Book1.md", "[[Home]] [[Focus]]\n1. How?\nanswer:: Block mornings\n", d)
        write_note("Book2.md", "[[Focus]] [[Grit]]\n1. Why?\nanswer:: Small wins\n", d)
        write_note("Book3.md", "[[Focus]]\n", d)  # linked, no answers: listed, adds nothing
        assert sync_answer_notes(d) == ["Focus - Answers.md", "Grit - Answers.md"]
        focus = read_note("Focus - Answers.md", d)
        assert "- [[Book3]]" in focus and "**1. How?**\nBlock mornings" in focus and "Small wins" in focus
        assert "### [[Book3]]" not in focus and not parse_answers(focus)
        assert not os.path.exists(os.path.join(d, "Home - Answers.md"))
        assert sync_answer_notes(d) == []  # nothing changed; generated notes aren't sources
        write_note("Book2.md", "[[Focus]]\n", d)  # answer gone: Focus rebuilt, Grit trashed
        assert sync_answer_notes(d) == ["Focus - Answers.md", "Grit - Answers.md"]
        assert "Small wins" not in read_note("Focus - Answers.md", d)
        assert "Grit - Answers.md" not in list_notes(d)
        write_note("Grit - Answers.md", "my own note\n", d)  # user-written, same name
        write_note("Book2.md", "[[Grit]]\nanswer:: x\n", d)
        assert "Grit - Answers.md" not in sync_answer_notes(d) and read_note("Grit - Answers.md", d) == "my own note\n"
        for n in ("Book1.md", "Book2.md", "Book3.md", "Focus - Answers.md", "Grit - Answers.md"):
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

        # fetch_ics: unreachable URL -> live=False, never raises. (ICS_CACHE
        # is a fixed path, not parameterized like other functions here, so
        # this can't assert on cache content - only on the live flag.)
        text, live = fetch_ics(url="http://127.0.0.1:1/does-not-exist", timeout=1)
        assert live is False

    print("selftest OK")


if __name__ == "__main__":
    selftest()
