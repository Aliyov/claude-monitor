"""Office furniture and architecture (original procedural pixel art).

Every function draws with an iso.Pen at absolute tile coordinates. The scene
calls each one into a scratch surface, crops the result into a sprite and
outlines it, so the functions themselves only care about shapes and colours.
"""
from __future__ import annotations

import math
import random

from .iso import PX_J, Pen, mix, sh

WALL_H = 92
DESK_H = 12
WALL_T = 0.45            # wall thickness (tiles)

WOOD_FLOOR = (180, 120, 74)
BRICK = (158, 76, 56)
MORTAR = (106, 66, 56)
PANEL = (64, 94, 98)
METAL = (78, 84, 96)
DESK_WOOD = (176, 124, 80)
DESK_TOP = (204, 156, 104)
BEIGE = (222, 214, 192)
DARK = (44, 46, 54)

SKY = {
    "day": ((104, 164, 224), (196, 224, 244), (128, 148, 178), (214, 228, 240)),
    "dusk": ((86, 74, 140), (246, 152, 104), (84, 70, 108), (255, 214, 140)),
    "night": ((14, 20, 48), (40, 48, 94), (30, 34, 60), (255, 222, 140)),
}


# ------------------------------------------------------------- structure
def floor(p: Pen, gi, gj, rng: random.Random) -> None:
    base = WOOD_FLOOR
    with p.floor() as f:
        f.rect(0, 0, gi, gj, base)
        r = 0.0
        while r < gj - 1e-6:
            x = -rng.random() * 2.5
            while x < gi:
                ln = 1.6 + rng.random() * 2.6
                tone = 0.9 + rng.random() * 0.16
                c = sh(base, tone)
                x0, x1 = max(0.0, x), min(gi, x + ln)
                f.rect(x0, r, x1 - x0, 0.5, c)
                for _ in range(2):
                    gx = x0 + rng.random() * max(0.1, x1 - x0 - 0.6)
                    gw = min(0.3 + rng.random() * 0.5, x1 - gx - 0.08)
                    f.rect(gx, r + 0.12 + rng.random() * 0.25, gw, PX_J, sh(c, 0.88))
                if rng.random() < 0.15 and x1 - x0 > 0.3:
                    f.rect(x0 + 0.05 + rng.random() * (x1 - x0 - 0.2), r + 0.2, 0.07, PX_J, sh(c, 0.7))
                f.rect(x1 - 1 / 16, r, 1 / 16, 0.5, sh(base, 0.66))
                x += ln
            f.rect(0, r, gi, PX_J, sh(base, 0.72))
            r += 0.5
        # ambient occlusion along both walls
        for k, a in ((0.0, 0.22), (0.25, 0.12), (0.5, 0.05)):
            f.rect(0, k, gi, 0.25, (40, 20, 10), a)
            f.rect(k, 0, 0.25, gj, (40, 20, 10), a)


def slab(p: Pen, gi, gj, depth=8) -> None:
    with p.face_i(0, gj, 0) as f:
        f.rect(-WALL_T, 0, gi + WALL_T, depth, (96, 62, 40))
        f.rect(-WALL_T, 0, gi + WALL_T, 1, (160, 108, 70))
        f.rect(-WALL_T, depth - 2, gi + WALL_T, 2, (70, 44, 30))
    with p.face_j(gi, -WALL_T, 0) as f:
        f.rect(0, 0, gj + WALL_T, depth, (74, 48, 32))
        f.rect(0, 0, gj + WALL_T, 1, (136, 92, 60))
        f.rect(0, depth - 2, gj + WALL_T, 2, (54, 34, 24))


def _bricks(f, length, height, rng, v0=0):
    f.rect(0, v0, length, height, MORTAR)
    row, v = 0, v0
    while v < v0 + height:
        u = -0.25 if row % 2 else 0.0
        while u < length:
            k = 0.86 + rng.random() * 0.26
            c = sh(BRICK, k)
            a = max(0.0, u)
            w = min(0.5, length - a, u + 0.5 - a) - 0.05
            f.rect(a + 0.03, v + 1, w, 3, c)
            f.rect(a + 0.03, v + 1, w, 1, sh(c, 1.12))
            u += 0.5
        v += 4
        row += 1


def _window(f, j0, j1, top, bot, rng, phase):
    sky0, sky1, bld, lit = SKY[phase]
    f.rect(j0 - 0.14, top - 3, j1 - j0 + 0.28, bot - top + 6, (70, 48, 38))
    for v in range(top, bot):
        t = (v - top) / max(1, bot - top - 1)
        f.rect(j0, v, j1 - j0, 1, mix(sky0, sky1, t))
    if phase == "day":
        for cx, cv in ((j0 + 0.6, top + 6), (j0 + 2.2, top + 10)):
            f.rect(cx, cv, 0.7, 2, (244, 248, 252))
            f.rect(cx + 0.15, cv - 1, 0.4, 1, (244, 248, 252))
    elif phase == "night":
        for _ in range(6):
            f.rect(j0 + rng.random() * (j1 - j0), top + rng.random() * 14, 1 / 16, 1, (230, 230, 250))
        f.rect(j1 - 0.8, top + 4, 0.25, 3, (240, 236, 210))
    # far skyline
    jj = j0
    while jj < j1:
        bw = 0.25 + rng.random() * 0.35
        bh = 14 + rng.random() * 18
        f.rect(jj, bot - bh, min(bw, j1 - jj), bh, mix(bld, sky1, 0.45))
        jj += bw
    # near skyline with lit windows
    jj = j0
    while jj < j1:
        bw = 0.35 + rng.random() * 0.55
        bh = 8 + rng.random() * 26
        c = sh(bld, 0.85 + rng.random() * 0.25)
        f.rect(jj, bot - bh, min(bw, j1 - jj), bh, c)
        f.rect(jj, bot - bh, min(bw, j1 - jj), 1, sh(c, 1.15))
        for wv in range(int(bot - bh + 3), bot - 2, 3):
            for wu in (0.08, 0.22, 0.36):
                if jj + wu + 0.06 < min(j1, jj + bw) and rng.random() < (0.5 if phase != "day" else 0.25):
                    f.rect(jj + wu, wv, 1 / 16, 1, lit if phase != "day" else sh(c, 1.3))
        jj += bw + 0.04
    # frame: mullions, transom, sill
    for m in (j0 + (j1 - j0) / 3, j0 + 2 * (j1 - j0) / 3):
        f.rect(m - 0.06, top, 0.12, bot - top, (70, 48, 38))
    f.rect(j0, top + (bot - top) // 2, j1 - j0, 2, (70, 48, 38))
    f.rect(j0, top, 0.25, bot - top, (255, 255, 255), 0.06)
    f.rect(j0 - 0.25, bot + 3, j1 - j0 + 0.5, 3, (196, 168, 134))
    f.rect(j0 - 0.25, bot + 3, j1 - j0 + 0.5, 1, (226, 202, 170))


WINDOWS = ((4.6, 8.3), (9.0, 12.7))


def windows_for(gj) -> list:
    """The two windows by the coffee bar, then more every 4.4 tiles along a
    long wall (big teams make the office deeper)."""
    out = [w for w in WINDOWS if w[1] < gj - 0.6]
    j0 = 13.4
    while j0 + 3.7 < gj - 4.2:          # keep the lounge corner free
        out.append((j0, j0 + 3.7))
        j0 += 4.4
    return out


def left_wall(p: Pen, gj, rng, phase) -> None:
    """Brick wall along j at i = 0 with big windows onto the city."""
    with p.face_j(0, 0, WALL_H) as f:
        _bricks(f, gj, WALL_H, rng)
        for j0, j1 in windows_for(gj):
            _window(f, j0, j1, 14, 62, rng, phase)
        # wall sconces between windows
        f.rect(8.55, 30, 0.25, 6, (60, 56, 52))
        f.rect(8.5, 28, 0.35, 3, (250, 220, 150))
        # framed picture near the lounge
        if gj > 16.5:
            f.rect(gj - 3.0, 22, 1.4, 22, (60, 44, 36))
            f.rect(gj - 2.92, 24, 1.24, 18, (236, 226, 206))
            f.rect(gj - 2.8, 30, 1.0, 8, (96, 150, 120))
            f.rect(gj - 2.5, 26, 0.4, 6, (220, 150, 80))
        f.rect(0, WALL_H - 5, gj, 5, (86, 56, 42))           # skirting
        f.rect(0, WALL_H - 5, gj, 1, (120, 84, 62))
    # wall thickness: cap and front end
    with p.floor(WALL_H) as f:
        f.rect(-WALL_T, -WALL_T, WALL_T, gj + WALL_T, (210, 190, 170))
        f.rect(-PX_J, -WALL_T, PX_J, gj + WALL_T, (236, 220, 200))
    with p.face_i(-WALL_T, gj, WALL_H) as f:
        f.rect(0, 0, WALL_T, WALL_H, (126, 60, 44))
        f.rect(0, 0, WALL_T, 2, (210, 190, 170))


def right_wall(p: Pen, gi, rng) -> None:
    """Panelled wall along i at j = 0: pipes, whiteboard, posters."""
    with p.face_i(0, 0, WALL_H) as f:
        f.rect(0, 0, gi, WALL_H, PANEL)
        u = 0.0
        while u < gi:
            f.rect(u, 18, 1 / 16, WALL_H - 18, sh(PANEL, 0.86))
            u += 1.4
        f.rect(0, 16, gi, 2, sh(PANEL, 1.18))
        f.rect(0, 0, gi, 16, sh(PANEL, 0.86))
        # pipes with brackets
        f.rect(0, 5, gi, 3, (164, 74, 62))
        f.rect(0, 5, gi, 1, (206, 112, 96))
        f.rect(0, 10, gi, 3, (74, 116, 160))
        f.rect(0, 10, gi, 1, (120, 160, 200))
        for bu in (1.5, 4.0, 7.8, 11.6, 14.6):
            f.rect(bu, 4, 0.12, 10, (130, 132, 138))
        f.rect(8.0, 9, 0.35, 5, (200, 70, 60))   # valve
        # whiteboard with an abstract diagram (no text)
        f.rect(8.3, 24, 2.95, 34, (176, 178, 186))
        f.rect(8.38, 25, 2.8, 31, (248, 250, 252))
        for (bu, bv, bw, bh, col) in ((8.6, 29, 0.6, 5, (70, 120, 210)), (9.9, 29, 0.6, 5, (210, 80, 70)),
                                      (9.25, 41, 0.75, 6, (80, 170, 96)), (10.5, 44, 0.4, 5, (70, 120, 210))):
            f.rect(bu, bv, bw, 1, col)
            f.rect(bu, bv + bh, bw, 1, col)
            f.rect(bu, bv, 1 / 16, bh, col)
            f.rect(bu + bw, bv, 1 / 16, bh + 1, col)
        f.rect(9.2, 32, 0.7, 1, (60, 60, 72))
        f.rect(9.6, 35, 1 / 16, 6, (60, 60, 72))
        f.rect(10.5, 36, 0.3, 1, (60, 60, 72))
        f.rect(8.3, 58, 2.95, 2, (150, 152, 160))
        for k, col in enumerate(((210, 60, 60), (60, 110, 210), (40, 40, 40))):
            f.rect(9.0 + k * 0.25, 57, 0.18, 1, col)
        # wall screen frame above the servers (content is animated)
        f.rect(5.55, 22, 2.0, 16, (30, 32, 38))
        f.rect(5.63, 23, 1.84, 14, (16, 30, 26))
        # posters in the rooms
        f.rect(3.0, 26, 1.1, 18, (60, 44, 36))
        f.rect(3.07, 27, 0.96, 16, (240, 196, 92))
        f.rect(3.2, 31, 0.6, 8, (214, 98, 70))
        f.rect(14.9, 26, 1.1, 18, (60, 44, 36))
        f.rect(14.97, 27, 0.96, 16, (120, 176, 210))
        f.rect(15.1, 33, 0.7, 6, (240, 240, 236))
        # air vent
        f.rect(12.6, 22, 0.9, 6, (120, 126, 130))
        for vv in range(23, 28, 2):
            f.rect(12.65, vv, 0.8, 1, (80, 86, 92))
        f.rect(0, WALL_H - 5, gi, 5, (40, 58, 60))
        f.rect(0, WALL_H - 5, gi, 1, (90, 120, 122))
    with p.floor(WALL_H) as f:
        f.rect(-WALL_T, -WALL_T, gi + WALL_T, WALL_T, (190, 204, 200))
        f.rect(-WALL_T, -PX_J, gi + WALL_T, PX_J, (220, 232, 228))
    with p.face_j(gi, -WALL_T, WALL_H) as f:
        f.rect(0, 0, WALL_T, WALL_H, (44, 66, 70))
        f.rect(0, 0, WALL_T, 2, (190, 204, 200))


def window_light(p: Pen, gj, phase) -> None:
    """Sunlight pooling on the floor below the windows."""
    if phase == "night":
        return
    col = (255, 236, 170) if phase == "day" else (255, 176, 120)
    with p.floor(0) as f:
        for j0, j1 in windows_for(gj):
            for k, a in ((0, 0.10), (1, 0.07)):
                f.rect(1.5 + k * 0.6, j0 + 0.9 + k * 0.3, 3.2 - k * 1.0, j1 - j0 - 0.4, col, a)


def room_floor(p: Pen, i0, i1, d, rug, accent) -> None:
    with p.floor(0) as f:
        f.rect(i0, 0, i1 - i0, d, (128, 86, 60))
        y = 0.0
        while y < d:
            f.rect(i0, y, i1 - i0, PX_J, (106, 70, 50))
            y += 0.5
        f.rect(i0 + 0.6, 1.4, i1 - i0 - 1.2, 2.3, sh(rug, 0.8))
        f.rect(i0 + 0.75, 1.55, i1 - i0 - 1.5, 2.0, rug)
        f.rect(i0 + 1.0, 1.8, i1 - i0 - 2.0, 1.5, accent)
        f.rect(i0 + 1.15, 1.95, i1 - i0 - 2.3, 1.2, rug)


# ---------------------------------------------------------- furniture
def plant(p: Pen, i, j, size=1.0, pot=(184, 98, 64)) -> None:
    x, y = p.ipt(i, j)
    pw = int(8 * size)
    p.rect(x - pw // 2, y - int(8 * size), pw, int(8 * size), pot)
    p.rect(x - pw // 2, y - int(8 * size), 2, int(8 * size), sh(pot, 1.15))
    p.rect(x - pw // 2 - 1, y - int(9 * size), pw + 2, 2, sh(pot, 0.8))
    p.rect(x - pw // 2, y - int(9 * size), pw, 1, (70, 50, 36))
    leaf, dark, light = (78, 160, 88), (48, 116, 64), (130, 200, 110)
    h = int(22 * size)
    base = y - int(9 * size)
    for k, (dx, dy, w, hh, col) in enumerate(((-1, -h, 2, h, dark), (-7, -h + 6, 6, 3, leaf),
                                              (1, -h + 3, 7, 3, leaf), (-8, -h + 12, 7, 3, dark),
                                              (2, -h + 10, 7, 3, dark), (-4, -h - 2, 5, 3, leaf),
                                              (-6, -6, 5, 3, leaf), (2, -7, 5, 3, leaf),
                                              (-3, -h + 1, 2, 2, light), (4, -h + 4, 2, 1, light))):
        p.rect(x + int(dx * size), base + int(dy * size), max(1, int(w * size)), max(1, int(hh * size)), col)


def mini_plant(p: Pen, i, j, z) -> None:
    x, y = p.ipt(i, j, z)
    p.rect(x - 2, y - 3, 4, 3, (230, 230, 226))
    p.rect(x - 2, y - 6, 4, 3, (84, 164, 92))
    p.rect(x - 1, y - 7, 2, 1, (120, 196, 110))


def mug(p: Pen, i, j, z, col=(244, 244, 240)) -> None:
    x, y = p.ipt(i, j, z)
    p.rect(x - 1, y - 4, 3, 4, col)
    p.px(x + 2, y - 3, col)
    p.px(x - 1, y - 4, (120, 76, 50))


def papers(p: Pen, i, j, z) -> None:
    p.box(i, j, z, 0.4, 0.3, 2, (238, 238, 232), top=(250, 250, 246), hi=False)
    with p.floor(z + 2) as f:
        f.rect(i + 0.08, j + 0.08, 0.25, PX_J, (150, 150, 160))


def office_chair(p: Pen, x, y, view, seat=(70, 80, 110)) -> None:
    """Swivel chair at floor point (x, y). view: front (we see the seat and
    the back behind it) or back (we see the backrest from behind)."""
    x, y = int(x), int(y)
    dark = (40, 40, 46)
    for dx, dy in ((-7, -1), (6, -1), (-4, 1), (3, 1), (-1, -2)):
        p.rect(x + dx, y + dy, 2, 2, dark)
    p.rect(x - 6, y - 2, 12, 1, (60, 60, 68))
    p.rect(x - 1, y - 9, 2, 7, (96, 98, 108))
    if view == "front":
        p.rect(x - 6, y - 24, 12, 14, sh(seat, 0.9))
        p.rect(x - 5, y - 23, 10, 3, sh(seat, 1.15))
        p.rect(x - 7, y - 13, 14, 4, seat)
        p.rect(x - 7, y - 13, 14, 1, sh(seat, 1.2))
        p.rect(x - 8, y - 17, 2, 6, dark)
        p.rect(x + 6, y - 17, 2, 6, dark)
    else:
        p.rect(x - 7, y - 12, 14, 4, seat)
        p.rect(x - 6, y - 26, 12, 15, sh(seat, 0.8))
        p.rect(x - 6, y - 26, 12, 2, sh(seat, 1.0))
        p.rect(x - 1, y - 11, 2, 2, dark)
        p.rect(x - 8, y - 17, 2, 5, dark)
        p.rect(x + 6, y - 17, 2, 5, dark)


def exec_chair(p: Pen, x, y) -> None:
    x, y = int(x), int(y)
    leather = (112, 58, 42)
    dark = (40, 40, 46)
    for dx, dy in ((-7, -1), (6, -1), (-4, 1), (3, 1)):
        p.rect(x + dx, y + dy, 2, 2, dark)
    p.rect(x - 1, y - 9, 2, 7, (120, 122, 130))
    p.rect(x - 8, y - 32, 16, 22, sh(leather, 0.9))
    for ty in (y - 28, y - 22, y - 16):
        for tx in (x - 5, x - 1, x + 3):
            p.px(tx, ty, sh(leather, 0.65))
    p.rect(x - 7, y - 31, 14, 2, sh(leather, 1.25))
    p.rect(x - 8, y - 13, 16, 4, leather)
    p.rect(x - 9, y - 18, 2, 7, sh(leather, 0.7))
    p.rect(x + 7, y - 18, 2, 7, sh(leather, 0.7))


def _desk(p: Pen, i, j, w, d, wood=DESK_WOOD, top=DESK_TOP, pedestal_side="right") -> None:
    legc = sh(wood, 0.7)
    p.box(i + 0.05, j + 0.08, 0, 0.12, d - 0.16, DESK_H - 2, legc, hi=False)
    p.box(i + w - 0.17, j + 0.08, 0, 0.12, d - 0.16, DESK_H - 2, legc, hi=False)
    pi = i + w - 0.75 if pedestal_side == "right" else i + 0.15
    p.box(pi, j + 0.12, 0, 0.6, d - 0.24, DESK_H - 2, wood)
    with p.face_i(pi, j + d - 0.12, DESK_H - 2) as f:
        for v in (1, 5):
            f.rect(0.05, v, 0.5, 3, sh(wood, 0.78))
            f.rect(0.22, v + 1, 0.16, 1, (230, 214, 180))
    p.box(i, j, DESK_H - 2, w, d, 2, wood, top=top)


def crt(p: Pen, i, j, screen_front: bool, seed) -> None:
    """Chunky CRT on a desk at (i, j)."""
    z = DESK_H
    p.box(i + 0.2, j + 0.15, z, 0.35, 0.3, 1, (170, 164, 146), hi=False)
    if screen_front:
        p.box(i + 0.1, j, z + 1, 0.55, 0.45, 9, sh(BEIGE, 0.92))      # tube (behind)
        p.box(i, j + 0.4, z + 1, 0.75, 0.2, 12, BEIGE, top=(236, 230, 212))
        with p.face_i(i, j + 0.6, z + 13) as f:
            f.rect(0.05, 1, 0.65, 10, sh(BEIGE, 0.9))
            f.rect(0.09, 2, 0.57, 7, (22, 26, 30))
            f.rect(0.55, 10, 0.08, 1, (90, 220, 120))
    else:
        p.box(i, j, z + 1, 0.75, 0.2, 12, BEIGE, top=(236, 230, 212))
        p.box(i + 0.1, j + 0.2, z + 1, 0.55, 0.45, 9, sh(BEIGE, 0.92))
        with p.face_i(i + 0.1, j + 0.65, z + 10) as f:
            for v in (2, 4, 6):
                f.rect(0.1, v, 0.35, 1, sh(BEIGE, 0.7))


def flat(p: Pen, i, j, screen_front: bool, seed) -> None:
    z = DESK_H
    p.box(i + 0.25, j + 0.1, z, 0.3, 0.25, 1, DARK, hi=False)
    p.box(i + 0.36, j + 0.18, z + 1, 0.08, 0.08, 4, (70, 72, 80), hi=False)
    p.box(i, j + 0.12, z + 4, 0.85, 0.1, 10, DARK, top=(70, 72, 82))
    if screen_front:
        with p.face_i(i, j + 0.22, z + 14) as f:
            f.rect(0.05, 1, 0.75, 8, (18, 22, 28))
            f.rect(0.7, 9, 0.06, 1, (90, 180, 240))


def laptop(p: Pen, i, j, screen_front: bool) -> None:
    z = DESK_H
    if screen_front:
        p.box(i, j + 0.25, z, 0.7, 0.4, 1, (150, 154, 162), top=(178, 182, 190), hi=False)
        p.box(i, j + 0.15, z + 1, 0.7, 0.08, 7, (120, 124, 132), hi=False)
        with p.face_i(i, j + 0.23, z + 8) as f:
            f.rect(0.05, 1, 0.6, 5, (20, 24, 30))
    else:
        p.box(i, j, z, 0.7, 0.4, 1, (150, 154, 162), top=(178, 182, 190), hi=False)
        p.box(i, j + 0.4, z + 1, 0.7, 0.08, 7, (176, 180, 188), hi=False)
        with p.face_i(i, j + 0.48, z + 8) as f:
            f.rect(0.28, 3, 0.14, 2, (230, 232, 236))


def keyboard(p: Pen, i, j) -> None:
    p.box(i, j, DESK_H, 0.62, 0.2, 1, (70, 72, 80), top=(104, 106, 116), hi=False)
    with p.floor(DESK_H + 1) as f:
        for k in range(5):
            f.rect(i + 0.05 + k * 0.11, j + 0.06, 0.06, PX_J, (150, 152, 160))
    x, y = p.ipt(i + 0.85, j + 0.12, DESK_H)
    p.rect(x, y - 1, 2, 1, (210, 210, 214))


def pc_tower(p: Pen, i, j) -> None:
    p.box(i, j, 0, 0.3, 0.6, 13, (60, 62, 70), top=(86, 88, 98))
    with p.face_i(i, j + 0.6, 13) as f:
        f.rect(0.05, 2, 0.2, 1, (40, 40, 44))
        f.rect(0.18, 9, 0.06, 1, (90, 230, 120))


def cluster(p: Pen, ci, cj, seed: int, temp: bool) -> dict:
    """Two desks back to back at (ci..ci+2, cj..cj+2). Returns geometry for
    the dynamic screen overlays."""
    rng = random.Random(seed)
    geo = {}
    if temp:
        for j in (cj, cj + 1.0):
            for li, lj in ((ci + 0.1, j + 0.1), (ci + 1.8, j + 0.1), (ci + 0.1, j + 0.82), (ci + 1.8, j + 0.82)):
                p.box(li, lj, 0, 0.08, 0.08, DESK_H - 2, (110, 112, 120), hi=False)
            p.box(ci, j, DESK_H - 2, 2.0, 0.95, 2, (176, 180, 186), top=(214, 216, 222))
        laptop(p, ci + 0.55, cj + 0.15, False)
        laptop(p, ci + 0.65, cj + 1.15, True)
        geo["near_screen"] = ("laptop", ci + 0.65, cj + 1.38, DESK_H + 8)
        mug(p, ci + 1.6, cj + 1.6, DESK_H)
        return geo
    _desk(p, ci, cj, 2.0, 1.0, pedestal_side="left")
    _desk(p, ci, cj + 1.0, 2.0, 1.0)
    # privacy divider
    p.box(ci + 0.05, cj + 0.94, DESK_H, 1.9, 0.12, 9, (96, 126, 140), top=(126, 156, 170))
    p.box(ci + 0.05, cj + 0.94, DESK_H + 9, 1.9, 0.12, 1, (70, 74, 84), hi=False)
    far_crt, near_crt = rng.random() < 0.5, rng.random() < 0.5
    # far seat (faces +j): monitor back to us
    (crt if far_crt else flat)(p, ci + 0.6, cj + 0.25, False, seed)
    keyboard(p, ci + 0.66, cj + 0.04)
    # near seat (faces -j): screen to us
    if near_crt:
        crt(p, ci + 0.6, cj + 1.12, True, seed)
        geo["near_screen"] = ("crt", ci + 0.6, cj + 1.72, DESK_H + 13)
    else:
        flat(p, ci + 0.55, cj + 1.1, True, seed)
        geo["near_screen"] = ("flat", ci + 0.55, cj + 1.32, DESK_H + 14)
    keyboard(p, ci + 0.66, cj + 1.72)
    # clutter
    if rng.random() < 0.7:
        mug(p, ci + 1.55, cj + 0.3, DESK_H, rng.choice(((244, 244, 240), (220, 90, 80), (80, 140, 210))))
    if rng.random() < 0.6:
        papers(p, ci + 1.35, cj + 1.45, DESK_H)
    if rng.random() < 0.5:
        mini_plant(p, ci + 0.25, cj + 0.35, DESK_H)
    if rng.random() < 0.6:
        mug(p, ci + 1.65, cj + 1.75, DESK_H, rng.choice(((244, 244, 240), (240, 190, 70))))
    if rng.random() < 0.5:
        x, y = p.ipt(ci + 0.4, cj + 1.5, DESK_H)
        p.rect(x - 1, y - 5, 3, 5, (70, 120, 180))     # pen cup
        p.px(x - 1, y - 6, (220, 60, 60))
        p.px(x + 1, y - 7, (240, 200, 60))
    if rng.random() < 0.6:
        pc_tower(p, ci + 2.1, cj + 1.2)
    if rng.random() < 0.4:
        pc_tower(p, ci - 0.4, cj + 0.2)
    return geo


def exec_desk(p: Pen, i, j) -> None:
    wood, top = (128, 76, 46), (158, 98, 60)
    _desk(p, i, j, 2.2, 1.0, wood, top)
    p.box(i, j + 0.95, 0, 2.2, 0.08, DESK_H - 2, sh(wood, 0.85), hi=False)   # modesty panel
    for mi in (i + 0.05, i + 1.45):
        p.box(mi + 0.3, j + 0.15, DESK_H, 0.2, 0.2, 4, DARK, hi=False)
        p.box(mi, j + 0.1, DESK_H + 4, 0.7, 0.1, 10, DARK, top=(70, 72, 82))
    mug(p, i + 0.25, j + 0.75, DESK_H)
    papers(p, i + 1.65, j + 0.6, DESK_H)
    keyboard(p, i + 0.85, j + 0.1)
    x, y = p.ipt(i + 1.1, j + 0.85, DESK_H)
    p.rect(x - 3, y - 2, 6, 2, (200, 170, 90))          # nameplate (blank)


def wall_shelf(p: Pen, i, j=0.05, w=1.8, h=36, books_seed=1) -> None:
    wood = (116, 76, 48)
    p.box(i, j, 0, w, 0.5, h, wood, top=(146, 100, 66))
    rng = random.Random(books_seed)
    with p.face_i(i, j + 0.5, h) as f:
        f.rect(0.05, 2, w - 0.1, h - 4, sh(wood, 0.6))
        for v in range(3, h - 4, 10):
            u = 0.1
            while u < w - 0.2:
                bw = 0.08 + rng.random() * 0.08
                bh = 5 + rng.randint(0, 3)
                col = rng.choice(((186, 70, 60), (70, 112, 176), (214, 172, 70), (90, 152, 100),
                                  (150, 92, 160), (230, 226, 214)))
                f.rect(u, v + 8 - bh, bw, bh, col)
                f.rect(u, v + 8 - bh, bw, 1, sh(col, 1.2))
                u += bw + 0.02
                if rng.random() < 0.08:
                    u += 0.2
            f.rect(0.05, v + 8, w - 0.1, 2, wood)


def tall_bookcase(p: Pen, i, j, d, h=46, seed=3) -> None:
    """Bookcase standing against the left wall, books on its +i face."""
    wood = (110, 72, 46)
    p.box(i, j, 0, 0.6, d, h, wood, top=(142, 98, 64))
    rng = random.Random(seed)
    with p.face_j(i + 0.6, j, h) as f:
        f.rect(0.05, 2, d - 0.1, h - 4, sh(wood, 0.55))
        for v in range(3, h - 4, 10):
            u = 0.08
            while u < d - 0.15:
                bw = 0.07 + rng.random() * 0.08
                bh = 5 + rng.randint(0, 3)
                col = rng.choice(((186, 70, 60), (70, 112, 176), (214, 172, 70), (90, 152, 100), (150, 92, 160)))
                f.rect(u, v + 8 - bh, bw, bh, col)
                u += bw + 0.02
            f.rect(0.05, v + 8, d - 0.1, 2, wood)


def glass_front(p: Pen, i0, i1, j, door) -> None:
    frame = (82, 88, 100)
    with p.face_i(i0, j, 44) as f:
        for a, b in ((0, door[0] - i0), (door[1] - i0, i1 - i0)):
            if b <= a:
                continue
            f.rect(a, 0, b - a, 44, (180, 220, 240), 0.2)
            f.rect(a + 0.15, 4, 0.12, 22, (255, 255, 255), 0.35)
            f.rect(a + 0.35, 8, 0.06, 12, (255, 255, 255), 0.25)
            f.rect(a, 0, b - a, 2, frame)
            f.rect(a, 34, b - a, 10, (112, 84, 64))
            f.rect(a, 34, b - a, 1, (150, 116, 90))
            u = a
            while u <= b + 1e-6:
                f.rect(min(u, b) - 0.04, 0, 0.08, 44, frame)
                u += 1.0
        # door frame
        da, db = door[0] - i0, door[1] - i0
        f.rect(da - 0.04, 0, 0.08, 44, frame)
        f.rect(db - 0.04, 0, 0.08, 44, frame)
        f.rect(da, 0, db - da, 3, frame)


def glass_side(p: Pen, i, j0, j1) -> None:
    frame = (82, 88, 100)
    with p.face_j(i, j0, 44) as f:
        f.rect(0, 0, j1 - j0, 44, (180, 220, 240), 0.2)
        f.rect(0.3, 4, 0.12, 22, (255, 255, 255), 0.3)
        f.rect(0, 0, j1 - j0, 2, frame)
        f.rect(0, 34, j1 - j0, 10, (112, 84, 64))
        f.rect(0, 34, j1 - j0, 1, (150, 116, 90))
        u = 0.0
        while u <= j1 - j0 + 1e-6:
            f.rect(min(u, j1 - j0) - 0.04, 0, 0.08, 44, frame)
            u += 1.0


def server_rack(p: Pen, i, j, h=62) -> None:
    p.box(i, j, 0, 1.0, 1.0, h, (38, 42, 50), top=(70, 74, 86))
    with p.face_i(i, j + 1.0, h) as f:
        f.rect(0.06, 2, 0.88, h - 4, (26, 28, 34))
        for v in range(4, h - 6, 4):
            f.rect(0.1, v, 0.8, 3, (46, 50, 60))
            f.rect(0.1, v, 0.8, 1, (64, 68, 80))
            f.rect(0.72, v + 1, 0.12, 1, (110, 116, 128))
    with p.face_j(i + 1.0, j, h) as f:
        for v in range(6, h - 6, 3):
            f.rect(0.15, v, 0.7, 1, (30, 32, 38))


def server_leds(p: Pen, i, j, h, frame: int, lit: bool) -> None:
    rng = random.Random(int(i * 100) + frame * 7919)
    with p.face_i(i, j + 1.0, h) as f:
        for v in range(4, h - 6, 4):
            for u in (0.16, 0.26, 0.36, 0.46):
                if rng.random() < 0.55:
                    col = (90, 236, 120) if rng.random() < 0.75 else (246, 186, 60)
                    f.rect(u, v + 1, 1 / 16, 1, col if lit else (54, 58, 66))


def wall_screen(p: Pen, frame: int) -> None:
    with p.face_i(0, 0, WALL_H) as f:
        rng = random.Random(frame * 31 + 5)
        for k in range(6):
            hgt = 2 + int(rng.random() * 8)
            f.rect(5.75 + k * 0.28, 36 - hgt, 0.18, hgt, (90, 220, 140))
        f.rect(5.7, 25, 1.7, 1, (120, 200, 255))
        f.rect(5.7 + (frame % 6) * 0.28, 25, 0.25, 1, (250, 250, 250))


def clock(p: Pen, i, z, hour: int, minute: int) -> None:
    """Wall clock on the right wall at (i, z) showing local time."""
    with p.face_i(i, 0, z) as f:
        f.rect(0, 0, 0.75, 12, (52, 44, 40))
        f.rect(0.06, 1, 0.63, 10, (246, 244, 236))
        for (u, v) in ((0.35, 1), (0.35, 10), (0.08, 5.5), (0.62, 5.5)):
            f.rect(u, v, 1 / 16, 1, (70, 70, 80))
    cx, cy = p.pt(i + 0.375, 0, z - 6)
    cx, cy = int(cx), int(cy)
    # hands drawn in screen space (clock face is nearly square at this size)
    am = (minute / 60) * 2 * math.pi
    ah = ((hour % 12) / 12 + minute / 720) * 2 * math.pi
    for ang, ln, col in ((ah, 2.6, (40, 40, 48)), (am, 4.2, (190, 60, 50))):
        for t in range(1, int(ln) + 1):
            p.px(cx + round(math.sin(ang) * t), cy - round(math.cos(ang) * t * 0.95), col)
    p.px(cx, cy, (40, 40, 48))


def coffee_bar(p: Pen) -> dict:
    wood, counter = (112, 74, 48), (226, 218, 204)
    p.box(0.15, 4.6, 0, 1.2, 4.2, 15, wood, top=counter)
    with p.face_j(1.35, 4.6, 15) as f:
        u = 0.1
        while u < 4.0:
            f.rect(u, 2, 0.95, 11, sh(wood, 0.9))
            f.rect(u + 0.08, 3, 0.79, 9, sh(wood, 1.05))
            f.rect(u + 0.8, 6, 0.06, 2, (220, 200, 160))
            u += 1.0
    p.box(0.1, 4.55, 15, 1.35, 4.3, 2, (196, 188, 172), top=counter)
    # espresso machine
    p.box(0.3, 4.9, 17, 0.85, 1.0, 13, (176, 180, 190), top=(206, 210, 218))
    with p.face_j(1.15, 4.9, 30) as f:
        f.rect(0.1, 1, 0.8, 3, (200, 60, 52))
        for u in (0.2, 0.6):
            f.rect(u, 5, 0.2, 2, (60, 62, 70))
            f.rect(u + 0.05, 7, 0.1, 2, (90, 92, 100))
        f.rect(0.1, 11, 0.8, 1, (60, 62, 70))
    for k in range(3):
        mug(p, 0.5 + k * 0.18, 5.05 + k * 0.05, 30)
    # grinder + jar
    p.box(0.4, 6.25, 17, 0.45, 0.45, 8, (60, 54, 50), top=(80, 72, 66))
    p.box(0.42, 6.27, 25, 0.4, 0.4, 5, (140, 92, 60), top=(170, 120, 80))
    p.box(0.45, 7.0, 17, 0.35, 0.35, 5, (220, 226, 230), top=(240, 242, 246))
    # cups and a fruit bowl
    for k in range(4):
        mug(p, 0.7, 7.5 + k * 0.18, 17, ((244, 244, 240), (220, 90, 80))[k % 2])
    x, y = p.ipt(0.75, 8.35, 17)
    p.rect(x - 4, y - 2, 8, 2, (210, 190, 150))
    for dx, col in ((-3, (230, 80, 60)), (0, (240, 200, 60)), (2, (100, 180, 80))):
        p.rect(x + dx, y - 4, 2, 2, col)
    return {"steam": p.ipt(0.72, 5.4, 30)}


def fridge(p: Pen, i, j) -> None:
    p.box(i, j, 0, 0.95, 0.75, 44, (226, 230, 236), top=(240, 244, 248))
    with p.face_j(i + 0.95, j, 44) as f:
        f.rect(0, 16, 0.75, 1, (180, 186, 194))
        f.rect(0.1, 6, 0.06, 6, (150, 156, 164))
        f.rect(0.1, 20, 0.06, 8, (150, 156, 164))
        f.rect(0.3, 4, 0.25, 4, (240, 200, 80))         # magnet notes
        f.rect(0.45, 24, 0.2, 3, (120, 180, 230))


def stool(p: Pen, x, y) -> None:
    x, y = int(x), int(y)
    p.rect(x - 4, y - 1, 8, 1, (60, 52, 48))
    p.rect(x - 1, y - 12, 2, 11, (90, 92, 100))
    p.rect(x - 3, y - 5, 6, 1, (90, 92, 100))
    p.rect(x - 5, y - 15, 10, 3, (150, 96, 60))
    p.rect(x - 5, y - 15, 10, 1, (190, 130, 86))


def cooler(p: Pen, i, j) -> None:
    p.box(i, j, 0, 0.5, 0.5, 20, (226, 230, 236), top=(240, 244, 248))
    with p.face_j(i + 0.5, j, 20) as f:
        f.rect(0.15, 6, 0.1, 2, (70, 140, 220))
        f.rect(0.3, 6, 0.1, 2, (220, 70, 60))
    p.box(i + 0.06, j + 0.06, 20, 0.38, 0.38, 13, (130, 190, 240), top=(170, 214, 248))
    p.box(i + 0.06, j + 0.06, 20, 0.12, 0.38, 13, (190, 226, 250), hi=False)


def armchair(p: Pen, i, j, col=(198, 100, 60)) -> None:
    p.box(i, j, 0, 1.1, 1.1, 8, col, top=sh(col, 1.12))
    p.box(i, j, 8, 0.3, 1.1, 11, sh(col, 0.92), top=sh(col, 1.1))
    p.box(i, j, 8, 1.1, 0.25, 6, sh(col, 0.92), top=sh(col, 1.1))
    p.box(i, j + 0.85, 8, 1.1, 0.25, 6, sh(col, 0.92), top=sh(col, 1.1))
    p.box(i + 0.4, j + 0.3, 8, 0.6, 0.5, 2, sh(col, 1.05), hi=False)


def side_table(p: Pen, i, j) -> None:
    p.box(i + 0.25, j + 0.2, 0, 0.1, 0.1, 9, (80, 56, 40), hi=False)
    p.box(i, j, 9, 0.6, 0.5, 2, (150, 104, 66), top=(186, 136, 90))
    p.box(i + 0.08, j + 0.06, 11, 0.32, 0.24, 2, (70, 112, 176), top=(90, 134, 196), hi=False)
    mug(p, i + 0.45, j + 0.35, 11)


def floor_lamp(p: Pen, i, j) -> None:
    x, y = p.ipt(i, j)
    p.rect(x - 3, y - 1, 6, 1, (50, 48, 50))
    p.rect(x, y - 30, 1, 29, (70, 66, 64))
    p.rect(x - 4, y - 38, 9, 8, (240, 214, 160))
    p.rect(x - 4, y - 38, 9, 1, (255, 236, 190))


def lounge_rug(p: Pen, i, j, w, d) -> None:
    with p.floor(0) as f:
        f.rect(i, j, w, d, (70, 104, 112))
        f.rect(i + 0.15, j + 0.15, w - 0.3, d - 0.3, (92, 128, 136))
        f.rect(i + 0.35, j + 0.35, w - 0.7, d - 0.7, (70, 104, 112))
        f.rect(i + 0.5, j + 0.5, w - 1.0, d - 1.0, (196, 160, 96))
        f.rect(i + 0.6, j + 0.6, w - 1.2, d - 1.2, (92, 128, 136))


def copier(p: Pen, i, j) -> None:
    p.box(i, j, 0, 1.0, 0.8, 16, (214, 216, 220), top=(236, 238, 242))
    p.box(i + 0.05, j + 0.05, 16, 0.9, 0.7, 4, (190, 194, 200), top=(170, 176, 186))
    with p.face_i(i, j + 0.8, 16) as f:
        f.rect(0.1, 3, 0.8, 2, (150, 154, 160))
        f.rect(0.1, 8, 0.8, 2, (150, 154, 160))
        f.rect(0.75, 13, 0.1, 1, (90, 220, 120))
    p.box(i + 0.25, j + 0.1, 20, 0.45, 0.3, 1, (250, 250, 248), hi=False)


def filing_cabinet(p: Pen, i, j, n=2) -> None:
    for k in range(n):
        ii = i + k * 0.62
        p.box(ii, j, 0, 0.6, 0.6, 22, (120, 130, 142), top=(150, 160, 172))
        with p.face_i(ii, j + 0.6, 22) as f:
            for v in (2, 9, 16):
                f.rect(0.06, v, 0.48, 5, (106, 116, 128))
                f.rect(0.22, v + 2, 0.16, 1, (210, 214, 220))
    mini_plant(p, i + 0.3, j + 0.3, 22)


def beanbag(p: Pen, i, j, col) -> None:
    x, y = p.ipt(i, j)
    p.rect(x - 8, y - 6, 16, 6, sh(col, 0.85))
    p.rect(x - 7, y - 9, 14, 4, col)
    p.rect(x - 5, y - 11, 10, 3, sh(col, 1.1))
    p.rect(x - 4, y - 11, 4, 1, sh(col, 1.3))


def low_table(p: Pen, i, j) -> None:
    p.box(i, j, 0, 1.0, 0.7, 6, (150, 104, 66), top=(186, 136, 90))
    papers(p, i + 0.2, j + 0.2, 6)
    mug(p, i + 0.75, j + 0.45, 6)


def round_rug(p: Pen, i, j, w, d) -> None:
    with p.floor(0) as f:
        f.rect(i + 0.3, j, w - 0.6, d, (176, 120, 80))
        f.rect(i, j + 0.3, w, d - 0.6, (176, 120, 80))
        f.rect(i + 0.45, j + 0.25, w - 0.9, d - 0.5, (210, 160, 96))
        f.rect(i + 0.25, j + 0.45, w - 0.5, d - 0.9, (210, 160, 96))
        f.rect(i + 0.7, j + 0.6, w - 1.4, d - 1.2, (176, 120, 80))


def tape(p: Pen, i, j, w, d) -> None:
    with p.floor(0) as f:
        u = 0.0
        while u < w:
            f.rect(i + u, j, min(0.3, w - u), PX_J, (240, 204, 60))
            f.rect(i + u, j + d, min(0.3, w - u), PX_J, (240, 204, 60))
            u += 0.5
        v = 0.0
        while v < d:
            f.rect(i, j + v, 1 / 16, min(0.3, d - v), (240, 204, 60))
            f.rect(i + w, j + v, 1 / 16, min(0.3, d - v), (240, 204, 60))
            v += 0.5


# --------------------------------------------------------------- dynamic
def screen(p: Pen, kind, i, j, z, state: str, frame: int, seed: int) -> None:
    """Screen content on a +j facing monitor whose screen plane starts at
    (i, j, z). state: code | idle | wait."""
    if kind == "crt":
        u0, u1, v0, v1 = 0.09, 0.66, 2, 9
    elif kind == "flat":
        u0, u1, v0, v1 = 0.05, 0.8, 1, 9
    else:
        u0, u1, v0, v1 = 0.05, 0.65, 1, 6
    rng = random.Random(seed * 13 + frame)
    with p.face_i(i, j, z) as f:
        if state == "code":
            f.rect(u0, v0, u1 - u0, v1 - v0, (16, 40, 32))
            for n, v in enumerate(range(v0 + 1, v1, 2)):
                ind = (rng.randint(0, 2)) * 0.08
                ln = 0.1 + rng.random() * (u1 - u0 - 0.2 - ind)
                col = ((110, 240, 150), (120, 200, 255), (250, 210, 110))[(n + frame) % 3]
                f.rect(u0 + 0.04 + ind, v, ln, 1, col)
        elif state == "wait":
            f.rect(u0, v0, u1 - u0, v1 - v0, (40, 36, 20))
            if frame % 2 == 0:
                f.rect(u0 + 0.05, v1 - 2, 0.1, 1, (250, 210, 90))
        else:
            f.rect(u0, v0, u1 - u0, v1 - v0, (24, 36, 60))
            k = frame % 4
            f.rect(u0 + 0.08 + k * (u1 - u0 - 0.2) / 4, v0 + 1 + (k % 2) * 2, 0.1, 1, (120, 170, 240))


def lamp(p: Pen, i, j, rgb, glow: float, night: bool) -> None:
    x, y = p.ipt(i, j, DESK_H)
    if glow > 0:
        a = glow * (1.6 if night else 1.0)
        p.rect(x - 6, y - 2, 13, 5, rgb, 0.12 * a)
        p.rect(x - 4, y - 1, 9, 3, rgb, 0.18 * a)
    p.rect(x - 2, y - 1, 5, 2, (60, 60, 68))
    p.rect(x, y - 10, 1, 9, (70, 70, 78))
    p.rect(x, y - 11, 4, 1, (70, 70, 78))
    p.rect(x + 1, y - 14, 6, 4, rgb)
    p.rect(x + 1, y - 14, 6, 1, sh(rgb, 1.3))
    p.rect(x + 2, y - 10, 4, 1, sh(rgb, 1.5) if glow > 0 else sh(rgb, 0.7))


def steam(p: Pen, x, y, frame: int) -> None:
    for k in range(3):
        ph = (frame + k * 2) % 6
        a = 0.5 - ph * 0.07
        if a <= 0:
            continue
        p.px(x + ((ph + k) % 3) - 1, y - 2 - ph * 2, (250, 250, 250), a)
        p.px(x + ((ph + k + 1) % 3) - 1, y - 3 - ph * 2, (250, 250, 250), a * 0.7)
