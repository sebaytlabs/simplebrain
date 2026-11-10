# Checklist

Everything SimpleBrain was asked to do, and where it's done. `python tools/supervise.py` runs every test and checks that
each `proof:` below still exists in the code (file :: text it must contain). A line marked **(yours)** is something only
you can do outside the program; it's listed so nothing is forgotten.

## The 21 requests (11-01-2026)
- [x] 1. Review the codebase. proof: CHANGELOG.md :: ## 0.4.0
- [x] 2. Read the notes given (60-day plan, open items, Jarvis plan) and use them. proof: simplebrain_today.py :: def next_sessions
- [x] 3. A watcher/supervisor that confirms tasks get done. proof: simplebrain_watch.py :: def done_of_three
- [x] 3b. A supervisor that confirms this checklist is done. proof: tools/supervise.py :: def check_proofs
- [x] 4. A folder drop location. proof: simplebrain_drop.py :: def drop_dir
- [x] 5. Runs on a new laptop and on a 5-year-old one. proof: packaging/simplebrain.spec :: libxcb-cursor
- [x] 5b. Old processors (Qt below 6.10). proof: requirements.txt :: PySide6-Essentials>=6.8,<6.10
- [x] 5c. Intel Macs as well as Apple Silicon. proof: .github/workflows/build.yml :: macos-15-intel
- [x] 5d. Wayland laptops. proof: simplebrain_app.py :: XDG_SESSION_TYPE
- [x] 6. A better color scheme: one look, Glass (the blue Holo was tried and dropped; you asked for one theme). proof: simplebrain_app.py :: One look: Glass
- [x] 7. Jarvis / KOTOR / Battlefield as the design inspiration: tried as Holo, replaced by Glass at your request. proof: CHANGELOG.md :: One look, Glass
- [x] 8. Every task, none skipped: this list. proof: CHECKLIST.md :: ## The 21 requests
- [x] 9. Updates itself from GitHub, on every system. proof: simplebrain_update.py :: def stage_update
- [x] 9b. You can see you're on the latest version. proof: simplebrain_app.py :: Updates: {html.escape
- [x] 10. Seamless for ADHD and a time limit: three things, time left, line for tomorrow. proof: simplebrain_watch.py :: def limit_seconds
- [x] 10b. Fewer steps: tasks and events straight from the top bar. proof: simplebrain_core.py :: def add_task
- [x] 10c. Dates the way you say them. proof: simplebrain_core.py :: def natural_date
- [x] 11. Barely on the internet: accounts as apps, signed in once. proof: simplebrain_desk.py :: def webapp_command
- [x] 11b. Email without checking email. proof: simplebrain_mail.py :: def needs_you
- [x] 12. Not only the easy parts (updater on 3 systems, watcher, PARA filing, money projection). proof: simplebrain_budget.py :: def project
- [x] 13. Hard tasks first: the freeze, then updates, then the watcher. proof: tests/test_app.py :: Tasks panel rebuild is too slow
- [x] 14. Reviewed for completeness: this file, checked by the supervisor. proof: tools/supervise.py :: CHECKLIST.md
- [x] 15. Plan the future and see the budget in a way that's exciting, not a bar. proof: simplebrain_money.py :: class MoneyView
- [x] 16. A reason to use it, built on PARA. proof: simplebrain_drop.py :: PARA = ("Projects", "Areas", "Resources", "Archives")
- [x] 16b. Something to feel good about: done count, all-three-done, funded goals. proof: simplebrain_app.py :: All three done.
- [x] 17. Less to fuss with: the Focus button went at your request, one less thing in the top bar. proof: CHANGELOG.md :: The Focus button (and F11) is gone
- [x] 18. Windows, Mac and Linux: easy download. proof: .github/workflows/build.yml :: SimpleBrain.zip
- [x] 19. A README that makes anyone an expert in hours. proof: README.md :: ## Become an expert
- [x] 20. Stupid simple: guided, one thing to learn at a time. proof: simplebrain_today.py :: def next_step
- [x] 21. The base stays: Glass, Inbox, Dataview, Answers, Sync, Website and the tour all kept (the theme choice went, at your request). proof: simplebrain_app.py :: def build_inbox

## Later requests
- [x] Clicking two or three items froze it. proof: simplebrain_app.py :: def task_row_buttons
- [x] Better than Obsidian, Roam, Notion at notes and backlinks. proof: simplebrain_links.py :: def unlinked_mentions
- [x] Looks like AI, is skill: related notes by shared ideas. proof: simplebrain_links.py :: def related
- [x] Calendar and workday without overwhelm or burnout. proof: simplebrain_day.py :: def spread_out
- [x] Breaks before burnout. proof: simplebrain_watch.py :: STRETCH_S
- [x] Check-ins you schedule, and suggested check-ins / contact updates. proof: simplebrain_day.py :: def follow_ups
- [x] Suggested check-ins. proof: simplebrain_day.py :: def suggest_people
- [x] The most effective route for every old feature; Home rewritten as a guide. proof: simplebrain_core.py :: ## Get it out of your head
- [x] Untouched old Home notes upgrade themselves. proof: simplebrain_core.py :: a starter note you never edited
- [x] Stress-test before the push. proof: tests/stress.py :: def main

- [x] Glass is the look (the blue was disliked; now the only one). proof: simplebrain_app.py :: One look: Glass
- [x] A tutorial you see: runs after updates, How to button, a Try it line per step. proof: simplebrain_app.py :: TOUR_VERSION
- [x] Pictures and videos open inside the window, never full screen. proof: simplebrain_app.py :: class Viewer
- [x] Video drawn inside even without a GPU (an old machine). proof: simplebrain_desk.py :: --vo=gpu,x11
- [x] Updates follow GitHub's main within half an hour, from any branch, restarting when you're away. proof: simplebrain_update.py :: def default_branch
- [x] Nothing fakeable: the score is what you ticked, not time at a window. proof: simplebrain_watch.py :: def tick_done
- [x] Today never pushes the old trial's videos: a course needs a course:: line. proof: simplebrain_today.py :: course::
- [x] Dataview like Obsidian's: inline fields, FROM/WHERE/SORT/GROUP BY/FLATTEN, TASK. proof: simplebrain_dataview.py :: def run
- [x] Act out a whole week as the user and fix what looks wrong. proof: CHANGELOG.md :: living a simulated week
- [x] Plan actions tick in SimpleBrain, twins together, nothing marked twice. proof: simplebrain_today.py :: def mark_plan_done
- [x] Daily habits that come back after a tick. proof: simplebrain_core.py :: REPEAT_RE

- [x] One theme that never switches: no Theme box; drop-downs ignore the wheel. proof: simplebrain_app.py :: class NoWheel

## From the Jarvis plan
- [x] Step 1, no blank start: login and back after 15+ minutes open today's first thing. proof: simplebrain_watch.py :: 'welcome'
- [x] Step 2, drift catcher with Back to it / Taking a break, quiet during shifts. proof: simplebrain_watch.py :: def in_shift
- [x] Step 2, never-drift words. proof: simplebrain_watch.py :: focus::
- [x] Step 3, logins that stay working (one signed-in profile). proof: simplebrain_app.py :: def web_profile
- [x] Step 4, email digest twice a day. proof: simplebrain_mail.py :: TIMES = (9, 16)
- [x] Email inside SimpleBrain, never the Fastmail site: read, reply, reply all, forward, new, archive, delete, mark unread, make a task or event from it. proof: simplebrain_mailwin.py :: class MailWindow
- [x] The whole calendar inside SimpleBrain: any day or month, add / edit / delete every event (Fastmail's too), place and notes, skip one date of a repeating event. proof: simplebrain_calwin.py :: class CalendarWindow
- [x] Step 5, nothing to move around: Downloads filed. proof: simplebrain_drop.py :: def settled_downloads
- [x] Step 6, end-of-day score. proof: simplebrain_watch.py :: def score_line
- [x] Super+J and login autostart no longer open the old Jarvis display (the desktop mode itself was removed in 0.6.0). proof: CHANGELOG.md :: Removed: the unused desktop mode
- [x] The workbook, one screen at a time (Today, 3 things). proof: simplebrain_today.py :: MAX_THINGS = 3
- [x] A base course in order before the others. proof: simplebrain_today.py :: AFTER_LINE
- [x] Never send, pay, post or delete without a yes (mail sends only on Send, deleted mail goes to Trash, calendar deletes ask first, filing has Undo). proof: simplebrain_calwin.py :: Delete “{e['title']}” on
- [x] Not a pop-up bar, voice assistant, web app or "just a display": everything sits in SimpleBrain and acts. proof: simplebrain_money.py :: Click a goal to leave it out

## From the 60-day plan and open items
- [x] Your money facts as a Budget note (starter notes). proof: simplebrain_budget.py :: def balance_from_file
- [x] Calls with their cards one click away. proof: simplebrain_today.py :: def cards_for
- [x] Work shifts keep it quiet. proof: simplebrain_watch.py :: SHIFT_RE
- [x] OBS clips ready: shown in Today (watch::). proof: simplebrain_today.py :: def fresh_in_watched
- [x] Rebuild + upload + push after every change: CI builds and releases; one zip for the store. proof: .github/workflows/build.yml :: SHA256SUMS
- [x] Every pop-up card has an × to close it now. proof: simplebrain_app.py :: self.close_button.clicked.connect(self.close)
- [x] Book notes: a tick for my personal library vs the public library (a library:: line). proof: simplebrain_app.py :: def on_toggle_library
- [x] A tutorial you can't skip: each step done for real before Next, window held until Done. proof: simplebrain_app.py :: def tutorial_locked
- [x] An ordinary program you click to open: no desktop buttons, no desktop question. proof: CHANGELOG.md :: Make SimpleBrain my desktop** and **Stop being my
- [x] Email with any service, steps to connect it. proof: simplebrain_mail.py :: class ImapAccount
- [x] Your own website (WordPress, Shopify, any site), steps to connect it. proof: simplebrain_publish.py :: class WordPressSite
- [x] The steps, with a button to the right page, tried before saving. proof: simplebrain_setup.py :: class EmailSetup
- [ ] Upload SimpleBrain.zip from the newest release to the Shopify product (yours: Shopify has no upload API for digital files)
- [ ] Paste the Shopify client secret into File > Website (yours)
- [ ] The calls, accounts and paperwork in your own starter notes (yours: there as dated tasks)
