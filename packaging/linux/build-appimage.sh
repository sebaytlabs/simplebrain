#!/bin/sh
# Wraps the PyInstaller build (dist/SimpleBrain) into dist/SimpleBrain-x86_64.AppImage.
set -eu
cd "$(dirname "$0")/../.."
APPDIR=build/SimpleBrain.AppDir
rm -rf "$APPDIR" && mkdir -p "$APPDIR"
cp -r dist/SimpleBrain "$APPDIR/SimpleBrain"
cp packaging/linux/simplebrain.desktop "$APPDIR/simplebrain.desktop"
cp packaging/icon.png "$APPDIR/simplebrain.png"
cat > "$APPDIR/AppRun" <<'RUN'
#!/bin/sh
exec "$(dirname "$(readlink -f "$0")")/SimpleBrain/SimpleBrain" "$@"
RUN
chmod +x "$APPDIR/AppRun"
# Pinned release + checksum: a moved "continuous" build or a tampered download
# would otherwise go straight into every Linux release. Bump both together.
TOOL_VERSION=1.9.1
TOOL_SHA256=ed4ce84f0d9caff66f50bcca6ff6f35aae54ce8135408b3fa33abfc3cb384eb0
TOOL=build/appimagetool-$TOOL_VERSION-x86_64.AppImage
[ -f "$TOOL" ] || curl -sSL -o "$TOOL" "https://github.com/AppImage/appimagetool/releases/download/$TOOL_VERSION/appimagetool-x86_64.AppImage"
echo "$TOOL_SHA256  $TOOL" | sha256sum -c - || { rm -f "$TOOL"; echo "appimagetool checksum mismatch" >&2; exit 1; }
chmod +x "$TOOL"
ARCH=x86_64 "$TOOL" --appimage-extract-and-run "$APPDIR" dist/SimpleBrain-x86_64.AppImage
