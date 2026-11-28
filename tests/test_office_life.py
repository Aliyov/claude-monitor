"""Office behaviours (dashboard/office/actors.py): pure logic, no GTK.

Run: python3 -m unittest discover -s tests -t .
"""
import unittest

from claude_monitor.dashboard.office import actors, model, scene
from tests.test_office_view import agent, dep, ra, session


def office(sess, agents=8):
    v = model.build(dep([ra(f"a{i}", i) for i in range(agents)]), sess)
    sc = scene.Scene(v, "day")
    sc.sync(v, 0.0)
    return v, sc


def run(sc, t0, t1, step=0.1):
    t, seen = t0, []
    while t < t1:
        t += step
        seen.append(sc.director.step(t))
    return t, seen


class NavTest(unittest.TestCase):
    def test_routes_stay_on_aisles(self):
        nav = actors.Nav(2.9, [5.4, 10.1])
        self.assertEqual(nav.route((5.0, 5.4), (9.0, 5.4)), [(9.0, 5.4)])
        self.assertEqual(nav.route((5.0, 5.4), (8.0, 10.1)), [(2.9, 5.4), (2.9, 10.1), (8.0, 10.1)])
        self.assertEqual(nav.route((5.0, 10.1), (2.9, 6.0)), [(2.9, 10.1), (2.9, 6.0)])
        self.assertEqual(nav.route((2.9, 6.0), (2.9, 7.5)), [(2.9, 7.5)])


class LifeTest(unittest.TestCase):
    def test_idle_people_wander_and_come_back(self):
        v, sc = office(session("idle"))
        t, seen = run(sc, 0.0, 240.0)
        walked = {f.key for frames in seen for f in frames if f.pose.startswith("walk")}
        stood = {f.key for frames in seen for f in frames if f.pose.startswith("stand")}
        self.assertTrue(walked, "nobody got up in 4 minutes")
        self.assertTrue(stood)
        maxw = sc.director.max_walkers
        for frames in seen:
            self.assertLessEqual(sum(1 for f in frames if not f.pose.startswith("sit")), maxw)
            for f in frames:   # never leaves the floor
                self.assertTrue(-0.1 <= f.i <= scene.GI + 0.1 and -0.1 <= f.j <= sc.gj + 0.1, (f.i, f.j))

    def test_workers_stay_seated_and_type(self):
        busy = [agent(f"x{i}", f"a{i}") for i in range(8)]
        v, sc = office(session("busy", busy, current={"tool": "Agent", "summary": "", "at": 1}))
        t, seen = run(sc, 0.0, 120.0)
        for frames in seen:
            for f in frames:
                if f.person.role != "lead":
                    self.assertTrue(f.pose.startswith("sit"), (f.key, f.pose))
        typing = {f.frame for frames in seen for f in frames if f.person.light == model.RED}
        self.assertTrue({1, 2} <= typing)
        lead = [f for f in seen[-1] if f.person.role == "lead"][0]
        self.assertEqual(lead.bubble, ("wait", "yellow"))   # waiting for its subagents
        tools = {f.bubble for f in seen[-1] if f.person.light == model.RED}
        self.assertEqual(tools, {("look", "red")})          # real current tool (Read)

    def test_someone_called_to_work_hurries_back(self):
        v, sc = office(session("idle"))
        t, seen = run(sc, 0.0, 400.0)
        away = [f.key for f in seen[-1] if not f.pose.startswith("sit") and f.key.startswith("a:")]
        if not away:
            self.skipTest("nobody away at this instant")
        key = away[0]
        name = key.split(":", 1)[1]
        v2 = model.build(dep([ra(f"a{i}", i) for i in range(8)]),
                         session("busy", [agent("z", name)], current={"tool": "Agent", "summary": "", "at": 1}))
        sc.sync(v2, t)
        t, seen = run(sc, t, t + 30.0)
        me = [f for f in seen[-1] if f.key == key][0]
        self.assertTrue(me.pose.startswith("sit"))
        self.assertEqual(me.person.light, model.RED)

    def test_calm_mode_keeps_everyone_seated(self):
        v, sc = office(session("idle"))
        sc.director.calm = True
        t, seen = run(sc, 0.0, 200.0)
        self.assertTrue(all(f.pose.startswith("sit") for frames in seen for f in frames))

    def test_chat_bubbles_are_only_dots(self):
        v, sc = office(session("idle"))
        t, seen = run(sc, 0.0, 300.0)
        kinds = {f.bubble[0] for frames in seen for f in frames if f.bubble}
        self.assertTrue(kinds <= {"dots1", "dots2", "dots3"}, kinds)


if __name__ == "__main__":
    unittest.main()
