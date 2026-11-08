#!/usr/bin/env python3
"""SimpleBrain as part of the Linux Mint desktop (X11, Xfce): files, videos and web links from a note open
in their own windows, placed beside the note; the playing video's time for the note; SimpleBrain up as
the desktop at login, Super+J to bring it forward and send it back. Each piece checks for its tool and
quietly does less without it. No Qt here.

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


def showing_desktop():
    return "showing the desktop: on" in _run(["wmctrl", "-m"]).lower()


def show_desktop(on):
    """Xfce's own Show Desktop (Super+D): every window out of the way, the desktop (SimpleBrain) in front."""
    _run(["wmctrl", "-k", "on" if on else "off"])


# ---------- hooking SimpleBrain into the Xfce session (no sudo) ----------

SHORTCUTS = {"<Super>j": "--toggle"}  # the key the old Jarvis display had
OLD_AUTOSTARTS = ("jarvis-hud.desktop",)


def app_command(app_file):
    """How a shortcut starts this SimpleBrain: the AppImage or installed build, else this source checkout."""
    if os.environ.get("APPIMAGE"):
        return [os.environ["APPIMAGE"]]
    if getattr(sys, "frozen", False):
        return [sys.executable]
    return [sys.executable, os.path.abspath(app_file)]


def _xfconf(args):
    try:
        out = subprocess.run(["xfconf-query", "-c", "xfce4-keyboard-shortcuts", *args],
                             capture_output=True, text=True, timeout=5)
        return out.returncode, out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return 1, ""


RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
AGENT = "app.simplebrain.plist"


def _winreg_run(name, value):
    """Set (value) or delete (None) a per-user Run entry: Windows starts it at every sign-in."""
    import winreg
    try:  # CreateKeyEx: a fresh account may not have the Run key yet
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            if value is None:
                winreg.DeleteValue(k, name)
            else:
                winreg.SetValueEx(k, name, 0, winreg.REG_SZ, value)
    except OSError:
        return False
    return True


def start_at_login(cmd, on, home=None, platform=sys.platform, reg=_winreg_run):
    """Windows and macOS: open SimpleBrain at login (on Today) or stop. Returns what it did."""
    home = home or os.path.expanduser("~")
    if platform == "win32":
        ok = reg("SimpleBrain", subprocess.list2cmdline([*cmd, "--desktop"]) if on else None)
    elif platform == "darwin":
        path = os.path.join(home, "Library", "LaunchAgents", AGENT)
        if on:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            args = "".join(f"<string>{a.replace('&', '&amp;').replace('<', '&lt;')}</string>" for a in [*cmd, "--desktop"])
            with open(path, "w", encoding="utf-8") as f:
                f.write('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
                        '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n<plist version="1.0"><dict>'
                        f"<key>Label</key><string>app.simplebrain</string><key>ProgramArguments</key><array>{args}</array>"
                        "<key>RunAtLoad</key><true/></dict></plist>\n")
            ok = True
        else:
            try:
                os.remove(path)
                ok = True
            except OSError:
                ok = False
    else:
        return []
    if not ok:
        return []
    return ["SimpleBrain opens on Today when you log in" if on else "SimpleBrain no longer opens when you log in"]


def integrate(cmd, home=None, xfconf=_xfconf, platform=sys.platform):
    """SimpleBrain up as the desktop at login, Super+J to bring it forward and send it back, and the
    old Jarvis display's autostart switched off (Hidden=true: nothing is deleted). A shortcut it replaces
    is saved once to ~/.config/SimpleBrain/old-shortcuts.json. Returns what it did, in plain words.
    On Windows and macOS: open at login, on Today (there's no desktop layer to take over there)."""
    if not platform.startswith("linux"):
        return start_at_login(cmd, True, home, platform)
    home = home or os.path.expanduser("~")
    auto = os.path.join(home, ".config", "autostart")
    os.makedirs(auto, exist_ok=True)
    exe = shlex.join(cmd)
    with open(os.path.join(auto, "simplebrain.desktop"), "w", encoding="utf-8") as f:
        f.write("[Desktop Entry]\nType=Application\nName=SimpleBrain\nComment=Your notes as your desktop\n"
                f"Exec={exe} --desktop\nIcon=simplebrain\nX-GNOME-Autostart-enabled=true\nTerminal=false\n")
    done = ["SimpleBrain is your desktop from the next login on"]
    for name in OLD_AUTOSTARTS:
        path = os.path.join(auto, name)
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                text = f.read()
            if "Hidden=true" not in text:
                with open(path, "a", encoding="utf-8") as f:
                    f.write("\nHidden=true\n")
                done.append(f"{name} no longer starts at login (file kept)")
    saved_path = os.path.join(home, ".config", "SimpleBrain", "old-shortcuts.json")
    try:
        with open(saved_path, encoding="utf-8") as f:
            saved = json.load(f)
    except (OSError, ValueError):
        saved = {}
    keys_ok = True
    for key, flag in SHORTCUTS.items():
        prop = f"/commands/custom/{key}"
        code, old = xfconf(["-p", prop])
        want = f"{exe} {flag}"
        if code == 0 and old and old != want and key not in saved:
            saved[key] = old
        if xfconf(["-p", prop, "-n", "-t", "string", "-s", want])[0] != 0:
            keys_ok = False
    if saved:
        os.makedirs(os.path.dirname(saved_path), exist_ok=True)
        with open(saved_path, "w", encoding="utf-8") as f:
            json.dump(saved, f, indent=1)
    done.append("Super+J brings SimpleBrain forward and sends it back" if keys_ok
                else f"Keyboard shortcut not set (not an Xfce desktop): add Super+J → '{exe} --toggle' in your keyboard settings")
    return done


TOOLS = {"wmctrl": "wmctrl", "mpv": "mpv", "xprop": "x11-utils"}


def missing_packages(have=have):
    return sorted({pkg for cmd, pkg in TOOLS.items() if not have(cmd)})


def install_command(pkgs, have=have):
    """One graphical password prompt (pkexec) installs what's missing; None when it can't be done that way."""
    if not pkgs or not (have("pkexec") and have("apt-get")):
        return None
    return ["pkexec", "apt-get", "install", "-y", *pkgs]


def unintegrate(home=None, xfconf=_xfconf, platform=sys.platform):
    """Undo integrate: no autostart, Super+J back to what it was (or free), the old autostart back on."""
    if not platform.startswith("linux"):
        return start_at_login([], False, home, platform)
    home = home or os.path.expanduser("~")
    auto = os.path.join(home, ".config", "autostart")
    done = []
    try:
        os.remove(os.path.join(auto, "simplebrain.desktop"))
        done.append("SimpleBrain no longer starts with your login")
    except OSError:
        pass
    for name in OLD_AUTOSTARTS:
        path = os.path.join(auto, name)
        try:
            with open(path, encoding="utf-8") as f:
                text = f.read()
        except OSError:
            continue
        if "\nHidden=true\n" in text:
            with open(path, "w", encoding="utf-8") as f:
                f.write(text.replace("\nHidden=true\n", "", 1))
            done.append(f"{name} starts at login again")
    try:
        with open(os.path.join(home, ".config", "SimpleBrain", "old-shortcuts.json"), encoding="utf-8") as f:
            saved = json.load(f)
    except (OSError, ValueError):
        saved = {}
    for key in SHORTCUTS:
        prop = f"/commands/custom/{key}"
        if key in saved:
            xfconf(["-p", prop, "-n", "-t", "string", "-s", saved[key]])
            done.append(f"{key.replace('<Super>', 'Super+').upper()} does what it did before")
        else:
            xfconf(["-p", prop, "-r"])
    return done


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
        # Hooking into the session: a temp home and a fake xfconf, never the real desktop.
        home, store = os.path.join(d, "home"), {"/commands/custom/<Super>j": "/home/me/.local/bin/jarvis hud on"}
        os.makedirs(os.path.join(home, ".config", "autostart"))
        with open(os.path.join(home, ".config", "autostart", "jarvis-hud.desktop"), "w") as f:
            f.write("[Desktop Entry]\nExec=jarvis hud on\n")

        def fake(args):
            if "-s" in args:
                store[args[1]] = args[-1]
                return 0, ""
            return (0, store[args[1]]) if args[1] in store else (1, "")
        said = integrate(["/opt/sb app"], home, fake, platform="linux")
        assert store["/commands/custom/<Super>j"] == "'/opt/sb app' --toggle"
        with open(os.path.join(home, ".config", "SimpleBrain", "old-shortcuts.json")) as f:
            assert json.load(f) == {"<Super>j": "/home/me/.local/bin/jarvis hud on"}  # the old Super+J is kept
        with open(os.path.join(home, ".config", "autostart", "simplebrain.desktop")) as f:
            assert "Exec='/opt/sb app' --desktop" in f.read()
        with open(os.path.join(home, ".config", "autostart", "jarvis-hud.desktop")) as f:
            assert f.read().endswith("Hidden=true\n")
        integrate(["/opt/sb app"], home, fake, platform="linux")  # again: the saved old shortcut isn't overwritten by ours
        with open(os.path.join(home, ".config", "SimpleBrain", "old-shortcuts.json")) as f:
            assert json.load(f)["<Super>j"].startswith("/home/me")
        assert len(said) == 3
        undone = unintegrate(home, fake, platform="linux")
        assert store["/commands/custom/<Super>j"] == "/home/me/.local/bin/jarvis hud on" and len(undone) == 3
        assert not os.path.exists(os.path.join(home, ".config", "autostart", "simplebrain.desktop"))
        with open(os.path.join(home, ".config", "autostart", "jarvis-hud.desktop")) as f:
            assert "Hidden=true" not in f.read()
        # Windows: a per-user Run entry; macOS: a LaunchAgent. Both opening on Today; both undone.
        runs = {}
        def fake_reg(name, value):
            if value is None:
                return runs.pop(name, None) is not None
            runs[name] = value
            return True
        assert start_at_login([r"C:\Program Files\SimpleBrain\SimpleBrain.exe"], True, home, "win32", fake_reg)
        assert runs["SimpleBrain"] == '"C:\\Program Files\\SimpleBrain\\SimpleBrain.exe" --desktop'
        assert start_at_login([], False, home, "win32", fake_reg) and runs == {}
        assert integrate(["/Applications/SimpleBrain.app/Contents/MacOS/SimpleBrain"], home, platform="darwin")
        with open(os.path.join(home, "Library", "LaunchAgents", AGENT)) as f:
            plist = f.read()
        assert "<string>/Applications/SimpleBrain.app/Contents/MacOS/SimpleBrain</string><string>--desktop</string>" in plist
        assert unintegrate(home, platform="darwin") and not os.path.exists(os.path.join(home, "Library", "LaunchAgents", AGENT))
        assert missing_packages(lambda c: c != "mpv") == ["mpv"]
        assert install_command(["mpv"], lambda c: True) == ["pkexec", "apt-get", "install", "-y", "mpv"]
        assert install_command(["mpv"], lambda c: c != "pkexec") is None and install_command([]) is None
    finally:
        shutil.rmtree(d, ignore_errors=True)
    print("desk selftest OK")


if __name__ == "__main__":
    selftest()
