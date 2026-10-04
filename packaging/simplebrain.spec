# PyInstaller build: pyinstaller packaging/simplebrain.spec
# Produces dist/SimpleBrain/ (Windows, Linux) or dist/SimpleBrain.app (macOS).
import os
import sys

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
ICON = os.path.join(SPECPATH, "icon.png")  # PyInstaller converts to .ico/.icns (needs Pillow)

a = Analysis(
    [os.path.join(ROOT, "simplebrain_app.py")],
    pathex=[ROOT],
    datas=[(ICON, "."), (os.path.join(ROOT, "THIRD-PARTY-NOTICES.md"), "."),
           (os.path.join(ROOT, "LICENSE"), "."), (os.path.join(ROOT, "LICENSES"), "LICENSES")],
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
