# TODOS

Deferred items — not blocking, revisit when the trigger condition hits.

- **Two-way calendar write-back** (CalDAV instead of read-only ICS
  pull). Trigger: need to create/edit events that show up in the real
  calendar, not just SimpleBrain's local one. Needs CalDAV credentials.
- **Backup/sync for the vault** (~/Documents/SimpleBrain is a single point of
  failure — no backup mechanism). Trigger: vault holds anything not also
  recorded elsewhere.
- **Fuzzy search across all notes (Ctrl+K)**. Trigger: sidebar note list gets
  long enough that scrolling to find a note is annoying.
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
- **Pull-request CI runs and an in-app changelog.**
