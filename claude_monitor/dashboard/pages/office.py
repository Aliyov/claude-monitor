"""View: the animated pixel-art office (one department per live session)."""

from __future__ import annotations

from gi.repository import Gtk

from ..office import model
from ..office.canvas import OfficeCanvas
from ..widgets import empty_state, label
from ..window import Page

LEGEND = [("light-red", "Working"), ("light-yellow", "Waiting"), ("light-green", "Idle / done"),
          ("light-grey", "Ambient (not a real agent)")]


class OfficePage(Page):
    title = "View"

    def __init__(self, win) -> None:
        super().__init__(win)
        self.canvas = OfficeCanvas()
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, vexpand=True)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.append(self.canvas)
        legend = Gtk.Box(spacing=16, halign=Gtk.Align.CENTER)
        legend.add_css_class("cm-office-legend")
        for cls, text in LEGEND:
            item = Gtk.Box(spacing=6)
            dot = Gtk.Box(valign=Gtk.Align.CENTER)
            dot.add_css_class("cm-dot")
            dot.add_css_class(cls)
            item.append(dot)
            item.append(label(text, "caption", "cm-muted"))
            legend.append(item)
        box.append(legend)
        self.stack.add_named(box, "office")
        self.stack.add_named(empty_state(
            "cm-office-symbolic", "Office Data Unavailable",
            "The running monitor service does not report office data yet.\n"
            "Reinstall Claude Monitor to update it."), "none")
        tv = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        tv.append(self.stack)
        self.root_page(tv, scroll=False, clamp=100000)

    def on_snapshot(self, snap: dict) -> None:
        if not isinstance((snap.get("office") or {}).get("departments"), list):
            self.stack.set_visible_child_name("none")
            return
        self.canvas.set_views(model.build_all(snap))
        self.stack.set_visible_child_name("office")
