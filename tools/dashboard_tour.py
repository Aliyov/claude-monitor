#!/usr/bin/env python3
"""Dev tool: launch the dashboard, visit every page, save PNG renders, quit.

    dbus-run-session -- sh -c 'python3 tools/mock_daemon.py & sleep 1; python3 tools/dashboard_tour.py OUT_DIR'

Renders are produced offscreen from the window's own render node, so this
works on Wayland without screenshot permissions.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claude_monitor.dashboard.app import DashboardApp  # noqa: E402
from gi.repository import GLib, Gtk  # noqa: E402

out = sys.argv[1] if len(sys.argv) > 1 else "."
width = int(os.environ.get("TOUR_WIDTH", "1240"))
height = int(os.environ.get("TOUR_HEIGHT", "860"))
scheme = os.environ.get("TOUR_SCHEME", "")
os.makedirs(out, exist_ok=True)
app = DashboardApp()
steps = []


def shot(name):
    win = app.window
    p = Gtk.WidgetPaintable.new(win)
    w, h = win.get_width(), win.get_height()
    snap = Gtk.Snapshot()
    p.snapshot(snap, w, h)
    node = snap.to_node()
    if node is None:
        print("no node for", name)
        return
    tex = win.get_renderer().render_texture(node, None)
    path = os.path.join(out, f"{name}.png")
    tex.save_to_png(path)
    print("saved", path, flush=True)


def first_live():
    snap = app.window.snapshot or {}
    live = snap.get("sessions") or []
    return live[0]["session_id"] if live else None


def plan():
    win = app.window
    win.set_default_size(width, height)
    if scheme:
        from gi.repository import Adw
        Adw.StyleManager.get_default().set_color_scheme(
            Adw.ColorScheme.FORCE_DARK if scheme == "dark" else Adw.ColorScheme.FORCE_LIGHT)
    seq = [
        (2500, lambda: shot("01-overview")),
        (100, lambda: win.navigate("sessions")),
        (1200, lambda: shot("02-sessions")),
        (100, lambda: win.open_session(first_live() or "mock-0001-aaaa", live=True)),
        (4500, lambda: shot("03-session-detail")),
        (100, lambda: win.navigate("timeline")),
        (1500, lambda: shot("04-timeline")),
        (100, lambda: win.navigate("history")),
        (1500, lambda: shot("05-history")),
        (100, lambda: win.open_session("mock-h003", live=False)),
        (1500, lambda: shot("06-history-detail")),
        (100, lambda: win.navigate("stats")),
        (1500, lambda: shot("07-stats")),
        (100, lambda: win.open_preferences()),
        (1200, lambda: shot("08-preferences")),
        (200, lambda: app.quit()),
    ]
    t = 0
    for delay, fn in seq:
        t += delay
        GLib.timeout_add(t, lambda fn=fn: (fn(), False)[1])
    return False


app.connect("activate", lambda *_: GLib.idle_add(plan))
sys.exit(app.run([sys.argv[0]]))
