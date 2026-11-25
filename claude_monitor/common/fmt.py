"""Human-readable formatting helpers shared by the UIs.

Every helper accepts ``None`` and returns an em dash, so missing data is never
rendered as a misleading zero.
"""

from __future__ import annotations

import time

DASH = "—"


def now_ms() -> int:
    return int(time.time() * 1000)


def tokens(n: int | float | None) -> str:
    """1234 -> '1.2K', 1_500_000 -> '1.5M'."""
    if n is None:
        return DASH
    n = float(n)
    for div, suffix in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(n) >= div:
            v = n / div
            return f"{v:.1f}{suffix}" if v < 100 else f"{v:.0f}{suffix}"
    return f"{int(n)}"


def bytes_(n: int | float | None) -> str:
    if n is None:
        return DASH
    n = float(n)
    for div, suffix in ((1 << 30, "GB"), (1 << 20, "MB"), (1 << 10, "KB")):
        if n >= div:
            v = n / div
            return f"{v:.1f} {suffix}" if v < 100 else f"{v:.0f} {suffix}"
    return f"{int(n)} B"


def percent(p: float | None, digits: int = 0) -> str:
    if p is None:
        return DASH
    return f"{p:.{digits}f}%"


def duration(ms: int | float | None, short: bool = True) -> str:
    """Compact duration: '45s', '3m 12s', '2h 05m', '3d 4h'."""
    if ms is None:
        return DASH
    s = int(max(0, ms) // 1000)
    d, s = divmod(s, 86400)
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    if d:
        return f"{d}d {h}h"
    if h:
        return f"{h}h {m:02d}m"
    if m:
        return f"{m}m {s:02d}s" if not short or m < 10 else f"{m}m"
    return f"{s}s"


def countdown(resets_at_s: int | float | None, now: float | None = None) -> str:
    """Countdown to a reset time given in epoch *seconds* (Claude Code's unit)."""
    if resets_at_s is None:
        return DASH
    now = time.time() if now is None else now
    left = int(resets_at_s - now)
    if left <= 0:
        return "resetting…"
    d, left = divmod(left, 86400)
    h, left = divmod(left, 3600)
    m, s = divmod(left, 60)
    if d:
        return f"{d}d {h}h {m:02d}m"
    if h:
        return f"{h}h {m:02d}m {s:02d}s"
    return f"{m}m {s:02d}s"


def relative(ts_ms: int | float | None, now: int | None = None) -> str:
    """'just now', '3m ago', '2h ago', 'yesterday', '4d ago'."""
    if ts_ms is None:
        return DASH
    now = now_ms() if now is None else now
    diff = (now - ts_ms) / 1000
    if diff < 0:
        diff = 0
    if diff < 10:
        return "just now"
    if diff < 60:
        return f"{int(diff)}s ago"
    if diff < 3600:
        return f"{int(diff // 60)}m ago"
    if diff < 86400:
        return f"{int(diff // 3600)}h ago"
    if diff < 172800:
        return "yesterday"
    return f"{int(diff // 86400)}d ago"


def clock(ts_ms: int | float | None, with_date: bool = False) -> str:
    if ts_ms is None:
        return DASH
    t = time.localtime(ts_ms / 1000)
    return time.strftime("%b %d, %H:%M" if with_date else "%H:%M:%S", t)


def is_today(ts_ms: int | float | None) -> bool:
    if ts_ms is None:
        return False
    t = time.localtime(ts_ms / 1000)
    today = time.localtime()
    return t.tm_year == today.tm_year and t.tm_yday == today.tm_yday


def date_label(ts_ms: int | float | None) -> str:
    if ts_ms is None:
        return DASH
    t = time.localtime(ts_ms / 1000)
    today = time.localtime()
    if t.tm_year == today.tm_year and t.tm_yday == today.tm_yday:
        return "Today " + time.strftime("%H:%M", t)
    if t.tm_year == today.tm_year and t.tm_yday == today.tm_yday - 1:
        return "Yesterday " + time.strftime("%H:%M", t)
    return time.strftime("%a %b %d, %H:%M", t)


def total_tokens(tc: dict | None) -> int | None:
    if not tc:
        return None
    return sum(int(tc.get(k) or 0) for k in ("input", "output", "cache_read", "cache_create"))


def ellipsize_middle(text: str | None, max_len: int = 60) -> str:
    if not text:
        return ""
    if len(text) <= max_len:
        return text
    half = (max_len - 1) // 2
    return text[:half] + "…" + text[-half:]


STATUS_LABELS = {
    "busy": "Working",
    "waiting": "Needs attention",
    "blocked": "Blocked",
    "idle": "Idle",
    "unknown": "Unknown",
    "running": "Running",
    "done": "Done",
}


def status_label(status: str | None) -> str:
    return STATUS_LABELS.get(status or "unknown", (status or "unknown").title())
