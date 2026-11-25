# Claude Monitor — Architecture

## Goals and hard constraints

- Monitor every Claude Code session on this machine (all terminals, all projects).
- Fedora / GNOME (Wayland), per-user, **no root**.
- **Never interfere** with Claude Code; **never** cause tokens or API calls.
- **Never fabricate** data: unknown values are `null` and shown as unavailable.
- Low resource usage; survive restarts; privacy by default.

## Data sources (verified on Claude Code 2.1.332)

| Data | Source | Notes |
|---|---|---|
| Live sessions + status | `~/.claude/sessions/<pid>.json` | Claude Code's own registry. `status` ∈ busy/idle/waiting/blocked. `procStart` = `/proc/<pid>/stat` field 22 → PID-reuse safe liveness. |
| Activity, tools, files, commands | `~/.claude/projects/<enc-cwd>/<session>.jsonl` | `tool_use` / `tool_result` blocks. Written within ~1 s. |
| Subagents | `<session>/subagents/agent-<id>.jsonl` + `.meta.json` | type, description, model, `finished`. Run inside the parent process. |
| Tokens | `message.usage` on assistant records | Repeated on every record of a multi-block message → **deduplicated by message id**. (Claude Code's own `stats-cache.json` sums per record and over-counts ≈2.5×.) |
| Limit hit + exact reset | `quotaLimits` on assistant records | Present only when a limit rejects a request. |
| Plan usage % (5 h / weekly) | status-line stdin JSON `rate_limits` | Filled from headers of responses Claude Code already received. Requires the **opt-in** status-line tee. |
| CPU / RAM | `/proc/<pid>/stat`, `/proc/<pid>/task/*/children` | Per session process tree (includes Bash children, MCP servers). Not separable per subagent. |

Rejected: calling `api/oauth/usage` ourselves (extra network request using the
user's OAuth token); the per-session messaging sockets (risk of interference).

## Components

```
 Claude Code sessions ──writes──► ~/.claude (read-only to us; kernel-enforced by systemd ProtectHome)
                                   │
                    optional tee ──┼──► ~/.local/state/claude-monitor/statusline/<sid>.json
                                   ▼
 claude-monitord (Python, GLib main loop, systemd --user, Nice=10, idle I/O)
   registry.py  ── 1 s poll of sessions/*.json (listdir + stat)
   ingest.py    ── resumable byte-offset JSONL tailer, defensive parser
   procmon.py   ── 2 s /proc sampling of live process trees
   usage.py     ── status-line drops → limits (drops windows past resets_at)
   engine.py    ── state machine, notifications, ≤1 Hz coalesced change signals
   store.py     ── SQLite WAL (~6 MB for 500 MB of transcripts)
   dbus_service ── io.github.ClaudeMonitor1 (JSON payloads, see CONTRACT.md)
        │ D-Bus session bus
        ├──► Dashboard (GTK4 + libadwaita, Python)
        ├──► GNOME Shell extension (GJS): panel indicator
        └──► claude-monitor CLI
```

### Why these choices

- **Separate daemon**: monitoring continues with no UI open; systemd restarts it;
  D-Bus activation starts it on demand.
- **Polling over inotify** for the handful of live files: a few `stat()` calls per
  second are cheaper and more robust than recursive inotify watches across
  hundreds of directories (inotify is not recursive; dirs come and go).
- **Shell extension for the top-bar indicator**: only the shell can add items
  to the GNOME top bar. (An earlier floating widget was removed at the user's
  request: it covered maximized/fullscreen windows.)
- **Python + PyGObject**: all deps preinstalled on Fedora Workstation; the
  workload is I/O-bound. Measured: full backfill of 508 MB in 2.8 s; steady state
  0.2 % of one core, ~47 MB RSS.
- **Native install, not Flatpak**: a sandbox's PID namespace would hide the host
  processes needed for CPU/RAM monitoring.
- **JSON over D-Bus**: trivial for both GJS and Python; versioned interface name.

## Reliability

- Byte offsets + inode per file persisted → restart resumes exactly; truncation or
  replacement triggers a safe re-read (token dedupe by message id, tool events
  dedupe by tool_use_id).
- Partial trailing lines are never consumed.
- Catch-up runs in 15 ms idle slices so D-Bus stays responsive; live sessions'
  files first.
- Unknown record types/fields are ignored; one bad record never stops ingestion.

## Privacy

- Prompt and response text are **never stored**. Stored: tool name, short
  summary (file name, first line of a command, search pattern), path/command
  detail (truncated; commands can be disabled in settings), timestamps, tokens.
- All data stays in `~/.local/share/claude-monitor`, mode 0700. No network code.
- Retention pruning (default 180 days) for events.

## Known limitations

- Plan usage % requires the opt-in status-line tee, and refreshes only while some
  Claude Code session is active. The UI shows "as of" time and staleness.
- Per-subagent CPU/RAM is impossible (same process); per-session tree only.
- RSS is summed over the process tree (shared pages counted per process).
- `waiting`/`blocked` registry statuses are interpreted from Claude Code's
  registry; exact semantics may evolve between versions.
- The transcript format is undocumented; parser is defensive and tested on
  synthetic fixtures (`tests/`).
