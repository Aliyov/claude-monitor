"""Read-side queries backing the D-Bus methods."""
import time

FILE_TOOLS = ("Read", "Write", "Edit", "MultiEdit", "NotebookEdit")


def tokens(r, prefix=""):
    return {"input": r[prefix + "in_tok"] or 0, "output": r[prefix + "out_tok"] or 0,
            "cache_read": r[prefix + "cr_tok"] or 0, "cache_create": r[prefix + "cc_tok"] or 0}


def token_sum(store, since_ms):
    r = store.x("SELECT SUM(in_tok) in_tok, SUM(out_tok) out_tok, SUM(cr_tok) cr_tok, SUM(cc_tok) cc_tok "
                "FROM messages WHERE ts >= ?", (since_ms,)).fetchone()
    return tokens(r)


def history_item(r, live_ids):
    live = r["session_id"] in live_ids
    started, last = r["started_at"], r["last_at"]
    ended = None if live else (r["ended_at"] or last)
    return {
        "session_id": r["session_id"], "project": r["project"], "cwd": r["cwd"], "title": r["title"],
        "model": r["model"], "started_at": started, "ended_at": ended,
        "duration_ms": (ended - started) if (ended and started) else None,
        "tool_calls": r["tool_calls"], "errors": r["errors"], "agent_count": r["agent_count"],
        "tokens": tokens(r), "live": live,
    }


def history(store, query, offset, limit, live_ids):
    where = "WHERE started_at IS NOT NULL"
    args = []
    if query:
        where += " AND (project LIKE ? OR title LIKE ? OR cwd LIKE ?)"
        q = f"%{query}%"
        args += [q, q, q]
    total = store.x(f"SELECT COUNT(*) FROM sessions {where}", args).fetchone()[0]
    rows = store.x(f"SELECT * FROM sessions {where} ORDER BY COALESCE(last_at, started_at) DESC "
                   f"LIMIT ? OFFSET ?", args + [min(limit, 500), offset]).fetchall()
    return {"total": total, "sessions": [history_item(r, live_ids) for r in rows]}


def agent_obj(r, live_session, current=None):
    recent = r["last_at"] and (time.time() * 1000 - r["last_at"]) < 15 * 60 * 1000
    running = live_session and not r["finished"] and bool(recent)
    return {"agent_id": r["agent_id"], "type": r["type"], "description": r["description"],
            "model": r["model"], "effort": r["effort"] if "effort" in r.keys() else None,
            "status": "running" if running else "done",
            "started_at": r["started_at"], "last_activity_at": r["last_at"],
            "current": current if running else None, "tool_calls": r["tool_calls"]}


def agents(store, session_id, live_session, currents=None):
    currents = currents or {}
    rows = store.x("SELECT * FROM agents WHERE session_id=? ORDER BY started_at", (session_id,)).fetchall()
    return [agent_obj(r, live_session, currents.get(r["agent_id"])) for r in rows]


def session_detail(store, session_id, live_ids):
    r = store.x("SELECT * FROM sessions WHERE session_id=?", (session_id,)).fetchone()
    if not r:
        return {"error": "not_found"}
    out = history_item(r, live_ids)
    out["agents"] = agents(store, session_id, out["live"])
    out["tool_counts"] = {t: n for t, n in store.x(
        "SELECT tool, COUNT(*) FROM events WHERE session_id=? AND kind='tool' GROUP BY tool ORDER BY 2 DESC",
        (session_id,))}
    ph = ",".join("?" * len(FILE_TOOLS))
    out["files_touched"] = [{"path": p, "count": n} for p, n in store.x(
        f"SELECT detail, COUNT(*) FROM events WHERE session_id=? AND tool IN ({ph}) AND detail IS NOT NULL "
        f"GROUP BY detail ORDER BY 2 DESC LIMIT 50", (session_id, *FILE_TOOLS))]
    return out


def event_obj(r, projects):
    return {"id": r["id"], "session_id": r["session_id"], "agent_id": r["agent_id"],
            "project": projects.get(r["session_id"]), "ts": r["ts"], "kind": r["kind"], "tool": r["tool"],
            "summary": r["summary"], "detail": r["detail"], "is_error": bool(r["is_error"])}


def events(store, session_id, before_id, limit, projects):
    limit = max(1, min(limit or 100, 1000))
    args, where = [], []
    if session_id:
        where.append("session_id=?")
        args.append(session_id)
    if before_id and before_id > 0:
        # Cursor on (ts, id): ids follow ingestion order, which is not chronological
        # after a history backfill.
        ref = store.x("SELECT ts FROM events WHERE id=?", (before_id,)).fetchone()
        if ref is None:
            return {"events": []}
        where.append("(ts < ? OR (ts = ? AND id < ?))")
        args += [ref[0], ref[0], before_id]
    w = ("WHERE " + " AND ".join(where)) if where else ""
    rows = store.x(f"SELECT * FROM events {w} ORDER BY ts DESC, id DESC LIMIT ?", args + [limit]).fetchall()
    return {"events": [event_obj(r, projects) for r in rows]}


def stats(store, days):
    days = max(1, min(days or 30, 3650))
    since = int((time.time() - days * 86400) * 1000)
    day_rows = store.x(
        "SELECT date(ts/1000,'unixepoch','localtime') d, SUM(in_tok) in_tok, SUM(out_tok) out_tok, "
        "SUM(cr_tok) cr_tok, SUM(cc_tok) cc_tok, COUNT(DISTINCT session_id) s "
        "FROM messages WHERE ts >= ? GROUP BY d ORDER BY d", (since,)).fetchall()
    tool_days = dict(store.x(
        "SELECT date(ts/1000,'unixepoch','localtime') d, COUNT(*) FROM events "
        "WHERE kind='tool' AND ts >= ? GROUP BY d", (since,)).fetchall())
    out_days = [{"date": r["d"], "tokens": tokens(r), "sessions": r["s"], "tool_calls": tool_days.get(r["d"], 0)}
                for r in day_rows]
    by_model = {r["model"]: tokens(r) for r in store.x(
        "SELECT model, SUM(in_tok) in_tok, SUM(out_tok) out_tok, SUM(cr_tok) cr_tok, SUM(cc_tok) cc_tok "
        "FROM messages WHERE ts >= ? AND model IS NOT NULL AND model NOT LIKE '<%' GROUP BY model ORDER BY out_tok DESC", (since,))}
    by_tool = {t: n for t, n in store.x(
        "SELECT tool, COUNT(*) FROM events WHERE kind='tool' AND ts >= ? GROUP BY tool ORDER BY 2 DESC LIMIT 30",
        (since,))}
    by_project = [{"project": r[0] or "(unknown)", "sessions": r[1], "tool_calls": r[2], "output_tokens": r[3]}
                  for r in store.x(
        "SELECT s.project, COUNT(DISTINCT s.session_id), "
        "(SELECT COUNT(*) FROM events e JOIN sessions s2 ON e.session_id=s2.session_id "
        "  WHERE s2.project IS s.project AND e.kind='tool' AND e.ts>=?), "
        "(SELECT SUM(m.out_tok) FROM messages m JOIN sessions s3 ON m.session_id=s3.session_id "
        "  WHERE s3.project IS s.project AND m.ts>=?) "
        "FROM sessions s WHERE s.last_at >= ? GROUP BY s.project ORDER BY 4 DESC", (since, since, since))]
    hourly = [0] * 24
    for h, n in store.x("SELECT CAST(strftime('%H', ts/1000, 'unixepoch', 'localtime') AS INTEGER), COUNT(*) "
                        "FROM events WHERE kind='tool' AND ts >= ? GROUP BY 1", (since,)):
        if h is not None:
            hourly[h] = n
    return {"days": out_days, "by_model": by_model, "by_tool": by_tool,
            "by_project": by_project, "hourly": hourly}
