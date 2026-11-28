"""Incremental, resumable ingestion of Claude Code transcript JSONL files.

Each file's byte offset is persisted, so after a restart only new bytes are
read. Records are parsed defensively: unknown record types and fields are
ignored, never fatal.
"""
import json
import logging
import os
import re
import time
from datetime import datetime
from pathlib import Path

from . import paths

log = logging.getLogger(__name__)

# Record types that carry nothing the monitor needs. Skipped before JSON
# parsing when the type is the first key (most of them are).
SKIP_TYPES = {
    b"api-request", b"api-request-blob", b"api-request-shape", b"data-flow-records",
    b"mode", b"permission-mode", b"atis-latch", b"file-history-snapshot",
    b"file-history-delta", b"frame-link", b"queue-operation", b"attachment",
    b"session-owner", b"artifact-autoreact-ledger", b"artifact-comment-monitor",
    b"tools-used", b"last-prompt", b"agent-setting", b"cost-state",
}

CHUNK = 4 * 1024 * 1024
_CMD_RE = re.compile(r"<command-name>\s*(/?[\w:.-]+)")


def ts_ms(s):
    if not s:
        return None
    try:
        return int(datetime.fromisoformat(s).timestamp() * 1000)
    except (ValueError, TypeError):
        return None


def project_name(cwd):
    return os.path.basename(cwd.rstrip("/")) if cwd else None


def _short(s, n):
    s = " ".join(str(s).split())
    return s if len(s) <= n else s[: n - 1] + "…"


def summarize_tool(name, inp, max_chars=200, store_commands=True):
    """Return (summary, detail) for a tool_use block. Metadata only."""
    inp = inp if isinstance(inp, dict) else {}
    path = inp.get("file_path") or inp.get("notebook_path") or inp.get("path")
    if name == "Bash" or name == "PowerShell":
        cmd = inp.get("command") or ""
        if not store_commands:
            return (inp.get("description") and _short(inp["description"], 80)) or "command", None
        first = cmd.strip().splitlines()[0] if cmd.strip() else ""
        return _short(first, 80), _short(cmd, max_chars)
    if name in ("Read", "Write", "Edit", "MultiEdit", "NotebookEdit") and path:
        return os.path.basename(path), _short(path, max_chars)
    if name in ("Grep", "Glob"):
        pat = inp.get("pattern") or ""
        return _short(pat, 80), _short(path, max_chars) if path else None
    if name == "WebFetch":
        return _short(inp.get("url", ""), 80), None
    if name == "WebSearch":
        return _short(inp.get("query", ""), 80), None
    if name in ("Agent", "Task"):
        desc = inp.get("description") or inp.get("subagent_type") or "subagent"
        return _short(desc, 80), inp.get("subagent_type")
    if name == "TodoWrite":
        return "update todo list", None
    if name.startswith("mcp__"):
        parts = name.split("__")
        return " · ".join(parts[1:3]), None
    if name == "Skill":
        return _short(inp.get("skill", "skill"), 80), None
    return name, None


class FileState:
    __slots__ = ("path", "offset", "size", "mtime", "inode", "session_id", "agent_id")

    def __init__(self, path, offset=0, size=0, mtime=0.0, inode=None, session_id=None, agent_id=None):
        self.path, self.offset, self.size, self.mtime = path, offset, size, mtime
        self.inode, self.session_id, self.agent_id = inode, session_id, agent_id


def classify(path: Path):
    """Return (session_id, agent_id) for a transcript path, or None."""
    name = path.name
    if not name.endswith(".jsonl"):
        return None
    if path.parent.name == "subagents" and name.startswith("agent-"):
        return path.parent.parent.name, name[len("agent-"):-len(".jsonl")]
    if path.parent.parent == paths.PROJECTS_DIR:
        return name[: -len(".jsonl")], None
    return None


class Ingestor:
    def __init__(self, store, config, emit):
        self.store = store
        self.config = config
        self.emit = emit  # callable(list[event_dict]) for live events
        self.files = {}
        for r in store.x("SELECT path, offset, size, mtime, inode, session_id, agent_id FROM files"):
            self.files[r[0]] = FileState(*r)
        self._agent_meta_mtime = {}

    # -- discovery ----------------------------------------------------
    def scan_tree(self):
        """Return paths of all transcripts that have unread bytes."""
        todo = []
        try:
            projects = list(os.scandir(paths.PROJECTS_DIR))
        except FileNotFoundError:
            return todo
        for pd in projects:
            if not pd.is_dir():
                continue
            try:
                entries = list(os.scandir(pd.path))
            except OSError:
                continue
            for e in entries:
                if e.name.endswith(".jsonl") and e.is_file():
                    if self.needs_read(e.path, e.stat()):
                        todo.append(e.path)
                elif e.is_dir() and e.name != "memory":
                    sub = os.path.join(e.path, "subagents")
                    todo.extend(self.scan_subagents(sub))
        return todo

    def scan_subagents(self, subdir):
        out = []
        try:
            for e in os.scandir(subdir):
                if e.name.endswith(".jsonl"):
                    if self.needs_read(e.path, e.stat()):
                        out.append(e.path)
                elif e.name.endswith(".meta.json"):
                    self._maybe_agent_meta(e.path, e.stat().st_mtime)
        except OSError:
            pass
        return out

    def needs_read(self, path, st=None):
        if st is None:
            try:
                st = os.stat(path)
            except OSError:
                return False
        fs = self.files.get(path)
        if fs is None:
            return True
        if fs.inode is not None and st.st_ino != fs.inode:
            return True
        return st.st_size != fs.offset

    # -- agent metadata ----------------------------------------------
    def _maybe_agent_meta(self, meta_path, mtime):
        if self._agent_meta_mtime.get(meta_path) == mtime:
            return
        self._agent_meta_mtime[meta_path] = mtime
        p = Path(meta_path)
        session_id = p.parent.parent.name
        agent_id = p.name[len("agent-"):-len(".meta.json")]
        try:
            with open(meta_path) as f:
                meta = json.load(f)
        except (OSError, ValueError):
            return
        cur = self.store.x("SELECT finished FROM agents WHERE session_id=? AND agent_id=?",
                           (session_id, agent_id)).fetchone()
        finished = 1 if meta.get("finished") else 0
        model = meta.get("pickedEffortModel") or meta.get("model")
        self._ensure_agent(session_id, agent_id)
        effort = meta.get("effort") if isinstance(meta.get("effort"), str) else None
        built_in = meta.get("isBuiltIn")
        built_in = (1 if built_in else 0) if isinstance(built_in, bool) else None
        self.store.x("UPDATE agents SET type=?, description=?, model=COALESCE(model, ?), finished=?, "
                     "effort=COALESCE(?, effort), built_in=COALESCE(?, built_in) "
                     "WHERE session_id=? AND agent_id=?",
                     (meta.get("agentType"), meta.get("description"), model, finished, effort, built_in,
                      session_id, agent_id))
        if cur is not None and cur[0] == 0 and finished and self._live_session(session_id):
            self._event(session_id, agent_id, int(mtime * 1000), "subagent_end", None,
                        meta.get("description") or "Subagent finished", None, live=True)

    def _ensure_agent(self, session_id, agent_id):
        cur = self.store.x("INSERT OR IGNORE INTO agents(session_id, agent_id) VALUES (?,?)",
                           (session_id, agent_id))
        if cur.rowcount:
            self._ensure_session(session_id)
            self.store.x("UPDATE sessions SET agent_count=agent_count+1 WHERE session_id=?", (session_id,))
            return True
        return False

    def _ensure_session(self, session_id):
        self.store.x("INSERT OR IGNORE INTO sessions(session_id) VALUES (?)", (session_id,))

    # hook set by engine: is this session currently live?
    def _live_session(self, session_id):
        return False

    # -- reading ------------------------------------------------------
    def ingest(self, path, live, max_bytes=CHUNK):
        """Read up to max_bytes of new complete lines. Returns True if more remain."""
        try:
            st = os.stat(path)
        except OSError:
            return False
        fs = self.files.get(path)
        if fs is None:
            ids = classify(Path(path))
            if ids is None:
                return False
            fs = FileState(path, 0, 0, 0.0, st.st_ino, ids[0], ids[1])
            self.files[path] = fs
            if fs.agent_id:
                self._ensure_agent(fs.session_id, fs.agent_id)
                meta = path[: -len(".jsonl")] + ".meta.json"
                try:
                    self._maybe_agent_meta(meta, os.stat(meta).st_mtime)
                except OSError:
                    pass
        if st.st_ino != fs.inode or st.st_size < fs.offset:
            log.info("file replaced/truncated, re-reading: %s", path)
            fs.offset, fs.inode = 0, st.st_ino
        if st.st_size == fs.offset:
            return False

        with open(path, "rb") as f:
            f.seek(fs.offset)
            data = f.read(max_bytes)
            nl = data.rfind(b"\n")
            while nl < 0 and len(data) and fs.offset + len(data) < st.st_size:
                more = f.read(max_bytes)  # a single huge line
                if not more:
                    break
                data += more
                nl = data.rfind(b"\n")
        if nl < 0:
            return False  # partial line still being written
        block = data[: nl + 1]
        self._ctx = _Ctx(fs.session_id, fs.agent_id)
        self.store.begin()
        live_events = []
        self._live_buf = live_events if live else None
        first_line = fs.offset == 0
        for raw in block.split(b"\n"):
            if raw:
                try:
                    self._line(raw)
                except Exception:  # never let one bad record stop ingestion
                    log.debug("bad record in %s", path, exc_info=True)
        if fs.agent_id and first_line and self._ctx.first_ts and live:
            row = self.store.x("SELECT description FROM agents WHERE session_id=? AND agent_id=?",
                               (fs.session_id, fs.agent_id)).fetchone()
            self._event(fs.session_id, fs.agent_id, self._ctx.first_ts, "subagent_start", None,
                        (row and row[0]) or "Subagent started", None)
        self._flush_ctx()
        fs.offset += len(block)
        fs.size, fs.mtime = st.st_size, st.st_mtime
        self.store.x("INSERT OR REPLACE INTO files VALUES (?,?,?,?,?,?,?)",
                     (fs.path, fs.offset, fs.size, fs.mtime, fs.inode, fs.session_id, fs.agent_id))
        self.store.commit()
        self._live_buf = None
        if live_events:
            self.emit(live_events)
        return fs.offset < st.st_size

    # -- record handling ---------------------------------------------
    def _line(self, raw):
        if raw.startswith(b'{"type":"'):
            end = raw.find(b'"', 9)
            if raw[9:end] in SKIP_TYPES:
                return
        o = json.loads(raw)
        if not isinstance(o, dict):
            return
        t = o.get("type")
        c = self._ctx
        if t == "ai-title":
            c.title = o.get("aiTitle") or c.title
            return
        ts = ts_ms(o.get("timestamp"))
        if ts:
            c.first_ts = c.first_ts or ts
            c.last_ts = max(c.last_ts or 0, ts)
        if o.get("cwd"):
            c.cwd = o["cwd"]
        if o.get("gitBranch"):
            c.branch = o["gitBranch"]
        if o.get("version"):
            c.version = o["version"]
        if t == "assistant":
            self._assistant(o, ts)
        elif t == "user":
            self._user(o, ts)
        elif t == "system":
            st = o.get("subtype")
            if st == "turn_duration" and not c.agent_id:
                secs = (o.get("durationMs") or 0) / 1000
                self._event(c.session_id, None, ts, "turn_end", None,
                            f"Turn finished ({_fmt_dur(secs)})", None)
            elif st == "compact_boundary":
                self._event(c.session_id, c.agent_id, ts, "compact", None, "Context compacted", None)

    def _assistant(self, o, ts):
        c = self._ctx
        m = o.get("message") or {}
        model = m.get("model")
        if model and not model.startswith("<"):
            c.model = model
        mid = m.get("id")
        u = m.get("usage")
        if mid and isinstance(u, dict):
            vals = (int(u.get("input_tokens") or 0), int(u.get("output_tokens") or 0),
                    int(u.get("cache_read_input_tokens") or 0), int(u.get("cache_creation_input_tokens") or 0))
            cur = self.store.x("INSERT OR IGNORE INTO messages VALUES (?,?,?,?,?,?,?,?,?)",
                               (mid, c.session_id, c.agent_id, ts, model, *vals))
            if cur.rowcount:
                for i in range(4):
                    c.tok[i] += vals[i]
        if o.get("isApiErrorMessage") or o.get("apiError"):
            kind = o.get("apiErrorType") or o.get("apiErrorStatus") or "API error"
            self._event(c.session_id, c.agent_id, ts, "error", None, f"API error: {kind}", None, is_error=True)
            c.errors += 1
        q = o.get("quotaLimits")
        if isinstance(q, dict) and q.get("status") == "rejected":
            rtype = q.get("rateLimitType") or "limit"
            self.store.kv_set("last_limit_hit", json.dumps(
                {"type": rtype, "resets_at": q.get("resetsAt"), "at": ts}))
            self._event(c.session_id, c.agent_id, ts, "limit", None,
                        f"Usage limit reached ({rtype.replace('_', '-')})", None, is_error=True)
        content = m.get("content")
        if isinstance(content, list):
            priv = self.config["privacy"]
            for b in content:
                if isinstance(b, dict) and b.get("type") == "tool_use":
                    tuid = b.get("id")
                    if tuid and self.store.x("SELECT 1 FROM events WHERE tool_use_id=?", (tuid,)).fetchone():
                        continue
                    name = b.get("name") or "tool"
                    summary, detail = summarize_tool(name, b.get("input"), priv["max_detail_chars"],
                                                     priv["store_commands"])
                    self._event(c.session_id, c.agent_id, ts, "tool", name, summary, detail, tool_use_id=tuid)
                    c.tool_calls += 1

    def _user(self, o, ts):
        c = self._ctx
        m = o.get("message") or {}
        content = m.get("content")
        if isinstance(content, list):
            for b in content:
                if isinstance(b, dict) and b.get("type") == "tool_result" and b.get("is_error"):
                    tuid = b.get("tool_use_id")
                    if tuid:
                        cur = self.store.x("UPDATE events SET is_error=1 WHERE tool_use_id=? AND is_error=0", (tuid,))
                        if cur.rowcount:
                            c.errors += 1
                            if self._live_buf is not None:
                                self._live_buf.append({"update": "tool_error", "tool_use_id": tuid,
                                                       "session_id": c.session_id})
            return
        if c.agent_id or o.get("isMeta") or o.get("isCompactSummary") or o.get("isVisibleInTranscriptOnly"):
            return
        origin = (o.get("origin") or {}).get("kind")
        if origin not in (None, "human"):
            return
        text = content if isinstance(content, str) else ""
        mm = _CMD_RE.search(text[:400])
        summary = f"Command {mm.group(1)}" if mm else "Prompt submitted"
        # Privacy: prompt text is never stored.
        self._event(c.session_id, None, ts, "prompt", None, summary, None)

    def _event(self, session_id, agent_id, ts, kind, tool, summary, detail,
               is_error=False, tool_use_id=None, live=False):
        if ts is None:
            ts = int(time.time() * 1000)
        cur = self.store.x(
            "INSERT INTO events(session_id, agent_id, ts, kind, tool, summary, detail, is_error, tool_use_id) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (session_id, agent_id, ts, kind, tool, summary, detail, int(is_error), tool_use_id))
        ev = {"id": cur.lastrowid, "session_id": session_id, "agent_id": agent_id, "ts": ts,
              "kind": kind, "tool": tool, "summary": summary, "detail": detail, "is_error": bool(is_error)}
        if live and self._live_buf is None:
            self.emit([ev])
        elif self._live_buf is not None:
            self._live_buf.append(ev)
        return ev

    def _flush_ctx(self):
        c = self._ctx
        self._ensure_session(c.session_id)
        if c.agent_id:
            self.store.x(
                "UPDATE agents SET model=COALESCE(?, model), started_at=COALESCE(MIN(started_at, ?), started_at, ?), "
                "last_at=MAX(COALESCE(last_at,0), COALESCE(?,0)), tool_calls=tool_calls+? "
                "WHERE session_id=? AND agent_id=?",
                (c.model, c.first_ts, c.first_ts, c.last_ts, c.tool_calls, c.session_id, c.agent_id))
            # subagent tokens/tools also count toward the parent session totals
            self.store.x(
                "UPDATE sessions SET tool_calls=tool_calls+?, errors=errors+?, in_tok=in_tok+?, out_tok=out_tok+?, "
                "cr_tok=cr_tok+?, cc_tok=cc_tok+? WHERE session_id=?",
                (c.tool_calls, c.errors, *c.tok, c.session_id))
            return
        self.store.x(
            "UPDATE sessions SET cwd=COALESCE(?, cwd), project=COALESCE(?, project), title=COALESCE(?, title), "
            "model=COALESCE(?, model), git_branch=COALESCE(?, git_branch), version=COALESCE(?, version), "
            "started_at=COALESCE(MIN(started_at, ?), started_at, ?), "
            "last_at=MAX(COALESCE(last_at,0), COALESCE(?,0)), "
            "tool_calls=tool_calls+?, errors=errors+?, in_tok=in_tok+?, out_tok=out_tok+?, cr_tok=cr_tok+?, cc_tok=cc_tok+? "
            "WHERE session_id=?",
            (c.cwd, project_name(c.cwd), c.title, c.model, c.branch, c.version, c.first_ts, c.first_ts,
             c.last_ts, c.tool_calls, c.errors, *c.tok, c.session_id))


class _Ctx:
    __slots__ = ("session_id", "agent_id", "title", "cwd", "branch", "version", "model",
                 "first_ts", "last_ts", "tok", "tool_calls", "errors")

    def __init__(self, session_id, agent_id):
        self.session_id, self.agent_id = session_id, agent_id
        self.title = self.cwd = self.branch = self.version = self.model = None
        self.first_ts = self.last_ts = None
        self.tok = [0, 0, 0, 0]
        self.tool_calls = self.errors = 0


def _fmt_dur(secs):
    secs = int(secs)
    if secs < 60:
        return f"{secs}s"
    if secs < 3600:
        return f"{secs // 60}m {secs % 60}s"
    return f"{secs // 3600}h {secs % 3600 // 60}m"
