"""Reads Claude Code's own live-session registry (~/.claude/sessions/<pid>.json)."""
import json
import logging
import os

from . import paths

log = logging.getLogger(__name__)


def proc_starttime(pid):
    """Field 22 of /proc/<pid>/stat (clock ticks since boot), or None if gone."""
    try:
        with open(f"/proc/{pid}/stat", "rb") as f:
            data = f.read()
    except OSError:
        return None
    # comm may contain spaces/parens: split after the last ')'
    rest = data[data.rfind(b")") + 2:].split()
    try:
        return int(rest[19])
    except (IndexError, ValueError):
        return None


class Registry:
    """Polls the registry directory; cheap (one listdir + stat per file)."""

    def __init__(self):
        self.entries = {}  # pid -> dict
        self._mtimes = {}

    def poll(self):
        """Return True if the set of live entries or any entry changed."""
        changed = False
        seen = set()
        try:
            it = list(os.scandir(paths.SESSIONS_DIR))
        except FileNotFoundError:
            it = []
        for e in it:
            name = e.name
            if not name.endswith(".json") or not name[:-5].isdigit():
                continue
            pid = int(name[:-5])
            seen.add(pid)
            try:
                mtime = e.stat().st_mtime_ns
            except OSError:
                continue
            if self._mtimes.get(pid) == mtime and pid in self.entries:
                continue
            try:
                with open(e.path) as f:
                    data = json.load(f)
            except (OSError, ValueError):
                continue  # being rewritten; retry next poll
            self._mtimes[pid] = mtime
            if self.entries.get(pid) != data:
                self.entries[pid] = data
                changed = True
        for pid in list(self.entries):
            if pid not in seen:
                del self.entries[pid]
                self._mtimes.pop(pid, None)
                changed = True
        return changed

    def live(self):
        """Entries whose process is alive and is the same process (PID reuse safe)."""
        out = {}
        for pid, e in self.entries.items():
            st = proc_starttime(pid)
            if st is None:
                continue
            want = e.get("procStart")
            if want is not None and str(st) != str(want):
                continue
            if e.get("sessionId"):
                out[pid] = e
        return out
