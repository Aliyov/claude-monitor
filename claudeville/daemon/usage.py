"""Plan usage limits — only from data Claude Code itself reported.

Source: the optional status-line tee (scripts/claudeville-statusline) saves
the JSON that Claude Code pipes to its status line. That JSON includes
`rate_limits` populated from headers of API responses Claude Code already made,
so reading it costs no tokens and no network requests.
"""
import json
import logging
import os
import time

from . import paths

log = logging.getLogger(__name__)
TEE_NAME = "claudeville-statusline"
# Installs from before the rename point Claude Code at the old name, which
# install.sh keeps as a link to the new script.
TEE_NAMES = (TEE_NAME, "claude-monitor-statusline")


def statusline_installed():
    try:
        with open(paths.CLAUDE_SETTINGS) as f:
            s = json.load(f)
    except (OSError, ValueError):
        return False
    cmd = ((s.get("statusLine") or {}).get("command")) or ""
    return any(n in cmd for n in TEE_NAMES)


class UsageTracker:
    def __init__(self):
        self._mtimes = {}
        self.by_session = {}  # session_id -> (mtime_ms, data)
        self.installed = statusline_installed()
        self._installed_checked = time.time()

    def poll(self):
        changed = False
        now = time.time()
        if now - self._installed_checked > 10:
            inst = statusline_installed()
            changed |= inst != self.installed
            self.installed, self._installed_checked = inst, now
        try:
            entries = list(os.scandir(paths.STATUSLINE_DIR))
        except FileNotFoundError:
            return changed
        for e in entries:
            if not e.name.endswith(".json"):
                continue
            try:
                m = e.stat().st_mtime_ns
            except OSError:
                continue
            if self._mtimes.get(e.path) == m:
                continue
            self._mtimes[e.path] = m
            try:
                with open(e.path) as f:
                    data = json.load(f)
            except (OSError, ValueError):
                continue
            sid = data.get("session_id")
            if not sid:
                continue
            ms = m // 1_000_000
            prev = self.by_session.get(sid)
            if prev is None or prev[0] <= ms:
                self.by_session[sid] = (ms, data)
                changed = True
        return changed

    def cleanup(self, max_age_s=7 * 86400):
        now = time.time()
        try:
            for e in os.scandir(paths.STATUSLINE_DIR):
                if now - e.stat().st_mtime > max_age_s:
                    os.unlink(e.path)
        except OSError:
            pass

    def session_info(self, session_id):
        v = self.by_session.get(session_id)
        if not v:
            return {}
        d = v[1]
        cw = d.get("context_window") or {}
        eff = d.get("effort")
        eff = eff.get("level") if isinstance(eff, dict) else eff
        return {"model": (d.get("model") or {}).get("id"),
                "context_percent": cw.get("used_percentage"),
                "effort": eff if isinstance(eff, str) and eff else None}

    def limits(self):
        """Latest rate limits across sessions; drops windows whose reset time passed."""
        best = None
        for ms, d in self.by_session.values():
            if d.get("rate_limits") and (best is None or ms > best[0]):
                best = (ms, d["rate_limits"])
        out = {"source": "statusline" if best else "none",
               "statusline_installed": self.installed,
               "as_of": best[0] if best else None, "five_hour": None, "seven_day": None}
        if best:
            now = time.time()
            for k in ("five_hour", "seven_day"):
                w = best[1].get(k)
                if isinstance(w, dict) and w.get("used_percentage") is not None:
                    r = w.get("resets_at")
                    if r is None or r > now:
                        out[k] = {"used_percentage": float(w["used_percentage"]), "resets_at": r}
        return out
