#!/usr/bin/env bash
# Claudeville installer: per-user, no root needed.
#
# One line, straight from GitHub (installs the latest release):
#   curl -fsSL https://raw.githubusercontent.com/Aliyov/claudeville/main/install.sh | bash
#
# Or from a checkout / extracted release:
#   ./install.sh                     service, dashboard, CLI and GNOME top-bar extension
#   ./install.sh --with-statusline   also enable the status-line tee (edits ~/.claude/settings.json
#                                    with a backup; needed for plan-limit percentages)
#   ./install.sh --no-extension      skip the GNOME Shell extension
#
# Nothing in ~/.claude is modified unless --with-statusline is given.
set -euo pipefail

REPO="Aliyov/claudeville"
say() { printf '\033[1;38;5;173m==>\033[0m %s\n' "$*"; }
die() { printf '\033[1;31merror:\033[0m %s\n' "$*" >&2; exit 1; }

# --- bootstrap: piped from curl, or run without the source tree next to it
SELF="${BASH_SOURCE[0]:-}"
SRC=""
[ -n "$SELF" ] && [ -f "$SELF" ] && SRC="$(cd "$(dirname "$SELF")" && pwd)"
if [ -z "$SRC" ] || [ ! -f "$SRC/claudeville/__init__.py" ]; then
    command -v curl >/dev/null || die "curl is needed to download Claudeville"
    REF="${CLAUDEVILLE_REF:-}"
    if [ -z "$REF" ]; then
        REF=$(curl -fsSL "https://api.github.com/repos/$REPO/releases/latest" 2>/dev/null |
              python3 -c 'import json,sys; print(json.load(sys.stdin).get("tag_name",""))' 2>/dev/null || true)
    fi
    REF="${REF:-main}"
    TMP="$(mktemp -d)"
    trap 'rm -rf "$TMP"' EXIT
    say "Downloading Claudeville ($REF)"
    curl -fsSL "https://github.com/$REPO/archive/$REF.tar.gz" | tar -xz -C "$TMP" ||
        die "download failed (https://github.com/$REPO/archive/$REF.tar.gz)"
    DIR="$(find "$TMP" -mindepth 1 -maxdepth 1 -type d | head -n 1)"
    bash "$DIR/install.sh" "$@"
    exit $?
fi

APP="$HOME/.local/share/claudeville/app"
BIN="$HOME/.local/bin"
UUID="claudeville@aliyov.github.io"
EXT_DST="$HOME/.local/share/gnome-shell/extensions/$UUID"
WITH_STATUSLINE=0
WITH_EXT=1
for a in "$@"; do
    case "$a" in
        --with-statusline) WITH_STATUSLINE=1 ;;
        --no-extension) WITH_EXT=0 ;;
        -h|--help) sed -n '2,13p' "$0"; exit 0 ;;
        *) die "unknown option: $a" ;;
    esac
done

# --- dependencies
say "Checking dependencies"
deps_hint() {
    local id=""
    [ -r /etc/os-release ] && id="$(. /etc/os-release; echo "${ID:-} ${ID_LIKE:-}")"
    case "$id" in
        *fedora*|*rhel*|*centos*) echo "sudo dnf install python3-gobject gtk4 libadwaita" ;;
        *debian*|*ubuntu*)        echo "sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1" ;;
        *arch*)                   echo "sudo pacman -S python-gobject gtk4 libadwaita" ;;
        *suse*)                   echo "sudo zypper install python3-gobject typelib-1_0-Gtk-4_0 typelib-1_0-Adw-1" ;;
        *)                        echo "install PyGObject, GTK 4 and libadwaita (1.6 or newer) with your package manager" ;;
    esac
}
[ "$(uname -s)" = Linux ] || die "Claudeville needs Linux (it reads /proc and uses systemd --user)"
command -v python3 >/dev/null || die "python3 not found. $(deps_hint)"
if ! python3 - <<'EOF'
import sys
if sys.version_info < (3, 10):
    sys.exit("Python 3.10 or newer is needed (found %d.%d)" % sys.version_info[:2])
try:
    import gi
    gi.require_version("Gtk", "4.0"); gi.require_version("Adw", "1")
    from gi.repository import Adw, Gio, Gtk  # noqa
except Exception as e:
    sys.exit(f"missing dependency: {e}")
if (Adw.get_major_version(), Adw.get_minor_version()) < (1, 6):
    sys.exit("libadwaita 1.6 or newer is needed (found %d.%d)" % (Adw.get_major_version(), Adw.get_minor_version()))
EOF
then
    die "dependencies missing. Try: $(deps_hint)"
fi
systemctl --user show-environment >/dev/null 2>&1 || die "a systemd user session is needed (systemctl --user)"

# --- migrate an install from before the rename ("Claude Monitor")
OLD_UUID="claude-monitor@claude-monitor.local"
if [ -e "$HOME/.local/share/claude-monitor" ] || [ -e "$HOME/.config/systemd/user/claude-monitor.service" ]; then
    say "Migrating from Claude Monitor (history and settings are kept)"
    systemctl --user disable --now claude-monitor.service >/dev/null 2>&1 || true
    rm -f "$HOME/.config/systemd/user/claude-monitor.service" \
          "$HOME/.local/share/dbus-1/services/io.github.ClaudeMonitor.service"
    systemctl --user daemon-reload || true
    for pair in ".local/share/claude-monitor:.local/share/claudeville" \
                ".local/state/claude-monitor:.local/state/claudeville" \
                ".config/claude-monitor:.config/claudeville"; do
        old="$HOME/${pair%%:*}"; new="$HOME/${pair##*:}"
        if [ -d "$old" ] && [ ! -e "$new" ]; then
            mv "$old" "$new"
        elif [ -d "$old" ]; then
            echo "    kept $old (a newer $new already exists)"
        fi
    done
    rm -f "$BIN/claude-monitord" "$BIN/claude-monitor" "$BIN/claude-monitor-dashboard"
    rm -f "$HOME/.local/share/applications/io.github.ClaudeMonitor.Dashboard.desktop" \
          "$HOME/.local/share/icons/hicolor/scalable/apps/io.github.ClaudeMonitor"*.svg
    if [ -d "$HOME/.local/share/gnome-shell/extensions/$OLD_UUID" ]; then
        gnome-extensions disable "$OLD_UUID" >/dev/null 2>&1 || true
        rm -rf "$HOME/.local/share/gnome-shell/extensions/$OLD_UUID"
        cur=$(gsettings get org.gnome.shell enabled-extensions 2>/dev/null || echo "@as []")
        case "$cur" in *"$OLD_UUID"*)
            gsettings set org.gnome.shell enabled-extensions \
                "$(python3 -c 'import ast,sys; l=ast.literal_eval(sys.argv[1].replace("@as ","")); print([x for x in l if x != sys.argv[2]])' "$cur" "$OLD_UUID")" ;;
        esac
    fi
fi

# --- application files
say "Installing application files to $APP"
mkdir -p "$APP" "$BIN"
rm -rf "$APP/claudeville" "$APP/claude_monitor"
cp -r "$SRC/claudeville" "$APP/"
mkdir -p "$APP/docs" && cp "$SRC"/docs/*.md "$APP/docs/" 2>/dev/null || true
cp "$SRC/LICENSE" "$APP/" 2>/dev/null || true
find "$APP" -name '__pycache__' -prune -exec rm -rf {} +
python3 -m compileall -q "$APP/claudeville" >/dev/null

wrapper() { # name module
    cat > "$BIN/$1" <<EOF
#!/usr/bin/env -S python3 -s
import sys
sys.path.insert(0, "$APP")
from $2 import main
sys.exit(main())
EOF
    chmod 755 "$BIN/$1"
}
wrapper claudevilled claudeville.daemon.__main__
wrapper claudeville claudeville.cli
wrapper claudeville-dashboard claudeville.dashboard.app
install -m 755 "$SRC/scripts/claudeville-statusline" "$BIN/claudeville-statusline"
# Claude Code may still call the tee by its old name: keep that name working.
if [ -e "$BIN/claude-monitor-statusline" ] || grep -qs "claude-monitor-statusline" "$HOME/.claude/settings.json"; then
    ln -sf claudeville-statusline "$BIN/claude-monitor-statusline"
fi

say "Installing desktop entry and icon"
DESKTOP="$HOME/.local/share/applications/io.github.aliyov.Claudeville.Dashboard.desktop"
install -Dm644 "$SRC/data/io.github.aliyov.Claudeville.Dashboard.desktop" "$DESKTOP"
sed -i "s|^Exec=.*|Exec=$BIN/claudeville-dashboard|" "$DESKTOP"
for icon in "$SRC"/data/icons/*.svg; do
    [ -e "$icon" ] && install -Dm644 "$icon" "$HOME/.local/share/icons/hicolor/scalable/apps/$(basename "$icon")"
done
gtk4-update-icon-cache -q -t -f "$HOME/.local/share/icons/hicolor" 2>/dev/null || true
update-desktop-database -q "$HOME/.local/share/applications" 2>/dev/null || true

say "Installing user service (systemd --user + D-Bus activation)"
install -Dm644 "$SRC/data/claudeville.service" "$HOME/.config/systemd/user/claudeville.service"
install -Dm644 "$SRC/data/io.github.aliyov.Claudeville.service" \
    "$HOME/.local/share/dbus-1/services/io.github.aliyov.Claudeville.service"
mkdir -p "$HOME/.local/share/claudeville" "$HOME/.local/state/claudeville" "$HOME/.config/claudeville"
systemctl --user daemon-reload
systemctl --user enable claudeville.service >/dev/null 2>&1
systemctl --user restart claudeville.service

# --- GNOME Shell extension (top-bar indicator), only on supported versions
if [ "$WITH_EXT" = 1 ] && [ -d "$SRC/extension/$UUID" ]; then
    SHELL_MAJOR="$(gnome-shell --version 2>/dev/null | sed -n 's/[^0-9]*\([0-9]\+\).*/\1/p')"
    SUPPORTED="$(python3 -c 'import json,sys; print(" ".join(json.load(open(sys.argv[1]))["shell-version"]))' \
                 "$SRC/extension/$UUID/metadata.json")"
    if [ -z "$SHELL_MAJOR" ]; then
        say "Skipping the top-bar extension (GNOME Shell not found)"
    elif ! printf ' %s ' "$SUPPORTED" | grep -q " $SHELL_MAJOR "; then
        say "Skipping the top-bar extension (made for GNOME $SUPPORTED, you have GNOME $SHELL_MAJOR)"
        echo "    The dashboard and service work without it."
    else
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
fi

if [ "$WITH_STATUSLINE" = 1 ]; then
    say "Enabling status-line tee (backup of settings.json is kept)"
    PYTHONPATH="$APP" python3 -m claudeville.integrations install-statusline "$BIN/claudeville-statusline"
fi

say "Done."
echo "    Dashboard:  'Claudeville' in Activities, or claudeville-dashboard"
echo "    CLI:        claudeville status"
echo "    Service:    systemctl --user status claudeville"
case ":$PATH:" in *":$BIN:"*) ;; *) echo "    Note: add $BIN to your PATH to use the commands from a terminal." ;; esac
