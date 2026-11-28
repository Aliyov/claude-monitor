"""OfficeCanvas: shows departments as pixel art, scaled with nearest-neighbour.

Each department is drawn into a small cairo surface (scene.render) only when
its content changes, uploaded once as a texture, and scaled by the GPU in
snapshot(). Name labels are drawn at full resolution on top so they stay
readable at any scale. No timers run here: the widget redraws only when a new
snapshot changes something (animation arrives in a later step).
"""
from __future__ import annotations

import math

import cairo
from gi.repository import Gdk, GLib, Graphene, Gsk, Gtk, Pango

from . import scene
from .model import GREEN, GREY, RED, YELLOW, DepartmentView

GAP_PX = 22        # gap between departments, in widget pixels
PAD_PX = 12
SIGN_H = 30        # room above each department for its sign
MAX_PRESCALE = 6
LABEL_FONT = "Sans Bold 8"
SIGN_FONT = "Sans Bold 10"
DOT_RGBA = {RED: (0.91, 0.27, 0.24), YELLOW: (0.94, 0.75, 0.2), GREEN: (0.31, 0.77, 0.39),
            GREY: (0.62, 0.62, 0.62)}


def _rgba(r, g, b, a=1.0) -> Gdk.RGBA:
    c = Gdk.RGBA()
    c.red, c.green, c.blue, c.alpha = r, g, b, a
    return c


def _rect(x, y, w, h) -> Graphene.Rect:
    return Graphene.Rect().init(x, y, w, h)


def _texture(r: scene.Rendered, k: int) -> Gdk.Texture:
    """Texture of the art upscaled k times with nearest-neighbour. The GPU then
    scales it (linearly) to the exact on-screen size: crisp, even pixels at
    any fractional zoom."""
    surf = r.surface
    if k > 1:
        big = cairo.ImageSurface(cairo.FORMAT_ARGB32, r.width * k, r.height * k)
        cr = cairo.Context(big)
        cr.scale(k, k)
        cr.set_source_surface(surf, 0, 0)
        cr.get_source().set_filter(cairo.FILTER_NEAREST)
        cr.paint()
        surf = big
    surf.flush()
    data = GLib.Bytes.new(bytes(surf.get_data()))
    # cairo ARGB32 is native-endian premultiplied: BGRA bytes on little-endian
    return Gdk.MemoryTexture.new(surf.get_width(), surf.get_height(),
                                 Gdk.MemoryFormat.B8G8R8A8_PREMULTIPLIED, data, surf.get_stride())


def _art_key(v: DepartmentView) -> tuple:
    return (v.lit, v.slot, tuple((p.key, p.role, p.seat, p.name, p.light, p.working) for p in v.people))


class _Dept:
    __slots__ = ("view", "key", "rendered", "texture", "tex_k")

    def __init__(self) -> None:
        self.view = None
        self.key = None
        self.rendered = None
        self.texture = None
        self.tex_k = 0

    def texture_for(self, scale: float) -> Gdk.Texture:
        k = max(1, min(MAX_PRESCALE, math.ceil(scale - 0.01)))
        if self.texture is None or self.tex_k != k:
            self.texture, self.tex_k = _texture(self.rendered, k), k
        return self.texture


class OfficeCanvas(Gtk.Widget):
    __gtype_name__ = "CmOfficeCanvas"

    def __init__(self) -> None:
        super().__init__(hexpand=True, vexpand=True)
        self.add_css_class("cm-office-canvas")
        self._depts: list[_Dept] = []
        self._layouts: dict[tuple, Pango.Layout] = {}

    # ----------------------------------------------------------------- data
    def set_views(self, views: list[DepartmentView]) -> None:
        old = {d.view.slot: d for d in self._depts if d.view is not None}
        new: list[_Dept] = []
        for v in views:
            d = old.get(v.slot) or _Dept()
            key = _art_key(v)
            if key != d.key:
                d.rendered = scene.render(v)
                d.texture = None
                d.key = key
            d.view = v
            new.append(d)
        self._depts = new
        self.queue_draw()

    # --------------------------------------------------------------- layout
    def _arrange(self, width: float, height: float):
        """Pick the column count and scale that show every department as large
        as possible."""
        n = len(self._depts)
        if not n:
            return 1.0, []
        best = None
        for cols in range(1, n + 1):
            rows = math.ceil(n / cols)
            grid = [self._depts[i:i + cols] for i in range(0, n, cols)]
            gw = max(sum(d.rendered.width for d in row) for row in grid)
            gh = sum(max(d.rendered.height for d in row) for row in grid)
            avail_w = width - 2 * PAD_PX - GAP_PX * (cols - 1)
            avail_h = height - 2 * PAD_PX - (GAP_PX + SIGN_H) * rows + GAP_PX
            s = min(avail_w / gw, avail_h / gh)
            if best is None or s > best[0]:
                best = (s, grid)
        s, grid = best
        s = max(0.25, min(s, 8.0))
        placed = []
        total_h = (sum(max(d.rendered.height for d in row) for row in grid) * s
                   + (GAP_PX + SIGN_H) * len(grid) - GAP_PX)
        y = max(PAD_PX, (height - total_h) / 2) + SIGN_H
        for row in grid:
            row_w = sum(d.rendered.width for d in row) * s + GAP_PX * (len(row) - 1)
            x = max(PAD_PX, (width - row_w) / 2)
            for d in row:
                placed.append((d, x, y))
                x += d.rendered.width * s + GAP_PX
            y += max(d.rendered.height for d in row) * s + GAP_PX + SIGN_H
        return s, placed

    # --------------------------------------------------------------- drawing
    def _layout(self, text: str, font: str, max_w: int) -> Pango.Layout:
        k = (text, font, max_w)
        lay = self._layouts.get(k)
        if lay is None:
            if len(self._layouts) > 400:
                self._layouts.clear()
            lay = self.create_pango_layout(text)
            lay.set_font_description(Pango.FontDescription.from_string(font))
            lay.set_width(max_w * Pango.SCALE)
            lay.set_ellipsize(Pango.EllipsizeMode.END)
            self._layouts[k] = lay
        return lay

    def do_snapshot(self, snap: Gtk.Snapshot) -> None:
        w, h = self.get_width(), self.get_height()
        s, placed = self._arrange(w, h)
        for d, x, y in placed:
            r = d.rendered
            tex = d.texture_for(s)
            filt = Gsk.ScalingFilter.NEAREST if tex.get_width() == round(r.width * s) \
                else Gsk.ScalingFilter.LINEAR
            snap.append_scaled_texture(tex, filt, _rect(x, y, r.width * s, r.height * s))
            self._sign(snap, d.view, x, y - SIGN_H + 2, r.width * s)
            cell = scene.DESK_W * s
            taken: list[tuple] = []
            for a in sorted(r.anchors, key=lambda a: (a.y, a.x)):
                p = a.person
                if p.filler or not p.name:
                    continue
                self._name_tag(snap, p.name, p.light, x + a.x * s, y + (a.y - 2) * s,
                               int(max(56, cell * 1.9)), taken)

    def _pill(self, snap, x, y, w, h, rgba) -> None:
        rr = Gsk.RoundedRect()
        rr.init_from_rect(_rect(x, y, w, h), h / 2)
        snap.push_rounded_clip(rr)
        snap.append_color(rgba, _rect(x, y, w, h))
        snap.pop()

    def _name_tag(self, snap, text, light, cx, bottom, max_w, taken) -> None:
        lay = self._layout(text, LABEL_FONT, max_w - 14)
        _ink, logical = lay.get_pixel_extents()
        tw, th = logical.width, logical.height
        dot = 6
        pw, ph = tw + dot + 12, th + 4
        x, y = round(cx - pw / 2), round(bottom - ph)
        for _ in range(3):   # lift the tag above any tag it would cover
            hit = [t for t in taken if x < t[0] + t[2] + 2 and t[0] < x + pw + 2
                   and y < t[1] + t[3] + 1 and t[1] < y + ph + 1]
            if not hit:
                break
            y = min(t[1] for t in hit) - ph - 1
        taken.append((x, y, pw, ph))
        self._pill(snap, x, y, pw, ph, _rgba(0.08, 0.08, 0.1, 0.78))
        c = DOT_RGBA.get(light)
        if c:
            self._pill(snap, x + 5, y + (ph - dot) / 2, dot, dot, _rgba(*c))
        snap.save()
        snap.translate(Graphene.Point().init(x + dot + 8, y + 2))
        snap.append_layout(lay, _rgba(1, 1, 1, 0.96))
        snap.restore()

    def _sign(self, snap, v: DepartmentView, x, y, dept_w) -> None:
        text = v.title if v.lit else f"{v.title} · dark"
        lay = self._layout(text, SIGN_FONT, int(max(120, dept_w - 16)))
        _ink, logical = lay.get_pixel_extents()
        pw, ph = logical.width + 16, logical.height + 6
        self._pill(snap, x, y, pw, ph, _rgba(0.12, 0.1, 0.09, 0.85 if v.lit else 0.6))
        snap.save()
        snap.translate(Graphene.Point().init(x + 8, y + 3))
        snap.append_layout(lay, _rgba(1, 0.93, 0.82, 1 if v.lit else 0.6))
        snap.restore()
