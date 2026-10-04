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
- **Dark mode toggle**. Trigger: system theme doesn't cover it well enough
  in practice.
- **Export/print a note or the whole vault to PDF/single markdown**. Trigger:
  need to share or archive outside the app.
- **Obsidian vault import**. Trigger: sharing with a second person who has
  an existing Obsidian vault.
- **Parameterize `ICS_CACHE`** (currently a fixed module constant, unlike
  every other function in simplebrain_core.py which takes `vault=VAULT`).
  Trigger: found during CEO review as a minor testability inconsistency,
  not a bug — fix opportunistically next time this area is touched.
- **Dataview search re-reads every note file on every keystroke**
  (`note_rows()` does a full `os.listdir` + read of all notes, wired to
  the search box's `textChanged` signal). Negligible at personal-vault
  scale; same architectural shape as the calendar freeze that was just
  fixed. Trigger: vault grows large enough to notice input lag while typing.
- **`force_layout` runs synchronously on the main thread** on every graph
  resize and "Recompute layout" click (O(n²) × 150 iterations).
  Negligible at a few dozen notes. Trigger: note count grows large enough
  that resizing the window visibly stutters.
- **Graph has no keyboard navigation** — the custom-painted GraphView only
  handles the mouse; there's no way to reach or activate a node via
  keyboard. Accepted for a single mouse-using user; found during design
  review. Trigger: an actual accessibility need arises, or the vault is
  shared with a second person who needs it.
