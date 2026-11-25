"""Live sessions list and per-session live detail view."""

from __future__ import annotations

from gi.repository import Adw, Gtk

from ...common import fmt
from ..widgets import (STATUS_ORDER, STATUS_RGB, AnimatedFeed, Sparkline, StatusDot,
                       StatusPill, card, chip, empty_state, event_icon, label, section_title,
                       set_text)
from ..window import Page


class SessionRow(Gtk.ListBoxRow):
    def __init__(self, sid: str) -> None:
        super().__init__(activatable=True)
        self.session_id = sid
        self.status = "unknown"
        self.started_at = 0
        box = Gtk.Box(spacing=14)
        box.set_margin_top(12)
        box.set_margin_bottom(12)
        box.set_margin_start(14)
        box.set_margin_end(10)
        self.dot = StatusDot()
        box.append(self.dot)
        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3, hexpand=True)
        top = Gtk.Box(spacing=8)
        self.project = label("", "heading", ellipsize=True)
        top.append(self.project)
        self.branch = chip("")
        top.append(self.branch)
        self.agents = chip("", accent=True)
        top.append(self.agents)
        col.append(top)
        self.title = label("", "cm-muted", ellipsize=True)
        col.append(self.title)
        self.current = label("", "cm-mono", "caption", ellipsize=True)
        col.append(self.current)
        box.append(col)
        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, halign=Gtk.Align.END, valign=Gtk.Align.CENTER)
        self.pill = StatusPill()
        self.pill.set_halign(Gtk.Align.END)
        right.append(self.pill)
        self.metrics = label("", "caption", "cm-muted", "cm-tnum", xalign=1, ellipsize=True)
        right.append(self.metrics)
        self.since = label("", "caption", "cm-muted", "cm-tnum", xalign=1, ellipsize=True)
        right.append(self.since)
        box.append(right)
        box.append(Gtk.Image.new_from_icon_name("go-next-symbolic"))
        self.set_child(box)
        self._since = None

    def update(self, s: dict) -> None:
        self.status = s.get("status") or "unknown"
        self.started_at = s.get("started_at") or 0
        self.dot.set_status(self.status)
        self.pill.set_status(self.status)
        set_text(self.project, s.get("project") or s.get("name") or "session")
        br = s.get("git_branch")
        self.branch.set_visible(bool(br))
        set_text(self.branch, br or "")
        n = sum(1 for a in s.get("agents") or [] if a.get("status") == "running")
        self.agents.set_visible(n > 0)
        set_text(self.agents, f"{n} agent{'s' if n != 1 else ''} running")
        t = s.get("title") or s.get("cwd") or ""
        set_text(self.title, t)
        cur = s.get("current")
        if cur and self.status != "idle":
            set_text(self.current, f"{cur.get('tool') or ''} · {cur.get('summary') or ''}")
        else:
            set_text(self.current, {"idle": "Ready for input", "busy": "No tool running"}.get(self.status, "—"))
        cpu = s.get("cpu_percent")
        set_text(self.metrics, f"CPU {fmt.percent(cpu, 1) if cpu is not None else '—'} · "
                               f"{fmt.bytes_(s.get('rss_bytes'))} · {fmt.tokens(fmt.total_tokens(s.get('tokens')))} tok")
        self._since = s.get("status_since")
        self.tick()

    def tick(self) -> None:
        if self._since:
            set_text(self.since, f"for {fmt.duration(fmt.now_ms() - self._since)}")


class AgentRow(Gtk.Box):
    def __init__(self, nested: bool) -> None:
        super().__init__(spacing=0)
        self.add_css_class("cm-agent-row")
        if nested:
            line = Gtk.Box()
            line.add_css_class("cm-tree-line")
            self.append(line)
        inner = Gtk.Box(spacing=10, hexpand=True)
        self.dot = StatusDot(small=True)
        inner.append(self.dot)
        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True)
        top = Gtk.Box(spacing=8)
        self.name = label("", "heading", ellipsize=True)
        top.append(self.name)
        self.type = chip("")
        top.append(self.type)
        self.model = chip("")
        top.append(self.model)
        col.append(top)
        self.current = label("", "caption", "cm-mono", "cm-muted", ellipsize=True)
        col.append(self.current)
        inner.append(col)
        self.meta = label("", "caption", "cm-muted", "cm-tnum", xalign=1, ellipsize=True)
        inner.append(self.meta)
        self.append(inner)

    def update_main(self, s: dict) -> None:
        status = s.get("status") or "unknown"
        self.dot.set_status(status)
        set_text(self.name, "Main agent")
        self.type.set_visible(False)
        m = s.get("model")
        self.model.set_visible(bool(m))
        set_text(self.model, m or "")
        cur = s.get("current")
        set_text(self.current, f"{cur.get('tool')} · {cur.get('summary') or ''}" if cur and status != "idle"
                 else fmt.status_label(status))
        set_text(self.meta, f"{s.get('tool_calls', 0)} tool calls")

    def update_agent(self, a: dict) -> None:
        st = a.get("status") or "unknown"
        self.dot.set_status(st)
        set_text(self.name, a.get("description") or a.get("agent_id") or "agent")
        self.type.set_visible(bool(a.get("type")))
        set_text(self.type, a.get("type") or "")
        self.model.set_visible(bool(a.get("model")))
        set_text(self.model, a.get("model") or "")
        cur = a.get("current")
        if st == "running" and cur:
            set_text(self.current, f"{cur.get('tool')} · {cur.get('summary') or ''}")
        else:
            set_text(self.current, "Finished" if st == "done" else fmt.status_label(st))
        dur = ""
        if a.get("started_at"):
            end = fmt.now_ms() if st == "running" else (a.get("last_activity_at") or a["started_at"])
            dur = " · " + fmt.duration(end - a["started_at"])
        set_text(self.meta, f"{a.get('tool_calls', 0)} calls{dur}")


class SessionDetail(Adw.NavigationPage):
    def __init__(self, page: "SessionsPage", sid: str) -> None:
        super().__init__(title="Session", tag="detail")
        self.page = page
        self.win = page.win
        self.session_id = sid
        self.session: dict | None = None
        self._loading_older = False

        tv = Adw.ToolbarView()
        hb = Adw.HeaderBar()
        self.wtitle = Adw.WindowTitle(title="Session", subtitle="")
        hb.set_title_widget(self.wtitle)
        tv.add_top_bar(hb)
        self.ended_banner = Adw.Banner(title="This session has ended.", button_label="Open in History")
        self.ended_banner.connect("button-clicked", lambda *_: self.win.open_session(self.session_id, live=False))
        tv.add_top_bar(self.ended_banner)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        # header card
        hcard = card()
        top = Gtk.Box(spacing=10)
        self.pill = StatusPill()
        top.append(self.pill)
        self.proj = label("", "title-3", ellipsize=True)
        self.proj.set_hexpand(True)
        top.append(self.proj)
        self.since = label("", "cm-muted", "cm-tnum", ellipsize=True)
        top.append(self.since)
        hcard.append(top)
        self.cwd = label("", "cm-mono", "cm-muted", ellipsize=True, selectable=True)
        self.cwd.set_margin_top(6)
        hcard.append(self.cwd)
        chips = Gtk.Box(spacing=6)
        chips.set_margin_top(8)
        self.c_branch = chip("")
        self.c_model = chip("", accent=True)
        self.c_ver = chip("")
        self.c_pid = chip("")
        self.c_started = chip("")
        for c in (self.c_model, self.c_branch, self.c_ver, self.c_pid, self.c_started):
            chips.append(c)
        hcard.append(chips)
        root.append(hcard)

        # current activity
        self.cur_card = card()
        cur = Gtk.Box(spacing=12)
        icon_box = Gtk.Box(valign=Gtk.Align.CENTER, halign=Gtk.Align.START)
        icon_box.set_hexpand(False)
        icon_box.add_css_class("cm-feed-icon")
        icon_box.add_css_class("k-tool")
        self.cur_icon = Gtk.Image(hexpand=True, halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        icon_box.append(self.cur_icon)
        cur.append(icon_box)
        ccol = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True)
        ccol.append(label("CURRENTLY", "cm-eyebrow"))
        self.cur_text = label("", "cm-mono", wrap=True, selectable=True)
        ccol.append(self.cur_text)
        cur.append(ccol)
        self.cur_when = label("", "caption", "cm-muted", "cm-tnum")
        cur.append(self.cur_when)
        self.cur_card.append(cur)
        root.append(self.cur_card)

        # metrics
        mflow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=True,
                            min_children_per_line=1, max_children_per_line=3, column_spacing=12, row_spacing=12)
        mflow.add_css_class("cm-grid")
        self.cpu_val, self.cpu_spark, cpu_card = self._metric_card("CPU", "cm-cpu-symbolic", STATUS_RGB["busy"])
        self.mem_val, self.mem_spark, mem_card = self._metric_card("Memory", "cm-memory-symbolic", (0.57, 0.25, 0.67))
        self.tok_val, tok_card = self._value_card("Tokens", "cm-token-symbolic")
        self.tok_sub = label("", "caption", "cm-muted", wrap=True)
        self.tok_sub.set_max_width_chars(28)
        tok_card.append(self.tok_sub)
        for c in (cpu_card, mem_card, tok_card):
            c.set_size_request(220, -1)
            mflow.append(c)
        root.append(mflow)
        self.counters = label("", "cm-muted", "cm-tnum", wrap=True)
        root.append(self.counters)

        # agents
        root.append(section_title("Agents"))
        self.agent_card = card()
        self.agent_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.agent_card.append(self.agent_box)
        self.main_row = AgentRow(nested=False)
        self.agent_box.append(self.main_row)
        self._agent_rows: dict[str, AgentRow] = {}
        self.agent_note = label("Per-agent CPU and memory are not measurable: subagents run inside the session's process.",
                                "caption", "cm-faint", wrap=True)
        self.agent_note.set_margin_top(6)
        self.agent_card.append(self.agent_note)
        root.append(self.agent_card)

        # activity feed
        fh = Gtk.Box(spacing=8)
        fh.append(section_title("Live activity"))
        root.append(fh)
        feed_card = card()
        feed_card.set_margin_bottom(4)
        self.feed = AnimatedFeed(cap=400, show_project=False, empty_text="Waiting for activity…")
        feed_card.append(self.feed)
        self.older = Gtk.Button(label="Load older activity", css_classes=["flat"], halign=Gtk.Align.CENTER)
        self.older.connect("clicked", lambda *_: self._load_older())
        feed_card.append(self.older)
        root.append(feed_card)

        self.body = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        self.body.add_named(Page.wrap(root), "content")
        missing = empty_state("cm-session-symbolic", "Session Not Running",
                              "This session is not live on this machine. Its recorded activity is in History.")
        btn = Gtk.Button(label="Open in History", halign=Gtk.Align.CENTER, css_classes=["pill", "suggested-action"])
        btn.connect("clicked", lambda *_: self.win.open_session(self.session_id, live=False))
        missing.set_child(btn)
        self.body.add_named(missing, "missing")
        tv.set_content(self.body)
        self.set_child(tv)
        self.win.client.get_session_events(sid, 0, 80, self._on_initial_events)

    @staticmethod
    def _metric_card(title: str, icon: str, color):
        c = card(hover=True, compact=True)
        head = Gtk.Box(spacing=6)
        img = Gtk.Image.new_from_icon_name(icon)
        img.add_css_class("cm-muted")
        head.append(img)
        head.append(label(title.upper(), "cm-eyebrow"))
        head.append(Gtk.Box(hexpand=True))
        val = label("—", "cm-mid-number")
        head.append(val)
        c.append(head)
        spark = Sparkline(color=color)
        spark.set_margin_top(6)
        c.append(spark)
        return val, spark, c

    @staticmethod
    def _value_card(title: str, icon: str):
        c = card(hover=True, compact=True)
        head = Gtk.Box(spacing=6)
        img = Gtk.Image.new_from_icon_name(icon)
        img.add_css_class("cm-muted")
        head.append(img)
        head.append(label(title.upper(), "cm-eyebrow"))
        c.append(head)
        val = label("—", "cm-big-number")
        c.append(val)
        return val, c

    # ------------------------------------------------------------ updates
    def update(self, s: dict | None) -> None:
        if s is None:
            if self.session:
                self.ended_banner.set_revealed(True)
                self.pill.set_status("done")
                set_text(self.since, "Ended")
            else:
                self.body.set_visible_child_name("missing")
            return
        self.body.set_visible_child_name("content")
        self.ended_banner.set_revealed(False)
        self.session = s
        status = s.get("status") or "unknown"
        self.wtitle.set_title(s.get("project") or "Session")
        self.wtitle.set_subtitle(s.get("title") or s.get("name") or "")
        self.pill.set_status(status)
        set_text(self.proj, s.get("title") or s.get("project") or "")
        set_text(self.cwd, s.get("cwd") or "")
        for c, v, pre in ((self.c_branch, s.get("git_branch"), "⎇ "), (self.c_model, s.get("model"), ""),
                          (self.c_ver, s.get("version"), "v"), (self.c_pid, s.get("pid"), "PID "),
                          (self.c_started, fmt.relative(s["started_at"]) if s.get("started_at") else None, "started ")):
            c.set_visible(v is not None and v != "")
            set_text(c, f"{pre}{v}" if v is not None else "")

        cur = s.get("current")
        if cur and status != "idle":
            self.cur_icon.set_from_icon_name(event_icon({"kind": "tool", "tool": cur.get("tool")}))
            set_text(self.cur_text, f"{cur.get('tool') or ''}  {cur.get('summary') or ''}")
            self._cur_at = cur.get("at")
        else:
            self.cur_icon.set_from_icon_name("cm-check-symbolic" if status == "idle" else "cm-pulse-symbolic")
            set_text(self.cur_text, {"idle": "Ready for input", "busy": "No tool running"}.get(status, "—"))
            self._cur_at = None

        cpu = s.get("cpu_percent")
        set_text(self.cpu_val, fmt.percent(cpu, 1) if cpu is not None else "—")
        set_text(self.mem_val, fmt.bytes_(s.get("rss_bytes")))
        series = self.win.series.get(self.session_id) or []
        self.cpu_spark.set_data([p[1] for p in series])
        self.mem_spark.set_data([p[2] for p in series])
        tok = s.get("tokens") or {}
        set_text(self.tok_val, fmt.tokens(fmt.total_tokens(tok)))
        set_text(self.tok_sub, f"in {fmt.tokens(tok.get('input'))} · out {fmt.tokens(tok.get('output'))} · "
                               f"cache read {fmt.tokens(tok.get('cache_read'))} · write {fmt.tokens(tok.get('cache_create'))}")
        ctx = s.get("context_percent")
        parts = [f"{s.get('tool_calls', 0)} tool calls", f"{s.get('errors', 0)} errors",
                 f"{s.get('proc_count', 0)} processes"]
        if ctx is not None:
            parts.append(f"context {fmt.percent(ctx)} used")
        set_text(self.counters, "  ·  ".join(parts))

        self.main_row.update_main(s)
        agents = s.get("agents") or []
        seen = set()
        for a in agents:
            aid = a.get("agent_id")
            seen.add(aid)
            row = self._agent_rows.get(aid)
            if row is None:
                row = AgentRow(nested=True)
                self._agent_rows[aid] = row
                self.agent_box.append(row)
            row.update_agent(a)
        for aid in list(self._agent_rows):
            if aid not in seen:
                self.agent_box.remove(self._agent_rows.pop(aid))
        self.agent_note.set_visible(bool(agents))
        self.tick()

    def tick(self) -> None:
        s = self.session
        if s and s.get("status_since"):
            set_text(self.since, f"{fmt.status_label(s.get('status'))} for "
                                 f"{fmt.duration(fmt.now_ms() - s['status_since'])}")
        at = getattr(self, "_cur_at", None)
        set_text(self.cur_when, fmt.relative(at) if at else "")

    def add_events(self, events: list[dict]) -> None:
        mine = [e for e in events if e.get("session_id") == self.session_id]
        if mine:
            self.feed.prepend_events(mine, animate=True)

    def _on_initial_events(self, data, err) -> None:
        if err is not None:
            self.win.toast(f"Could not load activity: {err}")
            return
        evs = (data or {}).get("events") or []
        self.feed.append_events(evs)
        self.older.set_visible(len(evs) >= 80)

    def _load_older(self) -> None:
        if self._loading_older:
            return
        self._loading_older = True
        before = self.feed.oldest_id
        self.win.client.get_session_events(self.session_id, before, 100, self._on_older)

    def _on_older(self, data, err) -> None:
        self._loading_older = False
        if err is not None:
            self.win.toast(f"Could not load activity: {err}")
            return
        evs = (data or {}).get("events") or []
        self.feed.append_events(evs)
        self.older.set_visible(len(evs) >= 100)


class SessionsPage(Page):
    title = "Sessions"

    def __init__(self, win) -> None:
        super().__init__(win)
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        root.append(section_title("Live sessions"))
        root.append(label("Every running Claude Code session on this machine, across all terminals and projects.",
                          "cm-muted", wrap=True))
        self.list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.list.add_css_class("boxed-list")
        self.list.set_sort_func(self._sort)
        self.list.connect("row-activated", lambda _l, row: self.open_detail(row.session_id))
        self.empty = empty_state("cm-session-symbolic", "No Active Sessions",
                                 "Sessions appear here as soon as Claude Code starts.")
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        self.stack.add_named(self.list, "list")
        self.stack.add_named(self.empty, "empty")
        root.append(self.stack)
        self.root_page(root)
        self._rows: dict[str, SessionRow] = {}
        self.detail: SessionDetail | None = None
        self.nav.connect("popped", self._on_popped)

    def _on_popped(self, _nav, page) -> None:
        if page is self.detail:
            self.detail = None

    @staticmethod
    def _sort(a, b) -> int:
        ka = (STATUS_ORDER.get(a.status, 9), -(a.started_at or 0))
        kb = (STATUS_ORDER.get(b.status, 9), -(b.started_at or 0))
        return (ka > kb) - (ka < kb)

    def open_detail(self, sid: str) -> None:
        if self.detail is not None and self.detail.session_id == sid:
            return
        if self.detail is not None:
            self.nav.pop_to_tag("root")
        self.detail = SessionDetail(self, sid)
        snap = self.win.snapshot or {}
        s = next((x for x in snap.get("sessions") or [] if x.get("session_id") == sid), None)
        self.detail.update(s)
        self.nav.push(self.detail)

    def on_snapshot(self, snap: dict) -> None:
        sessions = snap.get("sessions") or []
        seen = set()
        resort = False
        for s in sessions:
            sid = s.get("session_id")
            if not sid:
                continue
            seen.add(sid)
            row = self._rows.get(sid)
            if row is None:
                row = SessionRow(sid)
                self._rows[sid] = row
                self.list.append(row)
                resort = True
            old = row.status
            row.update(s)
            resort |= old != row.status
        for sid in list(self._rows):
            if sid not in seen:
                self.list.remove(self._rows.pop(sid))
        if resort:
            self.list.invalidate_sort()
        self.stack.set_visible_child_name("list" if self._rows else "empty")
        if self.detail is not None:
            s = next((x for x in sessions if x.get("session_id") == self.detail.session_id), None)
            self.detail.update(s)

    def on_events(self, events: list[dict]) -> None:
        if self.detail is not None:
            self.detail.add_events(events)

    def tick(self) -> None:
        for r in self._rows.values():
            r.tick()
        if self.detail is not None:
            self.detail.tick()
