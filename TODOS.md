# TODOS

Deferred items — not blocking, revisit when the trigger condition hits.

- **Undo for Inbox classify actions**. Trigger: misclicks happen often enough
  that "just edit the text file" stops being an acceptable fix.
- **Export/print a note or the whole vault to PDF/single markdown**. Trigger:
  need to share or archive outside the app.
- **Obsidian vault import**. Trigger: sharing with a second person who has
  an existing Obsidian vault.
- **Graph has no keyboard navigation** — the custom-painted GraphView only
  handles the mouse; there's no way to reach or activate a node via
  keyboard. Accepted for a single mouse-using user; found during design
  review. Trigger: an actual accessibility need arises, or the vault is
  shared with a second person who needs it.
- **Signed releases and a signature check in the updater.** The updater's checksum comes
  from the same release as the file, so it only catches corruption. Trigger: before selling to people
  who don't know the author.
- **Calendar and Shopify secrets in the OS keyring.** The CalDAV password / feed link sits in the vault's
  `.config`; on a USB drive (exFAT, no permissions) anyone holding the drive can read it. Trigger: before
  promoting the portable USB build.
- **Restrict what a `file::` line opens** (known document types, or ask first). Trigger: syncing with a
  device you don't control.
- **`defusedxml` for CalDAV replies.** Low risk (you choose the server). Trigger: any change to the CalDAV code.
- **Code signing (Windows) and notarization (macOS).** First launches show scary warnings. Trigger: when
  sales justify the yearly cost.
- **Split `simplebrain_core.py`** (updater, citations, CalDAV next) **and `simplebrain_app.py`.**
  Trigger: next time one of those areas is touched.
- **An in-app changelog.**

Done and removed from this list (2026-11-22): two-way calendar (CalDAV, `simplebrain_calendar.py`), vault backup and device sync (`backup-vault.sh`, `simplebrain_sync.py`), search across everything (the top bar, `simplebrain_find.py`), pull-request CI runs.
