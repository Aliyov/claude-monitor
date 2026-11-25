#!/usr/bin/env bash
# Claude Monitor uninstaller.
#   ./uninstall.sh          remove the app; keep history database and config
#   ./uninstall.sh --purge  also delete the history database, state and config
set -uo pipefail

APP="$HOME/.local/share/claude-monitor/app"
BIN="$HOME/.local/bin"
UUID="claude-monitor@claude-monitor.local"
PURGE=0
[ "${1:-}" = "--purge" ] && PURGE=1

# Restore Claude Code's status line first (only touches it if our tee is installed).
if [ -d "$APP/claude_monitor" ]; then
    PYTHONPATH="$APP" python3 -m claude_monitor.integrations uninstall-statusline || true
fi

systemctl --user disable --now claude-monitor.service 2>/dev/null || true
rm -f "$HOME/.config/systemd/user/claude-monitor.service" \
      "$HOME/.local/share/dbus-1/services/io.github.ClaudeMonitor.service"
systemctl --user daemon-reload 2>/dev/null || true

gnome-extensions disable "$UUID" 2>/dev/null || true
rm -rf "$HOME/.local/share/gnome-shell/extensions/$UUID"

rm -f "$BIN/claude-monitord" "$BIN/claude-monitor" "$BIN/claude-monitor-dashboard" "$BIN/claude-monitor-statusline"
rm -f "$HOME/.local/share/applications/io.github.ClaudeMonitor.Dashboard.desktop" \
      "$HOME/.local/share/icons/hicolor/scalable/apps/io.github.ClaudeMonitor"*.svg
rm -rf "$APP"

if [ "$PURGE" = 1 ]; then
    rm -rf "$HOME/.local/share/claude-monitor" "$HOME/.local/state/claude-monitor" "$HOME/.config/claude-monitor"
    echo "Claude Monitor removed, including history and settings."
else
    echo "Claude Monitor removed. History kept in ~/.local/share/claude-monitor (use --purge to delete)."
fi
