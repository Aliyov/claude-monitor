"""View: the animated pixel-art office (one department per live session)."""

from __future__ import annotations

import re

from gi.repository import Adw, Gdk, Gtk, Pango

from ..office import model
from ..office.canvas import OfficeCanvas
from ..widgets import empty_state, label
from ..window import Page

LEGEND = [("light-red", "Working"), ("light-yellow", "Waiting"), ("light-green", "Idle / done"),
          ("light-grey", "Ambient (not a real agent)")]
LIGHT_CLASS = {model.RED: "light-red", model.YELLOW: "light-yellow", model.GREEN: "light-green",
               model.GREY: "light-grey"}
EFFORT_TEXT = {"low": "Low", "medium": "Medium", "high": "High", "xhigh": "Extra high", "max": "Max"}
HINT_GRID = "Click a department to enlarge it · scroll to zoom"
HINT_FOCUS = "Click someone for details · scroll or pinch to zoom · drag to move"


def pretty_model(m: str | None) -> str:
    """'claude-opus-5-5' -> 'Opus 5.5', 'sonnet' -> 'Sonnet'; unknown text is kept."""
    if not m:
        return "—"
    if m == "inherit":
        return "Same as the session"
    mm = re.match(r"(?:claude-)?(fable|opus|sonnet|haiku)(?:-(\d+)(?:-(\d+))?)?", m)
    if not mm:
        return m
    name = mm.group(1).capitalize()
    if mm.group(2):
        name += f" {mm.group(2)}" + (f".{mm.group(3)}" if mm.group(3) else "")
    return name


def role_text(p: model.Person, view: model.DepartmentView) -> str:
    if p.role == "lead":
        return "Lead · the main Claude Code session"
    if p.role == "contractor":
        return "Contractor · temporary desk"
    if p.filler:
        return "Ambient worker"
    if p.seat == "private":
        return "Team agent · private room (highest rank)"
    if view.source == "default":
        return "Subagent"
    return "Team agent"


class PersonPopover(Gtk.Popover):
    def __init__(self, on_open_session) -> None:
        super().__init__(has_arrow=True, autohide=True)
        self.add_css_class("cm-person-popover")
        self._on_open = on_open_session
        self.ref = None              # (slot, person key)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        for m in ("top", "bottom", "start", "end"):
            getattr(box, f"set_margin_{m}")(6)
        box.set_size_request(260, -1)
        self.title = label("", "heading", ellipsize=True)
        self.role = label("", "caption", "cm-muted", wrap=True)
        box.append(self.title)
        box.append(self.role)
        self.grid = Gtk.Grid(column_spacing=12, row_spacing=4)
        box.append(self.grid)
        self.note = label("", "caption", "cm-muted", wrap=True)
        box.append(self.note)
        self.open_btn = Gtk.Button(label="Open Session")
        self.open_btn.add_css_class("pill")
        self.open_btn.connect("clicked", self._open)
        box.append(self.open_btn)
        self.set_child(box)
        self._session = None

    def _open(self, *_a) -> None:
        if self._session:
            self.popdown()
            self._on_open(self._session)

    def show_person(self, p: model.Person, view: model.DepartmentView) -> None:
        self.ref = (view.slot, p.key)
        child = self.grid.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self.grid.remove(child)
            child = nxt
        if p.filler:
            self.title.set_text("Ambient worker")
            self.role.set_text("Not a real agent")
            self.note.set_text("Shown so every department has at least five people. "
                               "Ambient workers never show activity.")
            self.note.set_visible(True)
            self.open_btn.set_visible(False)
            return
        self.title.set_text(p.name or "—")
        self.role.set_text(role_text(p, view))
        rows = []
        status = Gtk.Box(spacing=6)
        dot = Gtk.Box(valign=Gtk.Align.CENTER)
        dot.add_css_class("cm-dot")
        dot.add_css_class(LIGHT_CLASS.get(p.light, "light-grey"))
        status.append(dot)
        status.append(label(p.status_text or "—", wrap=True))
        rows.append(("Status", status))
        rows.append(("Model", pretty_model(p.model)))
        rows.append(("Effort", EFFORT_TEXT.get(p.effort, p.effort) if p.effort else "—"))
        if p.current:
            doing = p.current.get("tool") or ""
            if p.current.get("summary"):
                doing += f" · {p.current['summary']}"
            rows.append(("Doing", doing or "—"))
        if p.description:
            rows.append(("Task" if p.role != "lead" else "Session", p.description))
        rows.append(("Project", view.project or "—"))
        for r, (k, v) in enumerate(rows):
            self.grid.attach(label(k, "caption", "cm-muted"), 0, r, 1, 1)
            w = v if isinstance(v, Gtk.Widget) else label(str(v), wrap=True)
            if isinstance(w, Gtk.Label):
                w.set_max_width_chars(34)
                w.set_lines(2)
                w.set_ellipsize(Pango.EllipsizeMode.END)
                w.set_tooltip_text(str(v))
            self.grid.attach(w, 1, r, 1, 1)
        self.note.set_visible(False)
        self._session = view.session_id if view.lit else None
        self.open_btn.set_visible(self._session is not None)


class OfficePage(Page):
    title = "View"

    def __init__(self, win) -> None:
        super().__init__(win)
        self.canvas = OfficeCanvas(on_focus=self._on_focus, on_person=self._on_person,
                                   on_zoom=self._on_zoom)
        self.popover = PersonPopover(lambda sid: self.win.open_session(sid, live=True))
        self.canvas.add_popover(self.popover)
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, vexpand=True)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.hint = label(HINT_GRID, "caption", "cm-muted", xalign=0.5)
        box.append(self.hint)
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

        tv = Adw.ToolbarView()
        hb = Adw.HeaderBar()
        self.back = Gtk.Button(icon_name="go-previous-symbolic", tooltip_text="All departments (Esc)")
        self.back.connect("clicked", lambda *_: self.canvas.set_focus_slot(None))
        self.back.set_visible(False)
        hb.pack_start(self.back)
        self.wtitle = Adw.WindowTitle(title="View", subtitle="")
        hb.set_title_widget(self.wtitle)
        zoom = Gtk.Box()
        zoom.add_css_class("linked")
        out_btn = Gtk.Button(icon_name="zoom-out-symbolic", tooltip_text="Zoom out (−)")
        out_btn.connect("clicked", lambda *_: self.canvas.zoom_at(1 / 1.25))
        self.zoom_label = Gtk.Button(label="100%", tooltip_text="Reset zoom (0)")
        self.zoom_label.add_css_class("cm-zoom-label")
        self.zoom_label.connect("clicked", lambda *_: self.canvas.reset_view())
        in_btn = Gtk.Button(icon_name="zoom-in-symbolic", tooltip_text="Zoom in (+)")
        in_btn.connect("clicked", lambda *_: self.canvas.zoom_at(1.25))
        for b in (out_btn, self.zoom_label, in_btn):
            zoom.append(b)
        hb.pack_end(zoom)
        tv.add_top_bar(hb)
        tv.set_content(self.stack)
        page = Adw.NavigationPage(title=self.title, tag="root")
        page.set_child(tv)
        self.nav.add(page)

        keys = Gtk.ShortcutController(scope=Gtk.ShortcutScope.MANAGED)
        for trig, fn in (("Escape", self._escape),
                         ("plus|equal|KP_Add|<Control>plus|<Control>equal", lambda *_: self._key_zoom(1.25)),
                         ("minus|KP_Subtract|<Control>minus", lambda *_: self._key_zoom(1 / 1.25)),
                         ("0|KP_0|<Control>0", lambda *_: (self.canvas.reset_view(), True)[1])):
            keys.add_shortcut(Gtk.Shortcut(trigger=Gtk.ShortcutTrigger.parse_string(trig),
                                           action=Gtk.CallbackAction.new(fn)))
        self.add_controller(keys)
        self._views: list = []

    # ----------------------------------------------------------------- focus
    def _key_zoom(self, f) -> bool:
        self.canvas.zoom_at(f)
        return True

    def _escape(self, *_a) -> bool:
        if self.popover.get_visible():
            self.popover.popdown()
            return True
        if self.canvas.zoom > 1.0:
            self.canvas.reset_view()
            return True
        if self.canvas.focus_slot is None:
            return False
        self.canvas.set_focus_slot(None)
        return True

    def _on_focus(self, slot) -> None:
        focused = slot is not None
        self.popover.popdown()
        self.back.set_visible(focused)
        self._update_hint()
        self._update_title()
        self.win.set_sidebar_compact(focused)

    def _on_zoom(self, z: float) -> None:
        self.zoom_label.set_label(f"{round(z * 100)}%")

    def _on_person(self, person, view, rect) -> None:
        self.popover.show_person(person, view)
        r = Gdk.Rectangle()
        r.x, r.y, r.width, r.height = int(rect[0]), int(rect[1]), max(1, int(rect[2])), max(1, int(rect[3]))
        self.popover.set_pointing_to(r)
        self.popover.popup()

    def _update_hint(self) -> None:
        single = len(self._views) == 1
        self.hint.set_text(HINT_FOCUS if self.canvas.focus_slot is not None or single else HINT_GRID)

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
        self._update_hint()
        self._update_title()
        self.stack.set_visible_child_name("office")
        if self.popover.get_visible() and self.popover.ref:   # keep an open popup current
            slot, key = self.popover.ref
            v = next((v for v in self._views if v.slot == slot), None)
            p = next((p for p in v.people if p.key == key), None) if v else None
            if p is None or p.light == model.OFF:
                self.popover.popdown()
            else:
                self.popover.show_person(p, v)
