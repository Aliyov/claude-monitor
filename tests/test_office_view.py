"""Office View seating and light rules (dashboard/office/model.py, no GTK).

Run: python3 -m unittest discover -s tests -t .
"""
import unittest

from claude_monitor.dashboard.office import model


def ra(name, rank, model_="opus", effort=None):
    return {"name": name, "description": None, "model": model_, "effort": effort, "scope": "project",
            "rank": rank, "room": "private" if rank == 0 else "desk"}


def dep(agents=(), lit=True, slot=0, sid="S"):
    return {"slot": slot, "lit": lit, "session_id": sid if lit else None, "project": "P", "cwd": "/p",
            "last_used_at": 1, "roster": {"source": "agents" if agents else "default", "root": None,
                                          "agents": list(agents),
                                          "private_room": agents[0]["name"] if agents else None}}


def session(status="idle", agents=(), current=None, waiting_for=None):
    return {"session_id": "S", "status": status, "model": "claude-opus-5-5", "effort": "high",
            "current": current, "waiting_for": waiting_for, "title": "T", "agents": list(agents)}


def agent(aid, typ, status="running", built_in=False, started=0):
    return {"agent_id": aid, "type": typ, "status": status, "built_in": built_in, "model": "sonnet",
            "effort": None, "description": f"{typ} task", "started_at": started,
            "current": {"tool": "Read", "summary": "x.py", "at": 1} if status == "running" else None}


def seats(view, seat):
    return [(p.role, p.name, p.light) for p in view.by_seat(seat)]


class LeadLightTest(unittest.TestCase):
    def test_states(self):
        self.assertEqual(model.lead_light(session("busy"))[0], model.RED)
        self.assertEqual(model.lead_light(session("idle"))[0], model.GREEN)
        light, text = model.lead_light(session("waiting", waiting_for="permission"))
        self.assertEqual((light, text), (model.YELLOW, "Waiting for you (permission)"))
        # delegating to running subagents
        s = session("busy", [agent("a", "x")], current={"tool": "Agent", "summary": "", "at": 1})
        self.assertEqual(model.lead_light(s), (model.YELLOW, "Waiting for 1 subagent"))
        # idle while background agents run
        self.assertEqual(model.lead_light(session("idle", [agent("a", "x"), agent("b", "y")]))[1],
                         "Waiting for 2 subagents")
        # busy with its own tool while a background agent runs: working
        s = session("busy", [agent("a", "x")], current={"tool": "Bash", "summary": "", "at": 1})
        self.assertEqual(model.lead_light(s)[0], model.RED)


class SeatingTest(unittest.TestCase):
    def test_default_team_is_lead_plus_four_grey_fillers(self):
        v = model.build(dep(), session())
        self.assertEqual(seats(v, "office"), [("lead", "Lead", model.GREEN)])
        self.assertEqual(seats(v, "desk"), [("filler", None, model.GREY)] * 4)
        self.assertEqual(v.by_seat("private"), [])

    def test_min_five_padding(self):
        v = model.build(dep([ra("impl", 0), ra("ver", 1, "haiku")]), session())
        self.assertEqual(seats(v, "private"), [("agent", "impl", model.GREEN)])
        self.assertEqual([p.role for p in v.by_seat("desk")], ["agent", "filler", "filler"])
        self.assertEqual(len(v.people), 5)
        big = model.build(dep([ra(f"a{i}", i) for i in range(7)]), session())
        self.assertEqual(len(big.people), 8)                 # no padding needed
        self.assertFalse(any(p.filler for p in big.people))

    def test_running_roster_agent_takes_its_seat(self):
        s = session("busy", [agent("x1", "ver")], current={"tool": "Agent", "summary": "", "at": 1})
        v = model.build(dep([ra("impl", 0), ra("ver", 1)]), s)
        ver = [p for p in v.people if p.name == "ver"][0]
        self.assertEqual((ver.light, ver.agent_id, ver.seat), (model.RED, "x1", "desk"))
        self.assertEqual(ver.current["tool"], "Read")
        self.assertEqual(v.by_seat("office")[0].light, model.YELLOW)
        self.assertEqual(v.by_seat("temp"), [])

    def test_builtin_duplicate_and_unknown_are_contractors(self):
        s = session("busy", [agent("e1", "Explore", built_in=True, started=1),
                             agent("v1", "ver", started=2), agent("v2", "ver", started=3),
                             agent("o1", "other", started=4)])
        v = model.build(dep([ra("impl", 0), ra("ver", 1)]), s)
        self.assertEqual([(p.name, p.agent_id) for p in v.by_seat("temp")],
                         [("Explore", "e1"), ("ver", "v2"), ("other", "o1")])
        self.assertTrue(all(p.role == "contractor" and p.light == model.RED for p in v.by_seat("temp")))

    def test_builtin_fallback_when_flag_unknown(self):
        s = session("busy", [agent("g1", "general-purpose", built_in=None)])
        v = model.build(dep([ra("general-purpose", 0)]), s)   # even if a file shares the name
        self.assertEqual(seats(v, "temp"), [("contractor", "general-purpose", model.RED)])

    def test_default_team_subagent_takes_over_filler(self):
        s = session("idle", [agent("e1", "Explore", built_in=True)])
        v = model.build(dep(), s)
        desks = v.by_seat("desk")
        self.assertEqual((desks[0].role, desks[0].name, desks[0].light), ("agent", "Explore", model.RED))
        self.assertEqual([p.role for p in desks[1:]], ["filler"] * 3)
        self.assertEqual(v.by_seat("temp"), [])
        many = model.build(dep(), session("idle", [agent(f"e{i}", "Explore", started=i) for i in range(6)]))
        self.assertEqual(len(many.by_seat("temp")), 2)       # 4 take over fillers, 2 at temp desks

    def test_done_agents_are_green_and_never_yellow(self):
        s = session("idle", [agent("v1", "ver", status="done")])
        v = model.build(dep([ra("impl", 0), ra("ver", 1)]), s)
        ver = [p for p in v.people if p.name == "ver"][0]
        self.assertEqual((ver.light, ver.status_text), (model.GREEN, "Done"))
        self.assertFalse(any(p.light == model.YELLOW for p in v.people if p.role != "lead"))

    def test_dark_department(self):
        v = model.build(dep([ra("impl", 0)], lit=False), None)
        self.assertFalse(v.lit)
        self.assertTrue(all(p.light == model.OFF for p in v.people))
        # lit flag without a matching live session is treated as dark (never invent a lead)
        v = model.build(dep(), None)
        self.assertFalse(v.lit)

    def test_build_all_without_office_data(self):
        self.assertEqual(model.build_all({"sessions": []}), [])
        snap = {"sessions": [session()], "office": {"departments": [dep(), dep(lit=False, slot=1)]}}
        self.assertEqual([v.lit for v in model.build_all(snap)], [True, False])



class SceneTest(unittest.TestCase):
    def test_render_every_kind_of_department(self):
        from claude_monitor.dashboard.office import scene
        s = session("busy", [agent("e1", "Explore", built_in=True, started=1),
                             agent("v1", "ver", started=2), agent("v2", "ver", started=3)])
        cases = [model.build(dep([ra(f"a{i}", i) for i in range(9)]), s),
                 model.build(dep(), session("waiting")),
                 model.build(dep([ra("impl", 0)], lit=False), None)]
        for v in cases:
            r = scene.render(v)
            self.assertEqual((r.surface.get_width(), r.surface.get_height()), (r.width, r.height))
            lit_people = [p for p in v.people if p.light != model.OFF]
            self.assertEqual(sorted(a.person.key for a in r.anchors), sorted(p.key for p in lit_people))


if __name__ == "__main__":
    unittest.main()
