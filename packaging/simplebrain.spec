# PyInstaller build: pyinstaller packaging/simplebrain.spec
# Produces dist/SimpleBrain/ (Windows, Linux) or dist/SimpleBrain.app (macOS).
import os
import sys

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
import glob
import importlib.util
HAVE_IROH = importlib.util.find_spec("iroh") is not None  # no iroh build for Intel Macs: sync is off there
XCB_CURSOR = sorted(glob.glob("/usr/lib/*-linux-gnu/libxcb-cursor.so.0*") + glob.glob("/usr/lib64/libxcb-cursor.so.0*"))[:1] \
    if sys.platform.startswith("linux") else []
ICON = os.path.join(SPECPATH, "icon.png")  # PyInstaller converts to .ico/.icns (needs Pillow)

a = Analysis(
    [os.path.join(ROOT, "simplebrain_app.py")],
    pathex=[ROOT],
    datas=[(ICON, "."), (os.path.join(ROOT, "THIRD-PARTY-NOTICES.md"), "."),
           (os.path.join(ROOT, "LICENSE"), "."), (os.path.join(ROOT, "LICENSES"), "LICENSES")]
    + collect_data_files("tzdata"),  # Windows has no system time zones; calendar feeds name them
    # iroh (device sync) loads its native library by path next to its module, so PyInstaller can't see it
    # iroh's native library, and on Linux libxcb-cursor: Qt 6.5+ needs it to start, and a fresh Ubuntu/Mint
    # install doesn't have it, so the program carries its own copy
    binaries=(collect_dynamic_libs("iroh") if HAVE_IROH else []) + [(p, ".") for p in XCB_CURSOR],
    hiddenimports=(["iroh"] if HAVE_IROH else []) + ["tzdata"],
    excludes=["tkinter", "gi"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="SimpleBrain",
    console=False,
    icon=ICON,
)
coll = COLLECT(exe, a.binaries, a.datas, name="SimpleBrain")

if sys.platform == "darwin":
    sys.path.insert(0, ROOT)
    from simplebrain_core import VERSION
    app = BUNDLE(
        coll,
        name="SimpleBrain.app",
        icon=ICON,
        bundle_identifier="app.simplebrain",
        info_plist={"CFBundleShortVersionString": VERSION, "CFBundleVersion": VERSION,
                    "NSHighResolutionCapable": True},
    )
