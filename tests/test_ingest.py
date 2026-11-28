"""Ingestion correctness tests on synthetic transcripts (stdlib unittest only).

Run: python3 -m unittest discover -s tests
"""
import importlib
import json
import os
import tempfile
import unittest
from pathlib import Path


def rec(**kw):
    return json.dumps(kw) + "\n"


def assistant(mid, ts, blocks, usage=None, model="claude-opus-5-5", **extra):
    return rec(type="assistant", timestamp=ts, sessionId="S", cwd="/home/u/Proj", version="2.1.0",
               message={"id": mid, "model": model, "role": "assistant", "content": blocks,
                        "usage": usage or {"input_tokens": 10, "output_tokens": 100,
                                           "cache_read_input_tokens": 1000, "cache_creation_input_tokens": 50}},
               **extra)


class IngestTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        os.environ["CLAUDE_CONFIG_DIR"] = str(root / "claude")
        os.environ["CLAUDEVILLE_DATA_DIR"] = str(root / "data")
        os.environ["XDG_CONFIG_HOME"] = str(root / "cfg")
        from claudeville.daemon import paths
        importlib.reload(paths)
        from claudeville.daemon import config, ingest, store
        for m in (config, ingest):
            importlib.reload(m)
        self.paths, self.ingest = paths, ingest
        self.proj = paths.PROJECTS_DIR / "-home-u-Proj"
        self.proj.mkdir(parents=True)
        (root / "data").mkdir()
        self.store = store.Store(root / "data" / "t.db")
        self.events = []
        self.ing = ingest.Ingestor(self.store, config.Config(), self.events.extend)
        self.file = self.proj / "S.jsonl"

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def write(self, text, mode="a"):
        with open(self.file, mode) as f:
            f.write(text)

    def run_all(self, live=False):
        while self.ing.ingest(str(self.file), live=live):
            pass

    def sess(self):
        return self.store.x("SELECT * FROM sessions WHERE session_id='S'").fetchone()

    def test_usage_deduplicated_per_message(self):
        # Claude Code writes one record per content block, each repeating the usage.
        self.write(assistant("m1", "2026-11-25T10:00:00Z", [{"type": "thinking", "thinking": ""}]))
        self.write(assistant("m1", "2026-11-25T10:00:01Z", [{"type": "text", "text": "hi"}]))
        self.write(assistant("m1", "2026-11-25T10:00:02Z",
                             [{"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "ls -la"}}]))
        self.run_all()
        s = self.sess()
        self.assertEqual((s["in_tok"], s["out_tok"], s["cr_tok"], s["cc_tok"]), (10, 100, 1000, 50))
        self.assertEqual(s["tool_calls"], 1)
        self.assertEqual(s["project"], "Proj")

    def test_resume_from_offset_and_partial_lines(self):
        self.write(assistant("m1", "2026-11-25T10:00:00Z", []))
        line = assistant("m2", "2026-11-25T10:01:00Z", [])
        self.write(line[:20])  # partial line being written
        self.run_all()
        self.assertEqual(self.sess()["out_tok"], 100)
        self.write(line[20:])
        self.run_all()
        self.assertEqual(self.sess()["out_tok"], 200)
        self.run_all()  # nothing new: idempotent
        self.assertEqual(self.sess()["out_tok"], 200)

    def test_tool_error_marked(self):
        self.write(assistant("m1", "2026-11-25T10:00:00Z",
                             [{"type": "tool_use", "id": "t9", "name": "Read", "input": {"file_path": "/a/b.py"}}]))
        self.write(rec(type="user", timestamp="2026-11-25T10:00:01Z",
                       message={"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t9",
                                                             "is_error": True, "content": "nope"}]}))
        self.run_all()
        ev = self.store.x("SELECT * FROM events WHERE tool_use_id='t9'").fetchone()
        self.assertEqual((ev["summary"], ev["detail"], ev["is_error"]), ("b.py", "/a/b.py", 1))
        self.assertEqual(self.sess()["errors"], 1)

    def test_prompt_text_never_stored(self):
        self.write(rec(type="user", timestamp="2026-11-25T10:00:00Z", origin={"kind": "human"},
                       message={"role": "user", "content": "my secret password is hunter2"}))
        self.run_all()
        rows = [dict(r) for r in self.store.x("SELECT * FROM events")]
        self.assertEqual(rows[0]["kind"], "prompt")
        self.assertNotIn("hunter2", json.dumps(rows))

    def test_skipped_and_garbage_records(self):
        self.write('{"type":"api-request-blob","message":{"content":"x"}}\n')
        self.write("not json at all\n")
        self.write(rec(type="ai-title", aiTitle="Fix the parser", sessionId="S"))
        self.write(assistant("m1", "2026-11-25T10:00:00Z", []))
        self.run_all()
        self.assertEqual(self.sess()["title"], "Fix the parser")
        self.assertEqual(self.sess()["out_tok"], 100)

    def test_live_events_emitted_only_when_live(self):
        self.write(assistant("m1", "2026-11-25T10:00:00Z",
                             [{"type": "tool_use", "id": "a", "name": "Grep", "input": {"pattern": "foo"}}]))
        self.run_all(live=False)
        self.assertEqual(self.events, [])
        self.write(assistant("m2", "2026-11-25T10:00:05Z",
                             [{"type": "tool_use", "id": "b", "name": "Bash", "input": {"command": "make\nmake test"}}]))
        self.run_all(live=True)
        self.assertEqual([(e["tool"], e["summary"]) for e in self.events], [("Bash", "make")])

    def test_subagent_attribution(self):
        sub = self.proj / "S" / "subagents"
        sub.mkdir(parents=True)
        (sub / "agent-x1.meta.json").write_text(json.dumps(
            {"agentType": "Explore", "description": "Find files", "finished": False,
             "isBuiltIn": True, "effort": "low"}))
        with open(sub / "agent-x1.jsonl", "w") as f:
            f.write(assistant("sm1", "2026-11-25T10:00:00Z",
                              [{"type": "tool_use", "id": "s1", "name": "Glob", "input": {"pattern": "**/*.py"}}],
                              model="claude-haiku-5-5"))
        for p in self.ing.scan_subagents(str(sub)):
            while self.ing.ingest(p, live=False):
                pass
        a = self.store.x("SELECT * FROM agents").fetchone()
        self.assertEqual((a["agent_id"], a["type"], a["description"], a["tool_calls"]),
                         ("x1", "Explore", "Find files", 1))
        self.assertEqual((a["built_in"], a["effort"]), (1, "low"))
        from claudeville.daemon import queries
        obj = queries.agent_obj(a, live_session=False)
        self.assertEqual((obj["built_in"], obj["effort"], obj["status"]), (True, "low", "done"))
        self.assertEqual(self.sess()["agent_count"], 1)
        self.assertEqual(self.sess()["out_tok"], 100)  # subagent tokens roll up into session

    def test_limit_hit_recorded(self):
        self.write(assistant("m1", "2026-11-25T10:00:00Z", [], quotaLimits={
            "status": "rejected", "resetsAt": 1795600200, "rateLimitType": "five_hour"}))
        self.run_all()
        hit = json.loads(self.store.kv_get("last_limit_hit"))
        self.assertEqual((hit["type"], hit["resets_at"]), ("five_hour", 1795600200))


class SummaryTest(unittest.TestCase):
    def test_commands_can_be_hidden(self):
        from claudeville.daemon.ingest import summarize_tool
        s, d = summarize_tool("Bash", {"command": "export TOKEN=abc", "description": "Set env"},
                              store_commands=False)
        self.assertEqual((s, d), ("Set env", None))

    def test_mcp_name(self):
        from claudeville.daemon.ingest import summarize_tool
        self.assertEqual(summarize_tool("mcp__github__create_issue", {})[0], "github · create_issue")


if __name__ == "__main__":
    unittest.main()
