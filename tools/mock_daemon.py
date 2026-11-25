#!/usr/bin/env python3
"""Mock Claude Monitor daemon for UI development.

Owns ``io.github.ClaudeMonitor`` on the session bus and serves *obviously
fake* fixture data (projects are named ``mock-*``) following docs/CONTRACT.md.
Emits SnapshotChanged / EventsAdded every few seconds.

    python3 tools/mock_daemon.py            # with usage data
    python3 tools/mock_daemon.py --no-usage # simulate missing status-line integration

Never run this while the real daemon is running (it would fail to own the name).
"""

from __future__ import annotations

import json
import random
import sys
import time

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

BUS_NAME = "io.github.ClaudeMonitor"
PATH = "/io/github/ClaudeMonitor"
IFACE_XML = """
<node>
  <interface name="io.github.ClaudeMonitor1">
    <method name="GetSnapshot"><arg type="s" direction="out"/></method>
    <method name="GetSessionEvents"><arg type="s" direction="in"/><arg type="x" direction="in"/><arg type="u" direction="in"/><arg type="s" direction="out"/></method>
    <method name="GetTimeline"><arg type="x" direction="in"/><arg type="u" direction="in"/><arg type="s" direction="out"/></method>
    <method name="GetHistory"><arg type="s" direction="in"/><arg type="u" direction="in"/><arg type="u" direction="in"/><arg type="s" direction="out"/></method>
    <method name="GetSession"><arg type="s" direction="in"/><arg type="s" direction="out"/></method>
    <method name="GetStats"><arg type="u" direction="in"/><arg type="s" direction="out"/></method>
    <method name="GetConfig"><arg type="s" direction="out"/></method>
    <method name="SetConfig"><arg type="s" direction="in"/><arg type="s" direction="out"/></method>
    <signal name="SnapshotChanged"><arg type="x"/></signal>
    <signal name="EventsAdded"><arg type="s"/></signal>
  </interface>
</node>
"""

NO_USAGE = "--no-usage" in sys.argv
rng = random.Random(7)
NOW = lambda: int(time.time() * 1000)  # noqa: E731
START = NOW()

TOOLS = [
    ("Bash", ["npm test", "pytest -q tests/", "git status", "cargo build --release", "ls -la src/"]),
    ("Read", ["src/main.py", "README.md", "package.json", "src/lib/store.ts"]),
    ("Edit", ["src/app.py", "src/components/Card.tsx", "docs/notes.md"]),
    ("Write", ["src/new_module.py", "tests/test_api.py"]),
    ("Grep", ["TODO", "def handle_", "useEffect"]),
    ("Glob", ["**/*.py", "src/**/*.ts"]),
    ("WebFetch", ["https://docs.example.org/api"]),
    ("Agent", ["Explore the codebase", "Write unit tests"]),
]

TOKENS = lambda s: {"input": s * 3, "output": s, "cache_read": s * 40, "cache_create": s * 5}  # noqa: E731

config = {
    "notifications": {"enabled": True, "on_finish": True, "on_error": True, "on_attention": True, "min_busy_seconds": 20},
    "privacy": {"store_commands": True, "max_detail_chars": 200},
    "retention_days": 180,
    "sample_interval_ms": 2000,
}

sessions = [
    {
        "session_id": "mock-0001-aaaa", "pid": 40001, "name": "mock-alpha", "title": "Refactor storage layer (mock)",
        "project": "mock-alpha", "cwd": "/home/user/Projects/mock-alpha", "git_branch": "main",
        "kind": "interactive", "entrypoint": "cli", "version": "2.1.332", "model": "claude-opus-5-5",
        "context_percent": 41.0, "status": "busy", "status_since": START - 95000, "started_at": START - 3600_000,
        "last_activity_at": START, "current": {"tool": "Bash", "summary": "pytest -q tests/", "at": START},
        "cpu_percent": 14.2, "rss_bytes": 412 << 20, "proc_count": 4, "tokens": TOKENS(52000),
        "tool_calls": 214, "errors": 2,
        "agents": [
            {"agent_id": "amock1", "type": "Explore", "description": "Map storage call sites", "model": "haiku",
             "status": "running", "started_at": START - 60000, "last_activity_at": START,
             "current": {"tool": "Grep", "summary": "store.get(", "at": START}, "tool_calls": 18},
            {"agent_id": "amock2", "type": "general-purpose", "description": "Write migration tests", "model": "opus",
             "status": "done", "started_at": START - 900000, "last_activity_at": START - 300000,
             "current": None, "tool_calls": 41},
        ],
    },
    {
        "session_id": "mock-0002-bbbb", "pid": 40002, "name": "mock-beta", "title": "Fix login redirect bug (mock)",
        "project": "mock-beta", "cwd": "/home/user/Projects/mock-beta", "git_branch": "fix/login",
        "kind": "interactive", "entrypoint": "cli", "version": "2.1.332", "model": "claude-fable-5-2", "context_percent": None,
        "status": "waiting", "status_since": START - 40000, "started_at": START - 1200_000,
        "last_activity_at": START - 40000, "current": {"tool": "Bash", "summary": "rm -rf build/", "at": START - 40000},
        "cpu_percent": 0.4, "rss_bytes": 298 << 20, "proc_count": 1, "tokens": TOKENS(8000),
        "tool_calls": 37, "errors": 0, "agents": [],
    },
    {
        "session_id": "mock-0003-cccc", "pid": 40003, "name": "mock-gamma", "title": None,
        "project": "mock-gamma", "cwd": "/home/user/mock-gamma", "git_branch": None,
        "kind": "interactive", "entrypoint": "cli", "version": "2.1.330", "model": None, "context_percent": None,
        "status": "idle", "status_since": START - 600000, "started_at": START - 7200_000,
        "last_activity_at": START - 600000, "current": None,
        "cpu_percent": 0.0, "rss_bytes": 251 << 20, "proc_count": 1, "tokens": TOKENS(3100),
        "tool_calls": 12, "errors": 0, "agents": [],
    },
]

events: list[dict] = []
_next_id = 1


def make_event(sess: dict, ts: int, kind: str | None = None) -> dict:
    global _next_id
    tool, samples = rng.choice(TOOLS)
    kind = kind or rng.choices(["tool", "tool", "tool", "tool", "error", "prompt", "turn_end"], k=1)[0]
    summary = rng.choice(samples)
    ev = {
        "id": _next_id, "session_id": sess["session_id"],
        "agent_id": rng.choice([None, None, None, "amock1"]) if sess["agents"] else None,
        "project": sess["project"], "ts": ts, "kind": kind,
        "tool": tool if kind in ("tool", "error") else None,
        "summary": summary if kind in ("tool", "error") else {
            "prompt": "User prompt", "turn_end": "Turn finished in 42s"}.get(kind, kind),
        "detail": ("/home/user/Projects/" + sess["project"] + "/" + summary) if tool in ("Read", "Edit", "Write") else None,
        "is_error": kind == "error",
    }
    if kind == "error":
        ev["summary"] = f"{summary} — exit code 1"
    _next_id += 1
    return ev


# Seed history of events: ~600 over the last 3 hours.
for i in range(600):
    s = rng.choice(sessions)
    events.append(make_event(s, START - (600 - i) * 18000))

history = []
for i in range(57):
    proj = rng.choice(["mock-alpha", "mock-beta", "mock-gamma", "mock-delta", "mock-epsilon"])
    started = START - (i + 1) * 5 * 3600_000 - rng.randint(0, 3600_000)
    dur = rng.randint(120_000, 3 * 3600_000)
    history.append({
        "session_id": f"mock-h{i:03d}", "project": proj, "cwd": f"/home/user/Projects/{proj}",
        "title": rng.choice(["Add dark mode (mock)", "Investigate flaky test (mock)", "Write docs (mock)",
                              None, "Upgrade dependencies (mock)", "Profile hot path (mock)"]),
        "model": rng.choice(["claude-opus-5-5", "claude-fable-5-2", "claude-sonnet-5-5"]),
        "started_at": started, "ended_at": started + dur, "duration_ms": dur,
        "tool_calls": rng.randint(3, 400), "errors": rng.randint(0, 6), "agent_count": rng.randint(0, 5),
        "tokens": TOKENS(rng.randint(500, 90000)), "live": False,
    })

revision = 1


def snapshot() -> dict:
    now_s = time.time()
    usage = {
        "source": "none" if NO_USAGE else "statusline",
        "statusline_installed": not NO_USAGE,
        "as_of": None if NO_USAGE else NOW() - 45000,
        "five_hour": None if NO_USAGE else {"used_percentage": 37.0 + (revision % 20), "resets_at": int(now_s + 2 * 3600 + 1234)},
        "seven_day": None if NO_USAGE else {"used_percentage": 62.0, "resets_at": int(now_s + 3 * 86400 + 5000)},
        "last_limit_hit": {"type": "five_hour", "resets_at": int(now_s - 3600 * 9), "at": NOW() - 3600_000 * 12},
        "tokens_5h": TOKENS(63000), "tokens_today": TOKENS(141000),
    }
    live = sessions
    return {
        "revision": revision, "generated_at": NOW(),
        "daemon": {"version": "0.1.0-mock", "started_at": START,
                   "indexing": {"active": revision < 6, "files_done": min(166, revision * 30), "files_total": 166}},
        "usage": usage,
        "sessions": live,
        "totals": {
            "live": len(live), "busy": sum(s["status"] == "busy" for s in live),
            "waiting": sum(s["status"] == "waiting" for s in live),
            "agents_running": sum(a["status"] == "running" for s in live for a in s["agents"]),
            "cpu_percent": round(sum(s["cpu_percent"] or 0 for s in live), 1),
            "rss_bytes": sum(s["rss_bytes"] or 0 for s in live),
        },
    }


def stats(days: int) -> dict:
    r = random.Random(days)
    out_days = []
    for d in range(days - 1, -1, -1):
        t = time.localtime(time.time() - d * 86400)
        scale = r.randint(0, 120000) if r.random() > 0.15 else 0
        out_days.append({"date": time.strftime("%Y-%m-%d", t), "tokens": TOKENS(scale),
                         "sessions": r.randint(0, 8) if scale else 0, "tool_calls": scale // 300})
    return {
        "days": out_days,
        "by_model": {"claude-opus-5-5": TOKENS(900000), "claude-fable-5-2": TOKENS(400000), "claude-haiku-5-5": TOKENS(120000)},
        "by_tool": {"Bash": 1520, "Read": 1210, "Edit": 840, "Grep": 420, "Glob": 300, "Write": 210, "Agent": 64, "WebFetch": 31},
        "by_project": [{"project": p, "sessions": r.randint(2, 30), "tool_calls": r.randint(100, 2000), "output_tokens": r.randint(10000, 400000)}
                       for p in ["mock-alpha", "mock-beta", "mock-gamma", "mock-delta", "mock-epsilon"]],
        "hourly": [max(0, int(80 * (1 - abs(h - 15) / 9)) + r.randint(0, 12)) for h in range(24)],
    }


def page(evs: list[dict], before_id: int, limit: int) -> list[dict]:
    newest_first = sorted(evs, key=lambda e: e["id"], reverse=True)
    if before_id:
        newest_first = [e for e in newest_first if e["id"] < before_id]
    return newest_first[: limit or 100]


def handle(conn, sender, path, iface, method, params, invocation):
    args = params.unpack()
    if method == "GetSnapshot":
        res = snapshot()
    elif method == "GetSessionEvents":
        sid, before, limit = args
        res = {"events": page([e for e in events if e["session_id"] == sid], before, limit)}
    elif method == "GetTimeline":
        before, limit = args
        res = {"events": page(events, before, limit)}
    elif method == "GetHistory":
        q, off, lim = args
        items = [h for h in history if not q or q.lower() in (h["project"] + (h["title"] or "") + h["cwd"]).lower()]
        res = {"total": len(items), "sessions": items[off: off + (lim or 50)]}
    elif method == "GetSession":
        sid = args[0]
        h = next((x for x in history if x["session_id"] == sid), None)
        live = next((x for x in sessions if x["session_id"] == sid), None)
        if h is None and live is not None:
            h = {k: live.get(k) for k in ("session_id", "project", "cwd", "title", "model", "started_at", "tool_calls", "errors", "tokens")}
            h.update(ended_at=None, duration_ms=None, agent_count=len(live["agents"]), live=True)
        if h is None:
            res = {"error": "not_found"}
        else:
            res = dict(h)
            res["agents"] = live["agents"] if live else [
                {"agent_id": "ahist1", "type": "Explore", "description": "Survey the repo", "model": "haiku",
                 "status": "done", "started_at": h["started_at"], "last_activity_at": h["started_at"] + 60000,
                 "current": None, "tool_calls": 22}]
            res["tool_counts"] = {"Bash": 40, "Read": 33, "Edit": 21, "Grep": 9, "Write": 4}
            res["files_touched"] = [{"path": f"{h['cwd']}/src/file_{i}.py", "count": 10 - i} for i in range(8)]
    elif method == "GetStats":
        res = stats(args[0] or 30)
    elif method == "GetConfig":
        res = config
    elif method == "SetConfig":
        config.update(json.loads(args[0]))
        print("SetConfig:", json.dumps(config), flush=True)
        res = {"ok": True}
    else:
        invocation.return_dbus_error("org.freedesktop.DBus.Error.UnknownMethod", method)
        return
    invocation.return_value(GLib.Variant("(s)", (json.dumps(res),)))


conn_ref: list[Gio.DBusConnection] = []


def tick() -> bool:
    global revision
    if not conn_ref:
        return True
    conn = conn_ref[0]
    revision += 1
    s = sessions[0]
    s["cpu_percent"] = round(max(0.5, min(95, s["cpu_percent"] + rng.uniform(-6, 6))), 1)
    s["rss_bytes"] = max(200 << 20, s["rss_bytes"] + rng.randint(-8, 9) * (1 << 20))
    new = [make_event(s, NOW(), "tool")]
    s["current"] = {"tool": new[0]["tool"], "summary": new[0]["summary"], "at": new[0]["ts"]}
    s["last_activity_at"] = new[0]["ts"]
    s["tool_calls"] += 1
    s["agents"][0]["tool_calls"] += 1
    if revision % 5 == 0:
        new.append(make_event(sessions[1], NOW()))
    events.extend(new)
    if revision % 12 == 0:  # flip third session busy/idle to exercise status transitions
        g = sessions[2]
        g["status"] = "busy" if g["status"] == "idle" else "idle"
        g["status_since"] = NOW()
        g["cpu_percent"] = 22.0 if g["status"] == "busy" else 0.0
    conn.emit_signal(None, PATH, "io.github.ClaudeMonitor1", "EventsAdded", GLib.Variant("(s)", (json.dumps({"events": new}),)))
    conn.emit_signal(None, PATH, "io.github.ClaudeMonitor1", "SnapshotChanged", GLib.Variant("(x)", (revision,)))
    return True


def on_bus(conn, name):
    node = Gio.DBusNodeInfo.new_for_xml(IFACE_XML)
    conn.register_object(PATH, node.interfaces[0], handle, None, None)
    conn_ref.append(conn)


def on_name(conn, name):
    print(f"mock daemon owns {name} (usage={'off' if NO_USAGE else 'on'})", flush=True)


def on_lost(conn, name):
    print("could not own bus name — is the real daemon running?", file=sys.stderr)
    loop.quit()


Gio.bus_own_name(Gio.BusType.SESSION, BUS_NAME, Gio.BusNameOwnerFlags.NONE, on_bus, on_name, on_lost)
GLib.timeout_add_seconds(3, tick)
loop = GLib.MainLoop()
try:
    loop.run()
except KeyboardInterrupt:
    pass
