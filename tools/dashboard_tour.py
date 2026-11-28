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


def shot_widget(widget, name):
    """Render one widget (e.g. a popover's content) on its own."""
    print("popover visible:", widget.get_parent().get_visible() if widget.get_parent() else None, flush=True)
    w, h = widget.get_width(), widget.get_height()
    p = Gtk.WidgetPaintable.new(widget)
    snap = Gtk.Snapshot()
    from gi.repository import Gdk, Graphene
    bg = Gdk.RGBA()
    bg.parse("#2e2e32")
    snap.append_color(bg, Graphene.Rect().init(0, 0, w, h))
    p.snapshot(snap, w, h)
    node = snap.to_node()
    if node is None:
        print("no node for", name)
        return
    tex = app.window.get_renderer().render_texture(node, None)
    path = os.path.join(out, f"{name}.png")
    tex.save_to_png(path)
    print("saved", path, flush=True)


def open_person(win, role):
    page = win.get_page("office")
    for hx, hy, hw, hh, person, view in page.canvas._hits:
        if person.role == role:   # a real click in the middle of the sprite
            page.canvas._on_click(None, 1, hx + hw / 2, hy + hh / 2)
            return


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
        (2500, lambda: shot("00-view")),
        (100, lambda: win.get_page("office").canvas.set_focus_slot(0)),
        (600, lambda: shot("00b-view-department")),
        (100, lambda: win.get_page("office").canvas.zoom_at(1.8)),
        (700, lambda: shot("00c-view-zoomed")),
        (100, lambda: win.get_page("office").canvas.reset_view()),
        (400, lambda: open_person(win, "lead")),
        (900, lambda: shot_widget(win.get_page("office").popover.get_child(), "00d-person-popover")),
        (100, lambda: win.get_page("office").popover.popdown()),
        (100, lambda: win.get_page("office").canvas.set_focus_slot(None)),
        (100, lambda: win.navigate("overview")),
        (1200, lambda: shot("01-overview")),
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
