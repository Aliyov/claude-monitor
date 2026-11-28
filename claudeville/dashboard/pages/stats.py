"""Statistics: token trends, tool usage, projects, models, hour-of-day activity."""

from __future__ import annotations

import time

from gi.repository import Adw, Gtk

from ...common import fmt
from ..charts import SERIES, HBarChart, HeatStrip, StackedBarChart
from ..widgets import STATUS_RGB, StatTile, card, label, set_text
from ..window import Page

RANGES = [("7", 7, "7 days"), ("30", 30, "30 days"), ("90", 90, "90 days")]
TOKEN_SERIES = [("output", "Output"), ("input", "Input"), ("cache_create", "Cache write"), ("cache_read", "Cache read")]


def _swatch(rgb) -> Gtk.DrawingArea:
    def draw(_a, cr, w, h):
        cr.set_source_rgb(*rgb)
        r = 3
        cr.new_sub_path()
        cr.arc(w - r, r, r, -1.5708, 0)
        cr.arc(w - r, h - r, r, 0, 1.5708)
        cr.arc(r, h - r, r, 1.5708, 3.1416)
        cr.arc(r, r, r, 3.1416, 4.7124)
        cr.close_path()
        cr.fill()
    da = Gtk.DrawingArea(content_width=10, content_height=10, valign=Gtk.Align.CENTER)
    da.set_draw_func(draw)
    return da


class StatsPage(Page):
    title = "Statistics"

    def __init__(self, win) -> None:
        super().__init__(win)
        self._days = 30
        self._data: dict | None = None
        self._loaded_at = 0.0
        self._include_cache_read = False

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)

        # summary tiles
        tiles = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=True,
                            min_children_per_line=2, max_children_per_line=4, column_spacing=12, row_spacing=12)
        tiles.add_css_class("cm-grid")
        self.t_tokens = StatTile("Total tokens", "cm-token-symbolic")
        self.t_output = StatTile("Output tokens", "cm-token-symbolic")
        self.t_sessions = StatTile("Sessions", "cm-session-symbolic")
        self.t_tools = StatTile("Tool calls", "utilities-terminal-symbolic")
        for t in (self.t_tokens, self.t_output, self.t_sessions, self.t_tools):
            t.set_size_request(130, -1)
            tiles.append(t)
        root.append(tiles)

        # daily tokens
        dc = card()
        head = Adw.WrapBox(child_spacing=12, line_spacing=8)
        title = label("DAILY TOKENS", "cm-eyebrow")
        title.set_hexpand(True)
        head.append(title)
        self.legend = Adw.WrapBox(child_spacing=12, line_spacing=4)
        head.append(self.legend)
        sw_box = Gtk.Box(spacing=6)
        sw_box.append(label("Cache reads", "caption", "cm-muted"))
        self.cache_switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        self.cache_switch.set_tooltip_text("Cache reads are usually far larger than other token types; "
                                           "include them to see true volume.")
        self.cache_switch.connect("notify::active", self._on_cache_toggle)
        sw_box.append(self.cache_switch)
        head.append(sw_box)
        dc.append(head)
        self.daily = StackedBarChart(height=240)
        self.daily.set_margin_top(10)
        dc.append(self.daily)
        root.append(dc)

        # tools + projects
        two = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=True,
                          min_children_per_line=1, max_children_per_line=2, column_spacing=14, row_spacing=14)
        two.add_css_class("cm-grid")
        tc = card()
        tc.append(label("TOOL USAGE", "cm-eyebrow"))
        self.tools = HBarChart(color=STATUS_RGB["busy"], max_rows=10)
        self.tools.set_margin_top(8)
        tc.append(self.tools)
        tc.set_size_request(300, -1)
        two.append(tc)
        pc = card()
        pc.append(label("PROJECTS · BY TOOL CALLS", "cm-eyebrow"))
        self.projects = HBarChart(color=SERIES[0], max_rows=10)
        self.projects.set_margin_top(8)
        pc.append(self.projects)
        pc.set_size_request(300, -1)
        two.append(pc)
        mc = card()
        mc.append(label("MODELS · TOTAL TOKENS", "cm-eyebrow"))
        self.models = HBarChart(color=SERIES[2], max_rows=8)
        self.models.set_margin_top(8)
        mc.append(self.models)
        mc.set_size_request(300, -1)
        two.append(mc)
        hc = card()
        hc.append(label("ACTIVITY BY HOUR OF DAY", "cm-eyebrow"))
        self.heat = HeatStrip()
        self.heat.set_margin_top(12)
        hc.append(self.heat)
        self.heat_note = label("", "caption", "cm-muted")
        self.heat_note.set_margin_top(4)
        hc.append(self.heat_note)
        hc.set_size_request(300, -1)
        two.append(hc)
        root.append(two)
        self.note = label("All figures are computed from your local Claude Code transcripts. "
                          "Plan-limit percentages are not part of this history.", "caption", "cm-faint", wrap=True)
        root.append(self.note)

        # range selector in the header
        self.toggle = Adw.ToggleGroup()
        for name, _d, lbl in RANGES:
            self.toggle.add(Adw.Toggle(name=name, label=lbl))
        self.toggle.set_active_name("30")
        self.toggle.connect("notify::active-name", self._on_range)
        self.toggle.add_css_class("round")

        tv = Adw.ToolbarView()
        hb = Adw.HeaderBar()
        hb.set_title_widget(self.toggle)
        refresh = Gtk.Button(icon_name="view-refresh-symbolic", tooltip_text="Reload")
        refresh.connect("clicked", lambda *_: self.load(force=True))
        hb.pack_end(refresh)
        tv.add_top_bar(hb)
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        sp = Gtk.Box(halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        sp.append(Adw.Spinner(width_request=32, height_request=32))
        self.stack.add_named(sp, "loading")
        self.stack.add_named(self.wrap(root), "content")
        tv.set_content(self.stack)
        page = Adw.NavigationPage(title=self.title, tag="root")
        page.set_child(tv)
        self.nav.add(page)
        self._build_legend()

    def _build_legend(self) -> None:
        self.legend.remove_all()
        for i, (_k, name) in enumerate(self._series()):
            b = Gtk.Box(spacing=5)
            b.append(_swatch(SERIES[i % len(SERIES)]))
            b.append(label(name, "caption", "cm-muted"))
            self.legend.append(b)

    def _series(self):
        return [s for s in TOKEN_SERIES if self._include_cache_read or s[0] != "cache_read"]

    # ---------------------------------------------------------------- data
    def on_shown(self) -> None:
        self._wanted = True
        # stats are heavy-ish; refresh at most every 60 s when the page is shown
        if self._data is None or time.time() - self._loaded_at > 60:
            self.load()

    def on_available(self, available: bool) -> None:
        if available and getattr(self, "_wanted", False):
            self.load(force=True)

    def load(self, force: bool = False) -> None:
        if not self.win.client.available:
            return  # on_available() retries once the service appears
        if self._data is None:
            self.stack.set_visible_child_name("loading")
        days = self._days
        self.win.client.get_stats(days, lambda d, e: self._on_stats(days, d, e))

    def _on_stats(self, days, data, err) -> None:
        if days != self._days:
            return
        if err is not None:
            self.win.toast(f"Could not load statistics: {err}")
            return
        self._data = data or {}
        self._loaded_at = time.time()
        self._render()
        self.stack.set_visible_child_name("content")

    def _render(self) -> None:
        d = self._data or {}
        days = d.get("days") or []
        tot = {"input": 0, "output": 0, "cache_read": 0, "cache_create": 0}
        sessions = tools = 0
        for day in days:
            for k in tot:
                tot[k] += int((day.get("tokens") or {}).get(k) or 0)
            sessions += int(day.get("sessions") or 0)
            tools += int(day.get("tool_calls") or 0)
        n = max(1, len(days))
        self.t_tokens.update(fmt.tokens(sum(tot.values())), f"{fmt.tokens(sum(tot.values()) / n)} per day")
        self.t_output.update(fmt.tokens(tot["output"]), f"{fmt.tokens(tot['output'] / n)} per day")
        self.t_sessions.update(str(sessions), f"{sessions / n:.1f} per day")
        self.t_tools.update(fmt.tokens(tools), f"{fmt.tokens(tools / n)} per day")

        series = self._series()
        labels, values = [], []
        for day in days:
            date = day.get("date") or ""
            try:
                t = time.strptime(date, "%Y-%m-%d")
                labels.append(time.strftime("%b %d" if self._days > 7 else "%a %d", t))
            except ValueError:
                labels.append(date)
            tk = day.get("tokens") or {}
            values.append([float(tk.get(k) or 0) for k, _ in series])
        self.daily.set_data(labels, [name for _, name in series], values)

        by_tool = sorted((d.get("by_tool") or {}).items(), key=lambda kv: -kv[1])
        self.tools.set_data([(k if not k.startswith("mcp__") else "MCP · " + k.split("__")[-1], float(v), fmt.tokens(v))
                             for k, v in by_tool])
        projects = sorted(d.get("by_project") or [], key=lambda p: -(p.get("tool_calls") or 0))
        self.projects.set_data([(p.get("project") or "?", float(p.get("tool_calls") or 0),
                                 f"{fmt.tokens(p.get('tool_calls'))}") for p in projects])
        models = sorted(((m, fmt.total_tokens(tc) or 0) for m, tc in (d.get("by_model") or {}).items()),
                        key=lambda kv: -kv[1])
        self.models.set_data([(m, float(v), fmt.tokens(v)) for m, v in models])
        hourly = d.get("hourly") or [0] * 24
        self.heat.set_data(hourly)
        if any(hourly):
            peak = max(range(24), key=lambda h: hourly[h])
            set_text(self.heat_note, f"Busiest hour: {peak:02d}:00 – {peak:02d}:59 · {hourly[peak]} tool calls")
        else:
            set_text(self.heat_note, "No activity in this range")

    def _on_range(self, *_a) -> None:
        name = self.toggle.get_active_name()
        self._days = next((d for n, d, _ in RANGES if n == name), 30)
        self.load(force=True)

    def _on_cache_toggle(self, sw, _p) -> None:
        self._include_cache_read = sw.get_active()
        self._build_legend()
        if self._data is not None:
            self._render()
