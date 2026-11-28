"""Main window: sidebar navigation, offline state, snapshot fan-out."""

from __future__ import annotations

import time
from collections import deque

from gi.repository import Adw, Gio, GLib, Gtk

from ..common import fmt
from ..common.client import MonitorClient
from .widgets import label, set_text

PAGES = [
    # id, title, icon
    ("office", "View", "cm-office-symbolic"),
    ("overview", "Overview", "cm-overview-symbolic"),
    ("sessions", "Sessions", "cm-session-symbolic"),
    ("timeline", "Timeline", "cm-timeline-symbolic"),
    ("history", "History", "cm-history-symbolic"),
    ("stats", "Statistics", "cm-chart-symbolic"),
]

SPARK_LEN = 150  # samples per session kept client-side (~5 min at 2 s)


class Page(Adw.Bin):
    """Base class for content pages. Each page owns an Adw.NavigationView."""

    title = ""

    def __init__(self, win: "MainWindow") -> None:
        super().__init__()
        self.win = win
        self.nav = Adw.NavigationView()
        self.set_child(self.nav)

    def root_page(self, content: Gtk.Widget, header_extra: Gtk.Widget | None = None,
                  scroll: bool = True, clamp: int = 1180) -> Adw.NavigationPage:
        tv = Adw.ToolbarView()
        hb = Adw.HeaderBar()
        if header_extra is not None:
            hb.pack_end(header_extra)
        tv.add_top_bar(hb)
        tv.set_content(self.wrap(content, scroll, clamp))
        page = Adw.NavigationPage(title=self.title, tag="root")
        page.set_child(tv)
        self.nav.add(page)
        return page

    @staticmethod
    def wrap(content: Gtk.Widget, scroll: bool = True, clamp: int = 1180) -> Gtk.Widget:
        c = Adw.Clamp(maximum_size=clamp, tightening_threshold=int(clamp * 0.8))
        content.set_margin_top(18)
        content.set_margin_bottom(24)
        content.set_margin_start(18)
        content.set_margin_end(18)
        c.set_child(content)
        if not scroll:
            return c
        sw = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        sw.set_child(c)
        return sw

    # hooks ------------------------------------------------------------
    def on_snapshot(self, snap: dict) -> None: ...
    def on_events(self, events: list[dict]) -> None: ...
    def on_shown(self) -> None: ...
    def on_available(self, available: bool) -> None: ...
    def tick(self) -> None: ...


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app: Adw.Application, client: MonitorClient) -> None:
        super().__init__(application=app, title="Claudeville")
        self.set_default_size(1240, 820)
        self.set_size_request(360, 480)
        self.client = client
        self.snapshot: dict | None = None
        self.series: dict[str, deque] = {}
        self._pages: dict[str, Page] = {}
        self._current = "office"
        self._fetching = False
        self._dirty = False
        self._tick_id = 0
        self._last_rev = -1
        self._sidebar_compact = False

        self.toasts = Adw.ToastOverlay()
        self.set_content(self.toasts)
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, transition_duration=220)
        self.toasts.set_child(self.stack)
        self.stack.add_named(self._build_offline(), "offline")
        self.stack.add_named(self._build_main(), "main")
        self.stack.set_visible_child_name("offline")

        bp = Adw.Breakpoint.new(Adw.BreakpointCondition.parse("max-width: 760sp"))
        bp.add_setter(self.split, "collapsed", True)
        self.add_breakpoint(bp)

        client.on_available(self._on_available)
        client.on_snapshot_changed(self._on_snapshot_changed)
        client.on_events_added(self._on_events)
        self.connect("notify::suspended", lambda *_: self._update_activity())
        self.connect("notify::is-active", lambda *_: self._update_activity())
        self.connect("map", lambda *_: self._update_activity())
        self.connect("unmap", lambda *_: self._update_activity())
        self._install_actions()

    # ------------------------------------------------------------- building
    def _build_offline(self) -> Gtk.Widget:
        tv = Adw.ToolbarView()
        tv.add_top_bar(Adw.HeaderBar())
        page = Adw.StatusPage(
            icon_name="io.github.aliyov.Claudeville",
            title="Monitor Service Not Running",
            description=(
                "The dashboard shows data from the Claudeville background service.\n"
                "Start it with <tt>systemctl --user start claudeville</tt> — "
                "this window reconnects automatically."
            ),
        )
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, halign=Gtk.Align.CENTER)
        spinner = Adw.Spinner()
        spinner.set_size_request(24, 24)
        box.append(spinner)
        box.append(label("Waiting for io.github.aliyov.Claudeville on the session bus…", "caption", "cm-muted", xalign=0.5))
        page.set_child(box)
        tv.set_content(page)
        return tv

    def _build_main(self) -> Gtk.Widget:
        self.split = Adw.NavigationSplitView(min_sidebar_width=220, max_sidebar_width=280, sidebar_width_fraction=0.2)

        # sidebar
        sb_tv = Adw.ToolbarView()
        sb_hb = Adw.HeaderBar()
        brand = Gtk.Box(spacing=8)
        icon = Gtk.Image.new_from_icon_name("io.github.aliyov.Claudeville")
        icon.set_pixel_size(22)
        brand.append(icon)
        self._brand_label = label("Claudeville", "cm-brand-title")
        brand.append(self._brand_label)
        sb_hb.set_title_widget(brand)
        menu = Gio.Menu()
        menu.append("Preferences", "win.preferences")
        menu.append("About Claudeville", "app.about")
        menu_btn = Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu, tooltip_text="Main Menu")
        menu_btn.set_primary(True)
        sb_hb.pack_end(menu_btn)
        self._menu_btn = menu_btn
        sb_tv.add_top_bar(sb_hb)

        self.sidebar = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.sidebar.add_css_class("navigation-sidebar")
        self.sidebar.add_css_class("cm-sidebar")
        self._badges: dict[str, Gtk.Label] = {}
        self._row_tails: list[Gtk.Box] = []
        for pid, title, icon_name in PAGES:
            row = Gtk.ListBoxRow()
            row.page_id = pid
            box = Gtk.Box(spacing=12)
            box.append(Gtk.Image.new_from_icon_name(icon_name))
            tail = Gtk.Box(spacing=12, hexpand=True)
            tail.append(label(title))
            tail.append(Gtk.Box(hexpand=True))
            badge = label("", "cm-badge", xalign=0.5)
            badge.set_visible(False)
            tail.append(badge)
            box.append(tail)
            row.set_tooltip_text(title)
            self._row_tails.append(tail)
            self._badges[pid] = badge
            row.set_child(box)
            self.sidebar.append(row)
        self.sidebar.connect("row-activated", self._on_row_activated)

        sb_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        sw = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        sw.set_child(self.sidebar)
        sb_box.append(sw)
        # footer: daemon status
        foot = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        foot.set_margin_start(18)
        foot.set_margin_end(18)
        foot.set_margin_bottom(14)
        foot.set_margin_top(8)
        self.foot_status = label("", "caption", "cm-muted", ellipsize=True)
        self.foot_index = label("", "caption", "cm-muted", ellipsize=True)
        foot.append(self.foot_status)
        foot.append(self.foot_index)
        sb_box.append(foot)
        self._foot = foot
        sb_tv.set_content(sb_box)
        sidebar_page = Adw.NavigationPage(title="Claudeville")
        sidebar_page.set_child(sb_tv)
        self.split.set_sidebar(sidebar_page)

        self.content_stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, transition_duration=160)
        self.content_page = Adw.NavigationPage(title="View")
        self.content_page.set_child(self.content_stack)
        self.split.set_content(self.content_page)
        self.sidebar.select_row(self.sidebar.get_row_at_index(0))
        GLib.idle_add(lambda: (self._show_page("office"), False)[1])
        return self.split

    def _install_actions(self) -> None:
        act = Gio.SimpleAction.new("preferences", None)
        act.connect("activate", lambda *_: self.open_preferences())
        self.add_action(act)
        app = self.get_application()
        app.set_accels_for_action("win.preferences", ["<Control>comma"])
        for i, (pid, _t, _i) in enumerate(PAGES):
            a = Gio.SimpleAction.new(f"page-{pid}", None)
            a.connect("activate", lambda _a, _p, pid=pid: self.navigate(pid))
            self.add_action(a)
            app.set_accels_for_action(f"win.page-{pid}", [f"<Alt>{i + 1}"])
        refresh = Gio.SimpleAction.new("refresh", None)
        refresh.connect("activate", lambda *_: self.refresh())
        self.add_action(refresh)
        app.set_accels_for_action("win.refresh", ["<Control>r", "F5"])

    # ------------------------------------------------------------ navigation
    def _on_row_activated(self, _lb, row) -> None:
        self._show_page(row.page_id)
        self.split.set_show_content(True)

    def navigate(self, page_id: str) -> Page:
        idx = [p[0] for p in PAGES].index(page_id)
        self.sidebar.select_row(self.sidebar.get_row_at_index(idx))
        page = self._show_page(page_id)
        self.split.set_show_content(True)
        return page

    def _page_class(self, page_id: str):
        if page_id == "office":
            from .pages.office import OfficePage
            return OfficePage
        if page_id == "overview":
            from .pages.overview import OverviewPage
            return OverviewPage
        if page_id == "sessions":
            from .pages.sessions import SessionsPage
            return SessionsPage
        if page_id == "timeline":
            from .pages.timeline import TimelinePage
            return TimelinePage
        if page_id == "history":
            from .pages.history import HistoryPage
            return HistoryPage
        if page_id == "stats":
            from .pages.stats import StatsPage
            return StatsPage
        raise KeyError(page_id)

    def get_page(self, page_id: str) -> Page:
        page = self._pages.get(page_id)
        if page is None:
            page = self._page_class(page_id)(self)
            self._pages[page_id] = page
            self.content_stack.add_named(page, page_id)
            if self.snapshot is not None:
                page.on_snapshot(self.snapshot)
        return page

    def set_sidebar_compact(self, compact: bool) -> None:
        """Icon-only sidebar rail, used while the View shows one department
        enlarged so the office gets the space."""
        if compact == self._sidebar_compact:
            return
        self._sidebar_compact = compact
        self.split.set_min_sidebar_width(58 if compact else 220)
        self.split.set_max_sidebar_width(58 if compact else 280)
        for w in (*self._row_tails, self._brand_label, self._menu_btn, self._foot):
            w.set_visible(not compact)
        if compact:
            self.sidebar.add_css_class("cm-rail")
        else:
            self.sidebar.remove_css_class("cm-rail")

    def _show_page(self, page_id: str) -> Page:
        page = self.get_page(page_id)
        if page_id != "office":
            self.set_sidebar_compact(False)
        self._current = page_id
        self.content_stack.set_visible_child_name(page_id)
        self.content_page.set_title(dict((p[0], p[1]) for p in PAGES)[page_id])
        page.on_shown()
        self._update_activity()
        return page

    def open_preferences(self) -> None:
        from .pages.settings import PreferencesDialog
        PreferencesDialog(self).present(self)

    # ------------------------------------------------------------- data flow
    @property
    def active(self) -> bool:
        return self.get_mapped() and not self.is_suspended()

    def _update_activity(self) -> None:
        active = self.active and self.client.available
        if active and not self._tick_id:
            self._tick_id = GLib.timeout_add_seconds(1, self._tick)
        elif not active and self._tick_id:
            GLib.source_remove(self._tick_id)
            self._tick_id = 0
        if active and self._dirty:
            self.refresh()

    def _tick(self) -> bool:
        page = self._pages.get(self._current)
        if page is not None:
            page.tick()
        return True

    def _on_available(self, available: bool) -> None:
        self.stack.set_visible_child_name("main" if available else "offline")
        for p in self._pages.values():
            p.on_available(available)
        if available:
            self._last_rev = -1
            self.refresh()
        else:
            self.snapshot = None
        self._update_activity()

    def _on_snapshot_changed(self, rev: int) -> None:
        if rev == self._last_rev:
            return
        self.refresh()

    def refresh(self) -> None:
        if not self.active:
            self._dirty = True  # fetch when shown again
            return
        if self._fetching:
            self._dirty = True
            return
        self._dirty = False
        self._fetching = True
        self.client.get_snapshot(self._on_snapshot)

    def _on_snapshot(self, snap, err) -> None:
        self._fetching = False
        if err is not None:
            if self.client.available:
                self.toast(f"Could not load snapshot: {err}")
        elif isinstance(snap, dict):
            self._last_rev = snap.get("revision", -1)
            self.snapshot = snap
            self._record_series(snap)
            self._update_chrome(snap)
            for p in self._pages.values():
                try:
                    p.on_snapshot(snap)
                except Exception as e:  # keep the UI alive on unexpected payloads
                    import logging
                    logging.getLogger(__name__).exception("page update failed")
                    self.toast(f"Display error: {e}")
        if self._dirty:
            GLib.timeout_add(250, lambda: (self.refresh(), False)[1])

    def _record_series(self, snap: dict) -> None:
        now = time.time()
        live = set()
        for s in snap.get("sessions") or []:
            sid = s.get("session_id")
            live.add(sid)
            buf = self.series.setdefault(sid, deque(maxlen=SPARK_LEN))
            buf.append((now, s.get("cpu_percent"), s.get("rss_bytes")))
        for sid in list(self.series):
            if sid not in live:
                del self.series[sid]

    def _update_chrome(self, snap: dict) -> None:
        totals = snap.get("totals") or {}
        live = totals.get("live") or 0
        waiting = totals.get("waiting") or 0
        badge = self._badges["sessions"]
        if live:
            set_text(badge, str(live))
            badge.set_visible(True)
            if waiting:
                badge.add_css_class("attention")
                badge.set_tooltip_text(f"{waiting} session(s) need attention")
            else:
                badge.remove_css_class("attention")
                badge.set_tooltip_text(f"{live} live session(s)")
        else:
            badge.set_visible(False)
        d = snap.get("daemon") or {}
        set_text(self.foot_status, f"Service {d.get('version', '?')} · up {fmt.duration(fmt.now_ms() - d['started_at']) if d.get('started_at') else '—'}")
        idx = d.get("indexing") or {}
        if idx.get("active"):
            set_text(self.foot_index, f"Indexing history {idx.get('files_done', 0)}/{idx.get('files_total', 0)}")
            self.foot_index.set_visible(True)
        else:
            self.foot_index.set_visible(False)

    def _on_events(self, events: list[dict]) -> None:
        if not events:
            return
        for p in self._pages.values():
            try:
                p.on_events(events)
            except Exception:
                import logging
                logging.getLogger(__name__).exception("event dispatch failed")

    # ------------------------------------------------------------------ misc
    def toast(self, text: str) -> None:
        t = Adw.Toast(title=GLib.markup_escape_text(text), timeout=4)
        self.toasts.add_toast(t)

    def open_session(self, session_id: str, live: bool = True) -> None:
        if live:
            page = self.navigate("sessions")
            page.open_detail(session_id)
        else:
            page = self.navigate("history")
            page.open_detail(session_id)
