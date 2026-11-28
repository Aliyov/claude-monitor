"""OfficeCanvas: the animated pixel-art office.

Per department a Scene (scene.py) owns a pre-rendered background and the
sprites; every frame the canvas only composites textures with the GPU:

  background texture + a few dozen sprite textures + name tags.

Textures are made once per sprite (pre-scaled by an integer k with nearest
neighbour, then GPU-scaled linearly to the exact zoom, which keeps pixels
even at any size) and cached.

Animation runs on a GLib timer at 12 fps for an enlarged department and 8 fps
for the grid (4 fps while the window is in the background). It stops
completely when the page is hidden, the window is minimised, or the desktop
asks for reduced animations (then a single still frame is shown).
"""
from __future__ import annotations

import math
import time

import cairo
from gi.repository import Gdk, GLib, Graphene, Gsk, Gtk, Pango

from .model import GREEN, GREY, RED, YELLOW, DepartmentView
from .scene import Scene, layout_key, phase_for

GAP_PX = 22
PAD_PX = 12
SIGN_H = 30
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


def _texture(surf: cairo.ImageSurface, k: int) -> Gdk.Texture:
    if k > 1:
        big = cairo.ImageSurface(cairo.FORMAT_ARGB32, surf.get_width() * k, surf.get_height() * k)
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


class _Dept:
    __slots__ = ("view", "scene", "tex")

    def __init__(self) -> None:
        self.view = None
        self.scene = None
        self.tex: dict = {}


class OfficeCanvas(Gtk.Widget):
    __gtype_name__ = "CmOfficeCanvas"
    TAG_MIN_SCALE = 1.25

    def __init__(self, on_focus=None) -> None:
        super().__init__(hexpand=True, vexpand=True)
        self.add_css_class("cm-office-canvas")
        self._depts: list[_Dept] = []
        self._views: list[DepartmentView] = []
        self._layouts: dict[tuple, Pango.Layout] = {}
        self._shared_tex: dict = {}
        self._placed: list = []
        self._scale = 1.0
        self._timer = 0
        self._fps = 0
        self._phase = None
        self._root_handler = None
        self.focus_slot: int | None = None
        self._on_focus = on_focus
        self.last_frame_ms = 0.0
        click = Gtk.GestureClick()
        click.connect("released", self._on_click)
        self.add_controller(click)
        motion = Gtk.EventControllerMotion()
        motion.connect("motion", self._on_motion)
        self.add_controller(motion)
        self.connect("map", self._on_map)
        self.connect("unmap", lambda *_: self._update_anim())
        settings = Gtk.Settings.get_default()
        if settings is not None:
            settings.connect("notify::gtk-enable-animations", lambda *_: self._update_anim())

    # ------------------------------------------------------------ animation
    @staticmethod
    def animations_enabled() -> bool:
        s = Gtk.Settings.get_default()
        return bool(s.get_property("gtk-enable-animations")) if s is not None else True

    def _on_map(self, *_a) -> None:
        root = self.get_root()
        if root is not None and self._root_handler is None and hasattr(root, "is_suspended"):
            self._root_handler = (root, [root.connect("notify::suspended", lambda *_: self._update_anim()),
                                         root.connect("notify::is-active", lambda *_: self._update_anim())])
        self._update_anim()

    def _wanted_fps(self) -> int:
        if not self.get_mapped() or not self.animations_enabled():
            return 0
        root = self.get_root()
        if root is not None and hasattr(root, "is_suspended") and root.is_suspended():
            return 0
        if not any(d.view is not None and d.view.lit for d in self._depts):
            return 0
        if root is not None and hasattr(root, "is_active") and not root.is_active():
            return 4
        return 12 if self.focus_slot is not None or len(self._depts) == 1 else 8

    def _update_anim(self) -> None:
        fps = self._wanted_fps()
        if fps == self._fps:
            return
        if self._timer:
            GLib.source_remove(self._timer)
            self._timer = 0
        self._fps = fps
        if fps:
            self._timer = GLib.timeout_add(int(1000 / fps), self._tick)
        self.queue_draw()

    def _tick(self) -> bool:
        lt = time.localtime()
        if phase_for(lt.tm_hour) != self._phase and self._views:
            self.set_views(self._views)
        self.queue_draw()
        return True

    # ---------------------------------------------------------------- focus
    def set_focus_slot(self, slot: int | None) -> None:
        if slot == self.focus_slot:
            return
        self.focus_slot = slot
        self.set_cursor(None)
        self._update_anim()
        self.queue_draw()
        if self._on_focus:
            self._on_focus(slot)

    def _dept_at(self, x, y):
        s = self._scale
        for d, dx, dy in self._placed:
            sc = d.scene
            if dx <= x <= dx + sc.width * s and dy - SIGN_H <= y <= dy + sc.height * s:
                return d
        return None

    def _on_click(self, gesture, n_press, x, y) -> None:
        if self.focus_slot is None:
            d = self._dept_at(x, y)
            if d is not None:
                self.set_focus_slot(d.view.slot)

    def _on_motion(self, _ctl, x, y) -> None:
        if self.focus_slot is None and self._dept_at(x, y) is not None:
            self.set_cursor(Gdk.Cursor.new_from_name("pointer", None))
        else:
            self.set_cursor(None)

    # ----------------------------------------------------------------- data
    def set_views(self, views: list[DepartmentView]) -> None:
        now = time.time()
        self._views = views
        self._phase = phase_for(time.localtime().tm_hour)
        old = {d.view.slot: d for d in self._depts if d.view is not None}
        new: list[_Dept] = []
        for v in views:
            d = old.get(v.slot) or _Dept()
            key = layout_key(v, self._phase)
            if d.scene is None or d.scene.key != key:
                d.scene = Scene(v, self._phase)
                d.tex = {}
            d.scene.sync(v, now)
            if d.scene.director is not None:
                d.scene.director.calm = not self.animations_enabled()
            d.view = v
            new.append(d)
        self._depts = new
        if self.focus_slot is not None and all(d.view.slot != self.focus_slot for d in new):
            self.set_focus_slot(None)
        self._update_anim()
        self.queue_draw()

    # --------------------------------------------------------------- layout
    def _arrange(self, width: float, height: float):
        depts = self._depts
        if self.focus_slot is not None:
            depts = [d for d in depts if d.view.slot == self.focus_slot] or depts
        n = len(depts)
        if not n:
            return 1.0, []
        best = None
        for cols in range(1, n + 1):
            rows = math.ceil(n / cols)
            grid = [depts[i:i + cols] for i in range(0, n, cols)]
            gw = max(sum(d.scene.width for d in row) for row in grid)
            gh = sum(max(d.scene.height for d in row) for row in grid)
            avail_w = width - 2 * PAD_PX - GAP_PX * (cols - 1)
            avail_h = height - 2 * PAD_PX - (GAP_PX + SIGN_H) * rows + GAP_PX
            s = min(avail_w / gw, avail_h / gh)
            if best is None or s > best[0]:
                best = (s, grid)
        s, grid = best
        s = max(0.25, min(s, 8.0))
        placed = []
        total_h = (sum(max(d.scene.height for d in row) for row in grid) * s
                   + (GAP_PX + SIGN_H) * len(grid) - GAP_PX)
        y = max(PAD_PX, (height - total_h) / 2) + SIGN_H
        for row in grid:
            row_w = sum(d.scene.width for d in row) * s + GAP_PX * (len(row) - 1)
            x = max(PAD_PX, (width - row_w) / 2)
            for d in row:
                placed.append((d, x, y))
                x += d.scene.width * s + GAP_PX
            y += max(d.scene.height for d in row) * s + GAP_PX + SIGN_H
        return s, placed

    # -------------------------------------------------------------- drawing
    def _tex(self, d: _Dept, sid: str, surf, k: int) -> Gdk.Texture:
        shared = sid[0] in "pb"
        cache = self._shared_tex if shared else d.tex
        key = (sid, k)
        t = cache.get(key)
        if t is None:
            if len(cache) > 2500:
                cache.clear()
            t = _texture(surf, k)
            cache[key] = t
        return t

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
        t0 = time.perf_counter()
        w, h = self.get_width(), self.get_height()
        s, placed = self._arrange(w, h)
        self._scale, self._placed = s, placed
        k = max(1, min(MAX_PRESCALE, math.ceil(s - 0.01)))
        filt = Gsk.ScalingFilter.NEAREST if abs(k - s) < 0.01 else Gsk.ScalingFilter.LINEAR
        now = time.time()
        lt = time.localtime(now)
        show_tags = s >= self.TAG_MIN_SCALE
        for d, x, y in placed:
            sc = d.scene
            snap.append_scaled_texture(self._tex(d, f"bg{sc.uid}", sc.background, k), filt,
                                       _rect(x, y, sc.width * s, sc.height * s))
            fr = sc.frame(now, lt.tm_hour, lt.tm_min)
            for dr in fr.draws:
                sw, sh_ = dr.surf.get_width(), dr.surf.get_height()
                snap.append_scaled_texture(self._tex(d, dr.sid, dr.surf, k), filt,
                                           _rect(x + dr.x * s, y + dr.y * s, sw * s, sh_ * s))
            self._sign(snap, d.view, x, y - SIGN_H + 2, sc.width * s)
            if not show_tags:
                continue
            taken: list[tuple] = []
            for tg in sorted(fr.tags, key=lambda t: (t.y, t.x)):
                p = tg.person
                if p.filler or not p.name:
                    continue
                self._name_tag(snap, p.name, p.light, x + tg.x * s, y + tg.y * s, int(max(90, 64 * s)), taken)
        self.last_frame_ms = (time.perf_counter() - t0) * 1000

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
