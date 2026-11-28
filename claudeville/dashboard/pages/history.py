"""History: searchable list of past sessions and a session inspector."""

from __future__ import annotations

from gi.repository import Adw, GObject, Gio, Gtk

from ...common import fmt
from ..charts import HBarChart
from ..widgets import (AnimatedFeed, StatTile, card, chip, empty_state, label, section_title,
                       set_text)
from ..window import Page
from .sessions import AgentRow

PAGE_SIZE = 60


class HistoryObj(GObject.Object):
    __gtype_name__ = "CMHistoryItem"

    def __init__(self, item: dict) -> None:
        super().__init__()
        self.item = item


class HistoryRow(Gtk.Box):
    def __init__(self) -> None:
        super().__init__(spacing=14, hexpand=True)
        self.add_css_class("cm-feed-row")
        self.set_margin_top(2)
        self.set_margin_bottom(2)
        icon_box = Gtk.Box(valign=Gtk.Align.CENTER, halign=Gtk.Align.START)
        icon_box.set_hexpand(False)
        icon_box.add_css_class("cm-feed-icon")
        icon_box.add_css_class("k-prompt")
        icon_box.append(Gtk.Image(icon_name="cm-session-symbolic", hexpand=True,
                                  halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER))
        self.append(icon_box)
        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3, hexpand=True)
        top = Gtk.Box(spacing=8)
        self.title = label("", "heading", ellipsize=True)
        top.append(self.title)
        self.project = chip("", accent=True)
        top.append(self.project)
        self.live = chip("LIVE")
        self.live.add_css_class("cm-pill")
        self.live.add_css_class("st-busy")
        top.append(self.live)
        col.append(top)
        self.meta = label("", "caption", "cm-muted", "cm-tnum", ellipsize=True)
        col.append(self.meta)
        self.append(col)
        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, valign=Gtk.Align.CENTER)
        self.when = label("", "caption", "cm-tnum", xalign=1)
        right.append(self.when)
        self.dur = label("", "caption", "cm-muted", "cm-tnum", xalign=1)
        right.append(self.dur)
        self.append(right)
        self.append(Gtk.Image(icon_name="go-next-symbolic", valign=Gtk.Align.CENTER))

    def bind(self, h: dict) -> None:
        set_text(self.title, h.get("title") or "Untitled session")
        set_text(self.project, h.get("project") or "")
        self.live.set_visible(bool(h.get("live")))
        errs = h.get("errors") or 0
        parts = [f"{h.get('tool_calls', 0)} tool calls",
                 f"{fmt.tokens(fmt.total_tokens(h.get('tokens')))} tokens"]
        if h.get("agent_count"):
            parts.append(f"{h['agent_count']} agents")
        if errs:
            parts.append(f"{errs} error{'s' if errs != 1 else ''}")
        if h.get("model"):
            parts.append(h["model"])
        set_text(self.meta, "  ·  ".join(parts))
        set_text(self.when, fmt.date_label(h.get("started_at")))
        set_text(self.dur, fmt.duration(h.get("duration_ms")) if h.get("duration_ms") is not None else
                 ("running" if h.get("live") else "—"))


class HistoryDetail(Adw.NavigationPage):
    def __init__(self, page: "HistoryPage", sid: str) -> None:
        super().__init__(title="Session", tag="detail")
        self.win = page.win
        self.session_id = sid
        self._loading = False
        tv = Adw.ToolbarView()
        hb = Adw.HeaderBar()
        self.wtitle = Adw.WindowTitle(title="Session", subtitle="")
        hb.set_title_widget(self.wtitle)
        self.live_btn = Gtk.Button(label="Live View", css_classes=["suggested-action"], visible=False)
        self.live_btn.connect("clicked", lambda *_: self.win.open_session(sid, live=True))
        hb.pack_end(self.live_btn)
        tv.add_top_bar(hb)

        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        sp = Gtk.Box(halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        sp.append(Adw.Spinner(width_request=32, height_request=32))
        self.stack.add_named(sp, "loading")
        self.stack.add_named(empty_state("dialog-warning-symbolic", "Session Not Found",
                                         "This session is no longer in the local history."), "missing")

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        hcard = card()
        self.h_title = label("", "title-2", wrap=True)
        hcard.append(self.h_title)
        self.h_cwd = label("", "cm-mono", "cm-muted", ellipsize=True, selectable=True)
        self.h_cwd.set_margin_top(4)
        hcard.append(self.h_cwd)
        self.h_when = label("", "cm-muted", "cm-tnum", wrap=True)
        self.h_when.set_margin_top(6)
        hcard.append(self.h_when)
        root.append(hcard)

        tiles = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=True,
                            min_children_per_line=2, max_children_per_line=4, column_spacing=12, row_spacing=12)
        tiles.add_css_class("cm-grid")
        self.t_tok = StatTile("Tokens", "cm-token-symbolic")
        self.t_tools = StatTile("Tool calls", "utilities-terminal-symbolic")
        self.t_err = StatTile("Errors", "dialog-error-symbolic")
        self.t_agents = StatTile("Agents", "cm-agent-symbolic")
        for t in (self.t_tok, self.t_tools, self.t_err, self.t_agents):
            t.set_size_request(130, -1)
            tiles.append(t)
        root.append(tiles)

        two = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=True,
                          min_children_per_line=1, max_children_per_line=2, column_spacing=14, row_spacing=14)
        two.add_css_class("cm-grid")
        tc = card()
        tc.append(label("TOOLS USED", "cm-eyebrow"))
        self.tool_chart = HBarChart(max_rows=12)
        self.tool_chart.set_margin_top(8)
        tc.append(self.tool_chart)
        tc.set_size_request(290, -1)
        two.append(tc)
        fc = card()
        fc.append(label("FILES TOUCHED", "cm-eyebrow"))
        self.files_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.files_box.set_margin_top(8)
        fc.append(self.files_box)
        fc.set_size_request(290, -1)
        two.append(fc)
        root.append(two)

        self.agents_title = section_title("Agents")
        root.append(self.agents_title)
        self.agents_card = card()
        self.agents_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.agents_card.append(self.agents_box)
        root.append(self.agents_card)

        root.append(section_title("Activity"))
        feed_card = card()
        self.feed = AnimatedFeed(cap=2000, show_project=False, empty_text="No activity recorded for this session")
        feed_card.append(self.feed)
        self.more = Gtk.Button(label="Load more", css_classes=["flat"], halign=Gtk.Align.CENTER)
        self.more.connect("clicked", lambda *_: self._load_events())
        feed_card.append(self.more)
        root.append(feed_card)

        self.stack.add_named(Page.wrap(root), "content")
        tv.set_content(self.stack)
        self.set_child(tv)
        self.win.client.get_session(sid, self._on_detail)
        self._load_events()

    def _on_detail(self, d, err) -> None:
        if err is not None:
            self.win.toast(f"Could not load session: {err}")
            self.stack.set_visible_child_name("missing")
            return
        if not d or d.get("error"):
            self.stack.set_visible_child_name("missing")
            return
        self.wtitle.set_title(d.get("project") or "Session")
        self.wtitle.set_subtitle(fmt.date_label(d.get("started_at")))
        self.live_btn.set_visible(bool(d.get("live")))
        set_text(self.h_title, d.get("title") or "Untitled session")
        set_text(self.h_cwd, d.get("cwd") or "")
        when = [f"Started {fmt.clock(d.get('started_at'), with_date=True)}"]
        if d.get("ended_at"):
            when.append(f"ended {fmt.clock(d['ended_at'], with_date=True)}")
        if d.get("duration_ms") is not None:
            when.append(f"duration {fmt.duration(d['duration_ms'], short=False)}")
        if d.get("model"):
            when.append(d["model"])
        set_text(self.h_when, "  ·  ".join(when))
        tok = d.get("tokens") or {}
        self.t_tok.update(fmt.tokens(fmt.total_tokens(tok)), f"{fmt.tokens(tok.get('output'))} output")
        self.t_tools.update(str(d.get("tool_calls", 0)))
        self.t_err.update(str(d.get("errors", 0)))
        self.t_agents.update(str(d.get("agent_count", 0)))
        counts = sorted((d.get("tool_counts") or {}).items(), key=lambda kv: -kv[1])
        self.tool_chart.set_data([(k, float(v), str(v)) for k, v in counts])
        files = d.get("files_touched") or []
        cwd = (d.get("cwd") or "").rstrip("/") + "/"
        if not files:
            self.files_box.append(label("No file operations recorded", "cm-muted"))
        for f in files[:50]:
            row = Gtk.Box(spacing=8)
            path = f.get("path") or ""
            short = path[len(cwd):] if cwd != "/" and path.startswith(cwd) else path
            pl = label(fmt.ellipsize_middle(short, 70), "cm-mono", "caption", ellipsize=True)
            pl.set_hexpand(True)
            pl.set_tooltip_text(path)
            row.append(pl)
            row.append(label(f"×{f.get('count', 0)}", "caption", "cm-muted", "cm-tnum"))
            self.files_box.append(row)
        agents = d.get("agents") or []
        self.agents_title.set_visible(bool(agents))
        self.agents_card.set_visible(bool(agents))
        for a in agents:
            r = AgentRow(nested=True)
            r.update_agent(a)
            self.agents_box.append(r)
        self.stack.set_visible_child_name("content")

    def _load_events(self) -> None:
        if self._loading:
            return
        self._loading = True
        self.win.client.get_session_events(self.session_id, self.feed.oldest_id, 200, self._on_events)

    def _on_events(self, data, err) -> None:
        self._loading = False
        if err is not None:
            self.win.toast(f"Could not load activity: {err}")
            return
        evs = (data or {}).get("events") or []
        self.feed.append_events(evs)
        self.more.set_visible(len(evs) >= 200)


class HistoryPage(Page):
    title = "History"

    def __init__(self, win) -> None:
        super().__init__(win)
        self.store = Gio.ListStore(item_type=HistoryObj)
        factory = Gtk.SignalListItemFactory()
        factory.connect("setup", lambda _f, it: it.set_child(HistoryRow()))
        factory.connect("bind", lambda _f, it: it.get_child().bind(it.get_item().item))
        self.lv = Gtk.ListView(model=Gtk.NoSelection(model=self.store), factory=factory,
                               single_click_activate=True)
        self.lv.add_css_class("cm-list")
        self.lv.connect("activate", self._on_activate)
        self.lv.set_margin_start(12)
        self.lv.set_margin_end(12)
        self._query = ""
        self._offset = 0
        self._total = None
        self._loading = False
        self._gen = 0
        self._loaded = False

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        bar = Gtk.Box(spacing=8)
        bar.set_margin_top(12)
        bar.set_margin_bottom(6)
        bar.set_margin_start(18)
        bar.set_margin_end(18)
        self.search = Gtk.SearchEntry(placeholder_text="Search by project, title or folder…", hexpand=True)
        self.search.set_search_delay(300)
        self.search.connect("search-changed", self._on_search)
        bar.append(self.search)
        self.count = label("", "caption", "cm-muted", "cm-tnum")
        bar.append(self.count)
        cb = Adw.Clamp(maximum_size=1180)
        cb.set_child(bar)
        box.append(cb)

        self.sw = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        cs = Adw.ClampScrollable(maximum_size=1180)
        cs.set_child(self.lv)
        self.sw.set_child(cs)
        self.sw.connect("edge-reached", lambda _s, pos: pos == Gtk.PositionType.BOTTOM and self._load())
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, vexpand=True)
        self.stack.add_named(self.sw, "list")
        self.empty = empty_state("cm-history-symbolic", "No Sessions Found",
                                 "Completed Claude Code sessions are kept here for later inspection.")
        self.stack.add_named(self.empty, "empty")
        sp = Gtk.Box(halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        sp.append(Adw.Spinner(width_request=32, height_request=32))
        self.stack.add_named(sp, "loading")
        self.stack.set_visible_child_name("loading")
        box.append(self.stack)

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
        self._gen += 1
        self._loaded = True
        self._offset = 0
        self._total = None
        self._loading = False
        self.store.remove_all()
        self.stack.set_visible_child_name("loading")
        self._load()

    def _load(self) -> None:
        if self._loading or (self._total is not None and self._offset >= self._total):
            return
        self._loading = True
        gen = self._gen
        self.win.client.get_history(self._query, self._offset, PAGE_SIZE,
                                    lambda d, e: self._on_page(gen, d, e))

    def _on_page(self, gen, data, err) -> None:
        if gen != self._gen:
            return
        self._loading = False
        if err is not None:
            self.win.toast(f"Could not load history: {err}")
            self.stack.set_visible_child_name("empty")
            return
        items = (data or {}).get("sessions") or []
        self._total = (data or {}).get("total", len(items))
        self.store.splice(self.store.get_n_items(), 0, [HistoryObj(i) for i in items])
        self._offset += len(items)
        if not items:
            self._total = self._offset
        n = self.store.get_n_items()
        self.stack.set_visible_child_name("list" if n else "empty")
        set_text(self.count, f"{self._total} session{'s' if self._total != 1 else ''}")

    def _on_search(self, entry) -> None:
        self._query = entry.get_text().strip()
        self.reload()

    def _on_activate(self, _lv, pos) -> None:
        obj = self.store.get_item(pos)
        if obj is not None:
            self.open_detail(obj.item.get("session_id"))

    def open_detail(self, sid: str) -> None:
        vis = self.nav.get_visible_page()
        if isinstance(vis, HistoryDetail) and vis.session_id == sid:
            return
        self.nav.pop_to_tag("root")
        self.nav.push(HistoryDetail(self, sid))
        if not self._loaded:
            self.reload()
