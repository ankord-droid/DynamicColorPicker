#!/usr/bin/env python3
"""
Dynamic Color Picker — плавающая модульная панель цвета для Clip Studio Paint и Photoshop.

Зависимости:  pip install PySide6 numpy
Опционально:  opencv-python (QR CSP с экрана), pynput (всплытие у пера), pywin32 (Photoshop)
Запуск:       python dynamic_color_picker.py
"""
import sys, os, json, math, copy

import numpy as np
from PySide6.QtCore import Qt, Signal, QObject, QTimer, QPointF, QRectF, QPoint, QMimeData, QSize
from PySide6.QtGui import (QColor, QPainter, QImage, QPen, QBrush, QLinearGradient, QCursor, QAction,
                           QDrag, QGuiApplication, QPainterPath, QPixmap, QIcon, QFont, QConicalGradient)
from PySide6.QtWidgets import (QApplication, QWidget, QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
                               QPushButton, QAbstractButton, QMenu, QScrollArea, QStackedWidget, QSlider,
                               QSpinBox, QFileDialog, QInputDialog, QMessageBox, QLineEdit, QCheckBox,
                               QSystemTrayIcon, QFormLayout, QSizePolicy, QFrame)

from dcp_core import *          # цветовая математика, ColorState, палитры, CSPLink
import csp_companion as cspc

# ============================================================== theme
CARD = QColor("#1D2333")
CARD2 = QColor("#283044")
TAB_OFF = QColor("#141927")
LINE = QColor("#323B55")
TXT = QColor("#C9D1E4")
DIM = QColor("#7B859E")
ACCENT = QColor("#2F6BFF")
TABW, SHADOW, PAD, HEADER = 26, 12, 14, 44
SCALES = {"S": 252, "M": 296, "L": 352}

QSS = """
* { color:#C9D1E4; font-family:'Segoe UI','Inter',sans-serif; font-size:9pt; }
QMenu { background:#1E2434; border:1px solid #333C55; border-radius:8px; padding:5px; }
QMenu::item { padding:6px 22px 6px 14px; border-radius:5px; }
QMenu::item:selected { background:#2F6BFF; color:white; }
QMenu::item:disabled { color:#5A6380; }
QMenu::separator { height:1px; background:#333C55; margin:4px 8px; }
QMenu::indicator { width:0; }
QToolTip { background:#1E2434; color:#C9D1E4; border:1px solid #333C55; padding:4px; }
QPushButton#pill { background:#262D40; border:none; border-radius:8px; padding:9px 12px; text-align:left; }
QPushButton#pill:hover { background:#2F3852; }
QPushButton#pill:disabled { color:#565F7C; background:#20263A; }
QPushButton#primary { background:#2F6BFF; color:white; border:none; border-radius:8px; padding:9px; font-weight:600; }
QPushButton#primary:hover { background:#4A7DFF; }
QPushButton#ghost { background:#262D40; border:none; border-radius:8px; padding:9px; }
QPushButton#ghost:hover { background:#2F3852; }
QPushButton#tab { background:transparent; border:none; border-bottom:2px solid transparent; padding:8px 4px; color:#7B859E; font-weight:600; }
QPushButton#tab:checked { color:white; border-bottom:2px solid #2F6BFF; }
QPushButton#link { background:transparent; border:none; color:#C9D1E4; font-weight:600; text-align:left; padding:4px 0; }
QLabel#head { color:#7B859E; font-size:8pt; padding-top:6px; }
QLabel#title { color:white; font-weight:600; }
QSlider::groove:horizontal { height:6px; background:#2A3146; border-radius:3px; }
QSlider::sub-page:horizontal { background:#2F6BFF; border-radius:3px; }
QSlider::handle:horizontal { background:white; width:14px; height:14px; margin:-4px 0; border-radius:7px; }
QLineEdit, QSpinBox { background:#262D40; border:1px solid #333C55; border-radius:6px; padding:4px 6px; }
QScrollArea { background:transparent; border:none; }
QScrollArea > QWidget > QWidget { background:transparent; }
QScrollBar:vertical { width:6px; background:transparent; margin:0; }
QScrollBar::handle:vertical { background:#3A4360; border-radius:3px; min-height:30px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height:0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background:transparent; }
QCheckBox::indicator { width:14px; height:14px; border-radius:4px; background:#262D40; border:1px solid #3A4360; }
QCheckBox::indicator:checked { background:#2F6BFF; border-color:#2F6BFF; }
"""


def card_path(r, radius=16):
    path = QPainterPath()
    path.addRoundedRect(r, radius, radius)
    return path


def paint_card(p, r, radius=16, glow=True):
    """Тёмная карточка с мягкой тенью и синей подсветкой верхнего края (как у TourBox)."""
    p.setPen(Qt.NoPen)
    for i in range(SHADOW, 0, -2):
        p.setBrush(QColor(0, 0, 0, int(7 * (SHADOW - i + 2) / 2)))
        p.drawRoundedRect(r.adjusted(-i, -i + 3, i, i + 3), radius + i, radius + i)
    g = QLinearGradient(r.topLeft(), r.bottomLeft())
    g.setColorAt(0, QColor("#202739"))
    g.setColorAt(1, CARD)
    p.setBrush(g)
    p.drawRoundedRect(r, radius, radius)
    if glow:
        eg = QLinearGradient(r.topLeft(), QPointF(r.left(), r.top() + r.height() * 0.35))
        eg.setColorAt(0, QColor(70, 130, 255, 230))
        eg.setColorAt(1, QColor(70, 130, 255, 0))
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QBrush(eg), 1.6))
        p.drawRoundedRect(r.adjusted(0.8, 0.8, -0.8, -0.8), radius, radius)
    p.setPen(QPen(QColor(255, 255, 255, 14), 1))
    p.setBrush(Qt.NoBrush)
    p.drawRoundedRect(r, radius, radius)


def draw_bar(p, r, stops, t, knob="round"):
    """Тонкий скруглённый градиент с ручкой."""
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    g = QLinearGradient(r.topLeft(), r.topRight())
    for i, c in enumerate(stops):
        g.setColorAt(i / max(1, len(stops) - 1), c)
    p.setPen(Qt.NoPen)
    p.setBrush(g)
    p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
    x = r.left() + t * r.width()
    cy = r.center().y()
    if knob == "round":
        p.setBrush(QColor(0, 0, 0, 90))
        p.drawEllipse(QPointF(x, cy + 1), 8, 8)
        p.setBrush(QColor("#F4F6FB"))
        p.drawEllipse(QPointF(x, cy), 7, 7)
        p.setBrush(QColor("#B9C1D6"))
        p.drawEllipse(QPointF(x, cy), 3, 3)
    else:
        kr = QRectF(x - 6, r.top() - 4, 12, r.height() + 8)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(0, 0, 0, 120), 3))
        p.drawRoundedRect(kr, 3, 3)
        p.setPen(QPen(QColor("#F4F6FB"), 2))
        p.drawRoundedRect(kr, 3, 3)
    p.restore()


def draw_compare(p, pos, new, old, bounds):
    """Кружок «было / стало» рядом с пером во время выбора."""
    r = 17
    c = QPointF(min(max(pos.x() - 38, r + 2), bounds.width() - r - 2),
                min(max(pos.y() - 38, r + 2), bounds.height() - r - 2))
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(0, 0, 0, 110))
    p.drawEllipse(c + QPointF(0, 1.5), r + 3, r + 3)
    rect = QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r)
    p.setBrush(to_qcolor(new))
    p.drawPie(rect, 0, 180 * 16)
    p.setBrush(to_qcolor(old))
    p.drawPie(rect, 180 * 16, 180 * 16)
    p.setPen(QPen(QColor("#F4F6FB"), 2.5))
    p.setBrush(Qt.NoBrush)
    p.drawEllipse(rect)
    p.restore()


# ============================================================== icon button
class IconButton(QAbstractButton):
    def __init__(self, kind, parent=None, size=24, tip=""):
        super().__init__(parent)
        self.kind = kind
        self.setFixedSize(size, size)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(tip)
        self._hover = False

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        if self._hover:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(255, 255, 255, 18))
            p.drawRoundedRect(QRectF(0, 0, w, h), 6, 6)
        col = ACCENT if self.isChecked() else (QColor("#E3E8F5") if self._hover else QColor("#AEB7CC"))
        pen = QPen(col, 1.8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        p.setPen(pen)
        cx, cy = w / 2, h / 2
        k = self.kind
        if k == "menu":
            for dy in (-5, 0, 5):
                p.drawLine(QPointF(cx - 7, cy + dy), QPointF(cx + 7, cy + dy))
        elif k == "pin":
            p.save()
            p.translate(cx, cy)
            p.rotate(35)
            p.setBrush(col)
            path = QPainterPath()
            path.moveTo(-4, -8)
            path.lineTo(4, -8)
            path.lineTo(3, -3)
            path.lineTo(6, 1)
            path.lineTo(-6, 1)
            path.lineTo(-3, -3)
            path.closeSubpath()
            p.drawPath(path)
            p.drawLine(QPointF(0, 1), QPointF(0, 9))
            p.restore()
        elif k == "mode":
            p.drawEllipse(QPointF(cx - 2, cy), 6, 6)
            p.drawRect(QRectF(cx - 5, cy - 3, 6, 6))
            p.setBrush(col)
            p.setPen(Qt.NoPen)
            tri = QPainterPath()
            tri.moveTo(cx + 6, cy - 1)
            tri.lineTo(cx + 10, cy - 1)
            tri.lineTo(cx + 8, cy + 2)
            p.drawPath(tri)
        elif k == "luma":
            path = QPainterPath()
            path.moveTo(cx - 8, cy + 2)
            path.lineTo(cx + 8, cy + 2)
            path.lineTo(cx + 5, cy + 7)
            path.lineTo(cx - 5, cy + 7)
            path.closeSubpath()
            p.drawPath(path)
            p.drawLine(QPointF(cx - 1, cy + 2), QPointF(cx - 1, cy - 8))
            sail = QPainterPath()
            sail.moveTo(cx, cy - 7)
            sail.quadTo(cx + 7, cy - 2, cx + 6, cy)
            sail.lineTo(cx, cy)
            p.drawPath(sail)
        elif k == "close":
            p.drawLine(QPointF(cx - 5, cy - 5), QPointF(cx + 5, cy + 5))
            p.drawLine(QPointF(cx + 5, cy - 5), QPointF(cx - 5, cy + 5))
        elif k == "minus":
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#3A4360") if not self._hover else QColor("#E5484D"))
            p.drawEllipse(QPointF(cx, cy), w / 2 - 1, h / 2 - 1)
            p.setPen(QPen(QColor("white"), 1.8, cap=Qt.RoundCap))
            p.drawLine(QPointF(cx - 4, cy), QPointF(cx + 4, cy))
        elif k == "edit":
            p.drawLine(QPointF(cx - 5, cy + 5), QPointF(cx + 5, cy - 5))
            p.drawLine(QPointF(cx - 6, cy + 6), QPointF(cx - 3, cy + 6))


# ============================================================== components
class Comp(QWidget):
    KEY = ""

    def __init__(self, app, opts=None):
        super().__init__()
        self.app, self.state, self.opts = app, app.state, dict(opts or {})

    def heightFor(self, w):
        return 40


def hue_angle(h):
    """Экранный угол (рад, против часовой) для оттенка: жёлтый сверху, оттенки по часовой стрелке."""
    return math.radians(150 - h * 360)


def angle_hue(a):
    return ((150 - math.degrees(a)) / 360) % 1


class WheelComp(Comp):
    """Кольцо оттенков + квадрат (HSV / V-HSV) или треугольник (HSL), повёрнутый к оттенку."""
    KEY = "wheel"

    def __init__(self, app, opts=None):
        super().__init__(app, opts)
        self.model = self.opts.get("model", "HSV")
        self.h, self.s, self.y = rgb_to_model(self.model, self.state.color())
        self._ring = self._shape = None
        self._ring_key = self._shape_key = None
        self._drag = None
        self._before = None
        self._mpos = QPointF()
        self.btn = IconButton("mode", self, 24, "Модель: HSV / HSL / V-HSV")
        self.btn.clicked.connect(self._model_menu)
        self.state.changed.connect(self._on_state)

    def heightFor(self, w):
        return int(w * 0.9)

    def resizeEvent(self, e):
        self.btn.move(self.width() - 26, self.height() - 24)

    def _model_menu(self):
        m = QMenu(self)
        for name, label in (("HSV", "HSV — квадрат"), ("HSL", "HSL — треугольник"), ("V-HSV", "V-HSV — квадрат")):
            a = m.addAction(("●  " if name == self.model else "    ") + label)
            a.triggered.connect(lambda _=False, n=name: self._set_model(n))
        m.exec(self.btn.mapToGlobal(QPoint(0, self.btn.height())))

    def _set_model(self, n):
        self.model = self.opts["model"] = n
        _, self.s, self.y = rgb_to_model(n, self.state.color())
        self._shape_key = None
        self.update()

    def _on_state(self, src):
        if src is self:
            return
        h, s, y = rgb_to_model(self.model, self.state.color())
        if s > 1e-3 and 1e-3 < y < 1 - 1e-3 or (self.model == "HSV" and s > 1e-3 and y > 1e-3):
            self.h = h
        self.s, self.y = s, y
        self.update()

    # ---- geometry
    def _geo(self):
        w, h = self.width(), self.height()
        R = min(w, h) / 2 - 4
        rw = max(10.0, R * 0.12)
        ri = R - rw - 8
        return w / 2, h / 2, R, rw, ri

    def _theta(self):
        return hue_angle(self.h) if self.model == "HSL" else 0.0

    def _to_screen(self, x, y, cx, cy):
        t = self._theta()
        c, s = math.cos(t), math.sin(t)
        return QPointF(cx + x * c + y * s, cy - x * s + y * c)

    def _to_local(self, pos, cx, cy):
        t = self._theta()
        c, s = math.cos(t), math.sin(t)
        dx, dy = pos.x() - cx, pos.y() - cy
        return dx * c - dy * s, dx * s + dy * c

    def _ring_img(self, R, rw):
        n = int(2 * R)
        key = (n, int(rw))
        if key != self._ring_key and n > 4:
            yy, xx = np.mgrid[0:n, 0:n] + 0.5
            dx, dy = xx - n / 2, yy - n / 2
            d = np.hypot(dx, dy)
            hue = ((150 - np.degrees(np.arctan2(-dy, dx))) / 360) % 1
            rgb = hsv2rgb(hue, 1, 1)
            a = np.clip(np.minimum(d - (n / 2 - rw), n / 2 - d), 0, 1)
            self._ring = np_to_qimage(np.concatenate([rgb * a[..., None], a[..., None]], -1))
            self._ring_key = key
        return self._ring

    def _shape_img(self, ri):
        tri = self.model == "HSL"
        n = int(2 * ri) if tri else int(ri * math.sqrt(2) * 0.97)
        key = (round(self.h, 4), self.model, n)
        if key != self._shape_key and n > 4:
            if tri:
                yy, xx = np.mgrid[0:n, 0:n] + 0.5
                x, y = xx - n / 2, yy - n / 2
                L = 0.5 - y / (2 * 0.866 * ri)
                width = 1.5 * ri * (1 - np.abs(2 * np.clip(L, 0, 1) - 1))
                S = np.clip((x + ri / 2) / np.maximum(width, 1e-6), 0, 1)
                rgb = np.clip(hsl2rgb(self.h, S, np.clip(L, 0, 1)), 0, 1)
                d_left = x + ri / 2
                d_edge = (ri - 1.5 * ri * np.abs(2 * L - 1) - x) * 0.5
                a = np.clip(np.minimum(d_left, d_edge) + 0.5, 0, 1) * ((L >= -0.01) & (L <= 1.01))
                img = np.concatenate([rgb * a[..., None], a[..., None]], -1)
            else:
                xs = np.linspace(0, 1, n)
                S, Y = np.meshgrid(xs, xs[::-1])
                img = np.clip(model_to_rgb(self.model, self.h, S, Y), 0, 1)
            self._shape = np_to_qimage(img)
            self._shape_key = key
        return self._shape

    def _marker_local(self, ri):
        if self.model == "HSL":
            width = 1.5 * ri * (1 - abs(2 * self.y - 1))
            return -ri / 2 + self.s * width, (1 - 2 * self.y) * 0.866 * ri
        sq = ri * math.sqrt(2) * 0.97
        return (self.s - 0.5) * sq, (0.5 - self.y) * sq

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        cx, cy, R, rw, ri = self._geo()
        ring = self._ring_img(R, rw)
        if ring:
            p.drawImage(QPointF(cx - R, cy - R), ring)
        shape = self._shape_img(ri)
        if shape:
            p.save()
            p.translate(cx, cy)
            p.rotate(-math.degrees(self._theta()))
            n = shape.width()
            p.drawImage(QRectF(-n / 2, -n / 2, n, n), shape)
            p.restore()
        # marker
        mx, my = self._marker_local(ri)
        m = self._to_screen(mx, my, cx, cy)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(0, 0, 0, 120), 3))
        p.drawEllipse(m, 6, 6)
        p.setPen(QPen(QColor("#F4F6FB"), 1.8))
        p.drawEllipse(m, 6, 6)
        # hue handle
        a = hue_angle(self.h)
        rm = R - rw / 2
        p.save()
        p.translate(cx + math.cos(a) * rm, cy - math.sin(a) * rm)
        p.rotate(-math.degrees(a))
        hr = QRectF(-(rw + 6) / 2, -rw * 0.38, rw + 6, rw * 0.76)
        p.setBrush(QColor.fromHsvF(self.h % 1.0, 1, 1))
        p.setPen(QPen(QColor(0, 0, 0, 110), 4))
        p.drawRoundedRect(hr, 4, 4)
        p.setPen(QPen(QColor("#F4F6FB"), 2.2))
        p.drawRoundedRect(hr, 4, 4)
        p.restore()
        if self._drag and self._before:
            draw_compare(p, self._mpos, self.state.color(), self._before, self.rect())

    def mousePressEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        cx, cy, R, rw, ri = self._geo()
        d = math.hypot(e.position().x() - cx, e.position().y() - cy)
        self._drag = "ring" if R - rw - 4 <= d <= R + 4 else ("shape" if d < R - rw - 4 else None)
        self._before = self.state.color()
        self._apply(e.position(), False)

    def mouseMoveEvent(self, e):
        self._apply(e.position(), False)

    def mouseReleaseEvent(self, e):
        self._apply(e.position(), True)
        self._drag = None
        self.update()

    def _apply(self, pos, commit):
        if not self._drag:
            return
        self._mpos = pos
        cx, cy, R, rw, ri = self._geo()
        if self._drag == "ring":
            self.h = angle_hue(math.atan2(-(pos.y() - cy), pos.x() - cx))
        else:
            x, y = self._to_local(pos, cx, cy)
            if self.model == "HSL":
                L = min(1, max(0, 0.5 - y / (2 * 0.866 * ri)))
                width = 1.5 * ri * (1 - abs(2 * L - 1))
                self.s = min(1, max(0, (x + ri / 2) / width)) if width > 1e-6 else 0
                self.y = L
            else:
                sq = ri * math.sqrt(2) * 0.97
                self.s = min(1, max(0, x / sq + 0.5))
                self.y = min(1, max(0, 0.5 - y / sq))
        self.state.set_color(model_to_rgb(self.model, self.h, self.s, self.y), self, commit)
        self.update()


class LumaComp(Comp):
    """Luma-Based Palette: срез гаммы sRGB на текущей яркости L* + слайдер яркости."""
    KEY = "luma"
    AB = 118

    def __init__(self, app, opts=None):
        super().__init__(app, opts)
        self.view = self.opts.get("view", "focused")
        self.L, self.C, self.H = self._lch()
        self._img = self._img_key = None
        self._drag = None
        self._before = None
        self._mpos = QPointF()
        self.btn = IconButton("luma", self, 24, "Focused / Full палитра")
        self.btn.clicked.connect(self._toggle)
        self.state.changed.connect(self._on_state)

    def heightFor(self, w):
        return int(w * 0.8) + 34

    def resizeEvent(self, e):
        self.btn.move(self.width() - 25, self.height() - 26)

    def _lch(self):
        L, a, b = rgb2lab(np.array(self.state.color()))
        return float(L), float(math.hypot(a, b)), float(math.degrees(math.atan2(b, a)) % 360)

    def _toggle(self):
        self.view = self.opts["view"] = "full" if self.view == "focused" else "focused"
        self._img_key = None
        self.update()

    def _on_state(self, src):
        if src is self:
            return
        L, C, H = self._lch()
        if C < 1.5:
            H = self.H
        self.L, self.C, self.H = L, C, H
        self.update()

    def _card(self):
        return QRectF(0, 0, self.width(), self.height() - 34)

    def _area(self):
        c = self._card()
        if self.view == "full":
            return c.adjusted(12, 12, -12, -12)
        side = min(c.width(), c.height()) - 18
        return QRectF(c.center().x() - side / 2, c.center().y() - side / 2, side, side)

    def _image(self, area):
        if self.view == "full":
            n = 96
            Cf = max(self.C, 30)
            key = ("full", round(Cf / 3))
            if key != self._img_key:
                Hs = np.linspace(0, 360, n)
                Ls = np.linspace(100, 0, n)
                Hg, Lg = np.meshgrid(Hs, Ls)
                hr = np.radians(Hg)
                lo, hi = np.zeros_like(Hg), np.full_like(Hg, Cf)
                for _ in range(10):
                    mid = (lo + hi) / 2
                    rgb = lab2rgb(np.stack([Lg, mid * np.cos(hr), mid * np.sin(hr)], -1))
                    ok = np.all((rgb > -1e-4) & (rgb < 1 + 1e-4), -1)
                    lo, hi = np.where(ok, mid, lo), np.where(ok, hi, mid)
                rgb = lab2rgb(np.stack([Lg, lo * np.cos(hr), lo * np.sin(hr)], -1))
                self._img = np_to_qimage(np.clip(rgb, 0, 1))
                self._img_key = key
        else:
            n = 120
            key = ("foc", round(self.L, 1))
            if key != self._img_key:
                ab = np.linspace(-self.AB, self.AB, n)
                A, B = np.meshgrid(ab, ab[::-1])
                rgb = lab2rgb(np.stack([np.full_like(A, self.L), A, B], -1))
                over = np.maximum(rgb.max(-1) - 1, -rgb.min(-1))
                alpha = np.clip(1 - over * 30, 0, 1)
                rgb = np.clip(rgb, 0, 1)
                self._img = np_to_qimage(np.concatenate([rgb * alpha[..., None], alpha[..., None]], -1))
                self._img_key = key
        return self._img

    def _marker(self, area):
        if self.view == "full":
            return QPointF(area.left() + self.H / 360 * area.width(), area.top() + (1 - self.L / 100) * area.height())
        a = self.C * math.cos(math.radians(self.H))
        b = self.C * math.sin(math.radians(self.H))
        return QPointF(area.left() + (a + self.AB) / (2 * self.AB) * area.width(),
                       area.top() + (self.AB - b) / (2 * self.AB) * area.height())

    def _slider_rect(self):
        return QRectF(6, self.height() - 22, self.width() - 40, 10)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        card = self._card()
        p.setPen(Qt.NoPen)
        p.setBrush(CARD2)
        p.drawRoundedRect(card, 12, 12)
        area = self._area()
        p.save()
        p.setClipPath(card_path(area, 6 if self.view == "full" else 0))
        p.drawImage(area, self._image(area))
        p.restore()
        m = self._marker(area)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(0, 0, 0, 120), 3))
        p.drawEllipse(m, 6, 6)
        p.setPen(QPen(QColor("#F4F6FB"), 1.8))
        p.drawEllipse(m, 6, 6)
        stops = [to_qcolor(lch_in_gamut(Li, self.C, self.H)) for Li in range(0, 101, 10)]
        draw_bar(p, self._slider_rect(), stops, self.L / 100, knob="rect")
        if self._drag and self._before:
            draw_compare(p, self._mpos, self.state.color(), self._before, self.rect())

    def mousePressEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        pos = e.position()
        if self._slider_rect().adjusted(-8, -8, 8, 8).contains(pos):
            self._drag = "slider"
        elif self._card().contains(pos):
            self._drag = "map"
        else:
            self._drag = None
        self._before = self.state.color()
        self._apply(pos, False)

    def mouseMoveEvent(self, e):
        self._apply(e.position(), False)

    def mouseReleaseEvent(self, e):
        self._apply(e.position(), True)
        self._drag = None
        self.update()

    def _apply(self, pos, commit):
        if not self._drag:
            return
        self._mpos = pos
        if self._drag == "slider":
            r = self._slider_rect()
            self.L = min(100, max(0, (pos.x() - r.left()) / r.width() * 100))
        else:
            area = self._area()
            fx = min(1, max(0, (pos.x() - area.left()) / area.width()))
            fy = min(1, max(0, (pos.y() - area.top()) / area.height()))
            if self.view == "full":
                self.H, self.L = fx * 360, (1 - fy) * 100
                self.C = max(self.C, 30)
            else:
                a, b = fx * 2 * self.AB - self.AB, self.AB - fy * 2 * self.AB
                self.C, self.H = math.hypot(a, b), math.degrees(math.atan2(b, a)) % 360
        rgb = lch_in_gamut(self.L, self.C, self.H)
        self.state.set_color(rgb, self, commit)
        self.update()


class FGBGComp(Comp):
    """Три «таблетки»: основной, фоновый, прозрачный. ПКМ — поменять местами."""
    KEY = "fgbg"

    def __init__(self, app, opts=None):
        super().__init__(app, opts)
        self.state.changed.connect(lambda _: self.update())
        self.setToolTip("ЛКМ — выбрать слот, ПКМ — поменять основной и фоновый")

    def heightFor(self, w):
        return 28

    def _rects(self):
        w = (self.width() - 2 * 10) / 3
        return [QRectF(2 + i * (w + 10), 3, w - 4, self.height() - 6) for i in range(3)]

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        s = self.state
        for i, r in enumerate(self._rects()):
            rad = r.height() / 2
            if i == 2:
                p.save()
                p.setClipPath(card_path(r, rad))
                p.fillRect(r, QColor("#3A4256"))
                for yy in range(int(r.top()), int(r.bottom()) + 1, 4):
                    for xx in range(int(r.left()), int(r.right()) + 1, 4):
                        if ((xx // 4) + (yy // 4)) % 2:
                            p.fillRect(xx, yy, 4, 4, QColor("#5A6378"))
                p.restore()
            else:
                p.setPen(Qt.NoPen)
                p.setBrush(to_qcolor(s.fg if i == 0 else s.bg))
                p.drawRoundedRect(r, rad, rad)
            active = (i == 2 and s.transparent) or (not s.transparent and i == (0 if s.active == "fg" else 1))
            if active:
                p.setBrush(Qt.NoBrush)
                p.setPen(QPen(QColor("#E9EEFB"), 2))
                p.drawRoundedRect(r.adjusted(-3, -3, 3, 3), rad + 3, rad + 3)

    def mousePressEvent(self, e):
        if e.button() == Qt.RightButton:
            self.state.swap()
            return
        for i, r in enumerate(self._rects()):
            if r.adjusted(-4, -4, 4, 4).contains(e.position()):
                if i == 2:
                    self.state.transparent = not self.state.transparent
                    self.state.changed.emit(None)
                else:
                    self.state.set_active("fg" if i == 0 else "bg")


class SliderComp(Comp):
    """Набор тонких слайдеров одного цветового пространства."""

    def __init__(self, app, opts=None, space="RGB"):
        super().__init__(app, opts)
        self.space = space
        self.KEY = "slider:" + space
        self.vals = space_from_rgb(space, self.state.color())
        self._drag = -1
        self.state.changed.connect(self._on_state)

    def heightFor(self, w):
        return 26 * len(SPACES[self.space])

    def _on_state(self, src):
        if src is self:
            return
        new = space_from_rgb(self.space, self.state.color())
        if self.space in ("HSL", "HSV", "V-HSV") and new[1] < 0.05:
            new[0] = self.vals[0]
        if self.space == "LCH" and new[1] < 0.5:
            new[2] = self.vals[2]
        self.vals = new
        self.update()

    def _bar(self, i):
        return QRectF(24, i * 26 + 10, self.width() - 24 - 48, 6)

    def _fmt(self, i):
        name, lo, hi = SPACES[self.space][i]
        v = self.vals[i]
        if name == "H":
            return f"{v:.0f}°"
        if self.space in ("HSL", "HSV", "V-HSV", "CMYK") or (self.space in ("LAB", "LCH") and name == "L"):
            return f"{v:.0f}%"
        return f"{v:.0f}"

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        for i, (name, lo, hi) in enumerate(SPACES[self.space]):
            stops = []
            for k in range(9):
                vv = list(self.vals)
                vv[i] = lo + (hi - lo) * k / 8
                stops.append(to_qcolor(space_to_rgb(self.space, vv)))
            r = self._bar(i)
            p.setPen(DIM)
            p.drawText(QRectF(0, r.center().y() - 9, 20, 18), Qt.AlignVCenter | Qt.AlignLeft, name)
            p.setPen(TXT)
            p.drawText(QRectF(self.width() - 44, r.center().y() - 9, 44, 18), Qt.AlignVCenter | Qt.AlignRight,
                       self._fmt(i))
            draw_bar(p, r, stops, (self.vals[i] - lo) / (hi - lo))

    def mousePressEvent(self, e):
        i = int(e.position().y() // 26)
        if 0 <= i < len(SPACES[self.space]):
            self._drag = i
            self._apply(e.position(), False)

    def mouseMoveEvent(self, e):
        self._apply(e.position(), False)

    def mouseReleaseEvent(self, e):
        self._apply(e.position(), True)
        self._drag = -1

    def _apply(self, pos, commit):
        if self._drag < 0:
            return
        name, lo, hi = SPACES[self.space][self._drag]
        r = self._bar(self._drag)
        t = min(1, max(0, (pos.x() - r.left()) / r.width()))
        self.vals[self._drag] = lo + (hi - lo) * t
        self.state.set_color(space_to_rgb(self.space, self.vals), self, commit)
        self.update()


class HistoryComp(Comp):
    KEY = "history"

    def __init__(self, app, opts=None):
        super().__init__(app, opts)
        self.state.historyChanged.connect(self.update)
        self.setToolTip("История цветов. ПКМ — удалить")

    def heightFor(self, w):
        return 24

    def _cells(self):
        d = 20
        n = max(1, int((self.width() + 6) // (d + 6)))
        return [(QRectF(i * (d + 6) + 1, 2, d, d), hx) for i, hx in enumerate(self.state.history[:n])]

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        cells = self._cells()
        if not cells:
            p.setPen(DIM)
            p.drawText(self.rect(), Qt.AlignVCenter | Qt.AlignLeft, "История пуста")
        for r, hx in cells:
            p.setPen(QPen(QColor(255, 255, 255, 25), 1))
            p.setBrush(QColor(hx))
            p.drawEllipse(r)

    def mousePressEvent(self, e):
        for i, (r, hx) in enumerate(self._cells()):
            if r.contains(e.position()):
                if e.button() == Qt.RightButton:
                    del self.state.history[i]
                    self.state.historyChanged.emit()
                else:
                    self.state.set_color(from_hex(hx), self, False)


class SwatchesComp(Comp):
    KEY = "swatches"
    CELL, GAP = 22, 5

    def __init__(self, app, opts=None):
        super().__init__(app, opts)
        self.state.palettesChanged.connect(self._refresh)
        self.setToolTip("ЛКМ — выбрать, ПКМ — удалить, «+» — добавить текущий цвет")

    def _refresh(self):
        self.app.relayout()
        self.update()

    def _colors(self):
        return self.state.palettes.get(self.state.current_palette, [])

    def _cols(self, w):
        return max(1, int((w + self.GAP) // (self.CELL + self.GAP)))

    def heightFor(self, w):
        n = len(self._colors()) + 1
        rows = math.ceil(n / self._cols(w))
        return 22 + rows * (self.CELL + self.GAP)

    def _cells(self):
        cols = self._cols(self.width())
        out = []
        for i in range(len(self._colors()) + 1):
            r, c = divmod(i, cols)
            out.append(QRectF(c * (self.CELL + self.GAP), 22 + r * (self.CELL + self.GAP), self.CELL, self.CELL))
        return out

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(TXT)
        f = p.font()
        f.setBold(True)
        p.setFont(f)
        p.drawText(QRectF(0, 0, self.width(), 18), Qt.AlignVCenter | Qt.AlignLeft, self.state.current_palette + "  ▾")
        cols = self._colors()
        for i, r in enumerate(self._cells()):
            if i < len(cols):
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(cols[i]))
                p.drawRoundedRect(r, 5, 5)
            else:
                p.setPen(Qt.NoPen)
                p.setBrush(CARD2)
                p.drawRoundedRect(r, 5, 5)
                p.setPen(QPen(DIM, 1.6))
                c = r.center()
                p.drawLine(QPointF(c.x() - 5, c.y()), QPointF(c.x() + 5, c.y()))
                p.drawLine(QPointF(c.x(), c.y() - 5), QPointF(c.x(), c.y() + 5))

    def mousePressEvent(self, e):
        pos = e.position()
        if pos.y() < 20:
            m = QMenu(self)
            for name in self.state.palettes:
                a = m.addAction(("●  " if name == self.state.current_palette else "    ") + name)
                a.triggered.connect(lambda _=False, n=name: self._select(n))
            m.exec(self.mapToGlobal(QPoint(0, 20)))
            return
        cols = self._colors()
        for i, r in enumerate(self._cells()):
            if r.contains(pos):
                if i == len(cols):
                    cols.append(to_hex(self.state.color()))
                    self.state.palettes[self.state.current_palette] = cols
                    self.state.palettesChanged.emit()
                elif e.button() == Qt.RightButton:
                    del cols[i]
                    self.state.palettesChanged.emit()
                else:
                    self.state.set_color(from_hex(cols[i]), self)

    def _select(self, n):
        self.state.current_palette = n
        self.state.palettesChanged.emit()


COMPONENTS = [
    ("Color Picker", [("wheel", "Color Wheel", "◌"), ("luma", "Luma-Based Palette", "⛵")]),
    ("Color Slider", [("slider:" + s, s, "☰") for s in ("RGB", "HSL", "HSV", "V-HSV", "LAB", "LCH", "CMYK")]),
    ("Color Management", [("history", "History", "↺"), ("fgbg", "Foreground/Background Color", "◐"),
                          ("swatches", "Swatches", "▦")]),
]


def make_comp(app, item):
    key, opts = item["key"], item.get("opts", {})
    if key.startswith("slider:"):
        return SliderComp(app, opts, key.split(":", 1)[1])
    cls = {"wheel": WheelComp, "luma": LumaComp, "fgbg": FGBGComp, "history": HistoryComp,
           "swatches": SwatchesComp}.get(key)
    return cls(app, opts) if cls else None


# ============================================================== body / panel
class Body(QWidget):
    def __init__(self, app, items):
        super().__init__()
        self.app = app
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        self.comps = []
        for it in items:
            c = make_comp(app, it)
            if c:
                self.comps.append(c)
                lay.addWidget(c)
        if not self.comps:
            hint = QLabel("Панель пуста.\n☰ → Настроить панель")
            hint.setAlignment(Qt.AlignCenter)
            hint.setStyleSheet("color:#7B859E; padding:30px")
            lay.addWidget(hint)

    def relayout(self, w):
        h = 0
        for c in self.comps:
            ch = c.heightFor(w)
            c.setFixedSize(w, ch)
            h += ch
        h += max(0, len(self.comps) - 1) * 12
        self.setFixedSize(w, h if self.comps else 120)

    def items(self):
        return [{"key": c.KEY, "opts": c.opts} for c in self.comps]


class GlobalTrigger(QObject):
    fired = Signal()

    def __init__(self):
        super().__init__()
        self._kb = self._ms = None

    def configure(self, hotkey, middle):
        self.stop()
        try:
            from pynput import keyboard, mouse
        except ImportError:
            return False
        if hotkey:
            try:
                self._kb = keyboard.GlobalHotKeys({hotkey: self.fired.emit})
                self._kb.start()
            except Exception:
                self._kb = None
        if middle:
            def on_click(x, y, btn, pressed):
                if pressed and btn == mouse.Button.middle:
                    self.fired.emit()
            self._ms = mouse.Listener(on_click=on_click)
            self._ms.start()
        return True

    def stop(self):
        for l in (self._kb, self._ms):
            if l:
                l.stop()
        self._kb = self._ms = None


def ps_set(state):
    if sys.platform != "win32":
        return
    try:
        import win32com.client
        ps = win32com.client.GetActiveObject("Photoshop.Application")
        c = win32com.client.Dispatch("Photoshop.SolidColor")
        r, g, b = to_qcolor(state.color()).getRgb()[:3]
        c.RGB.Red, c.RGB.Green, c.RGB.Blue = r, g, b
        if state.active == "fg":
            ps.ForegroundColor = c
        else:
            ps.BackgroundColor = c
    except Exception:
        pass


class FloatingPanel(QWidget):
    """Главное окно: парящая карточка без рамки с боковыми вкладками панелей."""

    def __init__(self):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowTitle("Dynamic Color Picker")
        self.state = ColorState()
        self.state.csp = CSPLink(self.state)
        self.cfg = self._load()
        self._apply_state_cfg()
        self.layouts = self.cfg.get("layouts") or [
            {"name": "1", "items": [{"key": "wheel"}, {"key": "history"}]},
            {"name": "2", "items": [{"key": "luma"}, {"key": "fgbg"}, {"key": "slider:CMYK"},
                                    {"key": "swatches"}, {"key": "history"}]},
        ]
        self.cur = min(self.cfg.get("cur", 0), len(self.layouts) - 1)
        self.scale = self.cfg.get("scale", "M")
        self.pinned = self.cfg.get("pinned", True)
        self.pinned_pos = QPoint(*self.cfg["pos"]) if self.cfg.get("pos") else None
        self.popped = False
        self._drag_off = None

        self.logo = QLabel("dyna\nmic", self)
        self.logo.setStyleSheet("color:#8A94AD; font-weight:800; font-size:10pt; line-height:80%;")
        f = self.logo.font()
        f.setPointSizeF(10)
        f.setWeight(QFont.Black)
        f.setLetterSpacing(QFont.PercentageSpacing, 92)
        self.logo.setFont(f)
        self.dot = QLabel("●", self)
        self.dot.setToolTip("Связь с CSP")
        self.menu_btn = IconButton("menu", self, 26, "Меню")
        self.menu_btn.clicked.connect(self._menu)
        self.pin_btn = IconButton("pin", self, 26, "Закрепить на экране")
        self.pin_btn.setCheckable(True)
        self.pin_btn.setChecked(self.pinned)
        self.pin_btn.toggled.connect(self.set_pinned)
        self.body = None
        self.build_body()

        self.state.historyChanged.connect(lambda: None)
        self.state._commit.timeout.connect(self._on_commit)
        self.state.csp.statusChanged.connect(self._csp_status)
        self._csp_status(self.state.csp.text, False)

        self.trigger = GlobalTrigger()
        self.trigger.fired.connect(self.popup_toggle, Qt.QueuedConnection)
        self.trigger.configure(self.cfg.get("hotkey", "<ctrl>+<alt>+c"), self.cfg.get("middle_click", False))
        self._leave = QTimer(singleShot=True, interval=650)
        self._leave.timeout.connect(self._maybe_return)
        self._make_tray()
        self._apply_flags()
        if self.pinned_pos:
            self.move(self.pinned_pos)
        else:
            g = QGuiApplication.primaryScreen().availableGeometry()
            self.move(g.right() - self.width() - 60, g.top() + 120)
        if self.cfg.get("csp_autoreconnect", True) and cspc.load_session(APP_DIR):
            QTimer.singleShot(600, self.state.csp.reconnect)

    # ---------------- config
    def _load(self):
        try:
            return json.load(open(CONFIG_PATH, encoding="utf-8"))
        except Exception:
            return {}

    def _apply_state_cfg(self):
        c, s = self.cfg, self.state
        if c.get("palettes"):
            s.palettes = c["palettes"]
        if "The Deepest Blue" not in s.palettes and not c.get("palettes"):
            s.palettes = {"The Deepest Blue": ["#F2D6C9", "#F6C9B5", "#5EC8F2", "#3FB3F0", "#2D8CF0", "#2A6FE8",
                                               "#1F4FD8", "#2B2FB8", "#6A3FD0", "#B24FD8", "#E85A8A", "#E8434F"],
                          "Default": ["#000000", "#FFFFFF", "#E05A47", "#F2C14E", "#5B8E7D", "#3D5A80"]}
        s.current_palette = c.get("current_palette") if c.get("current_palette") in s.palettes else next(iter(s.palettes))
        s.history = c.get("history", [])
        if c.get("fg"):
            s.fg = from_hex(c["fg"]) or s.fg
        if c.get("bg"):
            s.bg = from_hex(c["bg"]) or s.bg

    def save(self):
        os.makedirs(APP_DIR, exist_ok=True)
        if self.body:
            self.layouts[self.cur]["items"] = self.body.items()
        s = self.state
        c = dict(self.cfg)
        c.update({"layouts": self.layouts, "cur": self.cur, "scale": self.scale, "pinned": self.pinned,
                  "pos": [self.pinned_pos.x(), self.pinned_pos.y()] if self.pinned_pos else None,
                  "palettes": s.palettes, "current_palette": s.current_palette, "history": s.history,
                  "fg": to_hex(s.fg), "bg": to_hex(s.bg)})
        json.dump(c, open(CONFIG_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    # ---------------- layout
    def body_width(self):
        return SCALES.get(self.scale, 296)

    def card_rect(self):
        return QRectF(SHADOW + TABW, SHADOW, self.width() - 2 * SHADOW - TABW, self.height() - 2 * SHADOW)

    def build_body(self):
        if self.body:
            self.layouts[self.cur]["items"] = self.body.items()
            self.body.hide()
            self.body.deleteLater()
        self.body = Body(self, self.layouts[self.cur]["items"])
        self.body.setParent(self)
        self.body.show()
        self.relayout()

    def relayout(self):
        if not self.body:
            return
        bw = self.body_width()
        self.body.relayout(bw)
        cw = bw + 2 * PAD
        ch = HEADER + self.body.height() + PAD + 4
        tabs_h = 56 + (len(self.layouts) + 1) * 38
        ch = max(ch, tabs_h)
        self.setFixedSize(cw + TABW + 2 * SHADOW, ch + 2 * SHADOW)
        cr = self.card_rect()
        self.body.move(int(cr.left() + PAD), int(cr.top() + HEADER))
        self.logo.move(int(cr.left() + 14), int(cr.top() + 8))
        self.logo.adjustSize()
        self.dot.move(int(cr.left() + 14 + self.logo.width() + 6), int(cr.top() + 14))
        self.dot.adjustSize()
        self.pin_btn.move(int(cr.right() - 36), int(cr.top() + 10))
        self.menu_btn.move(int(cr.right() - 66), int(cr.top() + 10))
        self.update()

    def _tab_rects(self):
        cr = self.card_rect()
        out = [QRectF(SHADOW + 2, cr.top() + 50 + i * 38, TABW + 10, 34) for i in range(len(self.layouts))]
        out.append(QRectF(SHADOW + 2, cr.top() + 50 + len(self.layouts) * 38, TABW + 10, 28))
        return out

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        tabs = self._tab_rects()
        f = p.font()
        f.setBold(True)
        f.setPointSize(10)
        p.setFont(f)
        for i, r in enumerate(tabs):
            if i == self.cur:
                continue
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, 60))
            p.drawRoundedRect(r.adjusted(-1, 1, 0, 2), 8, 8)
            p.setBrush(TAB_OFF)
            p.drawRoundedRect(r, 8, 8)
            p.setPen(DIM)
            p.drawText(QRectF(r.left(), r.top(), TABW - 2, r.height()), Qt.AlignCenter,
                       "+" if i == len(self.layouts) else self.layouts[i]["name"][:2])
        paint_card(p, self.card_rect())
        r = tabs[self.cur]
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#1F2638"))
        p.drawRoundedRect(r, 8, 8)
        p.drawRect(QRectF(r.right() - 10, r.top(), 12, r.height()))
        p.setPen(QColor("white"))
        p.drawText(QRectF(r.left(), r.top(), TABW - 2, r.height()), Qt.AlignCenter, self.layouts[self.cur]["name"][:2])

    def mousePressEvent(self, e):
        pos = e.position()
        for i, r in enumerate(self._tab_rects()):
            if r.contains(pos) and pos.x() < self.card_rect().left() + 2:
                if i == len(self.layouts):
                    self.add_layout()
                elif e.button() == Qt.RightButton:
                    self._tab_menu(i, e.globalPosition().toPoint())
                else:
                    self.switch(i)
                return
        if e.button() == Qt.LeftButton:
            self._drag_off = e.globalPosition().toPoint() - self.pos()

    def mouseMoveEvent(self, e):
        if self._drag_off is not None:
            self.move(e.globalPosition().toPoint() - self._drag_off)

    def mouseReleaseEvent(self, e):
        if self._drag_off is not None and not self.popped:
            self.pinned_pos = self.pos()
        self._drag_off = None

    # ---------------- layouts
    def switch(self, i):
        if i == self.cur:
            return
        self.layouts[self.cur]["items"] = self.body.items()
        self.cur = i
        self.body.hide()
        self.body.deleteLater()
        self.body = None
        self.build_body()

    def add_layout(self):
        self.layouts[self.cur]["items"] = self.body.items()
        self.layouts.append({"name": str(len(self.layouts) + 1), "items": [{"key": "wheel"}]})
        self.switch(len(self.layouts) - 1)
        self.open_editor()

    def _tab_menu(self, i, gpos):
        m = QMenu(self)
        m.addAction("Переименовать", lambda: self._rename(i))
        m.addAction("Дублировать", lambda: self._dup(i))
        d = m.addAction("Удалить", lambda: self._del(i))
        d.setEnabled(len(self.layouts) > 1)
        m.exec(gpos)

    def _rename(self, i):
        n, ok = QInputDialog.getText(self, "Панель", "Короткое имя (1–2 символа):", text=self.layouts[i]["name"])
        if ok and n.strip():
            self.layouts[i]["name"] = n.strip()[:2]
            self.update()

    def _dup(self, i):
        self.layouts[self.cur]["items"] = self.body.items()
        self.layouts.insert(i + 1, copy.deepcopy(self.layouts[i]))
        self.layouts[i + 1]["name"] = str(len(self.layouts))
        self.switch(i + 1)

    def _del(self, i):
        self.layouts.pop(i)
        self.cur = min(self.cur, len(self.layouts) - 1)
        if self.body:
            self.body.hide()
            self.body.deleteLater()
            self.body = None
        self.build_body()

    # ---------------- menu / dialogs
    def _menu(self):
        m = QMenu(self)
        m.addAction("Настроить панель…", self.open_editor)
        m.addSeparator()
        m.addAction("Подключение к CSP…", self.open_csp)
        ps = m.addAction(("✓  " if self.cfg.get("ps_sync") else "    ") + "Синхронизация с Photoshop")
        ps.triggered.connect(lambda: self.cfg.__setitem__("ps_sync", not self.cfg.get("ps_sync")))
        sz = m.addMenu("Размер панели")
        for k, lbl in (("S", "Маленькая"), ("M", "Средняя"), ("L", "Большая")):
            a = sz.addAction(("●  " if k == self.scale else "    ") + lbl)
            a.triggered.connect(lambda _=False, k=k: self._set_scale(k))
        m.addAction("Всплытие у пера…", self.open_settings)
        m.addSeparator()
        m.addAction("Скрыть", self.hide)
        m.addAction("Выход", self.quit)
        m.exec(self.menu_btn.mapToGlobal(QPoint(0, self.menu_btn.height() + 4)))

    def _set_scale(self, k):
        self.scale = k
        self.relayout()

    def open_editor(self):
        self.layouts[self.cur]["items"] = self.body.items()
        dlg = EditorDialog(self, self.layouts[self.cur]["items"])
        if dlg.exec():
            self.layouts[self.cur]["items"] = dlg.items()
            self.body.hide()
            self.body.deleteLater()
            self.body = None
            self.build_body()

    def open_csp(self):
        CSPDialog(self).exec()

    def open_settings(self):
        d = SettingsDialog(self, self.cfg)
        if d.exec():
            self.cfg.update(d.values())
            self.trigger.configure(self.cfg.get("hotkey"), self.cfg.get("middle_click"))

    def _csp_status(self, text, ok):
        self.dot.setStyleSheet(f"color:{'#2ECC71' if ok else '#4A5370'}; font-size:9pt;")
        self.dot.setToolTip("CSP: " + text)

    def _on_commit(self):
        if self.cfg.get("ps_sync"):
            ps_set(self.state)

    # ---------------- pin / follow mode
    def _apply_flags(self):
        vis = self.isVisible()
        self.setWindowFlag(Qt.WindowStaysOnTopHint, self.pinned or self.popped)
        if vis or not self.popped:
            self.show()

    def set_pinned(self, on):
        self.pinned = on
        if on and not self.popped:
            self.pinned_pos = self.pos()
        self._apply_flags()

    def popup_toggle(self):
        if self.popped:
            self._return_home()
            return
        cur = QCursor.pos()
        scr = QGuiApplication.screenAt(cur) or QGuiApplication.primaryScreen()
        g = scr.availableGeometry()
        x = min(max(g.left(), cur.x() + 30), g.right() - self.width())
        if x < cur.x() + 30:
            x = max(g.left(), cur.x() - 30 - self.width())
        y = min(max(g.top(), cur.y() - self.height() // 3), g.bottom() - self.height())
        if self.pinned and not self.pinned_pos:
            self.pinned_pos = self.pos()
        self.popped = True
        self._apply_flags()
        self.move(x, y)
        self.show()
        self.raise_()
        self.activateWindow()

    def _return_home(self):
        self.popped = False
        if self.pinned:
            if self.pinned_pos:
                self.move(self.pinned_pos)
            self._apply_flags()
        else:
            self.hide()

    def leaveEvent(self, e):
        if self.popped and self.cfg.get("auto_return", True):
            self._leave.start()

    def enterEvent(self, e):
        self._leave.stop()

    def _maybe_return(self):
        if self.popped and not self.frameGeometry().contains(QCursor.pos()) and not QApplication.mouseButtons() \
                and not QApplication.activePopupWidget() and not QApplication.activeModalWidget():
            self._return_home()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape and self.popped:
            self._return_home()

    # ---------------- tray / quit
    def _make_tray(self):
        pm = QPixmap(64, 64)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        g = QConicalGradient(32, 32, 0)
        for i in range(7):
            g.setColorAt(i / 6, QColor.fromHsvF((i / 6) % 1 * 0.999, 1, 1))
        p.setPen(QPen(QBrush(g), 10))
        p.drawEllipse(QRectF(8, 8, 48, 48))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#1D2333"))
        p.drawRoundedRect(QRectF(22, 22, 20, 20), 3, 3)
        p.end()
        icon = QIcon(pm)
        QApplication.instance().setWindowIcon(icon)
        self.tray = QSystemTrayIcon(icon, self)
        m = QMenu()
        m.addAction("Показать панель", self._show_home)
        m.addAction("Подключение к CSP…", self.open_csp)
        m.addSeparator()
        m.addAction("Выход", self.quit)
        self.tray.setContextMenu(m)
        self.tray.activated.connect(lambda r: self._show_home() if r == QSystemTrayIcon.Trigger else None)
        self.tray.setToolTip("Dynamic Color Picker")
        self.tray.show()

    def _show_home(self):
        self.popped = False
        if self.pinned_pos:
            self.move(self.pinned_pos)
        self._apply_flags()
        self.show()
        self.raise_()

    def quit(self):
        self.save()
        self.trigger.stop()
        self.state.csp.disconnect()
        self.tray.hide()
        QApplication.quit()


# ============================================================== dark dialogs
class DarkDialog(QDialog):
    def __init__(self, parent, title=""):
        super().__init__(parent, Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self._off = None
        self.outer = QVBoxLayout(self)
        self.outer.setContentsMargins(SHADOW + 16, SHADOW + 12, SHADOW + 16, SHADOW + 16)
        self.outer.setSpacing(10)
        if title:
            row = QHBoxLayout()
            t = QLabel(title)
            t.setObjectName("title")
            row.addWidget(t)
            row.addStretch()
            x = IconButton("close", self, 24, "Закрыть")
            x.clicked.connect(self.reject)
            row.addWidget(x)
            self.outer.addLayout(row)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        paint_card(p, QRectF(self.rect()).adjusted(SHADOW, SHADOW, -SHADOW, -SHADOW))

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._off = e.globalPosition().toPoint() - self.pos()

    def mouseMoveEvent(self, e):
        if self._off is not None:
            self.move(e.globalPosition().toPoint() - self._off)

    def mouseReleaseEvent(self, e):
        self._off = None

    def center_on(self, w):
        g = w.frameGeometry()
        self.adjustSize()
        scr = (QGuiApplication.screenAt(g.center()) or QGuiApplication.primaryScreen()).availableGeometry()
        x = min(max(scr.left(), g.center().x() - self.width() // 2), scr.right() - self.width())
        y = min(max(scr.top(), g.center().y() - self.height() // 2), scr.bottom() - self.height())
        self.move(x, y)


def pill(text, obj="pill"):
    b = QPushButton(text)
    b.setObjectName(obj)
    b.setCursor(Qt.PointingHandCursor)
    return b


class CSPDialog(DarkDialog):
    def __init__(self, panel):
        super().__init__(panel, "Подключение к Clip Studio Paint")
        self.link = panel.state.csp
        self.setFixedWidth(380)
        self.msg = QLabel(wordWrap=True)
        self.outer.addWidget(self.msg)
        hint = QLabel("В CSP: File → Connect to smartphone. QR-код считается с экрана автоматически.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#7B859E")
        self.outer.addWidget(hint)
        g = QGridLayout()
        g.setSpacing(8)
        for i, (t, fn, obj) in enumerate((("Подключить по QR", self.link.start_scan, "primary"),
                                          ("Вставить URL", self._paste, "ghost"),
                                          ("Переподключиться", self.link.reconnect, "ghost"),
                                          ("Отключить", self.link.disconnect, "ghost"))):
            b = pill(t, obj)
            b.clicked.connect(fn)
            g.addWidget(b, i // 2, i % 2)
        self.outer.addLayout(g)
        self.link.statusChanged.connect(self._show)
        self._show(self.link.text, self.link.connected)
        self.center_on(panel)

    def _show(self, text, ok):
        self.msg.setText(f"<span style='color:{'#2ECC71' if ok else '#7B859E'}; font-size:12pt'>●</span>&nbsp; {text}")

    def _paste(self):
        clip = QGuiApplication.clipboard().text()
        url, ok = QInputDialog.getText(self, "URL из QR", "https://companion.clip-studio.com/…?s=…",
                                       text=clip if clip.startswith(cspc.QR_PREFIX) else "")
        if ok and url:
            self.link.connect_url(url)


class SettingsDialog(DarkDialog):
    def __init__(self, panel, cfg):
        super().__init__(panel, "Всплытие у пера")
        self.setFixedWidth(380)
        f = QFormLayout()
        f.setSpacing(8)
        self.hotkey = QLineEdit(cfg.get("hotkey", "<ctrl>+<alt>+c"))
        f.addRow("Горячая клавиша:", self.hotkey)
        self.outer.addLayout(f)
        self.middle = QCheckBox("Средняя / боковая кнопка пера")
        self.middle.setChecked(cfg.get("middle_click", False))
        self.autoret = QCheckBox("Прятать, когда перо уходит с панели")
        self.autoret.setChecked(cfg.get("auto_return", True))
        self.recon = QCheckBox("Автоподключение к CSP при запуске")
        self.recon.setChecked(cfg.get("csp_autoreconnect", True))
        for w in (self.middle, self.autoret, self.recon):
            self.outer.addWidget(w)
        n = QLabel("📌 включён — панель стоит на месте и всплывает у пера по клавише.\n"
                   "📌 выключен — Follow Mode: панель появляется только у пера.")
        n.setStyleSheet("color:#7B859E")
        n.setWordWrap(True)
        self.outer.addWidget(n)
        row = QHBoxLayout()
        c = pill("✕", "ghost")
        c.clicked.connect(self.reject)
        ok = pill("✓", "primary")
        ok.clicked.connect(self.accept)
        row.addWidget(c)
        row.addWidget(ok, 2)
        self.outer.addLayout(row)
        self.center_on(panel)

    def values(self):
        return {"hotkey": self.hotkey.text().strip(), "middle_click": self.middle.isChecked(),
                "auto_return": self.autoret.isChecked(), "csp_autoreconnect": self.recon.isChecked()}


# ============================================================== editor
MIME_NEW, MIME_MOVE = "application/x-dcp-new", "application/x-dcp-move"


class EditItem(QWidget):
    removed = Signal(object)

    def __init__(self, comp, idx):
        super().__init__()
        self.comp, self.idx = comp, idx
        comp.setParent(self)
        comp.move(0, 0)
        self.setFixedSize(comp.size())
        self.rm = IconButton("minus", self, 18, "Убрать")
        self.rm.clicked.connect(lambda: self.removed.emit(self))
        self.rm.move(self.width() - 18, 0)
        self.rm.hide()
        self._hover = False

    def enterEvent(self, e):
        self._hover = True
        self.rm.show()
        self.rm.raise_()
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.rm.hide()
        self.update()

    def paintEvent(self, e):
        if self._hover:
            p = QPainter(self)
            p.setRenderHint(QPainter.Antialiasing)
            p.setPen(QPen(QColor(47, 107, 255, 160), 1.2, Qt.DashLine))
            p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)



class Grip(QLabel):
    """Ручка перетаскивания компонента в превью."""

    def __init__(self, item):
        super().__init__("⠿")
        self.item = item
        self.setFixedWidth(14)
        self.setCursor(Qt.OpenHandCursor)
        self.setStyleSheet("color:#5A6380; font-size:12pt")
        self.setToolTip("Перетащите, чтобы изменить порядок")

    def mousePressEvent(self, e):
        md = QMimeData()
        md.setData(MIME_MOVE, str(self.item.idx).encode())
        drag = QDrag(self)
        drag.setMimeData(md)
        drag.setPixmap(self.item.grab().scaledToWidth(160, Qt.SmoothTransformation))
        drag.exec(Qt.MoveAction)


class Preview(QWidget):
    changed = Signal()

    def __init__(self, panel, items):
        super().__init__()
        self.panel, self.items = panel, [dict(i) for i in items]
        self.setAcceptDrops(True)
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.lay.setSpacing(12)
        self.rows = []
        self.marker_y = None
        self.rebuild()

    def rebuild(self):
        for r in self.rows:
            r.deleteLater()
        self.rows = []
        while self.lay.count():
            it = self.lay.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        bw = self.panel.body_width()
        for i, it in enumerate(self.items):
            c = make_comp(self.panel, it)
            if not c:
                continue
            c.setFixedSize(bw, c.heightFor(bw))
            ei = EditItem(c, i)
            ei.removed.connect(self._remove)
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(4)
            h.addWidget(Grip(ei))
            h.addWidget(ei)
            self.rows.append(row)
            self.lay.addWidget(row)
        if not self.items:
            l = QLabel("Перетащите компоненты сюда")
            l.setAlignment(Qt.AlignCenter)
            l.setStyleSheet("color:#7B859E; padding:40px; border:1px dashed #3A4360; border-radius:10px")
            self.lay.addWidget(l)
        self.lay.addStretch()
        self.changed.emit()

    def _remove(self, ei):
        self.items.pop(ei.idx)
        self.rebuild()

    def _index_at(self, y):
        for i, r in enumerate(self.rows):
            if y < r.y() + r.height() / 2:
                return i
        return len(self.rows)

    def dragEnterEvent(self, e):
        if e.mimeData().hasFormat(MIME_NEW) or e.mimeData().hasFormat(MIME_MOVE):
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        i = self._index_at(e.position().y())
        self.marker_y = (self.rows[i].y() - 6) if i < len(self.rows) else \
            (self.rows[-1].y() + self.rows[-1].height() + 6 if self.rows else 10)
        self.update()
        e.acceptProposedAction()

    def dragLeaveEvent(self, e):
        self.marker_y = None
        self.update()

    def dropEvent(self, e):
        i = self._index_at(e.position().y())
        md = e.mimeData()
        if md.hasFormat(MIME_NEW):
            self.items.insert(i, {"key": bytes(md.data(MIME_NEW)).decode()})
        else:
            j = int(bytes(md.data(MIME_MOVE)).decode())
            it = self.items.pop(j)
            self.items.insert(i - 1 if j < i else i, it)
        self.marker_y = None
        e.acceptProposedAction()
        QTimer.singleShot(0, self.rebuild)

    def paintEvent(self, e):
        if self.marker_y is not None:
            p = QPainter(self)
            p.setPen(QPen(ACCENT, 3, cap=Qt.RoundCap))
            p.drawLine(QPointF(18, self.marker_y), QPointF(self.width() - 4, self.marker_y))


class CompButton(QPushButton):
    def __init__(self, key, text, glyph):
        super().__init__(f"{glyph}   {text}")
        self.key = key
        self.setObjectName("pill")
        self.setCursor(Qt.PointingHandCursor)
        self._press = None

    def mousePressEvent(self, e):
        self._press = e.position()
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._press is not None and (e.position() - self._press).manhattanLength() > 8:
            self._press = None
            self.setDown(False)
            md = QMimeData()
            md.setData(MIME_NEW, self.key.encode())
            drag = QDrag(self)
            drag.setMimeData(md)
            drag.setPixmap(self.grab())
            drag.exec(Qt.CopyAction)


class MiniGrid(QWidget):
    def __init__(self, colors, cell=16):
        super().__init__()
        self.colors, self.cell = list(colors), cell
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFixedHeight(self._h(250))

    def _h(self, w):
        cols = max(1, (w + 4) // (self.cell + 4))
        return max(self.cell, math.ceil(len(self.colors) / cols) * (self.cell + 4))

    def resizeEvent(self, e):
        self.setFixedHeight(self._h(self.width()))

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        cols = max(1, (self.width() + 4) // (self.cell + 4))
        p.setPen(Qt.NoPen)
        for i, hx in enumerate(self.colors):
            r, c = divmod(i, cols)
            p.setBrush(QColor(hx))
            p.drawRoundedRect(QRectF(c * (self.cell + 4), r * (self.cell + 4), self.cell, self.cell), 4, 4)


class EditorDialog(DarkDialog):
    """Настройка панели: слева живое превью, справа Components | Swatches."""

    def __init__(self, panel, items):
        super().__init__(panel)
        self.panel, self.state = panel, panel.state
        root = QHBoxLayout()
        root.setSpacing(16)
        self.outer.addLayout(root)
        # left: preview
        left = QVBoxLayout()
        cap = QLabel("Превью панели")
        cap.setObjectName("head")
        left.addWidget(cap)
        self.preview = Preview(panel, items)
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setWidget(self.preview)
        sa.setFixedWidth(panel.body_width() + 30)
        sa.setMinimumHeight(520)
        left.addWidget(sa)
        root.addLayout(left)
        # right
        right = QVBoxLayout()
        tabs = QHBoxLayout()
        self.t_comp, self.t_sw = pill("Components", "tab"), pill("Swatches", "tab")
        for b in (self.t_comp, self.t_sw):
            b.setCheckable(True)
            tabs.addWidget(b)
        tabs.addStretch()
        right.addLayout(tabs)
        self.stack = QStackedWidget()
        self.stack.addWidget(self._comp_page())
        self.sw_stack = QStackedWidget()
        self.sw_list = QWidget()
        self.sw_stack.addWidget(self._wrap(self.sw_list))
        self.ex_page = self._extract_page()
        self.sw_stack.addWidget(self.ex_page)
        self.stack.addWidget(self.sw_stack)
        right.addWidget(self.stack, 1)
        self.t_comp.clicked.connect(lambda: self._tab(0))
        self.t_sw.clicked.connect(lambda: self._tab(1))
        self._tab(0)
        bottom = QHBoxLayout()
        c = pill("✕", "ghost")
        c.setFixedWidth(110)
        c.clicked.connect(self.reject)
        ok = pill("✓", "primary")
        ok.clicked.connect(self.accept)
        bottom.addWidget(c)
        bottom.addWidget(ok, 1)
        right.addLayout(bottom)
        rw = QWidget()
        rw.setLayout(right)
        rw.setFixedWidth(290)
        root.addWidget(rw)
        self.preview.changed.connect(self._refresh_buttons)
        self.state.palettesChanged.connect(self._build_sw_list)
        self._build_sw_list()
        self._refresh_buttons()
        self.center_on(panel)

    def items(self):
        return self.preview.items

    def _wrap(self, w):
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setWidget(w)
        return sa

    def _tab(self, i):
        self.t_comp.setChecked(i == 0)
        self.t_sw.setChecked(i == 1)
        self.stack.setCurrentIndex(i)

    def _comp_page(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 6, 0)
        v.setSpacing(6)
        self.comp_buttons = []
        for group, entries in COMPONENTS:
            h = QLabel(group)
            h.setObjectName("head")
            v.addWidget(h)
            for key, text, glyph in entries:
                b = CompButton(key, text, glyph)
                b.clicked.connect(lambda _=False, k=key: self._add(k))
                self.comp_buttons.append(b)
                v.addWidget(b)
        v.addStretch()
        return self._wrap(w)

    def _add(self, key):
        self.preview.items.append({"key": key})
        self.preview.rebuild()

    def _refresh_buttons(self):
        used = {i["key"] for i in self.preview.items}
        for b in self.comp_buttons:
            b.setEnabled(b.key not in used)

    # ---- swatches
    def _build_sw_list(self):
        old = self.sw_list.layout()
        if old:
            QWidget().setLayout(old)
        v = QVBoxLayout(self.sw_list)
        v.setContentsMargins(0, 4, 6, 0)
        v.setSpacing(8)
        add = pill("+   Add", "ghost")
        m = QMenu(add)
        m.addAction("Import Swatches", self._import)
        m.addAction("Import Image", self._import_image)
        m.addAction("New Swatch Group", self._new_group)
        add.setMenu(m)
        v.addWidget(add)
        for name, cols in self.state.palettes.items():
            box = QFrame()
            box.setStyleSheet("QFrame{background:#232A3C; border-radius:10px}")
            bv = QVBoxLayout(box)
            bv.setContentsMargins(10, 6, 8, 10)
            row = QHBoxLayout()
            t = pill(("●  " if name == self.state.current_palette else "") + name, "link")
            t.clicked.connect(lambda _=False, n=name: self._select(n))
            row.addWidget(t, 1)
            for kind, tip, fn in (("edit", "Переименовать", self._rename), ("close", "Удалить", self._delete)):
                b = IconButton(kind, box, 22, tip)
                b.clicked.connect(lambda _=False, n=name, f=fn: f(n))
                row.addWidget(b)
            ex = IconButton("menu", box, 22, "Экспорт")
            ex.clicked.connect(lambda _=False, n=name: self._export(n))
            row.addWidget(ex)
            bv.addLayout(row)
            bv.addWidget(MiniGrid(cols))
            v.addWidget(box)
        v.addStretch()

    def _select(self, n):
        self.state.current_palette = n
        self.state.palettesChanged.emit()

    def _unique(self, name):
        base, k = name, 2
        while name in self.state.palettes:
            name, k = f"{base} {k}", k + 1
        return name

    def _new_group(self, colors=None, name=None):
        name = name or QInputDialog.getText(self, "Новая группа", "Имя:")[0]
        if not name:
            return
        name = self._unique(name)
        self.state.palettes[name] = list(colors or [])
        self.state.current_palette = name
        self.state.palettesChanged.emit()

    def _rename(self, old):
        new, ok = QInputDialog.getText(self, "Переименовать", "Имя:", text=old)
        if ok and new and new not in self.state.palettes:
            self.state.palettes = {(new if k == old else k): v for k, v in self.state.palettes.items()}
            if self.state.current_palette == old:
                self.state.current_palette = new
            self.state.palettesChanged.emit()

    def _delete(self, n):
        if len(self.state.palettes) <= 1:
            return
        del self.state.palettes[n]
        if self.state.current_palette == n:
            self.state.current_palette = next(iter(self.state.palettes))
        self.state.palettesChanged.emit()

    def _import(self):
        path, _ = QFileDialog.getOpenFileName(self, "Импорт палитры", "", "Palettes (*.gpl *.json *.txt *.hex)")
        if path:
            cols = parse_palette(path)
            if cols:
                self._new_group(cols, os.path.splitext(os.path.basename(path))[0])

    def _export(self, n):
        path, _ = QFileDialog.getSaveFileName(self, "Экспорт", n + ".gpl",
                                              "GIMP/Krita palette (*.gpl);;JSON (*.json);;HEX (*.txt)")
        if path:
            write_palette(path, n, self.state.palettes[n])

    # ---- extract
    def _extract_page(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 4, 6, 0)
        v.setSpacing(10)
        back = pill("‹   Extract Colors from Image", "link")
        back.clicked.connect(lambda: self.sw_stack.setCurrentIndex(0))
        v.addWidget(back)
        self.ex_img = QLabel()
        self.ex_img.setAlignment(Qt.AlignCenter)
        self.ex_img.setMinimumHeight(160)
        v.addWidget(self.ex_img)
        lab = QLabel("Extraction Accuracy")
        lab.setObjectName("head")
        v.addWidget(lab)
        self.ex_acc = QSlider(Qt.Horizontal)
        self.ex_acc.setRange(1, 100)
        self.ex_acc.setValue(60)
        self.ex_acc.sliderReleased.connect(self._run_extract)
        v.addWidget(self.ex_acc)
        row = QHBoxLayout()
        l2 = QLabel("Количество цветов")
        l2.setObjectName("head")
        row.addWidget(l2)
        self.ex_n = QSpinBox()
        self.ex_n.setRange(2, 48)
        self.ex_n.setValue(16)
        self.ex_n.valueChanged.connect(lambda _: self._run_extract())
        row.addWidget(self.ex_n)
        v.addLayout(row)
        self.ex_grid = MiniGrid([], 20)
        v.addWidget(self.ex_grid)
        save = pill("Save to Swatches", "primary")
        save.clicked.connect(self._save_extract)
        v.addWidget(save)
        v.addStretch()
        self.ex_path = None
        return self._wrap(w)

    def _import_image(self):
        path, _ = QFileDialog.getOpenFileName(self, "Изображение", "",
                                              "Images (*.png *.jpg *.jpeg *.bmp *.webp *.tif *.tiff)")
        if not path:
            return
        self.ex_path = path
        pm = QPixmap(path).scaled(270, 190, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        r = QPixmap(pm.size())
        r.fill(Qt.transparent)
        p = QPainter(r)
        p.setRenderHint(QPainter.Antialiasing)
        p.setClipPath(card_path(QRectF(r.rect()), 10))
        p.drawPixmap(0, 0, pm)
        p.end()
        self.ex_img.setPixmap(r)
        self.sw_stack.setCurrentIndex(1)
        self._run_extract()

    def _run_extract(self):
        if not self.ex_path:
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self.ex_grid.colors = extract_colors(self.ex_path, self.ex_n.value(), self.ex_acc.value())
        finally:
            QApplication.restoreOverrideCursor()
        self.ex_grid.setFixedHeight(self.ex_grid._h(max(self.ex_grid.width(), 250)))
        self.ex_grid.update()

    def _save_extract(self):
        if self.ex_grid.colors:
            self._new_group(self.ex_grid.colors, os.path.splitext(os.path.basename(self.ex_path))[0])
            self.sw_stack.setCurrentIndex(0)


# ============================================================== main
def main():
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName("Dynamic Color Picker")
    app.setQuitOnLastWindowClosed(False)
    app.setStyle("Fusion")
    app.setStyleSheet(QSS)
    w = FloatingPanel()
    w.show()
    app.aboutToQuit.connect(w.save)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
