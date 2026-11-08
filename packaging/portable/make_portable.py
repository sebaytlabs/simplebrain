#!/usr/bin/env python3
"""Assemble a portable folder for a USB drive from a PyInstaller build.

    python packaging/portable/make_portable.py /path/to/drive [--dist dist]

Result (run it once on each OS; the folders merge into the same drive):

    drive/
      simplebrain-settings.json   shared: {"vault": "Vault"}, relative, so the drive can change letter
      Vault/                      the notes; every OS reads and writes the same folder
      Windows/SimpleBrain.exe     (+ _internal/)
      Mac/SimpleBrain.app
      Linux/SimpleBrain-x86_64.AppImage   (or Linux/SimpleBrain + _internal/)

Each program sits exactly one folder below the drive root, so it finds the shared settings
file one folder up. The settings file beside (or one folder above) the program is what switches SimpleBrain into
portable mode: it finds Vault relative to itself. Format the drive exFAT so all three systems
can write to it.
"""
import json
import os
import shutil
import sys


def main(argv):
    if not argv or argv[0].startswith("-"):
        sys.exit(__doc__)
    drive = os.path.abspath(argv[0])
    dist = os.path.abspath(argv[argv.index("--dist") + 1]) if "--dist" in argv else "dist"
    plat = {"win32": "Windows", "darwin": "Mac"}.get(sys.platform, "Linux")
    dest = os.path.join(drive, plat)
    parts = [("SimpleBrain.app", os.path.join(dest, "SimpleBrain.app")),
             ("SimpleBrain-x86_64.AppImage", os.path.join(dest, "SimpleBrain-x86_64.AppImage")),
             ("SimpleBrain", dest)]  # the PyInstaller folder: its contents go straight into dest
    copied = False
    for name, target in parts:
        src = os.path.join(dist, name)
        if not os.path.exists(src):
            continue
        if sys.platform == "linux" and name == "SimpleBrain" and copied:
            continue  # the AppImage already wraps the folder
        os.makedirs(dest, exist_ok=True)
        if os.path.isdir(src):
            if name != "SimpleBrain":  # the .app bundle replaces any older copy
                shutil.rmtree(target, ignore_errors=True)
            shutil.copytree(src, target, symlinks=True, dirs_exist_ok=True)
        else:
            shutil.copy2(src, target)
        print("copied", target)
        copied = True
    if not copied:
        sys.exit(f"Nothing to copy: build first (pyinstaller packaging/simplebrain.spec), looked in {dist}")
    os.makedirs(os.path.join(drive, "Vault"), exist_ok=True)
    settings = os.path.join(drive, "simplebrain-settings.json")
    if not os.path.exists(settings):  # never replace a drive's existing choice
        with open(settings, "w", encoding="utf-8", newline="\n") as f:
            json.dump({"vault": "Vault"}, f, indent=2)
        print("wrote", settings)
    print("done:", drive)


if __name__ == "__main__":
    main(sys.argv[1:])
