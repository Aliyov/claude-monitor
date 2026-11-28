"""Office scene: layout, one-time static rendering and per-frame assembly.

Building (only when the department's layout changes):
  * the floor, walls and decals are painted straight into a background;
  * every piece of furniture is drawn on its own, cropped into a sprite,
    outlined, and painted onto the background in depth order;
  * glass partitions are kept out of the background ("overlays") because
    they are translucent and must be drawn over whoever walks behind them.

Each frame (about 12 per second while visible) produces a short list of
draws: people, bubbles, lamps, screens, server LEDs, steam, the clock and the
glass, plus any static sprite that is in front of one of those and overlaps
it (so a desk correctly hides the person sitting behind it). The canvas
uploads each sprite once as a texture and only composites; nothing is
re-rendered per frame.

Depth = i + j of an object's footprint centre (painter's order), with a few
explicit values for the glass rooms.
"""
from __future__ import annotations

import hashlib
import itertools
import math
import random
import time
from dataclasses import dataclass, field

import cairo

from . import art, look
from .actors import Director, Nav, Seat, Spot
from .iso import HW, HH, Pen, crop, new_surface, outline
from .model import GREY, OFF, RED, YELLOW, DepartmentView, Person

GI = 17
ROOM_D = 4.0
CORR_J = 5.4
LEFT_I = 2.9
CLUSTER_I = (4.0, 7.3, 10.6, 13.9)
ROW_J0, ROW_STEP = 7.0, 4.2
M = 6
SLAB = 8
LEAD_SEAT = (2.6, 0.85)
PRIV_SEAT = (14.6, 0.85)

LAMP_RGB = {RED: (240, 70, 58), YELLOW: (248, 196, 50), "green": (90, 210, 110), GREY: (168, 168, 172)}
_uid = itertools.count(1)


def phase_for(hour: int) -> str:
    if 8 <= hour < 17:
        return "day"
    if 6 <= hour < 8 or 17 <= hour < 20:
        return "dusk"
    return "night"


def grid(view: DepartmentView):
    """(desk clusters, contractor clusters, rows, depth in tiles)."""
    desks = view.by_seat("desk")
    temps = view.by_seat("temp")
    n_desk = max(2, math.ceil(len(desks) / 2))
    n_temp = math.ceil(len(temps) / 2)
    rows = math.ceil((n_desk + n_temp) / len(CLUSTER_I))
    gj = max(14, int(math.ceil(ROW_J0 + rows * ROW_STEP)))
    return n_desk, n_temp, rows, gj


def layout_key(view: DepartmentView, phase: str) -> tuple:
    return (view.lit, view.slot, phase, view.project,
            tuple((p.key, p.seat, p.light == OFF) for p in view.people))


@dataclass
class Static:
    sid: str
    surf: cairo.ImageSurface
    x: int
    y: int
    w: int
    h: int
    depth: float


@dataclass
class Draw:
    depth: float
    sid: str
    surf: cairo.ImageSurface
    x: int
    y: int


@dataclass
class Tag:
    person: Person
    x: float
    y: float


@dataclass
class Frame:
    draws: list = field(default_factory=list)
    tags: list = field(default_factory=list)


class Scene:
    def __init__(self, view: DepartmentView, phase: str) -> None:
        self.uid = next(_uid)
        self.view = view
        self.phase = phase
        self.key = layout_key(view, phase)
        self.n_desk, self.n_temp, self.rows, self.gj = grid(view)
        gj = self.gj
        wt = math.ceil(art.WALL_T * HW)
        self.ox = M + gj * HW + wt
        self.oy = M + art.WALL_H + 2 * math.ceil(art.WALL_T * HH) + 2
        self.width = self.ox + GI * HW + wt + M
        self.height = self.oy + (GI + gj) * HH + SLAB + M
        self.extra_spots: list = []
        self.statics: list[Static] = []
        self.overlays: list[Static] = []
        self.bank: dict = {}
        self.seed = int(hashlib.md5((view.project or str(view.slot)).encode()).hexdigest()[:8], 16)
        self._overlap_cache: dict = {}
        self.seats: dict[str, Seat] = {}
        self.lamps: dict[str, tuple] = {}       # person key -> (i, j, depth)
        self.screens: dict[str, tuple] = {}     # person key -> (cluster slot, depth)
        self._geo: dict = {}
        self._scratch, scr_cr = new_surface(self.width, self.height)
        self.pen = Pen(scr_cr, self.ox, self.oy)
        t0 = time.perf_counter()
        self._build()
        self.build_ms = (time.perf_counter() - t0) * 1000
        self.director = Director(self.seats, self.spots, self.nav, self.seed) if view.lit else None

    # ------------------------------------------------------------ build
    def _render(self, fn, do_outline=True):
        """Draw fn(pen) into the scratch surface; return (surface, x, y)."""
        pen, cr = self.pen, self.pen.cr
        pen.begin()
        fn(pen)
        bb = pen.bb
        if bb is None:
            return None
        surf, x, y = crop(self._scratch, bb)
        cr.save()
        cr.set_operator(cairo.OPERATOR_CLEAR)
        cr.rectangle(math.floor(bb[0]) - 1, math.floor(bb[1]) - 1, math.ceil(bb[2] - bb[0]) + 3,
                     math.ceil(bb[3] - bb[1]) + 3)
        cr.fill()
        cr.restore()
        if do_outline:
            surf = outline(surf)
            x, y = x - 1, y - 1
        return surf, x, y

    def _build(self) -> None:
        view, gj = self.view, self.gj
        bg, bcr = new_surface(self.width, self.height)
        bp = Pen(bcr, self.ox, self.oy)

        # --- architecture and floor decals straight into the background
        art.slab(bp, GI, gj, SLAB)
        art.floor(bp, GI, gj, random.Random(self.seed))
        art.room_floor(bp, 0.0, 5.0, ROOM_D, (150, 62, 58), (214, 170, 90))
        art.room_floor(bp, GI - 5.0, GI, ROOM_D, (64, 92, 138), (200, 200, 210))
        art.left_wall(bp, gj, random.Random(self.seed + 1), self.phase)
        art.right_wall(bp, GI, random.Random(self.seed + 2))
        art.window_light(bp, gj, self.phase)
        j0 = gj - 3.6
        art.lounge_rug(bp, 0.8, j0 + 0.1, 2.0, 3.2)

        items: list[tuple] = []   # (depth, fn, overlay)

        def add(depth, fn, overlay=False, shadow=None):
            items.append((depth, fn, overlay))
            if shadow:
                bp.shadow(*shadow)

        # --- back rooms
        add(1.0, lambda p: art.wall_shelf(p, 0.3, books_seed=self.seed), shadow=(0.3, 0.05, 1.8, 0.5))
        add(3.9, lambda p: art.plant(p, 0.7, 3.3, 1.0))
        add(4.4, lambda p: art.exec_desk(p, 1.5, 1.4), shadow=(1.5, 1.4, 2.2, 1.0))
        x, y = bp.pt(*LEAD_SEAT)
        add(LEAD_SEAT[0] + LEAD_SEAT[1] - 0.15, lambda p, x=x, y=y: art.exec_chair(p, x, y))
        add(6.5, lambda p: art.glass_front(p, 0.0, 5.0, ROOM_D, (3.45, 4.55)), overlay=True)
        add(5.5, lambda p: art.glass_side(p, 5.0, 0.0, ROOM_D), overlay=True)

        add(14.0, lambda p: art.wall_shelf(p, GI - 4.7, books_seed=self.seed + 9),
            shadow=(GI - 4.7, 0.05, 1.8, 0.5))
        add(17.0, lambda p: art.plant(p, GI - 0.6, 3.3, 0.9, pot=(90, 110, 140)))
        add(16.4, lambda p: art.exec_desk(p, GI - 3.5, 1.4), shadow=(GI - 3.5, 1.4, 2.2, 1.0))
        x, y = bp.pt(*PRIV_SEAT)
        add(PRIV_SEAT[0] + PRIV_SEAT[1] - 0.15, lambda p, x=x, y=y: art.exec_chair(p, x, y))
        add(13.6, lambda p: art.glass_side(p, GI - 5.0, 0.0, ROOM_D), overlay=True)
        add(18.5, lambda p: art.glass_front(p, GI - 5.0, GI, ROOM_D, (GI - 4.55, GI - 3.45)), overlay=True)

        # --- servers, cooler, whiteboard corner
        for ri in (5.5, 6.6):
            add(ri + 1.1, lambda p, ri=ri: art.server_rack(p, ri, 0.1), shadow=(ri, 0.1, 1.0, 1.0))
        self.racks = [(5.5, 0.1, 62, 6.61), (6.6, 0.1, 62, 7.71)]
        add(8.5, lambda p: art.plant(p, 8.0, 0.5, 0.8))
        add(12.1, lambda p: art.cooler(p, 11.35, 0.25), shadow=(11.35, 0.25, 0.5, 0.5))

        # --- coffee bar + lounge (left side)
        geo: dict = {}
        add(7.45, lambda p: geo.update(art.coffee_bar(p)), shadow=(0.15, 4.6, 1.3, 4.2))
        add(9.8, lambda p: art.fridge(p, 0.15, 8.95), shadow=(0.15, 8.95, 0.95, 0.75))
        for sj in (5.3, 6.8, 8.3):
            x, y = bp.pt(2.15, sj)
            add(2.15 + sj, lambda p, x=x, y=y: art.stool(p, x, y))
        bj0 = max(j0, 13.6)
        if gj - 0.2 - bj0 >= 1.2:
            add(0.4 + (bj0 + gj) / 2, lambda p: art.tall_bookcase(p, 0.12, bj0, gj - 0.2 - bj0, seed=self.seed),
                shadow=(0.12, bj0, 0.6, gj - 0.2 - bj0))
        add(1.85 + j0 + 1.0, lambda p: art.armchair(p, 1.3, j0 + 0.45), shadow=(1.3, j0 + 0.45, 1.1, 1.1))
        add(1.7 + j0 + 2.0, lambda p: art.side_table(p, 1.4, j0 + 1.75))
        add(0.95 + j0 + 3.0, lambda p: art.floor_lamp(p, 0.9, j0 + 3.0))

        # --- desk clusters
        desks = view.by_seat("desk")
        temps = view.by_seat("temp")
        aisles = [CORR_J]
        for slot in range(self.n_desk + self.n_temp):
            r, k = divmod(slot, len(CLUSTER_I))
            ci, cj = CLUSTER_I[k], ROW_J0 + r * ROW_STEP
            if slot < self.n_desk:
                pair, temp = desks[2 * slot:2 * slot + 2], False
            else:
                t = slot - self.n_desk
                pair, temp = temps[2 * t:2 * t + 2], True
                art.tape(bp, ci - 0.45, cj - 1.4, 2.9, 3.6)
            cdepth = ci + 1 + cj + 1.0
            seed = self.seed + slot * 101

            def draw_cluster(p, ci=ci, cj=cj, seed=seed, temp=temp, slot=slot):
                self._geo[slot] = art.cluster(p, ci, cj, seed, temp)
            add(cdepth, draw_cluster, shadow=(ci, cj, 2.0, 2.0))
            far_aisle = CORR_J if r == 0 else cj - 1.1
            near_aisle = cj + 3.1
            if near_aisle not in aisles:
                aisles.append(near_aisle)
            for idx, si, sj, facing, aisle in ((0, ci + 1.0, cj - 0.55, "front", far_aisle),
                                               (1, ci + 1.0, cj + 2.55, "back", near_aisle)):
                person = pair[idx] if idx < len(pair) else None
                if not temp:
                    sdepth = si + sj + (-0.05 if facing == "front" else 0.35)
                    cx, cy = bp.pt(si, sj + (0 if facing == "front" else 0.35))
                    seat_col = random.Random(seed + idx).choice(((88, 96, 132), (60, 64, 76), (150, 70, 60),
                                                                (70, 120, 110)))
                    add(sdepth, lambda p, cx=cx, cy=cy, f=facing, c=seat_col: art.office_chair(p, cx, cy, f, c))
                if person is None or person.light == OFF:
                    continue
                self.seats[person.key] = Seat(
                    person.key, si, sj, facing, [(si, aisle)],
                    chat_point=None if temp else (si + 0.6, aisle),
                    chat_face="+j" if facing == "front" else "-j")
                lamp_ij = (ci + 1.8, cj + 0.62) if facing == "front" else (ci + 0.2, cj + 1.72)
                self.lamps[person.key] = (lamp_ij[0], lamp_ij[1], cdepth + 0.01)
                if facing == "back":
                    self.screens[person.key] = (slot, cdepth + 0.02)

        # front corner furniture when the last row leaves room
        free_j = ROW_J0 + self.rows * ROW_STEP - 0.6
        if gj - free_j >= 2.4:
            fj = gj - 1.4
            add(5.0 + fj + 0.4, lambda p, fj=fj: art.copier(p, 4.6, fj), shadow=(4.6, fj, 1.0, 0.8))
            add(6.3 + fj + 0.3, lambda p, fj=fj: art.filing_cabinet(p, 5.9, fj + 0.2), shadow=(5.9, fj + 0.2, 1.24, 0.6))
            art.round_rug(bp, 10.2, fj - 0.9, 3.6, 2.2)
            add(11.4 + fj, lambda p, fj=fj: art.low_table(p, 11.2, fj - 0.35), shadow=(11.2, fj - 0.35, 1.0, 0.7))
            for bi, bj, col in ((10.6, fj - 0.3, (220, 120, 70)), (12.7, fj + 0.4, (90, 140, 200)),
                                (11.6, fj + 0.85, (120, 180, 110))):
                add(bi + bj, lambda p, bi=bi, bj=bj, c=col: art.beanbag(p, bi, bj, c))
            self.extra_spots = [Spot("lounge", 11.0, fj + 0.5, "+i", (11.0, ROW_J0 + (self.rows - 1) * ROW_STEP + 3.1))]
        for pi, pj, s in ((GI - 0.55, CORR_J + 0.9, 1.0), (GI - 0.6, gj - 0.6, 1.1), (3.5, gj - 0.45, 0.9)):
            add(pi + pj, lambda p, pi=pi, pj=pj, s=s: art.plant(p, pi, pj, s))

        # --- rooms: seats for lead / private
        lead = view.by_seat("office")
        if lead and lead[0].light != OFF:
            self.seats[lead[0].key] = Seat(lead[0].key, *LEAD_SEAT, "front",
                                           [(4.0, LEAD_SEAT[1]), (4.0, CORR_J)])
            self.lamps[lead[0].key] = (3.45, 1.6, 4.41)
        priv = view.by_seat("private")
        if priv and priv[0].light != OFF:
            self.seats[priv[0].key] = Seat(priv[0].key, *PRIV_SEAT, "front",
                                           [(GI - 4.0, PRIV_SEAT[1]), (GI - 4.0, CORR_J)])
            self.lamps[priv[0].key] = (GI - 1.65, 1.6, 16.41)

        self.nav = Nav(LEFT_I, aisles)
        self.spots = [Spot("coffee", 2.45, 6.05, "-i", (LEFT_I, 6.05)),
                      Spot("coffee", 2.45, 7.55, "-i", (LEFT_I, 7.55)),
                      Spot("cooler", 11.6, 1.45, "-j", (11.6, CORR_J)),
                      Spot("whiteboard", 9.3, 1.5, "-j", (9.3, CORR_J)),
                      Spot("whiteboard", 10.4, 1.7, "-j", (10.4, CORR_J)),
                      Spot("lounge", 2.2, gj - 0.65, "-i", (LEFT_I, gj - 0.65))] + self.extra_spots

        # --- render items in depth order
        for n, (depth, fn, overlay) in enumerate(sorted(items, key=lambda t: t[0])):
            res = self._render(fn)
            if res is None:
                continue
            surf, x, y = res
            st = Static(f"s{self.uid}:{n}", surf, x, y, surf.get_width(), surf.get_height(), depth)
            if overlay and view.lit:
                self.overlays.append(st)
            else:
                bcr.set_source_surface(surf, x, y)
                bcr.paint()
                self.statics.append(st)
        self.steam_xy = geo.get("steam")
        self.screen_geo = {k: (self._geo.get(slot, {}).get("near_screen"), d)
                           for k, (slot, d) in self.screens.items()}
        if not view.lit:
            bcr.set_operator(cairo.OPERATOR_ATOP)
            bcr.set_source_rgba(14 / 255, 16 / 255, 34 / 255, 0.62)
            bcr.paint()
            bcr.set_operator(cairo.OPERATOR_OVER)
        self.background = bg

    # ------------------------------------------------------------ dynamic
    def _dyn(self, out, key, depth, fn, do_outline=False) -> None:
        hit = self.bank.get(key)
        if hit is None:
            hit = self._render(fn, do_outline) or (new_surface(1, 1)[0], 0, 0)
            if len(self.bank) > 3000:
                self.bank.clear()
            self.bank[key] = hit
        surf, x, y = hit
        out.append(Draw(depth, f"g{self.uid}:{key}", surf, x, y))

    def sync(self, view: DepartmentView, now: float) -> None:
        self.view = view
        if self.director is not None:
            self.director.sync(view.people, now)

    def frame(self, now: float, hour: int, minute: int) -> Frame:
        fr = Frame()
        if not self.view.lit or self.director is None:
            return fr
        out: list[Draw] = []
        night = self.phase == "night"
        # ambient animation
        for ri, rj, rh, d in self.racks:
            f = int(now * 2.5) % 4
            self._dyn(out, f"led:{ri}:{f}", d,
                      lambda p, ri=ri, rj=rj, rh=rh, f=f: art.server_leds(p, ri, rj, rh, f, True))
        f = int(now * 1.5) % 6
        self._dyn(out, f"wscr:{f}", 0.05, lambda p, f=f: art.wall_screen(p, f))
        self._dyn(out, f"clk:{hour}:{minute}", 0.06, lambda p: art.clock(p, 7.75, 72, hour, minute))
        if self.steam_xy:
            f = int(now * 6) % 6
            sx, sy = self.steam_xy
            self._dyn(out, f"steam:{f}", 7.46, lambda p, f=f: art.steam(p, sx, sy, f))
        for st in self.overlays:
            out.append(Draw(st.depth, st.sid, st.surf, st.x, st.y))

        frames = self.director.step(now)
        bubbles = []
        for af in frames:
            p = af.person
            seated = af.pose.startswith("sit")
            lamp = self.lamps.get(af.key)
            if lamp:
                rgb = LAMP_RGB.get(p.light, LAMP_RGB[GREY])
                glow = 0.0 if p.light == GREY else (1.0 if p.light != RED else 1.0 + (int(now * 1.5 + af.phase) % 2) * 0.5)
                li, lj, ld = lamp
                self._dyn(out, f"lamp:{li}:{lj}:{p.light}:{glow}:{night}", ld,
                          lambda pen, li=li, lj=lj, rgb=rgb, g=glow: art.lamp(pen, li, lj, rgb, g, night))
            sg = self.screen_geo.get(af.key)
            if sg and sg[0]:
                (kind, si, sj, sz), sd = sg
                if p.light == RED and seated:
                    state, f = "code", int(now * 4 + af.phase) % 4
                elif p.light == YELLOW:
                    state, f = "wait", int(now * 2) % 2
                else:
                    state, f = "idle", int(now * 0.8 + af.phase) % 4
                self._dyn(out, f"scr:{si}:{sj}:{state}:{f}", sd,
                          lambda pen, k=kind, si=si, sj=sj, sz=sz, s=state, f=f:
                          art.screen(pen, k, si, sj, sz, s, f, int(si * 10 + sj)))
            L = look.look_for(p.name, p.key, p.role)
            sid, surf = look.sprite(L, af.pose, af.frame, af.flip)
            x, y = self.pen.ipt(af.i, af.j)
            out.append(Draw(af.i + af.j, sid, surf, x - (look.AX + 1), y - (look.AY + 1)))
            head = y + look.head_top(af.pose, af.frame)
            tag_y = head
            if af.bubble:
                bsid, bs = look.bubble(*af.bubble)
                bob = int(now * 2 + af.phase) % 2
                by = head - bs.get_height() + 3 - bob
                bubbles.append(Draw(1e6, bsid, bs, x + 3, by))
                tag_y = min(tag_y, by + 2)
            fr.tags.append(Tag(p, x, tag_y - 1))

        # statics in front of something dynamic are drawn again over it
        need = {}
        for d in out:
            for st in self._in_front(d):
                need[st.sid] = st
        out.extend(Draw(st.depth, st.sid, st.surf, st.x, st.y) for st in need.values())
        out.sort(key=lambda d: d.depth)
        out.extend(bubbles)
        fr.draws = out
        return fr

    def _in_front(self, d: Draw) -> list:
        w, h = d.surf.get_width(), d.surf.get_height()
        key = (d.x, d.y, w, h, round(d.depth, 3))
        hit = self._overlap_cache.get(key)
        if hit is None:
            hit = [st for st in self.statics
                   if st.depth > d.depth and st.x < d.x + w and d.x < st.x + st.w
                   and st.y < d.y + h and d.y < st.y + st.h]
            if len(self._overlap_cache) > 4000:
                self._overlap_cache.clear()
            self._overlap_cache[key] = hit
        return hit
