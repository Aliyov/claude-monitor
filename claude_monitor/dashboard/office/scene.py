"""Pixel-art office scene: layout + drawing of one department at low
resolution (1 unit = 1 art pixel). The canvas scales the result up with
nearest-neighbour filtering, so everything here is drawn with integer
rectangles and no antialiasing. All art is original and procedural.

Layout of a department (top to bottom):
  wall with windows
  [ lead office ] [ private room ] [ kitchenette ]
  corridor
  open floor: rows of desks (DESK_COLS per row) | temp desks for contractors
"""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass

import cairo

from .model import GREEN, GREY, OFF, RED, YELLOW, DepartmentView, Person

M = 8                 # outer margin
WALL_H = 14
ROOM_W, ROOM_H = 76, 58
KITCHEN_W = 52
GAP = 6
CORRIDOR_H = 14
DESK_W, DESK_H = 36, 34
DESK_COLS = 4
TEMP_W = 36

# palette (RGB 0..255)
P = {
    "night": (24, 26, 38), "wall": (214, 205, 189), "wall_dark": (176, 164, 146),
    "trim": (122, 104, 88), "window": (150, 196, 226), "window_hi": (205, 229, 244),
    "frame": (96, 84, 74), "wood": (186, 140, 96), "wood_dark": (160, 116, 78),
    "carpet": (98, 116, 132), "carpet_dark": (88, 105, 120), "tile": (222, 222, 214),
    "tile_dark": (204, 204, 196), "desk": (142, 98, 64), "desk_top": (176, 128, 86),
    "desk_dark": (104, 70, 46), "temp_desk": (170, 172, 176), "temp_top": (200, 202, 206),
    "temp_leg": (120, 122, 128), "chair": (54, 58, 70), "chair_hi": (76, 82, 98),
    "laptop": (58, 62, 70), "laptop_hi": (92, 98, 108), "screen_glow": (120, 190, 255),
    "plant_pot": (176, 92, 60), "leaf": (72, 148, 86), "leaf_dark": (52, 116, 66),
    "counter": (232, 230, 226), "counter_dark": (190, 188, 184), "machine": (66, 66, 72),
    "mug": (240, 240, 236), "rug": (166, 74, 64), "rug_hi": (190, 98, 84), "shadow": (0, 0, 0),
    "shelf": (130, 92, 62), "book1": (184, 72, 64), "book2": (70, 120, 180), "book3": (210, 170, 70),
    "outline": (40, 34, 32), "skin_shadow": (0, 0, 0),
}
LIGHT_RGB = {RED: (232, 70, 62), YELLOW: (240, 190, 50), GREEN: (78, 196, 100),
             GREY: (150, 150, 150), OFF: (60, 60, 66)}
SHIRTS = [(210, 120, 80), (86, 132, 196), (108, 168, 112), (176, 98, 160), (214, 176, 72),
          (92, 170, 176), (196, 86, 96), (128, 112, 196), (230, 140, 60), (120, 140, 150)]
SKINS = [(246, 214, 182), (232, 190, 150), (204, 154, 112), (168, 116, 80), (120, 82, 58)]
HAIRS = [(48, 36, 30), (92, 60, 36), (176, 132, 76), (30, 30, 34), (150, 70, 40), (200, 190, 170)]
LEAD_SHIRT = (204, 110, 74)
FILLER_SHIRT = (150, 150, 154)


@dataclass
class Anchor:
    """Where a person is in art pixels (head top centre) for labels/hit tests."""
    person: Person
    x: int
    y: int
    box: tuple[int, int, int, int]   # x, y, w, h of the clickable sprite area


@dataclass
class Rendered:
    surface: cairo.ImageSurface
    width: int
    height: int
    anchors: list[Anchor]
    title_xy: tuple[int, int]


def _h(s: str) -> int:
    return int(hashlib.md5(s.encode()).hexdigest()[:8], 16)


class Pen:
    def __init__(self, cr: cairo.Context) -> None:
        self.cr = cr

    def rect(self, x, y, w, h, rgb, a=1.0) -> None:
        cr = self.cr
        cr.set_source_rgba(rgb[0] / 255, rgb[1] / 255, rgb[2] / 255, a)
        cr.rectangle(int(x), int(y), int(w), int(h))
        cr.fill()

    def px(self, x, y, rgb, a=1.0) -> None:
        self.rect(x, y, 1, 1, rgb, a)


def layout_size(view: DepartmentView) -> tuple[int, int, dict]:
    desks = view.by_seat("desk")
    temps = view.by_seat("temp")
    rows = max(1, math.ceil(len(desks) / DESK_COLS))
    temp_rows = rows
    temp_cols = math.ceil(len(temps) / temp_rows) if temps else 0
    if temps and temp_cols > 2:            # keep the temp area compact: grow rows instead
        temp_cols = 2
        temp_rows = math.ceil(len(temps) / 2)
    rows_total = max(rows, temp_rows if temps else 0)
    floor_w = DESK_COLS * DESK_W + (GAP * 2 + temp_cols * TEMP_W if temps else 0)
    rooms_w = ROOM_W * 2 + KITCHEN_W + GAP * 2
    inner_w = max(rooms_w, floor_w)
    w = M * 2 + inner_w
    floor_y = M + WALL_H + ROOM_H + CORRIDOR_H
    h = floor_y + rows_total * DESK_H + M + 4
    return w, h, {"rows": rows_total, "temp_cols": temp_cols, "temp_rows": temp_rows,
                  "inner_w": inner_w, "floor_y": floor_y}


def render(view: DepartmentView) -> Rendered:
    w, h, L = layout_size(view)
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
    cr = cairo.Context(surf)
    cr.set_antialias(cairo.ANTIALIAS_NONE)
    pen = Pen(cr)
    anchors: list[Anchor] = []

    _building(pen, w, h, L)
    top = M + WALL_H
    x0 = M
    # rooms
    office = (x0, top, ROOM_W, ROOM_H)
    private = (x0 + ROOM_W + GAP, top, ROOM_W, ROOM_H)
    kitchen = (x0 + 2 * (ROOM_W + GAP), top, KITCHEN_W, ROOM_H)
    _room(pen, *office, floor="wood")
    _room(pen, *private, floor="wood")
    _room(pen, *kitchen, floor="tile")
    _kitchen(pen, *kitchen)
    _office_decor(pen, *office, rug=True)
    _office_decor(pen, *private, rug=False)

    lead = view.by_seat("office")
    if lead:
        anchors.append(_seat_big(pen, lead[0], office))
    priv = view.by_seat("private")
    if priv:
        anchors.append(_seat_big(pen, priv[0], private))
    else:
        _empty_big_desk(pen, private)

    # open floor
    fy = L["floor_y"]
    desks = view.by_seat("desk")
    for i, p in enumerate(desks):
        r, c = divmod(i, DESK_COLS)
        anchors.append(_seat_desk(pen, p, x0 + c * DESK_W, fy + r * DESK_H, temp=False))
    # empty desks to complete the last row looks tidy
    for i in range(len(desks), L["rows"] * DESK_COLS if desks else 0):
        r, c = divmod(i, DESK_COLS)
        _desk(pen, x0 + c * DESK_W, fy + r * DESK_H, temp=False, light=None)
    temps = view.by_seat("temp")
    if temps:
        tx = x0 + DESK_COLS * DESK_W + GAP * 2
        _temp_zone(pen, tx - GAP, fy - 4, L["temp_cols"] * TEMP_W + GAP, L["temp_rows"] * DESK_H + 6)
        for i, p in enumerate(temps):
            c, r = divmod(i, L["temp_rows"])
            anchors.append(_seat_desk(pen, p, tx + c * TEMP_W, fy + r * DESK_H, temp=True))

    if not view.lit:
        pen.rect(0, 0, w, h, P["night"], 0.62)
    return Rendered(surf, w, h, [a for a in anchors if a is not None], (x0, M + 2))


# ---------------------------------------------------------------- building
def _building(pen: Pen, w, h, L) -> None:
    pen.rect(0, 0, w, h, P["outline"])
    pen.rect(2, 2, w - 4, h - 4, P["carpet"])
    # carpet texture: sparse darker pixels in a fixed pattern
    for y in range(L["floor_y"] - CORRIDOR_H, h - 2, 4):
        for x in range(2 + (y // 4) % 2 * 2, w - 2, 4):
            pen.px(x, y, P["carpet_dark"])
    # top wall with windows
    pen.rect(2, 2, w - 4, M + WALL_H - 2, P["wall"])
    pen.rect(2, M + WALL_H - 2, w - 4, 2, P["trim"])
    for wx in range(M + 6, w - M - 20, 30):
        pen.rect(wx, 4, 20, M + WALL_H - 8, P["frame"])
        pen.rect(wx + 1, 5, 18, M + WALL_H - 10, P["window"])
        pen.rect(wx + 2, 6, 5, 2, P["window_hi"])
        pen.rect(wx + 10, 5, 1, M + WALL_H - 10, P["frame"])


def _room(pen: Pen, x, y, w, h, floor) -> None:
    if floor == "wood":
        pen.rect(x, y, w, h, P["wood"])
        for yy in range(y, y + h, 4):
            pen.rect(x, yy, w, 1, P["wood_dark"])
            off = (yy // 4 % 3) * 7
            for xx in range(x + off, x + w, 21):
                pen.rect(xx, yy, 1, 4, P["wood_dark"])
    else:
        pen.rect(x, y, w, h, P["tile"])
        for yy in range(y, y + h, 6):
            pen.rect(x, yy, w, 1, P["tile_dark"])
        for xx in range(x, x + w, 6):
            pen.rect(xx, y, 1, h, P["tile_dark"])
    # walls (left, right, bottom with a door gap)
    pen.rect(x - 2, y, 2, h + 2, P["wall_dark"])
    pen.rect(x + w, y, 2, h + 2, P["wall_dark"])
    door = 16
    dx = x + w - door - 6
    pen.rect(x - 2, y + h, dx - x + 2, 2, P["wall_dark"])
    pen.rect(dx + door, y + h, x + w + 2 - dx - door, 2, P["wall_dark"])


def _kitchen(pen: Pen, x, y, w, h) -> None:
    pen.rect(x, y, w, 10, P["counter_dark"])
    pen.rect(x, y, w, 8, P["counter"])
    # coffee machine
    pen.rect(x + 4, y - 4, 10, 12, P["machine"])
    pen.rect(x + 6, y - 2, 6, 3, (120, 200, 140))
    pen.rect(x + 7, y + 4, 4, 3, P["mug"])
    # sink
    pen.rect(x + 22, y + 2, 12, 4, (170, 176, 184))
    pen.rect(x + 27, y, 2, 3, (130, 136, 144))
    # fridge
    pen.rect(x + w - 12, y - 2, 10, 22, (226, 230, 236))
    pen.rect(x + w - 12, y + 9, 10, 1, (180, 184, 190))
    pen.rect(x + w - 4, y + 3, 1, 4, (150, 154, 160))
    # small table + plant
    pen.rect(x + 10, y + 32, 18, 10, P["desk_dark"])
    pen.rect(x + 10, y + 31, 18, 9, P["desk_top"])
    pen.rect(x + 14, y + 33, 3, 3, P["mug"])
    _plant(pen, x + w - 10, y + h - 14)


def _office_decor(pen: Pen, x, y, w, h, rug) -> None:
    # bookshelf on the back wall
    pen.rect(x + 4, y, 22, 12, P["shelf"])
    for i, c in enumerate((P["book1"], P["book2"], P["book3"], P["book2"], P["book1"])):
        pen.rect(x + 6 + i * 4, y + 2, 3, 4 + (i % 2), c)
    pen.rect(x + 4, y + 7, 22, 1, P["desk_dark"])
    _plant(pen, x + w - 10, y + 2)
    if rug:
        pen.rect(x + 14, y + 30, w - 28, 22, P["rug"])
        pen.rect(x + 16, y + 32, w - 32, 18, P["rug_hi"])
        pen.rect(x + 18, y + 34, w - 36, 14, P["rug"])


def _plant(pen: Pen, x, y) -> None:
    pen.rect(x + 1, y + 6, 6, 5, P["plant_pot"])
    pen.rect(x, y + 6, 8, 1, (150, 76, 50))
    pen.rect(x + 2, y, 4, 6, P["leaf"])
    pen.rect(x, y + 2, 3, 3, P["leaf_dark"])
    pen.rect(x + 5, y + 1, 3, 3, P["leaf_dark"])
    pen.rect(x + 3, y - 2, 2, 3, P["leaf"])


def _temp_zone(pen: Pen, x, y, w, h) -> None:
    # taped-off area on the carpet: "temporary desks"
    for xx in range(x, x + w, 4):
        pen.rect(xx, y, 2, 1, (230, 196, 70))
        pen.rect(xx, y + h - 1, 2, 1, (230, 196, 70))
    for yy in range(y, y + h, 4):
        pen.rect(x, yy, 1, 2, (230, 196, 70))
        pen.rect(x + w - 1, yy, 1, 2, (230, 196, 70))


# ------------------------------------------------------------------ people
def _looks(p: Person) -> tuple:
    seed = _h(p.name or p.key)
    if p.role == "lead":
        shirt = LEAD_SHIRT
    elif p.filler:
        shirt = FILLER_SHIRT
    else:
        shirt = SHIRTS[seed % len(SHIRTS)]
    skin = SKINS[(seed >> 4) % len(SKINS)]
    hair = HAIRS[(seed >> 8) % len(HAIRS)]
    style = (seed >> 12) % 3
    return shirt, skin, hair, style


def _person(pen: Pen, p: Person, cx, top) -> tuple[int, int, int, int]:
    """Upper body seen from the front, head top-centre at (cx, top).
    Returns the bounding box (x, y, w, h)."""
    shirt, skin, hair, style = _looks(p)
    x = cx - 4
    dim = 0.55 if p.filler else 1.0
    # shoulders / body
    pen.rect(x - 1, top + 9, 10, 7, tuple(int(c * 0.82) for c in shirt))
    pen.rect(x, top + 9, 8, 7, shirt)
    pen.rect(x + 3, top + 9, 2, 2, tuple(min(255, int(c * 1.15)) for c in shirt))
    # head
    pen.rect(x + 1, top + 2, 6, 7, skin)
    pen.rect(x + 1, top + 8, 6, 1, tuple(int(c * 0.86) for c in skin))
    # hair styles
    pen.rect(x + 1, top, 6, 3, hair)
    if style == 0:
        pen.rect(x, top + 1, 1, 4, hair)
        pen.rect(x + 7, top + 1, 1, 4, hair)
    elif style == 1:
        pen.rect(x + 1, top - 1, 4, 1, hair)
    else:
        pen.rect(x, top + 1, 1, 7, hair)
        pen.rect(x + 7, top + 1, 1, 7, hair)
    # eyes
    if not p.filler:
        pen.px(x + 2, top + 5, P["outline"])
        pen.px(x + 5, top + 5, P["outline"])
    else:
        pen.rect(x + 2, top + 5, 4, 1, tuple(int(c * 0.8) for c in skin))
    if dim < 1:
        pen.rect(x - 1, top - 1, 10, 17, (180, 180, 184), 0.35)
    return (x - 1, top - 1, 10, 17)


def _lamp(pen: Pen, x, y, light) -> None:
    rgb = LIGHT_RGB.get(light, LIGHT_RGB[OFF])
    if light in (RED, YELLOW, GREEN):
        pen.rect(x - 1, y - 1, 5, 5, rgb, 0.28)
    pen.rect(x, y, 3, 3, rgb)
    pen.px(x, y, tuple(min(255, c + 60) for c in rgb))
    pen.rect(x + 1, y + 3, 1, 2, P["outline"])


def _chair(pen: Pen, cx, y) -> None:
    pen.rect(cx - 6, y, 12, 12, P["chair"])
    pen.rect(cx - 5, y + 1, 10, 3, P["chair_hi"])


def _desk(pen: Pen, x, y, temp, light, working=False, chair=True) -> None:
    """A desk cell DESK_W x DESK_H with its origin at the top-left."""
    cx = x + DESK_W // 2
    dy = y + 18
    if chair and not temp:
        _chair(pen, cx, y + 6)
    if temp:
        pen.rect(x + 4, dy + 8, 2, 6, P["temp_leg"])
        pen.rect(x + DESK_W - 6, dy + 8, 2, 6, P["temp_leg"])
        pen.rect(x + 3, dy, DESK_W - 6, 9, P["temp_desk"])
        pen.rect(x + 3, dy, DESK_W - 6, 3, P["temp_top"])
    else:
        pen.rect(x + 2, dy + 2, DESK_W - 4, 12, P["desk_dark"])
        pen.rect(x + 2, dy, DESK_W - 4, 11, P["desk"])
        pen.rect(x + 2, dy, DESK_W - 4, 4, P["desk_top"])
    # laptop, back facing us; a soft glow on the desk top while working
    pen.rect(cx - 6, dy - 5, 12, 7, P["laptop"])
    pen.rect(cx - 6, dy - 5, 12, 1, P["laptop_hi"])
    pen.rect(cx - 1, dy - 3, 2, 2, P["laptop_hi"])
    if working:
        pen.rect(cx - 7, dy + 1, 14, 2, P["screen_glow"], 0.45)
    if light is not None:
        _lamp(pen, x + DESK_W - 9, dy - 4, light)


def _seat_desk(pen: Pen, p: Person, x, y, temp) -> Anchor | None:
    cx = x + DESK_W // 2
    head = y + 3
    if p.light == OFF:          # dark department: furniture only
        _desk(pen, x, y, temp, OFF)
        return None
    if not temp:
        _chair(pen, cx, y + 6)
    box = _person(pen, p, cx, head)
    _desk(pen, x, y, temp, p.light, working=p.working, chair=False)
    return Anchor(p, cx, head, box)


def _seat_big(pen: Pen, p: Person, room) -> Anchor | None:
    x, y, w, h = room
    if p.light == OFF:
        _empty_big_desk(pen, room)
        return None
    cx = x + w // 2
    head = y + 14
    pen.rect(cx - 7, y + 17, 14, 13, P["chair"])
    pen.rect(cx - 6, y + 18, 12, 3, P["chair_hi"])
    box = _person(pen, p, cx, head)
    dy = y + 30
    pen.rect(cx - 22, dy + 2, 44, 12, P["desk_dark"])
    pen.rect(cx - 22, dy, 44, 11, P["desk"])
    pen.rect(cx - 22, dy, 44, 4, P["desk_top"])
    pen.rect(cx - 7, dy - 6, 14, 8, P["laptop"])
    pen.rect(cx - 7, dy - 6, 14, 1, P["laptop_hi"])
    if p.working:
        pen.rect(cx - 8, dy + 1, 16, 2, P["screen_glow"], 0.45)
    pen.rect(cx + 12, dy + 1, 3, 3, P["mug"])
    _lamp(pen, cx - 18, dy - 4, p.light)
    return Anchor(p, cx, head, box)


def _empty_big_desk(pen: Pen, room) -> None:
    x, y, w, h = room
    cx = x + w // 2
    dy = y + 30
    pen.rect(cx - 7, y + 17, 14, 13, P["chair"])
    pen.rect(cx - 22, dy + 2, 44, 12, P["desk_dark"])
    pen.rect(cx - 22, dy, 44, 11, P["desk"])
    pen.rect(cx - 22, dy, 44, 4, P["desk_top"])
