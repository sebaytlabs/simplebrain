"""Book recommendations from the keywords in your notes, via Open Library. No UI imports.

A book is a note with a "Trigger Words or Phrases::" section (what New Learning Note makes) or a
link to [[Learning]]. Its [[keywords]] steer the search; the more books you add, the better the
picks. The result is an ordinary note, Recommendations.md, rebuilt in the background.

Privacy: the only thing sent over the network is one keyword per search, to openlibrary.org.
Note text and book titles never leave the machine.

Self-test: python3 simplebrain_recommend.py
"""
import difflib
import hashlib
import json
import math
import os
import random
import re
import tempfile
import time
import urllib.parse
import urllib.request
from collections import Counter
from datetime import date, datetime

import simplebrain_core as core

OUT_NAME = "Recommendations.md"
STATE_NAME = ".recommend-state"  # a dotfile: the app's note list ignores it, and it travels with the vault
VERSION = 1  # bump when the output format changes, so the skip check rebuilds once
MIN_WANT = 5       # drop books almost nobody has shelved; raise if picks are weak
CORE, STRETCH = 10, 5   # picks that fit your taste / picks from further out
CORE_POOL = 30     # core is sampled from the top N matches, not always the top 10
MAX_QUERIES = 12   # one request each, top-weighted keywords only
BUDGET = 40        # seconds of searching before settling for what came back
# catalog labels, not topics (all seen in Open Library data)
JUNK = {"popular works", "social aspects", "aspect social", "new york times bestseller",
        "life", "character", "general", "english", "language", "english language", "classics",
        "nonfiction", "specimens", "miniature books", "early works to 1800", "large type books",
        "accessible book", "protected daisy", "in library", "learning", "home"}
JUNK_PREFIX = ("nyt:", "reading level", "textbooks for", "study and teaching", "juvenile")
TRIGGERS = re.compile(r"^#+ *trigger words.*?$(.*?)(?=^#|\Z)", re.S | re.M | re.I)


def _links(text):
    """Link targets, lowercased; [[a|alias]] and [[a#heading]] reduce to a."""
    return [l.split("|")[0].split("#")[0].strip().lower() for l in core.WIKILINK_RE.findall(text)]


def _keep(k):
    # ponytail: non-ASCII drops accented foreign tags; plain-ASCII foreign tags ("psychologie") pass
    return bool(k) and k.isascii() and k not in JUNK and not k.startswith(JUNK_PREFIX)


def books(vault):
    """{title: [keywords]} for every book note in the vault."""
    found = {}
    for n in core.list_user_notes(vault):
        title = core.note_title(n)
        if n == OUT_NAME or title.lower() == "learning":
            continue
        text = core.read_note(n, vault)
        if core.ANSWERS_MARK in text:
            continue
        section = TRIGGERS.search(text)
        if not section and "learning" not in _links(text):
            continue
        pool = _links(section.group(1)) if section else _links(text)
        found[title] = [k for k in dict.fromkeys(pool) if _keep(k)]
    return found


def open_library_search(keyword, timeout=20):
    q = urllib.parse.urlencode({
        "q": f'subject:"{keyword.replace(chr(34), " ")}" AND language:eng', "sort": "want_to_read",
        "limit": 40, "fields": "key,title,author_name,subject,want_to_read_count"})
    req = urllib.request.Request(f"https://openlibrary.org/search.json?{q}",
                                 headers={"User-Agent": "SimpleBrain-recommender/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)["docs"]


def _norm(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _latin(title):
    """Work-level language:eng still lets in foreign editions; reject non-Latin titles."""
    return all(c.isascii() or ord(c) < 0x250 for c in title)


def _owned(title, have):
    """'Unfu*k Yourself' (Open Library) must equal 'Unfuck Yourself' (vault); subtitles too."""
    t = _norm(title)
    return any((len(h) >= 5 and (h in t or t in h))
               or difflib.SequenceMatcher(None, t, h).ratio() > 0.85 for h in have)


def _write_atomic(path, text):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    for attempt in range(5):  # Windows refuses to replace a file another program has open
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            time.sleep(0.2)
    with open(path, "w", encoding="utf-8", newline="\n") as f:  # last resort: not atomic, but it lands
        f.write(text)
    os.remove(tmp)


def _set_status(out, msg):
    """Change the '> ' status line of an existing note, so a failure shows up in the app."""
    if os.path.exists(out):
        with open(out, encoding="utf-8", errors="replace") as f:
            text = f.read()
        _write_atomic(out, re.sub(r"^> .*$", lambda _: "> " + msg, text, count=1, flags=re.M))


def build(mine, cands, today, now):
    """The note text: pure, so it can be tested without a network."""
    weights = Counter(k for kws in mine.values() for k in kws)  # repeats count more
    need = min(5, 2 + len(weights) // 15) if len(weights) >= 2 else 1
    # whole-word match, optional plural: "habit" hits "habits" / "habit breaking", not "inhabit"
    pat = {k: re.compile(r"(?<!\w)" + re.escape(k) + r"(?:s|es)?(?!\w)") for k in weights}
    subs = {k: " | ".join(d.get("subject", [])).lower() for k, d in cands.items()}
    # specificity: a keyword found on most candidates counts less than a rare one
    idf = {k: math.log(1 + len(cands) / max(1, sum(bool(pat[k].search(s)) for s in subs.values())))
           for k in weights}
    picks = []
    for key, d in cands.items():
        hit = [k for k in weights if pat[k].search(subs[key])]
        if len(hit) >= need:
            picks.append((sum(weights[k] * idf[k] for k in hit), d["want_to_read_count"], d["title"],
                          (d.get("author_name") or ["?"])[0], hit))
    picks.sort(key=lambda p: (-p[0], -p[1], p[2]))
    # same picks all day (so a restart doesn't churn), different tomorrow; stretch comes from the tail
    rng = random.Random(today.isoformat())
    pool = picks[:CORE_POOL]
    core_picks = sorted(rng.sample(pool, min(CORE, len(pool))), key=lambda p: (-p[0], p[2]))
    tail = picks[CORE_POOL:]
    stretch = rng.sample(tail, min(STRETCH, len(tail)))

    def row(p):
        return f"- {p[2]}, {p[3]}: matches " + " ".join(f"[[{k}]]" for k in p[4])

    lines = ["# Recommendations", "",
             f"> Updated {now:%Y-%m-%d %H:%M} from {len(mine)} books, {len(weights)} keywords.", "",
             "## For you"] + ([row(p) for p in core_picks] or ["- Nothing matched yet. Add books or keywords."])
    if stretch:
        lines += ["", "## Stretch (further from your usual)"] + [row(p) for p in stretch]
    return "\n".join(lines) + "\n", len(core_picks), len(stretch)


def refresh(vault=None, search=None, force=False, today=None, now=None):
    """Rebuild Recommendations.md for a vault. Safe to call from a background thread (it takes
    the vault as an argument and touches no globals). Returns a short result string; never raises
    for network trouble - a failed refresh keeps the old list and says so in the note itself."""
    vault = vault or core.VAULT
    search = search or open_library_search
    today, now = today or date.today(), now or datetime.now()
    out, state = os.path.join(vault, OUT_NAME), os.path.join(vault, STATE_NAME)
    mine = books(vault)
    if not mine:
        return "no books"
    sig = hashlib.sha256(json.dumps([VERSION, sorted(mine.items()), today.isoformat()]).encode()).hexdigest()
    if not force and os.path.exists(out) and os.path.exists(state):
        with open(state, encoding="utf-8") as f:
            if f.read() == sig:
                return "unchanged"

    weights = Counter(k for kws in mine.values() for k in kws)
    have = {_norm(t) for t in mine}
    cands, failed = {}, 0
    deadline = time.monotonic() + BUDGET
    for kw, _ in weights.most_common(MAX_QUERIES):
        if time.monotonic() > deadline:  # slow server: use what we have, retry next time
            failed += 1
            break
        try:
            docs = search(kw)
        except (OSError, ValueError, KeyError):  # URLError/timeout are OSError; bad JSON is ValueError
            failed += 1
            continue
        for d in docs:
            if d.get("want_to_read_count", 0) >= MIN_WANT and _latin(d.get("title", "")) \
                    and not _owned(d.get("title", ""), have):
                cands[d["key"]] = d
        if search is open_library_search:
            time.sleep(0.5)  # be polite to a free service
    if failed and not cands:
        _set_status(out, f"Refresh failed {now:%Y-%m-%d %H:%M} (offline?). Showing the previous list.")
        return "failed"

    text, n_core, n_stretch = build(mine, cands, today, now)
    if failed:
        text = text.replace("keywords.\n", f"keywords ({failed} searches failed).\n", 1)
    _write_atomic(out, text)
    if not failed:  # a partial run retries next time
        with open(state, "w", encoding="utf-8", newline="\n") as f:
            f.write(sig)
    return f"ok: {n_core} picks + {n_stretch} stretch"


# ---------- self-test (no network, no UI) ----------

def selftest():
    def doc(i, title, subjects, want=100, author="A. Writer"):
        return {"key": f"/works/OL{i}W", "title": title, "subject": subjects,
                "want_to_read_count": want, "author_name": [author]}

    catalog = [doc(1, "Tiny Habits", ["Habit", "Behavior modification", "Personal Growth"]),
               doc(2, "The Power of Habit", ["Habit", "Habit breaking", "Psychology"]),
               doc(3, "Atomic Habits: An Easy Way", ["Habit", "Habit breaking", "Psychology"]),  # owned
               doc(4, "Hamlet", ["Classics", "Character", "Drama"]),
               doc(5, "Quiet Tail Book", ["Habit"], want=1),  # too few readers
               doc(6, "嫌われる勇気", ["Habit", "Psychology"]),  # non-Latin title
               doc(7, "Mindset", ["Psychology", "Habit", "Personal Growth"])]
    calls = []

    def fake_search(kw):
        calls.append(kw)
        return catalog

    with tempfile.TemporaryDirectory() as d:
        core.ensure_vault(d)
        # no books yet: nothing to do, no network
        assert refresh(d, search=fake_search) == "no books" and calls == []
        core.write_note("Atomic Habits.md", "# Atomic Habits\n\n[[Home]]\n\n# Postview\n"
                        "## Trigger Words or Phrases:: (put each one in double square brackets)\n"
                        "[[habit]] [[habit breaking]] [[psychology]] [[Personal Growth]] [[popular works]] "
                        "[[naïve]] [[habit|alias]]\n\n# Your Questions\n1. See [[Elsewhere]]\n", d)
        core.write_note("Plain.md", "# Plain\n[[Learning]] [[psychology]] [[Home]]\n", d)  # linked-to-Learning form
        core.write_note("Other.md", "# Other\n[[Home]] [[habit]]\n", d)  # not a book
        mine = books(d)
        assert mine == {"Atomic Habits": ["habit", "habit breaking", "psychology", "personal growth"],
                        "Plain": ["psychology"]}, mine  # only the trigger section; junk/non-ASCII/Home dropped

        today, now = date(2026, 10, 14), datetime(2026, 10, 14, 11, 5)
        result = refresh(d, search=fake_search, today=today, now=now)
        assert result.startswith("ok"), result
        text = core.read_note(OUT_NAME, d)
        assert "> Updated 2026-10-14 11:05 from 2 books, 4 keywords." in text
        for want in ("Tiny Habits", "The Power of Habit", "Mindset"):
            assert want in text, want
        for dropped in ("Hamlet", "Quiet Tail Book", "嫌われる勇気", "Atomic Habits: An Easy Way"):
            assert dropped not in text, dropped  # off-topic / few readers / foreign / already owned
        assert "matches [[habit]]" in text or "matches [[psychology]]" in text
        assert len(calls) == 4  # one search per keyword
        # unchanged vault, same day: no network at all; --force always rebuilds
        n = len(calls)
        assert refresh(d, search=fake_search, today=today, now=now) == "unchanged" and len(calls) == n
        assert refresh(d, search=fake_search, today=today, now=now, force=True).startswith("ok")
        # the note and state file are not themselves books or notes
        assert OUT_NAME not in books(d) and STATE_NAME not in core.list_notes(d)
        # a changed keyword rebuilds
        core.write_note("Plain.md", "# Plain\n[[Learning]] [[psychology]] [[personal growth]]\n", d)
        assert refresh(d, search=fake_search, today=today, now=now).startswith("ok")
        # tomorrow: new day, new sample, rebuilt
        assert refresh(d, search=fake_search, today=date(2026, 10, 15), now=now).startswith("ok")

        # offline: old list kept, status line says so, state not advanced
        def offline(kw):
            raise OSError("no network")
        before = core.read_note(OUT_NAME, d)
        assert refresh(d, search=offline, today=date(2026, 10, 16), now=now) == "failed"
        after = core.read_note(OUT_NAME, d)
        assert "Refresh failed 2026-10-14 11:05 (offline?)" in after
        assert after.split("\n", 3)[3] == before.split("\n", 3)[3]  # same picks, only the status line moved
        # partly offline: what came back is used, and the next start retries
        flaky = iter([OSError("x")])

        def partly(kw):
            e = next(flaky, None)
            if e:
                raise e
            return catalog
        assert refresh(d, search=partly, today=date(2026, 10, 17), now=now).startswith("ok")
        assert "searches failed)" in core.read_note(OUT_NAME, d)
        assert refresh(d, search=fake_search, today=date(2026, 10, 17), now=now) .startswith("ok")  # retried

    print("recommend selftest OK")


if __name__ == "__main__":
    selftest()
