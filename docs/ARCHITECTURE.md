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
   roster.py    ── agent definition frontmatter (.claude/agents/*.md) → teams
   office.py    ── department slots for the View page (persisted in kv)
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

## Office View data

The dashboard's "View" page draws each live session as a department of an
office. The daemon supplies only facts; the animation lives in the dashboard.

- **Teams** come from Claude Code's own subagent definitions:
  `<project>/.claude/agents/*.md` and `~/.claude/agents/*.md`, frontmatter only
  (name, description, model, effort). CLAUDE.md prose is not parsed: it is free
  text, and Claude Code can only launch agents that have a definition file.
- **Cheap**: each agents dir is re-listed at most every 3 s (`scandir` + mtimes);
  files are re-read only when that signature changes. A change marks the
  snapshot dirty. Project-root lookups are cached for 30 s.
- **Slots** are assigned in `office.py` on every registry change; the layout is
  written to kv only when it really changes, so departments keep their place
  across daemon restarts.
- **Built-in agents** (`isBuiltIn` in the subagent meta) are flagged so the UI
  can seat them as "contractors".
- No tokens, no network: everything is read from local files Claude Code
  already writes.

### Office View rendering (dashboard)

`claude_monitor/dashboard/office/`: `model.py` (who sits where, lights),
`actors.py` (behaviour: typing, walks to coffee/whiteboard/cooler/lounge,
"..." chats; working people stay seated), `look.py` (characters, bubbles),
`art.py` (furniture, walls), `iso.py` (isometric pixel pen), `scene.py`
(layout + per-frame assembly) and `canvas.py` (GTK widget).

- All art is original and procedural; every object is drawn once into its own
  sprite with a 1-px outline, and the background is pre-composited.
- Per frame only textures are composited (background + ~50 sprites); static
  sprites are re-drawn only where they are in front of a moving one.
- 12 fps for an enlarged department, 8 fps for the grid, 4 fps when the
  window is in the background, 0 when hidden, minimised or when the desktop
  asks for reduced animations. Measured: ~2 ms per frame, ~1 % of one core
  on top of the idle dashboard.
- Interaction: click a department to enlarge it (the sidebar collapses to an
  icon rail), wheel / pinch to zoom around the pointer (100–500 %), drag to
  pan, click a person for a popover (name, role, status, model, effort,
  current tool, task, "Open Session"). Esc steps back.
- Only real data drives it: lamp colours and tool bubbles come from the
  snapshot; chat bubbles are decorative dots; the wall clock and window sky
  follow local time.

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
- Session `effort` is only known with the status-line tee; subagent `effort`
  only when the call overrides it. Subagents report only running/done, so they
  can never be shown as "waiting".
- The transcript format is undocumented; parser is defensive and tested on
  synthetic fixtures (`tests/`).
