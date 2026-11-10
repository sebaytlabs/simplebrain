# SimpleBrain

## What this is
A notes app that doesn't make you configure it: plain Markdown, `[[links]]` + graph,
one-letter tasks/inbox/calendar. PySide6 desktop app for Linux, one user.

## Layout
- `simplebrain_core.py`: vault logic (notes, tasks, inbox, calendar, graph layout). Runs its own selftest.
- `simplebrain_ics.py`: calendar-feed parsing (time zones, repeats, skipped dates). Runs its own selftest.
- `simplebrain_sync.py`: device sync over iroh (pairing code, conflict rules, `SyncService`). Runs its own selftest, including a two-device sync on localhost.
- `simplebrain_publish.py`: publishes notes ticked "Show this note on my website" to the user's own site: `WordPressSite` (REST + application password), `ShopifySite` (Admin GraphQL), `FolderSite` (HTML files for any host). Runs its own selftest with fakes. Setup lives in `~/.config/SimpleBrain/website.json` (an older `shopify.json` still counts), never in the vault.
- `simplebrain_today.py`: the generated Today note (three things from tasks + the `plan::` workbook, their files and call cards, favorite problems, people, free stretch, calendar, habits). Not synced (its MARK). Runs its own selftest.
- `simplebrain_find.py`: the top bar's search (notes, open windows, apps, a cached file list of home + mounted drives). Runs its own selftest.
- `simplebrain_habits.py`: local log of what's opened through SimpleBrain, in the settings folder (never the vault). Runs its own selftest.
- `simplebrain_update.py`: self-updates (git fast-forward of a checkout, or the newest release for the installed build). Runs its own selftest, including a real git update in temp repos. Tests set `SIMPLEBRAIN_NO_UPDATE`.
- `simplebrain_glass.py`: the Glass theme (warm dark background of its own, never the wallpaper; gold accent: never neon/cyan; no clock, the panel has one) and clickable links in the editor.
- `simplebrain_money.py`: the money view (`MoneyView`, `MoneyWindow`), in Glass's warm gold.
- One look: Glass. The user asked for a single theme: no Theme box, no other themes, nothing that switches it.
- `simplebrain_watch.py`: the watcher (active window title + idle time once a minute, off the UI thread): drift nudge, breaks, welcome back, `limit::` time left and the parked line, the day's three, the score. Day log in the settings folder, never the vault. Runs its own selftest.
- `simplebrain_drop.py`: drop it and it's filed into PARA folders (`para::`), linked from notes, logged for Undo; never overwrites or deletes. Runs its own selftest.
- `simplebrain_budget.py`: the Budget note (cash, +/- lines with repeats, goals) projected forward; goals are paid only when they fit. Runs its own selftest.
- `simplebrain_links.py`: backlinks in context, unlinked mentions, related notes (tf-idf, cached by mtime), `[[` completion. Runs its own selftest.
- `simplebrain_day.py`: overload and Spread out, check-in follow-ups, suggested check-ins. Runs its own selftest.
- `simplebrain_mail.py`: any email service over IMAP/SMTP (`ImapAccount`, `imap_fetch`, `PROVIDERS` with each service's app-password steps, `guess_servers` via Thunderbird's provider list) and Fastmail over JMAP (`Account`, `fetch`); same interface, picked by `open_account`/`fetch_any`. Setup in the settings folder (0600). Runs its own selftest against fake JMAP, IMAP and SMTP servers.
- `simplebrain_setup.py`: `EmailSetup` and `WebsiteSetup`, the step-by-step connect windows (Qt); tried before saving.
- `simplebrain_mailwin.py`: the Mail window (Qt): inbox, the email, Reply/Forward/New, Archive/Delete/Unread, task or event from an email. Network off the UI thread.
- `simplebrain_calendar.py`: the whole calendar over CalDAV (events with place/notes in a range, create, edit, delete, skip one date of a series). Runs its own selftest against a fake CalDAV server.
- `simplebrain_calwin.py`: the Calendar window (Qt): month, the picked day and the week after, add/edit/delete.
- `tools/supervise.py`: runs every selftest and the app test and checks `CHECKLIST.md`'s proofs. `tests/stress.py`: timings on a 3,000-note vault and odd input.
- `simplebrain_desk.py`: the X11/Xfce side: open a file beside its note (mpv, xdg-open, browser --new-window, wmctrl), mpv's time over its IPC socket. Runs its own selftest.
- `simplebrain_app.py`: the Qt window (`GraphView`, `SimpleBrain`). The layout is the user's: add hooks, never rearrange panels. One running copy: `--toggle` and a plain start are handed to it over a local socket; `--desktop` makes the window the desktop layer.
- `tests/test_app.py`: headless end-to-end check in a throwaway vault.
- `packaging/`: PyInstaller spec, AppImage and install scripts.
- `dev.sh`: runs the app and restarts it whenever a `.py` file changes.
- `backup-vault.sh`: one-way backup of the vault to the Backup drive, keeping old versions.

## Commands
- Run with live restart: `./dev.sh`
- Test everything: `python tools/supervise.py` (expect `supervise OK`); speed: `QT_QPA_PLATFORM=offscreen python tests/stress.py`.
- Test one module: `python simplebrain_core.py`, `python simplebrain_ics.py`, `python simplebrain_sync.py`, `python simplebrain_publish.py`, `python simplebrain_desk.py`, `python simplebrain_today.py`, `python simplebrain_find.py`, `python simplebrain_habits.py`, `python simplebrain_update.py`, then `QT_QPA_PLATFORM=offscreen python tests/test_app.py`
  (expect `selftest OK`, `ics selftest OK`, `sync selftest OK`, `desk selftest OK`, `today selftest OK`, `find selftest OK`, `habits selftest OK`, `update selftest OK` and `app test OK`; use `.venv/bin/python`).
- Sync never touches the live vault in tests: they use temp vaults and a temp device-key folder.
- Build: `pyinstaller packaging/simplebrain.spec`, then `packaging/linux/build-appimage.sh`.

## Conventions
- Notes are written with `core.write_atomic` (side file, then swap in): never open a note `"w"` directly.
- The guided tour is `Tour` in `simplebrain_app.py`, a tutorial: each step says what a part is for and has a "Try it" line. Add a step in `SimpleBrain.tour_steps` when a feature needs pointing out, and bump `TOUR_VERSION` so updated copies see it once.
- Match the surrounding code: terse comments that say why, no new dependency for a few lines.
- New logic gets an assert in the selftest or in `tests/test_app.py`.
- Fewer steps than doing it by hand, or it doesn't ship. No game words (missions, XP, ranks), no imports that flood tasks or the calendar, never more than 3 things to do on screen.
- Nothing personal in code: paths come from notes (`plan::`, `file::`) or are searched for. It's meant to be open-sourced.
- Qt stays below 6.10 (constraints.txt): 6.10+ won't start on pre-SSE4.2 processors, and old computers must work.
- Releases: bump `VERSION` in simplebrain_core.py; a push to main with a new VERSION publishes the release that installed copies update to.
- Power: no short polling timers; the file list is built on the first search and refreshed at most daily. The watcher's
  one-minute tick (a title read off the UI thread) is the exception; the Drop folder is watched by the system, not polled.
- Lists that can hold thousands of rows use plain items plus `RowButtons`, never a widget per row (that froze the window).
- Settings lines are read through `core.settings_text` (Home + a Settings note), never Home alone.
- A new feature gets a line in `CHECKLIST.md` with a `proof:` and, if it needs pointing out, a *Learn one thing* step
  (`simplebrain_today.LEARN`) or a tour step.

## Don't touch
- `~/Documents/SimpleBrain` is the live vault. Tests use a temp vault (`SIMPLEBRAIN_VAULT`).
- The vault's `.config` holds the calendar feed link, which is a secret: don't read or print it.

## Notes
- The GitHub repo is private; the README install link points to the Sebayt Labs store product page.
