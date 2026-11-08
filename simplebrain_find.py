#!/usr/bin/env python3
"""Find anything from SimpleBrain's top bar: notes, windows already open (brought up, not opened twice),
apps, files in your home folder and on mounted drives (the Backup drive too, which the system's own
`locate` skips), and the web as the last resort. No Qt here; the app shows the results.

Run: python simplebrain_find.py   (selftest)
"""
import configparser
import os
import re
import threading
import time

import simplebrain_core as core
import simplebrain_desk as desk

SKIP_DIRS = {"node_modules", "__pycache__", ".venv", "venv", "site-packages", ".git", "proc", "lost+found",
             "Trash", ".Trash-1000", "snap"}
MAX_FILES = 400_000  # a home folder plus a backup drive; past this the walk stops rather than eat memory
KIND_ORDER = {"window": 0, "note": 1, "app": 2, "file": 3}
GOOD_EXTS = set(desk.MEDIA_EXTS) | {".pdf", ".epub", ".docx", ".doc", ".odt", ".xlsx", ".ods", ".pptx", ".txt",
                                    ".md", ".png", ".jpg", ".jpeg", ".py", ".html"}


def roots():
    home = os.path.expanduser("~")
    out = [home]
    if os.name == "nt":  # other drives: D:, E: (a backup drive, a USB stick)
        import string
        out += [f"{d}:\\" for d in string.ascii_uppercase[3:] if os.path.isdir(f"{d}:\\")]
    for base in (f"/media/{os.environ.get('USER', '')}", "/mnt", "/Volumes"):
        try:
            out += [os.path.join(base, d) for d in sorted(os.listdir(base))]
        except OSError:
            pass
    return out


class FileIndex:
    """Every file name under the roots, walked in the background (hidden folders and build junk left out),
    so a search is a scan of names in memory, not a disk walk. Saved to `cache` and reused: the disks are
    walked again only when the saved list is over a day old, and never until the first search
    (an old laptop on battery shouldn't spin its disks for a list nobody asked for)."""
    STALE_S = 24 * 3600

    def __init__(self, paths=None, cache=None):
        self.paths, self.ready, self._roots, self.cache = [], False, paths, cache
        self._started = False

    def ensure(self):
        """Call before searching: loads the saved list at once, walks again in the background if old."""
        if self._started:
            return self
        self._started = True
        age = None
        if self.cache and os.path.exists(self.cache):
            try:
                with open(self.cache, encoding="utf-8", errors="replace") as f:
                    self.paths = f.read().split("\n")
                self.ready = True
                age = time.time() - os.path.getmtime(self.cache)
            except OSError:
                pass
        if age is None or age > self.STALE_S:
            self.start()
        return self

    def build(self):
        found = []
        for root in self._roots or roots():
            for d, dirs, files in os.walk(root, onerror=lambda e: None):
                dirs[:] = [x for x in dirs if not x.startswith(".") and x not in SKIP_DIRS]
                found += [os.path.join(d, f) for f in files if not f.startswith(".")]
                if len(found) >= MAX_FILES:
                    break
            if len(found) >= MAX_FILES:
                break
        self.paths, self.ready = found, True
        if self.cache:
            try:
                os.makedirs(os.path.dirname(self.cache), exist_ok=True)
                core.write_atomic(self.cache, "\n".join(found))
            except OSError:
                pass
        return self

    def start(self):
        threading.Thread(target=self.build, daemon=True).start()
        return self


def apps(dirs=None):
    """[(name, desktop file path)] of the apps in the menu (NoDisplay/Hidden ones left out)."""
    dirs = dirs or [os.path.expanduser("~/.local/share/applications"), "/usr/local/share/applications",
                    "/usr/share/applications", "/var/lib/flatpak/exports/share/applications"]
    seen, out = set(), []
    for d in dirs:
        try:
            names = sorted(os.listdir(d))
        except OSError:
            continue
        for f in names:
            if not f.endswith(".desktop") or f in seen:
                continue
            seen.add(f)  # a user's copy in ~/.local hides the system one
            cp = configparser.RawConfigParser(strict=False, interpolation=None)
            try:
                cp.read(os.path.join(d, f), encoding="utf-8")
                e = cp["Desktop Entry"]
            except (configparser.Error, KeyError, UnicodeDecodeError):
                continue
            if e.get("NoDisplay", "").lower() == "true" or e.get("Hidden", "").lower() == "true" or not e.get("Name"):
                continue
            out.append((e["Name"], os.path.join(d, f)))
    return out


def app_command(desktop_path):
    """Run a menu entry the way the menu would: gtk-launch when there, else its Exec line without the %-codes."""
    if desk.have("gtk-launch"):
        return ["gtk-launch", os.path.basename(desktop_path)]
    cp = configparser.RawConfigParser(strict=False, interpolation=None)
    cp.read(desktop_path, encoding="utf-8")
    exe = re.sub(r"\s?%[a-zA-Z]", "", cp["Desktop Entry"].get("Exec", "")).strip()
    import shlex
    return shlex.split(exe) if exe else None


def short_dir(path):
    """Where a file is, short enough to read at a glance: 'Backup › Guitar 2023'."""
    parts = [x for x in re.split(r"[\\/]", path)[:-1] if x and not x.endswith(":")]  # / or \, and no C:
    return " › ".join(parts[-2:]) if parts else os.sep


def _score(name, terms):
    """Lower is better; None when a term is missing."""
    low = name.lower()
    if not all(t in low for t in terms):
        return None
    s = 0 if low.startswith(terms[0]) else 1
    if any(re.search(rf"\b{re.escape(t)}", low) for t in terms):
        s -= 0.5
    return s + len(name) / 200


def search(query, vault=None, index=None, app_list=None, wins=None, limit=8, habits=None):
    """[(kind, label, detail, target)]: windows, notes, apps, then files, best first within each kind.
    habits: {target: lift} from simplebrain_habits, so what you use around now ranks higher."""
    vault = vault or core.VAULT
    habits = habits or {}
    terms = query.lower().split()
    if not terms:
        return []
    hits = []
    for wid, title in (desk.windows() if wins is None else wins).items():
        if title and title != "SimpleBrain" and (s := _score(title, terms)) is not None:
            hits.append((s, "window", title, "already open: bring it up", wid))
    for n in core.list_user_notes(vault):
        title = core.note_title(n)
        s = _score(title, terms)
        if s is None and all(t in core.read_note(n, vault).lower() for t in terms):
            s = 2  # the words are in the note, not its title
        if s is not None:
            hits.append((s, "note", title, "note", n))
    for name, path in (apps() if app_list is None else app_list):
        if (s := _score(name, terms)) is not None:
            hits.append((s, "app", name, "app", path))
    files = []
    for p in (index.paths if index else []):
        base = os.path.basename(p)
        s = _score(base, terms)
        if s is None:  # 'python module 1' finds module-01.mp4 in Python Essentials 1/: the folders count too
            s = _score(" / ".join(p.split(os.sep)[-3:]), terms)
            s = None if s is None else s + 0.5
        if s is not None:
            if os.path.splitext(base)[1].lower() not in GOOD_EXTS:
                s += 2  # documents and media before config files and the like
            files.append((s, "file", base, short_dir(p), p))
            if len(files) > 400:
                break
    files = [(f[0] - habits.get(f[-1], 0), *f[1:]) for f in files]
    hits = [(h[0] - habits.get(h[-1], 0), *h[1:]) for h in hits]
    files.sort()
    hits.sort(key=lambda h: (KIND_ORDER[h[1]], h[0]))
    out = [h[1:] for h in hits if h[1] != "file"][:limit - min(4, len(files))]
    out += [h[1:] for h in files[:limit - len(out)]]
    return out


def selftest():
    import shutil
    import tempfile
    d = tempfile.mkdtemp()
    try:
        vault, home, appdir = (os.path.join(d, x) for x in ("vault", "home", "apps"))
        core.ensure_vault(vault)
        core.write_note("Python.md", "# Python\nStudy Group on Dec 19\n", vault)
        core.write_note("Spanish OPI.md", "# Spanish OPI\nmock interview with python flashcards\n", vault)
        for p in ("Courses/Python Essentials 1/module-01.mp4", "Courses/Python Essentials 1/notes.pdf",
                  ".cache/python-junk.bin", "code/node_modules/python.js", "Backup/Guitar/guitar-01.mp3",
                  "code/python.conf"):
            os.makedirs(os.path.dirname(os.path.join(home, p)), exist_ok=True)
            open(os.path.join(home, p), "w").close()
        cache = os.path.join(d, "cfg", "files.txt")
        idx = FileIndex([home], cache).build()
        assert idx.ready and not any(".cache" in p or "node_modules" in p for p in idx.paths)
        again = FileIndex([os.path.join(d, "nowhere")], cache).ensure()  # fresh list on disk: no walk
        assert again.ready and sorted(again.paths) == sorted(idx.paths) and not any(
            t.name != "MainThread" and t.is_alive() and t.daemon for t in threading.enumerate())
        os.makedirs(appdir)
        with open(os.path.join(appdir, "librewolf.desktop"), "w") as f:
            f.write("[Desktop Entry]\nName=LibreWolf\nExec=librewolf %u\nType=Application\n")
        with open(os.path.join(appdir, "hidden.desktop"), "w") as f:
            f.write("[Desktop Entry]\nName=Python Helper\nNoDisplay=true\nExec=x\n")
        al = apps([appdir])
        assert al == [("LibreWolf", os.path.join(appdir, "librewolf.desktop"))]
        if not desk.have("gtk-launch"):
            assert app_command(al[0][1]) == ["librewolf"]
        r = search("python", vault, idx, al, {"0x1": "Python Essentials 1 - edube.org — LibreWolf", "0x2": "SimpleBrain"})
        kinds = [x[0] for x in r]
        assert kinds[0] == "window" and r[0][3] == "0x1"  # already open: brought up, not opened again
        assert ("note", "Python", "note", "Python.md") in r and ("note", "Spanish OPI", "note", "Spanish OPI.md") in r
        assert r.index(("note", "Python", "note", "Python.md")) < r.index(("note", "Spanish OPI", "note", "Spanish OPI.md"))
        files = [x[1] for x in r if x[0] == "file"]
        assert files[:2] == ["module-01.mp4", "notes.pdf"] or set(files[:2]) == {"module-01.mp4", "notes.pdf"}
        assert files[-1] == "python.conf"  # a config file comes after documents and media
        assert search("guitar 01", vault, idx, al, {})[0][1] == "guitar-01.mp3"  # every word must match
        assert search("librewolf", vault, idx, al, {})[0][:2] == ("app", "LibreWolf")
        assert search("  ", vault, idx, al, {}) == [] and search("zzzq", vault, idx, al, {}) == []
        assert len(search("p", vault, idx, al, {}, limit=5)) <= 5
        r = search("python", vault, idx, al, {}, habits={"Spanish OPI.md": 3})
        assert r.index(("note", "Spanish OPI", "note", "Spanish OPI.md")) < r.index(("note", "Python", "note", "Python.md"))
        assert short_dir("/media/owner/Backup/Guitar 2023/s1.mp4") == "Backup › Guitar 2023"
    finally:
        shutil.rmtree(d, ignore_errors=True)
    print("find selftest OK")


if __name__ == "__main__":
    selftest()
