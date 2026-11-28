#!/usr/bin/env bash
# Claudeville uninstaller.
#   ./uninstall.sh          remove the app; keep history database and config
#   ./uninstall.sh --purge  also delete the history database, state and config
set -uo pipefail

APP="$HOME/.local/share/claudeville/app"
BIN="$HOME/.local/bin"
UUID="claudeville@aliyov.github.io"
PURGE=0
[ "${1:-}" = "--purge" ] && PURGE=1

# Restore Claude Code's status line first (only touches it if our tee is installed).
if [ -d "$APP/claudeville" ]; then
    PYTHONPATH="$APP" python3 -m claudeville.integrations uninstall-statusline || true
fi

systemctl --user disable --now claudeville.service 2>/dev/null || true
rm -f "$HOME/.config/systemd/user/claudeville.service" \
      "$HOME/.local/share/dbus-1/services/io.github.aliyov.Claudeville.service"
systemctl --user daemon-reload 2>/dev/null || true

gnome-extensions disable "$UUID" 2>/dev/null || true
rm -rf "$HOME/.local/share/gnome-shell/extensions/$UUID"

rm -f "$BIN/claudevilled" "$BIN/claudeville" "$BIN/claudeville-dashboard" "$BIN/claudeville-statusline"
# link kept for Claude Code settings written before the rename
[ -L "$BIN/claude-monitor-statusline" ] && rm -f "$BIN/claude-monitor-statusline"
rm -f "$HOME/.local/share/applications/io.github.aliyov.Claudeville.Dashboard.desktop" \
      "$HOME/.local/share/icons/hicolor/scalable/apps/io.github.aliyov.Claudeville"*.svg
rm -rf "$APP"

if [ "$PURGE" = 1 ]; then
    rm -rf "$HOME/.local/share/claudeville" "$HOME/.local/state/claudeville" "$HOME/.config/claudeville"
    echo "Claudeville removed, including history and settings."
else
    echo "Claudeville removed. History kept in ~/.local/share/claudeville (use --purge to delete)."
fi
