#!/usr/bin/env python3
"""Linking like a pro, without a model: plain word statistics on your own notes, on this computer. No Qt here.

- backlinks_in_context: each note that links here, with the line that does it (you see why, not just who).
- unlinked_mentions: notes that name this one without a [[link]]; link_mention turns one into a link in a click.
- related: notes about the same things that aren't linked yet, by the words they share that few other notes use
  (tf-idf), with those words as the reason.
- complete: titles for the [[ you're typing, best first.

Run: python simplebrain_links.py   (selftest)
"""
import math
import os
import re
from collections import Counter

import simplebrain_core as core

GENERATED = re.compile(r"^(Today|Recommendations|Inbox|Calendar)(\s*\(.*\))?\.md$|" + re.escape(core.ANSWERS_SUFFIX) + r"\.md$")
STOP = set("""a about above after again against all also am an and any are as at be because been before being below
between both but by can could did do does doing down during each few for from further had has have having he her here
hers him his how i if in into is it its itself just me more most my no nor not now of off on once only or other our out
over own same she should so some such than that the their them then there these they this those through to too under
until up very was we were what when where which while who whom why will with would you your yours file due http https
www com org note notes see""".split())
_CACHE = {}  # path -> ((mtime_ns, size), text)


def _text(name, vault):
    path = os.path.join(vault, name)
    try:
        st = os.stat(path)
    except OSError:
        return ""
    key = (st.st_mtime_ns, st.st_size)
    hit = _CACHE.get(path)
    if hit and hit[0] == key:
        return hit[1]
    text = core.read_note(name, vault)
    _CACHE[path] = (key, text)
    return text


def notes(vault):
    return [n for n in core.list_user_notes(vault) if not GENERATED.search(n)]


def backlinks_in_context(filename, vault=None):
    """[(note, line)] for every line elsewhere that links to this note."""
    vault = vault or core.VAULT
    title = core.note_title(filename).lower()
    out = []
    for n in notes(vault):
        if n == filename:
            continue
        for line in _text(n, vault).splitlines():
            if any(l.strip().lower() == title for l in core.parse_links(line)):
                out.append((n, line.strip()))
    return out


def _mention_re(title):
    return re.compile(r"(?<![\w\[])" + re.escape(title) + r"(?![\w\]])", re.I)


def unlinked_mentions(filename, vault=None, limit=20):
    """[(note, line number, line)] where another note names this one in plain text (not inside a [[link]])."""
    vault = vault or core.VAULT
    title = core.note_title(filename)
    if len(title) < 4 or title.lower() in ("home", "inbox", "calendar", "today"):
        return []
    rx = _mention_re(title)
    out = []
    for n in notes(vault):
        if n == filename:
            continue
        for i, line in enumerate(_text(n, vault).splitlines()):
            plain = core.WIKILINK_RE.sub(lambda m: " " * len(m.group()), line)  # names inside a link don't count
            if rx.search(plain) and not line.lstrip().startswith(("file::", "#")):
                out.append((n, i, line.strip()))
                if len(out) >= limit:
                    return out
    return out


def link_mention(note, line_no, title, vault=None):
    """Turn the first plain mention of `title` on that line into [[title]]. True if the note changed."""
    vault = vault or core.VAULT
    lines = core.read_note(note, vault).split("\n")
    if not 0 <= line_no < len(lines):
        return False
    line = lines[line_no]
    spans = [m.span() for m in core.WIKILINK_RE.finditer(line)]
    for m in _mention_re(title).finditer(line):
        if any(a <= m.start() < b for a, b in spans):
            continue
        lines[line_no] = line[:m.start()] + f"[[{title}]]" + line[m.end():]
        core.write_note(note, "\n".join(lines), vault)
        return True
    return False


def words(text):
    text = core.WIKILINK_RE.sub(lambda m: m.group(1), text)
    text = re.sub(r"https?://\S+|file::.*", " ", text)
    out = []
    for w in re.findall(r"[a-zA-Z][a-zA-Z'-]{2,}", text):
        w = w.lower().strip("'-")
        if w not in STOP and len(w) > 2:
            out.append(w[:-1] if w.endswith("s") and len(w) > 4 and not w.endswith("ss") else w)
    return out


_WORDS = {}  # path -> (text it came from, Counter): re-counted only when the note changed


def _counts(x, vault):
    text = _text(x, vault)
    hit = _WORDS.get(os.path.join(vault, x))
    if hit and hit[0] is text:
        return hit[1]
    c = Counter(words(core.note_title(x) + " " + core.note_title(x) + " " + text))
    _WORDS[os.path.join(vault, x)] = (text, c)
    return c


def related(filename, vault=None, n=5):
    """[(note, [shared words])]: notes about the same things that neither links to nor from this one."""
    vault = vault or core.VAULT
    names = notes(vault)
    docs = {x: _counts(x, vault) for x in names}
    if filename not in docs:
        docs[filename] = Counter(words(core.note_title(filename) + " " + _text(filename, vault)))
    df = Counter(w for c in docs.values() for w in c)
    N = len(docs)
    idf = {w: math.log((N + 1) / (k + 0.5)) for w, k in df.items()}

    def vec(c):
        v = {w: (1 + math.log(k)) * idf[w] for w, k in c.items() if df[w] < max(3, N * 0.5)}
        norm = math.sqrt(sum(x * x for x in v.values())) or 1
        return {w: x / norm for w, x in v.items()}

    me = vec(docs[filename])
    linked = {l.lower() for l in core.parse_links(_text(filename, vault))}
    title = core.note_title(filename).lower()
    scored = []
    for x in names:
        if x == filename or core.note_title(x).lower() in linked:
            continue
        if any(l.lower() == title for l in core.parse_links(_text(x, vault))):
            continue
        v = vec(docs[x])
        score = sum(me[w] * v[w] for w in me.keys() & v.keys())
        shared = sorted(me.keys() & v.keys(), key=lambda w: -(me[w] * v[w]))
        if score >= 0.12 and len(shared) >= 2:
            scored.append((score, x, shared[:3]))
    return [(x, sh) for _, x, sh in sorted(scored, reverse=True)[:n]]


def complete(prefix, titles, n=8):
    """Titles for '[[prefix': starts-with first, then word starts, then anywhere; shortest first within each."""
    p = prefix.strip().lower()
    if not p:
        return sorted(titles, key=str.lower)[:n]
    rank = []
    for t in titles:
        tl = t.lower()
        if tl.startswith(p):
            r = 0
        elif any(w.startswith(p) for w in re.split(r"[\s\-_]+", tl)):
            r = 1
        elif p in tl:
            r = 2
        else:
            continue
        rank.append((r, len(t), t))
    return [t for _, _, t in sorted(rank)[:n]]


OPEN_LINK = re.compile(r"\[\[([^\[\]]*)$")


def typing_link(before_cursor):
    """The text after an unclosed '[[' just before the cursor, or None."""
    m = OPEN_LINK.search(before_cursor)
    return m.group(1) if m else None


def selftest():
    import shutil
    import tempfile
    v = tempfile.mkdtemp()
    try:
        core.ensure_vault(v)
        core.write_note("Walker Supply.md", "# Walker Supply\nOperator company with Dad. Warehouses downtown, permit "
                        "number, bond and letter of credit.\n", v)
        core.write_note("Bond.md", "# Bond\nThe city wants financial assurance: a bond or letter of credit for the "
                        "permit. The bank's letter of credit, signed online.\n", v)
        core.write_note("Dad.md", "# Dad\nevery:: 1 week\nTalked about [[Walker Supply]] leases today.\n", v)
        core.write_note("Week.md", "# Week\nCall the attorney about walker supply and the assignment.\n"
                        "Already linked: [[Walker Supply]] and also Walker Supply here.\n", v)
        core.write_note("Python.md", "# Python\nStudy Group exam prep: lists, loops, functions. Edube course modules.\n", v)
        core.write_note("Study Group Exam.md", "# Study Group Exam\nPython Institute exam December 19; lists, functions, modules.\n", v)
        core.write_note("Today.md", "# Today\nWalker Supply call\n", v)  # generated: never a source
        assert backlinks_in_context("Walker Supply.md", v) == [
            ("Dad.md", "Talked about [[Walker Supply]] leases today."),
            ("Week.md", "Already linked: [[Walker Supply]] and also Walker Supply here.")]
        um = unlinked_mentions("Walker Supply.md", v)
        assert [(n, i) for n, i, _ in um] == [("Week.md", 1), ("Week.md", 2)]  # lowercase too; Today never counts
        assert link_mention("Week.md", 1, "Walker Supply", v)
        assert core.read_note("Week.md", v).split("\n")[1] == "Call the attorney about [[Walker Supply]] and the assignment."
        assert link_mention("Week.md", 2, "Walker Supply", v)
        assert core.read_note("Week.md", v).split("\n")[2] == "Already linked: [[Walker Supply]] and also [[Walker Supply]] here."
        assert unlinked_mentions("Walker Supply.md", v) == [] and not link_mention("Week.md", 2, "Walker Supply", v)
        rel = related("Walker Supply.md", v)
        assert rel and rel[0][0] == "Bond.md" and {"letter", "credit"} & set(rel[0][1])  # the shared words are the reason
        assert related("Python.md", v)[0][0] == "Study Group Exam.md"
        assert all(x != "Dad.md" for x, _ in related("Walker Supply.md", v))  # already linked: not suggested
        titles = ["Walker Supply", "Python", "Study Group Exam", "Bond", "Python Notes"]
        assert complete("py", titles) == ["Python", "Python Notes"] and complete("exam", titles) == ["Study Group Exam"]
        assert complete("upp", titles) == ["Walker Supply"]
        assert typing_link("see [[Vig") == "Vig" and typing_link("see [[done]] x") is None and typing_link("[[") == ""
    finally:
        shutil.rmtree(v, ignore_errors=True)
    print("links selftest OK")


if __name__ == "__main__":
    selftest()
