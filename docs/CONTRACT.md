# Claude Monitor — Interface Contract (v1)

This file is the single source of truth shared by the daemon, the dashboard
and the GNOME Shell extension. Change it deliberately and update all three.

## Principles

- The daemon is the only component that reads `~/.claude`. It never writes there.
- UIs are thin: they render what the daemon reports and never invent numbers.
- Any value the daemon cannot know is `null`. UIs render `null` as "—" or
  "Unavailable", never as 0.
- All timestamps are **milliseconds since epoch** unless the field name ends
  in `_s` or is `resets_at` (seconds, copied verbatim from Claude Code).

## Paths

| Purpose | Path |
|---|---|
| Database (daemon-owned) | `~/.local/share/claude-monitor/monitor.db` |
| User config (JSON, daemon watches it) | `~/.config/claude-monitor/config.json` |
| Status-line drops (optional tee) | `~/.local/state/claude-monitor/statusline/<session_id>.json` |
| Hook event drops (optional) | `~/.local/state/claude-monitor/hooks/` |

## D-Bus (session bus)

- Bus name: `io.github.ClaudeMonitor`
- Object path: `/io/github/ClaudeMonitor`
- Interface: `io.github.ClaudeMonitor1`

All methods return one JSON string (`s`). Keeping the payload as JSON makes
GJS and Python clients trivial and the interface easy to version.

| Method | Args | Returns |
|---|---|---|
| `GetSnapshot` | — | `Snapshot` |
| `GetSessionEvents` | `s session_id, x before_id, u limit` | `{"events":[Event]}` newest first by `ts`; `before_id` = id of the oldest event already shown (cursor), `0` = latest |
| `GetTimeline` | `x before_id, u limit` | `{"events":[Event]}` across all sessions, newest first |
| `GetHistory` | `s query, u offset, u limit` | `{"total":n,"sessions":[HistoryItem]}` newest first; query matches project/title/cwd |
| `GetSession` | `s session_id` | `SessionDetail` or `{"error":"not_found"}` |
| `GetStats` | `u days` | `Stats` |
| `GetConfig` | — | config object |
| `SetConfig` | `s json` | `{"ok":true}` — daemon persists & applies |

| Signal | Args | Meaning |
|---|---|---|
| `SnapshotChanged` | `x revision` | Snapshot changed; coalesced to ≤ 1 Hz. Clients re-call `GetSnapshot`. |
| `EventsAdded` | `s json` | `{"events":[Event]}` batch of new events, ≤ 1 Hz, oldest first |

Clients must tolerate the daemon being absent (show a "Monitor service not
running" state) and reconnect when the name appears (`Gio.bus_watch_name`).

## Objects

```jsonc
// Snapshot
{
  "revision": 42,
  "generated_at": 1795620000000,
  "daemon": {"version": "0.1.0", "started_at": 1795610000000,
             "indexing": {"active": true, "files_done": 40, "files_total": 166}},
  "usage": Usage,
  "sessions": [Session],          // live sessions only (process alive)
  "totals": {"live": 2, "busy": 1, "waiting": 0, "agents_running": 3,
             "cpu_percent": 12.5, "rss_bytes": 734003200}
}

// Usage — plan limits. Only real data; null when not known.
{
  "source": "statusline" | "none",
  "statusline_installed": false,
  "as_of": 1795620000000 | null,                  // when Claude Code last reported limits
  "five_hour": {"used_percentage": 37.0, "resets_at": 1795630000} | null,
  "seven_day": {"used_percentage": 12.0, "resets_at": 1796000000} | null,
  "last_limit_hit": {"type": "five_hour", "resets_at": 1795600200, "at": 1795580000000} | null,
  "tokens_5h":  TokenCounts,  // exact, summed from local transcripts (rolling 5 h)
  "tokens_today": TokenCounts // exact, local calendar day
}

// TokenCounts
{"input": 0, "output": 0, "cache_read": 0, "cache_create": 0}

// Session (live)
{
  "session_id": "uuid", "pid": 107202, "name": "claude-monitor-8b",
  "title": "Build Claude Monitor" | null,     // ai-title from transcript
  "project": "Claude_Monitor", "cwd": "/home/...", "git_branch": "main" | null,
  "kind": "interactive", "entrypoint": "cli", "version": "2.1.332",
  "model": "claude-opus-5-5" | null,
  "context_percent": 41.0 | null, // context window used, only with status-line tee
  "status": "busy" | "idle" | "waiting" | "blocked" | "unknown",
  "status_since": 1795620000000,
  "waiting_for": "input needed" | "permission" | null,  // Claude Code's own reason, when waiting
  "started_at": 1795610000000, "last_activity_at": 1795620000000 | null,
  "current": {"tool": "Bash", "summary": "npm test", "at": 1795620000000} | null,
  "cpu_percent": 3.2 | null,      // whole process tree, % of ONE core
  "rss_bytes": 337000000 | null,  // sum of RSS over process tree
  "proc_count": 3,
  "tokens": TokenCounts, "tool_calls": 120, "errors": 1,
  "agents": [Agent]
}

// Agent (subagent of a session). CPU/RAM are NOT available per agent:
// subagents run inside the parent process.
{
  "agent_id": "a12c6d6e88d03b336", "type": "general-purpose",
  "description": "Scaffold project", "model": "opus" | null,
  "status": "running" | "done",
  "started_at": ms | null, "last_activity_at": ms | null,
  "current": {"tool": "Read", "summary": "src/main.py", "at": ms} | null,
  "tool_calls": 12
}

// Event
{
  "id": 1234, "session_id": "uuid", "agent_id": null | "a12…",
  "project": "Claude_Monitor", "ts": 1795620000000,
  "kind": "tool" | "error" | "prompt" | "turn_end" | "subagent_start" |
          "subagent_end" | "compact" | "status" | "session_start" |
          "session_end" | "limit",
  "tool": "Bash" | null,
  "summary": "npm test",          // short human text, already truncated
  "detail": "/full/path" | null,  // e.g. file path or longer command
  "is_error": false
}

// HistoryItem
{
  "session_id": "uuid", "project": "Penny-Trade", "cwd": "/home/...",
  "title": "…" | null, "model": "claude-opus-5-5" | null,
  "started_at": ms, "ended_at": ms | null, "duration_ms": n | null,
  "tool_calls": n, "errors": n, "agent_count": n,
  "tokens": TokenCounts, "live": false
}

// SessionDetail = HistoryItem + {
//   "agents": [Agent], "tool_counts": {"Bash": 40, ...},
//   "files_touched": [{"path": "...", "count": 3}]   // top 50
// }

// Stats
{
  "days": [{"date": "2026-11-25", "tokens": TokenCounts, "sessions": 3, "tool_calls": 210}],
  "by_model": {"claude-opus-5-5": TokenCounts},
  "by_tool": {"Bash": 500, "Read": 320},
  "by_project": [{"project": "Penny-Trade", "sessions": 12, "tool_calls": 900, "output_tokens": 120000}],
  "hourly": [24 ints]   // tool calls per local hour of day over the range
}
```

## Config (`config.json`) — defaults

```json
{
  "notifications": {"enabled": true, "on_finish": true, "on_error": true,
                    "on_attention": true, "min_busy_seconds": 20},
  "privacy": {"store_commands": true, "max_detail_chars": 200},
  "retention_days": 180,
  "sample_interval_ms": 2000
}
```

## Status vocabulary (UI colours)

| status | meaning | suggested colour |
|---|---|---|
| busy | Claude is working | accent blue, pulsing dot |
| waiting | waiting on the user (permission / input) | amber |
| blocked | blocked | red |
| idle | turn finished, ready | green |
| unknown | registry not readable | grey |
