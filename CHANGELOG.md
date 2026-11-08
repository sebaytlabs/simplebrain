# Changelog

## 0.5.4
- The examples and tests use made-up names, places and amounts.

## 0.5.3
- **Connect your own email and your own website**, step by step. **File → Email (connect yours)** works with any email
  service: type your address and SimpleBrain shows that service's steps for an app password (Gmail, iCloud, Yahoo, AOL,
  Fastmail, Zoho, GMX), with a button that opens the page, or fills in the server settings for any other provider.
  **File → Website (connect yours)** publishes to WordPress, Shopify, or any other site (web pages in a folder you
  upload or sync). Both try the connection before saving. A Fastmail token or Shopify store set up before keeps working.
- Saving a note on Windows waits out a file another program is reading for a moment, instead of failing.
- SimpleBrain is an ordinary program you click to open. **File → Make SimpleBrain my desktop** and **Stop being my
  desktop** are gone, and the first start no longer asks to make it your desktop. If it was set up before, remove
  `~/.config/autostart/simplebrain.desktop` to stop it starting at login.

## 0.5.2
- **File → Unlock KeePassXC when I log in** is gone (passwords are in Bitwarden now). If it was ever set up,
  remove `~/.config/autostart/simplebrain-keepassxc.desktop` to stop it.
- A one-word date in `c fri …` is counted from the right day (a test failed once the week moved on).

## 0.5.1
- Turning the plan workbook off (`plan:: off`) or moving it no longer counts its actions as done: no false
  "All three done". Today's three are picked again from what's left.
- No more counts on the way: the "All three done" card and a ticked task don't show "x of 3".

## 0.5.0
- **A real tutorial is the way in.** The first time SimpleBrain opens (and once after this update) a 16-step tutorial
  walks through every part, and at each step you do the thing for real: put a thought in the Inbox, file it as a task,
  write a task and an event in one line, tick a task, open a note, make a book note and mark it personal or public
  library, link two notes, use the links under a note and the graph. Only the ringed part
  can be clicked, and Next opens once you've done the step. It can't be skipped, closed or minimized until the end.
  The How to button replays it any time, and a replay can be skipped.
- The Focus button (and F11) is gone: one less button in the top bar. (The `focus::` words for the drift nudge stay.)

## 0.4.8
- The "0/3 done" count is gone from the top bar: it wasn't clear what it meant. The top bar shows only your computer
  time left when Home has a `limit::` line. The tour, Home and the first steps no longer mention the count.

## 0.4.7
- **Personal or public library.** A book note (a Learning Note, or any note linked to [[Learning]]) has a tick under
  its title: "From my personal library". Ticked, the note gets `library:: personal`; unticked, `library:: public`.
  It's a plain line in the note, so it syncs, and a dataview can list your own books with `WHERE library = "personal"`.

## 0.4.6
- Every pop-up card in the corner (nudges, welcome back, mail, filed) has an × to close it right away, instead of
  waiting for it to go away by itself.

## 0.4.5
- When Fastmail or the calendar refuses something (offline, a password changed), the Mail and Calendar windows now
  say why in their status line. Before, the message was lost and nothing seemed to happen. The same fix for "Couldn't
  file that" when a dropped file can't be moved.
- Tidying: unused code removed, one shared helper for the two new windows.

## 0.4.4
- **Mail inside SimpleBrain.** The Mail button (and the "Mail that needs you" card) opens your inbox in a SimpleBrain
  window: read the whole email, Reply, Reply all, Forward, New email, Archive, Delete (to Trash), Mark unread, and turn
  an email into a task or an event (the email is kept as a note the task or event links to). No browser, no sign-in.
  Replies come from the address the email was sent to. Needs a Fastmail token with Email and Email submission access.
- **The whole calendar inside SimpleBrain.** The Calendar button opens a month to pick any day and the week after it.
  Add, edit (title, date, all day or start to end, place, notes) and delete any event, the ones made in Fastmail or on
  a phone too. A repeating event can skip one date or be deleted whole. Editing a Calendar.md event here moves it to
  the real calendar with its place and notes.

## 0.4.3
- **Mail works with a real Fastmail account.** The digest asked Fastmail for the List-Unsubscribe header as text, a
  form Fastmail refuses, so every check failed and no mail card ever showed. It asks for the form Fastmail allows now.
- The app test no longer reads the real desktop: an open Fastmail window on the computer made it fail.

## 0.4.2
- **One look, Glass.** The Theme box (System, Light, Dark, Glass, Holo) and the blue Holo theme are gone, so nothing can
  switch the look. It had been changing "by itself": rolling the mouse wheel to scroll the window while the pointer passed
  over the Theme box stepped through the themes and saved each one. Other drop-downs (the Dataview tag filter) ignore the
  wheel too now.
- **Fixed a crash on the desktop**: bringing SimpleBrain forward (Super+J, opening it again), picking an open window in
  the search bar, or opening an app or account that's already open called a function lost in an old revert. It's back,
  and a test now checks that everything the window calls exists.
- Tests no longer read the real computer: the Today selftest picked up a real plan workbook from the Desktop and failed
  on a real machine; the app test expected videos to open outside, which mpv on X11 now does inside.

## 0.4.1
- **Glass is the look again.** 0.4.0 switched everyone to the blue Holo theme; it's back to Glass (Holo stays in the
  Theme box for anyone who picks it). The cards and the Money window are in Glass's warm gold too.
- **A tutorial you'll actually see.** It starts by itself the first time you open this version, walks through each part
  with one thing to try, and the new **How to** button at the top runs it again any time.
- Your Home note gets the new guide even if it still has the very first wording (that one wasn't recognized before).
- The rows under the note no longer sit in a black box.
- **Pictures and videos open inside SimpleBrain**, where the graph is, never full screen or in a window of their own
  (× goes back to the graph; Open outside if you want it). Video plays in mpv drawn inside the window, even on a
  computer without good graphics drivers; Ctrl+T still writes where it is.
- **Updates arrive within half an hour** of a change on GitHub, follow main even if your copy sat on another branch,
  and restart once you've been away from the keyboard for two minutes (as the desktop, the window is always "active").
- **No fake focus time.** The top bar and the daily score count what you ticked done, never time in front of a window.
- Today no longer pushes the old trial's Videos note: a course is only a note with a `course::` line.
- The Home guide reads in whole sentences (no line breaks in the middle).
- **Dataview like Obsidian's**: the fields you write (`status:: active`) become columns by themselves; a query in the
  box (`TABLE status FROM #project SORT due`) or in a ```dataview block in a note shows its result; tasks there tick.
- **Plan actions tick here.** Workbook actions due today are in Tasks; ticking one (or its twin task in a note) does
  both, so nothing has to be marked twice and done things stop coming back. The count at the top moves on every tick.
- **Habits**: `t Python module every:day` (or every:weekday, every:week, every:mon …) is done for today when ticked
  and back on its next day; habits are never spread out.
- Call cards and other text files open inside the viewer too.
- Found by living a simulated week with it: a task due today could be cut from Today before the plan's actions were
  weighed in; the "where did you stop?" card could be covered by a stretch reminder; pay already in a bank export's
  balance was counted twice; the line you leave showed for days; drift named the browser, not the site; a date in an
  example (in code) counted as a contact; calendar rows overlapped; Glass checkboxes were black squares.

## 0.4.0
- **Fixed: clicking two or three things froze the window.** The Tasks and notes lists built a row of widgets per item on
  every change (seconds on a big vault); they're light rows now, with the buttons on the selected row. Big vaults are
  fast throughout: tested on 3,000 notes and 6,000 tasks (`tests/stress.py`).
- **Updates install themselves on every system**: the AppImage, the Windows installer (silently), the Mac app, the
  Linux install and a git checkout, checksum-checked, restarting only when you've stepped away. Help → About says
  you're on the latest. Releases add an Intel Mac build, `SHA256SUMS` and one `SimpleBrain.zip` for the store.
- **Holo**, a new look (the default once; Glass stays in the Theme box): slate with a tactical grid, ice-blue light lines,
  orange for what you act on, amber for wins.
- **Shortest routes**: `t call the bank fri` in the top bar is a task at once, `c tomorrow 2pm dentist` an event at once.
  Dates the way you say them everywhere (`fri`, `next mon`, `nov 5`, `in 3 days`); `due:fri` in a note becomes a date.
- **The watcher**: ten minutes of drift bring one card (Back to it / Taking a break), quiet during shifts; 90 minutes
  without a break bring one card to stand up; back after 15 minutes away, Today's first thing is open; `limit:: 3h` shows
  time left and asks where you stopped, and tomorrow's Today opens with it; the day's three are counted done; a daily score.
- **Drop it and it's filed (PARA)**: files and folders dropped on the window, or in the Drop folder, go to the matching
  Projects/Areas folder or Resources by kind, linked from their note, with Undo. Old Downloads are filed once a day.
  A dropped `.md` becomes a note.
- **Money, forward**: a Budget note in plain lines, projected to a date; a ring of how far the money lasts, the road ahead,
  goals that light up when funded; click one to leave it out; what changed since you last looked.
- **Linking like a pro**: `[[` completes titles; *Mentioned in* turns plain mentions into links in a click; *Related*
  finds notes about the same things; *Linked from* shows the line that links.
- **A workday that doesn't bury you**: *Spread out* moves what's over three a day to lighter days; check-ins that follow
  up (*How did it go?* after an event with someone) and suggested check-ins.
- **Accounts as apps** (`app::` lines: own window, one sign-in that stays, in the app menu), a read-only **Fastmail
  digest** twice a day, and **KeePassXC unlocked at login** (Linux).
- **Courses in order** (`folder::`, `after::`) and **watched folders** (`watch::`).
- **Focus** (F11): Today and the note you're in, nothing else.
- **Guided**: Today ends with one thing to learn, which moves on by itself; the tour covers what's new; Home is rewritten
  around what you want done (an untouched old Home upgrades itself). Settings can live in a note called Settings.
- Runs on more machines: Linux builds carry libxcb-cursor (fresh Ubuntu/Mint), Wayland goes through XWayland, the AppImage
  adds itself to the app menu, and an unexpected error is logged and shown instead of closing anything.
- `tools/supervise.py` runs every test and checks `CHECKLIST.md`, the list of everything asked for.

## 0.3.2
- As the desktop, SimpleBrain no longer shows the wallpaper through it: Glass has a warm dark background of its own.
- No clock of its own: the panel already shows the time.
- Fast on an older computer, measured with 300 notes and 900 tasks: start 1.5 s → 0.2 s; a Tasks refresh (after
  every save or tick) 5.2 s → 0.26 s, since each group now shows the nearest 40 and says how many more; Today and
  search work in the background, so a click or a keystroke never waits on them (Enter still opens the top result);
  the Glass background is drawn 1:1 instead of rescaled on every repaint; a note with hundreds of files shows
  buttons for the first 12.
- Fixed: coming back to the window could raise an error (a missing import).

## 0.3.1
- **Updates install themselves.** Run from a git checkout (`./dev.sh`), SimpleBrain checks GitHub at start and every
  six hours, fast-forwards when nothing of yours is in the way (it never overwrites edits to the code), installs new
  requirements, and restarts the next time you step away from the window. The installed Linux build takes the newest
  release the same way, checksum-checked. No question, no click.
- Every new version on main is published as a GitHub release (Linux AppImage with its checksum, Windows installer,
  Mac disk image), which is what installed copies update from.
- Tidies up after the short-lived "missions" trial build, once and without asking: the step tasks and 7pm calendar
  events it added are taken out; the notes keep every file link (steps become headings); the originals go to the
  trash in your notes folder. Notes of your own tagged #mission are left alone.
- A `#` inside a file path or web address (`Lesson #10.mp4`) is no longer read as a tag.

## 0.3.0
- **Your desktop.** On Linux Mint, SimpleBrain asks once: *Make SimpleBrain your desktop?* One click and it comes up at
  every login as the desktop itself (under your other windows, no taskbar button), installs what it needs (mpv, wmctrl,
  x11-utils) with one password prompt, and Super+J brings it forward and sends it back. File › Stop being my desktop
  undoes all of it.
- **Today.** A note SimpleBrain writes for you: your three things (never more), overdue and timed ones first, each with
  the files, videos, links and call card that go with it, one click away; which of your *12 favorite problems* each one
  moves forward; the one person you're overdue to reach and birthdays this week; your longest free stretch; today's
  calendar; and what you usually open around this time. At login the first thing's file is already open beside it.
- **Your plan, where it is.** A `plan:: path/to/plan.xlsx` line in Home (or a workbook with "plan" in its name on your
  Desktop or in Documents) is read, never imported: its actions due today join your tasks in Today. Nothing floods
  your task list or calendar.
- **Find anything.** The top bar finds notes, files on every drive (the Backup drive too), apps, and windows already
  open, as you type. Enter opens the highlighted one; the last row still captures the line to the Inbox.
- **Links open.** Web addresses, `file::` paths and `[[notes]]` in a note open on a click: files and videos in their
  own window beside the note (video windowed in mpv, resuming where you left off), web links in a new browser window.
  Ctrl+T writes where the video is (`12:34 — `).
- **People.** A note with `every:: 2 weeks` is someone to keep in touch with; a dated line in it (or a past calendar
  event linking to it) is the last contact. Add `birthday:: 03-14` for a heads-up a week ahead.
- **It learns your day.** What you open through SimpleBrain, and when, stays on this computer (never synced, nothing
  watched on screen) and ranks search and Today.
- **Glass**, a new theme: warm dark over your blurred wallpaper, one gold accent.
- **Windows and macOS too:** the first question there is *Open SimpleBrain when you log in?* (on Today, full screen);
  File › Today on every system; search covers other drives (D:, E: … on Windows, /Volumes on macOS).
- Runs on old computers: Qt is held at 6.9 (6.10 and later need a 2009-or-newer processor). Light on power: no
  polling; the file list is built on the first search and refreshed at most daily.

## 0.2.0
- Notes are saved in one step (side file, then swapped in), so a crash or a pulled USB stick can't leave half a note.
- Calendar feeds: UTC and named time zones show on your computer's clock (Windows zone names too); repeating events keep
  their wall-clock time across daylight saving; skipped dates, single edited occurrences and cancelled events are honoured.
- The Dataview search no longer re-reads unchanged notes on every keystroke.
- Rename a note with the pencil next to it in the list; every link to it (notes, Inbox, Calendar) follows.
- File → Broken links… lists links to notes that don't exist yet.
- A guided tour on first launch (Help → Take the tour to run it again).
- New Home note explaining all of this. A Home note you never edited is replaced by it on the next sync.
- The Shopify settings file is created private from the start.
- Calendar parsing moved to its own file, `simplebrain_ics.py`.
