#!/usr/bin/env python3
"""Updates that install themselves. No Qt here.

- Run from a git checkout (./dev.sh or python simplebrain_app.py): fetch, and when the branch is only behind
  (nothing of yours would be overwritten) fast-forward it; requirements that changed are installed into the
  same Python. The app restarts when you're not using its window (dev.sh restarts it by itself).
- Installed copy (Windows installer, Mac app, Linux AppImage or install.sh): the newest GitHub release's file for
  this system, downloaded, checked against the release's checksum, and swapped in (stage_update, apply_now,
  restart_command). A copy on a USB drive is left for its owner to replace.

Run: python simplebrain_update.py   (selftest)
"""
import json
import os
import re
import subprocess
import sys
import urllib.request

import simplebrain_core as core

CHECK_EVERY_MIN = 30  # a change on GitHub arrives within half an hour; one small fetch costs nothing
CHECK_EVERY_H = CHECK_EVERY_MIN / 60


def _git(repo, *args, timeout=60):
    r = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, timeout=timeout)
    return r.returncode, r.stdout.strip()


def checkout_dir(app_file):
    """The git checkout SimpleBrain runs from, or None (an installed build, a copied folder)."""
    d = os.path.dirname(os.path.abspath(app_file))
    return d if os.path.isdir(os.path.join(d, ".git")) else None


def default_branch(repo):
    """The branch GitHub publishes from (origin's HEAD), normally main."""
    code, ref = _git(repo, "symbolic-ref", "--quiet", "refs/remotes/origin/HEAD")
    return ref.rsplit("/", 1)[-1] if code == 0 and ref else "main"


def git_update(repo, fetch=True):
    """Bring the checkout up to what's published on GitHub (origin's main) when that's safe, whichever branch it is
    on: a copy left on an old feature branch that's already merged moves to main. Returns (state, changed files):
    'updated', 'current', or why it was left alone ('local changes', 'diverged', 'no upstream', 'offline')."""
    try:
        if fetch and _git(repo, "fetch", "--quiet", "origin")[0]:
            return "offline", []
        main = default_branch(repo)
        target = f"origin/{main}"
        if _git(repo, "rev-parse", "--verify", "--quiet", target)[0]:
            return "no upstream", []
        _, counts = _git(repo, "rev-list", "--left-right", "--count", f"HEAD...{target}")
        ahead, behind = (int(x) for x in counts.split())
        if not behind:
            return "current", []
        if ahead:
            return "diverged", []  # commits of yours that aren't published: never thrown away
        _, dirty = _git(repo, "status", "--porcelain", "--untracked-files=no")
        if dirty:
            return "local changes", []  # never overwrite edits someone made to the code
        _, old = _git(repo, "rev-parse", "HEAD")
        _, branch = _git(repo, "rev-parse", "--abbrev-ref", "HEAD")
        if branch != main:  # on another branch with nothing of its own: go to main
            if _git(repo, "rev-parse", "--verify", "--quiet", main)[0] == 0:
                if _git(repo, "merge-base", "--is-ancestor", main, target)[0]:
                    return "diverged", []
                if _git(repo, "checkout", "--quiet", main)[0]:
                    return "local changes", []
            elif _git(repo, "checkout", "--quiet", "-b", main, "--track", target)[0]:
                return "local changes", []
        if _git(repo, "merge", "--ff-only", "--quiet", target)[0]:
            return "diverged", []
        _, changed = _git(repo, "diff", "--name-only", old, "HEAD")
        return "updated", [c for c in changed.splitlines() if c]
    except (OSError, subprocess.SubprocessError, ValueError):
        return "offline", []


def pip_command(repo, changed, python=sys.executable):
    """Install what the update needs, into the Python SimpleBrain runs in; None when nothing changed."""
    if not {"requirements.txt", "constraints.txt"} & set(changed):
        return None
    cmd = [python, "-m", "pip", "install", "-q", "-r", os.path.join(repo, "requirements.txt")]
    if os.path.exists(os.path.join(repo, "constraints.txt")):
        cmd += ["-c", os.path.join(repo, "constraints.txt")]
    return cmd


# ---------- installed copies on every system: find the newest release, stage it, swap it in ----------
# Each release carries the three downloads and SHA256SUMS (build.yml). Nothing is installed without a matching
# checksum; the running copy is only replaced once the new one is complete on disk.

ASSET_PATTERNS = {
    "appimage": r"^SimpleBrain-x86_64\.AppImage$",
    "linux-install": r"^SimpleBrain-x86_64\.AppImage$",
    "windows": r"^SimpleBrain-[\d.]+-windows-setup\.exe$",
    "mac-arm": r"^SimpleBrain-[\d.]+-mac-ARM64\.dmg$",
    "mac-intel": r"^SimpleBrain-[\d.]+-mac-X64\.dmg$",
}


def install_kind(frozen=None, platform=None, env=None, exe=None, machine=None, portable=None):
    """How this copy was installed, which decides how it updates: 'appimage', 'linux-install' (install.sh),
    'windows' (the installer), 'mac-arm' / 'mac-intel' (the .app), or None (source run, a portable drive)."""
    import platform as _pf
    frozen = getattr(sys, "frozen", False) if frozen is None else frozen
    platform = platform or sys.platform
    env = os.environ if env is None else env
    exe = exe or sys.executable
    if env.get("APPIMAGE"):
        return "appimage"
    if not frozen:
        return None
    if portable if portable is not None else core.settings_path() != os.path.join(core.user_config_dir(), "settings.json"):
        return None  # a copy on a USB drive is its owner's to replace (it serves three systems at once)
    if platform.startswith("linux"):
        return "linux-install"
    if platform == "win32":
        return "windows"
    if platform == "darwin":
        m = (machine or _pf.machine()).lower()
        return "mac-arm" if m in ("arm64", "aarch64") else "mac-intel"
    return None


def release_info(repo=core.REPO, timeout=15, gh=None):
    """{"tag", "assets": {name: download url}} of the newest release, through the `gh` login when there is one
    (the repo can be private) or GitHub's public API; None offline."""
    import shutil
    gh = gh if gh is not None else shutil.which("gh")
    if gh:
        try:
            r = subprocess.run([gh, "release", "view", "--repo", repo, "--json", "tagName,assets"],
                               capture_output=True, text=True, timeout=timeout)
            if r.returncode == 0:
                d = json.loads(r.stdout)
                return {"tag": d["tagName"], "assets": {a["name"]: a.get("url", "") for a in d.get("assets", [])},
                        "via": "gh"}
        except (OSError, subprocess.SubprocessError, ValueError, KeyError):
            pass
    try:
        req = urllib.request.Request(f"https://api.github.com/repos/{repo}/releases/latest",
                                     headers={"Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.load(r)
        return {"tag": d["tag_name"], "assets": {a["name"]: a["browser_download_url"] for a in d.get("assets", [])},
                "via": "web"}
    except (OSError, ValueError, KeyError):
        return None


def pick_asset(info, kind):
    pat = ASSET_PATTERNS.get(kind)
    return next((n for n in sorted(info["assets"]) if pat and re.match(pat, n)), None) if info else None


def _fetch(info, name, folder, repo=core.REPO):
    path = os.path.join(folder, name)
    if info.get("via") == "gh":
        r = subprocess.run(["gh", "release", "download", info["tag"], "--repo", repo, "--pattern", name,
                            "--dir", folder, "--clobber"], capture_output=True, text=True, timeout=1800)
        if r.returncode:
            raise OSError("download failed: " + r.stderr.strip()[:200])
        return path
    with urllib.request.urlopen(info["assets"][name], timeout=60) as src, open(path, "wb") as out:
        while chunk := src.read(1 << 20):
            out.write(chunk)
    return path


def expected_sum(info, name, folder):
    """The published sha256 of one download: from SHA256SUMS, or the older single <name>.sha256."""
    if "SHA256SUMS" in info["assets"]:
        with open(_fetch(info, "SHA256SUMS", folder), encoding="utf-8") as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 2 and os.path.basename(parts[1].lstrip("*")) == name:
                    return parts[0].lower()
    if name + ".sha256" in info["assets"]:
        with open(_fetch(info, name + ".sha256", folder), encoding="utf-8") as f:
            parts = f.read().split()
        return parts[0].lower() if parts else None
    return None


def sha256(path):
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def stage_update(info, kind, folder):
    """Download this system's file of the release into `folder` and check it. Returns its path; raises
    OSError with a plain reason (no checksum, mismatch, no file for this system)."""
    name = pick_asset(info, kind)
    if not name:
        raise OSError("no download for this system in " + info["tag"])
    os.makedirs(folder, exist_ok=True)
    want = expected_sum(info, name, folder)
    if not want:
        raise OSError("the release has no checksum, nothing installed")
    path = _fetch(info, name, folder)
    if sha256(path) != want:
        os.remove(path)
        raise OSError("checksum mismatch, nothing installed")
    return path


def apply_now(kind, staged, appimage=None):
    """Put a staged download in place where that is safe while running (the AppImage file, the install.sh
    folder). Returns True if done; Windows and macOS are swapped at restart (restart_command)."""
    if kind == "appimage":
        target = appimage or os.environ["APPIMAGE"]
        tmp = target + ".new"
        import shutil
        shutil.copyfile(staged, tmp)
        os.chmod(tmp, 0o755)
        os.replace(tmp, target)  # the running copy keeps its old file open; the next start is the new one
        return True
    if kind == "linux-install":
        return core.install_update_from(staged) == ""
    return False


def restart_command(kind, staged, app_path, args=()):
    """The command that installs a staged Windows/Mac download after SimpleBrain quits and starts the new one
    (with the arguments it was running with)."""
    if kind == "windows":
        setup = subprocess.list2cmdline([staged, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS"])
        again = subprocess.list2cmdline([app_path, *args])
        return ["cmd", "/c", f'timeout /t 2 /nobreak >nul & {setup} & start "" {again}']
    if kind in ("mac-arm", "mac-intel"):
        mnt = os.path.join(os.path.dirname(staged), "mnt")
        script = (f'sleep 2; hdiutil attach -nobrowse -quiet -mountpoint "{mnt}" "{staged}" && '
                  f'rm -rf "{app_path}.new" && ditto "{mnt}/SimpleBrain.app" "{app_path}.new" && '
                  f'hdiutil detach -quiet "{mnt}"; [ -d "{app_path}.new" ] && rm -rf "{app_path}.old" && '
                  f'mv "{app_path}" "{app_path}.old" && mv "{app_path}.new" "{app_path}" && rm -rf "{app_path}.old"; '
                  f'open -n "{app_path}"' + (" --args " + " ".join(args) if args else ""))
        return ["/bin/sh", "-c", script]
    return None


def staging_dir():
    return os.path.join(core.user_config_dir(), "update")


def selftest():
    import shutil
    import tempfile
    d = tempfile.mkdtemp()
    try:
        # installed copies: which kind, which file of the release, checksum or nothing, the AppImage swapped in place
        assert install_kind(env={"APPIMAGE": "/x/S.AppImage"}) == "appimage"
        assert install_kind(frozen=False, env={}) is None
        assert install_kind(frozen=True, platform="win32", env={}, portable=False) == "windows"
        assert install_kind(frozen=True, platform="win32", env={}, portable=True) is None  # a USB copy is left alone
        assert install_kind(frozen=True, platform="darwin", env={}, machine="arm64", portable=False) == "mac-arm"
        assert install_kind(frozen=True, platform="darwin", env={}, machine="x86_64", portable=False) == "mac-intel"
        assert install_kind(frozen=True, platform="linux", env={}, portable=False) == "linux-install"
        rel = os.path.join(d, "release")
        os.makedirs(rel)
        files = {"SimpleBrain-x86_64.AppImage": b"#!/bin/sh\necho new\n", "SimpleBrain-0.9.0-windows-setup.exe": b"MZ",
                 "SimpleBrain-0.9.0-mac-ARM64.dmg": b"dmg", "SimpleBrain-0.9.0-mac-X64.dmg": b"dmg-intel"}
        import hashlib
        for n, b in files.items():
            open(os.path.join(rel, n), "wb").write(b)
        sums = "".join(f"{hashlib.sha256(b).hexdigest()}  {n}\n" for n, b in files.items())
        open(os.path.join(rel, "SHA256SUMS"), "w").write(sums)
        url = lambda n: "file://" + os.path.join(rel, n).replace("\\", "/") if os.name != "nt" else "file:///" + os.path.join(rel, n).replace("\\", "/")
        info = {"tag": "v0.9.0", "via": "web", "assets": {n: url(n) for n in [*files, "SHA256SUMS"]}}
        assert pick_asset(info, "windows") == "SimpleBrain-0.9.0-windows-setup.exe"
        assert pick_asset(info, "mac-intel") == "SimpleBrain-0.9.0-mac-X64.dmg" and pick_asset(info, "linux-install") == "SimpleBrain-x86_64.AppImage"
        staged = stage_update(info, "appimage", os.path.join(d, "stage"))
        mine = os.path.join(d, "SimpleBrain.AppImage")
        open(mine, "w").write("old")
        assert apply_now("appimage", staged, appimage=mine) and open(mine, "rb").read() == files["SimpleBrain-x86_64.AppImage"]
        assert os.access(mine, os.X_OK) or os.name == "nt"
        open(os.path.join(rel, "SimpleBrain-0.9.0-windows-setup.exe"), "wb").write(b"tampered")
        try:
            stage_update(info, "windows", os.path.join(d, "stage"))
            raise AssertionError("a file that doesn't match its checksum must never be installed")
        except OSError as e:
            assert "checksum" in str(e) and not os.path.exists(os.path.join(d, "stage", "SimpleBrain-0.9.0-windows-setup.exe"))
        bare = {"tag": "v0.9.0", "via": "web", "assets": {"SimpleBrain-0.9.0-mac-ARM64.dmg": url("SimpleBrain-0.9.0-mac-ARM64.dmg")}}
        try:
            stage_update(bare, "mac-arm", os.path.join(d, "stage"))
            raise AssertionError("no checksum, no install")
        except OSError as e:
            assert "checksum" in str(e)
        win = restart_command("windows", r"C:\t\setup.exe", r"C:\p\SimpleBrain.exe", ["--toggle"])
        assert win[:2] == ["cmd", "/c"] and "/VERYSILENT" in win[2] and win[2].endswith("SimpleBrain.exe --toggle")
        mac = restart_command("mac-arm", "/t/s.dmg", "/Applications/SimpleBrain.app")
        assert "hdiutil attach" in mac[2] and mac[2].rstrip().endswith('open -n "/Applications/SimpleBrain.app"')
        assert restart_command("appimage", "x", "y") is None

        # a git checkout behind its upstream is brought up to date; local edits or own commits stop it
        if shutil.which("git"):
            g = lambda repo, *a: subprocess.run(["git", "-C", repo, *a], capture_output=True, text=True, check=True)
            origin, mine = os.path.join(d, "origin.git"), os.path.join(d, "mine")
            subprocess.run(["git", "init", "-q", "--bare", "-b", "main", origin], check=True)
            subprocess.run(["git", "clone", "-q", origin, mine], check=True, capture_output=True)
            for repo in (mine,):
                g(repo, "config", "user.email", "t@t")
                g(repo, "config", "user.name", "t")
            open(os.path.join(mine, "app.py"), "w").write("v1\n")
            g(mine, "add", ".")
            g(mine, "commit", "-qm", "v1")
            g(mine, "push", "-q", "origin", "HEAD:main")
            g(mine, "branch", "-q", "--set-upstream-to", "origin/main")
            assert git_update(mine) == ("current", [])
            other = os.path.join(d, "other")
            subprocess.run(["git", "clone", "-q", origin, other], check=True, capture_output=True)
            g(other, "config", "user.email", "t@t")
            g(other, "config", "user.name", "t")
            open(os.path.join(other, "app.py"), "w").write("v2\n")
            open(os.path.join(other, "requirements.txt"), "w").write("x\n")
            g(other, "add", ".")
            g(other, "commit", "-qm", "v2")
            g(other, "push", "-q", "origin", "HEAD:main")
            open(os.path.join(mine, "app.py"), "w").write("my edit\n")
            assert git_update(mine)[0] == "local changes"  # an edit to the code is never overwritten
            g(mine, "checkout", "-q", "app.py")
            state, changed = git_update(mine)
            assert state == "updated" and sorted(changed) == ["app.py", "requirements.txt"]
            assert open(os.path.join(mine, "app.py")).read() == "v2\n"
            assert pip_command(mine, changed, "py")[:4] == ["py", "-m", "pip", "install"]
            assert pip_command(mine, ["app.py"]) is None
            assert checkout_dir(os.path.join(mine, "app.py")) == mine and checkout_dir(os.path.join(d, "x.py")) is None
            # a copy left on a feature branch that was merged moves to main by itself
            g(mine, "checkout", "-q", "-b", "claude/feature")
            open(os.path.join(mine, "feat.py"), "w").write("f\n")
            g(mine, "add", ".")
            g(mine, "commit", "-qm", "feature")
            g(mine, "push", "-q", "origin", "claude/feature")
            g(other, "pull", "-q", "origin", "main")
            g(other, "fetch", "-q", "origin")
            g(other, "merge", "-q", "--no-ff", "-m", "merge feature", "origin/claude/feature")
            open(os.path.join(other, "app.py"), "w").write("v3\n")
            g(other, "commit", "-qam", "v3")
            g(other, "push", "-q", "origin", "HEAD:main")
            state, changed = git_update(mine)
            assert state == "updated" and "app.py" in changed, state
            assert g(mine, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() == "main"
            assert open(os.path.join(mine, "app.py")).read() == "v3\n" and os.path.exists(os.path.join(mine, "feat.py"))
            assert git_update(mine) == ("current", [])
            g(mine, "checkout", "-q", "-b", "mine-only")
            open(os.path.join(mine, "x.py"), "w").write("mine\n")
            g(mine, "add", ".")
            g(mine, "commit", "-qm", "mine")
            open(os.path.join(other, "app.py"), "w").write("v4\n")
            g(other, "commit", "-qam", "v4")
            g(other, "push", "-q", "origin", "HEAD:main")
            assert git_update(mine)[0] == "diverged"  # your own unpublished commits are never left behind
            lone = os.path.join(d, "lone")
            subprocess.run(["git", "init", "-q", lone], check=True)
            assert git_update(lone, fetch=False)[0] == "no upstream"
    finally:
        shutil.rmtree(d, ignore_errors=True)
    print("update selftest OK")


if __name__ == "__main__":
    selftest()
