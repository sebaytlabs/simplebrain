#!/usr/bin/env python3
"""SimpleBrain and the rest of the computer: files, videos and web links from a note open in their own windows
(placed beside the note where the system allows: X11 with wmctrl), the playing video's time for the note, your
web accounts as app windows, the app-menu entry of the Linux AppImage. Each piece checks for its tool and
quietly does less without it, on Windows and macOS too. No Qt here.

Run: python simplebrain_desk.py   (selftest; window placement runs when an X display is up)
"""
import json
import os
import re
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import time

MEDIA_EXTS = {".mp3", ".m4a", ".m4b", ".wav", ".ogg", ".opus", ".flac", ".aac", ".wma",
              ".mp4", ".m4v", ".mkv", ".webm", ".avi", ".mov", ".wmv", ".mpg", ".mpeg", ".vob"}


def have(cmd):
    return shutil.which(cmd) is not None


def x11():
    return bool(os.environ.get("DISPLAY")) and os.environ.get("XDG_SESSION_TYPE", "x11") != "wayland"


def _run(args, timeout=2):
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def mpv_socket():
    return os.path.join(tempfile.gettempdir(), f"simplebrain-mpv-{os.getuid() if hasattr(os, 'getuid') else 0}")


BROWSERS = ("librewolf", "firefox", "chromium", "google-chrome", "brave-browser")


def open_command(path):
    """Media plays in mpv (windowed, never full screen, resuming where you left off, with a control
    socket so the note can ask what time it is); a web link gets its own browser window, not a tab
    lost among others; everything else opens in its usual program."""
    if path.startswith(("http://", "https://")):
        for b in BROWSERS:
            if have(b):
                return [b, "--new-window", path]
        if sys.platform == "darwin":
            return ["open", path]
        if os.name == "nt":
            return ["cmd", "/c", "start", "", path]
        return ["xdg-open", path] if have("xdg-open") else None
    if os.path.splitext(path)[1].lower() in MEDIA_EXTS and have("mpv"):
        return ["mpv", "--force-window=immediate", "--save-position-on-quit", "--no-fullscreen",
                f"--input-ipc-server={mpv_socket()}", path]
    if sys.platform == "darwin":
        return ["open", path]
    if os.name == "nt":
        return ["cmd", "/c", "start", "", path]
    return ["xdg-open", path] if have("xdg-open") else None


# ---------- your accounts as apps: one window each, one sign-in that stays ----------

APP_LINE = re.compile(r"^\s*app::\s*(.+?)\s+(https?://\S+)\s*$", re.I | re.M)
CHROMIUMS = ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable", "brave-browser", "microsoft-edge",
             "vivaldi")
EDGE_WIN = (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe")


def web_apps(texts):
    """[(name, url)] from `app:: Fastmail https://app.fastmail.com` lines (Home, or a note called Apps)."""
    out = {}
    for text in texts:
        for name, url in APP_LINE.findall(text):
            out.setdefault(name.strip(), url)
    return list(out.items())


def webapp_command(url, profile, platform=None, have=have, exists=os.path.exists):
    """A site as its own app window. A Chromium-family browser gives a real app window (no tabs, no address bar)
    with one SimpleBrain profile, so you sign in once and stay signed in for every app; otherwise a new window of
    your usual browser, whose own sign-ins stay too."""
    platform = platform or sys.platform
    if platform == "win32":
        edge = next((e for e in EDGE_WIN if exists(e)), None)
        if edge:
            return [edge, f"--app={url}", f"--user-data-dir={profile}"]
        return ["cmd", "/c", "start", "", url]
    if platform == "darwin":
        for app in ("Google Chrome", "Brave Browser", "Microsoft Edge", "Chromium"):
            if exists(f"/Applications/{app}.app"):
                return ["open", "-na", app, "--args", f"--app={url}", f"--user-data-dir={profile}"]
        return ["open", url]
    for b in CHROMIUMS:
        if have(b):
            return [b, f"--app={url}", f"--user-data-dir={profile}", "--no-first-run"]
    return open_command(url)


def _slug(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "app"


def sync_launchers(apps, profile, home=None, have=have):
    """Linux: each web app also in your app menu (simplebrain-web-*.desktop); ones you took out of the list go.
    Returns the names written."""
    home = home or os.path.expanduser("~")
    folder = os.path.join(home, ".local", "share", "applications")
    os.makedirs(folder, exist_ok=True)
    want = {}
    for name, url in apps:
        cmd = webapp_command(url, profile, platform="linux", have=have)
        if not cmd:
            continue
        want[f"simplebrain-web-{_slug(name)}.desktop"] = (
            "[Desktop Entry]\nType=Application\n"
            f"Name={name}\nComment={url} (from SimpleBrain)\nExec={shlex.join(cmd)}\nIcon=internet-web-browser\n"
            "Terminal=false\nCategories=Network;\nX-SimpleBrain=web\n")
    for f in os.listdir(folder):
        if f.startswith("simplebrain-web-") and f not in want:
            os.remove(os.path.join(folder, f))
    for f, text in want.items():
        path = os.path.join(folder, f)
        try:
            with open(path, encoding="utf-8") as fh:
                if fh.read() == text:
                    continue
        except OSError:
            pass
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
    return sorted(n for n, _ in apps)


def appimage_menu_entry(appimage, icon, home=None):
    """The AppImage in the app menu the first time it runs (and again if it was moved): no install step."""
    home = home or os.path.expanduser("~")
    apps = os.path.join(home, ".local", "share", "applications")
    path = os.path.join(apps, "simplebrain.desktop")
    want = (f"[Desktop Entry]\nType=Application\nName=SimpleBrain\nComment=Notes, tasks, calendar and your day\n"
            f"Exec={shlex.quote(appimage)} %F\nIcon=simplebrain\nTerminal=false\nCategories=Office;Utility;\n"
            "StartupWMClass=SimpleBrain\n")
    try:
        with open(path, encoding="utf-8") as f:
            if f.read() == want:
                return False
    except OSError:
        pass
    try:
        os.makedirs(apps, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(want)
        icons = os.path.join(home, ".local", "share", "icons", "hicolor", "512x512", "apps")
        os.makedirs(icons, exist_ok=True)
        if os.path.exists(icon):
            shutil.copyfile(icon, os.path.join(icons, "simplebrain.png"))
    except OSError:
        return False
    return True


IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg", ".tif", ".tiff", ".ico"}


def can_embed(platform=None, have=have, x11=x11):
    """mpv can draw inside SimpleBrain's own window on X11 (Linux Mint) and Windows; elsewhere it opens beside."""
    platform = platform or sys.platform
    return have("mpv") and ((platform.startswith("linux") and x11()) or platform == "win32")


def embed_command(path, wid):
    """mpv drawing into SimpleBrain's viewer (window id `wid`): never full screen, resumes where you stopped, and keeps
    the control socket, so Ctrl+T in the note still writes where the video is."""
    # only outputs that draw into a given window: without a working GPU (an old machine) mpv would otherwise fall
    # back to one (sdl) that ignores --wid and opens a window of its own
    return ["mpv", f"--wid={int(wid)}", "--vo=gpu,x11" if not sys.platform == "win32" else "--vo=gpu,direct3d", "--keep-open=yes", "--force-window=yes", "--no-fullscreen", "--osc=yes",
            "--save-position-on-quit", "--no-terminal", f"--input-ipc-server={mpv_socket()}", path]


def mpv_quit(path=None, timeout=0.5):
    """Ask the mpv on the control socket to stop, remembering where it was (quit-watch-later). True if it answered."""
    path = path or mpv_socket()
    if not hasattr(socket, "AF_UNIX") or not os.path.exists(path):
        return False
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            s.connect(path)
            s.sendall(b'{"command": ["quit-watch-later"]}\n')
        return True
    except OSError:
        return False


def launch(cmd):
    try:
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        return True
    except OSError:
        return False


def video_time(path=None, timeout=0.5):
    """'12:34' (or '1:02:03') where the mpv opened from a note is, or None when nothing is playing."""
    path = path or mpv_socket()
    if not hasattr(socket, "AF_UNIX") or not os.path.exists(path):
        return None
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            s.connect(path)
            s.sendall(b'{"command": ["get_property", "time-pos"]}\n')
            buf = b""
            while b"\n" not in buf:
                chunk = s.recv(4096)
                if not chunk:
                    break
                buf += chunk
        for line in buf.splitlines():
            msg = json.loads(line)
            if "data" in msg and isinstance(msg["data"], (int, float)):
                t = int(msg["data"])
                return f"{t // 3600}:{t % 3600 // 60:02d}:{t % 60:02d}" if t >= 3600 else f"{t // 60}:{t % 60:02d}"
    except (OSError, ValueError):
        return None
    return None


def windows():
    """{window id: title} of the normal windows (wmctrl), or {} without it."""
    if not (x11() and have("wmctrl")):
        return {}
    out = {}
    for line in _run(["wmctrl", "-l"]).splitlines():
        parts = line.split(None, 3)
        if len(parts) >= 3:
            out[parts[0]] = parts[3] if len(parts) > 3 else ""
    return out


def activate(wid):
    """Bring a window up and give it the keyboard (an open window found from the top bar, SimpleBrain on Super+J).
    False when it can't be done here (no wmctrl, not X11): nothing breaks, the window just stays where it is."""
    if not (wid and x11() and have("wmctrl")):
        return False
    _run(["wmctrl", "-i", "-a", str(wid)])
    return True


def place(wid, rect):
    """Move a window to (x, y, w, h), un-maximized, and bring it up."""
    if not (wid and have("wmctrl")):
        return False
    x, y, w, h = rect
    _run(["wmctrl", "-i", "-r", wid, "-b", "remove,maximized_vert,maximized_horz,fullscreen"])
    _run(["wmctrl", "-i", "-r", wid, "-e", f"0,{x},{y},{w},{h}"])
    _run(["wmctrl", "-i", "-a", wid])
    return True


def beside(area, keep_right_edge, min_width=640):
    """Where a file opened from a note goes: from the right edge of what must stay visible (the notes
    list and the editor) to the screen's right edge; never narrower than min_width."""
    x, y, w, h = area
    left = min(max(keep_right_edge, x), x + w - min_width)
    return left, y, x + w - left, h


def selftest():
    import tempfile as _tf
    # every desk.something the window calls exists here (activate() was lost once in a revert and crashed Super+J)
    app_src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "simplebrain_app.py"), encoding="utf-8").read()
    called = set(re.findall(r"\bdesk\.([a-z_][a-z0-9_]*)\(", app_src))
    missing = sorted(n for n in called if not callable(globals().get(n)))
    assert not missing, f"simplebrain_app calls desk functions that don't exist: {missing}"
    assert activate("0x1") in (True, False) and activate(None) is False
    assert can_embed("linux", have=lambda c: True, x11=lambda: True) and can_embed("win32", have=lambda c: True)
    assert not can_embed("darwin", have=lambda c: True) and not can_embed("linux", have=lambda c: False, x11=lambda: True)
    assert not can_embed("linux", have=lambda c: True, x11=lambda: False)  # Wayland without X: beside, as before
    e = embed_command("/v/s 1.mp4", 12345)
    assert e[0] == "mpv" and "--wid=12345" in e and "--no-fullscreen" in e and e[-1] == "/v/s 1.mp4"
    assert any(a.startswith("--input-ipc-server=") for a in e)  # Ctrl+T keeps working
    assert any(a.startswith("--vo=gpu,") for a in e)  # never a video output that opens its own window
    ah = _tf.mkdtemp()
    ico = os.path.join(ah, "i.png")
    open(ico, "w").close()
    assert appimage_menu_entry("/opt/My Apps/SimpleBrain.AppImage", ico, home=ah)
    assert "Exec='/opt/My Apps/SimpleBrain.AppImage' %F" in open(os.path.join(ah, ".local/share/applications/simplebrain.desktop")).read()
    assert not appimage_menu_entry("/opt/My Apps/SimpleBrain.AppImage", ico, home=ah)  # once is enough
    apps = web_apps(["# Home\napp:: Fastmail https://app.fastmail.com\napp:: myRC https://my.riverside.example\n",
                     "app:: Fastmail https://other\nnot an app:: x"])
    assert apps == [("Fastmail", "https://app.fastmail.com"), ("myRC", "https://my.riverside.example")]
    prof = "/p"
    chromium = webapp_command("https://x.com", prof, platform="linux", have=lambda c: c == "chromium")
    assert chromium == ["chromium", "--app=https://x.com", "--user-data-dir=/p", "--no-first-run"]
    plain = webapp_command("https://x.com", prof, platform="linux", have=lambda c: c in ("librewolf",))
    assert plain is None or plain[-1] == "https://x.com"  # your usual browser, a new window
    win = webapp_command("https://x.com", prof, platform="win32", exists=lambda p: p == EDGE_WIN[1])
    assert win[0] == EDGE_WIN[1] and win[1] == "--app=https://x.com"
    assert webapp_command("https://x.com", prof, platform="darwin", exists=lambda p: "Brave" in p)[:3] == ["open", "-na", "Brave Browser"]
    h = _tf.mkdtemp()
    sync_launchers(apps, prof, home=h, have=lambda c: c == "chromium")
    menu = os.path.join(h, ".local", "share", "applications")
    assert sorted(os.listdir(menu)) == ["simplebrain-web-fastmail.desktop", "simplebrain-web-myrc.desktop"]
    assert "Exec=chromium --app=https://my.riverside.example" in open(os.path.join(menu, "simplebrain-web-myrc.desktop")).read()
    open(os.path.join(menu, "other.desktop"), "w").close()
    sync_launchers(apps[:1], prof, home=h, have=lambda c: c == "chromium")
    assert sorted(os.listdir(menu)) == ["other.desktop", "simplebrain-web-fastmail.desktop"]  # yours are never touched
    d = tempfile.mkdtemp()
    try:
        song, pdf = os.path.join(d, "session-01.mp3"), os.path.join(d, "Guide.pdf")
        if have("mpv"):
            c = open_command(song)
            assert c[0] == "mpv" and "--no-fullscreen" in c and c[-1] == song and any("ipc" in a for a in c)
        c = open_command(pdf)
        assert c is None or c[-1] == pdf
        assert beside((0, 30, 1920, 1050), 1100) == (1100, 30, 820, 1050)
        assert beside((0, 30, 1920, 1050), 1700) == (1280, 30, 640, 1050)  # never a sliver
        if have("librewolf") or have("firefox"):
            assert open_command("https://edube.org")[1:] == ["--new-window", "https://edube.org"]
        if hasattr(socket, "AF_UNIX"):  # a fake mpv answering on the control socket
            import threading
            path = os.path.join(d, "mpv.sock")
            srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            srv.bind(path)
            srv.listen(1)

            def answer():
                c, _ = srv.accept()
                c.recv(4096)
                c.sendall(b'{"event":"pause"}\n{"data":754.3,"request_id":0,"error":"success"}\n')
                c.close()
            threading.Thread(target=answer, daemon=True).start()
            assert video_time(path) == "12:34"
            srv.close()
            assert video_time(os.path.join(d, "none.sock")) is None
        if x11() and have("wmctrl") and have("xmessage") and _run(["wmctrl", "-m"]):
            before = set(windows())
            p = subprocess.Popen(["xmessage", "SimpleBrain test"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                for _ in range(50):
                    new = [w for w in windows() if w not in before]
                    if new:
                        break
                    time.sleep(0.1)
                assert new and place(new[0], (0, 0, 800, 600))
                geo = _run(["xwininfo", "-id", new[0]]) if have("xwininfo") else "Width: 800"
                assert "Width: 800" in geo or "Width: 7" in geo  # the window manager may keep a border
            finally:
                p.kill()
    finally:
        shutil.rmtree(d, ignore_errors=True)
    print("desk selftest OK")


if __name__ == "__main__":
    selftest()
