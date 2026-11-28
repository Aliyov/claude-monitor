"""Isometric pixel-art office scene (original, procedural art).

One department is a diorama: plank floor, a brick wall with big city windows
on the left, a plaster wall with pipes, server racks and a whiteboard on the
right, a glass-walled lead office and private room at the back, a coffee bar,
a lounge corner, and clusters of back-to-back desks with CRT monitors and
desk lamps. People sit at desks; working people get a speech bubble with an
icon of their REAL current tool.

Projection: tile (i, j) at height z maps to
    x = ox + (i - j) * 16,   y = oy + (i + j) * 8 - z
Faces are drawn by giving cairo an affine matrix for the plane, so bricks,
planks and windows are simple rectangles in plane coordinates. Antialiasing
is off, which yields the classic 2:1 pixel stair-steps.
"""
from __future__ import annotations

import hashlib
import math
import random
from dataclasses import dataclass

import cairo

from .model import GREEN, OFF, RED, YELLOW, DepartmentView, Person

HW, HH = 16, 8            # half tile width / height in art pixels
WALL_H = 84
M = 6
SLAB = 7                   # floor thickness shown at the front edges
DESK_H = 12
GI = 17                    # tiles along the right wall
CLUSTER_I = [4.0, 7.3, 10.6, 13.9]   # desk clusters per row (each seats 2)
ROW_J0, ROW_STEP = 7.0, 4.2

LIGHT_RGB = {RED: (238, 74, 62), YELLOW: (246, 194, 56), GREEN: (88, 204, 108),
             "grey": (160, 160, 164), OFF: (70, 70, 76)}
SHIRTS = [(214, 120, 78), (78, 128, 196), (96, 164, 104), (172, 96, 160), (222, 182, 70),
          (84, 168, 176), (198, 82, 94), (124, 108, 200), (234, 140, 56), (64, 92, 120)]
SKINS = [(250, 218, 186), (236, 194, 152), (208, 158, 114), (170, 118, 82), (118, 80, 56)]
HAIRS = [(46, 34, 28), (96, 62, 36), (184, 136, 78), (28, 28, 32), (156, 72, 40), (206, 196, 176),
         (40, 90, 170)]
LEAD_SHIRT = (60, 70, 92)
FILLER_SHIRT = (150, 150, 156)


def _c(rgb, k=1.0):
    return tuple(max(0, min(255, int(v * k))) for v in rgb)


@dataclass
class Anchor:
    person: Person
    x: int           # head top centre (art px)
    y: int
    box: tuple       # x, y, w, h clickable area


@dataclass
class Rendered:
    surface: cairo.ImageSurface
    width: int
    height: int
    anchors: list
    title_xy: tuple


# --------------------------------------------------------------------- pen
class Iso:
    def __init__(self, cr: cairo.Context, ox: float, oy: float) -> None:
        self.cr, self.ox, self.oy = cr, ox, oy

    def pt(self, i, j, z=0.0):
        return self.ox + (i - j) * HW, self.oy + (i + j) * HH - z

    def color(self, rgb, a=1.0):
        self.cr.set_source_rgba(rgb[0] / 255, rgb[1] / 255, rgb[2] / 255, a)

    def rect(self, x, y, w, h, rgb, a=1.0):
        self.color(rgb, a)
        self.cr.rectangle(x, y, w, h)
        self.cr.fill()

    def px(self, x, y, rgb, a=1.0):
        self.rect(int(x), int(y), 1, 1, rgb, a)

    # planes: draw in local coordinates inside a `with`
    def floor(self, z=0.0):
        return _Plane(self.cr, cairo.Matrix(HW, HH, -HW, HH, self.ox, self.oy - z))

    def face_i(self, i, j, z=0.0):
        """Vertical plane running along +i (faces the viewer's lower left).
        Local x = tiles along i, local y = pixels *down* from height z."""
        x, y = self.pt(i, j, z)
        return _Plane(self.cr, cairo.Matrix(HW, HH, 0, 1, x, y))

    def face_j(self, i, j, z=0.0):
        """Vertical plane running along +j (faces the viewer's lower right)."""
        x, y = self.pt(i, j, z)
        return _Plane(self.cr, cairo.Matrix(-HW, HH, 0, 1, x, y))

    def box(self, i, j, z, w, d, h, rgb, top=None, k_left=0.84, k_right=0.68):
        """Solid prism; visible faces are top, +j (left) and +i (right)."""
        with self.face_i(i, j + d, z + h) as p:
            p.rect(0, 0, w, h, _c(rgb, k_left))
        with self.face_j(i + w, j, z + h) as p:
            p.rect(0, 0, d, h, _c(rgb, k_right))
        with self.floor(z + h) as p:
            p.rect(i, j, w, d, top or rgb)


class _Plane:
    def __init__(self, cr, m) -> None:
        self.cr, self.m = cr, m

    def __enter__(self):
        self.cr.save()
        self.cr.transform(self.m)
        return self

    def __exit__(self, *a):
        self.cr.restore()

    def rect(self, x, y, w, h, rgb, a=1.0):
        self.cr.set_source_rgba(rgb[0] / 255, rgb[1] / 255, rgb[2] / 255, a)
        self.cr.rectangle(x, y, w, h)
        self.cr.fill()


# ------------------------------------------------------------------ layout
def _grid(view: DepartmentView):
    """Desk clusters (2 seats each) fill slots row by row; contractor clusters
    continue in the following slots inside a taped box."""
    desks = view.by_seat("desk")
    temps = view.by_seat("temp")
    n_desk = max(2, math.ceil(len(desks) / 2))
    n_temp = math.ceil(len(temps) / 2)
    rows = math.ceil((n_desk + n_temp) / len(CLUSTER_I))
    gj = int(math.ceil(ROW_J0 + rows * ROW_STEP))
    return n_desk, n_temp, rows, max(gj, 14)


def layout_size(view: DepartmentView):
    _d, _t, _r, gj = _grid(view)
    w = (GI + gj) * HW + 2 * M
    h = WALL_H + (GI + gj) * HH + SLAB + 2 * M
    return w, h, gj


def render(view: DepartmentView) -> Rendered:
    n_desk, n_temp, rows, gj = _grid(view)
    w, h, _ = layout_size(view)
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
    cr = cairo.Context(surf)
    cr.set_antialias(cairo.ANTIALIAS_NONE)
    iso = Iso(cr, M + gj * HW, M + WALL_H)
    seed = int(hashlib.md5((view.project or str(view.slot)).encode()).hexdigest()[:8], 16)
    rng = random.Random(seed)
    lit = view.lit

    _slab(iso, gj)
    _floor(iso, gj, random.Random(seed))
    _left_wall(iso, gj, random.Random(seed + 1), lit)
    _right_wall(iso, random.Random(seed + 2))

    items: list = []   # (depth, order, draw)

    def add(depth, fn):
        items.append((depth, len(items), fn))

    anchors: list[Anchor] = []

    lead = view.by_seat("office")
    priv = view.by_seat("private")
    _room(iso, add, anchors, 0.0, 5.0, lead[0] if lead else None, big=True)
    _room(iso, add, anchors, GI - 5.0, GI, priv[0] if priv else None, big=False)
    _servers(iso, add, rng, lit)
    _coffee_bar(iso, add)
    _lounge(iso, add, gj)

    desks = view.by_seat("desk")
    temps = view.by_seat("temp")
    for slot in range(n_desk + n_temp):
        r, k = divmod(slot, len(CLUSTER_I))
        ci, cj = CLUSTER_I[k], ROW_J0 + r * ROW_STEP
        if slot < n_desk:
            seats, temp = desks[2 * slot:2 * slot + 2], False
        else:
            t = slot - n_desk
            seats, temp = temps[2 * t:2 * t + 2], True
            _tape(iso, ci - 0.45, cj - 1.45, 2.9, 3.45)
        far = seats[0] if seats else None
        near = seats[1] if len(seats) > 1 else None
        _cluster(iso, add, anchors, ci, cj, far, near, temp=temp)
    for (pi, pj) in ((3.0, gj - 0.8), (GI - 0.8, 5.4), (GI - 0.8, gj - 0.8)):
        add(pi + pj, lambda pi=pi, pj=pj: _plant(iso, pi, pj, big=True))

    items.sort(key=lambda t: (t[0], t[1]))
    for _d, _n, fn in items:
        fn()

    if not lit:   # night tint on the drawn pixels only
        cr.set_operator(cairo.OPERATOR_ATOP)
        iso.rect(0, 0, w, h, (16, 18, 34), 0.6)
        cr.set_operator(cairo.OPERATOR_OVER)
    return Rendered(surf, w, h, anchors, (M, M))


# -------------------------------------------------------------- structure
def _slab(iso: Iso, gj):
    with iso.face_i(0, gj, 0) as p:
        p.rect(0, 0, GI, SLAB, (92, 60, 40))
        p.rect(0, 0, GI, 1, (150, 100, 66))
    with iso.face_j(GI, 0, 0) as p:
        p.rect(0, 0, gj, SLAB, (70, 46, 32))
        p.rect(0, 0, gj, 1, (130, 88, 58))


def _floor(iso: Iso, gj, rng):
    base = (170, 112, 66)
    with iso.floor() as p:
        p.rect(0, 0, GI, gj, base)
        for r in range(int(gj * 4)):          # planks run along i
            jj = r / 4
            p.rect(0, jj, GI, 0.25, _c(base, (1.0, 0.95, 1.04, 0.92)[r % 4]))
            p.rect(0, jj, GI, 0.03, _c(base, 0.78))
            x = rng.random() * 3
            while x < GI:
                p.rect(x, jj, 0.05, 0.25, _c(base, 0.74))
                x += 2.2 + rng.random() * 2.5


def _brick(p, length, height, rng, base=(150, 72, 52)):
    p.rect(0, 0, length, height, (110, 66, 54))
    row, v = 0, 0
    while v < height:
        u = -0.25 if row % 2 else 0.0
        while u < length:
            k = 0.9 + rng.random() * 0.22
            p.rect(max(0, u) + 0.04, v + 1, min(0.5, length - max(0, u)) - 0.06, 3, _c(base, k))
            u += 0.5
        v += 4
        row += 1


def _left_wall(iso: Iso, gj, rng, lit):
    """Brick wall along j at i = 0, with big windows onto a city."""
    with iso.face_j(0, 0, WALL_H) as p:
        _brick(p, gj, WALL_H, rng)
        for (j0, j1) in ((4.8, 8.6), (9.6, 13.4)):
            if j1 > gj - 0.5:
                continue
            p.rect(j0 - 0.12, 10, j1 - j0 + 0.24, 52, (58, 40, 34))
            sky_top, sky_bot = ((96, 156, 214), (186, 214, 236)) if lit else ((24, 30, 60), (50, 56, 96))
            for v in range(12, 60):
                t = (v - 12) / 48
                p.rect(j0, v, j1 - j0, 1, tuple(int(a + (b - a) * t) for a, b in zip(sky_top, sky_bot)))
            jj = j0
            while jj < j1:
                bw = 0.3 + rng.random() * 0.5
                bh = 10 + rng.random() * 30
                col = (120, 140, 168) if lit else (40, 46, 74)
                p.rect(jj, 60 - bh, min(bw, j1 - jj), bh, _c(col, 0.85 + rng.random() * 0.3))
                for wv in range(int(60 - bh + 3), 58, 4):
                    if rng.random() < 0.45:
                        p.rect(jj + 0.08, wv, 0.06, 1, (210, 226, 240) if lit else (255, 236, 160))
                jj += bw + 0.05
            for m in (j0 + (j1 - j0) / 3, j0 + 2 * (j1 - j0) / 3):
                p.rect(m - 0.05, 12, 0.1, 48, (58, 40, 34))
            p.rect(j0, 36, j1 - j0, 2, (58, 40, 34))
            p.rect(j0 - 0.2, 60, j1 - j0 + 0.4, 3, (176, 150, 120))   # sill
        p.rect(0, 0, gj, 2, (196, 160, 132))
        p.rect(0, WALL_H - 3, gj, 3, (84, 56, 40))


def _right_wall(iso: Iso, rng):
    """Plaster wall along i at j = 0: pipes, whiteboard, status screen."""
    with iso.face_i(0, 0, WALL_H) as p:
        p.rect(0, 0, GI, WALL_H, (74, 96, 96))
        for v in range(0, WALL_H, 6):
            p.rect(0, v, GI, 1, (68, 88, 88))
        p.rect(0, 6, GI, 2, (150, 70, 60))
        p.rect(0, 9, GI, 2, (70, 110, 150))
        for u in (5.4, 11.2):
            p.rect(u, 6, 0.08, WALL_H - 10, (120, 124, 128))
        # whiteboard with an abstract diagram (boxes and arrows, no text)
        p.rect(8.4, 18, 2.8, 30, (220, 222, 226))
        p.rect(8.5, 19, 2.6, 28, (246, 248, 250))
        for (u, v, uw, vh, col) in ((8.7, 23, 0.6, 5, (80, 130, 210)), (10.0, 23, 0.6, 5, (210, 90, 80)),
                                    (9.3, 34, 0.7, 6, (90, 170, 100)), (10.4, 36, 0.4, 4, (80, 130, 210))):
            p.rect(u, v, uw, 1, col)
            p.rect(u, v + vh, uw, 1, col)
            p.rect(u, v, 0.05, vh, col)
            p.rect(u + uw, v, 0.05, vh + 1, col)
        p.rect(9.3, 26, 0.7, 1, (60, 60, 70))
        p.rect(9.6, 28, 0.05, 6, (60, 60, 70))
        p.rect(8.4, 48, 2.8, 2, (170, 170, 176))
        # wall-mounted screen
        p.rect(5.7, 14, 1.8, 12, (30, 32, 36))
        p.rect(5.8, 15, 1.6, 10, (24, 60, 44))
        for v in range(17, 24, 2):
            p.rect(5.9, v, 0.4 + rng.random() * 0.9, 1, (90, 220, 130))
        p.rect(0, 0, GI, 2, (120, 140, 140))
        p.rect(0, WALL_H - 3, GI, 3, (50, 62, 62))


# ------------------------------------------------------------- furniture
def _plant(iso: Iso, i, j, big=False):
    x, y = iso.pt(i, j)
    x, y = int(x), int(y)
    iso.rect(x - 4, y - 7, 8, 7, (176, 96, 62))
    iso.rect(x - 5, y - 8, 10, 2, (150, 78, 50))
    leaf, dark = (82, 160, 90), (54, 120, 66)
    hg = 18 if big else 11
    for (dx, dy, w, h, col) in ((-1, -8 - hg, 2, hg, dark), (-6, -3 - hg, 5, 3, leaf),
                                (1, -5 - hg, 6, 3, leaf), (-7, 2 - hg, 6, 3, dark),
                                (2, 1 - hg, 6, 3, dark), (-3, -10 - hg, 4, 3, leaf),
                                (-5, -12, 4, 3, leaf), (2, -13, 4, 3, leaf)):
        iso.rect(x + dx, y + dy, w, h, col)


def _servers(iso: Iso, add, rng, lit):
    for i in (5.5, 6.6):
        leds = [(v, u, rng.random() < 0.6, rng.random() < 0.7) for v in range(4, 56, 4) for u in (0.15, 0.3, 0.45)]

        def draw(i=i, leds=leds):
            iso.box(i, 0.1, 0, 1.0, 1.0, 58, (44, 48, 56), top=(70, 74, 84))
            with iso.face_i(i, 1.1, 58) as p:
                for v in range(4, 56, 4):
                    p.rect(0.08, v, 0.84, 3, (30, 33, 40))
                for v, u, on, green in leds:
                    if on:
                        col = ((90, 230, 120) if green else (240, 180, 60)) if lit else (50, 54, 60)
                        p.rect(u, v + 1, 0.06, 1, col)
        add(i + 0.6, draw)


def _coffee_bar(iso: Iso, add):
    def bar():
        iso.box(0.1, 4.6, 0, 1.3, 4.2, 16, (120, 78, 48), top=(196, 146, 96))
        iso.box(0.3, 5.0, 16, 0.8, 0.9, 12, (150, 152, 158), top=(190, 192, 198))   # espresso machine
        with iso.face_i(0.3, 5.9, 28) as p:
            p.rect(0.2, 3, 0.4, 3, (60, 60, 66))
            p.rect(0.3, 7, 0.2, 2, (240, 240, 236))
        iso.box(0.35, 7.6, 16, 0.6, 0.7, 7, (70, 60, 52), top=(90, 78, 66))          # grinder
        for jj in (6.4, 6.9, 7.2):
            x, y = iso.pt(0.8, jj, 16)
            iso.rect(int(x) - 1, int(y) - 4, 3, 4, (244, 244, 240))
            iso.px(int(x) + 2, int(y) - 3, (244, 244, 240))
    add(0.1 + 7.0, bar)
    for jj in (5.3, 6.8, 8.3):
        def stool(jj=jj):
            x, y = iso.pt(2.2, jj)
            x, y = int(x), int(y)
            iso.rect(x - 1, y - 10, 2, 10, (70, 60, 56))
            iso.rect(x - 4, y - 12, 8, 3, (140, 90, 56))
            iso.rect(x - 3, y - 1, 6, 1, (60, 52, 48))
        add(2.2 + jj, stool)


def _bookshelf_face(p, length, height, seed):
    k = seed
    for v in range(4, height - 4, 10):
        p.rect(0, v + 6, length, 1, (80, 52, 34))
        u = 0.1
        while u < length - 0.2:
            bw = 0.1 + (k % 3) * 0.04
            col = ((180, 70, 60), (70, 110, 170), (210, 170, 70), (90, 150, 100), (150, 90, 160))[k % 5]
            p.rect(u, v + 6 - (5 + k % 3), bw, 5 + k % 3, col)
            u += bw + 0.03
            k += 7


def _lounge(iso: Iso, add, gj):
    j0 = gj - 3.5

    def shelf():
        iso.box(0.1, j0, 0, 0.8, 2.6, 40, (110, 72, 46), top=(140, 96, 62))
        with iso.face_j(0.9, j0, 40) as p:
            _bookshelf_face(p, 2.6, 40, int(j0 * 13))
    add(0.5 + j0 + 1.3, shelf)
    with iso.floor() as p:
        p.rect(1.4, j0 - 0.4, 3.0, 3.2, (70, 104, 110))
        p.rect(1.6, j0 - 0.2, 2.6, 2.8, (86, 124, 130))

    def chair():
        iso.box(2.2, j0 + 0.8, 0, 1.3, 1.2, 8, (196, 98, 58), top=(220, 120, 74))
        iso.box(2.2, j0 + 0.8, 8, 0.35, 1.2, 10, (176, 84, 50), top=(210, 110, 70))
        iso.box(2.2, j0 + 0.8, 8, 1.3, 0.25, 5, (176, 84, 50))
        iso.box(2.2, j0 + 1.75, 8, 1.3, 0.25, 5, (176, 84, 50))
    add(2.8 + j0 + 1.4, chair)


def _tape(iso: Iso, i, j, w, d):
    with iso.floor() as p:
        u = 0.0
        while u < w:
            p.rect(i + u, j, 0.28, 0.08, (236, 200, 70))
            p.rect(i + u, j + d, 0.28, 0.08, (236, 200, 70))
            u += 0.5
        v = 0.0
        while v < d:
            p.rect(i, j + v, 0.06, 0.28, (236, 200, 70))
            p.rect(i + w, j + v, 0.06, 0.28, (236, 200, 70))
            v += 0.5


def _room(iso: Iso, add, anchors, i0, i1, person: Person | None, big: bool):
    """Glass-walled room at the back, i in [i0, i1), j in [0, 4)."""
    d = 4.0
    with iso.floor() as p:
        p.rect(i0 + 0.1, 0.1, i1 - i0 - 0.2, d - 0.2, (122, 82, 58))
        p.rect(i0 + 0.6, 1.6, i1 - i0 - 1.2, 2.0, (150, 62, 58) if big else (70, 96, 140))
        p.rect(i0 + 0.75, 1.75, i1 - i0 - 1.5, 1.7, (176, 82, 70) if big else (90, 118, 164))
    mid = (i0 + i1) / 2
    add(i0 + 1.2, lambda: _wall_shelf(iso, i0 + 0.3))
    add(i1 - 0.1, lambda: _plant(iso, i1 - 0.7, 0.6))
    _seated(iso, add, anchors, person, mid - 1.0, 1.4, temp=False, facing="front", exec_desk=True)
    door = (i1 - 1.6, i1 - 0.5) if big else (i0 + 0.5, i0 + 1.6)

    def glass_front():
        with iso.face_i(i0, d, 40) as p:
            for (a, b) in ((0, door[0] - i0), (door[1] - i0, i1 - i0)):
                if b <= a:
                    continue
                p.rect(a, 0, b - a, 40, (190, 226, 240), 0.22)
                p.rect(a, 30, b - a, 10, (90, 70, 56))
                p.rect(a, 0, b - a, 2, (70, 76, 84))
                u = a
                while u <= b:
                    p.rect(u, 0, 0.06, 40, (70, 76, 84))
                    u += 1.0
                p.rect(a + 0.2, 6, 0.3, 1, (240, 250, 255), 0.7)
    add(mid + d + 0.2, glass_front)

    side_i = i1 if big else i0

    def glass_side():
        with iso.face_j(side_i, 0, 40) as p:
            p.rect(0, 0, d, 40, (190, 226, 240), 0.22)
            p.rect(0, 30, d, 10, (90, 70, 56))
            p.rect(0, 0, d, 2, (70, 76, 84))
            for u in (0.0, 1.0, 2.0, 3.0, 4.0):
                p.rect(u, 0, 0.06, 40, (70, 76, 84))
    add(side_i + d / 2 + (0.3 if big else -0.3), glass_side)


def _wall_shelf(iso: Iso, i):
    iso.box(i, 0.05, 0, 1.8, 0.5, 34, (110, 72, 46), top=(140, 96, 62))
    with iso.face_i(i, 0.55, 34) as p:
        _bookshelf_face(p, 1.8, 34, int(i * 10))


# ----------------------------------------------------------------- desks
TOOL_ICON = {"Edit": "code", "Write": "code", "MultiEdit": "code", "NotebookEdit": "code",
             "Bash": "term", "Read": "look", "Grep": "look", "Glob": "look", "LS": "look",
             "WebFetch": "web", "WebSearch": "web", "Agent": "team", "Task": "team"}
GLYPHS = {
    "code": ["..#...#..", ".#..#..#.", "#...#...#", ".#.#...#.", "..#...#.."],
    "term": ["#........", ".#.......", "..#......", ".#.......", "#...####."],
    "look": [".###...", "#...#..", "#...#..", ".###.#.", ".....##"],
    "web":  [".#####.", "#.#.#.#", "#######", "#.#.#.#", ".#####."],
    "team": [".#...#.", "###.###", ".#...#.", "##...##", "##...##"],
    "gear": ["..#.#..", ".#####.", "##...##", ".#####.", "..#.#.."],
    "wait": ["#######", ".#...#.", "..#.#..", ".#...#.", "#######"],
    "ask":  [".###.", "#...#", "...#.", "..#..", "..#.."],
}


def _bubble(iso: Iso, x, y, kind, light):
    g = GLYPHS[kind]
    gw, gh = len(g[0]), len(g)
    bw, bh = gw + 6, gh + 6
    bx, by = int(x), int(y) - bh
    ink = (40, 36, 40)
    iso.rect(bx, by + 1, bw, bh - 2, ink)
    iso.rect(bx + 1, by, bw - 2, bh, ink)
    iso.rect(bx + 1, by + 1, bw - 2, bh - 2, (252, 250, 244))
    iso.rect(bx + 1, by + bh, 3, 2, ink)
    iso.rect(bx + 2, by + bh - 1, 1, 2, (252, 250, 244))
    col = {RED: (200, 60, 50), YELLOW: (190, 140, 20)}.get(light, (60, 60, 70))
    for r, row in enumerate(g):
        for c, ch in enumerate(row):
            if ch == "#":
                iso.px(bx + 3 + c, by + 3 + r, col)


def _cluster(iso: Iso, add, anchors, ci, cj, far, near, temp):
    """Two desks back to back: `far` sits behind the back desk facing the
    viewer; `near` sits in front of the front desk with the back to us."""
    _seated(iso, add, anchors, far, ci, cj, temp=temp, facing="front")
    _seated(iso, add, anchors, near, ci, cj + 1.0, temp=temp, facing="back")


def _desk(iso: Iso, i, j, w, temp, exec_desk=False):
    if temp:
        top, body = (206, 208, 212), (150, 152, 158)
        for (li, lj) in ((i + 0.1, j + 0.85), (i + w - 0.15, j + 0.85), (i + w - 0.15, j + 0.1)):
            x, y = iso.pt(li, lj)
            iso.rect(int(x), int(y) - DESK_H + 2, 1, DESK_H - 2, (110, 112, 118))
        iso.box(i, j, DESK_H - 2, w, 1.0, 2, body, top=top)
    else:
        top, body = ((150, 92, 56), (116, 72, 44)) if exec_desk else ((186, 134, 86), (140, 96, 60))
        iso.box(i, j, 0, w, 1.0, DESK_H, body, top=top)
        with iso.face_i(i, j + 1.0, DESK_H) as p:   # drawers
            p.rect(w - 0.75, 3, 0.6, 3, _c(body, 0.7))
            p.rect(w - 0.75, 7, 0.6, 3, _c(body, 0.7))
            p.rect(w - 0.5, 4, 0.1, 1, (220, 200, 160))
            p.rect(w - 0.5, 8, 0.1, 1, (220, 200, 160))


def _monitor(iso: Iso, i, j, screen_to_viewer, on, working, lines):
    iso.box(i + 0.25, j + 0.1, DESK_H, 0.2, 0.3, 2, (150, 146, 134))
    iso.box(i, j, DESK_H + 2, 0.7, 0.55, 11, (214, 208, 190), top=(230, 226, 210))
    if screen_to_viewer:
        with iso.face_i(i, j + 0.55, DESK_H + 13) as p:
            p.rect(0.06, 2, 0.58, 8, (30, 34, 40))
            if on:
                p.rect(0.08, 3, 0.54, 6, (28, 64, 48) if working else (36, 52, 72))
                if working:
                    for n, v in enumerate(range(4, 9, 2)):
                        p.rect(0.1, v, lines[n], 1, (110, 240, 150))
                else:
                    p.rect(0.3, 5, 0.1, 1, (120, 160, 210))
    # keyboard
    iso.box(i + 0.05, j + (0.62 if screen_to_viewer else -0.0) + (0 if screen_to_viewer else 0), DESK_H,
            0.6, 0.22, 1, (60, 62, 70), top=(96, 98, 108)) if screen_to_viewer else None


def _lamp(iso: Iso, i, j, light):
    x, y = iso.pt(i, j, DESK_H)
    x, y = int(x), int(y)
    rgb = LIGHT_RGB.get(light, LIGHT_RGB[OFF])
    if light in (RED, YELLOW, GREEN):
        iso.rect(x - 5, y - 2, 11, 4, rgb, 0.22)
    iso.rect(x - 2, y - 1, 5, 2, (60, 60, 66))
    iso.rect(x, y - 9, 1, 8, (60, 60, 66))
    iso.rect(x - 2, y - 13, 6, 4, rgb)
    iso.rect(x - 2, y - 13, 6, 1, _c(rgb, 1.25))


def _chair(iso: Iso, x, y, col=(52, 56, 68)):
    iso.rect(x - 6, y - 21, 12, 13, col)
    iso.rect(x - 5, y - 20, 10, 3, _c(col, 1.3))
    iso.rect(x - 1, y - 8, 2, 6, (40, 42, 50))
    iso.rect(x - 5, y - 2, 10, 2, (40, 42, 50))


def _looks(p: Person):
    seed = int(hashlib.md5((p.name or p.key).encode()).hexdigest()[:8], 16)
    shirt = LEAD_SHIRT if p.role == "lead" else FILLER_SHIRT if p.filler else SHIRTS[seed % len(SHIRTS)]
    return shirt, SKINS[(seed >> 4) % len(SKINS)], HAIRS[(seed >> 8) % len(HAIRS)], (seed >> 12) % 4


def _body_front(iso: Iso, p: Person, x, y):
    """Seated, facing the viewer; (x, y) = floor point under the chair.
    Returns the head-top y."""
    shirt, skin, hair, style = _looks(p)
    t = y - 30
    iso.rect(x - 6, t + 11, 12, 11, _c(shirt, 0.85))
    iso.rect(x - 4, t + 11, 8, 11, shirt)
    if p.role == "lead":
        iso.rect(x - 1, t + 11, 2, 6, (230, 232, 236))
        iso.rect(x, t + 12, 1, 5, (190, 60, 56))
    iso.rect(x - 4, t + 2, 8, 9, skin)
    iso.rect(x - 4, t + 10, 8, 1, _c(skin, 0.86))
    iso.rect(x - 5, t + 5, 1, 3, _c(skin, 0.92))
    iso.rect(x + 4, t + 5, 1, 3, _c(skin, 0.92))
    iso.rect(x - 4, t, 8, 3, hair)
    if style == 0:
        iso.rect(x - 5, t + 1, 1, 5, hair)
        iso.rect(x + 4, t + 1, 1, 5, hair)
    elif style == 1:
        iso.rect(x - 3, t - 1, 5, 1, hair)
    elif style == 2:
        iso.rect(x - 5, t + 1, 1, 10, hair)
        iso.rect(x + 4, t + 1, 1, 10, hair)
    else:
        iso.rect(x + 2, t - 3, 4, 4, hair)
    if p.filler:
        iso.rect(x - 3, t + 6, 6, 1, _c(skin, 0.8))
    else:
        iso.px(x - 2, t + 6, (34, 30, 34))
        iso.px(x + 1, t + 6, (34, 30, 34))
        iso.rect(x - 1, t + 8, 2, 1, _c(skin, 0.75))
    return t


def _body_back(iso: Iso, p: Person, x, y):
    shirt, skin, hair, style = _looks(p)
    t = y - 30
    iso.rect(x - 6, t + 11, 12, 11, _c(shirt, 0.8))
    iso.rect(x - 4, t + 11, 8, 11, _c(shirt, 0.92))
    iso.rect(x - 4, t + 2, 8, 9, skin)
    iso.rect(x - 4, t, 8, 9 if style != 1 else 8, hair)
    iso.rect(x - 5, t + 1, 1, 4, hair)
    iso.rect(x + 4, t + 1, 1, 4, hair)
    if style == 2:
        iso.rect(x - 4, t + 9, 8, 3, hair)
    if style == 3:
        iso.rect(x - 1, t + 9, 2, 5, hair)
    iso.rect(x - 5, t + 4, 1, 2, skin)
    iso.rect(x + 4, t + 4, 1, 2, skin)
    return t


def _seated(iso: Iso, add, anchors, person, i, j, temp, facing, exec_desk=False):
    """One work place: a 2-tile desk at row j. 'front' = the person sits
    behind it (smaller j) facing us; 'back' = in front of it, back to us."""
    lit = person is not None and person.light != OFF
    working = lit and person.working
    lr = random.Random(int(i * 100 + j * 10))
    lines = [0.1 + lr.random() * 0.4 for _ in range(3)]
    if facing == "front":
        pj = j - 0.55
        x, y = (int(v) for v in iso.pt(i + 1.0, pj))

        def behind():
            if not temp:
                _chair(iso, x, y)
            if lit:
                top = _body_front(iso, person, x, y)
                anchors.append(Anchor(person, x, top, (x - 7, top - 1, 14, 24)))
                _maybe_bubble(iso, person, x + 7, top + 4)
        add(i + 1.0 + pj, behind)

        def desk():
            _desk(iso, i, j, 2.0, temp, exec_desk)
            _monitor(iso, i + 0.65, j + 0.1, False, lit, working, lines)
            _lamp(iso, i + 1.75, j + 0.8, person.light if person else OFF)
            if exec_desk:
                mx, my = iso.pt(i + 0.3, j + 0.7, DESK_H)
                iso.rect(int(mx), int(my) - 4, 3, 4, (244, 244, 240))
        add(i + 1.0 + j + 0.5, desk)
    else:
        pj = j + 1.55
        x, y = (int(v) for v in iso.pt(i + 1.0, pj))

        def desk():
            _desk(iso, i, j, 2.0, temp)
            _monitor(iso, i + 0.75, j + 0.3, True, lit, working, lines)
            _lamp(iso, i + 0.25, j + 0.2, person.light if person else OFF)
        add(i + 1.0 + j + 0.5, desk)

        def in_front():
            if lit:
                top = _body_back(iso, person, x, y)
                anchors.append(Anchor(person, x, top, (x - 7, top - 1, 14, 24)))
                _maybe_bubble(iso, person, x + 7, top + 4)
            if not temp:
                _chair(iso, x, y + 6, (58, 62, 76))
        add(i + 1.0 + pj, in_front)


def _maybe_bubble(iso: Iso, p: Person, x, y):
    if p.role == "lead" and p.light == YELLOW:
        _bubble(iso, x, y, "ask" if p.status == "waiting" else "wait", YELLOW)
    elif p.working and p.current:
        _bubble(iso, x, y, TOOL_ICON.get(p.current.get("tool") or "", "gear"), RED)
