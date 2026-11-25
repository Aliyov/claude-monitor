#!/usr/bin/env bash
# Claude Monitor installer — per-user, no root required.
#
#   ./install.sh                     install daemon, dashboard, CLI, shell extension
#   ./install.sh --with-statusline   also enable the status-line tee (edits ~/.claude/settings.json
#                                    with a backup; needed for plan-limit percentages)
#   ./install.sh --no-extension      skip the GNOME Shell extension
#
# Nothing in ~/.claude is modified unless --with-statusline is given.
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP="$HOME/.local/share/claude-monitor/app"
BIN="$HOME/.local/bin"
UUID="claude-monitor@claude-monitor.local"
EXT_DST="$HOME/.local/share/gnome-shell/extensions/$UUID"
WITH_STATUSLINE=0
WITH_EXT=1
for a in "$@"; do
    case "$a" in
        --with-statusline) WITH_STATUSLINE=1 ;;
        --no-extension) WITH_EXT=0 ;;
        -h|--help) sed -n '2,10p' "$0"; exit 0 ;;
        *) echo "unknown option: $a" >&2; exit 2 ;;
    esac
done

say() { printf '\033[1;38;5;173m==>\033[0m %s\n' "$*"; }

say "Checking dependencies"
python3 - <<'EOF'
import sys
try:
    import gi
    gi.require_version("Gtk", "4.0"); gi.require_version("Adw", "1")
    from gi.repository import Gtk, Adw, Gio  # noqa
except Exception as e:
    sys.exit(f"missing dependency: {e}\n  sudo dnf install python3-gobject gtk4 libadwaita")
EOF

say "Installing application files to $APP"
mkdir -p "$APP" "$BIN"
rm -rf "$APP/claude_monitor"
cp -r "$SRC/claude_monitor" "$APP/"
mkdir -p "$APP/docs" && cp "$SRC"/docs/*.md "$APP/docs/" 2>/dev/null || true
find "$APP" -name '__pycache__' -prune -exec rm -rf {} +
python3 -m compileall -q "$APP/claude_monitor" >/dev/null

wrapper() { # name module
    cat > "$BIN/$1" <<EOF
#!/usr/bin/python3 -s
import sys
sys.path.insert(0, "$APP")
from $2 import main
sys.exit(main())
EOF
    chmod 755 "$BIN/$1"
}
wrapper claude-monitord claude_monitor.daemon.__main__
wrapper claude-monitor claude_monitor.cli
wrapper claude-monitor-dashboard claude_monitor.dashboard.app
install -m 755 "$SRC/scripts/claude-monitor-statusline" "$BIN/claude-monitor-statusline"

say "Installing desktop entry and icon"
install -Dm644 "$SRC/data/io.github.ClaudeMonitor.Dashboard.desktop" \
    "$HOME/.local/share/applications/io.github.ClaudeMonitor.Dashboard.desktop"
sed -i "s|^Exec=.*|Exec=$BIN/claude-monitor-dashboard|" \
    "$HOME/.local/share/applications/io.github.ClaudeMonitor.Dashboard.desktop"
for icon in "$SRC"/data/icons/*.svg; do
    [ -e "$icon" ] && install -Dm644 "$icon" "$HOME/.local/share/icons/hicolor/scalable/apps/$(basename "$icon")"
done
gtk4-update-icon-cache -q -t -f "$HOME/.local/share/icons/hicolor" 2>/dev/null || true
update-desktop-database -q "$HOME/.local/share/applications" 2>/dev/null || true

say "Installing user service (systemd --user + D-Bus activation)"
install -Dm644 "$SRC/data/claude-monitor.service" "$HOME/.config/systemd/user/claude-monitor.service"
install -Dm644 "$SRC/data/io.github.ClaudeMonitor.service" "$HOME/.local/share/dbus-1/services/io.github.ClaudeMonitor.service"
mkdir -p "$HOME/.local/share/claude-monitor" "$HOME/.local/state/claude-monitor" "$HOME/.config/claude-monitor"
systemctl --user daemon-reload
systemctl --user enable claude-monitor.service >/dev/null 2>&1
systemctl --user restart claude-monitor.service

if [ "$WITH_EXT" = 1 ] && [ -d "$SRC/extension/$UUID" ]; then
    say "Installing GNOME Shell extension"
    rm -rf "$EXT_DST"
    mkdir -p "$(dirname "$EXT_DST")"
    cp -r "$SRC/extension/$UUID" "$EXT_DST"
    [ -d "$EXT_DST/schemas" ] && glib-compile-schemas "$EXT_DST/schemas"
    if gnome-extensions enable "$UUID" 2>/dev/null; then
        echo "    enabled. On Wayland, log out and back in once so GNOME Shell loads it."
    else
        # Shell doesn't know the new extension until re-login; pre-enable it in settings.
        cur=$(gsettings get org.gnome.shell enabled-extensions 2>/dev/null || echo "@as []")
        case "$cur" in *"$UUID"*) ;; *)
            gsettings set org.gnome.shell enabled-extensions \
                "$(python3 -c 'import ast,sys; l=ast.literal_eval(sys.argv[1].replace("@as ","")); l.append(sys.argv[2]); print(l)' "$cur" "$UUID")" ;;
        esac
        echo "    installed and enabled. Log out and back in once so GNOME Shell loads it."
    fi
fi

if [ "$WITH_STATUSLINE" = 1 ]; then
    say "Enabling status-line tee (backup of settings.json is kept)"
    PYTHONPATH="$APP" python3 -m claude_monitor.integrations install-statusline "$BIN/claude-monitor-statusline"
fi

say "Done."
echo "    Dashboard:  claude-monitor-dashboard   (or 'Claude Monitor' in Activities)"
echo "    CLI:        claude-monitor status"
echo "    Service:    systemctl --user status claude-monitor"
