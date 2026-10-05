# SimpleBrain

A note app that doesn't make you configure it. Notes with `[[links]]`, a live
graph of how they connect, tasks with due dates, a calendar, and an inbox where
you type a thought and file it with one click. No plugins, no query language,
no account. Your notes are plain Markdown files in a folder you own.

## Install

Linux (x86-64): download `SimpleBrain-x86_64.AppImage` from the
[latest release](https://github.com/sebaytlabs/simplebrain/releases/latest),
then:

```
chmod +x SimpleBrain-x86_64.AppImage
./SimpleBrain-x86_64.AppImage
```

Windows and macOS builds aren't available yet. To build from source, see below.

## Using it

- **Capture:** type anything in the bar at the top and press Enter. It lands in
  the Inbox, where one click files it as a **Task**, **Event** or **Note**.
- **Notes:** link notes by writing `[[Note Name]]`. Clicking a link opens (or
  creates) that note. The graph shows every link; click a dot to open it.
- **Tasks:** any line like `t call the bank due:10-01-2026` in any note
  shows up under Overdue / Today / Upcoming / No date. Ticking it makes it
  `- [x] …`; old `- [ ] …` lines are converted to `t …` automatically.
- **Shorthand** (any note, on save): a line starting `i ` moves to the Inbox,
  `c 10-05-2026 2pm dentist` moves to the Calendar (time optional).
  Lowercase only, so `I think…` is left alone.
- **Calendar:** add local events, or show a read-only calendar feed by adding
  `ICS_URL=https://…` to the `.config` file in your notes folder.
- **Dataview:** every note in a table, filterable by `#tag` or title. The
  matching notes light up orange in the graph.
- **Answers:** under a numbered question, write `answer:: your answer`. Each
  `[[Keyword]]` you link gets a `Keyword - Answers` note listing every note
  that links to it, then all their answers. It rebuilds on save; don't edit it.

Your notes live in `Documents/SimpleBrain` (File → Open vault folder). Deleted
notes go to `.trash` inside it, never straight to oblivion.

**Settings** (in `.config` in your notes folder):

| Line | Effect |
|---|---|
| `ICS_URL=https://…` | Show a calendar feed (treat the URL like a password) |

Set the environment variable `SIMPLEBRAIN_VAULT` to use a different notes
folder, e.g. a USB drive.

## Build from source

Linux, Python 3.10+. Build, test and install it into your app menu:

```
git clone https://github.com/sebaytlabs/simplebrain.git
cd simplebrain
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements-build.txt
python simplebrain_core.py
QT_QPA_PLATFORM=offscreen python tests/test_app.py
pyinstaller packaging/simplebrain.spec
packaging/linux/install.sh
```

The two tests print `selftest OK` and `app test OK`. `install.sh` puts the app
in `~/.local/share/simplebrain/app`, adds it to your app menu and adds a
`simplebrain` command. Run it again after a rebuild to update. To run from
source without installing: `python simplebrain_app.py`.

Portable AppImage: after `pyinstaller`, run `packaging/linux/build-appimage.sh`. Release builds use
`packaging/linux/build-in-docker.sh`, which compiles inside Ubuntu 22.04 so the
AppImage runs on older distributions too. On Windows, with Inno Setup:

```
python -c "from PIL import Image; Image.open('packaging/icon.png').save('build/icon.ico', sizes=[(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)])"
iscc /DAppVersion=<VERSION from simplebrain_core.py> packaging\windows\simplebrain.iss
```

## Project layout

- `simplebrain_core.py`: notes, links, tasks, inbox, calendar, answers. No UI.
- `simplebrain_app.py`: the desktop app (Qt).
- `packaging/`: icon, PyInstaller spec, Linux AppImage/install scripts, Windows installer.

## License

MIT, see [LICENSE](LICENSE).
