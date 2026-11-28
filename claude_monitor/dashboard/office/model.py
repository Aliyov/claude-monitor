"""Office View model: turns one snapshot Department (+ its live Session) into
the people that sit in it. Pure Python, no GTK, so it can be unit tested.

Rules (see docs/CONTRACT.md, "UI rules"):
- the session itself is the lead, always in its own office;
- RosterAgent rank 0 (room "private") gets the private room, the rest sit at
  tables; a team with no definition files gets 4 grey ambient fillers;
- a department always shows at least MIN_PEOPLE people (grey fillers pad it);
- a running subagent whose type names a roster agent works at that agent's
  seat; a running built-in agent (or a second parallel instance, or a type not
  in the roster) is a contractor at a temporary desk. With the default team, a
  running subagent takes over a filler seat instead;
- lights: red = working, yellow = lead waiting on the user or on its running
  subagents, green = idle / done, grey = filler (not a real agent), off = the
  department is dark. Subagents are never yellow (Claude Code reports only
  running/done).

Nothing is invented: fillers carry no name and are flagged `filler`.
"""
from __future__ import annotations

from dataclasses import dataclass, field

MIN_PEOPLE = 5
DEFAULT_FILLERS = MIN_PEOPLE - 1
# Claude Code's built-in agent types, for agents indexed before `built_in`
# existed (built_in is null). A real built_in value always wins.
BUILTIN_TYPES = {"general-purpose", "Explore", "Plan", "statusline-setup", "claude-code-guide",
                 "web-fetch", "fork", "output-style-setup"}
DELEGATING_TOOLS = {"Agent", "Task"}

RED, YELLOW, GREEN, GREY, OFF = "red", "yellow", "green", "grey", "off"


@dataclass
class Person:
    key: str                     # stable id inside the department (seat identity)
    role: str                    # lead | agent | contractor | filler
    seat: str                    # office | private | desk | temp
    name: str | None = None      # label; None for fillers
    model: str | None = None
    effort: str | None = None
    light: str = GREEN
    status: str | None = None    # raw status: busy/idle/waiting/... or running/done
    status_text: str = ""        # human text for the popup
    current: dict | None = None  # {"tool","summary","at"} while working
    agent_id: str | None = None  # the live subagent occupying this seat
    description: str | None = None

    @property
    def filler(self) -> bool:
        return self.role == "filler"

    @property
    def working(self) -> bool:
        return self.light == RED


@dataclass
class DepartmentView:
    slot: int
    lit: bool
    project: str | None
    session_id: str | None
    title: str                   # sign text
    source: str                  # roster source: agents | default
    people: list[Person] = field(default_factory=list)

    def by_seat(self, seat: str) -> list[Person]:
        return [p for p in self.people if p.seat == seat]


def _is_builtin(agent: dict) -> bool:
    b = agent.get("built_in")
    if isinstance(b, bool):
        return b
    return agent.get("type") in BUILTIN_TYPES


def lead_light(session: dict) -> tuple[str, str]:
    """(light, status text) for the lead."""
    st = session.get("status")
    running = [a for a in session.get("agents") or [] if a.get("status") == "running"]
    cur_tool = (session.get("current") or {}).get("tool")
    if st == "waiting":
        why = session.get("waiting_for")
        return YELLOW, f"Waiting for you ({why})" if why else "Waiting for you"
    if running and (st != "busy" or cur_tool in DELEGATING_TOOLS):
        n = len(running)
        return YELLOW, f"Waiting for {n} subagent{'s' if n != 1 else ''}"
    if st == "busy":
        return RED, "Working"
    if st == "blocked":
        return YELLOW, "Blocked"
    if st == "idle":
        return GREEN, "Idle"
    return GREEN, "Status unknown"


def build(dep: dict, session: dict | None) -> DepartmentView:
    lit = bool(dep.get("lit")) and session is not None
    roster = dep.get("roster") or {}
    source = roster.get("source") or "default"
    project = dep.get("project")
    view = DepartmentView(slot=int(dep.get("slot") or 0), lit=lit, project=project,
                          session_id=dep.get("session_id") if lit else None,
                          title=project or "Empty department", source=source)
    people = view.people

    # --- lead
    if lit:
        light, text = lead_light(session)
        people.append(Person(key="lead", role="lead", seat="office", name="Lead",
                             model=session.get("model"), effort=session.get("effort"), light=light,
                             status=session.get("status"), status_text=text,
                             current=session.get("current") if light == RED else None,
                             description=session.get("title")))
    else:
        people.append(Person(key="lead", role="lead", seat="office", name="Lead", light=OFF,
                             status=None, status_text="Department is dark: no live session"))

    # --- team seats
    team: list[Person] = []
    for ra in roster.get("agents") or []:
        team.append(Person(key=f"a:{ra.get('name')}", role="agent",
                           seat="private" if ra.get("room") == "private" else "desk",
                           name=ra.get("name"), model=ra.get("model"), effort=ra.get("effort"),
                           light=GREEN if lit else OFF, status="idle" if lit else None,
                           status_text="Not running" if lit else "Department is dark",
                           description=ra.get("description")))
    n_fill = DEFAULT_FILLERS if not team else max(0, MIN_PEOPLE - 1 - len(team))
    fillers = [Person(key=f"f:{i}", role="filler", seat="desk", light=GREY if lit else OFF,
                      status_text="Ambient worker (not a real agent)") for i in range(n_fill)]

    # --- live subagents
    contractors: list[Person] = []
    if lit:
        by_name = {p.name: p for p in team}
        free_fillers = list(fillers)
        running = [a for a in session.get("agents") or [] if a.get("status") == "running"]
        running.sort(key=lambda a: (a.get("started_at") or 0, a.get("agent_id") or ""))
        for a in running:
            seat_owner = by_name.get(a.get("type"))
            if seat_owner is not None and seat_owner.agent_id is None and not _is_builtin(a):
                _occupy(seat_owner, a)
                continue
            if source == "default" and free_fillers:
                f = free_fillers.pop(0)
                f.role = "agent"
                f.name = a.get("type") or "subagent"
                f.model = None
                _occupy(f, a)
                continue
            c = Person(key=f"c:{a.get('agent_id')}", role="contractor", seat="temp",
                       name=a.get("type") or "subagent")
            _occupy(c, a)
            contractors.append(c)
        # done agents of the roster: show their last run as green "done"
        for a in session.get("agents") or []:
            p = by_name.get(a.get("type"))
            if a.get("status") == "done" and p is not None and p.agent_id is None and not _is_builtin(a):
                p.status, p.status_text = "done", "Done"
                p.description = a.get("description") or p.description

    people.extend(team)
    people.extend(fillers)
    people.extend(contractors)
    return view


def _occupy(p: Person, agent: dict) -> None:
    p.agent_id = agent.get("agent_id")
    p.light = RED
    p.status = "running"
    p.status_text = "Working"
    p.current = agent.get("current")
    p.model = agent.get("model") or p.model
    p.effort = agent.get("effort") or p.effort
    p.description = agent.get("description") or p.description


def build_all(snap: dict) -> list[DepartmentView]:
    sessions = {s.get("session_id"): s for s in snap.get("sessions") or []}
    deps = (snap.get("office") or {}).get("departments")
    if not isinstance(deps, list):
        return []
    return [build(d, sessions.get(d.get("session_id"))) for d in deps]
