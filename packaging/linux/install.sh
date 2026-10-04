#!/bin/sh
# Installs (or updates) a SimpleBrain build for the current user: app menu entry,
# icon, and `simplebrain` command. Usage: install.sh [path/to/dist/SimpleBrain]
set -eu
SRC="${1:-$(dirname "$0")/../../dist/SimpleBrain}"
[ -x "$SRC/SimpleBrain" ] || { echo "no build at $SRC" >&2; exit 1; }
DEST="$HOME/.local/share/simplebrain/app"
rm -rf "$DEST.new" && mkdir -p "$(dirname "$DEST")" && cp -r "$SRC" "$DEST.new"
rm -rf "$DEST" && mv "$DEST.new" "$DEST"
mkdir -p "$HOME/.local/bin" "$HOME/.local/share/applications" "$HOME/.local/share/icons/hicolor/512x512/apps"
ln -sf "$DEST/SimpleBrain" "$HOME/.local/bin/simplebrain"
cp "$(dirname "$0")/../icon.png" "$HOME/.local/share/icons/hicolor/512x512/apps/simplebrain.png"
sed "s|^Exec=.*|Exec=$DEST/SimpleBrain|" "$(dirname "$0")/simplebrain.desktop" > "$HOME/.local/share/applications/simplebrain.desktop"
command -v update-desktop-database >/dev/null && update-desktop-database "$HOME/.local/share/applications" || true
echo "installed $("$DEST/SimpleBrain" --version) to $DEST"
