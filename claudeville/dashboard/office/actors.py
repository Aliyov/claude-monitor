"""Office life: who sits, types, walks, drinks coffee and chats.

Pure Python (no GTK, no cairo) so it can be unit tested.

Rules
- Working (red) and waiting (yellow) people stay at their desk. Someone who
  starts working while away hurries back.
- Idle (green) people and grey ambient fillers sometimes get up: coffee bar,
  water cooler, whiteboard, lounge bookshelf, or a chat at a colleague's desk.
  A few at a time, so the office never empties.
- Contractors (temporary desks) only exist while they run, so they never
  wander.
- Chat bubbles are decorative "..." only; tool bubbles show the REAL current
  tool of a working person.

Movement follows aisles: every seat has an exit path onto the aisle network
(aisles run along i; a "left aisle" along j joins them), so people walk in
straight isometric lines and never cut through desks.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from .look import TOOL_ICON
from .model import GREEN, GREY, RED, YELLOW, Person

SPEED = 1.7          # tiles per second
HURRY = 2.8
MAX_DT = 0.25

STAY = {"coffee": (6, 13), "cooler": (4, 8), "whiteboard": (6, 12), "lounge": (8, 15), "chat": (6, 12)}
WEIGHT = {"coffee": 3.0, "cooler": 1.5, "whiteboard": 1.5, "lounge": 1.0, "chat": 2.5}


@dataclass
class Seat:
    key: str
    i: float
    j: float
    facing: str              # front: faces +j (towards us); back: faces -j
    exit: list               # waypoints from the seat to the aisle network
    chat_point: tuple | None = None   # where a visitor stands to chat (None = no visits)
    chat_face: str = "+j"


@dataclass
class Spot:
    kind: str
    i: float
    j: float
    face: str                # +i | +j | -i | -j
    entry: tuple             # point on the aisle network
    taken: str | None = None


class Nav:
    """Aisles along i at the given j values, joined by one aisle along j at
    i = left_i. Points on the network lie on an aisle or on the left aisle."""

    def __init__(self, left_i: float, aisles: list[float]) -> None:
        self.left_i = left_i
        self.aisles = sorted(aisles)

    def route(self, a: tuple, b: tuple) -> list:
        eq = lambda x, y: abs(x - y) < 1e-6  # noqa: E731
        if eq(a[1], b[1]) or (eq(a[0], self.left_i) and eq(b[0], self.left_i)):
            return [b]
        pts = []
        if not eq(a[0], self.left_i):
            pts.append((self.left_i, a[1]))
        pts.append((self.left_i, b[1]))
        if not eq(b[0], self.left_i):
            pts.append(b)
        return pts


@dataclass
class ActorFrame:
    key: str
    person: Person
    i: float
    j: float
    pose: str
    frame: int
    flip: bool
    bubble: tuple | None     # (kind, colour)
    phase: float


@dataclass
class Actor:
    person: Person
    seat: Seat
    rng: random.Random
    i: float = 0.0
    j: float = 0.0
    mode: str = "sit"        # sit | walk | stand
    face: str = "+j"
    path: list = field(default_factory=list)
    trail: list = field(default_factory=list)
    spot: Spot | None = None
    going_home: bool = False
    hurry: bool = False
    until: float = 0.0
    next_think: float = 0.0
    phase: float = 0.0
    chat_with: str | None = None


def _dir(di, dj) -> str:
    if abs(di) >= abs(dj):
        return "+i" if di > 0 else "-i"
    return "+j" if dj > 0 else "-j"


def _wanders(p: Person) -> bool:
    return p.light in (GREEN, GREY) and p.role != "contractor"


class Director:
    def __init__(self, seats: dict[str, Seat], spots: list[Spot], nav: Nav, seed: int = 0) -> None:
        self.seats, self.spots, self.nav = seats, spots, nav
        self.seed = seed
        self.actors: dict[str, Actor] = {}
        self.last = None
        self.calm = False        # reduced animations: everyone stays seated

    # ------------------------------------------------------------ people
    def sync(self, people: list[Person], now: float) -> None:
        live = {}
        for p in people:
            seat = self.seats.get(p.key)
            if seat is None or p.light == "off":
                continue
            a = self.actors.get(p.key)
            if a is None:
                rng = random.Random(f"{self.seed}:{p.key}")
                a = Actor(person=p, seat=seat, rng=rng, i=seat.i, j=seat.j,
                          face="+j" if seat.facing == "front" else "-j",
                          next_think=now + rng.uniform(3, 22), phase=rng.random() * 10)
            a.person, a.seat = p, seat
            live[p.key] = a
        for k, a in self.actors.items():
            if k not in live and a.spot is not None:
                a.spot.taken = None
        self.actors = live

    @property
    def max_walkers(self) -> int:
        return max(1, min(3, len(self.actors) // 3))

    # -------------------------------------------------------------- think
    def _choices(self, a: Actor):
        out = []
        for s in self.spots:
            if s.taken is None:
                out.append((WEIGHT.get(s.kind, 1.0), s))
        for other in self.actors.values():
            if other is a or other.mode != "sit" or other.seat.chat_point is None:
                continue
            if any(x.chat_with == other.person.key for x in self.actors.values()):
                continue
            ci, cj = other.seat.chat_point
            out.append((WEIGHT["chat"] / max(1, len(self.actors) - 1),
                        Spot("chat", ci, cj, other.seat.chat_face, (ci, cj), taken=other.person.key)))
        return out

    def _leave(self, a: Actor, spot: Spot, now: float) -> None:
        a.spot = spot
        if spot.kind == "chat":
            a.chat_with = spot.taken
        spot.taken = a.person.key if spot.kind != "chat" else spot.taken
        start = a.seat.exit[-1] if a.seat.exit else (a.seat.i, a.seat.j)
        path = list(a.seat.exit) + self.nav.route(start, spot.entry)
        if (spot.i, spot.j) != tuple(spot.entry):
            path.append((spot.i, spot.j))
        a.path, a.trail = path, [(a.seat.i, a.seat.j)]
        a.mode, a.going_home, a.hurry = "walk", False, False

    def _go_home(self, a: Actor, hurry: bool) -> None:
        if a.spot is not None and a.spot.kind != "chat":
            a.spot.taken = None
        a.spot, a.chat_with = None, None
        a.path = list(reversed(a.trail)) + [(a.seat.i, a.seat.j)]
        a.trail = [(a.i, a.j)]
        a.mode, a.going_home, a.hurry = "walk", True, hurry

    def _think(self, a: Actor, now: float) -> None:
        walkers = sum(1 for x in self.actors.values() if x.mode != "sit")
        a.next_think = now + a.rng.uniform(7, 18)
        if walkers >= self.max_walkers or a.rng.random() > 0.5:
            return
        choices = self._choices(a)
        if not choices:
            return
        total = sum(w for w, _ in choices)
        r = a.rng.random() * total
        for w, spot in choices:
            r -= w
            if r <= 0:
                self._leave(a, spot, now)
                return

    # --------------------------------------------------------------- move
    def _advance(self, a: Actor, dist: float) -> None:
        while dist > 1e-9 and a.path:
            ti, tj = a.path[0]
            di, dj = ti - a.i, tj - a.j
            ln = math.hypot(di, dj)
            if ln < 1e-6:
                a.path.pop(0)
                continue
            a.face = _dir(di, dj)
            if ln <= dist:
                a.i, a.j = ti, tj
                a.trail.append((ti, tj))
                a.path.pop(0)
                dist -= ln
            else:
                a.i += di / ln * dist
                a.j += dj / ln * dist
                dist = 0

    def step(self, now: float) -> list[ActorFrame]:
        dt = 0.0 if self.last is None else max(0.0, min(MAX_DT, now - self.last))
        self.last = now
        for a in list(self.actors.values()):
            p = a.person
            if self.calm:
                if a.mode != "sit":
                    if a.spot is not None and a.spot.kind != "chat":
                        a.spot.taken = None
                    a.mode, a.path, a.spot, a.chat_with = "sit", [], None, None
                    a.i, a.j = a.seat.i, a.seat.j
                continue
            if a.mode != "sit" and not _wanders(p) and not a.going_home:
                self._go_home(a, hurry=True)
            if a.mode == "walk":
                self._advance(a, dt * (HURRY if a.hurry else SPEED))
                if not a.path:
                    if a.going_home:
                        a.mode, a.going_home, a.hurry = "sit", False, False
                        a.i, a.j = a.seat.i, a.seat.j
                        a.face = "+j" if a.seat.facing == "front" else "-j"
                        a.next_think = now + a.rng.uniform(12, 30)
                    else:
                        a.mode = "stand"
                        a.face = a.spot.face if a.spot else a.face
                        lo, hi = STAY.get(a.spot.kind if a.spot else "", (5, 10))
                        a.until = now + a.rng.uniform(lo, hi)
            elif a.mode == "stand":
                host = self.actors.get(a.chat_with) if a.chat_with else None
                left = a.chat_with is not None and (host is None or host.mode != "sit"
                                                    or not _wanders(host.person))
                if now >= a.until or left:
                    self._go_home(a, hurry=False)
            elif _wanders(p) and now >= a.next_think:
                self._think(a, now)
        return [self._frame(a, now) for a in self.actors.values()]

    # -------------------------------------------------------------- frames
    def _talking(self, a: Actor, now: float) -> bool:
        """Visitor and host take turns with '...' bubbles."""
        turn = int((now + 0.0) / 2.4) % 2
        if a.mode == "stand" and a.chat_with:
            return turn == 0
        if a.mode == "sit" and any(x.chat_with == a.person.key and x.mode == "stand"
                                   for x in self.actors.values()):
            return turn == 1
        if a.mode == "stand" and a.spot is not None and a.spot.kind in ("coffee", "cooler"):
            mates = sorted(x.person.key for x in self.actors.values()
                           if x.mode == "stand" and x.spot is not None and x.spot.kind == a.spot.kind)
            if len(mates) > 1:
                return mates[int(now / 2.4) % len(mates)] == a.person.key
        return False

    def _frame(self, a: Actor, now: float) -> ActorFrame:
        p = a.person
        t = now + a.phase
        bubble = None
        if p.light == RED and p.current:
            bubble = (TOOL_ICON.get(p.current.get("tool") or "", "gear"), "red")
        elif p.role == "lead" and p.light == YELLOW:
            bubble = ("ask" if p.status == "waiting" else "wait", "yellow")
        elif self._talking(a, now):
            bubble = (f"dots{1 + int(now * 3) % 3}", "ink")
        if a.mode == "sit":
            front = a.seat.facing == "front"
            pose = "sit_front" if front else "sit_back"
            if p.light == RED:
                frame = 0 if t % 7.0 < 0.9 else 1 + int(t * 6) % 2
            elif front and t % 4.7 < 0.18:
                frame = 3
            elif front and t % 19.0 < 2.4:
                frame = 4
            else:
                frame = 0
            return ActorFrame(p.key, p, a.i, a.j, pose, frame, front, bubble, a.phase)
        front = a.face in ("+i", "+j")
        flip = a.face in ("+j", "-i")
        if a.mode == "walk":
            pose = "walk_front" if front else "walk_back"
            frame = int(t * 8) % 4
        else:
            pose = "stand_front" if front else "stand_back"
            kind = a.spot.kind if a.spot else ""
            if front and t % 5.1 < 0.18:
                frame = 1
            elif front and kind in ("coffee", "cooler") and t % 7.0 < 2.2:
                frame = 2
            else:
                frame = 0
        return ActorFrame(p.key, p, a.i, a.j, pose, frame, flip, bubble, a.phase)
