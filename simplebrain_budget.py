#!/usr/bin/env python3
"""Your money, forward: a Budget note in plain words, projected day by day to the date you care about. No Qt here.

The Budget note (made the first time you open the budget; edit it like any note):

    cash:: 42.10                                   what you have now (or the newest Balance in a dropped bank export)
    until:: 12-31-2026                             how far ahead to look (60 days without it)
    + 310 Cafe pay every friday from 11-13-2026    money in: once on a date, every <weekday>, every 2 weeks from …,
    - 199 Lawyer 11-22-2026                        money out:   monthly <day>, yearly <MM-DD>
    - 20 Music app monthly 11
    goal:: 300 Python course 12-19-2026            something to pay for; lit up when the money is there that day

The view shows how long the money lasts, where it's lowest, what you end with, and which goals are funded. Click a
goal to leave it out and see what that changes. A spreadsheet with a Balance column (a bank export, the plan
workbook's cash-flow tab) is read where it is: its newest balance becomes the starting cash.

Run: python simplebrain_budget.py   (selftest)
"""
import os
import re
from datetime import date, timedelta

import simplebrain_core as core

NOTE = "Budget.md"
DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
DATE = r"(\d{1,2}[-/]\d{1,2}[-/]\d{4}|\d{4}-\d{2}-\d{2})"
LINE_RE = re.compile(r"^\s*([+-])\s*\$?(\d[\d,]*(?:\.\d+)?)\s+(.+?)\s*$")
GOAL_RE = re.compile(r"^\s*goal::\s*\$?(\d[\d,]*(?:\.\d+)?)\s+(.+?)\s*$", re.I)
CASH_RE = re.compile(r"^\s*cash::\s*\$?(-?\d[\d,]*(?:\.\d+)?)\s*$", re.I | re.M)
UNTIL_RE = re.compile(r"^\s*until::\s*" + DATE + r"\s*$", re.I | re.M)
FILE_RE = re.compile(r"^\s*budget::\s*(.+?)\s*$", re.I | re.M)
BUDGET_NAMES = re.compile(r"budget|cash|bank|transaction|statement|account|money|60-day", re.I)

TEMPLATE = """# Budget
Money in starts with +, money out with -. Dates are MM-DD-YYYY. SimpleBrain projects it forward; open it with the Money button at the top.

cash:: 0
until:: {until}

## Coming in
+ 0 Paycheck every friday from {friday}

## Going out
- 0 Phone monthly 15

## Goals
goal:: 100 Something worth saving for {goal}
"""


def amount(s):
    return float(s.replace(",", ""))


def parse_when(text, today):
    """(title, rule) from the end of a line: rule is ('once', d) / ('weekly', weekday, start, step_weeks) /
    ('monthly', day, start) / ('yearly', month, day) / ('once', today) when nothing is said."""
    t = text
    start = today
    m = re.search(r"\s+from\s+" + DATE + r"\s*$", t, re.I)
    if m:
        start = core.parse_date(m.group(1)) or today
        t = t[:m.start()]
    m = re.search(r"\s+every\s+(\d+)\s+weeks?\s*$", t, re.I)
    if m:
        return t[:m.start()].strip(), ("weekly", start.weekday(), start, max(1, int(m.group(1))))
    m = re.search(r"\s+(?:every|each)\s+(" + "|".join(DAYS) + r")s?\s*$", t, re.I)
    if m:
        return t[:m.start()].strip(), ("weekly", DAYS.index(m.group(1).lower()), start, 1)
    m = re.search(r"\s+(?:weekly)\s*$", t, re.I)
    if m:
        return t[:m.start()].strip(), ("weekly", start.weekday(), start, 1)
    m = re.search(r"\s+(?:monthly|every month)(?:\s+(?:on\s+)?(?:the\s+)?(\d{1,2})(?:st|nd|rd|th)?)?\s*$", t, re.I)
    if m:
        return t[:m.start()].strip(), ("monthly", int(m.group(1) or start.day), start)
    m = re.search(r"\s+yearly\s+(\d{1,2})[-/](\d{1,2})\s*$", t, re.I)
    if m:
        return t[:m.start()].strip(), ("yearly", int(m.group(1)), int(m.group(2)))
    m = re.search(r"\s+(?:on\s+)?" + DATE + r"\s*$", t, re.I)
    if m:
        return t[:m.start()].strip(), ("once", core.parse_date(m.group(1)) or today)
    return t.strip(), ("once", today)


def occurs(rule, d):
    kind = rule[0]
    if kind == "once":
        return d == rule[1]
    if kind == "weekly":
        _, wd, start, step = rule
        return d >= start and d.weekday() == wd and ((d - start).days // 7) % step == 0
    if kind == "monthly":
        _, day, start = rule
        last = (date(d.year + (d.month == 12), d.month % 12 + 1, 1) - timedelta(days=1)).day
        return d >= start and d.day == min(day, last)
    if kind == "yearly":
        return (d.month, d.day) == (rule[1], rule[2])
    return False


def parse(text, today=None):
    """{"cash", "until", "lines": [{"amount" (signed), "title", "rule"}], "goals": [...], "file"} from the note."""
    today = today or date.today()
    m = CASH_RE.search(text)
    u = UNTIL_RE.search(text)
    f = FILE_RE.search(text)
    out = {"cash": amount(m.group(1)) if m else 0.0, "until": (core.parse_date(u.group(1)) if u else None)
           or today + timedelta(days=60), "lines": [], "goals": [], "file": f.group(1) if f else None}
    for line in text.splitlines():
        g = GOAL_RE.match(line)
        if g:
            title, rule = parse_when(g.group(2), today)
            out["goals"].append({"amount": amount(g.group(1)), "title": title,
                                 "date": rule[1] if rule[0] == "once" else out["until"]})
            continue
        m = LINE_RE.match(line)
        if m and not line.lstrip().startswith("- ["):
            title, rule = parse_when(m.group(3), today)
            out["lines"].append({"amount": amount(m.group(2)) * (1 if m.group(1) == "+" else -1), "title": title, "rule": rule})
    return out


def _walk(b, today, goals):
    bal, series, events = b["cash"], [], []
    counted = b.get("cash_from", (None, None))[1]  # a balance from a bank export already holds that day's money
    d = today
    while d <= b["until"]:
        for ln in b["lines"]:
            if counted and d <= counted:
                continue
            if occurs(ln["rule"], d) and not (ln["rule"][0] == "once" and d < today):
                bal += ln["amount"]
                events.append((d, ln["amount"], ln["title"]))
        for g in goals:
            if g["date"] == d:
                bal -= g["amount"]
                events.append((d, -g["amount"], g["title"]))
        series.append((d, round(bal, 2)))
        d += timedelta(days=1)
    return series, events


def project(b, today=None, skip=()):
    """Day by day from today to `until`: {"series": [(date, balance)], "low": (date, balance), "end", "out_on"
    (first day below zero or None), "goals": [{…, "funded", "short"}], "events": [(date, amount, title)]}.
    Bills and pay are certain; goals are what you're saving toward: earliest first, each one is paid only if the
    money stays above zero from its day on (funded), else it's left out and says how much more it needs (short)."""
    today = today or date.today()
    paid, goals = [], []
    for g in sorted(b["goals"], key=lambda g: g["date"]):
        if g["title"] in skip:
            goals.append({**g, "funded": None, "short": 0})
            continue
        series, _ = _walk(b, today, paid + [g])
        after = [v for dd, v in series if dd >= g["date"]]
        ok = bool(after) and min(after) >= 0
        if ok:
            paid.append(g)
        goals.append({**g, "funded": ok, "short": 0 if ok or not after else round(-min(after), 2)})
    series, events = _walk(b, today, paid)
    low = min(series, key=lambda x: x[1]) if series else (today, b["cash"])
    out_on = next((dd for dd, v in series if v < 0), None)
    order = {g["title"]: i for i, g in enumerate(b["goals"])}
    return {"series": series, "low": low, "end": series[-1][1] if series else b["cash"], "out_on": out_on,
            "goals": sorted(goals, key=lambda g: order.get(g["title"], 0)), "events": events}


def runway(p, today=None):
    """0..1: how much of the way to `until` the money lasts (1 = all the way)."""
    s = p["series"]
    if not s:
        return 1.0
    if not p["out_on"]:
        return 1.0
    return max(0.0, (p["out_on"] - s[0][0]).days / max(1, len(s) - 1))


def money(v, sign=False):
    s = f"${abs(v):,.0f}" if abs(v) >= 100 else f"${abs(v):,.2f}"
    return ("-" if v < 0 else "+" if sign and v > 0 else "") + s


def summary(p, today=None):
    """One line for Today: where you end up, and the next thing that moves the money."""
    today = today or date.today()
    s = p["series"]
    if not s:
        return ""
    nxt = next(((d, a, t) for d, a, t in p["events"] if d >= today), None)
    head = f"{money(p['end'])} on {s[-1][0].strftime('%b')} {s[-1][0].day}"
    if p["out_on"]:
        head += f" · runs short {p['out_on'].strftime('%b')} {p['out_on'].day}"
    if nxt:
        when = "today" if nxt[0] == today else "tomorrow" if nxt[0] == today + timedelta(days=1) else nxt[0].strftime("%a %b ") + str(nxt[0].day)
        head += f" · next: {nxt[2]} {money(nxt[1], True)} {when}"
    return head


def is_budget_file(path):
    return os.path.splitext(path)[1].lower() in (".csv", ".xlsx") and bool(BUDGET_NAMES.search(os.path.basename(path)))


def balance_from_file(path):
    """(date, balance) of the newest row with a Balance column in a .csv or .xlsx (a bank export, a cash-flow tab)."""
    rows_by_sheet = {}
    try:
        if path.lower().endswith(".xlsx"):
            import simplebrain_today as today_mod
            rows_by_sheet = today_mod.read_xlsx(path)
        else:
            import csv
            with open(path, encoding="utf-8-sig", errors="replace", newline="") as f:
                rows_by_sheet = {"csv": list(csv.reader(f))}
    except Exception:  # an odd file is just not a source
        return None
    best = None
    for rows in rows_by_sheet.values():
        for hi, row in enumerate(rows[:15]):
            head = [str(c).strip().lower() if c is not None else "" for c in row]
            bal = next((i for i, h in enumerate(head) if "balance" in h), None)
            dat = next((i for i, h in enumerate(head) if h in ("date", "week", "day", "posted", "posting date",
                                                                "transaction date", "week of", "week ending")), None)
            if bal is None or dat is None:
                continue
            for r in rows[hi + 1:]:
                if max(bal, dat) >= len(r) or r[bal] in (None, "") or r[dat] in (None, ""):
                    continue
                v = r[dat]
                d = (date(1899, 12, 30) + timedelta(days=int(v))) if isinstance(v, float) and 20000 < v < 80000 \
                    else core.parse_date(str(v).split()[0])
                try:
                    x = float(str(r[bal]).replace("$", "").replace(",", ""))
                except ValueError:
                    continue
                if d and (best is None or d >= best[0]):
                    best = (d, x)
            break
    return best


def load(vault=None, today=None, plan=None):
    """The budget from the note, its starting cash taken from a linked spreadsheet when there's a newer balance."""
    vault = vault or core.VAULT
    today = today or date.today()
    path = os.path.join(vault, NOTE)
    text = core.read_note(NOTE, vault) if os.path.exists(path) else ""
    b = parse(text, today)
    src = core.resolve_file(b["file"], vault) if b["file"] else plan
    if src and os.path.isfile(src):
        got = balance_from_file(src)
        if got and got[0] <= today:
            b["cash"], b["cash_from"] = got[1], (src, got[0])
    return b


def ensure_note(vault=None, today=None):
    vault = vault or core.VAULT
    today = today or date.today()
    if not os.path.exists(os.path.join(vault, NOTE)):
        friday = today + timedelta(days=(4 - today.weekday()) % 7)
        core.write_note(NOTE, TEMPLATE.format(until=core.show_date(today + timedelta(days=60)), friday=core.show_date(friday),
                                              goal=core.show_date(today + timedelta(days=30))), vault)
    return NOTE


def link_file(path, vault=None):
    """Use a dropped spreadsheet as the budget's source of today's cash: a `budget::` line in the note."""
    vault = vault or core.VAULT
    ensure_note(vault)
    text = core.read_note(NOTE, vault)
    line = "budget:: " + core.file_line(path, vault).split("::", 1)[1].strip()
    # a function, not the line itself, as the replacement: a Windows path's backslashes (C:\\Users) aren't escapes
    text = FILE_RE.sub(lambda m: line, text, count=1) if FILE_RE.search(text) else text.replace("\n", "\n" + line + "\n", 1)
    core.write_note(NOTE, text, vault)


def selftest():
    import shutil
    import tempfile
    today = date(2026, 11, 1)  # a Sunday
    note = """# Budget
cash:: 42.10
until:: 12-31-2026
+ 300 Side job 11-06-2026
+ 310 Cafe pay every friday from 11-13-2026
- 420 Tuition plan monthly 28 from 12-01-2026
- 20 Music app monthly 11
- 5 Email monthly on the 15th
- 199 Lawyer 11-22-2026
- 12.50 Pet store 11-07-2026
- [ ] not a money line
goal:: 150 Spanish class 12-16-2026
goal:: 300 Python course 12-19-2026
goal:: 3000 Conference 11-20-2026
"""
    b = parse(note, today)
    assert b["cash"] == 42.10 and b["until"] == date(2026, 12, 31) and len(b["lines"]) == 7 and len(b["goals"]) == 3
    pay = next(l for l in b["lines"] if l["title"] == "Cafe pay")
    assert pay["rule"] == ("weekly", 4, date(2026, 11, 13), 1)
    assert next(l for l in b["lines"] if l["title"] == "Email")["rule"][:2] == ("monthly", 15)
    assert occurs(("monthly", 31, today), date(2026, 11, 30))  # the 31st in a 30-day month is its last day
    p = project(b, today)
    assert p["series"][0] == (today, 42.10) and p["series"][-1][0] == date(2026, 12, 31)
    conference = next(g for g in p["goals"] if g["title"] == "Conference")
    assert conference["funded"] is False and conference["short"] > 1000  # $3,000 on Nov 20 doesn't fit, and says by how much
    assert [g["title"] for g in p["goals"]] == ["Spanish class", "Python course", "Conference"]  # the note's order
    assert all(g["funded"] for g in p["goals"] if g["title"] != "Conference")  # the ones that fit light up
    assert min(v for _, v in p["series"]) >= 0 or p["out_on"]  # a goal that doesn't fit never sinks the projection
    q = project(b, today, skip={"Spanish class"})
    assert q["end"] == p["end"] + 150 and next(g for g in q["goals"] if g["title"] == "Spanish class")["funded"] is None
    assert runway(q) >= runway(p)
    odd = parse("cash:: lots\n+ 12 x every 0 weeks\n- 5 y monthly 99\ngoal:: 5 z 02-30-2026\nuntil:: 13-45-2026\n", today)
    assert project(odd, today)["series"]  # nonsense lines never take the view down
    short = project(parse("cash:: 10\n- 50 Rent 11-03-2026\n", today), today)
    assert short["out_on"] == date(2026, 11, 3) and 0 < runway(short) < 0.1
    assert summary(q, today).startswith(money(q["end"])) and "next: Side job +$300 Fri Nov 6" in summary(q, today)
    assert money(-1234.5) == "-$1,234" and money(16.2, True) == "+$16.20"
    assert is_budget_file("/x/Bank-export.csv") and is_budget_file("/x/Money-Plan.xlsx") and not is_budget_file("/x/a.csv")
    d = tempfile.mkdtemp()
    try:
        csvp = os.path.join(d, "bank.csv")
        with open(csvp, "w") as f:
            f.write("Date,Description,Amount,Balance\n10-30-2026,Coffee,-3.00,46.10\n10-31-2026,Fee,-4.00,42.10\n")
        assert balance_from_file(csvp) == (date(2026, 10, 31), 42.10)
        import simplebrain_today as T
        x = os.path.join(d, "Money-Plan.xlsx")
        T._write_xlsx(x, [["Week", "In", "Out", "Ending balance"], ["11-01-2026", 0, 0, 42.10], ["11-08-2026", 300, 12.50, 329.60]],
                      sheet="Cash Flow")
        assert balance_from_file(x) == (date(2026, 11, 8), 329.60)
        v = os.path.join(d, "v")
        core.ensure_vault(v)
        ensure_note(v, today)
        assert "cash:: 0" in core.read_note(NOTE, v) and project(load(v, today), today)["series"]
        link_file(csvp, v)
        assert load(v, today)["cash"] == 42.10 and "budget:: " in core.read_note(NOTE, v)
        link_file(x, v)
        assert core.read_note(NOTE, v).count("budget::") == 1
        real_line = core.file_line
        core.file_line = lambda path, vault=None: "file:: C:\\Users\\Sam\\Downloads\\bank.csv"  # as on Windows
        try:
            link_file(x, v)
            assert "budget:: C:\\Users\\Sam\\Downloads\\bank.csv" in core.read_note(NOTE, v)
        finally:
            core.file_line = real_line
        link_file(x, v)
        assert load(v, date(2026, 11, 10))["cash"] == 329.60
        # pay that's already in the export's balance isn't added again that day
        core.write_note(NOTE, "# Budget\ncash:: 0\nbudget:: bank.csv\n+ 300 Side job 10-31-2026\n- 5 x monthly 1\n", v)
        open(os.path.join(v, "bank.csv"), "w").write("Date,Balance\n10-31-2026,342.10\n")
        p31 = project(load(v, date(2026, 10, 31)), date(2026, 10, 31))
        assert p31["series"][0][1] == 342.10 and p31["series"][1] == (date(2026, 11, 1), 337.10)
    finally:
        shutil.rmtree(d, ignore_errors=True)
    print("budget selftest OK")


if __name__ == "__main__":
    selftest()
