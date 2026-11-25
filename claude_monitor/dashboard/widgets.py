"""Reusable dashboard widgets.

Everything here is update-in-place: widgets expose ``update(data)`` methods so
pages can diff snapshots instead of rebuilding widget trees.
"""

from __future__ import annotations

import math
from collections import deque

from gi.repository import Adw, GLib, Gtk, Pango

from ..common import fmt

BRAND = (0xD9 / 255, 0x77 / 255, 0x57 / 255)
STATUS_RGB = {
    "busy": (0x35 / 255, 0x84 / 255, 0xE4 / 255),
    "running": (0x35 / 255, 0x84 / 255, 0xE4 / 255),
    "waiting": (0xE5 / 255, 0xA5 / 255, 0x0A / 255),
    "blocked": (0xE0 / 255, 0x1B / 255, 0x24 / 255),
    "idle": (0x2E / 255, 0xC2 / 255, 0x7E / 255),
}
STATUS_ORDER = {"waiting": 0, "blocked": 1, "busy": 2, "idle": 3, "unknown": 4}
_STATUS_CLASSES = ("st-busy", "st-waiting", "st-blocked", "st-idle", "st-unknown", "st-running", "st-done")


def set_status_class(widget: Gtk.Widget, status: str | None) -> None:
    status = status or "unknown"
    for c in _STATUS_CLASSES:
        if c != "st-" + status:
            widget.remove_css_class(c)
    widget.add_css_class("st-" + status)


def label(text: str = "", *classes: str, xalign: float = 0.0, ellipsize: bool = False,
          wrap: bool = False, selectable: bool = False) -> Gtk.Label:
    lbl = Gtk.Label(label=text, xalign=xalign)
    for c in classes:
        lbl.add_css_class(c)
    if ellipsize:
        lbl.set_ellipsize(Pango.EllipsizeMode.END)
    if wrap:
        lbl.set_wrap(True)
        lbl.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
    if selectable:
        lbl.set_selectable(True)
    return lbl


def set_text(lbl: Gtk.Label, text: str) -> None:
    """Avoid relayout when the text did not change."""
    if lbl.get_label() != text:
        lbl.set_label(text)


def fg_rgba(widget: Gtk.Widget) -> tuple[float, float, float, float]:
    c = widget.get_color()
    return c.red, c.green, c.blue, c.alpha


def accent_rgb() -> tuple[float, float, float]:
    try:
        c = Adw.StyleManager.get_default().get_accent_color_rgba()
        return c.red, c.green, c.blue
    except Exception:
        return STATUS_RGB["busy"]


# ------------------------------------------------------------------ status

PULSE_SECONDS = {"busy": 5, "running": 5, "waiting": 12}


class StatusDot(Gtk.Box):
    """Status indicator. Pulses briefly after a change, then shows a static halo.

    A continuous CSS animation would keep the window repainting at 60 fps,
    which costs several percent of a CPU core for a purely cosmetic effect.
    """

    def __init__(self, status: str = "unknown", small: bool = False) -> None:
        super().__init__(valign=Gtk.Align.CENTER, halign=Gtk.Align.CENTER)
        self.add_css_class("cm-dot")
        if small:
            self.add_css_class("small")
        self._status: str | None = None
        self._pulse_id = 0
        self.connect("unmap", lambda *_: self._stop_pulse())
        self.set_status(status)

    def set_status(self, status: str | None) -> None:
        status = status or "unknown"
        if status == self._status:
            return
        first = self._status is None
        self._status = status
        set_status_class(self, status)
        self.set_tooltip_text(fmt.status_label(status))
        secs = PULSE_SECONDS.get(status)
        if self._pulse_id:
            GLib.source_remove(self._pulse_id)
            self._pulse_id = 0
        # Only animate while actually on screen: GTK keeps ticking the frame
        # clock for CSS animations that start or stop on hidden widgets.
        if secs and not first and self.get_mapped():
            self.add_css_class("pulse")
            self._pulse_id = GLib.timeout_add_seconds(secs, self._stop_pulse)
        else:
            self.remove_css_class("pulse")

    def _stop_pulse(self) -> bool:
        if self._pulse_id:
            GLib.source_remove(self._pulse_id)
        self._pulse_id = 0
        self.remove_css_class("pulse")
        return False


class StatusPill(Gtk.Box):
    def __init__(self, status: str = "unknown") -> None:
        super().__init__(spacing=6, valign=Gtk.Align.CENTER)
        self.add_css_class("cm-pill")
        self._dot = StatusDot(status, small=True)
        self._lbl = Gtk.Label()
        self.append(self._dot)
        self.append(self._lbl)
        self.set_status(status)

    def set_status(self, status: str | None) -> None:
        set_status_class(self, status)
        self._dot.set_status(status)
        set_text(self._lbl, fmt.status_label(status))


def chip(text: str, accent: bool = False) -> Gtk.Label:
    lbl = Gtk.Label(label=text, valign=Gtk.Align.CENTER)
    lbl.add_css_class("cm-chip")
    if accent:
        lbl.add_css_class("accent")
    lbl.set_ellipsize(Pango.EllipsizeMode.END)
    return lbl


def card(child: Gtk.Widget | None = None, hover: bool = False, compact: bool = False) -> Gtk.Box:
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    box.add_css_class("cm-card")
    if hover:
        box.add_css_class("cm-hover")
    if compact:
        box.add_css_class("cm-compact")
    if child is not None:
        box.append(child)
    return box


# --------------------------------------------------------------- usage ring

class UsageRing(Gtk.DrawingArea):
    """Circular gauge whose value animates smoothly between updates."""

    def __init__(self, size: int = 108) -> None:
        super().__init__(content_width=size, content_height=size, valign=Gtk.Align.CENTER)
        self._value: float | None = None   # target 0..100
        self._shown = 0.0                  # animated value
        self.set_draw_func(self._draw)
        target = Adw.CallbackAnimationTarget.new(self._on_anim)
        self._anim = Adw.TimedAnimation.new(self, 0.0, 0.0, 500, target)
        self._anim.set_easing(Adw.Easing.EASE_OUT_CUBIC)

    def _on_anim(self, v: float) -> None:
        self._shown = v
        self.queue_draw()

    def set_value(self, value: float | None) -> None:
        if value is None:
            self._value = None
            self._anim.skip()
            self._shown = 0.0
            self.queue_draw()
            return
        value = max(0.0, min(100.0, float(value)))
        if self._value is not None and abs(value - self._value) < 0.01:
            return
        self._value = value
        if not self.get_mapped():
            # Off-screen: jump straight to the value; animating would only repaint.
            self._anim.skip()
            self._shown = value
            self.queue_draw()
            return
        self._anim.set_value_from(self._shown)
        self._anim.set_value_to(value)
        self._anim.play()

    @staticmethod
    def level_color(v: float) -> tuple[float, float, float]:
        if v >= 90:
            return STATUS_RGB["blocked"]
        if v >= 75:
            return STATUS_RGB["waiting"]
        return BRAND

    def _draw(self, _area, cr, w, h) -> None:
        size = min(w, h)
        lw = max(6.0, size * 0.085)
        r = size / 2 - lw / 2 - 1
        cx, cy = w / 2, h / 2
        fr, fg, fb, _ = fg_rgba(self)
        cr.set_line_width(lw)
        cr.set_source_rgba(fr, fg, fb, 0.10)
        cr.arc(cx, cy, r, 0, 2 * math.pi)
        cr.stroke()
        if self._value is None:
            # dashed ring = unavailable
            cr.set_source_rgba(fr, fg, fb, 0.25)
            cr.set_dash([3.0, 5.0])
            cr.arc(cx, cy, r, 0, 2 * math.pi)
            cr.stroke()
            return
        frac = self._shown / 100.0
        if frac > 0:
            cr.set_line_cap(1)  # ROUND
            rr, gg, bb = self.level_color(self._value)
            cr.set_source_rgb(rr, gg, bb)
            start = -math.pi / 2
            cr.arc(cx, cy, r, start, start + 2 * math.pi * frac)
            cr.stroke()


class UsageCard(Gtk.Box):
    """One plan-limit window: ring + percentage + countdown + staleness."""

    def __init__(self, title: str, subtitle: str) -> None:
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=18, hexpand=True)
        self.add_css_class("cm-card")
        self.add_css_class("cm-hover")
        self._resets_at: float | None = None
        self._as_of: int | None = None

        overlay = Gtk.Overlay()
        self.ring = UsageRing()
        overlay.set_child(self.ring)
        center = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        self.pct = label("—", "cm-mid-number", xalign=0.5)
        self.pct_sub = label("used", "caption", "cm-muted", xalign=0.5)
        center.append(self.pct)
        center.append(self.pct_sub)
        overlay.add_overlay(center)
        self.append(overlay)

        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, valign=Gtk.Align.CENTER, hexpand=True)
        col.append(label(title.upper(), "cm-eyebrow", ellipsize=True))
        col.append(label(subtitle, "heading", ellipsize=True))
        self.countdown = label("—", "title-3", "cm-tnum", ellipsize=True)
        self.countdown.set_margin_top(6)
        col.append(self.countdown)
        self.reset_at = label("", "caption", "cm-muted", ellipsize=True)
        col.append(self.reset_at)
        self.as_of = label("", "caption", "cm-muted", ellipsize=True)
        col.append(self.as_of)
        self.append(col)

    def update(self, window: dict | None, as_of: int | None) -> None:
        self._as_of = as_of
        if not window:
            self.ring.set_value(None)
            set_text(self.pct, "—")
            set_text(self.pct_sub, "no data")
            self._resets_at = None
            set_text(self.reset_at, "Claude Code has not reported this window yet")
        else:
            pct = window.get("used_percentage")
            self.ring.set_value(pct)
            set_text(self.pct, fmt.percent(pct))
            set_text(self.pct_sub, "used")
            self._resets_at = window.get("resets_at")
            if self._resets_at:
                t = GLib.DateTime.new_from_unix_local(int(self._resets_at))
                set_text(self.reset_at, "Resets " + t.format("%a %H:%M"))
            else:
                set_text(self.reset_at, "Reset time unknown")
        self.tick()

    def tick(self) -> None:
        if self._resets_at:
            set_text(self.countdown, "Resets in " + fmt.countdown(self._resets_at))
        else:
            set_text(self.countdown, "—")
        if self._as_of:
            age = fmt.now_ms() - self._as_of
            set_text(self.as_of, "Reported " + fmt.relative(self._as_of))
            if age > 15 * 60 * 1000:
                self.as_of.add_css_class("cm-stale")
                self.as_of.set_tooltip_text(
                    "Claude Code only reports limits while a session is active. "
                    "This value may be out of date.")
            else:
                self.as_of.remove_css_class("cm-stale")
                self.as_of.set_tooltip_text(None)
        else:
            set_text(self.as_of, "")


# --------------------------------------------------------------- stat tile

class StatTile(Gtk.Box):
    def __init__(self, title: str, icon: str | None = None, hover: bool = True) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4, hexpand=True)
        self.add_css_class("cm-card")
        self.add_css_class("cm-compact")
        if hover:
            self.add_css_class("cm-hover")
        head = Gtk.Box(spacing=6)
        if icon:
            img = Gtk.Image.new_from_icon_name(icon)
            img.add_css_class("cm-muted")
            head.append(img)
        title_lbl = label(title.upper(), "cm-eyebrow", ellipsize=True)
        # Ellipsizing labels request almost no minimum width, so grids squeeze
        # them to "C…". Reserve room for the full title.
        title_lbl.set_width_chars(len(title) + 4)  # uppercase + letter-spacing
        head.append(title_lbl)
        self.append(head)
        self.value = label("—", "cm-big-number", ellipsize=True)
        self.value.set_width_chars(6)
        self.append(self.value)
        self.sub = label("", "caption", "cm-muted", ellipsize=True)
        self.sub.set_max_width_chars(16)
        self.sub.set_tooltip_text(None)
        self.append(self.sub)

    def update(self, value: str, sub: str = "") -> None:
        set_text(self.value, value)
        if self.sub.get_label() != sub:
            self.sub.set_label(sub)
            self.sub.set_tooltip_text(sub or None)


# --------------------------------------------------------------- sparkline

class Sparkline(Gtk.DrawingArea):
    """Tiny line chart over a client-side ring buffer."""

    def __init__(self, color: tuple[float, float, float] = BRAND, height: int = 46,
                 max_value: float | None = None) -> None:
        super().__init__(content_height=height, hexpand=True)
        self._data: list[float] = []
        self._color = color
        self._max = max_value
        self.set_draw_func(self._draw)

    def set_data(self, data) -> None:
        self._data = [float(x) for x in data if x is not None]
        self.queue_draw()

    def _draw(self, _a, cr, w, h) -> None:
        d = self._data
        fr, fg, fb, _ = fg_rgba(self)
        cr.set_source_rgba(fr, fg, fb, 0.08)
        cr.set_line_width(1)
        cr.move_to(0, h - 0.5)
        cr.line_to(w, h - 0.5)
        cr.stroke()
        if len(d) < 2:
            return
        top = self._max or max(d) or 1.0
        top = max(top, 1e-9)
        n = len(d)
        pts = [(i * (w - 2) / (n - 1) + 1, h - 3 - (v / top) * (h - 8)) for i, v in enumerate(d)]
        r, g, b = self._color
        cr.move_to(pts[0][0], h)
        for x, y in pts:
            cr.line_to(x, y)
        cr.line_to(pts[-1][0], h)
        cr.close_path()
        cr.set_source_rgba(r, g, b, 0.16)
        cr.fill()
        cr.set_line_width(1.8)
        cr.set_line_join(1)
        cr.move_to(*pts[0])
        for x, y in pts[1:]:
            cr.line_to(x, y)
        cr.set_source_rgb(r, g, b)
        cr.stroke()
        cr.arc(pts[-1][0] - 1, pts[-1][1], 2.6, 0, 2 * math.pi)
        cr.fill()


# ------------------------------------------------------------- event rows

TOOL_ICONS = {
    "Bash": "utilities-terminal-symbolic",
    "BashOutput": "utilities-terminal-symbolic",
    "KillShell": "media-playback-stop-symbolic",
    "Read": "text-x-generic-symbolic",
    "Edit": "document-edit-symbolic",
    "MultiEdit": "document-edit-symbolic",
    "Write": "document-new-symbolic",
    "NotebookEdit": "document-edit-symbolic",
    "Grep": "system-search-symbolic",
    "Glob": "system-search-symbolic",
    "WebFetch": "web-browser-symbolic",
    "WebSearch": "web-browser-symbolic",
    "Agent": "cm-agent-symbolic",
    "Task": "cm-agent-symbolic",
    "TodoWrite": "checkbox-checked-symbolic",
    "Skill": "applications-science-symbolic",
}
KIND_ICONS = {
    "error": "dialog-error-symbolic",
    "prompt": "cm-chat-symbolic",
    "turn_end": "cm-check-symbolic",
    "subagent_start": "cm-agent-symbolic",
    "subagent_end": "cm-agent-symbolic",
    "compact": "cm-compact-symbolic",
    "status": "cm-pulse-symbolic",
    "session_start": "cm-session-symbolic",
    "session_end": "cm-session-symbolic",
    "limit": "dialog-warning-symbolic",
}
KIND_CLASS = {
    "error": "k-error", "prompt": "k-prompt", "subagent_start": "k-agent", "subagent_end": "k-agent",
    "turn_end": "k-turn", "limit": "k-limit", "tool": "k-tool",
}
KIND_LABELS = {
    "tool": "Tool", "error": "Error", "prompt": "Prompt", "turn_end": "Turn finished",
    "subagent_start": "Agent started", "subagent_end": "Agent finished", "compact": "Compaction",
    "status": "Status", "session_start": "Session started", "session_end": "Session ended", "limit": "Limit hit",
}
MONO_TOOLS = {"Bash", "BashOutput", "Grep", "Glob", "Read", "Edit", "MultiEdit", "Write", "NotebookEdit"}


def event_icon(ev: dict) -> str:
    kind = ev.get("kind") or "tool"
    if kind == "tool":
        tool = ev.get("tool") or ""
        if tool.startswith("mcp__"):
            return "cm-plug-symbolic"
        return TOOL_ICONS.get(tool, "cm-pulse-symbolic")
    return KIND_ICONS.get(kind, "cm-pulse-symbolic")


def event_title(ev: dict) -> str:
    kind = ev.get("kind") or "tool"
    tool = ev.get("tool")
    if tool and kind in ("tool", "error"):
        if tool.startswith("mcp__"):
            parts = tool.split("__")
            return f"MCP · {parts[1]} · {parts[-1]}" if len(parts) >= 3 else tool
        return tool
    return KIND_LABELS.get(kind, kind.replace("_", " ").title())


class EventRow(Gtk.Box):
    """One activity entry. Bindable: call ``bind(ev)`` to reuse in a ListView."""

    def __init__(self, show_project: bool = True) -> None:
        super().__init__(spacing=12, hexpand=True, halign=Gtk.Align.FILL)
        self.add_css_class("cm-feed-row")
        self._show_project = show_project
        self.icon_box = Gtk.Box(halign=Gtk.Align.START, valign=Gtk.Align.START)
        self.icon_box.set_hexpand(False)
        self.icon_box.add_css_class("cm-feed-icon")
        self.icon = Gtk.Image(hexpand=True, halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        self.icon_box.append(self.icon)
        self.append(self.icon_box)

        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True)
        top = Gtk.Box(spacing=8)
        self.title = label("", "heading", ellipsize=True)
        self.title.set_hexpand(False)
        top.append(self.title)
        self.project = chip("", accent=True)
        top.append(self.project)
        self.agent = chip("")
        top.append(self.agent)
        spacer = Gtk.Box(hexpand=True)
        top.append(spacer)
        self.time = label("", "caption", "cm-muted", "cm-tnum")
        top.append(self.time)
        col.append(top)
        self.summary = label("", ellipsize=True)
        self.summary.set_max_width_chars(120)
        col.append(self.summary)
        self.append(col)
        self._ev: dict | None = None

    def bind(self, ev: dict, show_date: bool = False) -> None:
        self._ev = ev
        kind = ev.get("kind") or "tool"
        self.icon.set_from_icon_name(event_icon(ev))
        for c in list(KIND_CLASS.values()):
            self.icon_box.remove_css_class(c)
        cls = KIND_CLASS.get("error" if ev.get("is_error") else kind)
        if cls:
            self.icon_box.add_css_class(cls)
        set_text(self.title, event_title(ev))
        if ev.get("is_error"):
            self.add_css_class("is-error")
        else:
            self.remove_css_class("is-error")
        proj = ev.get("project") or ""
        self.project.set_visible(self._show_project and bool(proj))
        set_text(self.project, proj)
        aid = ev.get("agent_id")
        self.agent.set_visible(bool(aid))
        if aid:
            set_text(self.agent, "agent " + aid[:6])
        ts = ev.get("ts")
        set_text(self.time, fmt.date_label(ts) if show_date and not fmt.is_today(ts) else fmt.clock(ts))
        self.time.set_tooltip_text(fmt.clock(ts, with_date=True) if ts else None)
        summary = ev.get("summary") or ""
        set_text(self.summary, summary)
        tool = ev.get("tool") or ""
        if tool in MONO_TOOLS and kind in ("tool", "error"):
            self.summary.add_css_class("cm-mono")
        else:
            self.summary.remove_css_class("cm-mono")
        detail = ev.get("detail")
        self.summary.set_tooltip_text(detail if detail and detail != summary else (summary if len(summary) > 60 else None))


class AnimatedFeed(Gtk.Box):
    """A capped, newest-first list whose new rows slide/fade in."""

    def __init__(self, cap: int = 300, show_project: bool = True, empty_text: str = "No activity yet") -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self._cap = cap
        self._show_project = show_project
        self._rows: deque[Gtk.Revealer] = deque()
        self._ids: set = set()
        self.empty = label(empty_text, "cm-muted", xalign=0.5)
        self.empty.set_margin_top(18)
        self.empty.set_margin_bottom(18)
        self.append(self.empty)

    @property
    def oldest_id(self) -> int:
        ids = [i for i in self._ids if isinstance(i, int)]
        return min(ids) if ids else 0

    def clear(self) -> None:
        for r in self._rows:
            self.remove(r)
        self._rows.clear()
        self._ids.clear()
        self.empty.set_visible(True)

    def _make(self, ev: dict, animate: bool) -> Gtk.Revealer:
        row = EventRow(show_project=self._show_project)
        row.bind(ev)
        rev = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.SLIDE_DOWN,
                           transition_duration=260 if animate else 0)
        rev.set_child(row)
        rev.set_reveal_child(not animate)
        if animate:
            row.set_opacity(0.0)
            GLib.idle_add(self._reveal, rev, row)
        return rev

    @staticmethod
    def _reveal(rev: Gtk.Revealer, row: Gtk.Widget) -> bool:
        rev.set_reveal_child(True)
        target = Adw.PropertyAnimationTarget.new(row, "opacity")
        anim = Adw.TimedAnimation.new(row, 0.0, 1.0, 320, target)
        anim.set_easing(Adw.Easing.EASE_OUT_CUBIC)
        anim.play()
        return False

    def prepend_events(self, events: list[dict], animate: bool = True) -> None:
        """``events`` oldest-first; each is inserted at the top."""
        for ev in events:
            eid = ev.get("id")
            if eid in self._ids:
                continue
            self._ids.add(eid)
            rev = self._make(ev, animate)
            self.insert_child_after(rev, self.empty)
            self._rows.appendleft(rev)
        self._trim()
        self.empty.set_visible(not self._rows)

    def append_events(self, events: list[dict]) -> None:
        """``events`` newest-first (as returned by paged queries); added at the bottom."""
        for ev in events:
            eid = ev.get("id")
            if eid in self._ids:
                continue
            self._ids.add(eid)
            rev = self._make(ev, False)
            self.append(rev)
            self._rows.append(rev)
        self._trim()
        self.empty.set_visible(not self._rows)

    def _trim(self) -> None:
        while len(self._rows) > self._cap:
            old = self._rows.pop()
            row = old.get_child()
            if isinstance(row, EventRow) and row._ev:
                self._ids.discard(row._ev.get("id"))
            self.remove(old)


# ----------------------------------------------------------- session card

class SessionCard(Gtk.Box):
    """Compact live-session card used on the Overview grid."""

    def __init__(self, session_id: str) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.session_id = session_id
        self.status = "unknown"
        self.started_at = 0
        self.add_css_class("cm-card")
        self.add_css_class("cm-hover")
        self.add_css_class("cm-session-card")
        self.set_size_request(250, -1)

        top = Gtk.Box(spacing=8)
        self.dot = StatusDot()
        top.append(self.dot)
        self.project = label("", "heading", ellipsize=True)
        self.project.set_hexpand(True)
        top.append(self.project)
        self.agents = chip("")
        top.append(self.agents)
        self.pill = StatusPill()
        top.append(self.pill)
        self.append(top)

        self.title = label("", "cm-muted", ellipsize=True)
        self.append(self.title)

        cur = Gtk.Box(spacing=8)
        self.cur_icon = Gtk.Image.new_from_icon_name("cm-pulse-symbolic")
        self.cur_icon.add_css_class("cm-muted")
        cur.append(self.cur_icon)
        self.current = label("", "cm-mono", ellipsize=True)
        self.current.set_hexpand(True)
        cur.append(self.current)
        self.append(cur)

        foot = Gtk.Box(spacing=14)
        self.since = label("", "caption", "cm-muted", "cm-tnum", ellipsize=True)
        self.since.set_hexpand(True)
        foot.append(self.since)
        self.cpu = self._metric(foot, "cm-cpu-symbolic")
        self.mem = self._metric(foot, "cm-memory-symbolic")
        self.append(foot)
        self._status_since: int | None = None

    @staticmethod
    def _metric(parent: Gtk.Box, icon: str) -> Gtk.Label:
        box = Gtk.Box(spacing=4)
        img = Gtk.Image.new_from_icon_name(icon)
        img.add_css_class("cm-faint")
        box.append(img)
        lbl = label("—", "caption", "cm-tnum")
        box.append(lbl)
        parent.append(box)
        return lbl

    def update(self, s: dict) -> None:
        self.status = s.get("status") or "unknown"
        self.started_at = s.get("started_at") or 0
        set_status_class(self, self.status)
        self.dot.set_status(self.status)
        self.pill.set_status(self.status)
        set_text(self.project, s.get("project") or s.get("name") or "session")
        self.project.set_tooltip_text(s.get("cwd"))
        title = s.get("title") or s.get("name") or ""
        set_text(self.title, title)
        self.title.set_visible(bool(title))
        running = sum(1 for a in s.get("agents") or [] if a.get("status") == "running")
        self.agents.set_visible(running > 0)
        set_text(self.agents, f"{running} agent{'s' if running != 1 else ''}")
        cur = s.get("current")
        if cur and self.status in ("busy", "waiting", "blocked"):
            self.cur_icon.set_from_icon_name(event_icon({"kind": "tool", "tool": cur.get("tool")}))
            set_text(self.current, f"{cur.get('tool') or ''}  {cur.get('summary') or ''}".strip())
            self.current.set_tooltip_text(cur.get("summary"))
        elif self.status == "idle":
            self.cur_icon.set_from_icon_name("cm-check-symbolic")
            set_text(self.current, "Ready for input")
            self.current.set_tooltip_text(None)
        elif self.status == "busy":
            self.cur_icon.set_from_icon_name("cm-pulse-symbolic")
            set_text(self.current, "No tool running")
            self.current.set_tooltip_text("Claude is working, but no tool call is in progress right now.")
        else:
            self.cur_icon.set_from_icon_name("cm-pulse-symbolic")
            set_text(self.current, "—")
            self.current.set_tooltip_text(None)
        cpu = s.get("cpu_percent")
        set_text(self.cpu, fmt.percent(cpu, 1) if cpu is not None else "—")
        set_text(self.mem, fmt.bytes_(s.get("rss_bytes")))
        self._status_since = s.get("status_since")
        self.tick()

    def tick(self) -> None:
        if self._status_since:
            set_text(self.since, f"{fmt.status_label(self.status)} for {fmt.duration(fmt.now_ms() - self._status_since)}")
        else:
            set_text(self.since, "")


def empty_state(icon: str, title: str, description: str) -> Adw.StatusPage:
    page = Adw.StatusPage(icon_name=icon, title=title, description=description)
    page.add_css_class("compact")
    return page


def section_title(text: str) -> Gtk.Label:
    lbl = label(text, "cm-section-title")
    return lbl
