"""Office View data: agent rosters (roster.py) and department slots (office.py).

Run: python3 -m unittest discover -s tests -t .
"""
import importlib
import json
import os
import tempfile
import unittest
from pathlib import Path


def agent_file(d, fname, body):
    d.mkdir(parents=True, exist_ok=True)
    (d / fname).write_text(body)


class FrontmatterTest(unittest.TestCase):
    def setUp(self):
        from claudeville.daemon import roster
        self.r = roster

    def test_flat_quoted_and_blocks(self):
        fm = self.r.parse_frontmatter(
            "---\nname: implementer\nmodel: 'opus'\neffort: \"high\"\n"
            "description: |\n  line one\n  line two\nnotes: >\n  folded\n  text\n---\nbody: ignored\n")
        self.assertEqual(fm["name"], "implementer")
        self.assertEqual(fm["model"], "opus")
        self.assertEqual(fm["effort"], "high")
        self.assertEqual(fm["description"], "line one\nline two")
        self.assertEqual(fm["notes"], "folded text")
        self.assertNotIn("body", fm)

    def test_no_frontmatter_and_junk(self):
        self.assertEqual(self.r.parse_frontmatter("# Just markdown\nname: x\n"), {})
        self.assertEqual(self.r.parse_frontmatter(""), {})
        fm = self.r.parse_frontmatter("---\n- list item\nname: ok\n  : weird\n---\n")
        self.assertEqual(fm, {"name": "ok"})


class RankTest(unittest.TestCase):
    def setUp(self):
        from claudeville.daemon import roster
        self.r = roster

    def test_family_and_version(self):
        self.assertEqual(self.r.model_family("claude-opus-5-5"), "opus")
        self.assertEqual(self.r.model_family("Sonnet"), "sonnet")
        self.assertIsNone(self.r.model_family("inherit"))
        self.assertEqual(self.r.model_version("claude-haiku-5-5"), (5, 5))
        self.assertIsNone(self.r.model_version("opus"))

    def test_order(self):
        k = self.r.rank_key
        self.assertGreater(k("fable", "low"), k("opus", "max"))         # family first
        self.assertGreater(k("opus", "low"), k("sonnet", "max"))
        self.assertGreater(k("haiku", None), k(None, "max"))           # unknown model last
        self.assertGreater(k("opus", "max"), k("opus", "xhigh"))       # then effort
        self.assertGreater(k("opus", "high"), k("opus", "medium"))
        self.assertGreater(k("claude-opus-5-5", None), k("claude-opus-4-1", None))
        self.assertGreater(k("opus", None), k("claude-opus-5-5", None))  # alias = newest


class RosterTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        os.environ["CLAUDE_CONFIG_DIR"] = str(root / "claude")
        from claudeville.daemon import paths, roster
        importlib.reload(paths)
        importlib.reload(roster)
        self.roster = roster
        self.user_agents = root / "claude" / "agents"
        self.proj = root / "proj"
        (self.proj / ".git").mkdir(parents=True)
        self.proj_agents = self.proj / ".claude" / "agents"

    def tearDown(self):
        self.tmp.cleanup()

    def team(self, cwd=None, model=None, effort=None):
        return self.roster.Rosters().roster(str(cwd or self.proj), model, effort)

    def test_default_when_no_agents(self):
        t = self.team()
        self.assertEqual(t["source"], "default")
        self.assertEqual(t["agents"], [])
        self.assertIsNone(t["private_room"])
        self.assertIsNone(t["root"])

    def test_project_root_lookup(self):
        agent_file(self.proj_agents, "a.md", "---\nname: a\n---\n")
        sub = self.proj / "src" / "deep"
        sub.mkdir(parents=True)
        self.assertEqual(self.roster.find_project_root(str(sub)), str(self.proj))
        # a nested git repo without agents stops the walk
        nested = self.proj / "vendor" / "lib"
        (nested / ".git").mkdir(parents=True)
        self.assertIsNone(self.roster.find_project_root(str(nested)))
        self.assertIsNone(self.roster.find_project_root(None))

    def test_merge_project_overrides_user(self):
        agent_file(self.user_agents, "helper.md", "---\nname: helper\nmodel: haiku\n---\n")
        agent_file(self.user_agents, "shared.md", "---\nname: shared\nmodel: haiku\n---\n")
        agent_file(self.proj_agents, "shared.md", "---\nname: shared\nmodel: sonnet\neffort: High\n---\n")
        agent_file(self.proj_agents, "noname.md", "---\nmodel: opus\n---\n")
        agent_file(self.proj_agents, "notes.txt", "---\nname: ignored\n---\n")
        t = self.team()
        self.assertEqual(t["source"], "agents")
        by = {a["name"]: a for a in t["agents"]}
        self.assertEqual(set(by), {"helper", "shared", "noname"})
        self.assertEqual(by["shared"]["model"], "sonnet")
        self.assertEqual(by["shared"]["effort"], "high")
        self.assertEqual(by["shared"]["scope"], "project")
        self.assertEqual(by["helper"]["scope"], "user")
        self.assertEqual([a["rank"] for a in t["agents"]], [0, 1, 2])
        self.assertEqual(t["agents"][0]["name"], "noname")      # opus outranks sonnet/haiku
        self.assertEqual(t["private_room"], "noname")
        self.assertEqual([a["room"] for a in t["agents"]], ["private", "desk", "desk"])
        self.assertFalse(any(k.startswith("_") for a in t["agents"] for k in a))

    def test_inherit_uses_session_model_for_ranking_only(self):
        agent_file(self.proj_agents, "inh.md", "---\nname: inh\nmodel: inherit\n---\n")
        agent_file(self.proj_agents, "son.md", "---\nname: son\nmodel: sonnet\n---\n")
        t = self.team(model="claude-opus-5-5")
        self.assertEqual(t["private_room"], "inh")
        self.assertEqual(t["agents"][0]["model"], "inherit")    # reported as written
        t = self.team(model="claude-haiku-5-5")
        self.assertEqual(t["private_room"], "son")

    def test_tie_is_stable(self):
        for n in "abcdef":
            agent_file(self.proj_agents, f"{n}.md", f"---\nname: {n}\nmodel: opus\neffort: high\n---\n")
        picks = {self.team()["private_room"] for _ in range(5)}
        self.assertEqual(len(picks), 1)

    def test_change_detection(self):
        agent_file(self.proj_agents, "a.md", "---\nname: a\n---\n")
        r = self.roster.Rosters()
        r.roster(str(self.proj), None, None, now=0.0)
        self.assertFalse(r.changed([str(self.proj)]))
        agent_file(self.proj_agents, "b.md", "---\nname: b\n---\n")
        for c in r._dirs.values():   # skip the 3 s recheck throttle
            c.checked = -100.0
        self.assertTrue(r.changed([str(self.proj)]))
        self.assertEqual(len(r.roster(str(self.proj), None, None)["agents"]), 2)


class FakeStore:
    def __init__(self, kv=None):
        self.kv = dict(kv or {})
        self.writes = 0

    def kv_get(self, key, default=None):
        return self.kv.get(key, default)

    def kv_set(self, key, value):
        self.kv[key] = value
        self.writes += 1


class FakeRosters:
    def roster(self, cwd, model, effort):
        return {"source": "default", "root": None, "agents": [], "private_room": None, "cwd": cwd}


H = 3600 * 1000


def sess(sid, project, started=0, cwd=None):
    return {"session_id": sid, "project": project, "cwd": cwd or f"/p/{project}", "started_at": started,
            "model": "claude-opus-5-5", "effort": "high"}


class OfficeTest(unittest.TestCase):
    def setUp(self):
        from claudeville.daemon import office
        self.office_mod = office
        self.store = FakeStore()
        self.o = office.Office(self.store)

    def sids(self):
        return [sl["session_id"] for sl in self.o.slots]

    def test_slot0_always_exists(self):
        self.assertEqual(self.sids(), [None])
        deps = self.o.departments(FakeRosters())
        self.assertEqual(len(deps), 1)
        self.assertFalse(deps[0]["lit"])
        self.assertEqual(deps[0]["roster"]["source"], "default")
        self.o.update([], 100 * H)
        self.assertEqual(self.sids(), [None])

    def test_each_session_own_slot_even_same_project(self):
        self.assertTrue(self.o.update([sess("b", "P", 2), sess("a", "P", 1)], 0))
        self.assertEqual(self.sids(), ["a", "b"])               # ordered by start time
        deps = self.o.departments(FakeRosters())
        self.assertTrue(all(d["lit"] for d in deps))
        self.assertEqual([d["slot"] for d in deps], [0, 1])

    def test_closed_goes_dark_and_reused_by_any_project(self):
        self.o.update([sess("a", "P")], 0)
        self.o.update([], H)
        self.assertEqual(self.sids(), [None])
        self.assertEqual(self.o.slots[0]["project"], "P")       # remembers last host
        self.o.update([sess("x", "Q")], 2 * H)
        self.assertEqual(self.sids(), ["x"])

    def test_prefers_slot_that_hosted_same_project(self):
        self.o.update([sess("a", "P", 1), sess("b", "Q", 2), sess("c", "R", 3)], 0)
        self.o.update([sess("a", "P", 1)], H)                    # Q and R go dark
        self.o.update([sess("a", "P", 1), sess("r2", "R", 9)], 2 * H)
        self.assertEqual(self.sids(), ["a", None, "r2"])

    def test_extra_dark_slots_expire_after_48h(self):
        self.o.update([sess("a", "P", 1), sess("b", "Q", 2)], 0)
        self.o.update([], H)
        self.assertEqual(len(self.o.slots), 2)
        self.o.update([], H + self.office_mod.EXPIRE_MS - 1)
        self.assertEqual(len(self.o.slots), 2)
        self.assertTrue(self.o.update([], H + self.office_mod.EXPIRE_MS))
        self.assertEqual(self.sids(), [None])                   # slot 0 never removed

    def test_persists_and_writes_only_on_change(self):
        self.o.update([sess("a", "P")], 0)
        w = self.store.writes
        self.assertFalse(self.o.update([sess("a", "P")], 5 * H))
        self.assertEqual(self.store.writes, w)
        o2 = self.office_mod.Office(self.store)
        self.assertEqual([sl["session_id"] for sl in o2.slots], ["a"])
        self.assertEqual(json.loads(self.store.kv["office_slots"])[0]["project"], "P")

    def test_corrupt_kv_recovers(self):
        for bad in ("not json", "{}", "[]"):
            o = self.office_mod.Office(FakeStore({"office_slots": bad}))
            self.assertEqual(len(o.slots), 1)
            self.assertIsNone(o.slots[0]["session_id"])


if __name__ == "__main__":
    unittest.main()
