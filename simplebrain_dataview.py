#!/usr/bin/env python3
"""Dataview queries, the way Obsidian's Dataview plugin writes them, over your SimpleBrain notes. No Qt here.

Every note is a page with the fields you write in it and the ones it has anyway:
- `Key:: value` on its own line, `[key:: value]` inside a sentence, `(key:: value)`, and YAML frontmatter at the top.
  Keys are also reachable lower-cased with spaces as dashes (`Due Date::` -> `due-date`). Values are typed: numbers,
  dates (2026-11-06 or 11-06-2026), [[links]], true/false, lists in frontmatter.
- file.name, file.path, file.folder, file.link, file.size, file.ctime, file.cday, file.mtime, file.mday, file.tags,
  file.etags, file.inlinks, file.outlinks, file.tasks, file.day (a date in the title, or a Date field).

A query (in a ```dataview block in any note, or typed in the Dataview panel):

    TABLE [WITHOUT ID] expr [AS "Name"], …     LIST [expr]     TASK
    FROM #tag | "folder" | [[Note]] (notes linking to it) | outgoing([[Note]]), with AND, OR, - and ( )
    WHERE expr          SORT expr [ASC|DESC], …          GROUP BY expr [AS name]
    FLATTEN expr [AS name]                                LIMIT n

Expressions: fields (a.b, rows.x swizzles over lists, this.field is the note the query is in), "text", numbers,
true/false/null, [[links]], [lists], date(today|tomorrow|yesterday|now|sow|eow|som|eom|soy|eoy|2026-11-06),
dur(2 days 4 hours), + - * / %, = != < > <= >=, AND OR !, and the common functions (contains, length, lower,
upper, round, min, max, sum, average, default, choice, join, split, regextest, regexmatch, replace, startswith,
endswith, date, number, string, link, dateformat, sort, reverse, unique, nonnull, flat, any, all, none, …).
Tasks (TASK) have text, completed, checked, status, due, line, path, tags, outlinks, file.

Run: python simplebrain_dataview.py   (selftest)
"""
import os
import re
from datetime import date, datetime, timedelta

import simplebrain_core as core


class DQLError(ValueError):
    """A query that can't be read: the message says where."""


class Link:
    def __init__(self, title):
        self.title = title.strip()

    @property
    def path(self):
        return self.title + ".md"

    def __eq__(self, o):
        return isinstance(o, Link) and o.title.lower() == self.title.lower() or isinstance(o, str) and o.lower() == self.title.lower()

    def __hash__(self):
        return hash(self.title.lower())

    def __lt__(self, o):
        return str(self) < str(o)

    def __str__(self):
        return f"[[{self.title}]]"

    __repr__ = __str__


# ---------- pages: what each note holds ----------

INLINE_LINE = re.compile(r"^\s*(?:[-*]\s+)?([A-Za-z0-9_][\w \-/]*?)::\s*(.*?)\s*$")
INLINE_BRACKET = re.compile(r"[\[(]([A-Za-z0-9_][\w \-/]*?)::\s*([^\]\)]*?)[\])]")
DATE_TEXT = re.compile(r"^(\d{4}-\d{2}-\d{2})(?:[T ](\d{2}):(\d{2}))?$|^(\d{1,2})[-/](\d{1,2})[-/](\d{4})$")
DATE_IN_TITLE = re.compile(r"(\d{4})-?(\d{2})-?(\d{2})")


def norm_key(k):
    return re.sub(r"[^\w\-/]", "", re.sub(r"\s+", "-", k.strip().lower()))


def typed(v):
    """A field's text as the value it is: number, date, link, bool, list of links, or text."""
    if isinstance(v, (list, dict, int, float, bool)) or v is None:
        return v
    s = str(v).strip()
    if s == "":
        return None
    if s.lower() in ("true", "false"):
        return s.lower() == "true"
    if re.fullmatch(r"-?\d+(\.\d+)?", s):
        return float(s) if "." in s else int(s)
    m = DATE_TEXT.match(s)
    if m:
        try:
            if m.group(1):
                d = date.fromisoformat(m.group(1))
                return datetime(d.year, d.month, d.day, int(m.group(2)), int(m.group(3))) if m.group(2) else d
            return date(int(m.group(6)), int(m.group(4)), int(m.group(5)))
        except ValueError:
            return s
    links = core.parse_links(s)
    if links and re.fullmatch(r"(\s*\[\[[^\]]+\]\]\s*,?)+", s):
        return Link(links[0]) if len(links) == 1 else [Link(x) for x in links]
    return s


def frontmatter(text):
    """(fields, body) from a simple YAML block at the top: key: value, key: [a, b], and '- item' lists."""
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---", 4)
    if end < 0:
        return {}, text
    out, key = {}, None
    for line in text[4:end].splitlines():
        m = re.match(r"^([A-Za-z0-9_][\w \-]*):\s*(.*)$", line)
        if m:
            key, val = m.group(1).strip(), m.group(2).strip()
            if val.startswith("[") and val.endswith("]") and not val.startswith("[["):
                out[key] = [typed(x.strip().strip("'\"")) for x in val[1:-1].split(",") if x.strip()]
            else:
                out[key] = typed(val.strip("'\"")) if val else []
        elif key and re.match(r"^\s*-\s+(.*)$", line):
            item = re.match(r"^\s*-\s+(.*)$", line).group(1).strip().strip("'\"")
            if not isinstance(out.get(key), list):
                out[key] = []
            out[key].append(typed(item))
    return out, text[end + 4:]


def fields_in(text):
    """{key: value} from frontmatter and inline fields (a key written twice becomes a list); not from code."""
    fm, body = frontmatter(text)
    body = core.without_code(body)
    out = dict(fm)
    for line in body.splitlines():
        found = INLINE_BRACKET.findall(line)
        if not found:
            m = INLINE_LINE.match(line)
            if m and not line.lstrip().lower().startswith(("http", "file::")):
                found = [m.groups()]
        for k, v in found:
            v = typed(v)
            if k in out and k not in fm:
                out[k] = (out[k] if isinstance(out[k], list) else [out[k]]) + [v]
            else:
                out[k] = v
    for k in list(out):
        nk = norm_key(k)
        if nk and nk not in out:
            out[nk] = out[k]
    return out


def all_tags(tags):
    out = []
    for t in tags:
        parts = t.split("/")
        for i in range(1, len(parts) + 1):
            x = "#" + "/".join(parts[:i])
            if x not in out:
                out.append(x)
    return out


def task_rows(n, text):
    out = []
    for i, line in enumerate(text.splitlines()):
        m = core.TASK_RE.match(line)
        if not m:
            continue
        status = (m.group(3) or " ") if m.group(2).startswith("-") else " "
        body = m.group(4)
        due = core.DUE_RE.search(body)
        out.append({"text": body, "status": status, "completed": status.lower() == "x", "checked": status != " ",
                    "line": i, "path": n, "due": core.parse_date(due.group(1)) if due else None,
                    "tags": ["#" + t for t in core.parse_tags(body)], "outlinks": [Link(x) for x in core.parse_links(body)],
                    "task": True, "fields": fields_in(body)})
    return out


_READ = {}  # note path -> ((mtime_ns, size), text, fields, tasks): a note is re-read only when it changed


def _read(n, vault):
    path = os.path.join(vault, n)
    st = os.stat(path)
    key = (st.st_mtime_ns, st.st_size)
    hit = _READ.get(path)
    if hit and hit[0] == key:
        return hit[1:]
    text = core.read_note(n, vault)
    entry = (text, fields_in(text), task_rows(n, text))
    import time
    if time.time() - st.st_mtime > 2:  # a coarse-clock drive (FAT) can show the same stamp for two quick saves
        _READ[path] = (key, *entry)
    else:
        _READ.pop(path, None)
    return entry


def pages(vault=None):
    """Every note as a page: {"file": {...}, field: value, …}."""
    vault = vault or core.VAULT
    import simplebrain_links as _links
    names = [n for n in core.list_user_notes(vault) if not _links.GENERATED.search(n)]  # Today, Answers: not yours
    cached = {}
    for n in names:
        try:
            cached[n] = _read(n, vault)
        except OSError:
            continue
    names = list(cached)
    texts = {n: cached[n][0] for n in names}
    outl = {n: [Link(x) for x in dict.fromkeys(core.parse_links(t))] for n, t in texts.items()}
    inl = {n: [] for n in names}
    titles = {core.note_title(n).lower(): n for n in names}
    for n, links in outl.items():
        for l in links:
            target = titles.get(l.title.lower())
            if target and target != n:
                inl[target].append(Link(core.note_title(n)))
    out = []
    for n in names:
        text = texts[n]
        path = os.path.join(vault, n)
        try:
            st = os.stat(path)
        except OSError:
            continue
        etags = ["#" + t for t in core.parse_tags(text)]
        f = dict(cached[n][1])
        title = core.note_title(n)
        day = None
        m = DATE_IN_TITLE.search(title)
        if m:
            try:
                day = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except ValueError:
                day = None
        if day is None and isinstance(f.get("date"), date):
            day = f["date"]
        ctime = datetime.fromtimestamp(getattr(st, "st_birthtime", None) or min(st.st_ctime, st.st_mtime))
        mtime = datetime.fromtimestamp(st.st_mtime)
        tasks = [dict(t) for t in cached[n][2]]
        page = {**f, "file": {"name": title, "path": n, "folder": os.path.dirname(n), "ext": "md", "link": Link(title),
                              "size": st.st_size, "ctime": ctime, "cday": ctime.date(), "mtime": mtime, "mday": mtime.date(),
                              "tags": all_tags([t[1:] for t in etags]), "etags": etags, "inlinks": inl[n], "outlinks": outl[n],
                              "tasks": tasks, "lists": tasks, "day": day, "frontmatter": frontmatter(text)[0]}}
        for t in tasks:
            t["file"] = page["file"]
        out.append(page)
    return out


# ---------- the query language ----------

TOKEN = re.compile(r'''\s*(?:
    (?P<str>"(?:[^"\\]|\\.)*")|
    (?P<link>\[\[[^\]]+\]\])|
    (?P<num>\d+(?:\.\d+)?)|
    (?P<op>!=|<=|>=|=>|[=<>+\-*/%!(),\[\]{}.:])|
    (?P<tag>\#[\w/\-]+)|
    (?P<name>[A-Za-z_][\w\-]*)
)''', re.X)
KEYWORDS = {"TABLE", "LIST", "TASK", "FROM", "WHERE", "SORT", "GROUP", "BY", "FLATTEN", "LIMIT", "AS", "ASC", "DESC",
            "ASCENDING", "DESCENDING", "WITHOUT", "ID", "AND", "OR", "CALENDAR"}


def tokens(text):
    out, i = [], 0
    text = text.rstrip()
    while i < len(text):
        m = TOKEN.match(text, i)
        if not m or m.end() == i:
            raise DQLError(f"can't read the query at: {text[i:i + 20]!r}")
        kind = m.lastgroup
        val = m.group(kind)
        out.append((kind, val))
        i = m.end()
    return out


class Parser:
    def __init__(self, text):
        self.t, self.i = tokens(text), 0

    def peek(self, k=0):
        return self.t[self.i + k] if self.i + k < len(self.t) else (None, None)

    def kw(self, *words):
        k, v = self.peek()
        return k == "name" and v.upper() in words

    def take(self, val=None):
        tok = self.peek()
        if tok[0] is None or (val is not None and tok[1] != val and not (tok[0] == "name" and tok[1].upper() == val)):
            raise DQLError(f"expected {val or 'more'} but found {tok[1] or 'the end'}")
        self.i += 1
        return tok

    # expressions: or > and > comparison > additive > multiplicative > unary > postfix > atom
    def expr(self):
        left = self.and_()
        while self.kw("OR"):
            self.take()
            left = ("or", left, self.and_())
        return left

    def and_(self):
        left = self.cmp()
        while self.kw("AND"):
            self.take()
            left = ("and", left, self.cmp())
        return left

    def cmp(self):
        left = self.add()
        while self.peek()[0] == "op" and self.peek()[1] in ("=", "!=", "<", ">", "<=", ">="):
            op = self.take()[1]
            left = ("cmp", op, left, self.add())
        return left

    def add(self):
        left = self.mul()
        while self.peek()[0] == "op" and self.peek()[1] in "+-" and self.peek()[1] != "":
            op = self.take()[1]
            left = ("arith", op, left, self.mul())
        return left

    def mul(self):
        left = self.unary()
        while self.peek()[0] == "op" and self.peek()[1] in ("*", "/", "%"):
            op = self.take()[1]
            left = ("arith", op, left, self.unary())
        return left

    def unary(self):
        if self.peek() == ("op", "!"):
            self.take()
            return ("not", self.unary())
        if self.peek() == ("op", "-"):
            self.take()
            return ("neg", self.unary())
        return self.postfix()

    def postfix(self):
        node = self.atom()
        while True:
            if self.peek() == ("op", "."):
                self.take()
                node = ("get", node, self.take()[1])
            elif self.peek() == ("op", "["):
                self.take()
                idx = self.expr()
                self.take("]")
                node = ("index", node, idx)
            else:
                return node

    def atom(self):
        k, v = self.peek()
        if k is None:
            raise DQLError("the query ends too soon")
        if k == "str":
            self.take()
            return ("lit", bytes(v[1:-1], "utf-8").decode("unicode_escape"))
        if k == "num":
            self.take()
            return ("lit", float(v) if "." in v else int(v))
        if k == "link":
            self.take()
            return ("lit", Link(v[2:-2].split("|")[0]))
        if k == "tag":
            self.take()
            return ("lit", v)
        if v == "(":
            self.take()
            e = self.expr()
            self.take(")")
            return e
        if v == "[":
            self.take()
            items = []
            while self.peek()[1] != "]":
                items.append(self.expr())
                if self.peek()[1] == ",":
                    self.take()
            self.take("]")
            return ("list", items)
        if k == "name":
            self.take()
            low = v.lower()
            if low in ("true", "false"):
                return ("lit", low == "true")
            if low == "null":
                return ("lit", None)
            if low in ("date", "dur") and self.peek()[1] == "(":
                raw = self.raw_until_close()
                return (low, raw)
            if self.peek()[1] == "(":
                self.take()
                args = []
                while self.peek()[1] != ")":
                    args.append(self.expr())
                    if self.peek()[1] == ",":
                        self.take()
                self.take(")")
                return ("call", low, args)
            return ("field", v)
        raise DQLError(f"didn't expect {v!r}")

    def raw_until_close(self):
        """date(…)/dur(…): the inside is read as words (date(2026-11-06), dur(2 days)) unless it's an expression."""
        self.take("(")
        depth, parts, start = 1, [], self.i
        while depth:
            k, v = self.take()
            if v == "(":
                depth += 1
            elif v == ")":
                depth -= 1
                if not depth:
                    break
            parts.append(v)
        inner = " ".join(parts)
        squeezed = re.sub(r"\s*([-:T])\s*", r"\1", inner)
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}(:\d{2})?)?|\d{1,2}-\d{1,2}-\d{4}", squeezed):
            return ("text", squeezed)
        if re.fullmatch(r"[A-Za-z]+", inner) or re.fullmatch(r"[\d.]+\s*[A-Za-z]+(\s+[\d.]+\s*[A-Za-z]+)*", inner):
            return ("text", inner)
        sub = Parser("x")  # anything else is an expression: date(file.name), dur(field)
        sub.t, sub.i = self.t[start:self.i - 1], 0
        return ("expr", sub.expr())

    # FROM sources
    def source(self):
        left = self.source_and()
        while self.kw("OR"):
            self.take()
            left = ("or", left, self.source_and())
        return left

    def source_and(self):
        left = self.source_atom()
        while self.kw("AND"):
            self.take()
            left = ("and", left, self.source_atom())
        return left

    def source_atom(self):
        k, v = self.peek()
        if v == "-" or v == "!":
            self.take()
            return ("not", self.source_atom())
        if v == "(":
            self.take()
            s = self.source()
            self.take(")")
            return s
        if k == "tag":
            self.take()
            return ("tag", v)
        if k == "str":
            self.take()
            return ("folder", v[1:-1])
        if k == "link":
            self.take()
            return ("linksto", v[2:-2])
        if k == "name" and v.lower() == "outgoing":
            self.take()
            self.take("(")
            link = self.take()[1]
            self.take(")")
            return ("outgoing", link[2:-2])
        raise DQLError(f"FROM takes #tags, \"folders\" or [[links]], not {v!r}")


def parse(text):
    """The query as {"type", "fields": [(expr, name)], "without_id", "from", "commands": [(name, …)]}."""
    lines = [l for l in text.strip().splitlines() if l.strip() and not l.strip().startswith("//")]
    p = Parser(" ".join(lines))
    if not p.kw("TABLE", "LIST", "TASK", "CALENDAR"):
        raise DQLError("a query starts with TABLE, LIST or TASK")
    q = {"type": p.take()[1].upper(), "fields": [], "without_id": False, "from": None, "commands": []}
    if q["type"] == "CALENDAR":
        raise DQLError("CALENDAR isn't supported here: the Calendar panel shows dates")
    if q["type"] == "TABLE" and p.kw("WITHOUT"):
        p.take()
        p.take("ID")
        q["without_id"] = True
    stop = ("FROM", "WHERE", "SORT", "GROUP", "FLATTEN", "LIMIT")
    if q["type"] in ("TABLE", "LIST"):
        while p.peek()[0] and not p.kw(*stop):
            start = p.i
            e = p.expr()
            name = " ".join(v for _, v in p.t[start:p.i])
            if p.kw("AS"):
                p.take()
                k, v = p.take()
                name = v[1:-1] if k == "str" else v
            q["fields"].append((e, name))
            if p.peek()[1] == ",":
                p.take()
            if q["type"] == "LIST":
                break
    if p.kw("FROM"):
        p.take()
        q["from"] = p.source()
    while p.peek()[0]:
        if p.kw("WHERE"):
            p.take()
            q["commands"].append(("where", p.expr()))
        elif p.kw("SORT"):
            p.take()
            keys = []
            while True:
                e = p.expr()
                desc = False
                if p.kw("ASC", "ASCENDING", "DESC", "DESCENDING"):
                    desc = p.take()[1].upper().startswith("DESC")
                keys.append((e, desc))
                if p.peek()[1] != ",":
                    break
                p.take()
            q["commands"].append(("sort", keys))
        elif p.kw("GROUP"):
            p.take()
            p.take("BY")
            start = p.i
            e = p.expr()
            name = "key"
            if p.kw("AS"):
                p.take()
                name = p.take()[1]
            q["commands"].append(("group", e, name))
        elif p.kw("FLATTEN"):
            p.take()
            start = p.i
            e = p.expr()
            name = " ".join(v for _, v in p.t[start:p.i])
            if p.kw("AS"):
                p.take()
                name = p.take()[1]
            q["commands"].append(("flatten", e, name))
        elif p.kw("LIMIT"):
            p.take()
            q["commands"].append(("limit", int(p.take()[1])))
        else:
            raise DQLError(f"didn't expect {p.peek()[1]!r} here")
    return q


# ---------- evaluating ----------

def special_date(word, now):
    today = now.date()
    w = word.lower()
    named = {"today": today, "now": now, "tomorrow": today + timedelta(days=1), "yesterday": today - timedelta(days=1),
             "sow": today - timedelta(days=today.weekday()), "eow": today + timedelta(days=6 - today.weekday()),
             "som": today.replace(day=1), "soy": today.replace(month=1, day=1), "eoy": today.replace(month=12, day=31)}
    if w == "eom":
        nxt = (today.replace(day=28) + timedelta(days=4)).replace(day=1)
        return nxt - timedelta(days=1)
    if w in named:
        return named[w]
    v = typed(word)
    if isinstance(v, (date, datetime)):
        return v
    return core.natural_date(word, today)


UNITS = {"s": 1, "sec": 1, "secs": 1, "second": 1, "seconds": 1, "m": 60, "min": 60, "mins": 60, "minute": 60,
         "minutes": 60, "h": 3600, "hr": 3600, "hrs": 3600, "hour": 3600, "hours": 3600, "d": 86400, "day": 86400,
         "days": 86400, "w": 604800, "wk": 604800, "week": 604800, "weeks": 604800, "mo": 2592000, "month": 2592000,
         "months": 2592000, "yr": 31536000, "year": 31536000, "years": 31536000}


def parse_dur(text):
    secs = 0.0
    found = re.findall(r"([\d.]+)\s*([A-Za-z]+)", text)
    if not found:
        return None
    for n, u in found:
        if u.lower() not in UNITS:
            return None
        secs += float(n) * UNITS[u.lower()]
    return timedelta(seconds=secs)


def get(obj, name):
    """Field access, case-insensitive and by the dashed name; on a list, every element's field (swizzling)."""
    if isinstance(obj, list):
        out = []
        for x in obj:
            v = get(x, name)
            out += v if isinstance(v, list) and isinstance(x, dict) and "rows" not in x and name == "rows" else [v]
        return out
    if isinstance(obj, Link):
        return None
    if isinstance(obj, dict):
        if name in obj:
            return obj[name]
        low = name.lower()
        for k, v in obj.items():
            if isinstance(k, str) and (k.lower() == low or norm_key(k) == low):
                return v
        if isinstance(obj.get("fields"), dict):
            return get(obj["fields"], name)
    if isinstance(obj, (date, datetime)):
        return getattr(obj, name, None)
    return None


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def as_cmp(v):
    """A value made comparable with others of its kind (dates with datetimes, links with text)."""
    if isinstance(v, datetime):
        return (2, v)
    if isinstance(v, date):
        return (2, datetime(v.year, v.month, v.day))
    if isinstance(v, bool):
        return (0, int(v))
    if isinstance(v, (int, float)):
        return (1, v)
    if isinstance(v, timedelta):
        return (3, v.total_seconds())
    if isinstance(v, Link):
        return (4, v.title.lower())
    if isinstance(v, list):
        return (6, [as_cmp(x) for x in v])
    if v is None:
        return (-1, 0)
    return (4, str(v).lower())


def compare(op, a, b):
    if op in ("=", "!="):
        eq = as_cmp(a) == as_cmp(b) if not (isinstance(a, Link) or isinstance(b, Link)) else \
            str(a.title if isinstance(a, Link) else a).lower() == str(b.title if isinstance(b, Link) else b).lower()
        return eq if op == "=" else not eq
    if a is None or b is None:
        return False
    ka, kb = as_cmp(a), as_cmp(b)
    if ka[0] != kb[0]:
        return False
    return {"<": ka < kb, ">": ka > kb, "<=": ka <= kb, ">=": ka >= kb}[op]


def truthy(v):
    if isinstance(v, (list, dict, str)):
        return len(v) > 0
    return bool(v) and v is not None


def arith(op, a, b):
    if op == "+":
        if isinstance(a, str) or isinstance(b, str):
            return f"{'' if a is None else a}{'' if b is None else b}"
        if isinstance(a, (date, datetime)) and isinstance(b, timedelta):
            return a + b
        if isinstance(a, timedelta) and isinstance(b, (date, datetime)):
            return b + a
    if op == "-" and isinstance(a, (date, datetime)) and isinstance(b, (date, datetime)):
        return as_cmp(a)[1] - as_cmp(b)[1]
    if op == "-" and isinstance(a, (date, datetime)) and isinstance(b, timedelta):
        return a - b
    if op == "*" and isinstance(a, str) and isinstance(b, int):
        return a * b
    if isinstance(a, timedelta) and isinstance(b, timedelta) and op in "+-":
        return a + b if op == "+" else a - b
    x, y = _num(a), _num(b)
    if x is None or y is None:
        return None
    try:
        return {"+": x + y, "-": x - y, "*": x * y, "/": x / y, "%": x % y}[op]
    except ZeroDivisionError:
        return None


def contains(hay, needle):
    if isinstance(hay, list):
        return any(contains(h, needle) if isinstance(h, (list, str)) and isinstance(needle, str) and not isinstance(h, list)
                   else compare("=", h, needle) for h in hay)
    if isinstance(hay, dict):
        return needle in hay
    if isinstance(hay, Link):
        hay = hay.title
    if isinstance(hay, str):
        n = needle.title if isinstance(needle, Link) else str(needle)
        return n.lower() in hay.lower() if isinstance(needle, Link) else n in hay
    return False


def fmt_date(d, pattern):
    """Luxon-style dateformat patterns (yyyy, MM, dd, MMM, MMMM, EEE, EEEE, HH, mm)."""
    rep = [("yyyy", "%Y"), ("MMMM", "%B"), ("MMM", "%b"), ("MM", "%m"), ("dd", "%d"), ("EEEE", "%A"), ("EEE", "%a"),
           ("HH", "%H"), ("mm", "%M"), ("yy", "%y")]
    out = pattern
    for a, b in rep:
        out = out.replace(a, b)
    return d.strftime(out)


def call(name, args, ctx):
    a = args
    lists = lambda v: v if isinstance(v, list) else ([] if v is None else [v])
    f = {
        "contains": lambda: contains(a[0], a[1]),
        "icontains": lambda: contains(str(a[0]).lower() if not isinstance(a[0], list) else [str(x).lower() for x in a[0]],
                                      str(a[1]).lower()),
        "econtains": lambda: a[1] in a[0] if isinstance(a[0], list) else a[0] == a[1],
        "containsword": lambda: re.search(r"\b" + re.escape(str(a[1])) + r"\b", str(a[0]), re.I) is not None,
        "length": lambda: len(a[0]) if isinstance(a[0], (list, str, dict)) else 0,
        "lower": lambda: str(a[0]).lower() if a[0] is not None else None,
        "upper": lambda: str(a[0]).upper() if a[0] is not None else None,
        "round": lambda: round(a[0], int(a[1]) if len(a) > 1 else None) if _num(a[0]) is not None else None,
        "trunc": lambda: int(a[0]) if _num(a[0]) is not None else None,
        "floor": lambda: __import__("math").floor(a[0]) if _num(a[0]) is not None else None,
        "ceil": lambda: __import__("math").ceil(a[0]) if _num(a[0]) is not None else None,
        "min": lambda: min((x for x in (lists(a[0]) if len(a) == 1 else a) if x is not None), key=as_cmp, default=None),
        "max": lambda: max((x for x in (lists(a[0]) if len(a) == 1 else a) if x is not None), key=as_cmp, default=None),
        "sum": lambda: sum(x for x in lists(a[0]) if _num(x) is not None),
        "product": lambda: __import__("math").prod(x for x in lists(a[0]) if _num(x) is not None),
        "average": lambda: (lambda xs: sum(xs) / len(xs) if xs else None)([x for x in lists(a[0]) if _num(x) is not None]),
        "default": lambda: a[1] if a[0] is None or a[0] == [] else a[0],
        "choice": lambda: a[1] if truthy(a[0]) else a[2],
        "join": lambda: (a[1] if len(a) > 1 else ", ").join(str(x) for x in lists(a[0])),
        "split": lambda: re.split(a[1], str(a[0]), maxsplit=int(a[2]) if len(a) > 2 else 0),
        "regextest": lambda: re.search(a[0], str(a[1])) is not None,
        "regexmatch": lambda: re.fullmatch(a[0], str(a[1])) is not None,
        "regexreplace": lambda: re.sub(a[1], a[2], str(a[0])),
        "replace": lambda: str(a[0]).replace(a[1], a[2]),
        "startswith": lambda: str(a[0]).startswith(str(a[1])),
        "endswith": lambda: str(a[0]).endswith(str(a[1])),
        "substring": lambda: str(a[0])[int(a[1]):(int(a[2]) if len(a) > 2 else None)],
        "truncate": lambda: (str(a[0]) if len(str(a[0])) <= int(a[1]) else str(a[0])[:int(a[1])] + (a[2] if len(a) > 2 else "...")),
        "padleft": lambda: str(a[0]).rjust(int(a[1]), a[2] if len(a) > 2 else " "),
        "padright": lambda: str(a[0]).ljust(int(a[1]), a[2] if len(a) > 2 else " "),
        "number": lambda: (lambda m: float(m.group()) if m and "." in m.group() else int(m.group()) if m else None)(
            re.search(r"-?\d+(\.\d+)?", str(a[0]))) if a[0] is not None else None,
        "string": lambda: "" if a[0] is None else str(a[0]),
        "link": lambda: Link(str(a[0]).removesuffix(".md")),
        "date": lambda: special_date(a[0], ctx["now"]) if isinstance(a[0], str) else a[0],
        "dur": lambda: parse_dur(str(a[0])),
        "dateformat": lambda: fmt_date(a[0], a[1]) if isinstance(a[0], (date, datetime)) else None,
        "striptime": lambda: a[0].date() if isinstance(a[0], datetime) else a[0],
        "typeof": lambda: type(a[0]).__name__.replace("str", "string").replace("int", "number").replace("float", "number"),
        "list": lambda: list(a),
        "sort": lambda: sorted(lists(a[0]), key=as_cmp),
        "reverse": lambda: list(reversed(lists(a[0]))),
        "unique": lambda: list(dict.fromkeys(lists(a[0]))),
        "nonnull": lambda: [x for x in lists(a[0]) if x is not None],
        "firstvalue": lambda: next((x for x in lists(a[0]) if x is not None), None),
        "flat": lambda: [y for x in lists(a[0]) for y in (x if isinstance(x, list) else [x])],
        "slice": lambda: lists(a[0])[int(a[1]) if len(a) > 1 else 0:(int(a[2]) if len(a) > 2 else None)],
        "any": lambda: any(truthy(x) for x in (lists(a[0]) if len(a) == 1 else a)),
        "all": lambda: all(truthy(x) for x in (lists(a[0]) if len(a) == 1 else a)),
        "none": lambda: not any(truthy(x) for x in (lists(a[0]) if len(a) == 1 else a)),
        "extract": lambda: {k: get(a[0], k) for k in a[1:]},
        "meta": lambda: {"path": a[0].path, "display": a[0].title} if isinstance(a[0], Link) else None,
        "currencyformat": lambda: f"${a[0]:,.2f}" if _num(a[0]) is not None else None,
    }.get(name)
    if f is None:
        raise DQLError(f"there's no function called {name}()")
    try:
        return f()
    except (IndexError, TypeError, ValueError, re.error, AttributeError):
        return None


def ev(node, row, ctx):
    kind = node[0]
    if kind == "lit":
        return node[1]
    if kind == "list":
        return [ev(x, row, ctx) for x in node[1]]
    if kind == "field":
        name = node[1]
        if name.lower() == "this":
            return ctx.get("this")
        v = get(row, name)
        if v is None and name.lower() == "rows":
            return None
        return v
    if kind == "get":
        base = ev(node[1], row, ctx)
        if isinstance(base, Link):
            base = ctx["by_title"].get(base.title.lower())
        return get(base, node[2])
    if kind == "index":
        base, idx = ev(node[1], row, ctx), ev(node[2], row, ctx)
        if isinstance(base, list) and isinstance(idx, int):
            return base[idx] if -len(base) <= idx < len(base) else None
        return get(base, str(idx))
    if kind == "and":
        return truthy(ev(node[1], row, ctx)) and truthy(ev(node[2], row, ctx))
    if kind == "or":
        return truthy(ev(node[1], row, ctx)) or truthy(ev(node[2], row, ctx))
    if kind == "not":
        return not truthy(ev(node[1], row, ctx))
    if kind == "neg":
        v = ev(node[1], row, ctx)
        return -v if _num(v) is not None else None
    if kind == "cmp":
        return compare(node[1], ev(node[2], row, ctx), ev(node[3], row, ctx))
    if kind == "arith":
        return arith(node[1], ev(node[2], row, ctx), ev(node[3], row, ctx))
    if kind == "call":
        return call(node[1], [ev(x, row, ctx) for x in node[2]], ctx)
    if kind in ("date", "dur"):
        sub = node[1]
        val = sub[1] if sub[0] == "text" else ev(sub[1], row, ctx)
        if kind == "date":
            return special_date(val, ctx["now"]) if isinstance(val, str) else val
        return parse_dur(str(val)) if val is not None else None
    raise DQLError(f"can't work out {kind}")


def in_source(src, page, ctx):
    if src is None:
        return True
    kind = src[0]
    if kind == "and":
        return in_source(src[1], page, ctx) and in_source(src[2], page, ctx)
    if kind == "or":
        return in_source(src[1], page, ctx) or in_source(src[2], page, ctx)
    if kind == "not":
        return not in_source(src[1], page, ctx)
    f = page["file"]
    if kind == "tag":
        return src[1].lower() in [t.lower() for t in f["tags"]]
    if kind == "folder":
        folder = src[1].strip("/")
        return folder == "" or f["folder"] == folder or f["folder"].startswith(folder + "/") or f["name"] == folder
    if kind == "linksto":  # notes that link to it (and the note itself, as Dataview does)
        t = src[1].split("|")[0].strip().lower()
        return f["name"].lower() == t or any(l.title.lower() == t for l in f["outlinks"])
    if kind == "outgoing":
        target = ctx["by_title"].get(src[1].lower())
        return bool(target) and any(l.title.lower() == f["name"].lower() for l in target["file"]["outlinks"])
    return False


def run(query, vault=None, this=None, now=None, all_pages=None):
    """Run a query. Returns {"type", "headers", "rows": [[cells]], "items": [(page or task, extra)], "groups"}.
    For TASK, items are the task rows (each knows its note and line, so a tick can be written back)."""
    q = parse(query) if isinstance(query, str) else query
    now = now or datetime.now()
    ps = all_pages if all_pages is not None else pages(vault)
    by_title = {p["file"]["name"].lower(): p for p in ps}
    ctx = {"now": now, "by_title": by_title, "this": by_title.get(core.note_title(this).lower()) if this else None}
    rows = [p for p in ps if in_source(q["from"], p, ctx)]
    if q["type"] == "TASK":
        rows = [t for p in rows for t in p["file"]["tasks"]]
    grouped = None
    for cmd in q["commands"]:
        if cmd[0] == "where":
            rows = [r for r in rows if truthy(ev(cmd[1], r, ctx))]
        elif cmd[0] == "sort":
            for e, desc in reversed(cmd[1]):  # stable: the last key first
                nulls = [r for r in rows if ev(e, r, ctx) is None]
                vals = [r for r in rows if ev(e, r, ctx) is not None]
                vals.sort(key=lambda r: as_cmp(ev(e, r, ctx)), reverse=desc)
                rows = vals + nulls
        elif cmd[0] == "limit":
            rows = rows[:cmd[1]]
        elif cmd[0] == "flatten":
            out = []
            for r in rows:
                v = ev(cmd[1], r, ctx)
                for x in (v if isinstance(v, list) else [v]):
                    out.append({**r, cmd[2]: x})
            rows = out
        elif cmd[0] == "group":
            groups = {}
            for r in rows:
                k = ev(cmd[1], r, ctx)
                key = str(k) if isinstance(k, (list, dict)) else k
                groups.setdefault(key, {"key": k, cmd[2]: k, "rows": []})["rows"].append(r)
            rows = list(groups.values())
            grouped = cmd[2]
    out = {"type": q["type"], "headers": [], "rows": [], "items": rows, "grouped": grouped}
    if q["type"] == "TABLE":
        id_name = "Group" if grouped else "File"
        out["headers"] = ([] if q["without_id"] else [id_name if not grouped else grouped]) + [n for _, n in q["fields"]]
        for r in rows:
            first = r.get(grouped) if grouped else r["file"]["link"]
            out["rows"].append(([] if q["without_id"] else [first]) + [ev(e, r, ctx) for e, _ in q["fields"]])
    elif q["type"] == "LIST":
        for r in rows:
            first = r.get(grouped) if grouped else r["file"]["link"]
            extra = ev(q["fields"][0][0], r, ctx) if q["fields"] else None
            out["rows"].append([first] + ([extra] if q["fields"] else []))
    else:
        out["rows"] = [[r["text"], r["file"]["link"]] for r in rows] if not grouped else \
            [[g.get(grouped), len(g["rows"])] for g in rows]
    return out


def show(v):
    """A value as text for a table cell."""
    if v is None:
        return "-"
    if isinstance(v, bool):
        return "✓" if v else "✗"
    if isinstance(v, datetime):
        return v.strftime("%m-%d-%Y %H:%M") if (v.hour, v.minute) != (0, 0) else v.strftime("%m-%d-%Y")
    if isinstance(v, date):
        return v.strftime("%m-%d-%Y")
    if isinstance(v, timedelta):
        d = v.days
        h = v.seconds // 3600
        return (f"{d} days" if d else "") + (f" {h} hours" if h else "") or f"{int(v.total_seconds())} s"
    if isinstance(v, float):
        return f"{v:g}"
    if isinstance(v, list):
        return ", ".join(show(x) for x in v)
    if isinstance(v, dict):
        return v.get("name") or ", ".join(f"{k}: {show(x)}" for k, x in v.items())
    return str(v)


BLOCK = re.compile(r"^```dataview[ \t]*\n(.*?)^```[ \t]*$", re.S | re.M)


def blocks(text):
    """The ```dataview queries written in a note."""
    return [m.group(1).strip() for m in BLOCK.finditer(text)]


QUERY_START = re.compile(r"^\s*(TABLE|LIST|TASK)\b", re.I)


def is_query(text):
    return bool(QUERY_START.match(text or ""))


def common_fields(vault=None, at_least=2, n=4, all_pages=None):
    """Field names used in at least two notes, most used first: the Dataview panel shows them as columns by itself."""
    ps = all_pages if all_pages is not None else pages(vault)
    count = {}
    for p in ps:
        seen = set()
        for k in p:
            if k == "file" or not isinstance(k, str) or norm_key(k) in seen:
                continue
            seen.add(norm_key(k))
            count[norm_key(k)] = count.get(norm_key(k), 0) + 1
    return [k for k, c in sorted(count.items(), key=lambda kv: (-kv[1], kv[0])) if c >= at_least][:n]


def selftest():
    import shutil
    import tempfile
    v = tempfile.mkdtemp()
    now = datetime(2026, 11, 2, 9, 0)
    try:
        core.ensure_vault(v)
        core.write_note("Walker Supply.md", "# Walker Supply\nstatus:: active\npriority:: 1\ndue:: 2026-11-04\nowner:: [[Dad]]\n"
                        "#project #work/retail\nt sign the lease due:2026-11-04\n- [x] file the permit\n", v)
        core.write_note("Sebayt Labs.md", "---\ntags: [store]\nstatus: paused\npriority: 3\naliases:\n  - Studio\n---\n"
                        "# Sebayt Labs\n#project\nRevenue so far: [revenue:: 29.99] and [rating:: 4]\nt record first video due:2026-11-09\n", v)
        core.write_note("Study Group.md", "# Study Group\nstatus:: active\npriority:: 2\ndue:: 12-19-2026\nDue Date:: 2026-12-19\n#cert\n"
                        "see [[Walker Supply]]\nt module 2 due:2026-11-02\n", v)
        core.write_note("Dad.md", "# Dad\nevery:: 1 week\n#person\n[[Walker Supply]] together\n", v)
        core.write_note("2026-11-01 Journal.md", "# Journal\nmood:: good\nhours:: 3\n", v)
        ps = pages(v)
        by = {p["file"]["name"]: p for p in ps}
        assert by["Walker Supply"]["status"] == "active" and by["Walker Supply"]["priority"] == 1
        assert by["Walker Supply"]["due"] == date(2026, 11, 4) and by["Walker Supply"]["owner"] == Link("Dad")
        assert by["Study Group"]["due"] == date(2026, 12, 19) and by["Study Group"]["due-date"] == date(2026, 12, 19)  # US date, normalized key
        assert by["Sebayt Labs"]["status"] == "paused" and by["Sebayt Labs"]["revenue"] == 29.99 and by["Sebayt Labs"]["aliases"] == ["Studio"]
        assert "#work" in by["Walker Supply"]["file"]["tags"] and "#work/retail" in by["Walker Supply"]["file"]["tags"]
        assert Link("Study Group") in by["Walker Supply"]["file"]["inlinks"] and Link("Dad") in by["Walker Supply"]["file"]["inlinks"]
        assert by["2026-11-01 Journal"]["file"]["day"] == date(2026, 11, 1)
        core.write_note("Today.md", "# Today\n[[Walker Supply]]\n", v)
        assert "Today" not in {p["file"]["name"] for p in pages(v)}  # SimpleBrain's own Today isn't one of your notes
        os.remove(os.path.join(v, "Today.md"))
        # TABLE with FROM, WHERE, SORT, AS
        r = run('TABLE status, priority AS "P", due FROM #project WHERE status != "done" SORT priority DESC', v, now=now)
        assert r["headers"] == ["File", "status", "P", "due"]
        assert [x[0].title for x in r["rows"]] == ["Sebayt Labs", "Walker Supply"] and r["rows"][1][2] == 1
        r = run("TABLE WITHOUT ID file.link AS Note, due - date(today) AS Left FROM #project OR #cert WHERE due SORT due", v, now=now)
        assert r["headers"] == ["Note", "Left"] and [x[0].title for x in r["rows"]] == ["Walker Supply", "Study Group"]
        assert r["rows"][0][1] == timedelta(days=2)
        # LIST, links as sources, outgoing(), negation, functions, date literals
        assert [x[0].title for x in run("LIST FROM [[Walker Supply]] SORT file.name", v, now=now)["rows"]] == ["Dad", "Study Group", "Walker Supply"]
        assert [x[0].title for x in run("LIST FROM outgoing([[Study Group]])", v, now=now)["rows"]] == ["Walker Supply"]
        assert [x[0].title for x in run("LIST FROM #project AND -#work", v, now=now)["rows"]] == ["Sebayt Labs"]
        assert [x[0].title for x in run('LIST WHERE contains(file.tags, "#person")', v, now=now)["rows"]] == ["Dad"]
        assert [x[0].title for x in run("LIST WHERE due AND due < date(today) + dur(1 week)", v, now=now)["rows"]] == ["Walker Supply"]
        assert run('LIST status FROM #cert', v, now=now)["rows"][0][1] == "active"
        assert [x[0].title for x in run('LIST WHERE file.day = date(2026-11-01)', v, now=now)["rows"]] == ["2026-11-01 Journal"]
        assert run("TABLE length(file.inlinks) AS links, upper(status) FROM #project SORT file.name", v, now=now)["rows"][1][1:] == [2, "ACTIVE"]
        assert run("TABLE choice(priority < 2, \"now\", \"later\") AS when FROM #project SORT file.name", v, now=now)["rows"][0][1] == "later"
        assert run("TABLE default(rating, 0) AS r FROM #project SORT file.name", v, now=now)["rows"][1][1] == 0
        # TASK, GROUP BY, FLATTEN, LIMIT, this
        t = run("TASK WHERE !completed AND due <= date(today) + dur(2 days)", v, now=now)
        assert sorted(x[0] for x in t["rows"]) == ["module 2 due:2026-11-02", "sign the lease due:2026-11-04"]
        assert all(i["path"] and isinstance(i["line"], int) for i in t["items"])  # each knows where to tick it
        g = run("TABLE length(rows) AS n FROM #project OR #cert GROUP BY status", v, now=now)
        assert sorted((show(x[0]), x[1]) for x in g["rows"]) == [("active", 2), ("paused", 1)]
        g = run("TABLE rows.file.name AS notes WHERE status GROUP BY status SORT key", v, now=now)
        assert g["rows"][0][0] == "active" and sorted(g["rows"][0][1]) == ["Study Group", "Walker Supply"]
        f = run("TABLE T FROM #project FLATTEN file.etags AS T SORT file.name", v, now=now)
        assert [show(x[1]) for x in f["rows"]] == ["#project", "#project", "#work/retail"]
        assert len(run("LIST LIMIT 2", v, now=now)["rows"]) == 2
        assert [x[0].title for x in run("LIST WHERE contains(file.outlinks, this.file.link) SORT file.name", v, now=now, this="Walker Supply.md")["rows"]] == ["Dad", "Study Group"]
        assert [x[0].title for x in run("LIST WHERE contains(this.file.inlinks, file.link) SORT file.name", v, now=now,
                                        this="Walker Supply.md")["rows"]] == ["Dad", "Study Group"]
        assert run("TABLE [[Walker Supply]].status AS s FROM #cert", v, now=now)["rows"][0][1] == "active"  # a linked note's field
        # errors say what's wrong; blocks are found in notes; the panel's automatic columns
        for bad, why in (("SELECT x", "starts with TABLE"), ("LIST FROM 3", "FROM takes"), ("LIST WHERE nosuch(1)", "no function"),
                         ('LIST WHERE status = "x', "can't read")):
            try:
                run(bad, v, now=now)
                raise AssertionError(bad)
            except DQLError as e:
                assert why in str(e), (bad, e)
        assert blocks("x\n```dataview\nLIST FROM #project\n```\ny\n```dataview\nTASK\n```\n") == ["LIST FROM #project", "TASK"]
        assert common_fields(v) == ["priority", "status", "due"]
        assert is_query("table status") and is_query("  LIST") and not is_query("tables I own")
        core.write_note("Study Group.md", core.read_note("Study Group.md", v).replace("status:: active", "status:: done"), v)
        assert next(p for p in pages(v) if p["file"]["name"] == "Study Group")["status"] == "done"  # a changed note is re-read
        assert show(date(2026, 11, 4)) == "11-04-2026" and show([Link("A"), 2]) == "[[A]], 2" and show(None) == "-"
    finally:
        shutil.rmtree(v, ignore_errors=True)
    print("dataview selftest OK")


if __name__ == "__main__":
    selftest()
