#!/usr/bin/env python3
"""Generate the dashboard's symbolic icons as *fill-only* SVG geometry.

GTK 4.22's symbolic icon loader fills every path (it ignores strokes), so
line art is expanded here into filled polygons: thick segments with round
caps, even-odd rings, etc.

    python3 tools/gen_icons.py  # writes claude_monitor/dashboard/icons/
"""

from __future__ import annotations

import math
import os

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "claude_monitor", "dashboard", "icons")
C = "#222"


def f(v: float) -> str:
    return f"{v:.3f}".rstrip("0").rstrip(".")


def circle_d(cx, cy, r) -> str:
    return (f"M{f(cx - r)} {f(cy)}a{f(r)} {f(r)} 0 1 0 {f(2 * r)} 0"
            f"a{f(r)} {f(r)} 0 1 0 {f(-2 * r)} 0z")


def dot(cx, cy, r) -> str:
    return f'<path fill="{C}" d="{circle_d(cx, cy, r)}"/>'


def ring(cx, cy, r, w) -> str:
    return (f'<path fill="{C}" fill-rule="evenodd" d="{circle_d(cx, cy, r + w / 2)}'
            f'{circle_d(cx, cy, r - w / 2)}"/>')


def rrect_d(x, y, w, h, r) -> str:
    r = min(r, w / 2, h / 2)
    return (f"M{f(x + r)} {f(y)}h{f(w - 2 * r)}a{f(r)} {f(r)} 0 0 1 {f(r)} {f(r)}"
            f"v{f(h - 2 * r)}a{f(r)} {f(r)} 0 0 1 {f(-r)} {f(r)}h{f(-(w - 2 * r))}"
            f"a{f(r)} {f(r)} 0 0 1 {f(-r)} {f(-r)}v{f(-(h - 2 * r))}a{f(r)} {f(r)} 0 0 1 {f(r)} {f(-r)}z")


def rrect(x, y, w, h, r) -> str:
    return f'<path fill="{C}" d="{rrect_d(x, y, w, h, r)}"/>'


def rrect_ring(x, y, w, h, r, t) -> str:
    return (f'<path fill="{C}" fill-rule="evenodd" d="{rrect_d(x - t / 2, y - t / 2, w + t, h + t, r + t / 2)}'
            f'{rrect_d(x + t / 2, y + t / 2, w - t, h - t, max(0.1, r - t / 2))}"/>')


def seg(x1, y1, x2, y2, w) -> str:
    dx, dy = x2 - x1, y2 - y1
    ln = math.hypot(dx, dy) or 1
    nx, ny = -dy / ln * w / 2, dx / ln * w / 2
    pts = [(x1 + nx, y1 + ny), (x2 + nx, y2 + ny), (x2 - nx, y2 - ny), (x1 - nx, y1 - ny)]
    d = "M" + "L".join(f"{f(a)} {f(b)}" for a, b in pts) + "z"
    return f'<path fill="{C}" d="{d}"/>'


def polyline(points, w, caps=True) -> str:
    out = []
    for (x1, y1), (x2, y2) in zip(points, points[1:]):
        out.append(seg(x1, y1, x2, y2, w))
    joints = points if caps else points[1:-1]
    for x, y in joints:
        out.append(dot(x, y, w / 2))
    return "".join(out)


def arc_poly(cx, cy, r, a0, a1, w, steps=28) -> str:
    pts = [(cx + r * math.cos(a0 + (a1 - a0) * i / steps), cy + r * math.sin(a0 + (a1 - a0) * i / steps))
           for i in range(steps + 1)]
    return polyline(pts, w)


W = 1.5  # standard line weight

ICONS = {
    "cm-chart": (rrect(2, 13, 12, 1.5, 0.75) + rrect(3, 8, 2.5, 4, 0.6) + rrect(6.75, 3, 2.5, 9, 0.6)
                 + rrect(10.5, 6, 2.5, 6, 0.6)),
    "cm-pulse": polyline([(1.2, 8.5), (4, 8.5), (5.8, 4.2), (8.4, 12.2), (10.4, 6.8), (11.6, 8.5), (14.8, 8.5)], W),
    "cm-agent": (rrect_ring(3, 5.2, 10, 8, 2.2, W) + dot(6.1, 9.2, 1.25) + dot(9.9, 9.2, 1.25)
                 + polyline([(8, 5), (8, 2.6)], W) + dot(8, 2, 1.1)
                 + polyline([(1.3, 8.2), (1.3, 10.6)], W) + polyline([(14.7, 8.2), (14.7, 10.6)], W)),
    "cm-timeline": (rrect(3.25, 1, 1.5, 14, 0.5) + dot(4, 3.5, 2) + dot(4, 8, 2) + dot(4, 12.5, 2)
                    + rrect(7.5, 2.75, 7, 1.5, 0.75) + rrect(7.5, 7.25, 5, 1.5, 0.75) + rrect(7.5, 11.75, 6, 1.5, 0.75)),
    "cm-cpu": (rrect_ring(3.6, 3.6, 8.8, 8.8, 1.6, W) + rrect(6, 6, 4, 4, 0.7)
               + "".join(rrect(x - 0.6, 0.8, 1.2, 2.2, 0.4) + rrect(x - 0.6, 13, 1.2, 2.2, 0.4) for x in (6, 10))
               + "".join(rrect(0.8, y - 0.6, 2.2, 1.2, 0.4) + rrect(13, y - 0.6, 2.2, 1.2, 0.4) for y in (6, 10))),
    "cm-memory": (rrect_ring(1.6, 3.8, 12.8, 7, 1.4, W) + rrect(4.1, 5.9, 1.6, 2.8, 0.3)
                  + rrect(7.2, 5.9, 1.6, 2.8, 0.3) + rrect(10.3, 5.9, 1.6, 2.8, 0.3)
                  + "".join(rrect(x - 0.55, 11.2, 1.1, 2.6, 0.4) for x in (3.6, 6.1, 8.6, 11.1, 13.1))),
    "cm-token": (ring(8, 8, 6.2, W) + polyline([(5.4, 5.9), (10.6, 5.9)], W) + polyline([(8, 5.9), (8, 11)], W)),
    "cm-plug": (polyline([(5.5, 1.5), (5.5, 4.2)], W) + polyline([(10.5, 1.5), (10.5, 4.2)], W)
                + f'<path fill="{C}" fill-rule="evenodd" d="M2.8 4h10.4v3.2a5.2 5.2 0 0 1-10.4 0zM4.3 5.5v1.7a3.7 3.7 0 0 0 7.4 0V5.5z"/>'
                + polyline([(8, 11.6), (8, 15)], W)),
    "cm-session": (rrect_ring(1.6, 2.6, 12.8, 10.8, 2, W)
                   + polyline([(4.6, 6.3), (6.7, 8.2), (4.6, 10.1)], W) + polyline([(8.6, 10.4), (11.4, 10.4)], W)),
    "cm-overview": (rrect(1.5, 1.5, 6, 7, 1.5) + rrect(8.5, 1.5, 6, 4, 1.5) + rrect(1.5, 9.5, 6, 5, 1.5)
                    + rrect(8.5, 6.5, 6, 8, 1.5)),
    "cm-history": (arc_poly(8, 8, 5.9, math.radians(200), math.radians(200 + 300), W)
                   + f'<path fill="{C}" d="M0.9 3.3L5.6 3.9L2.2 7.4z"/>'
                   + polyline([(8, 4.8), (8, 8.2), (10.4, 9.8)], W)),
    "cm-office": (rrect_ring(3, 2, 10, 7, 1.2, W) + rrect(7.2, 9, 1.6, 2.2, 0.3)
                  + rrect(1, 11.2, 14, 1.8, 0.6) + rrect(2.2, 13, 1.6, 2.2, 0.3) + rrect(12.2, 13, 1.6, 2.2, 0.3)),
    "cm-check": polyline([(3, 8.6), (6.2, 11.6), (13, 4.4)], 1.9),
    "cm-chat": (f'<path fill="{C}" fill-rule="evenodd" d="{rrect_d(1.3, 1.6, 13.4, 10, 2.2)}'
                f'{rrect_d(2.8, 3.1, 10.4, 7, 1)}"/>'
                + f'<path fill="{C}" d="M4 11h3.4L4 14.6z"/>'),
    "cm-compact": (polyline([(4, 2), (8, 5.4), (12, 2)], W) + polyline([(4, 14), (8, 10.6), (12, 14)], W)
                   + polyline([(2, 8), (14, 8)], W)),
}


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    for name, body in ICONS.items():
        svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16">{body}</svg>\n'
        with open(os.path.join(OUT, f"{name}-symbolic.svg"), "w") as fh:
            fh.write(svg)
    print(f"wrote {len(ICONS)} icons to {OUT}")


if __name__ == "__main__":
    main()
