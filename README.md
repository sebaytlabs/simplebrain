# SimpleBrain

A second brain that doesn't make you configure it. Your notes are plain Markdown files in a folder you own, linked
with `[[double brackets]]` and drawn as a live graph. Around them: tasks with dates, a calendar, an inbox, a Today
page that hands you three things to do (never more), money projected forward, your files filed for you, your web
accounts as apps, and a quiet watcher that keeps you on track. No plugins, no query language, no account.

Built for someone with little time at the computer and a lot on their mind: every feature is one line or one click,
and it teaches itself to you one step at a time.

## Download

| Your computer | Get this from the [latest release](https://github.com/sebaytlabs/simplebrain/releases/latest) or the [Sebayt Labs store](https://sebaytlabs.com/products/simplebrain) | Then |
|---|---|---|
| Windows 10 or 11 | `SimpleBrain-<version>-windows-setup.exe` | Run it. If Windows says *protected your PC*: **More info → Run anyway** (once). |
| Mac with Apple chip (M1 and later) | `SimpleBrain-<version>-mac-ARM64.dmg` | Open it, drag SimpleBrain to Applications. First start: right-click → **Open** → **Open**. |
| Mac with Intel chip (2015–2020) | `SimpleBrain-<version>-mac-X64.dmg` | Same as above. Device sync isn't available on Intel Macs yet (its library has no build there); everything else is. |
| Linux (Mint, Ubuntu 22.04+, Debian, Fedora…) | `SimpleBrain-x86_64.AppImage` | `chmod +x SimpleBrain-x86_64.AppImage` then double-click it. It adds itself to your app menu. |
| All three | `SimpleBrain.zip` | Everything above in one download (what the store sells). |

### What works where

| | Windows | Mac | Linux |
|---|---|---|---|
| Notes, links, graph, tasks, Inbox, calendar, Today, budget, book notes | yes | yes | yes |
| Email, website publishing, book recommendations | yes | yes | yes |
| Sync between your devices | yes | Apple chip only | yes |
| Search across notes and files | yes | yes | yes |
| Search also lists open windows and installed apps | no | no | yes (X11) |
| Open a file beside its note, side by side | no | no | yes (X11, needs `wmctrl`) |
| Play a video inside a note and write down where it is (Ctrl+T) | needs [mpv](https://mpv.io) | needs mpv | needs mpv |

It runs on new laptops and on older ones: Qt is held below 6.10 (6.10 needs SSE4.2), so processors from before about 2009 still
work, the Linux build carries the one library fresh installs lack, and Wayland laptops are handled.

**It updates itself.** Every copy (Windows, Mac, Linux, or a git checkout) checks GitHub at start and every six hours,
downloads the newest version, checks its checksum, and swaps it in the next time you step away from the window.
**Help → About** says whether you're on the latest. You never have to think about it.

## Your first ten minutes

1. Start SimpleBrain: an ordinary window you open from its icon. A five-minute tutorial walks you through each part, and you do one real thing at each step; the **How to**
   button at the top runs it again any time.
2. In the bar at the top type `t call mom fri` and press Enter. That's a task, due Friday.
3. Type `c tomorrow 2pm coffee with Dad` and press Enter. That's on the calendar.
4. Type any thought and press Enter. It waits in the Inbox until you decide (one click: Task, Event or Note).
5. **File → Today.** Your three things, with their files one click away. At the bottom: *Learn one thing*, the next
   step worth learning. It moves on by itself when you've done it. Ten steps and you know the whole program.

## Become an expert

### Everything SimpleBrain understands (the cheat sheet)

Type these in the top bar or on their own line in any note. Dates work the way you say them: `today`, `tomorrow`,
`fri`, `next mon`, `in 3 days`, `nov 5`, `11-5`, or `11-05-2026`.

| You write | What happens |
|---|---|
| `t call the bank fri` | A task due Friday (in the top bar: at once; in a note: it stays there and shows in Tasks) |
| `t Python module every:day` (or `every:weekday`, `every:week`, `every:month`, `every:mon` …) | A habit: tick it and it's done for today, back on its next day |
| `t pay rent due:dec 1` / `due:fri` | In a note, the date is written out when it saves (`due:2026-12-01`) |
| `c fri 2pm dentist` | An event on the calendar (time optional) |
| `i maybe learn piano` | To the Inbox, to decide later |
| `[[Note name]]` | A link. Type two brackets and a few letters and pick from the list |
| `#tag` | A tag; filter by it in Dataview (a tag inside `code` or a code block doesn't count) |
| `status:: active` (or `[rating:: 4]` mid-sentence, or YAML at the top) | A field: Dataview shows it as a column by itself and queries can use it |
| a ```` ```dataview ```` block with `TABLE status, due FROM #project WHERE status != "done" SORT due` | Its live result under the note (TABLE, LIST or TASK; tasks can be ticked there) |
| `file:: ~/Videos/session-01.mp4` | A link to a file that opens beside the note (video windowed in mpv, resumes) |
| `course:: ~/Videos/Guitar` | A course: Today and the note show the **next** session, in order |
| `after:: [[Base course]]` | This course waits until that one is done |
| `answer:: …` (under a numbered question) | Collected into "<name> - Answers" notes for every note it links |
| `every:: 2 weeks`, `birthday:: 03-14`, `#person` | A person: Today says when to check in; a dated line (`11-02-2026 called`) counts |
| `cash:: 250`, `+ 280 pay every friday`, `- 21 phone monthly 11`, `goal:: 345 exam 12-19-2026` | Lines of the **Budget** note |

Settings are lines in **Home** or in a note called **Settings** (delete a line to turn it off):

| Line | Effect |
|---|---|
| `limit:: 3h` or `limit:: until 9pm` | Computer time left shows at the top; 10 minutes before the end it asks where you stopped, and tomorrow's Today opens with that line |
| `focus:: youtube python, edube` | Window titles with these words are never counted as drift |
| `drift:: chess.com` | …and these always are |
| `plan:: ~/Desktop/Projects/plan.xlsx` | Today reads that workbook's dated actions (a sheet with Date, Action, Status) and its `cards/` folder |
| `para:: ~/Desktop` | Where your Projects / Areas / Resources / Archives folders are (found by itself otherwise) |
| `watch:: ~/Videos/ready` | Today lists what's new in that folder |
| `mail:: riverside.example, bank.example` | Senders that always make the email digest |
| `app:: Fastmail https://app.fastmail.com` | That account as an app (also in a note called **Apps**) |
| `file downloads:: off` | Stop filing old Downloads |

### Today: what to do now
Three things, never more: overdue and timed ones first, from your notes and your plan workbook (the same action in
both shows once). Each comes with its files, links and call card. Above them: the line you left yesterday, yesterday's
score and your money. Below: courses' next sessions, new files in watched folders, mail that needs you, one person to
reach (and a good time), your longest free stretch, today's calendar, what you usually open around now, and *Learn one
thing*. When more than three are due, **Spread out** (Tasks panel) moves the rest to the lightest days of the week,
never onto a shift.

### The watcher: on track without keeping track
Once a minute SimpleBrain reads the active window's title, on this computer only. It never sends it anywhere, and the
log lives in the settings folder, never your notes. What it does with that:
- 10 minutes of drift (email, video sites, social, shuffling files) → one card: **Back to it** (Today's first thing
  opens beside your notes) or **Taking a break** (quiet for 15 minutes). Quiet during calendar events with *shift* or
  *work* in the title.
- 90 minutes at the screen without five minutes away → one card to stand up.
- Don't want the cards? Put `nudges:: off` on a line in Home. Time left and the day's three still show.
- Back after 15 minutes away → Today's first thing is already open.
- The top bar shows how many of today's three you've ticked done and, with a `limit::` line, the time left. Time in
  front of a window is never counted as work (anyone can sit in front of a window); the score is what you ticked.
- An hour after an event that links a person (`c fri 2pm coffee with [[Dad]]`) → *How did it go?* One line goes into
  their note, dated.

### Notes and links, like a pro
Under the editor: **Links**, **Linked from** (hover a name to see the line that links here), **Files**, **Mentioned
in** (notes that name this one without a link; **＋link** or **Link all**) and **Related** (notes about the same things
that aren't linked yet, with the words they share). The **Graph** shows the open note and its neighbours; **Show all
notes** for the whole map; right-click a dot for an icon or picture. **Dataview** lists every note; filter by `#tag`;
the fields your notes use become columns by themselves; type a query in its box the way Obsidian's Dataview writes them
(`TABLE`, `LIST`, `TASK`, `FROM #tag / [[Note]] / outgoing([[Note]])`, `WHERE`, `SORT`, `GROUP BY`, `FLATTEN`, `LIMIT`,
`date(today)`, `dur(2 days)`, `contains()`, `length()` and the other common functions; `file.name`, `file.tags`,
`file.inlinks`, `file.mtime`, `file.day` …).
The pencil next to a note renames it and fixes every link; **File → Broken links** finds typos.

### Drop it and it's filed (PARA)
Drag files or folders onto the window: each goes into the Projects or Areas folder whose name it matches
(`walker-supply-lease.pdf` → `Projects/walker-supply`), otherwise into `Resources/<kind>`, and the note of that name gets a
`file::` line. Drop onto the open note to file it with that note. A card says where everything went, with **Undo**.
The **⇣ Drop** button opens a Drop folder that works the same. Downloads untouched for two days are filed once a day
(only if the PARA folders were yours to begin with). Nothing is ever overwritten or deleted. A dropped `.md` file
becomes a note; a bank export (`.csv`/`.xlsx` with a Balance column) updates your cash.

### Money, forward
The **Money** button (it shows what you end with, on a ring) opens a projection of your Budget note, day by day to
`until::`: a ring that fills as far as the money lasts, the road ahead with its lowest point, and goals as diamonds that
light up amber when the money is there that day (and say how much more when it isn't). Click a goal to leave it out and
watch what changes. Each time you open it, it tells you what moved since you last looked.

### Accounts as apps, email without checking email
`app::` lines make sites into apps: found from the top bar, opened in their own window with one SimpleBrain sign-in
that stays signed in (Chromium, Chrome, Brave or Edge; otherwise a new window of your browser), and in the Linux app
menu.

**File → Email (connect yours)** works with any email service. Type your address; SimpleBrain knows Gmail, iCloud,
Yahoo, AOL, Fastmail, Zoho and GMX and shows that service's steps to make an app password, with a button that opens the
page. For anything else it looks up the server settings and fills them in. It tries the connection before saving. Then
at 9am and 4pm one card lists the few unread messages from people (not newsletters or robots), and **Mail** reads,
replies, archives and deletes inside SimpleBrain. Outlook.com/Hotmail and Proton need their own sign-in or Bridge app;
the steps say how to get around that.

### Your notes on your website
**File → Website (connect yours)**: pick **WordPress** (an application password), **Shopify** (a Dev Dashboard
app), or **Any other website** (plain web pages written into a folder you upload or that syncs to Netlify, GitHub
Pages, Neocities or your host). Each has numbered steps and a button to the right page, and it's tried before it's
saved. Then tick *Show this note on my website* on a note: it's published, kept up to date on every save, and taken
down when you untick it, with a list of your published notes made for you.

### Keyboard
Enter (top bar) opens the highlighted result or captures the line · ↑↓ move through results · Esc closes them ·
Ctrl+S save · Ctrl+N new learning note · Ctrl+T (in a note) writes where the video is.

### What leaves your computer, and when
Nothing, unless you turn it on: book recommendations send keywords to openlibrary.org (asked first); sync goes
device-to-device (encrypted, via iroh relays when needed); the calendar feed and CalDAV go to your calendar; the
website sends ticked notes to the site you connected; mail goes to and from the email service you connected; updates come from GitHub. The
watcher's log, habits, and tokens stay in the settings folder on this computer.

### When something's off
- *It says an update wasn't installed*: it tries again in six hours; Help → About shows why.
- *Something went wrong*: your notes were saved first; details are in `crash.log` in the settings folder
  (`~/.config/SimpleBrain`, `%APPDATA%\SimpleBrain`, or `~/Library/Application Support/SimpleBrain`).
- *A file opens but not beside the note*: install `wmctrl` (Linux; SimpleBrain offers to).
- *The drift card never comes on Linux*: `xprop` (package `x11-utils`) is needed to read window titles.
- *Mac: "can't be opened"*: right-click → Open the first time (it's not notarized yet).

## Today and your notes

SimpleBrain is a program you click to open, not your desktop or something running in the background.

- **It opens on Today**, a note it writes for you: your three things for the day, never more (overdue and timed ones
  first), each with its files, videos, links and call card one click away, and the first one already open beside it.
  Under them: which of your favorite problems each thing moves forward, the one person you're overdue to reach and
  birthdays this week, your longest free stretch, today's calendar, and what you usually open around this time.
- **Type in the top bar to find anything**: notes, files on any drive, apps, windows already open (brought up, not
  opened twice). Enter opens it; the last row captures the line to the Inbox instead.
- **Click a link in a note** to open it: a file or video in its own window beside the note, a web link in a new
  browser window. Ctrl+T writes where the video is.

Things it reads, all plain text in your notes:

| Write this | Where | What happens |
|---|---|---|
| `plan:: ~/Desktop/Projects/plan.xlsx` | Home | Today shows that workbook's actions due today (a sheet with Date, Action and Status columns). A `cards/` folder beside it supplies call scripts by matching words. Without the line, a workbook with "plan" in its name on your Desktop or in Documents is used. |
| `1. How can I …?` | a note titled *12 Favorite Problems* (or anything with "questions") | Today says which question each thing moves forward, or gives you one to keep in mind. |
| `every:: 2 weeks` and `birthday:: 03-14` | a person's note | Today names whoever you're most overdue to reach. Write a line with the date when you talk (`11-02-2026 called about the bond`). |
| `file:: ~/Videos/session-01.mp4` | any note | A link that opens the file beside the note. |

What you open is remembered on this computer only, never synced.

**Updates install themselves.** From a git checkout (`./dev.sh`) SimpleBrain pulls new versions from GitHub on its
own (never over edits you made to the code) and restarts when you step away; the installed Linux build takes each new
release. Every version that reaches `main` is published as a release.

**Windows and macOS:** Today, the search bar, clickable links, people, habits and Glass work the same; **File › Today** opens it any
time on any system.

## Using it

- **Capture:** type anything in the bar at the top and press Enter. It lands in
  the Inbox, where one click files it as a **Task**, **Event** or **Note**
  (a Note becomes its own note file, titled with the start of the thought).
- **Notes:** link notes by writing `[[Note Name]]`. Clicking a link opens (or
  creates) that note. The graph shows the open note (ringed) and what it is
  connected to: notes it links to or that link to it, and notes sharing a link
  with those. Home, Learning and Recommendations are shown but never bridged
  through. Click a dot to move there; tick **Show all notes** for the full map.
- **Files:** click **Link file…** under the editor and pick a file anywhere on
  the computer (a PDF, a recording…). The note gets a `file:: path` line and a
  button under the editor that opens it. The file isn't copied or moved; it's never
  published to your website; on another device it shows "(not found)" unless the file is there too.
- **Rename and broken links:** the pencil next to a note in the list renames it and
  rewrites every `[[link]]` to it, in other notes, the Inbox and the Calendar. **File → Broken links…**
  lists links to notes that don't exist (a typo shows up there); double-click one to open a note that uses it.
- **Tutorial:** the first launch walks through the window one part at a time, and you do each step for real
  (a task, an event, a note, a book note). **Help → Take the tour** runs it again.
- **Tasks:** any line like `t call the bank due:10-01-2026` in any note
  shows up under Overdue / Today / Upcoming / No date. Ticking it makes it
  `- [x] …`; old `- [ ] …` lines are converted to `t …` automatically.
- **Shorthand** (any note, on save): a line starting `i ` moves to the Inbox,
  `c 10-05-2026 2pm dentist` moves to the Calendar (time optional).
  Lowercase only, so `I think…` is left alone.
- **Calendar:** add local events, or show an outside calendar read-only next to
  them: click **Choose file…** and pick an `.ics` file or a `.csv` (a header row
  with a Date and a Title column, optionally Time; Google/Outlook exports work),
  or click **Link…** and paste an iCal (.ics) link. One source at a time; it
  re-reads on **Sync**. Times from other time zones are shown on your computer's clock; skipped
  dates in repeating events, single edited occurrences and cancelled events are honoured. To go both ways, paste the CalDAV calendar address as your
  calendar shows it (for Fastmail, `https://caldav.fastmail.com/dav/calendars/user/you@…/id/`),
  then the app password when asked; the user name is read from the address. Servers that
  don't put it there take `https://user:app-password@host/path/`. Your own events are then sent to that calendar
  (edits and deletes too) and the calendar's other events are shown read-only. Only
  events made in SimpleBrain are written; events made elsewhere are never changed.
- **Notes folder:** the **Change notes folder…** button at the top is always
  visible. Pick any folder, a USB drive included: everything (notes, inbox,
  calendar settings, recommendations) lives inside it and moves with it. A
  folder with no notes yet can be filled with a copy of your current notes; the
  originals are never touched.
- **Sync between devices:** the **Sync…** button at the top shows a pairing code
  (and the same code as a QR picture) that is always there. On your other device, open **Sync…** and enter it under
  *Add a device*. No account, no server to run. From then on both devices keep
  their notes the same by themselves: typing is saved a moment after you stop,
  and sent to the other device when it's open. A device that is off catches up
  when it's back; nothing is lost in the meantime. If the same note was changed on both,
  neither version is lost: one stays under the note's name and the other is kept beside
  it as `Note (conflict …)`, the same on both devices. The Inbox and Calendar lists are merged line by line.
  Devices find each other by key through [iroh](https://www.iroh.computer); when
  they can't connect directly, iroh's public relay servers pass along encrypted
  traffic, so they never see your notes. Anyone who has your code can join your
  notes, so keep it to yourself; **New code** replaces it. The calendar link in
  `.config`, generated notes (Recommendations, Answers) and the trash are never sent.
- **Studying a book:** **+ New Learning Note** makes a page that takes you through a book in three short sittings.
  *First look* (20 minutes): your purpose, a one-sentence guess at what the book says, the words that keep coming up,
  and 3 to 5 questions. Then stop and sleep on it. *Find the answers* (the next day, 25 minutes): one question at a
  time with a timer, and each answer typed in your own words with the book closed, then checked. *Say it back* (two
  days later, 20 minutes): two minutes out loud from memory, fix what was wrong, and one thing you'll do with a date.
  Then two five-minute checks from memory, a week and a month on. Only the next sitting is a task; ticking it writes
  the one after on its day.
- **Book recommendations:** a note made with **+ New Learning Note** is a book;
  put its keywords under *Trigger Words or Phrases* in double square brackets.
  SimpleBrain suggests books in a `Recommendations` note, rebuilt in the
  background at startup, and gets better with every book you add. It asks once
  before using the network; it sends only your keywords, one at a time, to
  openlibrary.org, never your notes or titles. Switch it off any time in
  File → Book recommendations.
- **Look:** one look, Glass: warm dark with one gold accent. There's nothing to set and nothing that can switch it.
- **Dataview:** every note in a table, filterable by `#tag` or title. The
  matching notes light up orange in the graph.
- **Answers:** under a numbered question, write `answer:: your answer`. Each
  `[[Keyword]]` you link gets a `Keyword - Answers` note listing every note
  that links to it, then all their answers. It rebuilds on save; don't edit it.

Your notes live in `Documents/SimpleBrain` unless you change it (File → Open
vault folder shows it). Deleted notes go to `.trash` inside it, never straight
to oblivion.

**Settings** (in `.config` in your notes folder):

| Line | Effect |
|---|---|
| `ICS_URL=https://…` | Show a calendar feed (treat the URL like a password) |
| `CALENDAR_FILE=path` | Show a calendar file (`.ics` or `.csv`); relative to the notes folder when it can be |

Which notes folder to use is decided, in order, by the `SIMPLEBRAIN_VAULT`
environment variable, then the folder saved by the **Change notes folder…**
button, then `Documents/SimpleBrain`. The saved choice lives in
`simplebrain-settings.json` beside the program (or one folder above it) when
that file exists, otherwise in your user settings folder.

## Portable (USB drive)

Format the drive exFAT, then on each system build once and assemble:

```
pyinstaller packaging/simplebrain.spec
python packaging/portable/make_portable.py /path/to/drive
```

The drive ends up holding `Windows/`, `Mac/` and `Linux/` programs plus one
shared `Vault/` and `simplebrain-settings.json` (`{"vault": "Vault"}`, relative,
so it works whatever letter or mount point the drive gets). Run the program
from the drive on any of the three and your notes are right there. The GitHub
workflow `build.yml` runs those steps on Windows, macOS and Linux and uploads
each result. Unsigned builds make Windows SmartScreen and macOS Gatekeeper warn
the first time; that is expected.

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

`python tools/supervise.py` runs every module's selftest and the app test, then checks
[CHECKLIST.md](CHECKLIST.md): it prints `supervise OK` only when everything passes and nothing on the checklist has
gone missing. The sync test runs a two-device sync over localhost, no internet needed.
`QT_QPA_PLATFORM=offscreen python tests/stress.py` times every action on a 3,000-note vault and feeds it odd files. `install.sh` puts the app
in `~/.local/share/simplebrain/app`, adds it to your app menu and adds a
`simplebrain` command. Run it again after a rebuild to update. The installed build also updates itself from the newest
GitHub release. To run from
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
- `simplebrain_recommend.py`: book recommendations from your notes (Open Library). No UI.
- `simplebrain_sync.py`: device-to-device sync (iroh), pairing codes, conflict rules. No UI.
- `simplebrain_today.py`: the Today note: three things, plan workbook, people, favorite problems, free time. No UI.
- `simplebrain_find.py`: find anything from the top bar (notes, files, apps, open windows). No UI.
- `simplebrain_habits.py`: what you open and when, kept on this computer, to rank search and Today. No UI.
- `simplebrain_desk.py`: the Linux desktop side: open a file beside its note, the list of open windows, video time. No UI.
- `simplebrain_glass.py`: the Glass theme and clickable links in the editor (Qt).
- `simplebrain_money.py`: the money view (Qt).
- `simplebrain_watch.py`: the watcher: drift, time left, breaks, the day's three, the score. No UI.
- `simplebrain_drop.py`: drop it and it's filed (PARA). No UI.
- `simplebrain_budget.py`: the Budget note projected forward. No UI.
- `simplebrain_links.py`: backlinks in context, unlinked mentions, related notes, [[ completion. No UI.
- `simplebrain_day.py`: overloaded days spread out, check-in follow-ups and suggestions. No UI.
- `simplebrain_mail.py`: email over IMAP/SMTP (any service) or Fastmail's JMAP: the digest and the mailbox. No UI.
- `simplebrain_publish.py`: ticked notes as pages on WordPress, Shopify or a folder of HTML. No UI.
- `simplebrain_setup.py`: the step-by-step windows that connect your email and your website (Qt).
- `simplebrain_update.py`: updates on every system, one-time clean-ups. No UI.
- `tools/supervise.py`: runs every test and checks CHECKLIST.md.
- `simplebrain_app.py`: the desktop app (Qt).
- `packaging/`: icon, PyInstaller spec, Linux AppImage/install scripts, Windows installer,
  portable-drive assembler.

## License

MIT, see [LICENSE](LICENSE).
