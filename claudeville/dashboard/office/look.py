"""Characters and speech bubbles (original procedural pixel art).

Every person gets a stable look from a hash of their name: skin, hair style
and colour, outfit, glasses, headphones. The lead wears a suit; ambient
fillers wear neutral grey so they read as "not a real agent".

Sprites are SW x SH with the feet (or seat point) at (AX, AY), drawn facing
right / up-right and mirrored for the other direction, then outlined.

Poses and frames
  sit_front  0 idle  1 type-a  2 type-b  3 blink  4 sip
  sit_back   0 idle  1 type-a  2 type-b
  stand_front / stand_back   0 idle  1 blink  2 sip
  walk_front / walk_back     0..3 walk cycle
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

from .iso import Pen, flip_h, new_surface, outline, sh

SW, SH = 24, 46
AX, AY = 12, 43
HEAD_STAND = 10          # hair top row when standing (sprite coords)
SIT_DROP = 2             # seated upper body sits this much lower

SKINS = [(252, 222, 192), (238, 196, 156), (214, 164, 120), (176, 122, 86), (124, 84, 60), (98, 64, 46)]
HAIRS = [(44, 32, 28), (92, 58, 34), (186, 136, 76), (26, 26, 30), (160, 74, 40), (214, 204, 186),
         (58, 96, 178), (196, 92, 140)]
TOPS = [(214, 116, 74), (74, 126, 200), (92, 166, 104), (170, 92, 160), (226, 184, 66), (78, 170, 178),
        (200, 78, 92), (122, 104, 204), (240, 142, 52), (60, 88, 118), (236, 236, 228), (52, 52, 60)]
PANTS = [(52, 62, 92), (70, 70, 78), (96, 80, 62), (40, 44, 56), (110, 120, 140)]
SHOES = [(40, 36, 36), (236, 236, 232), (120, 74, 46), (196, 70, 60)]
ACCENTS = [(240, 210, 90), (240, 110, 90), (110, 200, 240), (250, 250, 250), (140, 220, 130)]

GREY_TOP, GREY_PANTS = (150, 152, 158), (110, 112, 120)


@dataclass(frozen=True)
class Look:
    key: str
    skin: tuple
    hair: tuple
    hair_style: int      # 0 short 1 long 2 bun 3 spiky 4 curly 5 bald+beard
    top: tuple
    top_style: int       # 0 tee 1 hoodie 2 suit 3 cardigan 4 sweater
    accent: tuple
    pants: tuple
    shoes: tuple
    glasses: bool
    phones: bool


def look_for(name: str | None, key: str, role: str) -> Look:
    s = int(hashlib.md5((name or key).encode()).hexdigest()[:12], 16)

    def pick(seq, shift):
        return seq[(s >> shift) % len(seq)]

    skin = pick(SKINS, 0)
    hair = pick(HAIRS, 4)
    style = (s >> 8) % 6
    top, top_style = pick(TOPS, 12), (s >> 16) % 5
    if top_style == 2:
        top_style = 4
    pants, shoes, accent = pick(PANTS, 20), pick(SHOES, 24), pick(ACCENTS, 28)
    glasses = (s >> 32) % 10 < 3
    phones = (s >> 36) % 10 < 2
    if role == "lead":
        top, top_style, pants, accent, shoes = (46, 56, 84), 2, (40, 44, 60), (232, 120, 70), (40, 36, 36)
    elif role == "filler":
        top, pants, accent, phones = GREY_TOP, GREY_PANTS, (200, 200, 204), False
        if top_style == 2:
            top_style = 0
    lk = f"{(name or key)}|{role}"
    return Look(lk, skin, hair, style, top, top_style, accent, pants, shoes, glasses, phones)


# ------------------------------------------------------------- drawing
def _head_front(p: Pen, L: Look, cx, hy, dx, blink, sip):
    skin, hair = L.skin, L.hair
    p.rect(cx - 4, hy, 8, 9, skin)
    p.rect(cx - 4, hy + 8, 8, 1, sh(skin, 0.86))
    p.rect(cx - 5, hy + 3, 1, 3, sh(skin, 0.92))
    p.rect(cx + 4, hy + 3, 1, 3, sh(skin, 0.9))
    st = L.hair_style
    if st == 0:
        p.rect(cx - 4, hy - 1, 8, 3, hair)
        p.rect(cx - 5, hy, 1, 4, hair)
        p.rect(cx + 4, hy, 1, 3, hair)
        p.rect(cx - 4 + max(dx, 0), hy + 2, 3, 1, hair)
    elif st == 1:
        p.rect(cx - 5, hy - 1, 10, 3, hair)
        p.rect(cx - 5, hy + 1, 2, 11, hair)
        p.rect(cx + 3, hy + 1, 2, 11, hair)
        p.rect(cx - 2, hy + 2, 3, 1, hair)
    elif st == 2:
        p.rect(cx - 4, hy - 1, 8, 3, hair)
        p.rect(cx - 5, hy, 1, 5, hair)
        p.rect(cx + 4, hy, 1, 5, hair)
        p.rect(cx - 2, hy - 4, 4, 3, hair)
        p.rect(cx - 1, hy - 4, 2, 1, sh(hair, 1.3))
    elif st == 3:
        p.rect(cx - 4, hy - 1, 8, 3, hair)
        for x in (cx - 4, cx - 2, cx, cx + 2):
            p.rect(x, hy - 3, 2, 2, hair)
        p.rect(cx - 5, hy, 1, 3, hair)
    elif st == 4:
        p.rect(cx - 5, hy - 2, 10, 4, hair)
        p.rect(cx - 6, hy, 2, 5, hair)
        p.rect(cx + 4, hy, 2, 5, hair)
        for x in (cx - 4, cx - 1, cx + 2):
            p.px(x, hy - 3, hair)
    else:
        p.rect(cx - 3, hy, 5, 1, sh(skin, 1.08))
        p.rect(cx - 4, hy + 6, 8, 3, hair)
        p.rect(cx - 1 + dx, hy + 6, 2, 1, sh(skin, 0.8))
    if st != 5:
        p.rect(cx - 2, hy - 1, 2, 1, sh(hair, 1.35))
    # face
    ey = hy + 4
    if L.glasses:
        for ex in (cx - 2 + dx, cx + 1 + dx):
            p.rect(ex - 1, ey, 2, 2, (196, 224, 240))
        p.rect(cx - 3 + dx, ey - 1, 6, 1, (44, 44, 52))
    if blink:
        p.rect(cx - 2 + dx, ey + 1, 1, 1, sh(skin, 0.55))
        p.rect(cx + 1 + dx, ey + 1, 1, 1, sh(skin, 0.55))
    else:
        p.rect(cx - 2 + dx, ey, 1, 2, (30, 26, 34))
        p.rect(cx + 1 + dx, ey, 1, 2, (30, 26, 34))
    if L.hair_style != 5:
        p.rect(cx - 1 + dx, hy + 7, 2, 1, (172, 92, 84))
    p.px(cx - 3 + dx, hy + 6, (236, 130, 130), 0.45)
    p.px(cx + 2 + dx, hy + 6, (236, 130, 130), 0.45)
    if L.phones:
        p.rect(cx - 5, hy - 2, 10, 1, (46, 46, 54))
        p.rect(cx - 6, hy + 2, 2, 4, (46, 46, 54))
        p.rect(cx + 4, hy + 2, 2, 4, (46, 46, 54))
        p.px(cx - 6, hy + 3, L.accent)
    if sip:
        p.rect(cx + dx + 1, hy + 6, 3, 4, (244, 244, 240))
        p.px(cx + dx + 4, hy + 7, (244, 244, 240))
        p.rect(cx + dx + 1, hy + 6, 3, 1, (120, 76, 50))


def _head_back(p: Pen, L: Look, cx, hy):
    skin, hair = L.skin, L.hair
    p.rect(cx - 4, hy, 8, 9, skin)
    p.rect(cx - 2, hy + 8, 4, 2, sh(skin, 0.86))
    st = L.hair_style
    if st == 5:
        p.rect(cx - 4, hy + 4, 8, 3, hair)
        p.rect(cx - 2, hy + 1, 3, 1, sh(skin, 1.1))
    else:
        p.rect(cx - 4, hy - 1, 8, 8, hair)
        p.rect(cx - 5, hy, 10, 5, hair)
        if st == 1:
            p.rect(cx - 5, hy, 10, 12, hair)
        elif st == 2:
            p.rect(cx - 2, hy - 4, 4, 4, hair)
        elif st == 3:
            for x in (cx - 4, cx - 2, cx, cx + 2):
                p.rect(x, hy - 3, 2, 2, hair)
        elif st == 4:
            p.rect(cx - 6, hy - 2, 12, 8, hair)
        p.rect(cx - 1, hy, 3, 1, sh(hair, 1.3))
    p.px(cx - 5, hy + 4, skin)
    p.px(cx + 4, hy + 4, sh(skin, 0.9))
    if L.phones:
        p.rect(cx - 5, hy - 2, 10, 1, (46, 46, 54))
        p.rect(cx - 6, hy + 2, 2, 4, (46, 46, 54))
        p.rect(cx + 4, hy + 2, 2, 4, (46, 46, 54))


def _torso(p: Pen, L: Look, cx, ty, back):
    tc = L.top
    p.rect(cx - 5, ty, 10, 10, tc)
    p.rect(cx - 5, ty, 1, 10, sh(tc, 1.12))
    p.rect(cx + 4, ty, 1, 10, sh(tc, 0.8))
    p.rect(cx - 4, ty, 8, 1, sh(tc, 1.1))
    st = L.top_style
    if back:
        if st == 1:
            p.rect(cx - 3, ty, 6, 3, sh(tc, 0.8))
        elif st == 2:
            p.rect(cx - 2, ty, 4, 1, (236, 236, 240))
            p.rect(cx, ty + 2, 1, 7, sh(tc, 0.86))
        elif st == 4:
            p.rect(cx - 5, ty + 4, 10, 1, L.accent)
    else:
        if st == 0:
            p.rect(cx - 2, ty, 4, 1, L.skin)
            p.rect(cx - 1, ty + 1, 2, 1, L.skin)
            p.rect(cx - 1, ty + 4, 3, 2, L.accent)
        elif st == 1:
            p.rect(cx - 3, ty, 6, 2, sh(tc, 0.78))
            p.rect(cx - 2, ty + 2, 1, 3, (240, 240, 236))
            p.rect(cx + 1, ty + 2, 1, 3, (240, 240, 236))
            p.rect(cx - 3, ty + 6, 6, 2, sh(tc, 0.85))
        elif st == 2:
            p.rect(cx - 2, ty, 4, 6, (238, 238, 242))
            p.rect(cx - 1, ty + 1, 2, 6, L.accent)
            p.rect(cx - 3, ty, 1, 5, sh(tc, 0.75))
            p.rect(cx + 2, ty, 1, 5, sh(tc, 0.75))
            p.px(cx + 2, ty + 7, (200, 200, 210))
        elif st == 3:
            p.rect(cx - 1, ty, 2, 10, (236, 232, 220))
            p.px(cx - 2, ty + 3, sh(tc, 0.7))
            p.px(cx - 2, ty + 6, sh(tc, 0.7))
        else:
            p.rect(cx - 5, ty + 4, 10, 1, L.accent)
            p.rect(cx - 5, ty + 6, 10, 1, L.accent)
            p.rect(cx - 2, ty, 4, 1, sh(tc, 0.85))
    p.rect(cx - 5, ty + 10, 10, 1, sh(L.pants, 0.7))


def _legs(p: Pen, L: Look, cx, phase):
    ly = 33
    pc = L.pants
    p.rect(cx - 4, ly, 4, 8 + phase, pc)
    p.rect(cx, ly, 4, 8 - phase, sh(pc, 0.84))
    p.rect(cx - 1, ly, 1, 2, sh(pc, 0.7))
    p.rect(cx - 5, ly + 8 + phase, 5, 2, L.shoes)
    p.rect(cx, ly + 8 - phase, 5, 2, sh(L.shoes, 0.86))


def _draw(L: Look, pose: str, frame: int):
    surf, cr = new_surface(SW, SH)
    p = Pen(cr)
    cx = AX
    back = pose.endswith("back")
    walking = pose.startswith("walk")
    seated = pose.startswith("sit")
    phase = (0, 1, 0, -1)[frame % 4] if walking else 0
    bob = -1 if walking and frame % 2 == 1 else 0
    yo = (SIT_DROP if seated else 0) + bob
    ty, hy = 22 + yo, 11 + yo
    blink = (seated and frame == 3) or (pose.startswith("stand") and frame == 1)
    sip = (seated and frame == 4) or (pose.startswith("stand") and frame == 2)
    typing = seated and frame in (1, 2)
    if not seated:
        _legs(p, L, cx, phase)
    tc = L.top
    # arms behind the torso
    if seated and not back:
        p.rect(cx - 7, ty + 1, 2, 6, sh(tc, 0.9))
        p.rect(cx + 5, ty + 1, 2, 6, sh(tc, 0.78))
    elif not sip:
        sw = -phase if walking else 0
        p.rect(cx - 7, ty + 1, 2, 9 + sw, sh(tc, 0.9))
        p.rect(cx + 5, ty + 1, 2, 9 - sw, sh(tc, 0.78))
        p.rect(cx - 7, ty + 10 + sw, 2, 2, L.skin)
        p.rect(cx + 5, ty + 10 - sw, 2, 2, sh(L.skin, 0.9))
    _torso(p, L, cx, ty, back)
    if seated and not back:
        a = -1 if frame == 1 else 0
        b = -1 if frame == 2 else 0
        p.rect(cx - 7, ty + 7, 3, 2, sh(tc, 0.9))
        p.rect(cx + 4, ty + 7, 3, 2, sh(tc, 0.78))
        if not sip:
            p.rect(cx - 5, ty + 8 + a, 2, 2, L.skin)
        p.rect(cx + 3, ty + 8 + b, 2, 2, sh(L.skin, 0.9))
    elif seated and back:
        a = 1 if frame == 1 else 0
        b = 1 if frame == 2 else 0
        p.rect(cx - 7, ty + 1 + a, 2, 7, sh(tc, 0.86))
        p.rect(cx + 5, ty + 1 + b, 2, 7, sh(tc, 0.74))
    if sip and not back:
        p.rect(cx + 5, ty + 1, 2, 4, sh(tc, 0.78))
        p.rect(cx + 3, ty + 3, 3, 2, sh(tc, 0.78))
    if back:
        _head_back(p, L, cx, hy)
    else:
        _head_front(p, L, cx, hy, 1, blink, sip)
    if typing and back:
        pass
    return surf


_cache: dict[str, object] = {}


def sprite(L: Look, pose: str, frame: int, flip: bool):
    """(sid, outlined surface). Anchor in the returned surface: (AX+1, AY+1)."""
    sid = f"p:{L.key}:{pose}:{frame}:{int(flip)}"
    s = _cache.get(sid)
    if s is None:
        if len(_cache) > 1500:
            _cache.clear()
        base = _draw(L, pose, frame)
        if flip:
            base = flip_h(base)
        s = outline(base)
        _cache[sid] = s
    return sid, s


def head_top(pose: str, frame: int) -> int:
    """Y of the hair top relative to the anchor (negative = above)."""
    yo = SIT_DROP if pose.startswith("sit") else 0
    if pose.startswith("walk") and frame % 2 == 1:
        yo -= 1
    return HEAD_STAND - 3 + yo - AY


# -------------------------------------------------------------- bubbles
GLYPHS = {
    "code": ["..#...#..", ".#..#..#.", "#...#...#", ".#.#...#.", "..#...#.."],
    "term": ["##.......", ".##......", "..##.....", ".##......", "##..####."],
    "look": [".###...", "#...#..", "#...#..", ".###.#.", ".....##"],
    "web": [".#####.", "#.#.#.#", "#######", "#.#.#.#", ".#####."],
    "team": [".#...#.", "###.###", ".#...#.", "##...##", "##...##"],
    "gear": ["..#.#..", ".#####.", "##...##", ".#####.", "..#.#.."],
    "wait": ["#######", ".#...#.", "..#.#..", ".#...#.", "#######"],
    "ask": [".###.", "#...#", "...#.", "..#..", ".....", "..#.."],
    "dots1": ["#....", ".....", "....."],
    "dots2": ["#.#..", ".....", "....."],
    "dots3": ["#.#.#", ".....", "....."],
    "idea": [".###.", "#...#", "#...#", ".#.#.", ".###."],
}
TOOL_ICON = {"Edit": "code", "Write": "code", "MultiEdit": "code", "NotebookEdit": "code",
             "Bash": "term", "BashOutput": "term", "Read": "look", "Grep": "look", "Glob": "look",
             "LS": "look", "WebFetch": "web", "WebSearch": "web", "Agent": "team", "Task": "team",
             "TodoWrite": "idea"}
INK_COLORS = {"red": (204, 58, 48), "yellow": (196, 140, 16), "ink": (64, 60, 72)}


def bubble(kind: str, color: str):
    sid = f"b:{kind}:{color}"
    s = _cache.get(sid)
    if s is None:
        g = GLYPHS[kind]
        gw, gh = len(g[0]), len(g)
        bw, bh = gw + 6, gh + 6
        surf, cr = new_surface(bw + 2, bh + 4)
        p = Pen(cr)
        white = (252, 250, 244)
        p.rect(1, 0, bw - 2, bh, white)
        p.rect(0, 1, bw, bh - 2, white)
        p.rect(2, bh, 3, 1, white)
        p.rect(2, bh + 1, 1, 1, white)
        p.rect(1, bh - 2, bw - 2, 1, (222, 218, 208))
        col = INK_COLORS.get(color, INK_COLORS["ink"])
        for r, row in enumerate(g):
            for c, ch in enumerate(row):
                if ch == "#":
                    p.px(3 + c, 3 + r, col)
        s = outline(surf, (40, 34, 40))
        _cache[sid] = s
    return sid, s
