#!/usr/bin/env bash
# One-way vault backup. Changed/deleted notes are kept under .history/<timestamp>/, never lost.
# .config is skipped: it holds the calendar feed link, which is a secret.
set -euo pipefail
SRC="${SIMPLEBRAIN_VAULT:-$HOME/Documents/SimpleBrain}/"
DEST="${1:-/media/owner/Backup/SimpleBrain-vault}"
mountpoint -q "$(dirname "$DEST")" || [ -d "$(dirname "$DEST")" ] || { echo "drive not mounted: $DEST" >&2; exit 1; }
mkdir -p "$DEST"
rsync -a --delete --exclude=.config --exclude=.calendar-cache.ics --exclude=.trash \
  --backup --backup-dir="$DEST/.history/$(date +%F_%H%M%S)" --exclude=/.history "$SRC" "$DEST/"
echo "backed up $(find "$DEST" -path "$DEST/.history" -prune -o -type f -print | wc -l) files to $DEST"
