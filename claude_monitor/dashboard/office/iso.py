"""Isometric pixel pen used by the office art.

Projection: tile (i, j) at height z (art pixels) maps to
    x = ox + (i - j) * 16,   y = oy + (i + j) * 8 - z
Vertical faces and the floor are drawn through affine cairo matrices, so
bricks, planks, windows and screens are plain rectangles in plane space.
Antialiasing is off: edges come out as crisp 2:1 pixel stair-steps.

The pen tracks the device-space bounding box of everything it fills, which
lets the scene crop each object into its own sprite.
"""
from __future__ import annotations

import math

import cairo

HW, HH = 16, 8
INK = (36, 26, 30)       # outline colour
PX_J = 1 / 8             # one screen pixel of thickness, in tile units


def sh(rgb, k):
    return tuple(max(0, min(255, int(round(v * k)))) for v in rgb)


def mix(a, b, t):
    return tuple(int(round(x + (y - x) * t)) for x, y in zip(a, b))


class Pen:
    def __init__(self, cr: cairo.Context, ox: float = 0.0, oy: float = 0.0) -> None:
        self.cr, self.ox, self.oy = cr, ox, oy
        self.bb = None

    # ------------------------------------------------------------ basics
    def begin(self) -> None:
        self.bb = None

    def pt(self, i, j, z=0.0):
        return self.ox + (i - j) * HW, self.oy + (i + j) * HH - z

    def ipt(self, i, j, z=0.0):
        x, y = self.pt(i, j, z)
        return int(math.floor(x)), int(math.floor(y))

    def _fill(self, rgb, a=1.0) -> None:
        cr = self.cr
        cr.set_source_rgba(rgb[0] / 255, rgb[1] / 255, rgb[2] / 255, a)
        x1, y1, x2, y2 = cr.fill_extents()
        if x2 > x1 and y2 > y1:
            pts = [cr.user_to_device(x, y) for x, y in ((x1, y1), (x2, y1), (x1, y2), (x2, y2))]
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            b = (min(xs), min(ys), max(xs), max(ys))
            self.bb = b if self.bb is None else (min(self.bb[0], b[0]), min(self.bb[1], b[1]),
                                                 max(self.bb[2], b[2]), max(self.bb[3], b[3]))
        cr.fill()

    def rect(self, x, y, w, h, rgb, a=1.0) -> None:
        if w <= 0 or h <= 0:
            return
        self.cr.rectangle(x, y, w, h)
        self._fill(rgb, a)

    def px(self, x, y, rgb, a=1.0) -> None:
        self.rect(int(x), int(y), 1, 1, rgb, a)

    def poly(self, pts, rgb, a=1.0) -> None:
        cr = self.cr
        cr.move_to(*pts[0])
        for p in pts[1:]:
            cr.line_to(*p)
        cr.close_path()
        self._fill(rgb, a)

    # ------------------------------------------------------------ planes
    def floor(self, z=0.0) -> "Plane":
        """Horizontal plane at height z; local units are tiles (i, j)."""
        return Plane(self, cairo.Matrix(HW, HH, -HW, HH, self.ox, self.oy - z))

    def face_i(self, i, j, z) -> "Plane":
        """Vertical plane along +i through (i, j); seen from +j (lower left).
        Local x = tiles along i, local y = pixels down from height z."""
        x, y = self.pt(i, j, z)
        return Plane(self, cairo.Matrix(HW, HH, 0, 1, x, y))

    def face_j(self, i, j, z) -> "Plane":
        """Vertical plane along +j through (i, j); seen from +i (lower right)."""
        x, y = self.pt(i, j, z)
        return Plane(self, cairo.Matrix(-HW, HH, 0, 1, x, y))

    # ------------------------------------------------------------ solids
    def box(self, i, j, z, w, d, h, rgb, top=None, kl=0.84, kr=0.66, hi=True) -> None:
        """Prism: top, +j face (left) and +i face (right); 1-px highlight on
        the top's front edges."""
        top = top or rgb
        with self.face_i(i, j + d, z + h) as p:
            p.rect(0, 0, w, h, sh(rgb, kl))
        with self.face_j(i + w, j, z + h) as p:
            p.rect(0, 0, d, h, sh(rgb, kr))
        with self.floor(z + h) as p:
            p.rect(i, j, w, d, top)
            if hi and w > 0.2 and d > 0.2:
                p.rect(i, j + d - PX_J, w, PX_J, sh(top, 1.14))
                p.rect(i + w - PX_J, j, PX_J, d, sh(top, 1.08))

    def shadow(self, i, j, w, d, a=0.22, grow=0.18) -> None:
        """Soft contact shadow on the floor (two stacked translucent rects)."""
        with self.floor(0) as p:
            p.rect(i - grow, j - grow * 0.5, w + grow * 2, d + grow * 1.6, (20, 10, 6), a * 0.5)
            p.rect(i, j, w + grow, d + grow, (20, 10, 6), a * 0.6)


class Plane:
    def __init__(self, pen: Pen, m: cairo.Matrix) -> None:
        self.pen, self.m = pen, m

    def __enter__(self) -> "Plane":
        self.pen.cr.save()
        self.pen.cr.transform(self.m)
        return self

    def __exit__(self, *a) -> None:
        self.pen.cr.restore()

    def rect(self, x, y, w, h, rgb, a=1.0) -> None:
        if w <= 0 or h <= 0:
            return
        self.pen.cr.rectangle(x, y, w, h)
        self.pen._fill(rgb, a)


# ------------------------------------------------------------- surfaces
def new_surface(w: int, h: int) -> tuple[cairo.ImageSurface, cairo.Context]:
    s = cairo.ImageSurface(cairo.FORMAT_ARGB32, max(1, int(w)), max(1, int(h)))
    cr = cairo.Context(s)
    cr.set_antialias(cairo.ANTIALIAS_NONE)
    return s, cr


def crop(src: cairo.ImageSurface, bb) -> tuple[cairo.ImageSurface, int, int]:
    W, H = src.get_width(), src.get_height()
    x0 = max(0, int(math.floor(bb[0])))
    y0 = max(0, int(math.floor(bb[1])))
    x1 = min(W, int(math.ceil(bb[2])))
    y1 = min(H, int(math.ceil(bb[3])))
    out, cr = new_surface(x1 - x0, y1 - y0)
    cr.set_source_surface(src, -x0, -y0)
    cr.paint()
    return out, x0, y0


def outline(src: cairo.ImageSurface, rgb=INK, a=1.0) -> cairo.ImageSurface:
    """1-px pixel-art outline around the opaque shape (4-neighbourhood)."""
    out, cr = new_surface(src.get_width() + 2, src.get_height() + 2)
    cr.set_source_rgba(rgb[0] / 255, rgb[1] / 255, rgb[2] / 255, a)
    for dx, dy in ((0, 1), (2, 1), (1, 0), (1, 2)):
        cr.mask_surface(src, dx, dy)
    cr.set_source_surface(src, 1, 1)
    cr.paint()
    return out


def flip_h(src: cairo.ImageSurface) -> cairo.ImageSurface:
    w = src.get_width()
    out, cr = new_surface(w, src.get_height())
    cr.translate(w, 0)
    cr.scale(-1, 1)
    cr.set_source_surface(src, 0, 0)
    cr.get_source().set_filter(cairo.FILTER_NEAREST)
    cr.paint()
    return out
