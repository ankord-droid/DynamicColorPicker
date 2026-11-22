"""
Дополнительные компоненты и системные функции Dynamic Color Picker:
  компоненты — Гамут-маска, Гармонии, Смешивание, Свет и тень, Тон, Палитра холста;
  система    — пипетка с экрана, профили программ, автозапуск, резервная копия, автообновление.

Модуль подключается в конце dcp_app.py; цвета темы читаются как ui.<ИМЯ> в момент отрисовки.
"""
import json
import math
import os
import subprocess
import sys
import tempfile
import threading
import urllib.request

import numpy as np
from PySide6.QtCore import Qt, QObject, Signal, QTimer, QPointF, QRectF, QPoint, QRect
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF, QPainterPath, QImage, QGuiApplication, QCursor, QFont
from PySide6.QtWidgets import QWidget, QMenu, QApplication, QLabel, QVBoxLayout, QHBoxLayout, QMessageBox, QFileDialog

import dcp_app as ui
from dcp_core import (APP_VERSION, GITHUB_REPO, APP_DIR, CONFIG_PATH, hsv2rgb, rgb2lab, lch_in_gamut, to_qcolor,
                      to_hex, from_hex, clip3, np_to_qimage, rgb2oklab, oklab2rgb, oklch_in_gamut, rgb2oklch,
                      extract_colors, qimage_rgb)
import colorsys


def _marker(p, pt, r=6):
    p.setBrush(Qt.NoBrush)
    p.setPen(QPen(QColor(0, 0, 0, 120), 3))
    p.drawEllipse(pt, r, r)
    p.setPen(QPen(QColor("#F4F6FB"), 1.8))
    p.drawEllipse(pt, r, r)


def _chip(p, r, hx, active=False, rad=6):
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(hx) if isinstance(hx, str) else hx)
    p.drawRoundedRect(r, rad, rad)
    if active:
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor("#E9EEFB"), 2))
        p.drawRoundedRect(r.adjusted(-3, -3, 3, 3), rad + 3, rad + 3)


def _label(p, r, text, color=None, align=Qt.AlignLeft | Qt.AlignVCenter, bold=False):
    p.setPen(color or ui.DIM)
    f = p.font()
    f.setBold(bold)
    p.setFont(f)
    p.drawText(r, align, text)


# ============================================================== Гамут-маска
MASKS = {
    "triangle": ("Треугольник", [(0.92, 0.0), (-0.46, 0.62), (-0.46, -0.62)]),
    "acute": ("Острый треугольник", [(0.95, 0.0), (-0.15, 0.38), (-0.15, -0.38)]),
    "diamond": ("Ромб", [(0.9, 0.0), (0.0, 0.42), (-0.62, 0.0), (0.0, -0.42)]),
    "split": ("Две зоны (дополнительные)", None),
}


class GamutComp(ui.Comp):
    """Гамут-маска по Гарни: круг оттенок × насыщенность, вне маски цвета затемнены.
    ЛКМ — выбор цвета, ПКМ-перетаскивание — сдвиг маски, колёсико — поворот, Ctrl+колёсико — размер."""
    KEY = "gamut"

    def __init__(self, app, opts=None):
        super().__init__(app, opts)
        o = self.opts
        o.setdefault("shape", "triangle")
        o.setdefault("rot", 0.0)
        o.setdefault("scale", 1.0)
        o.setdefault("ox", 0.0)
        o.setdefault("oy", 0.0)
        o.setdefault("constrain", True)
        h, s, v = colorsys.rgb_to_hsv(*self.state.color())
        self.h, self.s, self.v = h, s, v
        self._img = self._img_n = None
        self._drag = None
        self.btn = ui.IconButton("mode", self, 24, "Форма маски")
        self.btn.clicked.connect(self._menu)
        self.state.changed.connect(self._on_state)
        self.setToolTip("ЛКМ — выбрать цвет. ПКМ — двигать маску. Колёсико — повернуть, Ctrl+колёсико — размер")

    def heightFor(self, w):
        return int(w * 0.86)

    def resizeEvent(self, e):
        self.btn.move(self.width() - 26, self.height() - 24)

    def _on_state(self, src):
        if src is self:
            return
        h, s, v = colorsys.rgb_to_hsv(*self.state.color())
        if s > 1e-3 and v > 1e-3:
            self.h = h
        self.s, self.v = s, v
        self.update()

    def _menu(self):
        m = QMenu(self)
        for k, (label, _) in MASKS.items():
            a = m.addAction(("●  " if self.opts["shape"] == k else "    ") + label)
            a.triggered.connect(lambda _=False, k=k: self._set("shape", k))
        m.addSeparator()
        a = m.addAction(("✓  " if self.opts["constrain"] else "    ") + "Ограничивать выбор маской")
        a.triggered.connect(lambda: self._set("constrain", not self.opts["constrain"]))
        m.addAction("    Сбросить положение", self._reset)
        m.exec(self.btn.mapToGlobal(QPoint(0, self.btn.height())))

    def _set(self, k, v):
        self.opts[k] = v
        self.update()

    def _reset(self):
        self.opts.update(rot=0.0, scale=1.0, ox=0.0, oy=0.0)
        self.update()

    def _geo(self):
        w, h = self.width(), self.height()
        R = min(w, h) / 2 - 6
        return w / 2, h / 2, R

    def _polys(self):
        """Маска в нормализованных координатах круга (x вправо, y вверх), с учётом поворота/размера/сдвига."""
        o = self.opts
        shape = o["shape"]
        if shape == "split":
            base = MASKS["acute"][1]
            parts = [base, [(-x, -y) for x, y in base]]
        else:
            parts = [MASKS.get(shape, MASKS["triangle"])[1]]
        a = math.radians(o["rot"])
        c, s = math.cos(a), math.sin(a)
        out = []
        for pts in parts:
            out.append([((x * c - y * s) * o["scale"] + o["ox"], (x * s + y * c) * o["scale"] + o["oy"]) for x, y in pts])
        return out

    def _to_screen(self, x, y):
        cx, cy, R = self._geo()
        return QPointF(cx + x * R, cy - y * R)

    def _qpolys(self):
        return [QPolygonF([self._to_screen(x, y) for x, y in pts]) for pts in self._polys()]

    def _disk(self, R):
        n = int(2 * R)
        if n != self._img_n and n > 4:
            yy, xx = np.mgrid[0:n, 0:n] + 0.5
            dx, dy = (xx - n / 2) / (n / 2), -(yy - n / 2) / (n / 2)
            r = np.hypot(dx, dy)
            hue = ((150 - np.degrees(np.arctan2(dy, dx))) / 360) % 1
            rgb = hsv2rgb(hue, np.clip(r, 0, 1), 1.0)
            a = np.clip((1 - r) * n / 2, 0, 1)
            self._img = np_to_qimage(np.concatenate([rgb * a[..., None], a[..., None]], -1))
            self._img_n = n
        return self._img

    def _pos_hs(self, pos):
        cx, cy, R = self._geo()
        dx, dy = (pos.x() - cx) / R, -(pos.y() - cy) / R
        return dx, dy

    def _hs_pos(self):
        a = ui.hue_angle(self.h)
        return self.s * math.cos(a), self.s * math.sin(a)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        cx, cy, R = self._geo()
        disk = QRectF(cx - R, cy - R, 2 * R, 2 * R)
        img = self._disk(R)
        if img:
            p.drawImage(disk, img)
        circle = QPainterPath()
        circle.addEllipse(disk)
        maskp = QPainterPath()
        for poly in self._qpolys():
            maskp.addPolygon(poly)
            maskp.closeSubpath()
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(15, 18, 28, 185))
        p.drawPath(circle.subtracted(maskp))
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, 200), 1.6))
        p.drawPath(maskp.intersected(circle))
        x, y = self._hs_pos()
        _marker(p, self._to_screen(x, y))

    def _inside(self, x, y):
        pt = self._to_screen(x, y)
        return any(poly.containsPoint(pt, Qt.OddEvenFill) for poly in self._qpolys())

    def _clamp_to_mask(self, x, y):
        if self._inside(x, y):
            return x, y
        best, bd = (x, y), 1e9
        for pts in self._polys():
            for i in range(len(pts)):
                ax, ay = pts[i]
                bx, by = pts[(i + 1) % len(pts)]
                vx, vy = bx - ax, by - ay
                t = max(0, min(1, ((x - ax) * vx + (y - ay) * vy) / max(1e-9, vx * vx + vy * vy)))
                px, py = ax + t * vx, ay + t * vy
                d = (px - x) ** 2 + (py - y) ** 2
                if d < bd:
                    best, bd = (px, py), d
        return best

    def mousePressEvent(self, e):
        self._drag = "move" if e.button() == Qt.RightButton else "pick"
        self._last = e.position()
        self._move(e.position(), False)

    def mouseMoveEvent(self, e):
        self._move(e.position(), False)

    def mouseReleaseEvent(self, e):
        self._move(e.position(), True)
        self._drag = None

    def _move(self, pos, commit):
        if self._drag == "move":
            cx, cy, R = self._geo()
            self.opts["ox"] += (pos.x() - self._last.x()) / R
            self.opts["oy"] -= (pos.y() - self._last.y()) / R
            self._last = pos
            self.update()
            return
        if self._drag != "pick":
            return
        x, y = self._pos_hs(pos)
        r = math.hypot(x, y)
        if r > 1:
            x, y = x / r, y / r
        if self.opts["constrain"]:
            x, y = self._clamp_to_mask(x, y)
        self.s = min(1.0, math.hypot(x, y))
        if self.s > 1e-4:
            self.h = ((150 - math.degrees(math.atan2(y, x))) / 360) % 1
        v = self.v if self.v > 0.02 else 1.0
        self.state.set_color(colorsys.hsv_to_rgb(self.h, self.s, v), self, commit)
        self.update()

    def wheelEvent(self, e):
        d = (e.angleDelta().y() or e.angleDelta().x()) / 120
        if e.modifiers() & Qt.ControlModifier:
            self.opts["scale"] = min(1.6, max(0.3, self.opts["scale"] * (1.05 ** d)))
            self.update()
            e.accept()
        else:
            super().wheelEvent(e)

    def adjust(self, step, pos):
        self.opts["rot"] = (self.opts["rot"] + step * 3) % 360
        self.update()
        return True


# ============================================================== Гармонии
SCHEMES = {
    "complementary": ("Дополнительные", [0, 180]),
    "split": ("Раздельно-дополнительные", [0, 150, 210]),
    "analogous": ("Аналоговые", [-30, 0, 30]),
    "triad": ("Триада", [0, 120, 240]),
    "tetrad": ("Тетрада", [0, 60, 180, 240]),
    "square": ("Квадрат", [0, 90, 180, 270]),
}


class HarmonyComp(ui.Comp):
    """Цветовые гармонии от текущего цвета. Клик по цвету — выбрать; колёсико — повернуть схему."""
    KEY = "harmony"

    def __init__(self, app, opts=None):
        super().__init__(app, opts)
        self.opts.setdefault("scheme", "complementary")
        self.h, self.s, self.v = colorsys.rgb_to_hsv(*self.state.color())
        self.state.changed.connect(self._on_state)

    def heightFor(self, w):
        return 86

    def _on_state(self, src):
        h, s, v = colorsys.rgb_to_hsv(*self.state.color())
        if src is self:
            self.s, self.v = s, v
        else:
            if s > 1e-3 and v > 1e-3:
                self.h = h
            self.s, self.v = s, v
        self.update()

    def _colors(self):
        return [(self.h + off / 360) % 1 for off in SCHEMES[self.opts["scheme"]][1]]

    def _chips(self):
        hs = self._colors()
        x0, w = 86, self.width() - 86
        cw = min(46, (w - (len(hs) - 1) * 8) / len(hs))
        return [(QRectF(x0 + i * (cw + 8), 26, cw, 52), h) for i, h in enumerate(hs)]

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        _label(p, QRectF(86, 0, self.width() - 86, 20), SCHEMES[self.opts["scheme"]][0] + "  ▾", ui.TXT, bold=True)
        c = QPointF(38, 44)
        R = 34
        for k in range(36):
            p.setPen(QPen(QColor.fromHsvF((k / 36) % 1 * 0.9999, 1, 1), 5, Qt.SolidLine, Qt.FlatCap))
            a0 = 150 - k * 10
            p.drawArc(QRectF(c.x() - R, c.y() - R, 2 * R, 2 * R), int((a0 - 10) * 16), int(11 * 16))
        for i, hh in enumerate(self._colors()):
            a = ui.hue_angle(hh)
            pt = QPointF(c.x() + math.cos(a) * (R - 12), c.y() - math.sin(a) * (R - 12))
            p.setPen(QPen(QColor(255, 255, 255, 110), 1))
            p.drawLine(c, pt)
            p.setBrush(to_qcolor(colorsys.hsv_to_rgb(hh, max(self.s, 0.25), max(self.v, 0.35))))
            p.setPen(QPen(QColor("#F4F6FB"), 2 if i == 0 else 1.2))
            p.drawEllipse(pt, 5 if i == 0 else 4, 5 if i == 0 else 4)
        cur = to_hex(self.state.color())
        for r, hh in self._chips():
            hx = to_hex(colorsys.hsv_to_rgb(hh, self.s, self.v))
            _chip(p, r, hx, active=hx == cur)

    def mousePressEvent(self, e):
        if e.position().y() < 22 and e.position().x() > 80:
            m = QMenu(self)
            for k, (label, _) in SCHEMES.items():
                a = m.addAction(("●  " if k == self.opts["scheme"] else "    ") + label)
                a.triggered.connect(lambda _=False, k=k: (self.opts.__setitem__("scheme", k), self.update()))
            m.exec(self.mapToGlobal(QPoint(86, 22)))
            return
        for r, hh in self._chips():
            if r.contains(e.position()):
                self.state.set_color(colorsys.hsv_to_rgb(hh, self.s, self.v), None)

    def adjust(self, step, pos):
        self.h = (self.h + step / 360) % 1
        self.state.set_color(colorsys.hsv_to_rgb(self.h, self.s, self.v), self, True)
        return True


# ============================================================== Смешивание
class MixerComp(ui.Comp):
    """Смешивание в OKLab: A → (средний) → B. ЛКМ по краю — взять текущий цвет, ПКМ по краю — меню.
    Колёсико над полосой — число шагов."""
    KEY = "mixer"

    def __init__(self, app, opts=None):
        super().__init__(app, opts)
        o = self.opts
        o.setdefault("steps", 7)
        o.setdefault("a", None)      # None — живой основной цвет
        o.setdefault("b", None)      # None — живой фоновый цвет
        o.setdefault("mid", None)
        self.state.changed.connect(lambda _: self.update())
        self.setToolTip("ЛКМ по краю — взять текущий цвет. ПКМ по краю — меню. Колёсико — число шагов")

    def heightFor(self, w):
        return 54

    def _ends(self):
        a = from_hex(self.opts["a"]) if self.opts["a"] else self.state.fg
        b = from_hex(self.opts["b"]) if self.opts["b"] else self.state.bg
        return a, b

    def _steps(self):
        a, b = self._ends()
        n = self.opts["steps"]
        keys = [a] + ([from_hex(self.opts["mid"])] if self.opts["mid"] else []) + [b]
        labs = [rgb2oklab(np.array(k)) for k in keys]
        out = []
        for i in range(n):
            t = i / (n - 1) * (len(labs) - 1)
            j = min(int(t), len(labs) - 2)
            f = t - j
            out.append(to_hex(clip3(oklab2rgb(labs[j] * (1 - f) + labs[j + 1] * f))))
        return out

    def _rects(self):
        w = self.width()
        a = QRectF(0, 18, 30, 30)
        b = QRectF(w - 30, 18, 30, 30)
        n = self.opts["steps"]
        x0, x1 = 40, w - 40
        cw = (x1 - x0 - (n - 1) * 3) / n
        cells = [QRectF(x0 + i * (cw + 3), 22, cw, 22) for i in range(n)]
        return a, b, cells

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        mid = "  · средний" if self.opts["mid"] else ""
        _label(p, QRectF(0, 0, self.width(), 16), f"Смешивание (OKLab){mid}", ui.DIM)
        ra, rb, cells = self._rects()
        A, B = self._ends()
        _chip(p, ra, to_qcolor(A), rad=8)
        _chip(p, rb, to_qcolor(B), rad=8)
        for tag, r, live in (("A", ra, self.opts["a"] is None), ("B", rb, self.opts["b"] is None)):
            if live:
                p.setPen(QPen(QColor(255, 255, 255, 140), 1, Qt.DashLine))
                p.setBrush(Qt.NoBrush)
                p.drawRoundedRect(r.adjusted(1, 1, -1, -1), 7, 7)
        cur = to_hex(self.state.color())
        for r, hx in zip(cells, self._steps()):
            _chip(p, r, hx, active=hx == cur, rad=4)

    def mousePressEvent(self, e):
        ra, rb, cells = self._rects()
        pos = e.position()
        for key, r in (("a", ra), ("b", rb)):
            if r.contains(pos):
                if e.button() == Qt.RightButton:
                    self._end_menu(key, e.globalPosition().toPoint())
                else:
                    self.opts[key] = to_hex(self.state.color())
                    self.update()
                return
        for r, hx in zip(cells, self._steps()):
            if r.adjusted(-1, -4, 1, 4).contains(pos):
                if e.button() == Qt.RightButton:
                    m = QMenu(self)
                    m.addAction("Сделать средним цветом", lambda hx=hx: self._set("mid", hx))
                    m.addAction("Убрать средний цвет", lambda: self._set("mid", None))
                    m.exec(e.globalPosition().toPoint())
                else:
                    self.state.set_color(from_hex(hx), self)
                return

    def _set(self, k, v):
        self.opts[k] = v
        self.update()

    def _end_menu(self, key, gpos):
        m = QMenu(self)
        m.addAction("Взять текущий цвет", lambda: self._set(key, to_hex(self.state.color())))
        m.addAction("Следовать за " + ("основным" if key == "a" else "фоновым") + " цветом",
                    lambda: self._set(key, None))
        m.addAction("Средний цвет = текущий", lambda: self._set("mid", to_hex(self.state.color())))
        m.addAction("Убрать средний цвет", lambda: self._set("mid", None))
        m.exec(gpos)

    def adjust(self, step, pos):
        self.opts["steps"] = int(min(15, max(3, self.opts["steps"] + (1 if step > 0 else -1))))
        self.update()
        return True


# ============================================================== Свет и тень
class LightShadowComp(ui.Comp):
    """Оттенки для света (светлее, теплее) и тени (темнее, холоднее, чуть насыщеннее) в OKLCH.
    Колёсико — сила сдвига тона."""
    KEY = "light_shadow"
    WARM, COOL = 85.0, 265.0

    def __init__(self, app, opts=None):
        super().__init__(app, opts)
        self.opts.setdefault("shift", 1.0)
        self.state.changed.connect(lambda _: self.update())
        self.setToolTip("Свет — теплее и светлее, тень — холоднее и темнее. Колёсико — сила сдвига тона")

    def heightFor(self, w):
        return 72

    @staticmethod
    def _toward(h, target, deg):
        d = (target - h + 540) % 360 - 180
        return h + max(-abs(d), min(abs(d), math.copysign(deg, d)))

    def _rows(self):
        L, C, H = rgb2oklch(self.state.color())
        k = self.opts["shift"]
        lights, shadows = [], []
        for i in range(1, 5):
            lh = self._toward(H, self.WARM, 6 * i * k) if C > 0.01 else H
            lights.append(to_hex(oklch_in_gamut(min(0.99, L + 0.065 * i), C * (1 - 0.06 * i), lh)))
            sh = self._toward(H, self.COOL, 7 * i * k) if C > 0.01 else H
            shadows.append(to_hex(oklch_in_gamut(max(0.03, L - 0.075 * i), C * (1 + 0.05 * i * k), sh)))
        return lights, shadows

    def _cells(self):
        w = self.width() - 46
        cw = (w - 3 * 4 - 40) / 4
        base = QRectF(46, 18, 34, 54 - 4)
        rows = []
        for r in range(2):
            rows.append([QRectF(86 + i * (cw + 4), 18 + r * 28, cw, 22) for i in range(4)])
        return base, rows

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        _label(p, QRectF(0, 0, self.width(), 16), "Свет и тень", ui.DIM)
        _label(p, QRectF(0, 18, 44, 22), "свет")
        _label(p, QRectF(0, 46, 44, 22), "тень")
        base, rows = self._cells()
        _chip(p, base, to_qcolor(self.state.color()), rad=6)
        lights, shadows = self._rows()
        cur = to_hex(self.state.color())
        for cells, cols in zip(rows, (lights, shadows)):
            for r, hx in zip(cells, cols):
                _chip(p, r, hx, active=hx == cur, rad=4)

    def mousePressEvent(self, e):
        base, rows = self._cells()
        lights, shadows = self._rows()
        for cells, cols in zip(rows, (lights, shadows)):
            for r, hx in zip(cells, cols):
                if r.contains(e.position()):
                    self.state.set_color(from_hex(hx), self)
                    return

    def adjust(self, step, pos):
        self.opts["shift"] = round(min(3.0, max(0.0, self.opts["shift"] + 0.25 * (1 if step > 0 else -1))), 2)
        self.update()
        return True


# ============================================================== Тон
class ValueComp(ui.Comp):
    """Тональная шкала: L* текущего цвета и ступень из 5/7/9. Клик по ступени — тот же цвет в этой яркости."""
    KEY = "value"

    def __init__(self, app, opts=None):
        super().__init__(app, opts)
        self.opts.setdefault("steps", 7)
        self.state.changed.connect(lambda _: self.update())
        self.setToolTip("Клик по ступени — тот же оттенок в этой яркости. Колёсико — 5 / 7 / 9 ступеней")

    def heightFor(self, w):
        return 54

    def _lch(self):
        L, a, b = rgb2lab(np.array(self.state.color()))
        return float(L), math.hypot(a, b), math.degrees(math.atan2(b, a))

    def _cells(self):
        n = self.opts["steps"]
        x0, w = 58, self.width() - 58
        cw = (w - (n - 1) * 3) / n
        return [QRectF(x0 + i * (cw + 3), 26, cw, 24) for i in range(n)]

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        L, C, H = self._lch()
        n = self.opts["steps"]
        idx = min(n - 1, int(L / 100 * n))
        g = lch_in_gamut(L, 0, 0)
        _chip(p, QRectF(0, 4, 24, 46), to_qcolor(self.state.color()), rad=6)
        _chip(p, QRectF(28, 4, 24, 46), to_qcolor(g), rad=6)
        _label(p, QRectF(58, 2, self.width() - 58, 20), f"L* {L:.0f}  ·  ступень {idx + 1} из {n}", ui.TXT, bold=True)
        for i, r in enumerate(self._cells()):
            Li = (i + 0.5) / n * 100
            _chip(p, r, to_qcolor(lch_in_gamut(Li, 0, 0)), active=(i == idx), rad=4)
        x = 58 + L / 100 * (self.width() - 58)
        p.setPen(QPen(ui.ACCENT, 2))
        p.drawLine(QPointF(x, 22), QPointF(x, 52))

    def mousePressEvent(self, e):
        L, C, H = self._lch()
        n = self.opts["steps"]
        for i, r in enumerate(self._cells()):
            if r.contains(e.position()):
                self.state.set_color(lch_in_gamut((i + 0.5) / n * 100, C, H), self)

    def adjust(self, step, pos):
        order = [5, 7, 9]
        i = order.index(self.opts["steps"]) if self.opts["steps"] in order else 1
        self.opts["steps"] = order[max(0, min(2, i + (1 if step > 0 else -1)))]
        self.update()
        return True


# ============================================================== экран: захват и пипетка
def grab_rect(rect):
    """Снимок прямоугольника экрана (глобальные логические координаты) -> QImage."""
    scr = QGuiApplication.screenAt(rect.center()) or QGuiApplication.primaryScreen()
    g = scr.geometry()
    return scr.grabWindow(0, rect.x() - g.x(), rect.y() - g.y(), rect.width(), rect.height()).toImage()


def color_under_cursor():
    pos = QCursor.pos()
    img = grab_rect(QRect(pos.x() - 1, pos.y() - 1, 3, 3))
    if img.isNull():
        return None
    arr = qimage_rgb(img).reshape(-1, 3)
    return tuple(float(x) for x in arr.mean(0))


class ScreenOverlay(QWidget):
    """Полноэкранный оверлей на одном мониторе: пипетка с лупой или выбор области."""

    def __init__(self, ctl, screen, mode):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.ctl, self.scr, self.mode = ctl, screen, mode
        self.shot = screen.grabWindow(0)
        self.img = self.shot.toImage()
        self.setGeometry(screen.geometry())
        self.setCursor(Qt.CrossCursor)
        self.setMouseTracking(True)
        self._a = self._b = None
        self._pos = QPoint(-100, -100)

    def _px(self, pos):
        dpr = self.shot.devicePixelRatio() or 1.0
        x = int(min(self.img.width() - 1, max(0, pos.x() * dpr)))
        y = int(min(self.img.height() - 1, max(0, pos.y() * dpr)))
        return x, y

    def _color_at(self, pos):
        x, y = self._px(pos)
        acc = np.zeros(3)
        n = 0
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                xx, yy = x + dx, y + dy
                if 0 <= xx < self.img.width() and 0 <= yy < self.img.height():
                    c = self.img.pixelColor(xx, yy)
                    acc += (c.redF(), c.greenF(), c.blueF())
                    n += 1
        return tuple(float(v) for v in acc / max(1, n))

    def paintEvent(self, e):
        p = QPainter(self)
        p.drawPixmap(0, 0, self.shot)
        p.fillRect(self.rect(), QColor(0, 0, 0, 40 if self.mode == "pick" else 90))
        p.setRenderHint(QPainter.Antialiasing)
        if self.mode == "rect":
            if self._a and self._b:
                r = QRect(self._a, self._b).normalized()
                dpr = self.shot.devicePixelRatio() or 1.0
                p.drawPixmap(r, self.shot, QRectF(r.x() * dpr, r.y() * dpr, r.width() * dpr, r.height() * dpr))
                p.setPen(QPen(ui.ACCENT, 2))
                p.drawRect(r)
            p.setPen(QColor("white"))
            p.drawText(QRectF(0, 20, self.width(), 30), Qt.AlignCenter,
                       "Обведите холст — из этой области будет собираться палитра.  Esc — отмена")
            return
        # лупа
        pos = self._pos
        x, y = self._px(pos)
        zoom, cells = 9, 13
        src = QRectF(x - cells // 2, y - cells // 2, cells, cells)
        size = zoom * cells
        lp = QRectF(pos.x() + 24, pos.y() + 24, size, size)
        if lp.right() > self.width():
            lp.moveRight(pos.x() - 24)
        if lp.bottom() > self.height() - 40:
            lp.moveBottom(pos.y() - 24)
        clip = QPainterPath()
        clip.addEllipse(lp)
        p.save()
        p.setClipPath(clip)
        p.drawImage(lp, self.img, src)
        p.restore()
        p.setPen(QPen(QColor("white"), 3))
        p.drawEllipse(lp)
        c = lp.center()
        p.setPen(QPen(QColor(0, 0, 0, 200), 1))
        p.setBrush(Qt.NoBrush)
        p.drawRect(QRectF(c.x() - zoom / 2, c.y() - zoom / 2, zoom, zoom))
        col = self._color_at(pos)
        tag = QRectF(lp.left() + size / 2 - 50, lp.bottom() + 6, 100, 24)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(20, 24, 36, 230))
        p.drawRoundedRect(tag, 8, 8)
        p.setBrush(to_qcolor(col))
        p.drawRoundedRect(QRectF(tag.left() + 4, tag.top() + 4, 16, 16), 4, 4)
        p.setPen(QColor("white"))
        p.drawText(tag.adjusted(24, 0, 0, 0), Qt.AlignVCenter | Qt.AlignLeft, to_hex(col))

    def mouseMoveEvent(self, e):
        self._pos = e.position().toPoint()
        if self.mode == "rect" and self._a:
            self._b = self._pos
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.RightButton:
            self.ctl.finish(None)
            return
        if self.mode == "pick":
            self.ctl.finish(self._color_at(e.position().toPoint()))
        else:
            self._a = self._b = e.position().toPoint()

    def mouseReleaseEvent(self, e):
        if self.mode == "rect" and self._a:
            r = QRect(self._a, e.position().toPoint()).normalized()
            if r.width() > 20 and r.height() > 20:
                self.ctl.finish(r.translated(self.scr.geometry().topLeft()))
            else:
                self._a = self._b = None
                self.update()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.ctl.finish(None)


class ScreenPicker(QObject):
    """Оверлеи на всех мониторах. finished(result): цвет (r,g,b) / QRect / None."""
    finished = Signal(object)

    def __init__(self, panel, mode):
        super().__init__(panel)
        self.panel, self.mode = panel, mode
        self.was_visible = panel.isVisible()
        panel.hide()
        QTimer.singleShot(120, self._open)

    def _open(self):
        self.wins = [ScreenOverlay(self, s, self.mode) for s in QGuiApplication.screens()]
        for w in self.wins:
            w.show()
        cur = QCursor.pos()
        for w in self.wins:
            if w.geometry().contains(cur):
                w.activateWindow()
                w.raise_()
                w._pos = w.mapFromGlobal(cur)

    def finish(self, result):
        for w in getattr(self, "wins", []):
            w.close()
            w.deleteLater()
        if self.was_visible:
            self.panel.show()
        self.finished.emit(result)
        self.deleteLater()


# ============================================================== Палитра холста
class CanvasComp(ui.Comp):
    """Цвета, уже использованные в работе: снимок выбранной области холста → k-means."""
    KEY = "canvas"
    CELL, GAP = 22, 5

    def __init__(self, app, opts=None):
        super().__init__(app, opts)
        self.opts.setdefault("count", 16)
        self.cols = list(app.cfg.get("canvas_colors", []))
        self.btn_scan = ui.IconButton("refresh", self, 22, "Обновить палитру холста")
        self.btn_scan.clicked.connect(self.scan)
        self.btn_area = ui.IconButton("area", self, 22, "Выбрать область холста")
        self.btn_area.clicked.connect(self.pick_area)
        self.btn_save = ui.IconButton("save", self, 22, "Сохранить как набор цветов")
        self.btn_save.clicked.connect(self._save)
        app.canvasUpdated.connect(self._set)
        self.setToolTip("ЛКМ — выбрать цвет. Колёсико — количество цветов")

    def _set(self, cols):
        self.cols = list(cols)
        self.app.relayout()
        self.update()

    def resizeEvent(self, e):
        w = self.width()
        self.btn_save.move(w - 22, 0)
        self.btn_scan.move(w - 48, 0)
        self.btn_area.move(w - 74, 0)

    def _ncols(self):
        return max(1, int((self.width() + self.GAP) // (self.CELL + self.GAP)))

    def heightFor(self, w):
        cols = max(1, int((w + self.GAP) // (self.CELL + self.GAP)))
        rows = max(1, math.ceil(len(self.cols) / cols))
        return 26 + rows * (self.CELL + self.GAP)

    def _cells(self):
        n = self._ncols()
        return [QRectF((i % n) * (self.CELL + self.GAP), 26 + (i // n) * (self.CELL + self.GAP), self.CELL, self.CELL)
                for i in range(len(self.cols))]

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        _label(p, QRectF(0, 0, self.width() - 80, 22), "Палитра холста", ui.TXT, bold=True)
        if not self.cols:
            _label(p, QRectF(0, 26, self.width(), self.CELL), "⟳ — снять цвета с холста", ui.DIM)
        cur = to_hex(self.state.color())
        for r, hx in zip(self._cells(), self.cols):
            _chip(p, r, hx, active=hx == cur, rad=5)

    def mousePressEvent(self, e):
        for r, hx in zip(self._cells(), self.cols):
            if r.contains(e.position()):
                self.state.set_color(from_hex(hx), self)

    def adjust(self, step, pos):
        self.opts["count"] = int(min(32, max(4, self.opts["count"] + (2 if step > 0 else -2))))
        self.app.cfg["canvas_count"] = self.opts["count"]
        self.scan()
        return True

    def scan(self):
        self.app.scan_canvas(self.opts["count"])

    def pick_area(self):
        self.app.pick_canvas_area(self.opts["count"])

    def _save(self):
        if self.cols:
            name = "Холст"
            k = 2
            while name in self.state.palettes:
                name, k = f"Холст {k}", k + 1
            self.state.palettes[name] = list(self.cols)
            self.state.current_palette = name
            self.state.palettesChanged.emit()


# ============================================================== Windows: активная программа, автозапуск
def foreground_exe():
    """(имя exe в нижнем регистре, hwnd, rect) активного окна; на не-Windows — (None, None, None)."""
    if sys.platform != "win32":
        return None, None, None
    import ctypes
    from ctypes import wintypes
    u32, k32 = ctypes.windll.user32, ctypes.windll.kernel32
    hwnd = u32.GetForegroundWindow()
    if not hwnd:
        return None, None, None
    pid = wintypes.DWORD()
    u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if pid.value == os.getpid():
        return "__self__", hwnd, None
    h = k32.OpenProcess(0x1000, False, pid.value)
    name = None
    if h:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(1024)
        if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            name = os.path.basename(buf.value).lower()
        k32.CloseHandle(h)
    r = wintypes.RECT()
    u32.GetWindowRect(hwnd, ctypes.byref(r))
    return name, hwnd, QRect(r.left, r.top, r.right - r.left, r.bottom - r.top)


RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def autostart_command():
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    script = os.path.abspath(sys.argv[0])
    return f'"{pyw if os.path.exists(pyw) else sys.executable}" "{script}"'


def autostart_enabled():
    if sys.platform != "win32":
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, "DynamicColorPicker")
            return True
    except OSError:
        return False


def set_autostart(on):
    if sys.platform != "win32":
        return
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if on:
            winreg.SetValueEx(k, "DynamicColorPicker", 0, winreg.REG_SZ, autostart_command())
        else:
            try:
                winreg.DeleteValue(k, "DynamicColorPicker")
            except OSError:
                pass


class AppWatcher(QObject):
    """Следит за активной программой: переключает панель по профилю, помнит последнее «чужое» окно."""
    appChanged = Signal(str)

    def __init__(self, parent):
        super().__init__(parent)
        self.last_exe = None
        self.last_rect = None
        self.t = QTimer(self, interval=700)
        self.t.timeout.connect(self._tick)
        if sys.platform == "win32":
            self.t.start()

    def _tick(self):
        try:
            exe, hwnd, rect = foreground_exe()
        except Exception:
            return
        if not exe or exe == "__self__":
            return
        self.last_rect = rect
        if exe != self.last_exe:
            self.last_exe = exe
            self.appChanged.emit(exe)


# ============================================================== резервная копия
BACKUP_SKIP = {"canvas_colors"}


def export_settings(panel, path):
    panel.save()
    cfg = json.load(open(CONFIG_PATH, encoding="utf-8"))
    data = {"app": "Dynamic Color Picker", "version": APP_VERSION,
            "config": {k: v for k, v in cfg.items() if k not in BACKUP_SKIP}}
    json.dump(data, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def import_settings(path):
    data = json.load(open(path, encoding="utf-8"))
    cfg = data.get("config") if isinstance(data, dict) else None
    if not isinstance(cfg, dict) or "layouts" not in cfg:
        raise ValueError("файл не похож на резервную копию Dynamic Color Picker")
    os.makedirs(APP_DIR, exist_ok=True)
    json.dump(cfg, open(CONFIG_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def restart_app():
    if getattr(sys, "frozen", False):
        subprocess.Popen([sys.executable])
    else:
        subprocess.Popen([sys.executable] + sys.argv)
    QApplication.quit()


# ============================================================== автообновление
def _ver(s):
    s = (s or "").lstrip("vV")
    out = []
    for part in s.split("."):
        num = "".join(ch for ch in part if ch.isdigit())
        out.append(int(num) if num else 0)
    return tuple(out + [0] * (3 - len(out)))


def installed_mode():
    if not getattr(sys, "frozen", False):
        return False
    base = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "DynamicColorPicker").lower()
    return os.path.dirname(sys.executable).lower() == base


class Updater(QObject):
    """Проверяет GitHub Releases, скачивает и ставит новую версию."""
    available = Signal(dict)
    status = Signal(str)
    downloaded = Signal(str)

    API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"

    def check(self, manual=False):
        threading.Thread(target=self._check, args=(manual,), daemon=True).start()

    def _check(self, manual):
        try:
            req = urllib.request.Request(self.API, headers={"Accept": "application/vnd.github+json",
                                                            "User-Agent": "DynamicColorPicker"})
            data = json.load(urllib.request.urlopen(req, timeout=10))
        except Exception as e:
            if manual:
                self.status.emit(f"Не удалось проверить обновления: {e}")
            return
        tag = data.get("tag_name", "")
        if _ver(tag) > _ver(APP_VERSION):
            self.available.emit(data)
        elif manual:
            self.status.emit(f"Установлена последняя версия ({APP_VERSION}).")

    def download(self, release):
        threading.Thread(target=self._download, args=(release,), daemon=True).start()

    def _download(self, release):
        assets = release.get("assets", [])
        want_setup = installed_mode()
        pick = None
        for a in assets:
            n = a["name"].lower()
            if n.endswith(".exe") and (("setup" in n) == want_setup):
                pick = a
                break
        pick = pick or next((a for a in assets if a["name"].lower().endswith(".exe")), None)
        if not pick:
            self.status.emit("В релизе нет exe-файла.")
            return
        try:
            dst = os.path.join(tempfile.gettempdir(), pick["name"])
            req = urllib.request.Request(pick["browser_download_url"], headers={"User-Agent": "DynamicColorPicker"})
            with urllib.request.urlopen(req, timeout=120) as r, open(dst, "wb") as f:
                while True:
                    chunk = r.read(1 << 16)
                    if not chunk:
                        break
                    f.write(chunk)
        except Exception as e:
            self.status.emit(f"Ошибка загрузки: {e}")
            return
        self.downloaded.emit(dst)

    @staticmethod
    def install(path):
        """Установщик — тихая установка; портативный exe — подмена файла после выхода."""
        if "setup" in os.path.basename(path).lower():
            subprocess.Popen([path, "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART"])
        else:
            exe = sys.executable
            bat = os.path.join(tempfile.gettempdir(), "dcp_update.bat")
            with open(bat, "w", encoding="cp866", errors="ignore") as f:
                f.write(f'@echo off\r\n:wait\r\ntimeout /t 1 /nobreak >nul\r\n'
                        f'move /y "{path}" "{exe}" >nul 2>&1 || goto wait\r\n'
                        f'start "" "{exe}"\r\ndel "%~f0"\r\n')
            subprocess.Popen(["cmd", "/c", bat], creationflags=0x08000000)
        QApplication.quit()


# ============================================================== регистрация компонентов
ui.EXTRA_COMPONENTS.update({
    "gamut": GamutComp, "harmony": HarmonyComp, "mixer": MixerComp,
    "light_shadow": LightShadowComp, "value": ValueComp, "canvas": CanvasComp,
})
ui.COMPONENTS.insert(1, ("Color Tools", [
    ("gamut", "Gamut Mask", "△"), ("harmony", "Harmony", "✣"), ("mixer", "Mixer", "⇄"),
    ("light_shadow", "Light & Shadow", "☀"), ("value", "Value Scale", "▤"), ("canvas", "Canvas Colors", "▣"),
]))
