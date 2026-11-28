"""View: the animated pixel-art office (one department per live session)."""

from __future__ import annotations

from gi.repository import Adw, Gtk

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
        self.canvas = OfficeCanvas(on_focus=self._on_focus)
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
        self.hint = label("Click a department to enlarge it", "caption", "cm-muted", xalign=0.5)
        box.prepend(self.hint)

        # own header: a back button while a department is enlarged
        tv = Adw.ToolbarView()
        hb = Adw.HeaderBar()
        self.back = Gtk.Button(icon_name="go-previous-symbolic", tooltip_text="All departments (Esc)")
        self.back.connect("clicked", lambda *_: self.canvas.set_focus_slot(None))
        self.back.set_visible(False)
        hb.pack_start(self.back)
        self.wtitle = Adw.WindowTitle(title="View", subtitle="")
        hb.set_title_widget(self.wtitle)
        tv.add_top_bar(hb)
        tv.set_content(self.stack)
        page = Adw.NavigationPage(title=self.title, tag="root")
        page.set_child(tv)
        self.nav.add(page)

        keys = Gtk.ShortcutController(scope=Gtk.ShortcutScope.MANAGED)
        keys.add_shortcut(Gtk.Shortcut(trigger=Gtk.ShortcutTrigger.parse_string("Escape"),
                                       action=Gtk.CallbackAction.new(self._escape)))
        self.add_controller(keys)
        self._views: list = []

    # ----------------------------------------------------------------- focus
    def _escape(self, *_a) -> bool:
        if self.canvas.focus_slot is None:
            return False
        self.canvas.set_focus_slot(None)
        return True

    def _on_focus(self, slot) -> None:
        focused = slot is not None
        self.back.set_visible(focused)
        self.hint.set_visible(not focused and len(self._views) > 1)
        self._update_title()
        self.win.set_sidebar_compact(focused)

    def _update_title(self) -> None:
        slot = self.canvas.focus_slot
        v = next((v for v in self._views if v.slot == slot), None)
        if v is None:
            lit = sum(v.lit for v in self._views)
            self.wtitle.set_subtitle(f"{lit} active · {len(self._views)} departments" if self._views else "")
        else:
            self.wtitle.set_subtitle(v.title + ("" if v.lit else " · dark"))

    def on_shown(self) -> None:
        self.win.set_sidebar_compact(self.canvas.focus_slot is not None)

    def on_snapshot(self, snap: dict) -> None:
        if not isinstance((snap.get("office") or {}).get("departments"), list):
            self.stack.set_visible_child_name("none")
            return
        self._views = model.build_all(snap)
        self.canvas.set_views(self._views)
        self.hint.set_visible(self.canvas.focus_slot is None and len(self._views) > 1)
        self._update_title()
        self.stack.set_visible_child_name("office")
