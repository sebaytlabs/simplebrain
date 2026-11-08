#!/usr/bin/env python3
"""A workday that doesn't bury you: overloaded days spread out, check-ins that follow up, people worth a word.
No Qt here.

- overload: more due by today than the three things Today shows. spread_out moves the rest (newest-due first
  stays) to the lightest days of the coming week, never onto a day with a shift, at most `per_day` a day.
- follow_ups: today's calendar events that link a note ([[Dad]]) and ended a while ago: SimpleBrain asks how it
  went, and log_contact writes your line, dated, into that note (which counts as your last contact).
- suggest_people: people you've been writing about this week but haven't been in touch with for a month, so a
  check-in can be suggested before it's overdue.

Run: python simplebrain_day.py   (selftest)
"""
import os
import re
import time
from datetime import date, datetime, timedelta

import simplebrain_core as core
import simplebrain_watch as watch

PER_DAY = 3  # the same three things Today shows: a day with more is a day that goes badly
PERSON_RE = re.compile(r"^\s*(every|birthday|phone|email)::|#person\b", re.I | re.M)
CONTACT_DATE = re.compile(r"\b(\d{1,2}[-/]\d{1,2}[-/]\d{4}|\d{4}-\d{2}-\d{2})\b")


def due_by_day(tasks):
    out = {}
    for t in tasks:
        if not t["done"] and t["due"]:
            out[t["due"]] = out.get(t["due"], 0) + 1
    return out


def overload(vault=None, today=None):
    """The open tasks due by today beyond the first PER_DAY (by due date, oldest kept): what would bury the day."""
    vault = vault or core.VAULT
    today = today or date.today()
    due = sorted((t for t in core.parse_tasks(vault) if not t["done"] and t["due"] and t["due"] <= today
                  and not t["file"].startswith("Today") and not core.REPEAT_RE.search(t["text"])),  # habits aren't overload
                 key=lambda t: (t["due"], t["file"], t["line"]))
    return due[PER_DAY:]


def lightest_days(tasks, events, today, days=7, per_day=PER_DAY):
    """Days from tomorrow on, lightest first (fewest tasks due, no shift), each with how many more it can take."""
    load = due_by_day(tasks)
    out = []
    for i in range(1, days + 1):
        d = today + timedelta(days=i)
        if any(e["date"] == d and watch.SHIFT_RE.search(e["title"]) for e in events):
            continue
        room = per_day - load.get(d, 0)
        if room > 0:
            out.append((load.get(d, 0), i, d, room))
    return [(d, room) for _, _, d, room in sorted(out)]


def spread_out(vault=None, today=None, per_day=PER_DAY):
    """Move what overloads today onto the lightest days ahead. Returns [(task text, new date)]."""
    vault = vault or core.VAULT
    today = today or date.today()
    extra = overload(vault, today)
    if not extra:
        return []
    tasks = core.parse_tasks(vault)
    slots = []
    for d, room in lightest_days(tasks, core.read_local_events(vault), today, per_day=per_day):
        slots += [d] * room
    moved = []
    for t, d in zip(extra, sorted(slots)):
        text = core.DUE_RE.sub(f"due:{d.isoformat()}", t["text"])
        if core.edit_task(t, text, vault):
            moved.append((core.DUE_RE.sub("", text).strip(), d))
    return moved


def follow_ups(vault=None, now=None, asked=(), after_h=1):
    """Today's events linking a note that ended (started more than `after_h` hours ago) and haven't been asked about:
    [{"key", "title", "note"}]. A note that already has a line dated today is taken as answered."""
    vault = vault or core.VAULT
    now = now or datetime.now()
    out = []
    for e in core.read_local_events(vault):
        if e["date"] != now.date() or not e["time"]:
            continue
        start = datetime.combine(e["date"], datetime.strptime(e["time"], "%H:%M").time())
        key = f"{e['date'].isoformat()} {e['time']} {e['title']}"
        if now - start < timedelta(hours=after_h) or key in asked:
            continue
        for link in core.parse_links(e["title"]):
            path = os.path.join(vault, link + ".md")
            if not os.path.exists(path):
                continue
            text = core.read_note(link + ".md", vault)
            if any(core.parse_date(x) == now.date() for x in CONTACT_DATE.findall(text)):
                continue
            out.append({"key": key, "title": core.WIKILINK_RE.sub(lambda m: m.group(1), e["title"]), "note": link})
            break
    return out


def log_contact(note, text, vault=None, today=None):
    """'11-02-2026 talked about the bond' at the end of their note: the record, and the last contact date."""
    vault = vault or core.VAULT
    today = today or date.today()
    body = core.read_note(note + ".md", vault).rstrip("\n")
    core.write_note(note + ".md", f"{body}\n{core.show_date(today)} {text.strip()}\n", vault)


def is_person(text):
    return bool(PERSON_RE.search(text))


def suggest_people(vault=None, today=None, recent_days=7, quiet_days=30, n=2):
    """People (notes with every::, birthday::, phone::, email:: or #person) linked from notes you changed this week
    whose last dated contact is over a month ago (or never): [(note, days since or None)]."""
    vault = vault or core.VAULT
    today = today or date.today()
    cutoff = time.time() - recent_days * 86400
    talked = {}
    for n_ in core.list_user_notes(vault):
        try:
            if os.path.getmtime(os.path.join(vault, n_)) < cutoff:
                continue
        except OSError:
            continue
        for link in core.parse_links(core.read_note(n_, vault)):
            if link + ".md" != n_:
                talked[link] = talked.get(link, 0) + 1
    out = []
    for name, k in sorted(talked.items(), key=lambda kv: -kv[1]):
        path = os.path.join(vault, name + ".md")
        if not os.path.exists(path):
            continue
        text = core.read_note(name + ".md", vault)
        if not is_person(text):
            continue
        dates = [d for x in CONTACT_DATE.findall(text) if (d := core.parse_date(x)) and d <= today]
        last = max(dates) if dates else None
        if last is None or (today - last).days >= quiet_days:
            out.append((name + ".md", (today - last).days if last else None))
    return out[:n]


def selftest():
    import shutil
    import tempfile
    v = tempfile.mkdtemp()
    try:
        core.ensure_vault(v)
        mon = date(2026, 11, 2)
        core.write_note("Work.md", "# Work\n" + "".join(f"t job {i} due:2026-11-0{1 + i % 2}\n" for i in range(7)) +
                        "t later thing due:2026-11-04\nt later two due:2026-11-04\nt later three due:2026-11-04\n", v)
        core.add_local_event("2026-11-03", "14:00", "Cafe shift 2pm-8pm", v)
        assert len(overload(v, mon)) == 4
        moved = spread_out(v, mon)
        assert len(moved) == 4 and all(d > mon for _, d in moved)
        assert all(d != date(2026, 11, 3) for _, d in moved)  # never onto a shift day
        assert all(d != date(2026, 11, 4) for _, d in moved)  # never onto a day that's already full
        load = due_by_day(core.parse_tasks(v))
        assert load[date(2026, 11, 1)] + load.get(mon, 0) == 3 and max(load.values()) <= PER_DAY
        assert overload(v, mon) == [] and spread_out(v, mon) == []
        core.write_note("Habit.md", "t module every:day due:2026-10-30\n", v)
        assert overload(v, mon) == []  # a daily habit is never moved off its days
        # check-ins: an event with a person, an hour later: how did it go? the answer goes in their note, dated
        core.write_note("Dad.md", "# Dad\nevery:: 1 week\n10-01-2026 lunch\n", v)
        core.add_local_event("2026-11-02", "12:00", "Coffee with [[Dad]]", v)
        core.add_local_event("2026-11-02", "16:00", "Call [[Dad]] about bond", v)
        f = follow_ups(v, datetime(2026, 11, 2, 13, 30))
        assert [x["title"] for x in f] == ["Coffee with Dad"] and f[0]["note"] == "Dad"
        assert follow_ups(v, datetime(2026, 11, 2, 13, 30), asked={f[0]["key"]}) == []
        log_contact("Dad", "talked about the letter of credit", v, mon)
        assert core.read_note("Dad.md", v).endswith("11-02-2026 talked about the letter of credit\n")
        assert follow_ups(v, datetime(2026, 11, 2, 18, 0)) == []  # a line dated today: already answered
        # people worth a check-in: written about this week, quiet for a month
        core.write_note("Jordan Lee.md", "# Jordan Lee\nemail:: c@example.com\n#person\n09-15-2026 account opened\n", v)
        core.write_note("Bond notes.md", "# Bond notes\nAsk [[Jordan Lee]] about the letter of credit. [[Dad]] too.\n", v)
        core.write_note("Not a person.md", "# Not a person\n", v)
        core.write_note("Misc.md", "see [[Not a person]]\n", v)
        assert suggest_people(v, mon) == [("Jordan Lee.md", 48)]
        assert is_person("x\nbirthday:: 03-14\n") and not is_person("just a note")
    finally:
        shutil.rmtree(v, ignore_errors=True)
    print("day selftest OK")


if __name__ == "__main__":
    selftest()
