"""Lightweight Cairo charts (no third-party dependencies).

Charts only redraw when data changes or the hovered item changes.
"""

from __future__ import annotations

import math

from gi.repository import Gtk, Pango, PangoCairo

from ..common import fmt
from .widgets import BRAND, fg_rgba

# Categorical palette (brand first), readable on light and dark.
SERIES = [
    BRAND,
    (0x35 / 255, 0x84 / 255, 0xE4 / 255),
    (0x91 / 255, 0x41 / 255, 0xAC / 255),
    (0x2E / 255, 0xA4 / 255, 0x8E / 255),
    (0xE5 / 255, 0xA5 / 255, 0x0A / 255),
]


def _rounded_rect(cr, x, y, w, h, r) -> None:
    r = max(0.0, min(r, w / 2, h / 2))
    if r <= 0:
        cr.rectangle(x, y, w, h)
        return
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    cr.close_path()


def _top_rounded(cr, x, y, w, h, r) -> None:
    r = max(0.0, min(r, w / 2, h))
    cr.new_sub_path()
    cr.move_to(x, y + h)
    cr.line_to(x, y + r)
    cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.line_to(x + w, y + h)
    cr.close_path()


def _nice_max(v: float) -> float:
    if v <= 0:
        return 1.0
    exp = 10 ** math.floor(math.log10(v))
    for m in (1, 2, 2.5, 5, 10):
        if v <= m * exp:
            return m * exp
    return 10 * exp


class _Chart(Gtk.DrawingArea):
    def __init__(self, height: int) -> None:
        super().__init__(content_height=height, hexpand=True)
        self._hover: int | None = None
        self.set_draw_func(self._draw)
        motion = Gtk.EventControllerMotion()
        motion.connect("motion", self._on_motion)
        motion.connect("leave", self._on_leave)
        self.add_controller(motion)
        self.set_has_tooltip(True)
        self.connect("query-tooltip", self._on_query_tooltip)

    def _layout(self, cr, text: str, small: bool = True, bold: bool = False):
        layout = PangoCairo.create_layout(cr)
        desc = self.get_pango_context().get_font_description().copy()
        if small:
            desc.set_size(int(desc.get_size() * 0.82))
        if bold:
            desc.set_weight(Pango.Weight.BOLD)
        layout.set_font_description(desc)
        layout.set_text(text, -1)
        return layout

    def _hit(self, x: float, y: float) -> int | None:  # pragma: no cover - override
        return None

    def _tooltip(self, idx: int) -> str | None:  # pragma: no cover - override
        return None

    def _on_motion(self, _c, x, y) -> None:
        idx = self._hit(x, y)
        if idx != self._hover:
            self._hover = idx
            self.queue_draw()
            self.trigger_tooltip_query()

    def _on_leave(self, _c) -> None:
        if self._hover is not None:
            self._hover = None
            self.queue_draw()

    def _on_query_tooltip(self, _w, x, y, _kb, tooltip) -> bool:
        idx = self._hit(x, y)
        if idx is None:
            return False
        text = self._tooltip(idx)
        if not text:
            return False
        tooltip.set_markup(text)
        return True

    def _draw(self, _a, cr, w, h) -> None:  # pragma: no cover - override
        pass


class StackedBarChart(_Chart):
    """Daily stacked bars. ``set_data(labels, series_names, values[n][k])``."""

    def __init__(self, height: int = 220) -> None:
        super().__init__(height)
        self._labels: list[str] = []
        self._series: list[str] = []
        self._values: list[list[float]] = []
        self._geom: list[tuple[float, float]] = []
        self._plot = (0.0, 0.0, 0.0, 0.0)

    def set_data(self, labels: list[str], series: list[str], values: list[list[float]]) -> None:
        self._labels, self._series, self._values = labels, series, values
        self._hover = None
        self.queue_draw()

    def _hit(self, x, y):
        for i, (x0, x1) in enumerate(self._geom):
            if x0 - 1 <= x <= x1 + 1:
                return i
        return None

    def _tooltip(self, i):
        if i >= len(self._values):
            return None
        vals = self._values[i]
        lines = [f"<b>{self._labels[i]}</b>  ·  {fmt.tokens(sum(vals))} tokens"]
        for name, v in zip(self._series, vals):
            lines.append(f"{name}: {fmt.tokens(v)}")
        return "\n".join(lines)

    def _draw(self, _a, cr, w, h) -> None:
        fr, fg, fb, _ = fg_rgba(self)
        n = len(self._values)
        totals = [sum(v) for v in self._values] or [0]
        ymax = _nice_max(max(totals) if totals else 0)
        widest = max(self._layout(cr, fmt.tokens(ymax * k / 4)).get_pixel_size()[0] for k in range(5))
        left, bottom, top = widest + 12.0, 22.0, 8.0
        pw, ph = w - left - 4, h - bottom - top
        # grid + y labels
        cr.set_line_width(1)
        for k in range(5):
            y = top + ph - ph * k / 4
            cr.set_source_rgba(fr, fg, fb, 0.07 if k else 0.16)
            cr.move_to(left, round(y) + 0.5)
            cr.line_to(w - 4, round(y) + 0.5)
            cr.stroke()
            lay = self._layout(cr, fmt.tokens(ymax * k / 4))
            tw, th = lay.get_pixel_size()
            cr.set_source_rgba(fr, fg, fb, 0.55)
            cr.move_to(left - 6 - tw, y - th / 2)
            PangoCairo.show_layout(cr, lay)
        self._geom = []
        if n == 0:
            return
        slot = pw / n
        bw = max(2.0, min(28.0, slot * 0.68))
        step = max(1, math.ceil(n / max(1, pw / 64)))
        for i, vals in enumerate(self._values):
            cx = left + slot * i + slot / 2
            x0 = cx - bw / 2
            self._geom.append((left + slot * i, left + slot * (i + 1)))
            hovered = self._hover == i
            dim = self._hover is not None and not hovered
            if hovered:
                cr.set_source_rgba(fr, fg, fb, 0.06)
                _rounded_rect(cr, left + slot * i, top, slot, ph, 6)
                cr.fill()
            y = top + ph
            total = sum(vals)
            nonzero = [k for k, v in enumerate(vals) if v > 0]
            for k, v in enumerate(vals):
                if v <= 0:
                    continue
                bh = ph * v / ymax
                r, g, b = SERIES[k % len(SERIES)]
                cr.set_source_rgba(r, g, b, 0.45 if dim else 1.0)
                if k == nonzero[-1]:
                    _top_rounded(cr, x0, y - bh, bw, bh, min(4, bw / 2))
                else:
                    cr.rectangle(x0, y - bh, bw, bh)
                cr.fill()
                y -= bh
            if total == 0:
                cr.set_source_rgba(fr, fg, fb, 0.12)
                cr.rectangle(x0, top + ph - 1.5, bw, 1.5)
                cr.fill()
            if i % step == 0 or hovered:
                lay = self._layout(cr, self._labels[i], bold=hovered)
                tw, _ = lay.get_pixel_size()
                cr.set_source_rgba(fr, fg, fb, 0.9 if hovered else 0.55)
                cr.move_to(max(left - 4, min(w - tw - 2, cx - tw / 2)), top + ph + 5)
                PangoCairo.show_layout(cr, lay)


class HBarChart(_Chart):
    """Horizontal ranked bars. ``set_data([(label, value, value_text)])``."""

    ROW = 30

    def __init__(self, color=BRAND, max_rows: int = 10) -> None:
        super().__init__(self.ROW * 3)
        self._rows: list[tuple[str, float, str]] = []
        self._color = color
        self._max_rows = max_rows

    def set_data(self, rows: list[tuple[str, float, str]]) -> None:
        self._rows = rows[: self._max_rows]
        self.set_content_height(max(self.ROW, self.ROW * len(self._rows)) + 4)
        self.queue_draw()

    def _hit(self, x, y):
        i = int((y - 2) // self.ROW)
        return i if 0 <= i < len(self._rows) else None

    def _tooltip(self, i):
        lbl, _v, txt = self._rows[i]
        return f"<b>{GLibMarkup.escape(lbl)}</b>: {txt}"

    def _draw(self, _a, cr, w, h) -> None:
        fr, fg, fb, _ = fg_rgba(self)
        if not self._rows:
            lay = self._layout(cr, "No data in this range", small=False)
            tw, th = lay.get_pixel_size()
            cr.set_source_rgba(fr, fg, fb, 0.5)
            cr.move_to((w - tw) / 2, (h - th) / 2)
            PangoCairo.show_layout(cr, lay)
            return
        label_w = min(170.0, w * 0.34)
        value_w = 64.0
        bar_x = label_w + 10
        bar_wmax = max(10.0, w - bar_x - value_w - 6)
        vmax = max(v for _, v, _ in self._rows) or 1
        r, g, b = self._color
        for i, (lbl, v, txt) in enumerate(self._rows):
            y = 2 + i * self.ROW
            hovered = self._hover == i
            if hovered:
                cr.set_source_rgba(fr, fg, fb, 0.06)
                _rounded_rect(cr, 0, y, w, self.ROW - 2, 6)
                cr.fill()
            lay = self._layout(cr, lbl, small=False, bold=hovered)
            lay.set_width(int((label_w - 8) * Pango.SCALE))
            lay.set_ellipsize(Pango.EllipsizeMode.END)
            _, th = lay.get_pixel_size()
            cr.set_source_rgba(fr, fg, fb, 0.92)
            cr.move_to(8, y + (self.ROW - 2 - th) / 2)
            PangoCairo.show_layout(cr, lay)
            # track
            cr.set_source_rgba(fr, fg, fb, 0.07)
            _rounded_rect(cr, bar_x, y + 9, bar_wmax, self.ROW - 20, 5)
            cr.fill()
            bw = max(3.0, bar_wmax * v / vmax)
            cr.set_source_rgba(r, g, b, 1.0 if hovered or self._hover is None else 0.55)
            _rounded_rect(cr, bar_x, y + 9, bw, self.ROW - 20, 5)
            cr.fill()
            lay = self._layout(cr, txt, bold=True)
            tw, th = lay.get_pixel_size()
            cr.set_source_rgba(fr, fg, fb, 0.8)
            cr.move_to(w - tw - 4, y + (self.ROW - 2 - th) / 2)
            PangoCairo.show_layout(cr, lay)


class HeatStrip(_Chart):
    """24 cells, one per hour of the day, shaded by intensity."""

    def __init__(self) -> None:
        super().__init__(64)
        self._vals: list[int] = [0] * 24
        self._cells: list[tuple[float, float]] = []

    def set_data(self, vals: list[int]) -> None:
        self._vals = (list(vals) + [0] * 24)[:24]
        self.queue_draw()

    def _hit(self, x, y):
        for i, (x0, x1) in enumerate(self._cells):
            if x0 <= x <= x1 and y <= 40:
                return i
        return None

    def _tooltip(self, i):
        return f"<b>{i:02d}:00 – {i:02d}:59</b>\n{self._vals[i]} tool calls"

    def _draw(self, _a, cr, w, h) -> None:
        fr, fg, fb, _ = fg_rgba(self)
        vmax = max(self._vals) or 1
        gap = 4.0
        cw = (w - gap * 23) / 24
        r, g, b = BRAND
        self._cells = []
        for i, v in enumerate(self._vals):
            x = i * (cw + gap)
            self._cells.append((x, x + cw))
            t = v / vmax
            if v == 0:
                cr.set_source_rgba(fr, fg, fb, 0.07)
            else:
                cr.set_source_rgba(r, g, b, 0.18 + 0.82 * t)
            _rounded_rect(cr, x, 0, cw, 36, 6)
            cr.fill()
            if self._hover == i:
                cr.set_source_rgba(fr, fg, fb, 0.75)
                cr.set_line_width(2)
                _rounded_rect(cr, x + 1, 1, cw - 2, 34, 5)
                cr.stroke()
            if i % 3 == 0:
                lay = self._layout(cr, f"{i:02d}")
                tw, _ = lay.get_pixel_size()
                cr.set_source_rgba(fr, fg, fb, 0.55)
                cr.move_to(x + cw / 2 - tw / 2, 42)
                PangoCairo.show_layout(cr, lay)


class GLibMarkup:
    @staticmethod
    def escape(text: str) -> str:
        from gi.repository import GLib
        return GLib.markup_escape_text(text)
