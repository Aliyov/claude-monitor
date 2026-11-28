"""Core state machine: registry + transcripts + /proc + usage -> snapshot & events."""
import json
import logging
import os
import time

from gi.repository import GLib

from . import paths, queries
from .ingest import project_name
from .office import Office
from .procmon import ProcMon
from .registry import Registry
from .roster import Rosters
from .usage import UsageTracker

log = logging.getLogger(__name__)
from .. import __version__ as VERSION

KNOWN_STATUS = {"busy", "idle", "waiting", "blocked"}


def now_ms():
    return int(time.time() * 1000)


class LiveSession:
    __slots__ = ("pid", "session_id", "entry", "status", "status_since", "busy_since",
                 "current", "agent_current", "cpu", "rss", "procs", "transcript")

    def __init__(self, pid, entry):
        self.pid = pid
        self.session_id = entry["sessionId"]
        self.entry = entry
        self.status = entry.get("status") if entry.get("status") in KNOWN_STATUS else "unknown"
        self.status_since = entry.get("statusUpdatedAt") or now_ms()
        self.busy_since = self.status_since if self.status == "busy" else None
        self.current = None
        self.agent_current = {}
        self.cpu = self.rss = None
        self.procs = 0
        self.transcript = None


class Engine:
    def __init__(self, store, config, ingestor, notifier):
        self.store, self.config, self.ing, self.notifier = store, config, ingestor, notifier
        self.registry = Registry()
        self.procmon = ProcMon()
        self.usage = UsageTracker()
        self.rosters = Rosters()
        self.office = Office(store)
        self.live = {}  # session_id -> LiveSession
        self.started_at = now_ms()
        self.revision = 0
        self._snap_cache = None
        self._dirty = False
        self._pending_events = []
        self.on_snapshot_changed = lambda rev: None
        self.on_events = lambda evs: None
        self._backlog = []
        self._backlog_total = 0
        self._backlog_done = 0
        self._catching_up = True
        self._last_error_notify = {}
        self._projects = {}
        self.ing.emit = self._ingested
        self.ing._live_session = lambda sid: sid in self.live

    # -- lifecycle -----------------------------------------------------
    def start(self):
        self.registry.poll()
        self._sync_live(initial=True)
        self._backlog = self.ing.scan_tree()
        # live sessions' files first, then newest first
        live_files = {ls.transcript for ls in self.live.values() if ls.transcript}
        self._backlog.sort(key=lambda p: (p not in live_files, -_mtime(p)))
        self._backlog_total = len(self._backlog)
        log.info("catch-up: %d files", self._backlog_total)
        GLib.idle_add(self._catch_up_step, priority=GLib.PRIORITY_LOW)
        GLib.timeout_add(1000, self._tick_fast)
        GLib.timeout_add(max(500, int(self.config["sample_interval_ms"])), self._tick_proc)
        GLib.timeout_add_seconds(60, self._tick_slow)
        GLib.timeout_add_seconds(5, self._tick_config)
        self._prune()
        self._sample_proc()
        self.mark_dirty()

    def _catch_up_step(self):
        deadline = time.monotonic() + 0.015  # ~15 ms slices keep D-Bus responsive
        while self._backlog and time.monotonic() < deadline:
            p = self._backlog[0]
            if not self.ing.ingest(p, live=False, max_bytes=1024 * 1024):
                self._backlog.pop(0)
                self._backlog_done += 1
        self.mark_dirty()
        if self._backlog:
            return True
        self._catching_up = False
        self._load_projects()
        log.info("catch-up complete")
        return False

    # -- ticks ---------------------------------------------------------
    def _tick_fast(self):
        try:
            if self.registry.poll():
                self._sync_live()
            else:
                self._check_alive()
            if not self._catching_up:
                for ls in list(self.live.values()):
                    self._poll_session_files(ls)
            if self.usage.poll():
                self.mark_dirty()
        except Exception:
            log.exception("fast tick failed")
        return True

    def _tick_proc(self):
        self._sample_proc()
        return True

    def _tick_slow(self):
        try:
            if not self._catching_up:
                for p in self.ing.scan_tree():
                    while self.ing.ingest(p, live=True):
                        pass
            if time.time() - float(self.store.kv_get("last_prune", "0")) > 86400:
                self._prune()
        except Exception:
            log.exception("slow tick failed")
        return True

    def _tick_config(self):
        if self.config.reload():
            log.info("config reloaded")
        try:
            if self.rosters.changed(sl["cwd"] for sl in self.office.slots if sl.get("cwd")):
                self.mark_dirty()
        except Exception:
            log.exception("roster check failed")
        return True

    def _prune(self):
        self.store.prune(int(self.config["retention_days"]))
        self.store.kv_set("last_prune", str(time.time()))
        self.usage.cleanup()

    # -- live session tracking ----------------------------------------
    def _check_alive(self):
        live_pids = set(self.registry.live())
        if any(ls.pid not in live_pids for ls in self.live.values()):
            self._sync_live()

    def _sync_live(self, initial=False):
        entries = self.registry.live()
        by_sid = {e["sessionId"]: (pid, e) for pid, e in entries.items()}
        changed = False
        for sid in list(self.live):
            if sid not in by_sid:
                ls = self.live.pop(sid)
                changed = True
                self._session_ended(ls)
        for sid, (pid, e) in by_sid.items():
            ls = self.live.get(sid)
            if ls is None:
                ls = LiveSession(pid, e)
                self.live[sid] = ls
                ls.transcript = self._find_transcript(sid, e.get("cwd"))
                self._register_session(ls)
                changed = True
                if not initial:
                    self._emit_events([self._mk_event(sid, None, "session_start", None,
                                                      f"Session started in {project_name(e.get('cwd'))}")])
            elif ls.entry != e:
                old = ls.status
                ls.entry, ls.pid = e, pid
                new = e.get("status") if e.get("status") in KNOWN_STATUS else "unknown"
                if new != old:
                    self._status_changed(ls, old, new, e.get("statusUpdatedAt") or now_ms())
                changed = True
        if changed:
            self._update_office()
            self.mark_dirty()

    def _update_office(self):
        live = []
        for ls in self.live.values():
            e = ls.entry
            info = self.usage.session_info(ls.session_id)
            live.append({"session_id": ls.session_id, "cwd": e.get("cwd"), "project": project_name(e.get("cwd")),
                         "started_at": e.get("startedAt"), "model": info.get("model"),
                         "effort": info.get("effort")})
        return self.office.update(live, now_ms())

    def _register_session(self, ls):
        e = ls.entry
        self.store.x("INSERT OR IGNORE INTO sessions(session_id) VALUES (?)", (ls.session_id,))
        self.store.x("UPDATE sessions SET cwd=COALESCE(cwd, ?), project=COALESCE(project, ?), "
                     "started_at=COALESCE(started_at, ?), version=COALESCE(?, version), ended_at=NULL "
                     "WHERE session_id=?",
                     (e.get("cwd"), project_name(e.get("cwd")), e.get("startedAt"), e.get("version"),
                      ls.session_id))
        self._projects[ls.session_id] = project_name(e.get("cwd"))

    def _session_ended(self, ls):
        ts = now_ms()
        self.store.x("UPDATE sessions SET ended_at=? WHERE session_id=?", (ts, ls.session_id))
        ev = self._mk_event(ls.session_id, None, "session_end", None, "Session ended")
        self._emit_events([ev])

    def _find_transcript(self, sid, cwd):
        if cwd:
            p = paths.project_dir_for_cwd(cwd) / f"{sid}.jsonl"
            if p.exists():
                return str(p)
        for fs in self.ing.files.values():
            if fs.session_id == sid and not fs.agent_id:
                return fs.path
        try:
            for d in os.scandir(paths.PROJECTS_DIR):
                p = os.path.join(d.path, f"{sid}.jsonl")
                if os.path.exists(p):
                    return p
        except OSError:
            pass
        # transcript may not exist yet (no message sent); retry later
        return str(paths.project_dir_for_cwd(cwd) / f"{sid}.jsonl") if cwd else None

    def _poll_session_files(self, ls):
        if ls.transcript:
            if self.ing.needs_read(ls.transcript):
                while self.ing.ingest(ls.transcript, live=True):
                    pass
            sub = os.path.join(ls.transcript[:-len(".jsonl")], "subagents")
            for p in self.ing.scan_subagents(sub):
                while self.ing.ingest(p, live=True):
                    pass

    def _status_changed(self, ls, old, new, ts):
        ls.status, ls.status_since = new, ts
        n = self.config["notifications"]
        project = self._projects.get(ls.session_id) or "Claude"
        title = self._title(ls.session_id)
        ev = None
        if new == "busy":
            ls.busy_since = ts
        elif new == "idle":
            busy_for = (ts - ls.busy_since) / 1000 if ls.busy_since else 0
            ls.busy_since = None
            ls.current = None
            ls.agent_current.clear()
            if old == "busy" and n["enabled"] and n["on_finish"] and busy_for >= n["min_busy_seconds"]:
                self.notifier.send(f"s:{ls.session_id}", f"✓ {project}: Claude finished",
                                   f"{title + ' — ' if title else ''}worked for {_fmt(busy_for)}")
        elif new in ("waiting", "blocked"):
            reason = ls.entry.get("waitingFor") or ("blocked" if new == "blocked" else "input needed")
            ev = self._mk_event(ls.session_id, None, "status", None, f"Waiting: {reason}",
                                is_error=new == "blocked")
            if n["enabled"] and n["on_attention"]:
                self.notifier.send(f"s:{ls.session_id}", f"⏳ {project}: Claude needs your attention",
                                   f"{reason.capitalize()}" + (f" — {title}" if title else ""))
        if ev:
            self._emit_events([ev])

    def _title(self, sid):
        r = self.store.x("SELECT title FROM sessions WHERE session_id=?", (sid,)).fetchone()
        return r[0] if r else None

    # -- proc ------------------------------------------------------------
    def _sample_proc(self):
        if not self.live:
            return
        res = self.procmon.sample(ls.pid for ls in self.live.values())
        for ls in self.live.values():
            cpu, rss, n = res.get(ls.pid, (None, None, 0))
            if (cpu, rss, n) != (ls.cpu, ls.rss, ls.procs):
                ls.cpu, ls.rss, ls.procs = cpu, rss, n
                self._dirty_quiet()

    # -- events ------------------------------------------------------------
    def _mk_event(self, sid, agent_id, kind, tool, summary, detail=None, is_error=False):
        ts = now_ms()
        cur = self.store.x("INSERT INTO events(session_id, agent_id, ts, kind, tool, summary, detail, is_error) "
                           "VALUES (?,?,?,?,?,?,?,?)", (sid, agent_id, ts, kind, tool, summary, detail, int(is_error)))
        return {"id": cur.lastrowid, "session_id": sid, "agent_id": agent_id, "ts": ts, "kind": kind,
                "tool": tool, "summary": summary, "detail": detail, "is_error": is_error}

    def _ingested(self, evs):
        out = []
        n = self.config["notifications"]
        for ev in evs:
            if "update" in ev:
                continue  # tool_error updates are reflected in counts; clients refetch
            ls = self.live.get(ev["session_id"])
            if ls is not None:
                if ev["kind"] == "tool":
                    cur = {"tool": ev["tool"], "summary": ev["summary"], "at": ev["ts"]}
                    if ev["agent_id"]:
                        ls.agent_current[ev["agent_id"]] = cur
                    else:
                        ls.current = cur
                elif ev["kind"] == "turn_end":
                    ls.current = None
                elif ev["kind"] == "subagent_end":
                    ls.agent_current.pop(ev["agent_id"], None)
            if ev["kind"] in ("error", "limit") and n["enabled"] and n["on_error"]:
                last = self._last_error_notify.get(ev["session_id"], 0)
                if ev["ts"] - last > 60_000:
                    self._last_error_notify[ev["session_id"]] = ev["ts"]
                    proj = self._projects.get(ev["session_id"]) or "Claude"
                    self.notifier.send(f"e:{ev['session_id']}", f"⚠ {proj}: {ev['summary']}",
                                       self._title(ev["session_id"]) or "")
            out.append(ev)
        if out:
            self._emit_events(out)
            self.mark_dirty()

    def _emit_events(self, evs):
        for ev in evs:
            if ev["session_id"] not in self._projects:
                r = self.store.x("SELECT project FROM sessions WHERE session_id=?", (ev["session_id"],)).fetchone()
                self._projects[ev["session_id"]] = r[0] if r else None
            ev["project"] = self._projects.get(ev["session_id"])
        self._pending_events.extend(evs)
        self._schedule_flush()

    def _load_projects(self):
        self._projects.update({sid: p for sid, p in self.store.x("SELECT session_id, project FROM sessions")})

    # -- change notification (coalesced to <= 1 Hz) -------------------------
    def mark_dirty(self):
        self._snap_cache = None
        self._dirty = True
        self._schedule_flush()

    def _dirty_quiet(self):
        self.mark_dirty()

    def _schedule_flush(self):
        if getattr(self, "_flush_src", None) is None:
            self._flush_src = GLib.timeout_add(1000 if self._last_flush_recent() else 50, self._flush)

    def _last_flush_recent(self):
        return time.monotonic() - getattr(self, "_last_flush", 0) < 1.0

    def _flush(self):
        self._flush_src = None
        self._last_flush = time.monotonic()
        if self._pending_events:
            evs, self._pending_events = self._pending_events[-200:], []
            self.on_events(evs)
        if self._dirty:
            self._dirty = False
            self.revision += 1
            self.on_snapshot_changed(self.revision)
        return False

    # -- read API ------------------------------------------------------------
    def snapshot(self):
        if self._snap_cache is not None:
            return self._snap_cache
        sessions = []
        busy = waiting = agents_running = 0
        cpu_total = 0.0
        rss_total = 0
        for ls in sorted(self.live.values(), key=lambda s: -(s.entry.get("startedAt") or 0)):
            r = self.store.x("SELECT * FROM sessions WHERE session_id=?", (ls.session_id,)).fetchone()
            e = ls.entry
            info = self.usage.session_info(ls.session_id)
            ags = queries.agents(self.store, ls.session_id, True, ls.agent_current)
            agents_running += sum(1 for a in ags if a["status"] == "running")
            busy += ls.status == "busy"
            waiting += ls.status in ("waiting", "blocked")
            cpu_total += ls.cpu or 0
            rss_total += ls.rss or 0
            sessions.append({
                "session_id": ls.session_id, "pid": ls.pid, "name": e.get("name"),
                "title": r["title"] if r else None,
                "project": project_name(e.get("cwd")), "cwd": e.get("cwd"),
                "git_branch": r["git_branch"] if r else None,
                "kind": e.get("kind"), "entrypoint": e.get("entrypoint"), "version": e.get("version"),
                "model": info.get("model") or (r["model"] if r else None),
                "context_percent": info.get("context_percent"),
                "effort": info.get("effort"),
                "status": ls.status, "status_since": ls.status_since,
                "waiting_for": e.get("waitingFor") if ls.status == "waiting" else None,
                "started_at": e.get("startedAt"), "last_activity_at": r["last_at"] if r else None,
                "current": ls.current if ls.status != "idle" else None,
                "cpu_percent": ls.cpu, "rss_bytes": ls.rss, "proc_count": ls.procs,
                "tokens": queries.tokens(r) if r else {"input": 0, "output": 0, "cache_read": 0, "cache_create": 0},
                "tool_calls": r["tool_calls"] if r else 0, "errors": r["errors"] if r else 0,
                "agents": ags,
            })
        self._update_office()
        office = {"departments": self.office.departments(self.rosters)}
        usage = self.usage.limits()
        lh = self.store.kv_get("last_limit_hit")
        usage["last_limit_hit"] = json.loads(lh) if lh else None
        t = time.time()
        lt = time.localtime(t)
        midnight = int(time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1)) * 1000)
        usage["tokens_5h"] = queries.token_sum(self.store, int((t - 5 * 3600) * 1000))
        usage["tokens_today"] = queries.token_sum(self.store, midnight)
        self._snap_cache = json.dumps({
            "revision": self.revision, "generated_at": now_ms(),
            "daemon": {"version": VERSION, "started_at": self.started_at,
                       "indexing": {"active": self._catching_up, "files_done": self._backlog_done,
                                    "files_total": self._backlog_total}},
            "usage": usage, "sessions": sessions, "office": office,
            "totals": {"live": len(sessions), "busy": busy, "waiting": waiting,
                       "agents_running": agents_running,
                       "cpu_percent": round(cpu_total, 1), "rss_bytes": rss_total},
        }, separators=(",", ":"))
        return self._snap_cache

    def live_ids(self):
        return set(self.live)

    def projects(self):
        return self._projects


def _mtime(p):
    try:
        return os.stat(p).st_mtime
    except OSError:
        return 0


def _fmt(secs):
    secs = int(secs)
    if secs < 60:
        return f"{secs}s"
    if secs < 3600:
        return f"{secs // 60}m {secs % 60:02d}s"
    return f"{secs // 3600}h {secs % 3600 // 60:02d}m"
