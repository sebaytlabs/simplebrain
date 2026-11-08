#!/usr/bin/env python3
"""Drop it and it's filed: PARA folders (Projects, Areas, Resources, Archives) without moving files around by hand.
No Qt here.

- Where your PARA folders are: a `para:: ~/Desktop` line in Home, else the first of Desktop, Documents and home
  that holds at least two of Projects/Areas/Resources/Archives, else they're made in Documents.
- A file or folder dropped on the window, or put in the Drop folder beside them, goes to the project or area
  folder whose name it shares words with (walker-supply-lease.pdf -> Projects/walker-supply); otherwise to
  Resources/<kind> (Documents, Videos, Audio, Pictures, Spreadsheets, Books, Programs, Other). A note whose
  title it matches gets a `file::` line, so it opens from there.
- Downloads: files untouched for two days are filed the same way, at most once a day, when your PARA folders were
  already there (yours, not made by SimpleBrain). `file downloads:: off` in Home stops it.
- Nothing is ever overwritten or deleted: a name that's taken gets " (2)"; every move is logged and Undo puts it back.

Run: python simplebrain_drop.py   (selftest)
"""
import json
import os
import re
import shutil
import time
from datetime import datetime

import simplebrain_core as core

PARA = ("Projects", "Areas", "Resources", "Archives")
DROP = "Drop"
PARA_LINE = re.compile(r"^\s*para::\s*(.+?)\s*$", re.I | re.M)
DOWNLOADS_OFF = re.compile(r"^\s*file downloads::\s*off\s*$", re.I | re.M)
SETTLE_S = 2 * 86400  # a download you haven't touched in two days is done with
PARTIAL = (".part", ".crdownload", ".download", ".tmp", ".partial")
KINDS = (("Videos", {".mp4", ".mkv", ".webm", ".avi", ".mov", ".m4v", ".wmv", ".mpg", ".mpeg"}),
         ("Audio", {".mp3", ".m4a", ".m4b", ".wav", ".ogg", ".opus", ".flac", ".aac"}),
         ("Pictures", {".png", ".jpg", ".jpeg", ".gif", ".webp", ".heic", ".bmp", ".svg"}),
         ("Spreadsheets", {".xlsx", ".xls", ".ods", ".csv"}),
         ("Books", {".epub", ".mobi", ".azw3"}),
         ("Programs", {".deb", ".appimage", ".exe", ".msi", ".dmg", ".pkg", ".rpm", ".sh"}),
         ("Documents", {".pdf", ".doc", ".docx", ".odt", ".txt", ".md", ".rtf", ".pptx", ".odp", ".zip", ".7z", ".tar", ".gz"}))
STOP = {"the", "and", "for", "with", "from", "copy", "final", "new", "file", "scan", "img", "image", "document",
        "untitled", "download", "version"}


def words(name):
    """Meaningful words of a file or folder name: 'Walker_Supply-lease (2).pdf' -> {'walker', 'supply', 'lease'}."""
    stem = os.path.splitext(os.path.basename(name.rstrip("/\\")))[0] if "." in os.path.basename(name) else os.path.basename(name.rstrip("/\\"))
    return {w for w in re.findall(r"[a-z]{3,}", stem.lower().replace("_", " ")) if w not in STOP}


def para_root(vault=None, candidates=("~/Desktop", "~/Documents", "~"), create=True):
    """(folder holding the PARA folders, True if they were already yours)."""
    vault = vault or core.VAULT
    try:
        m = PARA_LINE.search(core.settings_text(vault))
    except OSError:
        m = None
    if m:
        root = os.path.normpath(core.resolve_file(m.group(1), vault))
        return root, any(os.path.isdir(os.path.join(root, p)) for p in PARA)
    for c in candidates:
        c = os.path.expanduser(c)
        if sum(os.path.isdir(os.path.join(c, p)) for p in PARA) >= 2:
            return c, True
    root = os.path.expanduser(candidates[1] if len(candidates) > 1 else candidates[0])
    if create:
        for p in PARA:
            os.makedirs(os.path.join(root, p), exist_ok=True)
    return root, False


def drop_dir(root):
    d = os.path.join(root, DROP)
    os.makedirs(d, exist_ok=True)
    return d


def kind_of(path):
    if os.path.isdir(path):
        return "Folders"
    ext = os.path.splitext(path)[1].lower()
    return next((k for k, exts in KINDS if ext in exts), "Other")


def destination(path, root, notes=()):
    """(folder it goes to, note title it belongs with or None, why) for one dropped file or folder."""
    w = words(path)
    best, score = None, 0
    for top in ("Projects", "Areas"):
        base = os.path.join(root, top)
        try:
            subs = [s for s in os.listdir(base) if os.path.isdir(os.path.join(base, s)) and not s.startswith(".")]
        except OSError:
            continue
        for s in subs:
            n = len(w & words(s))
            if n > score or (n == score and n and top == "Projects" and best and "Areas" in best):
                best, score = os.path.join(base, s), n
    note = None
    nscore = 0
    for t in notes:
        n = len(w & words(t))
        if n > nscore and n >= min(2, len(words(t)) or 2):
            note, nscore = t, n
    if best and (score >= 2 or (score == 1 and len(words(os.path.basename(best))) == 1)):
        return best, note, f"matches {os.path.relpath(best, root)}"
    if note:  # no folder yet, but a note of that name: a project folder named after it
        folder = os.path.join(root, "Projects", note)
        return folder, note, f"goes with your note {note}"
    k = kind_of(path)
    return os.path.join(root, "Resources", k), None, f"a {k[:-1].lower() if k.endswith('s') else k.lower()} → Resources"


def free_name(folder, name):
    stem, ext = os.path.splitext(name)
    if os.path.isdir(os.path.join(folder, name)):
        stem, ext = name, ""
    cand, i = name, 2
    while os.path.exists(os.path.join(folder, cand)):
        cand, i = f"{stem} ({i}){ext}", i + 1
    return os.path.join(folder, cand)


def log_path():
    return os.path.join(core.user_config_dir(), "drop-log.json")


def _log(entries):
    try:
        with open(log_path(), encoding="utf-8") as f:
            old = json.load(f)
    except (OSError, ValueError):
        old = []
    os.makedirs(os.path.dirname(log_path()), exist_ok=True)
    core.write_atomic(log_path(), json.dumps((old + entries)[-500:], indent=1))


def file_one(path, root, vault=None, link=True, note=None):
    """Move one file or folder to where it goes; link it from its note. {"from", "to", "note", "why"} or None.
    `note`: dropped on that note, so it goes with it (its project folder, unless a folder already matches)."""
    vault = vault or core.VAULT
    path = os.path.abspath(path)
    if not os.path.exists(path) or protected(path, root, vault):
        return None
    if filed_already(path, root):  # already in your PARA folders: it stays; dropped on a note, it's linked there
        if note and os.path.exists(os.path.join(vault, note + ".md")):
            text = core.read_note(note + ".md", vault)
            line = core.file_line(path, vault)
            if line not in text:
                core.write_note(note + ".md", text.rstrip("\n") + "\n" + line + "\n", vault)
                return {"from": path, "to": path, "note": note, "why": "linked where it is",
                        "when": datetime.now().isoformat(timespec="seconds")}
        return None
    notes = [core.note_title(n) for n in core.list_user_notes(vault)]
    folder, found, why = destination(path, root, notes)
    if note:
        if not why.startswith("matches"):
            folder, why = destination(note, root)[0] if destination(note, root)[2].startswith("matches") \
                else os.path.join(root, "Projects", note), f"goes with your note {note}"
        found = note
    note = found
    if os.path.abspath(os.path.dirname(path)) == os.path.abspath(folder):
        return None  # already where it belongs
    if os.path.abspath(folder).startswith(path + os.sep):
        return None  # a folder can't go inside itself
    os.makedirs(folder, exist_ok=True)
    to = free_name(folder, os.path.basename(path.rstrip("/\\")))
    shutil.move(path, to)
    entry = {"from": path, "to": to, "note": note, "why": why, "when": datetime.now().isoformat(timespec="seconds")}
    if note and link:
        n = note + ".md"
        text = core.read_note(n, vault)
        line = core.file_line(to, vault)
        if line not in text:
            core.write_note(n, text.rstrip("\n") + "\n" + line + "\n", vault)
    return entry


def _inside(path, folder):
    path, folder = os.path.normcase(os.path.abspath(path)), os.path.normcase(os.path.abspath(folder))
    return path == folder or path.startswith(folder.rstrip(os.sep) + os.sep)


def protected(path, root, vault=None):
    """Never moved: the PARA folders themselves, the Drop folder, the folder holding them, the notes folder, home,
    or anything that contains one of those (dropping Projects onto the window must not move Projects)."""
    keep = [root, os.path.join(root, DROP), vault or core.VAULT, os.path.expanduser("~")] + [os.path.join(root, p) for p in PARA]
    return any(_inside(k, path) for k in keep) or _inside(path, vault or core.VAULT)


def filed_already(path, root):
    return any(_inside(path, os.path.join(root, p)) for p in PARA)


def file_all(paths, root, vault=None, note=None):
    done = [e for e in (file_one(p, root, vault, note=note) for p in paths) if e]
    if done:
        _log(done)
    return done


def undo(entries, vault=None):
    """Put filed things back where they came from (and take their file:: lines out). Returns how many."""
    vault = vault or core.VAULT
    n = 0
    for e in reversed(entries):
        if not os.path.exists(e["to"]) or os.path.exists(e["from"]):
            continue
        os.makedirs(os.path.dirname(e["from"]), exist_ok=True)
        shutil.move(e["to"], e["from"])
        n += 1
        if e.get("note") and os.path.exists(os.path.join(vault, e["note"] + ".md")):
            text = core.read_note(e["note"] + ".md", vault)
            line = core.file_line(e["to"], vault)
            if line in text:
                core.write_note(e["note"] + ".md", text.replace(line + "\n", "").replace(line, ""), vault)
    return n


def drop_folder_items(root):
    d = drop_dir(root)
    return [os.path.join(d, f) for f in sorted(os.listdir(d)) if not f.startswith(".") and not f.endswith(PARTIAL)]


def settled_downloads(folder="~/Downloads", now=None, settle=SETTLE_S):
    """Downloads nobody has touched for two days (finished, not half-downloaded)."""
    folder = os.path.expanduser(folder)
    now = now or time.time()
    out = []
    try:
        names = os.listdir(folder)
    except OSError:
        return []
    for f in sorted(names):
        p = os.path.join(folder, f)
        if f.startswith(".") or f.lower().endswith(PARTIAL):
            continue
        try:
            if now - os.path.getmtime(p) >= settle:
                out.append(p)
        except OSError:
            pass
    return out


def downloads_on(vault=None, was_yours=True):
    try:
        off = DOWNLOADS_OFF.search(core.settings_text(vault or core.VAULT))
    except OSError:
        off = None
    return was_yours and not off


def counts(root):
    """{PARA folder: how many things in it}: the PARA picture at a glance."""
    out = {}
    for p in PARA:
        try:
            out[p] = sum(1 for x in os.listdir(os.path.join(root, p)) if not x.startswith("."))
        except OSError:
            out[p] = 0
    return out


def selftest():
    import tempfile
    d = tempfile.mkdtemp()
    real_cfg = core.user_config_dir
    core.user_config_dir = lambda: os.path.join(d, "cfg")
    try:
        v = os.path.join(d, "vault")
        core.ensure_vault(v)
        desk_ = os.path.join(d, "Desktop")
        for p in ("Projects/walker-supply", "Projects/money-plan", "Areas/Claude", "Resources", "Archives"):
            os.makedirs(os.path.join(desk_, p))
        root, yours = para_root(v, candidates=(desk_, os.path.join(d, "Documents")))
        assert root == desk_ and yours
        fresh, mine = para_root(v, candidates=(os.path.join(d, "none"), os.path.join(d, "Documents")))
        assert fresh == os.path.join(d, "Documents") and not mine and os.path.isdir(os.path.join(fresh, "Archives"))
        core.write_note("Home.md", f"# Home\npara:: {desk_}\n", v)
        assert para_root(v)[0] == os.path.normpath(desk_)
        assert words("Walker_Supply-lease (2).pdf") == {"walker", "supply", "lease"}
        assert destination(os.path.join(d, "walker supply lease.pdf"), desk_)[0] == os.path.join(desk_, "Projects", "walker-supply")
        assert destination(os.path.join(d, "claude notes.txt"), desk_)[0] == os.path.join(desk_, "Areas", "Claude")
        assert destination(os.path.join(d, "IMG_2041.jpg"), desk_)[0] == os.path.join(desk_, "Resources", "Pictures")
        assert destination(os.path.join(d, "random.xyz"), desk_)[0] == os.path.join(desk_, "Resources", "Other")
        core.write_note("Guitar Course.md", "# Guitar Course\n", v)
        f, note, _ = destination(os.path.join(d, "guitar course session 3.mp3"), desk_, ["Guitar Course"])
        assert note == "Guitar Course" and f == os.path.join(desk_, "Projects", "Guitar Course")
        # drop: moved, linked from its note, never overwrites, undo puts everything back
        drop = drop_dir(desk_)
        for name in ("walker-supply lease.pdf", "guitar course session 3.mp3", "IMG_2041.jpg"):
            open(os.path.join(drop, name), "w").write(name)
        os.makedirs(os.path.join(desk_, "Resources", "Pictures"))
        open(os.path.join(desk_, "Resources", "Pictures", "IMG_2041.jpg"), "w").write("older")
        done = file_all(drop_folder_items(desk_), desk_, v)
        assert len(done) == 3 and drop_folder_items(desk_) == []
        assert os.path.exists(os.path.join(desk_, "Projects", "walker-supply", "walker-supply lease.pdf"))
        assert open(os.path.join(desk_, "Resources", "Pictures", "IMG_2041.jpg")).read() == "older"  # never overwritten
        assert os.path.exists(os.path.join(desk_, "Resources", "Pictures", "IMG_2041 (2).jpg"))
        assert "file:: " in core.read_note("Guitar Course.md", v) and "session 3.mp3" in core.read_note("Guitar Course.md", v)
        with open(log_path()) as fh:
            assert len(json.load(fh)) == 3
        assert undo(done, v) == 3 and len(drop_folder_items(desk_)) == 3
        assert "session 3.mp3" not in core.read_note("Guitar Course.md", v)
        folder = os.path.join(drop, "Walker Supply scans")
        os.makedirs(folder)
        open(os.path.join(folder, "a.pdf"), "w").close()
        e = file_one(folder, desk_, v)
        assert e["to"] == os.path.join(desk_, "Projects", "walker-supply", "Walker Supply scans") and os.path.isdir(e["to"])
        # downloads: only settled ones, never half-downloaded; only when the PARA folders were yours
        dl = os.path.join(d, "Downloads")
        os.makedirs(dl)
        for name, age in (("old.pdf", 3 * 86400), ("new.pdf", 60), ("big.iso.part", 5 * 86400)):
            p = os.path.join(dl, name)
            open(p, "w").close()
            os.utime(p, (time.time() - age, time.time() - age))
        assert [os.path.basename(p) for p in settled_downloads(dl)] == ["old.pdf"]
        assert downloads_on(v) and not downloads_on(v, was_yours=False)
        core.write_note("Home.md", "# Home\nfile downloads:: off\n", v)
        assert not downloads_on(v)
        assert counts(desk_)["Projects"] >= 3
        # never moved: the PARA folders, the Drop folder, the notes folder, home, or what holds them; filed stays put
        for p in (os.path.join(desk_, "Projects"), desk_, drop, v, os.path.join(desk_, "Archives")):
            assert file_one(p, desk_, v) is None and os.path.isdir(p)
        lease = os.path.join(desk_, "Projects", "walker-supply", "walker-supply lease.pdf")
        open(lease, "w").close()
        assert file_one(lease, desk_, v) is None and os.path.exists(lease)
        core.write_note("Bond.md", "# Bond\n", v)
        e = file_one(lease, desk_, v, note="Bond")
        assert e["to"] == lease and "walker-supply lease.pdf" in core.read_note("Bond.md", v)  # linked where it is
        # dropped on an open note: it goes with that note (its project folder) and is linked from it
        core.write_note("Riverside.md", "# Riverside\n", v)
        p = os.path.join(d, "statement.pdf")
        open(p, "w").close()
        e = file_all([p], desk_, v, note="Riverside")[0]
        assert e["to"] == os.path.join(desk_, "Projects", "Riverside", "statement.pdf") and "statement.pdf" in core.read_note("Riverside.md", v)
        p = os.path.join(d, "walker supply bond.pdf")
        open(p, "w").close()
        assert file_all([p], desk_, v, note="Riverside")[0]["to"].startswith(os.path.join(desk_, "Projects", "walker-supply"))
    finally:
        core.user_config_dir = real_cfg
        shutil.rmtree(d, ignore_errors=True)
    print("drop selftest OK")


if __name__ == "__main__":
    selftest()
