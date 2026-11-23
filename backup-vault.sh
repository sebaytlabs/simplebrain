#!/usr/bin/env bash
# One-way vault backup. Changed/deleted notes are kept under .history/<timestamp>/, never lost.
# .config is skipped: it holds the calendar feed link, which is a secret.
# Usage: ./backup-vault.sh /path/on/your/backup/drive/SimpleBrain-vault   (or set SIMPLEBRAIN_BACKUP once)
set -euo pipefail
SRC="${SIMPLEBRAIN_VAULT:-$HOME/Documents/SimpleBrain}/"
DEST="${1:-${SIMPLEBRAIN_BACKUP:-}}"
[ -n "$DEST" ] || { echo "usage: $0 /path/on/backup/drive/SimpleBrain-vault  (or set SIMPLEBRAIN_BACKUP)" >&2; exit 2; }
mountpoint -q "$(dirname "$DEST")" || [ -d "$(dirname "$DEST")" ] || { echo "drive not mounted: $DEST" >&2; exit 1; }
mkdir -p "$DEST"
rsync -a --delete --exclude=.config --exclude=.calendar-cache.ics --exclude=.trash \
  --backup --backup-dir="$DEST/.history/$(date +%F_%H%M%S)" --exclude=/.history "$SRC" "$DEST/"
echo "backed up $(find "$DEST" -path "$DEST/.history" -prune -o -type f -print | wc -l) files to $DEST"
