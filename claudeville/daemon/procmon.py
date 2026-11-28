"""CPU / RSS sampling of Claude session process trees via /proc (no psutil needed)."""
import os
import time

CLK_TCK = os.sysconf("SC_CLK_TCK")
PAGE = os.sysconf("SC_PAGE_SIZE")


def _stat(pid):
    try:
        with open(f"/proc/{pid}/stat", "rb") as f:
            data = f.read()
    except OSError:
        return None
    rest = data[data.rfind(b")") + 2:].split()
    try:
        # utime(14) stime(15) starttime(22) rss(24) -> indexes in rest: 11,12,19,21
        return int(rest[11]) + int(rest[12]), int(rest[19]), int(rest[21]) * PAGE
    except (IndexError, ValueError):
        return None


def descendants(pid):
    out = []
    stack = [pid]
    seen = {pid}
    while stack:
        p = stack.pop()
        try:
            tasks = os.listdir(f"/proc/{p}/task")
        except OSError:
            continue
        for t in tasks:
            try:
                with open(f"/proc/{p}/task/{t}/children") as f:
                    kids = f.read().split()
            except OSError:
                continue
            for k in kids:
                k = int(k)
                if k not in seen:
                    seen.add(k)
                    out.append(k)
                    stack.append(k)
    return out


class ProcMon:
    def __init__(self):
        self._prev = {}  # (pid, starttime) -> ticks
        self._prev_t = None

    def sample(self, roots):
        """roots: iterable of pids. Returns {root: (cpu_percent|None, rss_bytes, proc_count)}."""
        now = time.monotonic()
        dt = (now - self._prev_t) if self._prev_t else None
        cur = {}
        result = {}
        for root in roots:
            ticks_delta = 0
            rss = 0
            count = 0
            have_prev = dt is not None
            for p in [root, *descendants(root)]:
                s = _stat(p)
                if s is None:
                    continue
                ticks, start, r = s
                key = (p, start)
                cur[key] = ticks
                prev = self._prev.get(key)
                if prev is not None:
                    ticks_delta += ticks - prev
                elif p == root:
                    have_prev = False
                rss += r
                count += 1
            cpu = round(100.0 * ticks_delta / CLK_TCK / dt, 1) if have_prev and dt else None
            result[root] = (cpu, rss, count)
        self._prev = cur
        self._prev_t = now
        return result
