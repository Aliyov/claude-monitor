"""Timeline: chronological cross-session activity with infinite scroll."""

from __future__ import annotations

from gi.repository import Adw, GLib, GObject, Gio, Gtk

from ..widgets import EventRow, label
from ..window import Page

PAGE_SIZE = 150
MAX_ITEMS = 6000

KIND_FILTERS = [
    ("All activity", None),
    ("Tools", {"tool"}),
    ("Errors", {"error"}),
    ("Prompts & turns", {"prompt", "turn_end"}),
    ("Agents", {"subagent_start", "subagent_end"}),
    ("Sessions", {"session_start", "session_end", "status", "compact", "limit"}),
]


class EventItem(GObject.Object):
    __gtype_name__ = "CMEventItem"

    def __init__(self, ev: dict) -> None:
        super().__init__()
        self.ev = ev


def make_event_list(show_project: bool = True, show_date: bool = True):
    """Return (store, filter_model, listview, custom_filter) for virtualised event lists."""
    store = Gio.ListStore(item_type=EventItem)
    custom = Gtk.CustomFilter()
    fmodel = Gtk.FilterListModel(model=store, filter=custom, incremental=False)
    sel = Gtk.NoSelection(model=fmodel)
    factory = Gtk.SignalListItemFactory()

    def setup(_f, item):
        item.set_child(EventRow(show_project=show_project))

    def bind(_f, item):
        item.get_child().bind(item.get_item().ev, show_date=show_date)

    factory.connect("setup", setup)
    factory.connect("bind", bind)
    lv = Gtk.ListView(model=sel, factory=factory)
    lv.add_css_class("cm-list")
    lv.set_vexpand(True)
    return store, fmodel, lv, custom


class TimelinePage(Page):
    title = "Timeline"

    def __init__(self, win) -> None:
        super().__init__(win)
        self.store, self.fmodel, self.lv, self.filter = make_event_list()
        self.filter.set_filter_func(self._match)
        self._ids: set[int] = set()
        self._oldest = 0
        self._loading = False
        self._exhausted = False
        self._kinds = None
        self._project = None
        self._query = ""
        self._projects: list[str] = []
        self._auto_pages = 0
        self._loaded = False

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        # filter bar
        bar = Adw.WrapBox(child_spacing=8, line_spacing=8)
        bar.set_margin_top(12)
        bar.set_margin_bottom(6)
        bar.set_margin_start(18)
        bar.set_margin_end(18)
        self.kind_dd = Gtk.DropDown.new_from_strings([k for k, _ in KIND_FILTERS])
        self.kind_dd.set_tooltip_text("Filter by kind")
        self.kind_dd.connect("notify::selected", self._on_kind)
        bar.append(self.kind_dd)
        self.proj_list = Gtk.StringList.new(["All projects"])
        self.proj_dd = Gtk.DropDown(model=self.proj_list)
        self.proj_dd.set_tooltip_text("Filter by project")
        self.proj_dd.connect("notify::selected", self._on_project)
        bar.append(self.proj_dd)
        self.search = Gtk.SearchEntry(placeholder_text="Filter loaded activity…", hexpand=True)
        self.search.set_size_request(220, -1)
        self.search.set_search_delay(250)
        self.search.connect("search-changed", self._on_search)
        bar.append(self.search)
        clamp_bar = Adw.Clamp(maximum_size=1180)
        clamp_bar.set_child(bar)
        box.append(clamp_bar)

        self.sw = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        # Overlay scrollbars fade in/out (≈2 s of 60 fps repainting) every time
        # live events change the list height; a classic scrollbar costs nothing.
        self.sw.set_overlay_scrolling(False)
        cs = Adw.ClampScrollable(maximum_size=1180)
        self.lv.set_margin_start(12)
        self.lv.set_margin_end(12)
        cs.set_child(self.lv)
        self.sw.set_child(cs)
        self.sw.connect("edge-reached", self._on_edge)

        self.empty = Adw.StatusPage(icon_name="cm-timeline-symbolic", title="No Activity",
                                    description="Nothing matches the current filters.")
        self.empty.add_css_class("compact")
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, vexpand=True)
        self.stack.add_named(self.sw, "list")
        self.stack.add_named(self.empty, "empty")
        spinner_box = Gtk.Box(halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        spinner_box.append(Adw.Spinner(width_request=32, height_request=32))
        self.stack.add_named(spinner_box, "loading")
        self.stack.set_visible_child_name("loading")
        box.append(self.stack)
        self.footer = label("", "caption", "cm-muted", xalign=0.5)
        self.footer.set_margin_top(4)
        self.footer.set_margin_bottom(8)
        box.append(self.footer)

        tv = Adw.ToolbarView()
        hb = Adw.HeaderBar()
        refresh = Gtk.Button(icon_name="view-refresh-symbolic", tooltip_text="Reload")
        refresh.connect("clicked", lambda *_: self.reload())
        hb.pack_end(refresh)
        tv.add_top_bar(hb)
        tv.set_content(box)
        page = Adw.NavigationPage(title=self.title, tag="root")
        page.set_child(tv)
        self.nav.add(page)

    # ---------------------------------------------------------------- data
    def on_shown(self) -> None:
        if not self._loaded:
            self.reload()

    def on_available(self, available: bool) -> None:
        if available and self._loaded:
            self.reload()

    def reload(self) -> None:
        if not self.win.client.available:
            self._loaded = True  # on_available() reloads once the service appears
            return
        self.store.remove_all()
        self._ids.clear()
        self._oldest = 0
        self._exhausted = False
        self._auto_pages = 0
        self._loaded = True
        self.stack.set_visible_child_name("loading")
        self._load_more()

    def _load_more(self) -> None:
        if self._loading or self._exhausted:
            return
        self._loading = True
        set_text_safe(self.footer, "Loading…")
        self.win.client.get_timeline(self._oldest, PAGE_SIZE, self._on_page)

    def _on_page(self, data, err) -> None:
        self._loading = False
        if err is not None:
            self.win.toast(f"Could not load timeline: {err}")
            set_text_safe(self.footer, "")
            self._refresh_state()
            return
        evs = (data or {}).get("events") or []
        if len(evs) < PAGE_SIZE:
            self._exhausted = True
        items = []
        for ev in evs:
            eid = ev.get("id")
            if eid in self._ids:
                continue
            self._ids.add(eid)
            items.append(EventItem(ev))
            self._note_project(ev.get("project"))
            if isinstance(eid, int) and (self._oldest == 0 or eid < self._oldest):
                self._oldest = eid
        if items:
            self.store.splice(self.store.get_n_items(), 0, items)
        self._refresh_state()
        # keep filling if filters hide most rows and the list cannot scroll yet
        if not self._exhausted and self.fmodel.get_n_items() < 40 and self._auto_pages < 8:
            self._auto_pages += 1
            GLib.idle_add(lambda: (self._load_more(), False)[1])

    def _refresh_state(self) -> None:
        n = self.fmodel.get_n_items()
        self.stack.set_visible_child_name("list" if n else "empty")
        total = self.store.get_n_items()
        if self._exhausted:
            set_text_safe(self.footer, f"{n} of {total} events shown · beginning of history")
        else:
            set_text_safe(self.footer, f"{n} of {total} loaded events shown · scroll for more")

    def _on_edge(self, _sw, pos) -> None:
        if pos == Gtk.PositionType.BOTTOM:
            self._auto_pages = 0
            self._load_more()

    def on_events(self, events: list[dict]) -> None:
        if not self._loaded:
            return
        items = []
        for ev in events:  # oldest first
            eid = ev.get("id")
            if eid in self._ids:
                continue
            self._ids.add(eid)
            self._note_project(ev.get("project"))
            items.append(EventItem(ev))
        if not items:
            return
        items.reverse()
        self.store.splice(0, 0, items)
        extra = self.store.get_n_items() - MAX_ITEMS
        if extra > 0:
            for i in range(self.store.get_n_items() - extra, self.store.get_n_items()):
                it = self.store.get_item(i)
                self._ids.discard(it.ev.get("id"))
            self.store.splice(self.store.get_n_items() - extra, extra, [])
            self._exhausted = False
            last = self.store.get_item(self.store.get_n_items() - 1)
            self._oldest = last.ev.get("id") or 0
        self._refresh_state()

    # -------------------------------------------------------------- filters
    def _note_project(self, proj: str | None) -> None:
        if proj and proj not in self._projects:
            self._projects.append(proj)
            self.proj_list.append(proj)

    def _match(self, item: EventItem) -> bool:
        ev = item.ev
        if self._kinds is not None:
            kind = "error" if ev.get("is_error") else ev.get("kind")
            if kind not in self._kinds:
                return False
        if self._project and ev.get("project") != self._project:
            return False
        if self._query:
            hay = f"{ev.get('tool') or ''} {ev.get('summary') or ''} {ev.get('detail') or ''} {ev.get('project') or ''}".lower()
            if self._query not in hay:
                return False
        return True

    def _changed(self) -> None:
        self.filter.changed(Gtk.FilterChange.DIFFERENT)
        self._auto_pages = 0
        self._refresh_state()
        if not self._exhausted and self.fmodel.get_n_items() < 40:
            self._load_more()

    def _on_kind(self, dd, _p) -> None:
        self._kinds = KIND_FILTERS[dd.get_selected()][1]
        self._changed()

    def _on_project(self, dd, _p) -> None:
        i = dd.get_selected()
        self._project = None if i == 0 else self.proj_list.get_string(i)
        self._changed()

    def _on_search(self, entry) -> None:
        self._query = entry.get_text().strip().lower()
        self._changed()


def set_text_safe(lbl: Gtk.Label, text: str) -> None:
    if lbl.get_label() != text:
        lbl.set_label(text)
