#!/usr/bin/env python3
"""
Dynamic Color Picker — плавающая модульная панель цвета для Clip Studio Paint и Photoshop.

Зависимости:  pip install PySide6 numpy
Опционально:  opencv-python (QR CSP с экрана), pynput (всплытие у пера), pywin32 (Photoshop)
Запуск:       python dynamic_color_picker.py
"""
import sys, os, json, math, copy, time, colorsys

import numpy as np
from PySide6.QtCore import Qt, Signal, QObject, QTimer, QPointF, QRectF, QPoint, QRect, QMimeData, QSize
from PySide6.QtGui import (QColor, QPainter, QImage, QPen, QBrush, QLinearGradient, QCursor, QAction,
                           QDrag, QGuiApplication, QPainterPath, QPixmap, QIcon, QFont, QConicalGradient)
from PySide6.QtWidgets import (QApplication, QWidget, QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
                               QPushButton, QAbstractButton, QMenu, QScrollArea, QStackedWidget, QSlider,
                               QSpinBox, QFileDialog, QInputDialog, QMessageBox, QLineEdit, QCheckBox,
                               QSystemTrayIcon, QFormLayout, QSizePolicy, QFrame, QComboBox)

from dcp_core import *          # цветовая математика, ColorState, палитры, CSPLink
from dcp_core import APP_VERSION
import csp_companion as cspc
from dcp_formats import import_palettes, export_palette, IMPORT_FILTER, EXPORT_FILTER
from dcp_hotkeys import HotkeyManager, ACTIONS, DEFAULT_BINDINGS, combo_name

# ============================================================== theme
from string import Template

THEMES = {
    "dark": dict(CARD="#1D2333", CARD_TOP="#202739", CARD2="#283044", TAB_OFF="#141927", TAB_ON="#1F2638",
                 LINE="#323B55", TXT="#C9D1E4", DIM="#7B859E", TITLE="#FFFFFF", ICON="#AEB7CC", ICON_HI="#E3E8F5",
                 BOX="#232A3C", BTN="#262D40", BTN_HI="#2F3852", BTN_DIS="#20263A", TXT_DIS="#565F7C",
                 MENU="#1E2434", CHK1="#3A4256", CHK2="#5A6378", GROOVE="#2A3146", BORDER="#333C55",
                 SCROLL="#3A4360", LOGO="#8A94AD", HOVER="#12FFFFFF", SHADOW_A="7"),
    "light": dict(CARD="#ECEFF5", CARD_TOP="#FAFBFD", CARD2="#E0E5EE", TAB_OFF="#D3D9E3", TAB_ON="#F7F8FB",
                  LINE="#CBD2DE", TXT="#2B3245", DIM="#77819A", TITLE="#111827", ICON="#5B6479", ICON_HI="#1F2937",
                  BOX="#E3E8F0", BTN="#E0E5EE", BTN_HI="#D3DAE6", BTN_DIS="#EBEEF3", TXT_DIS="#A3ABBD",
                  MENU="#FFFFFF", CHK1="#C9CFDA", CHK2="#EEF1F5", GROOVE="#D3D9E3", BORDER="#CBD2DE",
                  SCROLL="#B9C1D0", LOGO="#6B7590", HOVER="#12000000", SHADOW_A="4"),
}
ACCENT = QColor("#2F6BFF")
TABW, SHADOW, PAD, HEADER = 26, 12, 14, 44
MAX_PANELS = 4

QSS_T = Template("""
* { color:$TXT; font-family:'Segoe UI','Inter',sans-serif; font-size:9pt; }
QMenu { background:$MENU; border:1px solid $BORDER; border-radius:8px; padding:5px; }
QMenu::item { padding:6px 22px 6px 14px; border-radius:5px; }
QMenu::item:selected { background:#2F6BFF; color:white; }
QMenu::item:disabled { color:$TXT_DIS; }
QMenu::separator { height:1px; background:$BORDER; margin:4px 8px; }
QMenu::indicator { width:0; }
QToolTip { background:$MENU; color:$TXT; border:1px solid $BORDER; padding:4px; }
QPushButton#pill { background:$BTN; border:none; border-radius:8px; padding:9px 12px; text-align:left; }
QPushButton#pill:hover { background:$BTN_HI; }
QPushButton#pill:disabled { color:$TXT_DIS; background:$BTN_DIS; }
QPushButton#primary { background:#2F6BFF; color:white; border:none; border-radius:8px; padding:9px; font-weight:600; }
QPushButton#primary:hover { background:#4A7DFF; }
QPushButton#ghost { background:$BTN; border:none; border-radius:8px; padding:9px; }
QPushButton#ghost:hover { background:$BTN_HI; }
QPushButton#ghost:checked { background:#2F6BFF; color:white; }
QPushButton#key { background:$BTN; border:1px solid $BORDER; border-radius:6px; padding:5px 8px; font-weight:600; }
QPushButton#key:hover { border-color:#2F6BFF; }
QPushButton#tab { background:transparent; border:none; border-bottom:2px solid transparent; padding:8px 4px; color:$DIM; font-weight:600; }
QPushButton#tab:checked { color:$TITLE; border-bottom:2px solid #2F6BFF; }
QPushButton#link { background:transparent; border:none; color:$TXT; font-weight:600; text-align:left; padding:4px 0; }
QLabel#head { color:$DIM; font-size:8pt; padding-top:6px; }
QLabel#title { color:$TITLE; font-weight:600; }
QLabel#big { color:$TITLE; font-size:16pt; font-weight:600; background:$BTN; border-radius:8px; padding:6px 10px; }
QFrame#box { background:$BOX; border-radius:10px; }
QSlider::groove:horizontal { height:6px; background:$GROOVE; border-radius:3px; }
QSlider::sub-page:horizontal { background:#2F6BFF; border-radius:3px; }
QSlider::handle:horizontal { background:white; border:1px solid $BORDER; width:14px; height:14px; margin:-5px 0; border-radius:8px; }
QLineEdit, QSpinBox, QComboBox { background:$BTN; border:1px solid $BORDER; border-radius:6px; padding:4px 6px; }
QComboBox::drop-down { border:none; width:18px; }
QComboBox QAbstractItemView { background:$MENU; border:1px solid $BORDER; selection-background-color:#2F6BFF; selection-color:white; outline:0; }
QScrollArea { background:transparent; border:none; }
QScrollArea > QWidget > QWidget { background:transparent; }
QScrollBar:vertical { width:6px; background:transparent; margin:0; }
QScrollBar::handle:vertical { background:$SCROLL; border-radius:3px; min-height:30px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height:0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background:transparent; }
QCheckBox { spacing:8px; }
QCheckBox::indicator { width:14px; height:14px; border-radius:4px; background:$BTN; border:1px solid $SCROLL; }
QCheckBox::indicator:checked { background:#2F6BFF; border-color:#2F6BFF; }
""")


def apply_theme(name):
    """Переключает тему: глобальные цвета для отрисовки + таблица стилей."""
    t = THEMES.get(name, THEMES["dark"])
    g = globals()
    for k, v in t.items():
        g[k] = int(v) if k == "SHADOW_A" else QColor(v)
    app = QApplication.instance()
    if app:
        app.setStyleSheet(QSS_T.substitute(**t))


apply_theme("dark")


def card_path(r, radius=16):
    path = QPainterPath()
    path.addRoundedRect(r, radius, radius)
    return path


def paint_card(p, r, radius=16, glow=True):
    """Тёмная карточка с мягкой тенью и синей подсветкой верхнего края (как у TourBox)."""
    p.setPen(Qt.NoPen)
    for i in range(SHADOW, 0, -2):
        p.setBrush(QColor(0, 0, 0, int(SHADOW_A * (SHADOW - i + 2) / 2)))
        p.drawRoundedRect(r.adjusted(-i, -i + 3, i, i + 3), radius + i, radius + i)
    g = QLinearGradient(r.topLeft(), r.bottomLeft())
    g.setColorAt(0, CARD_TOP)
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
            p.setBrush(HOVER)
            p.drawRoundedRect(QRectF(0, 0, w, h), 6, 6)
        col = ACCENT if self.isChecked() else (ICON_HI if self._hover else ICON)
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
            p.setBrush(SCROLL if not self._hover else QColor("#E5484D"))
            p.drawEllipse(QPointF(cx, cy), w / 2 - 1, h / 2 - 1)
            p.setPen(QPen(QColor("white"), 1.8, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(QPointF(cx - 4, cy), QPointF(cx + 4, cy))
        elif k == "edit":
            p.drawLine(QPointF(cx - 5, cy + 5), QPointF(cx + 5, cy - 5))
            p.drawLine(QPointF(cx - 6, cy + 6), QPointF(cx - 3, cy + 6))
        elif k == "eyedropper":
            p.drawLine(QPointF(cx - 6, cy + 6), QPointF(cx + 2, cy - 2))
            p.drawLine(QPointF(cx - 7, cy + 7), QPointF(cx - 6, cy + 6))
            p.setBrush(col)
            p.drawEllipse(QPointF(cx + 4, cy - 4), 3.2, 3.2)
            p.drawLine(QPointF(cx, cy - 6), QPointF(cx + 6, cy))
        elif k == "refresh":
            p.drawArc(QRectF(cx - 6, cy - 6, 12, 12), 60 * 16, 280 * 16)
            p.drawLine(QPointF(cx + 3, cy - 6), QPointF(cx + 6, cy - 5))
            p.drawLine(QPointF(cx + 3, cy - 6), QPointF(cx + 4, cy - 2))
        elif k == "area":
            pen.setStyle(Qt.DashLine)
            p.setPen(pen)
            p.drawRoundedRect(QRectF(cx - 7, cy - 5, 14, 10), 2, 2)
        elif k == "save":
            p.drawRoundedRect(QRectF(cx - 6, cy - 6, 12, 12), 2, 2)
            p.drawLine(QPointF(cx - 3, cy - 6), QPointF(cx - 3, cy - 2))
            p.drawLine(QPointF(cx - 3, cy - 2), QPointF(cx + 3, cy - 2))
            p.drawLine(QPointF(cx + 3, cy - 2), QPointF(cx + 3, cy - 6))


# ============================================================== components
class Comp(QWidget):
    KEY = ""

    def __init__(self, app, opts=None):
        super().__init__()
        self.app, self.state, self.opts = app, app.state, dict(opts or {})
        self._wheel_acc = 0.0

    def heightFor(self, w):
        return 40

    def adjust(self, step, pos):
        """HoverAdjust: колёсико / диск над компонентом. Вернуть True, если обработано."""
        return False

    def wheelEvent(self, e):
        d = e.angleDelta().y() or e.angleDelta().x()
        self._wheel_acc += d / 120
        steps = int(self._wheel_acc)
        if steps == 0:
            e.accept()
            return
        self._wheel_acc -= steps
        if e.modifiers() & Qt.ShiftModifier:
            steps *= 5
        if self.adjust(steps, e.position()):
            e.accept()
        else:
            e.ignore()


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
        self.shape = self.opts.get("shape", "wheel")
        self.h, self.s, self.y = rgb_to_model(self.model, self.state.color())
        self._ring = self._shape = None
        self._ring_key = self._shape_key = None
        self._drag = None
        self._before = None
        self._mpos = QPointF()
        self.btn = IconButton("mode", self, 24, "Модель (HSV / HSL / V-HSV) и вид (круг / куб)")
        self.btn.clicked.connect(self._model_menu)
        self.state.changed.connect(self._on_state)

    def heightFor(self, w):
        return int(w * 0.9) if self.shape == "wheel" else int(w - 40 + 30)

    def resizeEvent(self, e):
        self.btn.move(self.width() - 26, self.height() - 24)

    def _model_menu(self):
        m = QMenu(self)
        for name in MODELS:
            a = m.addAction(("●  " if name == self.model else "    ") + name)
            a.triggered.connect(lambda _=False, n=name: self._set_model(n))
        m.addSeparator()
        for sh, label in (("wheel", "Цветовой круг"), ("cube", "Куб")):
            a = m.addAction(("●  " if sh == self.shape else "    ") + label)
            a.triggered.connect(lambda _=False, v=sh: self._set_shape(v))
        m.exec(self.btn.mapToGlobal(QPoint(0, self.btn.height())))

    def _set_shape(self, v):
        self.shape = self.opts["shape"] = v
        self._shape_key = None
        self.app.relayout()
        self.update()

    def cycle_model(self):
        self._set_model(MODELS[(MODELS.index(self.model) + 1) % len(MODELS)])

    def adjust(self, step, pos):
        self.h = (self.h + step / 360) % 1
        self.state.set_color(model_to_rgb(self.model, self.h, self.s, self.y), self, True)
        self.update()
        return True

    # ---- cube geometry: плоскость + вертикальная полоса оттенков
    def _cube_geo(self):
        w = self.width()
        side = max(40, min(w - 40, self.height() - 30))
        plane = QRectF((w - side - 28) / 2, 2, side, side)
        strip = QRectF(plane.right() + 12, 2, 16, side)
        return plane, strip

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
        return hue_angle(self.h) if self.model == "HSL" and self.shape == "wheel" else 0.0

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
        tri = self.model == "HSL" and self.shape == "wheel"
        n = int(2 * ri) if tri else (int(ri) if self.shape == "cube" else int(ri * math.sqrt(2) * 0.97))
        key = (round(self.h, 4), self.model, n, self.shape)
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

    def _paint_cube(self, p):
        plane, strip = self._cube_geo()
        img = self._shape_img(plane.width())
        p.save()
        p.setClipPath(card_path(plane, 8))
        if img:
            p.drawImage(plane, img)
        p.restore()
        mx, my = plane.left() + self.s * plane.width(), plane.top() + (1 - self.y) * plane.height()
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(0, 0, 0, 120), 3))
        p.drawEllipse(QPointF(mx, my), 6, 6)
        p.setPen(QPen(QColor("#F4F6FB"), 1.8))
        p.drawEllipse(QPointF(mx, my), 6, 6)
        g = QLinearGradient(strip.topLeft(), strip.bottomLeft())
        for k in range(13):
            g.setColorAt(k / 12, QColor.fromHsvF((k / 12) % 1 * 0.9999, 1, 1))
        p.setPen(Qt.NoPen)
        p.setBrush(g)
        p.drawRoundedRect(strip, 8, 8)
        y = strip.top() + self.h * strip.height()
        kr = QRectF(strip.left() - 3, y - 5, strip.width() + 6, 10)
        p.setBrush(QColor.fromHsvF(self.h % 1.0, 1, 1))
        p.setPen(QPen(QColor(0, 0, 0, 110), 4))
        p.drawRoundedRect(kr, 4, 4)
        p.setPen(QPen(QColor("#F4F6FB"), 2.2))
        p.drawRoundedRect(kr, 4, 4)
        if self._drag and self._before:
            draw_compare(p, self._mpos, self.state.color(), self._before, self.rect())

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        if self.shape == "cube":
            self._paint_cube(p)
            return
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
        if self.shape == "cube":
            plane, strip = self._cube_geo()
            pos = e.position()
            self._drag = "cplane" if plane.adjusted(-6, -6, 6, 6).contains(pos) else \
                ("cstrip" if strip.adjusted(-8, -6, 8, 6).contains(pos) else None)
            self._before = self.state.color()
            self._apply(pos, False)
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
        if self._drag in ("cplane", "cstrip"):
            plane, strip = self._cube_geo()
            if self._drag == "cplane":
                self.s = min(1, max(0, (pos.x() - plane.left()) / plane.width()))
                self.y = min(1, max(0, 1 - (pos.y() - plane.top()) / plane.height()))
            else:
                self.h = min(0.9999, max(0, (pos.y() - strip.top()) / strip.height()))
        elif self._drag == "ring":
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
    NEAR = 8

    def adjust(self, step, pos):
        self.L = min(100, max(0, self.L + step))
        self.state.set_color(lch_in_gamut(self.L, self.C, self.H), self, True)
        self.update()
        return True

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
        sr = self._slider_rect()
        if self.view == "focused":
            # подсвеченный диапазон близкой яркости (±NEAR L*)
            a = max(0, self.L - self.NEAR) / 100
            b = min(100, self.L + self.NEAR) / 100
            band = QRectF(sr.left() + a * sr.width() - 2, sr.top() - 5, (b - a) * sr.width() + 4, sr.height() + 10)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(255, 255, 255, 40))
            p.drawRoundedRect(band, 6, 6)
        draw_bar(p, sr, stops, self.L / 100, knob="rect")
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
                p.fillRect(r, CHK1)
                for yy in range(int(r.top()), int(r.bottom()) + 1, 4):
                    for xx in range(int(r.left()), int(r.right()) + 1, 4):
                        if ((xx // 4) + (yy // 4)) % 2:
                            p.fillRect(xx, yy, 4, 4, CHK2)
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
        self.setToolTip("Клик по числу — цифровая клавиатура. Колёсико над слайдером — точная настройка")
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
        if not 0 <= i < len(SPACES[self.space]):
            return
        if e.position().x() > self.width() - 46:
            name, lo, hi = SPACES[self.space][i]
            NumPad.open(self, f"{self.space} · {name}", self.vals[i], lo, hi,
                        lambda v, i=i: self._set_val(i, v), self.mapToGlobal(QPoint(self.width(), i * 26)))
            return
        self._drag = i
        self._apply(e.position(), False)

    def _set_val(self, i, v):
        self.vals[i] = v
        self.state.set_color(space_to_rgb(self.space, self.vals), self, True)
        self.update()

    def adjust(self, step, pos):
        i = int(pos.y() // 26)
        if not 0 <= i < len(SPACES[self.space]):
            return False
        name, lo, hi = SPACES[self.space][i]
        v = self.vals[i] + step
        self._set_val(i, (v % 360) if name == "H" else min(hi, max(lo, v)))
        return True

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
        self.setToolTip("История цветов. ПКМ — закрепить / удалить. Закреплённые не вытесняются")

    def heightFor(self, w):
        return 24

    def _cells(self):
        d = 20
        n = max(1, int((self.width() + 6) // (d + 6)))
        return [(QRectF(i * (d + 6) + 1, 2, d, d), hx, pin) for i, (hx, pin) in enumerate(self.state.history_view()[:n])]

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        cells = self._cells()
        if not cells:
            p.setPen(DIM)
            p.drawText(self.rect(), Qt.AlignVCenter | Qt.AlignLeft, "История пуста")
        for r, hx, pin in cells:
            p.setPen(QPen(QColor(255, 255, 255, 25), 1))
            p.setBrush(QColor(hx))
            if pin:
                p.drawRoundedRect(r, 5, 5)
                p.setPen(Qt.NoPen)
                p.setBrush(ACCENT)
                p.drawEllipse(QPointF(r.right() - 2, r.top() + 2), 3.2, 3.2)
            else:
                p.drawEllipse(r)

    def mousePressEvent(self, e):
        for r, hx, pin in self._cells():
            if r.contains(e.position()):
                if e.button() == Qt.RightButton:
                    m = QMenu(self)
                    m.addAction("Открепить" if pin else "Закрепить", lambda hx=hx: self.state.toggle_pin(hx))
                    m.addAction("Удалить", lambda hx=hx: self.state.remove_history(hx))
                    m.exec(e.globalPosition().toPoint())
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


EXTRA_COMPONENTS = {}   # заполняется dcp_extras


def make_comp(app, item):
    key, opts = item["key"], item.get("opts", {})
    if key.startswith("slider:"):
        return SliderComp(app, opts, key.split(":", 1)[1])
    cls = {"wheel": WheelComp, "luma": LumaComp, "fgbg": FGBGComp, "history": HistoryComp,
           "swatches": SwatchesComp}.get(key) or EXTRA_COMPONENTS.get(key)
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
            hint.setStyleSheet(f"color:{DIM.name()}; padding:30px")
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
    """Главное окно: парящая карточка без рамки с боковыми вкладками панелей (до 4)."""
    canvasUpdated = Signal(list)

    def __init__(self):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowTitle("Dynamic Color Picker")
        self.state = ColorState()
        self.state.csp = CSPLink(self.state)
        self.cfg = self._load()
        apply_theme(self.cfg.get("theme", "dark"))
        self._apply_state_cfg()
        self.layouts = (self.cfg.get("layouts") or [
            {"name": "1", "items": [{"key": "wheel"}, {"key": "history"}]},
            {"name": "2", "items": [{"key": "luma"}, {"key": "fgbg"}, {"key": "slider:CMYK"},
                                    {"key": "swatches"}, {"key": "history"}]},
        ])[:MAX_PANELS]
        self.cur = min(self.cfg.get("cur", 0), len(self.layouts) - 1)
        old_scale = {"S": 252, "M": 296, "L": 352}.get(self.cfg.get("scale"), 296)
        self.width_px = int(self.cfg.get("width_px", old_scale))
        self.max_len = int(self.cfg.get("max_len", 0))          # 0 = авто
        self.mode = self.cfg.get("mode", "pinned")              # follow | pinned
        self.side = self.cfg.get("side", "right")               # right | left | above | below | center
        pos = self.cfg.get("pinned_pos") or self.cfg.get("pos")
        self.pinned_pos = QPoint(*pos) if pos else None
        self.temp_pin = False                                     # сбрасывается при перезапуске
        self.popped = False
        self._drag_off = None
        self._call_t = 0.0
        self._call_nav = False

        self.logo = QLabel("dyna\nmic", self)
        f = self.logo.font()
        f.setPointSizeF(10)
        f.setWeight(QFont.Black)
        f.setLetterSpacing(QFont.PercentageSpacing, 92)
        self.logo.setFont(f)
        self.dot = QLabel("●", self)
        self.menu_btn = IconButton("menu", self, 26, "Меню")
        self.menu_btn.clicked.connect(self._menu)
        self.eye_btn = IconButton("eyedropper", self, 26, "Пипетка с экрана")
        self.eye_btn.clicked.connect(self.eyedropper)
        self.pin_btn = IconButton("pin", self, 26, "")
        self.pin_btn.setCheckable(True)
        self.pin_btn.clicked.connect(self._pin_clicked)
        self.scroll = QScrollArea(self)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.body = None
        self._restyle()
        self.build_body()

        self.state._commit.timeout.connect(self._on_commit)
        self.state.csp.statusChanged.connect(self._csp_status)
        self._csp_status(self.state.csp.text, False)

        self.keys = HotkeyManager()
        self.keys.pressed.connect(self.on_action_press, Qt.QueuedConnection)
        self.keys.released.connect(self.on_action_release, Qt.QueuedConnection)
        self._configure_keys()
        self._leave = QTimer(singleShot=True, interval=650)
        self._leave.timeout.connect(self._maybe_return)
        self._make_tray()
        self._sync_pin_btn()
        if self.pinned_pos:
            self.move(self.pinned_pos)
        else:
            g = QGuiApplication.primaryScreen().availableGeometry()
            self.move(g.right() - self.width() - 60, g.top() + 120)
            self.pinned_pos = self.pos()
        import dcp_extras as ex
        self.ex = ex
        self.watcher = ex.AppWatcher(self)
        self.watcher.appChanged.connect(self._on_app)
        self.updater = ex.Updater(self)
        self.updater.available.connect(self._update_available)
        self.updater.status.connect(lambda t: self.tray.showMessage("Dynamic Color Picker", t,
                                                                    QSystemTrayIcon.Information, 4000))
        self.updater.downloaded.connect(self._update_downloaded)
        if self.cfg.get("update_check", True):
            QTimer.singleShot(4000, self.updater.check)
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
        else:
            s.palettes = {"The Deepest Blue": ["#F2D6C9", "#F6C9B5", "#5EC8F2", "#3FB3F0", "#2D8CF0", "#2A6FE8",
                                               "#1F4FD8", "#2B2FB8", "#6A3FD0", "#B24FD8", "#E85A8A", "#E8434F"],
                          "Default": ["#000000", "#FFFFFF", "#E05A47", "#F2C14E", "#5B8E7D", "#3D5A80"]}
        s.current_palette = c.get("current_palette") if c.get("current_palette") in s.palettes else next(iter(s.palettes))
        s.history = c.get("history", [])
        s.pinned = c.get("pinned_history", [])
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
        c.pop("pos", None)
        c.pop("pinned", None)
        c.pop("scale", None)
        c.update({"layouts": self.layouts, "cur": self.cur, "width_px": self.width_px, "max_len": self.max_len,
                  "mode": self.mode, "side": self.side,
                  "pinned_pos": [self.pinned_pos.x(), self.pinned_pos.y()] if self.pinned_pos else None,
                  "palettes": s.palettes, "current_palette": s.current_palette, "history": s.history,
                  "pinned_history": s.pinned,
                  "fg": to_hex(s.fg), "bg": to_hex(s.bg)})
        json.dump(c, open(CONFIG_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    def _configure_keys(self):
        b = self.cfg.get("bindings")
        if b is None:
            b = dict(DEFAULT_BINDINGS)
            self.cfg["bindings"] = b
        self.keys.configure(b, self.cfg.get("suppress_keys", True), self.cfg.get("middle_click", False))

    def _restyle(self):
        self.logo.setStyleSheet(f"color:{LOGO.name()};")
        self.update()

    # ---------------- layout
    def body_width(self):
        return self.width_px

    def card_rect(self):
        return QRectF(SHADOW + TABW, SHADOW, self.width() - 2 * SHADOW - TABW, self.height() - 2 * SHADOW)

    def build_body(self):
        if self.body:
            self.layouts[self.cur]["items"] = self.body.items()
            self.body.hide()
            self.body.deleteLater()
        self.body = Body(self, self.layouts[self.cur]["items"])
        self.scroll.setWidget(self.body)
        self.scroll.setWidgetResizable(False)
        self.body.show()
        self.relayout()

    def relayout(self):
        if not self.body:
            return
        bw = self.body_width()
        self.body.relayout(bw)
        bh = self.body.height()
        view = min(bh, self.max_len) if self.max_len > 0 else bh
        sb = 10 if view < bh else 0
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded if sb else Qt.ScrollBarAlwaysOff)
        cw = bw + 2 * PAD + sb
        ch = HEADER + view + PAD + 4
        tabs_h = 56 + (len(self.layouts) + 1) * 38
        ch = max(ch, tabs_h)
        self.setFixedSize(int(cw + TABW + 2 * SHADOW), int(ch + 2 * SHADOW))
        cr = self.card_rect()
        self.scroll.setGeometry(int(cr.left() + PAD), int(cr.top() + HEADER), bw + sb, view)
        self.logo.move(int(cr.left() + 14), int(cr.top() + 8))
        self.logo.adjustSize()
        self.dot.move(int(cr.left() + 14 + self.logo.width() + 6), int(cr.top() + 14))
        self.dot.adjustSize()
        self.pin_btn.move(int(cr.right() - 36), int(cr.top() + 10))
        self.menu_btn.move(int(cr.right() - 66), int(cr.top() + 10))
        self.eye_btn.move(int(cr.right() - 96), int(cr.top() + 10))
        self.update()

    def _tab_rects(self):
        cr = self.card_rect()
        n = len(self.layouts)
        out = [QRectF(SHADOW + 2, cr.top() + 50 + i * 38, TABW + 10, 34) for i in range(n)]
        if n < MAX_PANELS:
            out.append(QRectF(SHADOW + 2, cr.top() + 50 + n * 38, TABW + 10, 28))
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
            p.setBrush(QColor(0, 0, 0, 40))
            p.drawRoundedRect(r.adjusted(-1, 1, 0, 2), 8, 8)
            p.setBrush(TAB_OFF)
            p.drawRoundedRect(r, 8, 8)
            p.setPen(DIM)
            p.drawText(QRectF(r.left(), r.top(), TABW - 2, r.height()), Qt.AlignCenter,
                       "+" if i == len(self.layouts) else self.layouts[i]["name"][:2])
        paint_card(p, self.card_rect())
        r = tabs[self.cur]
        p.setPen(Qt.NoPen)
        p.setBrush(TAB_ON)
        p.drawRoundedRect(r, 8, 8)
        p.drawRect(QRectF(r.right() - 10, r.top(), 12, r.height()))
        p.setPen(TITLE)
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

    def wheelEvent(self, e):
        # прокрутка вкладок колёсиком над боковыми вкладками
        if e.position().x() < self.card_rect().left():
            self.switch((self.cur + (1 if e.angleDelta().y() < 0 else -1)) % len(self.layouts))

    # ---------------- layouts
    def switch(self, i):
        if i == self.cur or not 0 <= i < len(self.layouts):
            return
        self.layouts[self.cur]["items"] = self.body.items()
        self.cur = i
        self.body.hide()
        self.body.deleteLater()
        self.body = None
        self.build_body()

    def next_panel(self, d=1):
        self.switch((self.cur + d) % len(self.layouts))

    def add_layout(self):
        if len(self.layouts) >= MAX_PANELS:
            return
        self.layouts[self.cur]["items"] = self.body.items()
        self.layouts.append({"name": str(len(self.layouts) + 1), "items": [{"key": "wheel"}]})
        self.switch(len(self.layouts) - 1)
        self.open_editor()

    def _tab_menu(self, i, gpos):
        m = QMenu(self)
        m.addAction("Переименовать", lambda: self._rename(i))
        d = m.addAction("Дублировать", lambda: self._dup(i))
        d.setEnabled(len(self.layouts) < MAX_PANELS)
        x = m.addAction("Удалить", lambda: self._del(i))
        x.setEnabled(len(self.layouts) > 1)
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
        self.layouts[self.cur]["items"] = self.body.items()
        self.layouts.pop(i)
        self.cur = min(self.cur, len(self.layouts) - 1)
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
        m.addSeparator()
        m.addAction("Настройки…", self.open_settings)
        m.addAction("Горячие клавиши…", lambda: self.open_settings(1))
        bk = m.addMenu("Резервная копия")
        bk.addAction("Экспорт настроек…", self.export_settings)
        bk.addAction("Импорт настроек…", self.import_settings)
        m.addAction("Проверить обновления", lambda: self.updater.check(manual=True))
        m.addSeparator()
        m.addAction(f"Dynamic Color Picker {APP_VERSION}").setEnabled(False)
        m.addAction("Скрыть", self.hide)
        m.addAction("Выход", self.quit)
        m.exec(self.menu_btn.mapToGlobal(QPoint(0, self.menu_btn.height() + 4)))

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

    def open_settings(self, tab=0):
        d = SettingsDialog(self, self.cfg, tab)
        self._leave.stop()
        if d.exec():
            v = d.values()
            self.cfg.update(v)
            self.mode, self.side = v["mode"], v["side"]
            self.width_px, self.max_len = v["width_px"], v["max_len"]
            apply_theme(v["theme"])
            self._restyle()
            self._configure_keys()
            self._sync_pin_btn()
            self.body.hide()
            self.body.deleteLater()
            self.body = None
            self.build_body()
            if self.mode == "pinned" and not self.isVisible():
                self._show_home()
            try:
                if v["autostart"] != self.ex.autostart_enabled():
                    self.ex.set_autostart(v["autostart"])
            except Exception as e:
                QMessageBox.warning(self, "Автозапуск", str(e))
        else:
            self._configure_keys()

    # ---------------- пипетка, холст, профили, резервная копия, обновления
    def eyedropper(self):
        pk = self.ex.ScreenPicker(self, "pick")
        pk.finished.connect(lambda c: c and self.state.set_color(c, None))

    def pick_under_cursor(self):
        c = self.ex.color_under_cursor()
        if c:
            self.state.set_color(c, None)

    def pick_canvas_area(self, count=None):
        pk = self.ex.ScreenPicker(self, "rect")

        def done(r):
            if r:
                self.cfg["canvas_rect"] = [r.x(), r.y(), r.width(), r.height()]
                self.scan_canvas(count)
        pk.finished.connect(done)

    def scan_canvas(self, count=None):
        count = count or self.cfg.get("canvas_count", 16)
        rr = self.cfg.get("canvas_rect")
        if rr:
            rect = QRect(*rr)
        elif self.watcher.last_rect is not None:
            rect = self.watcher.last_rect
        else:
            self.pick_canvas_area(count)
            return
        img = self.ex.grab_rect(rect)
        me = self.frameGeometry() if self.isVisible() else None
        mask = None
        if me is not None and me.intersects(rect):
            inter = me.intersected(rect).translated(-rect.x(), -rect.y())

            def mask(shape, inter=inter, rw=rect.width(), rh=rect.height()):
                h, w = shape[:2]
                m = np.ones((h, w), bool)
                sx, sy = w / rw, h / rh
                m[int(inter.top() * sy):int(inter.bottom() * sy) + 1, int(inter.left() * sx):int(inter.right() * sx) + 1] = False
                return m
        cols = extract_colors(img, count, 70, mask)
        self.cfg["canvas_colors"] = cols
        self.canvasUpdated.emit(cols)

    def _on_app(self, exe):
        prof = self.cfg.get("profiles", {})
        idx = prof.get(exe)
        if idx is not None and 0 <= idx < len(self.layouts):
            self.switch(idx)

    def export_settings(self):
        path, _ = QFileDialog.getSaveFileName(self, "Экспорт настроек", "DynamicColorPicker-settings.json", "JSON (*.json)")
        if path:
            self.ex.export_settings(self, path)

    def import_settings(self):
        path, _ = QFileDialog.getOpenFileName(self, "Импорт настроек", "", "JSON (*.json)")
        if not path:
            return
        try:
            self.ex.import_settings(path)
        except Exception as e:
            QMessageBox.warning(self, "Импорт настроек", str(e))
            return
        self.keys.stop()
        self.state.csp.disconnect()
        self.tray.hide()
        self.save = lambda: None          # не перезаписывать импортированный файл
        self.ex.restart_app()

    def _update_available(self, rel):
        tag = rel.get("tag_name", "")
        if tag == self.cfg.get("skip_version"):
            return
        box = QMessageBox(self)
        box.setWindowTitle("Обновление")
        box.setText(f"Доступна версия {tag} (у вас {APP_VERSION}).")
        box.setDetailedText(rel.get("body") or "")
        upd = box.addButton("Обновить", QMessageBox.AcceptRole)
        box.addButton("Позже", QMessageBox.RejectRole)
        skip = box.addButton("Пропустить версию", QMessageBox.DestructiveRole)
        box.exec()
        if box.clickedButton() is upd:
            if getattr(sys, "frozen", False):
                self.tray.showMessage("Dynamic Color Picker", "Загрузка обновления…", QSystemTrayIcon.Information, 3000)
                self.updater.download(rel)
            else:
                from PySide6.QtGui import QDesktopServices
                from PySide6.QtCore import QUrl
                QDesktopServices.openUrl(QUrl(rel.get("html_url", "")))
        elif box.clickedButton() is skip:
            self.cfg["skip_version"] = tag

    def _update_downloaded(self, path):
        self.save()
        self.keys.stop()
        self.state.csp.disconnect()
        self.tray.hide()
        self.ex.Updater.install(path)

    def _csp_status(self, text, ok):
        self.dot.setStyleSheet(f"color:{'#2ECC71' if ok else SCROLL.name()}; font-size:9pt;")
        self.dot.setToolTip("CSP: " + text)

    def _on_commit(self):
        if self.cfg.get("ps_sync"):
            ps_set(self.state)

    # ---------------- display modes
    def _sync_pin_btn(self):
        perm = self.mode == "pinned"
        self.pin_btn.setChecked(perm or self.temp_pin)
        self.pin_btn.setToolTip("Постоянное закрепление (меняется в настройках)" if perm else
                                ("Временно закреплено — до перезапуска" if self.temp_pin else
                                 "Временно закрепить панель на экране"))

    def _pin_clicked(self):
        if self.mode == "pinned":
            self._sync_pin_btn()
            return
        self.temp_pin = not self.temp_pin
        if self.temp_pin:
            self.popped = False
            self.pinned_pos = self.pos()
        self._sync_pin_btn()

    def _stays(self):
        return self.mode == "pinned" or self.temp_pin

    def _cursor_over(self):
        return self.isVisible() and self.card_rect().translated(self.pos()).contains(QPointF(QCursor.pos()))

    def pop_at_cursor(self):
        cur = QCursor.pos()
        scr = (QGuiApplication.screenAt(cur) or QGuiApplication.primaryScreen()).availableGeometry()
        w, h, gap = self.width(), self.height(), 22
        x, y = {
            "right": (cur.x() + gap - SHADOW, cur.y() - h // 3),
            "left": (cur.x() - gap - w + SHADOW, cur.y() - h // 3),
            "above": (cur.x() - w // 2, cur.y() - gap - h + SHADOW),
            "below": (cur.x() - w // 2, cur.y() + gap - SHADOW),
            "center": (cur.x() - w // 2, cur.y() - h // 2),
        }.get(self.side, (cur.x() + gap, cur.y() - h // 3))
        x = min(max(scr.left() - SHADOW, x), scr.right() - w + SHADOW)
        y = min(max(scr.top() - SHADOW, y), scr.bottom() - h + SHADOW)
        self.popped = True
        self.move(x, y)
        self.show()
        self.raise_()
        self.activateWindow()

    def _return_home(self):
        self.popped = False
        self._leave.stop()
        if self._stays():
            if self.pinned_pos:
                self.move(self.pinned_pos)
            self.show()
        else:
            self.hide()

    def _show_home(self):
        self.popped = False
        if self.pinned_pos:
            self.move(self.pinned_pos)
        self.show()
        self.raise_()

    def toggle_visible(self):
        if self.isVisible() and not self.popped:
            self.hide()
        elif self._stays():
            self._show_home()
        else:
            self.pop_at_cursor()

    def call_press(self):
        self._call_t = time.monotonic()
        self._call_nav = False
        if self._cursor_over():
            self.next_panel()                 # быстрая навигация: кнопка над панелью — следующая панель
            self._call_nav = True
            return
        if self.popped:
            self._return_home()
            self._call_nav = True
            return
        if self.mode == "pinned" and not self.temp_pin:
            self._call_nav = True
            self.toggle_visible()             # постоянное закрепление: показать / скрыть
            return
        self.pop_at_cursor()                  # Follow / временное закрепление: всплыть у пера

    def call_release(self):
        if self._call_nav or not self.popped:
            return
        if time.monotonic() - self._call_t > 0.35:   # удерживали — при отпускании прячем/возвращаем
            self._return_home()
        # короткое нажатие: панель остаётся, пока перо не уйдёт (или Esc / повторное нажатие)

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

    # ---------------- hotkey actions
    def on_action_press(self, act):
        s = self.state
        if act == "call":
            self.call_press()
        elif act == "toggle":
            self.toggle_visible()
        elif act == "next_panel":
            self.next_panel(1)
        elif act == "prev_panel":
            self.next_panel(-1)
        elif act.startswith("panel_"):
            self.switch(int(act[-1]) - 1)
        elif act in ("adjust_up", "adjust_down"):
            self.hover_adjust(1 if act == "adjust_up" else -1)
        elif act in ("hue_up", "hue_down"):
            self._nudge("hue", 3 if act == "hue_up" else -3)
        elif act in ("luma_up", "luma_down"):
            self._nudge("luma", 2 if act == "luma_up" else -2)
        elif act in ("sat_up", "sat_down"):
            self._nudge("sat", 0.03 if act == "sat_up" else -0.03)
        elif act == "swap":
            s.swap()
        elif act == "select_fg":
            s.set_active("fg")
        elif act == "select_bg":
            s.set_active("bg")
        elif act == "transparent":
            s.transparent = not s.transparent
            s.changed.emit(None)
        elif act == "cycle_model":
            for c in self.body.comps:
                if isinstance(c, WheelComp):
                    c.cycle_model()
        elif act == "add_swatch":
            s.palettes.setdefault(s.current_palette, []).append(to_hex(s.color()))
            s.palettesChanged.emit()
        elif act == "pin":
            self._pin_clicked()
        elif act == "eyedropper":
            self.eyedropper()
        elif act == "pick_under_cursor":
            self.pick_under_cursor()
        elif act == "scan_canvas":
            self.scan_canvas()

    def on_action_release(self, act):
        if act == "call":
            self.call_release()

    def hover_adjust(self, step):
        """Диск/клавиши HoverAdjust: элемент под курсором, иначе — оттенок."""
        w = QApplication.widgetAt(QCursor.pos())
        while w is not None and not isinstance(w, Comp):
            w = w.parentWidget()
        if w is not None and w.adjust(step, QPointF(w.mapFromGlobal(QCursor.pos()))):
            return
        self._nudge("hue", step * 2)

    def _nudge(self, what, d):
        s = self.state
        rgb = s.color()
        if what == "luma":
            L, a, b = rgb2lab(np.array(rgb))
            C, H = math.hypot(a, b), math.degrees(math.atan2(b, a))
            s.set_color(lch_in_gamut(min(100, max(0, L + d)), C, H), None, True)
            return
        h, sat, v = colorsys.rgb_to_hsv(*rgb)
        if what == "hue":
            for c in self.body.comps:
                if isinstance(c, WheelComp):
                    h = c.h
            h = (h + d / 360) % 1
        else:
            sat = min(1, max(0, sat + d))
        s.set_color(colorsys.hsv_to_rgb(h, sat, v), None, True)

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
        res = os.path.join(getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__))), "icon.png")
        icon = QIcon(res) if os.path.exists(res) else QIcon(pm)
        QApplication.instance().setWindowIcon(icon)
        self.tray = QSystemTrayIcon(icon, self)
        m = QMenu()
        m.addAction("Показать панель", self._show_home)
        m.addAction("Настройки…", self.open_settings)
        m.addAction("Подключение к CSP…", self.open_csp)
        m.addSeparator()
        m.addAction("Выход", self.quit)
        self.tray.setContextMenu(m)
        self.tray.activated.connect(lambda r: self._show_home() if r == QSystemTrayIcon.Trigger else None)
        self.tray.setToolTip("Dynamic Color Picker")
        self.tray.show()

    def start(self):
        if self.mode == "pinned":
            self._show_home()
        else:
            combo = combo_name(self.cfg.get("bindings", {}).get("call", ""))
            self.tray.showMessage("Dynamic Color Picker", f"Follow Mode. Вызов панели: {combo}",
                                  QSystemTrayIcon.Information, 4000)

    def quit(self):
        self.save()
        self.keys.stop()
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
        hint.setStyleSheet(f"color:{DIM.name()}")
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
    """Настройки: режимы отображения, горячие клавиши, внешний вид."""

    def __init__(self, panel, cfg, tab=0):
        super().__init__(panel, "Настройки")
        self.panel, self.cfg = panel, cfg
        self.setFixedWidth(540)
        self.bindings = dict(cfg.get("bindings") or DEFAULT_BINDINGS)
        tabs = QHBoxLayout()
        self.tab_btns = []
        for i, name in enumerate(("Режимы", "Горячие клавиши", "Вид", "Система")):
            b = pill(name, "tab")
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, i=i: self._tab(i))
            tabs.addWidget(b)
            self.tab_btns.append(b)
        tabs.addStretch()
        self.outer.addLayout(tabs)
        self.stack = QStackedWidget()
        self.stack.addWidget(self._modes_page())
        self.stack.addWidget(self._keys_page())
        self.stack.addWidget(self._look_page())
        self.stack.addWidget(self._system_page())
        self.outer.addWidget(self.stack)
        row = QHBoxLayout()
        c = pill("✕", "ghost")
        c.clicked.connect(self.reject)
        ok = pill("✓", "primary")
        ok.clicked.connect(self.accept)
        row.addWidget(c)
        row.addWidget(ok, 2)
        self.outer.addLayout(row)
        avail = 540 - 2 * (SHADOW + 16)
        self.stack.setMinimumHeight(max(self.stack.widget(i).layout().totalHeightForWidth(avail)
                                        for i in range(self.stack.count())))
        self._tab(tab)
        self.panel.keys.recorded.connect(self._recorded, Qt.QueuedConnection)
        self._rec_action = None
        self.center_on(panel)

    def _tab(self, i):
        for k, b in enumerate(self.tab_btns):
            b.setChecked(k == i)
        self.stack.setCurrentIndex(i)
        self.adjustSize()

    @staticmethod
    def _combo(items, current):
        cb = QComboBox()
        for key, label in items:
            cb.addItem(label, key)
        keys = [k for k, _ in items]
        cb.setCurrentIndex(keys.index(current) if current in keys else 0)
        return cb

    def _head(self, text):
        l = QLabel(text)
        l.setObjectName("head")
        return l

    def _note(self, text):
        l = QLabel(text)
        l.setWordWrap(True)
        l.setStyleSheet(f"color:{DIM.name()}")
        return l

    # ---- Режимы
    def _modes_page(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.addWidget(self._head("Режим отображения"))
        self.mode = self._combo([("follow", "Follow Mode — панель у пера по кнопке вызова"),
                                 ("pinned", "Pinned Mode — панель всегда на экране")], self.cfg.get("mode", "pinned"))
        v.addWidget(self.mode)
        v.addWidget(self._note(
            "Follow: держите кнопку вызова — панель у пера, отпустили — исчезла. Короткое нажатие оставляет "
            "панель, пока перо не уйдёт с неё.\n"
            "📌 на панели — временное закрепление: панель можно двигать, кнопка вызова всё равно приносит её "
            "к перу, после отпускания она возвращается. Сбрасывается при перезапуске.\n"
            "Pinned: кнопка вызова показывает / скрывает панель.\n"
            "Кнопка вызова, когда курсор над панелью, листает панели 1–4."))
        v.addWidget(self._head("С какой стороны от курсора появляться"))
        self.side = self._combo([("right", "Справа"), ("left", "Слева"), ("above", "Сверху"),
                                 ("below", "Снизу"), ("center", "По центру курсора")], self.cfg.get("side", "right"))
        v.addWidget(self.side)
        self.autoret = QCheckBox("Прятать после короткого нажатия, когда перо уходит с панели")
        self.autoret.setChecked(self.cfg.get("auto_return", True))
        self.recon = QCheckBox("Автоподключение к CSP при запуске")
        self.recon.setChecked(self.cfg.get("csp_autoreconnect", True))
        v.addSpacing(6)
        v.addWidget(self.autoret)
        v.addWidget(self.recon)
        v.addStretch()
        return w

    # ---- Горячие клавиши
    def _keys_page(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        if not self.panel.keys.available:
            v.addWidget(self._note("⚠ Пакет pynput не найден — глобальные клавиши недоступны."))
        v.addWidget(self._note("Нажмите на кнопку справа и затем клавишу или сочетание на отдельной клавиатуре. "
                               "Esc — отмена, × — очистить. Лучше всего подходят F13–F24 и клавиши, "
                               "не занятые в CSP."))
        inner = QWidget()
        g = QGridLayout(inner)
        g.setContentsMargins(0, 0, 8, 0)
        g.setVerticalSpacing(5)
        self.key_btns = {}
        g.setColumnStretch(0, 1)
        for r, (act, label) in enumerate(ACTIONS):
            lab = QLabel(label)
            lab.setWordWrap(True)
            g.addWidget(lab, r, 0)
            b = pill(combo_name(self.bindings.get(act, "")), "key")
            b.setMinimumWidth(120)
            b.clicked.connect(lambda _=False, a=act: self._start_rec(a))
            g.addWidget(b, r, 1)
            x = IconButton("close", inner, 22, "Очистить")
            x.clicked.connect(lambda _=False, a=act: self._set_binding(a, ""))
            g.addWidget(x, r, 2)
            self.key_btns[act] = b
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        sa.setWidget(inner)
        sa.setFixedHeight(320)
        v.addWidget(sa)
        self.suppress = QCheckBox("Не передавать назначенные клавиши в CSP и другие программы")
        self.suppress.setChecked(self.cfg.get("suppress_keys", True))
        self.middle = QCheckBox("Средняя / боковая кнопка пера = вызов панели")
        self.middle.setChecked(self.cfg.get("middle_click", False))
        v.addWidget(self.suppress)
        v.addWidget(self.middle)
        return w

    def _start_rec(self, act):
        if self._rec_action:
            self.key_btns[self._rec_action].setText(combo_name(self.bindings.get(self._rec_action, "")))
        self._rec_action = act
        self.key_btns[act].setText("Нажмите клавиши…")
        self.panel.keys.record()

    def _recorded(self, combo):
        act = self._rec_action
        self._rec_action = None
        if not act:
            return
        if combo:
            self._set_binding(act, combo)
        else:
            self.key_btns[act].setText(combo_name(self.bindings.get(act, "")))

    def _set_binding(self, act, combo):
        if combo:
            for a, c in list(self.bindings.items()):
                if c == combo and a != act:
                    self.bindings[a] = ""
                    self.key_btns[a].setText("—")
        self.bindings[act] = combo
        self.key_btns[act].setText(combo_name(combo))

    # ---- Вид
    def _look_page(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.addWidget(self._head("Тема"))
        self.theme = self._combo([("dark", "Тёмная"), ("light", "Светлая")], self.cfg.get("theme", "dark"))
        v.addWidget(self.theme)
        v.addWidget(self._head("Ширина панели"))
        self.width_s, wl = self._slider(200, 460, self.panel.width_px, lambda x: f"{x} px")
        v.addLayout(wl)
        v.addWidget(self._head("Длина панели (дальше — прокрутка)"))
        self.len_s, ll = self._slider(0, 1400, self.panel.max_len, lambda x: "авто" if x < 200 else f"{x} px")
        v.addLayout(ll)
        v.addStretch()
        return w

    def _system_page(self):
        import dcp_extras as ex
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.addWidget(self._head("Профили программ — какую панель открывать"))
        prof = dict(self.cfg.get("profiles", {}))
        panels = [(None, "Не переключать")] + [(i, f"Панель {i + 1}") for i in range(MAX_PANELS)]
        self.prof_rows = []
        known = [("clipstudiopaint.exe", "Clip Studio Paint"), ("photoshop.exe", "Photoshop")]
        custom = [k for k in prof if k not in dict(known)]
        g = QGridLayout()
        g.setColumnStretch(0, 1)
        for r, (exe, label) in enumerate(known + [(custom[0] if custom else "", None)]):
            if label:
                g.addWidget(QLabel(label), r, 0)
                name_w = exe
            else:
                name_w = QLineEdit(exe)
                name_w.setPlaceholderText("другая программа, например krita.exe")
                g.addWidget(name_w, r, 0)
            cb = self._combo(panels, prof.get(exe) if exe else None)
            g.addWidget(cb, r, 1)
            self.prof_rows.append((name_w, cb))
        v.addLayout(g)
        v.addWidget(self._note("Панель переключается, когда эта программа становится активной (только Windows)."))
        v.addWidget(self._head("Запуск и обновления"))
        self.autostart = QCheckBox("Запускать вместе с Windows")
        self.autostart.setChecked(ex.autostart_enabled())
        self.autostart.setEnabled(sys.platform == "win32")
        self.updates = QCheckBox("Проверять обновления при запуске")
        self.updates.setChecked(self.cfg.get("update_check", True))
        v.addWidget(self.autostart)
        v.addWidget(self.updates)
        v.addWidget(self._note(f"Версия {APP_VERSION}. Резервная копия настроек: ☰ → Резервная копия."))
        v.addStretch()
        return w

    def _profiles(self):
        out = {}
        for name_w, cb in self.prof_rows:
            exe = name_w if isinstance(name_w, str) else name_w.text().strip().lower()
            if exe and cb.currentData() is not None:
                if not exe.endswith(".exe"):
                    exe += ".exe"
                out[exe] = cb.currentData()
        return out

    def _slider(self, lo, hi, val, fmt):
        row = QHBoxLayout()
        s = QSlider(Qt.Horizontal)
        s.setRange(lo, hi)
        s.setValue(val)
        lab = QLabel(fmt(val))
        lab.setFixedWidth(60)
        s.valueChanged.connect(lambda x: lab.setText(fmt(x)))
        row.addWidget(s)
        row.addWidget(lab)
        return s, row

    def reject(self):
        self.panel.keys.cancel_record()
        super().reject()

    def values(self):
        ml = self.len_s.value()
        return {"mode": self.mode.currentData(), "side": self.side.currentData(),
                "auto_return": self.autoret.isChecked(), "csp_autoreconnect": self.recon.isChecked(),
                "bindings": {a: c for a, c in self.bindings.items() if c},
                "suppress_keys": self.suppress.isChecked(), "middle_click": self.middle.isChecked(),
                "theme": self.theme.currentData(), "width_px": self.width_s.value(),
                "max_len": 0 if ml < 200 else ml,
                "profiles": self._profiles(), "autostart": self.autostart.isChecked(),
                "update_check": self.updates.isChecked()}


class NumPad(DarkDialog):
    """Экранная цифровая клавиатура для точного ввода значения."""
    _open = None

    @classmethod
    def open(cls, parent, title, value, lo, hi, cb, gpos):
        dlg = cls(parent, title, value, lo, hi, cb)
        scr = (QGuiApplication.screenAt(gpos) or QGuiApplication.primaryScreen()).availableGeometry()
        dlg.adjustSize()
        x = min(max(scr.left(), gpos.x() + 8), scr.right() - dlg.width())
        y = min(max(scr.top(), gpos.y() - 40), scr.bottom() - dlg.height())
        dlg.move(x, y)
        cls._open = dlg
        dlg.show()

    def __init__(self, parent, title, value, lo, hi, cb):
        super().__init__(parent.window(), title)
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        self.lo, self.hi, self.cb = lo, hi, cb
        self.text = f"{value:.0f}"
        self.fresh = True
        self.disp = QLabel()
        self.disp.setObjectName("big")
        self.disp.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.outer.addWidget(self.disp)
        rng = QLabel(f"{lo} … {hi}")
        rng.setStyleSheet(f"color:{DIM.name()}")
        self.outer.addWidget(rng)
        g = QGridLayout()
        g.setSpacing(6)
        keys = ["7", "8", "9", "4", "5", "6", "1", "2", "3", "−", "0", "."]
        for i, k in enumerate(keys):
            b = pill(k, "ghost")
            b.setFixedSize(54, 40)
            b.clicked.connect(lambda _=False, k=k: self._key(k))
            g.addWidget(b, i // 3, i % 3)
        bs = pill("⌫", "ghost")
        bs.clicked.connect(lambda: self._key("bs"))
        ok = pill("OK", "primary")
        ok.clicked.connect(self._ok)
        g.addWidget(bs, 4, 0)
        g.addWidget(ok, 4, 1, 1, 2)
        self.outer.addLayout(g)
        self._show()

    def _show(self):
        self.disp.setText(self.text or "0")

    def _key(self, k):
        if self.fresh and k not in ("bs",):
            self.text = ""
        self.fresh = False
        if k == "bs":
            self.text = self.text[:-1]
        elif k == "−":
            self.text = self.text[1:] if self.text.startswith("-") else "-" + self.text
        elif k == "." and "." in self.text:
            return
        else:
            self.text += k
        self._show()

    def keyPressEvent(self, e):
        t = e.text()
        if t.isdigit() or t == ".":
            self._key(t)
        elif t == "-":
            self._key("−")
        elif e.key() == Qt.Key_Backspace:
            self._key("bs")
        elif e.key() in (Qt.Key_Return, Qt.Key_Enter):
            self._ok()
        elif e.key() == Qt.Key_Escape:
            self.close()

    def _ok(self):
        try:
            v = float(self.text)
        except ValueError:
            self.close()
            return
        self.cb(min(self.hi, max(self.lo, v)))
        self.close()


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
        self.setStyleSheet(f"color:{SCROLL.name()}; font-size:12pt")
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
            l.setStyleSheet(f"color:{DIM.name()}; padding:40px; border:1px dashed {SCROLL.name()}; border-radius:10px")
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
            p.setPen(QPen(ACCENT, 3, Qt.SolidLine, Qt.RoundCap))
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
            box.setObjectName("box")
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
        path, _ = QFileDialog.getOpenFileName(self, "Импорт палитры", "", IMPORT_FILTER)
        if not path:
            return
        try:
            groups = import_palettes(path)
        except Exception as e:
            QMessageBox.warning(self, "Импорт", f"Не удалось прочитать файл:\n{e}")
            return
        for name, cols in groups:
            if cols:
                self._new_group(cols, name)

    def _export(self, n):
        path, _ = QFileDialog.getSaveFileName(self, "Экспорт", n + ".cls", EXPORT_FILTER)
        if path:
            export_palette(path, n, self.state.palettes[n])

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
    w = FloatingPanel()
    w.start()
    app.aboutToQuit.connect(w.save)
    sys.exit(app.exec())



import dcp_extras  # noqa: E402,F401  — регистрирует дополнительные компоненты

if __name__ == "__main__":
    main()
