# Claudeville — GNOME Shell extension

Floating widget + top-bar indicator for GNOME Shell 50. It is a thin client of
the `claudevilled` D-Bus service (`io.github.aliyov.Claudeville`, see
`docs/CONTRACT.md`) and never reads `~/.claude` or talks to the network itself.

UUID: `claudeville@aliyov.github.io`

## Features

- **Floating card**: 5-hour and weekly plan usage (only real values from the
  daemon; `—` when unknown, "reset · awaiting update" once a window has rolled
  over), live/busy/waiting/agents counts, and live sessions with status dot,
  current tool, CPU, RAM and context %.
  Drag it anywhere (the position is saved and kept inside the work area).
  Click the header to collapse it to a pill. It sits above application
  windows but below shell menus, and can hide while a fullscreen window is on
  its monitor.
- **Panel indicator** (optional): status dot + `sessions  5h%`. Turns amber
  when a session is waiting for you. The menu mirrors the card and has
  *Open Dashboard*, a floating-widget switch, and *Preferences*.
- **Shortcut**: `<Super><Alt>c` toggles the card (configurable, can be empty).
- **Offline state**: when the daemon is not running, the UI says so and
  reconnects automatically when the bus name appears.

## Resource use

- No polling: one `GetSnapshot` on connect, then only on `SnapshotChanged`
  (≤ 1 Hz from the daemon); overlapping fetches are coalesced.
- The countdown timer only runs while a countdown is actually visible (card
  expanded, or menu open): 1 s when a reset is < 1 h away, else 15 s.
- The busy-dot "breathing" is one shared low-priority timer (a short ease
  every 2.4 s), active only while visible; disable with *Reduce animations*.
  Shell-wide "reduce animation" settings are respected automatically.
- Session rows are reused and diffed by `session_id`; the panel menu only
  renders while open.
- Every D-Bus call is async and cancelled in `disable()`.

## Install (normally done by the project's install script)

```sh
EXT=claudeville@aliyov.github.io
DEST=~/.local/share/gnome-shell/extensions/$EXT
mkdir -p "$DEST"
cp -r extension/$EXT/* "$DEST/"
glib-compile-schemas "$DEST/schemas"
gnome-extensions enable $EXT
```

On **Wayland**, GNOME Shell only picks up a *newly installed* extension after
you log out and back in. Updating files of an already loaded extension also
needs a re-login, or disable + enable for most JS changes.

## Development

- Logs: `journalctl --user -f -o cat /usr/bin/gnome-shell | grep -i claude`
- Preferences: `gnome-extensions prefs claudeville@aliyov.github.io`
- Nested test shell (needs `mutter-devkit`, not installed on this machine):
  `dbus-run-session gnome-shell --devkit --wayland`
- Syntax check: `for f in *.js; do node --input-type=module --check < $f; done`
- Schema check: `glib-compile-schemas --strict --dry-run schemas`

## Files

| File | Role |
|---|---|
| `extension.js` | enable/disable, wiring, countdown ticker, dashboard launcher |
| `client.js` | async D-Bus client (bus-name watch, signal, coalesced fetch) |
| `widget.js` | floating card: drag, collapse, placement, hover |
| `indicator.js` | panel button + popup menu |
| `views.js` | shared UsageView / SessionList / StatusDot / Pulser |
| `format.js` | pure formatting helpers (no GNOME imports) |
| `prefs.js` | Adw preferences |
| `stylesheet.css` | styles |
| `schemas/` | GSettings schema |
| `icons/` | symbolic icon |
