"""Overview: plan limits, token counters, totals, live session grid."""

from __future__ import annotations

from gi.repository import Adw, Gtk

from ...common import fmt
from ..widgets import (STATUS_ORDER, SessionCard, StatTile, UsageCard, empty_state, label,
                       section_title, set_text)
from ..window import Page


class OverviewPage(Page):
    title = "Overview"

    def __init__(self, win) -> None:
        super().__init__(win)
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)

        self.banner = Adw.Banner(title="")
        self.banner.set_revealed(False)

        # --- plan limits
        head = Gtk.Box(spacing=8)
        head.append(section_title("Plan usage"))
        head.append(Gtk.Box(hexpand=True))
        self.usage_src = label("", "caption", "cm-muted", ellipsize=True, xalign=1)
        head.append(self.usage_src)
        root.append(head)

        self.usage_box = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=True,
                                     min_children_per_line=1, max_children_per_line=2,
                                     column_spacing=14, row_spacing=14)
        self.usage_box.add_css_class("cm-grid")
        self.five = UsageCard("Session window", "5-hour limit")
        self.week = UsageCard("Weekly window", "7-day limit")
        for c in (self.five, self.week):
            c.set_size_request(290, -1)
            self.usage_box.append(c)
        self.no_usage = self._build_no_usage()
        self.usage_stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE,
                                     vhomogeneous=False, interpolate_size=True)
        self.usage_stack.add_named(self.usage_box, "data")
        self.usage_stack.add_named(self.no_usage, "none")
        root.append(self.usage_stack)
        self.limit_hit = label("", "caption", "cm-muted", wrap=True)
        self.limit_hit.set_visible(False)
        root.append(self.limit_hit)

        # --- tokens + totals
        root.append(section_title("Right now"))
        self.tiles_flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=True,
                                      min_children_per_line=2, max_children_per_line=3,
                                      column_spacing=12, row_spacing=12)
        self.tiles_flow.add_css_class("cm-grid")
        self.t_tokens5 = StatTile("Tokens · 5 h", "cm-token-symbolic")
        self.t_today = StatTile("Tokens · today", "cm-token-symbolic")
        self.t_live = StatTile("Live sessions", "cm-session-symbolic")
        self.t_agents = StatTile("Agents running", "cm-agent-symbolic")
        self.t_cpu = StatTile("CPU", "cm-cpu-symbolic")
        self.t_mem = StatTile("Memory", "cm-memory-symbolic")
        for t in (self.t_tokens5, self.t_today, self.t_live, self.t_agents, self.t_cpu, self.t_mem):
            t.set_size_request(130, -1)
            self.tiles_flow.append(t)
        root.append(self.tiles_flow)

        # --- sessions grid
        sh = Gtk.Box(spacing=8)
        sh.append(section_title("Live sessions"))
        sh.append(Gtk.Box(hexpand=True))
        all_btn = Gtk.Button(label="All sessions", css_classes=["flat"])
        all_btn.connect("clicked", lambda *_: self.win.navigate("sessions"))
        sh.append(all_btn)
        root.append(sh)
        self.grid = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=True,
                                min_children_per_line=1, max_children_per_line=3,
                                column_spacing=12, row_spacing=12, activate_on_single_click=True)
        self.grid.add_css_class("cm-grid")
        self.grid.set_valign(Gtk.Align.START)
        self.grid.set_sort_func(self._sort)
        self.grid.connect("child-activated", self._on_card)
        self.empty = empty_state("cm-session-symbolic", "No Active Sessions",
                                 "Start Claude Code in any terminal — it appears here automatically.")
        self.grid_stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, vhomogeneous=False)
        self.grid_stack.add_named(self.grid, "grid")
        self.grid_stack.add_named(self.empty, "empty")
        root.append(self.grid_stack)
        self._cards: dict[str, tuple[Gtk.FlowBoxChild, SessionCard]] = {}

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        outer.append(self.banner)
        sw = self.wrap(root)
        sw.set_vexpand(True)
        outer.append(sw)
        tv = Adw.ToolbarView()
        tv.add_top_bar(Adw.HeaderBar())
        tv.set_content(outer)
        page = Adw.NavigationPage(title=self.title, tag="root")
        page.set_child(tv)
        self.nav.add(page)

    def _build_no_usage(self) -> Gtk.Widget:
        box = Gtk.Box(spacing=16)
        box.add_css_class("cm-card")
        box.add_css_class("cm-honest-card")
        img = Gtk.Image.new_from_icon_name("dialog-information-symbolic")
        img.set_pixel_size(32)
        img.add_css_class("cm-muted")
        img.set_valign(Gtk.Align.START)
        box.append(img)
        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, hexpand=True)
        col.append(label("Plan limits unavailable", "heading"))
        col.append(label(
            "Claude Code only shares 5-hour and weekly limit percentages with its status line. "
            "Enable the optional status-line integration to see them here. Nothing is estimated: "
            "until then, Claude Monitor shows only the exact token counts it reads from your local transcripts.",
            "cm-muted", wrap=True))
        box.append(col)
        return box

    # ------------------------------------------------------------- updates
    def on_snapshot(self, snap: dict) -> None:
        usage = snap.get("usage") or {}
        idx = (snap.get("daemon") or {}).get("indexing") or {}
        if idx.get("active"):
            self.banner.set_title(f"Indexing session history — {idx.get('files_done', 0)} of "
                                  f"{idx.get('files_total', 0)} transcripts. Statistics may be incomplete.")
            self.banner.set_revealed(True)
        else:
            self.banner.set_revealed(False)

        has = usage.get("source") not in (None, "none") and (usage.get("five_hour") or usage.get("seven_day"))
        if has:
            self.usage_stack.set_visible_child_name("data")
            self.five.update(usage.get("five_hour"), usage.get("as_of"))
            self.week.update(usage.get("seven_day"), usage.get("as_of"))
            set_text(self.usage_src, "Reported by Claude Code status line")
        else:
            self.usage_stack.set_visible_child_name("none")
            set_text(self.usage_src, "Integration installed — waiting for Claude Code to report"
                     if usage.get("statusline_installed") else "")
        hit = usage.get("last_limit_hit")
        if hit and hit.get("at"):
            kind = {"five_hour": "5-hour", "seven_day": "weekly"}.get(hit.get("type"), hit.get("type") or "")
            ra = hit.get("resets_at")
            reset = f" · resets in {fmt.countdown(ra)}" if ra and ra > fmt.now_ms() / 1000 else ""
            set_text(self.limit_hit, f"Last {kind} limit hit {fmt.relative(hit['at'])}{reset}")
            self.limit_hit.set_visible(True)
        else:
            self.limit_hit.set_visible(False)

        t5 = usage.get("tokens_5h")
        td = usage.get("tokens_today")
        self.t_tokens5.update(fmt.tokens(fmt.total_tokens(t5)),
                              f"{fmt.tokens((t5 or {}).get('output'))} output" if t5 else "")
        self.t_today.update(fmt.tokens(fmt.total_tokens(td)),
                            f"{fmt.tokens((td or {}).get('output'))} output" if td else "")
        tot = snap.get("totals") or {}
        live = tot.get("live")
        self.t_live.update(str(live) if live is not None else "—",
                           f"{tot.get('busy', 0)} working · {tot.get('waiting', 0)} waiting")
        self.t_agents.update(str(tot.get("agents_running", "—")), "subagents in progress")
        self.t_cpu.update(fmt.percent(tot.get("cpu_percent"), 1), "of one core, all sessions")
        self.t_mem.update(fmt.bytes_(tot.get("rss_bytes")), "resident, all sessions")
        self._update_cards(snap.get("sessions") or [])

    def _update_cards(self, sessions: list[dict]) -> None:
        seen = set()
        resort = False
        for s in sessions:
            sid = s.get("session_id")
            if not sid:
                continue
            seen.add(sid)
            entry = self._cards.get(sid)
            if entry is None:
                c = SessionCard(sid)
                child = Gtk.FlowBoxChild()
                child.set_child(c)
                self.grid.append(child)
                self._cards[sid] = (child, c)
                entry = (child, c)
                resort = True
            old = entry[1].status
            entry[1].update(s)
            if old != entry[1].status:
                resort = True
        for sid in list(self._cards):
            if sid not in seen:
                child, _ = self._cards.pop(sid)
                self.grid.remove(child)
        if resort:
            self.grid.invalidate_sort()
        self.grid_stack.set_visible_child_name("grid" if self._cards else "empty")

    @staticmethod
    def _sort(a: Gtk.FlowBoxChild, b: Gtk.FlowBoxChild) -> int:
        ca, cb = a.get_child(), b.get_child()
        ka = (STATUS_ORDER.get(ca.status, 9), -(ca.started_at or 0))
        kb = (STATUS_ORDER.get(cb.status, 9), -(cb.started_at or 0))
        return (ka > kb) - (ka < kb)

    def _on_card(self, _fb, child) -> None:
        self.win.open_session(child.get_child().session_id, live=True)

    def tick(self) -> None:
        if self.usage_stack.get_visible_child_name() == "data":
            self.five.tick()
            self.week.tick()
        for _child, c in self._cards.values():
            c.tick()
