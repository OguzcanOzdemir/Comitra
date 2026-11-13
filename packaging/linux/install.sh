#!/bin/sh
# Install the extracted portable Comitra folder for the current user:
#   ~/.local/opt/comitra, launchers in ~/.local/bin, menu entry and icon.
# Usage:  ./install.sh            (install)
#         ./install.sh --uninstall
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
PREFIX="${XDG_DATA_HOME:-$HOME/.local/share}"
OPT="$HOME/.local/opt/comitra"
BIN="$HOME/.local/bin"

if [ "$1" = "--uninstall" ]; then
    rm -rf "$OPT" "$BIN/comitra" "$BIN/comitra-cli" \
        "$PREFIX/applications/comitra.desktop" "$PREFIX/icons/hicolor/512x512/apps/comitra.png"
    echo "Comitra removed (your index in ~/.local/share/Comitra was kept)."
    exit 0
fi

mkdir -p "$OPT" "$BIN" "$PREFIX/applications" "$PREFIX/icons/hicolor/512x512/apps"
cp -a "$HERE/." "$OPT/"
# An installed copy uses the normal per-user data folders.
rm -f "$OPT/comitra-portable.txt" "$OPT/install.sh"
ln -sf "$OPT/Comitra" "$BIN/comitra"
ln -sf "$OPT/comitra-cli" "$BIN/comitra-cli"
cp "$HERE/comitra.png" "$PREFIX/icons/hicolor/512x512/apps/comitra.png"
sed "s|^Exec=.*|Exec=\"$OPT/Comitra\" %F|" "$HERE/comitra.desktop" > "$PREFIX/applications/comitra.desktop"
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$PREFIX/applications" || true
echo "Comitra installed. Start it from the application menu or run: comitra"
