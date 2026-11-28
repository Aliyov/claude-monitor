"""SQLite persistence. Single connection, used only from the GLib main thread."""
import sqlite3
import time

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS files (
    path TEXT PRIMARY KEY, offset INTEGER NOT NULL, size INTEGER NOT NULL,
    mtime REAL NOT NULL, inode INTEGER, session_id TEXT, agent_id TEXT
);
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY, project TEXT, cwd TEXT, title TEXT, model TEXT,
    git_branch TEXT, version TEXT, started_at INTEGER, last_at INTEGER, ended_at INTEGER,
    tool_calls INTEGER NOT NULL DEFAULT 0, errors INTEGER NOT NULL DEFAULT 0,
    in_tok INTEGER NOT NULL DEFAULT 0, out_tok INTEGER NOT NULL DEFAULT 0,
    cr_tok INTEGER NOT NULL DEFAULT 0, cc_tok INTEGER NOT NULL DEFAULT 0,
    agent_count INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS sessions_last ON sessions(last_at);
CREATE TABLE IF NOT EXISTS agents (
    session_id TEXT NOT NULL, agent_id TEXT NOT NULL, type TEXT, description TEXT,
    model TEXT, started_at INTEGER, last_at INTEGER,
    tool_calls INTEGER NOT NULL DEFAULT 0, finished INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (session_id, agent_id)
);
CREATE TABLE IF NOT EXISTS messages (
    msg_id TEXT PRIMARY KEY, session_id TEXT, agent_id TEXT, ts INTEGER, model TEXT,
    in_tok INTEGER, out_tok INTEGER, cr_tok INTEGER, cc_tok INTEGER
);
CREATE INDEX IF NOT EXISTS messages_ts ON messages(ts);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY, session_id TEXT NOT NULL, agent_id TEXT, ts INTEGER NOT NULL,
    kind TEXT NOT NULL, tool TEXT, summary TEXT, detail TEXT,
    is_error INTEGER NOT NULL DEFAULT 0, tool_use_id TEXT
);
CREATE INDEX IF NOT EXISTS events_ts ON events(ts);
CREATE INDEX IF NOT EXISTS events_session ON events(session_id, ts);
CREATE INDEX IF NOT EXISTS events_tuid ON events(tool_use_id) WHERE tool_use_id IS NOT NULL;
"""


class Store:
    def __init__(self, path):
        self.db = sqlite3.connect(str(path), isolation_level=None, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.execute("PRAGMA temp_store=MEMORY")
        self.db.execute("PRAGMA cache_size=-4000")  # ~4 MB page cache
        self.db.executescript(SCHEMA)
        cols = {r[1] for r in self.db.execute("PRAGMA table_info(agents)")}
        if "effort" not in cols:  # added for the office View (per-call effort override)
            self.db.execute("ALTER TABLE agents ADD COLUMN effort TEXT")
        if "built_in" not in cols:  # meta isBuiltIn: Explore, Plan, general-purpose... ("contractors")
            self.db.execute("ALTER TABLE agents ADD COLUMN built_in INTEGER")
        self.db.execute("INSERT OR IGNORE INTO kv VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),))
        self._in_tx = False

    # -- transactions -------------------------------------------------
    def begin(self):
        if not self._in_tx:
            self.db.execute("BEGIN")
            self._in_tx = True

    def commit(self):
        if self._in_tx:
            self.db.execute("COMMIT")
            self._in_tx = False

    def x(self, sql, args=()):
        return self.db.execute(sql, args)

    # -- kv -----------------------------------------------------------
    def kv_get(self, key, default=None):
        r = self.db.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return r[0] if r else default

    def kv_set(self, key, value):
        self.db.execute("INSERT OR REPLACE INTO kv VALUES (?,?)", (key, value))

    # -- maintenance --------------------------------------------------
    def prune(self, retention_days: int):
        cutoff = int((time.time() - retention_days * 86400) * 1000)
        self.db.execute("DELETE FROM events WHERE ts < ?", (cutoff,))

    def close(self):
        self.commit()
        try:
            self.db.execute("PRAGMA optimize")
        finally:
            self.db.close()
