#!/usr/bin/env python3
"""
Dynamic Color Picker — модульная панель работы с цветом для Clip Studio Paint и Photoshop.

Зависимости:  pip install PySide6 numpy
Опционально:  pip install opencv-python  (автосчитывание QR CSP Companion Mode с экрана)
              pip install pynput      (глобальная горячая клавиша / кнопка пера -> всплытие у курсора)
              pip install pywin32     (Windows: прямая установка цвета в Photoshop через COM)

Запуск:       python dynamic_color_picker.py
"""
import sys, os, json, uuid, math, colorsys
import numpy as np
from PySide6.QtCore import Qt, Signal, QObject, QTimer, QPointF, QRectF, QByteArray, QMimeData, QPoint
from PySide6.QtGui import (QColor, QPainter, QImage, QPen, QBrush, QLinearGradient, QCursor,
                           QAction, QDrag, QGuiApplication, QPolygonF)
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QDockWidget, QTabWidget, QVBoxLayout,
                               QHBoxLayout, QGridLayout, QLabel, QComboBox, QPushButton, QToolButton,
                               QSlider, QSpinBox, QDoubleSpinBox, QListWidget, QListWidgetItem, QFileDialog,
                               QInputDialog, QMessageBox, QLineEdit, QFrame, QScrollArea, QToolBar,
                               QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QSizePolicy)

import csp_companion as cspc

APP_DIR = os.path.join(os.path.expanduser("~"), ".dynamic_color_picker")
CONFIG_PATH = os.path.join(APP_DIR, "config.json")

# ============================================================== color math
M_RGB2XYZ = np.array([[0.4124564, 0.3575761, 0.1804375],
                      [0.2126729, 0.7151522, 0.0721750],
                      [0.0193339, 0.1191920, 0.9503041]])
M_XYZ2RGB = np.linalg.inv(M_RGB2XYZ)
WHITE = np.array([0.95047, 1.0, 1.08883])


def _lin(c):
    c = np.asarray(c, float)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def _gam(c):
    c = np.asarray(c, float)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * np.power(np.maximum(c, 0), 1 / 2.4) - 0.055)


def _f(t):
    return np.where(t > 0.008856, np.cbrt(t), 7.787 * t + 16 / 116)


def _finv(t):
    return np.where(t > 0.206893, t ** 3, (t - 16 / 116) / 7.787)


def rgb2lab(rgb):
    """rgb [...,3] 0..1 -> lab [...,3]"""
    xyz = _lin(rgb) @ M_RGB2XYZ.T / WHITE
    fx, fy, fz = _f(xyz[..., 0]), _f(xyz[..., 1]), _f(xyz[..., 2])
    return np.stack([116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)], -1)


def lab2rgb(lab):
    lab = np.asarray(lab, float)
    fy = (lab[..., 0] + 16) / 116
    fx = fy + lab[..., 1] / 500
    fz = fy - lab[..., 2] / 200
    xyz = np.stack([_finv(fx), _finv(fy), _finv(fz)], -1) * WHITE
    return _gam(xyz @ M_XYZ2RGB.T)


def lab_L(rgb):
    y = _lin(rgb) @ M_RGB2XYZ[1]
    return 116 * _f(y) - 16


def hsv2rgb(h, s, v):
    h, s, v = np.broadcast_arrays(np.asarray(h, float), np.asarray(s, float), np.asarray(v, float))
    h6 = (h % 1.0) * 6
    i = np.floor(h6).astype(int) % 6
    f = h6 - np.floor(h6)
    p, q, t = v * (1 - s), v * (1 - s * f), v * (1 - s * (1 - f))
    cond = [i == k for k in range(6)]
    r = np.select(cond, [v, q, p, p, t, v])
    g = np.select(cond, [t, v, v, q, p, p])
    b = np.select(cond, [p, p, t, v, v, q])
    return np.stack([r, g, b], -1)


def hsl2rgb(h, s, l):
    l = np.asarray(l, float)
    s = np.asarray(s, float)
    v = l + s * np.minimum(l, 1 - l)
    sv = np.where(v > 1e-9, 2 * (1 - l / np.maximum(v, 1e-9)), 0)
    return hsv2rgb(h, sv, v)


def vhsv2rgb(h, s, L):
    """V-HSV: HSV, где V заменён перцептивной яркостью (CIE L*, 0..1)."""
    base = hsv2rgb(h, s, 1.0)
    L = np.broadcast_to(np.asarray(L, float) * 100, base.shape[:-1])
    lo, hi = np.zeros(L.shape), np.ones(L.shape)
    for _ in range(16):
        mid = (lo + hi) / 2
        less = lab_L(base * mid[..., None]) < L
        lo, hi = np.where(less, mid, lo), np.where(less, hi, mid)
    return base * ((lo + hi) / 2)[..., None]


MODELS = ["HSV", "HSL", "V-HSV"]


def model_to_rgb(model, h, s, y):
    if model == "HSL":
        return hsl2rgb(h, s, y)
    if model == "V-HSV":
        return vhsv2rgb(h, s, y)
    return hsv2rgb(h, s, y)


def rgb_to_model(model, rgb):
    r, g, b = rgb
    if model == "HSL":
        h, l, s = colorsys.rgb_to_hls(r, g, b)
        return h, s, l
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    if model == "V-HSV":
        return h, s, float(lab_L(np.array(rgb))) / 100
    return h, s, v


def clip3(rgb):
    return tuple(float(min(1, max(0, c))) for c in rgb)


def to_qcolor(rgb):
    r, g, b = clip3(rgb)
    return QColor(round(r * 255), round(g * 255), round(b * 255))


def to_hex(rgb):
    return to_qcolor(rgb).name().upper()


def from_hex(s):
    c = QColor(s.strip() if s.strip().startswith("#") else "#" + s.strip())
    return (c.redF(), c.greenF(), c.blueF()) if c.isValid() else None


def in_gamut(rgb, eps=1e-4):
    return bool(np.all(np.asarray(rgb) >= -eps) and np.all(np.asarray(rgb) <= 1 + eps))


# ----- slider spaces: channels (name, min, max)
SPACES = {
    "RGB": [("R", 0, 255), ("G", 0, 255), ("B", 0, 255)],
    "CMYK": [("C", 0, 100), ("M", 0, 100), ("Y", 0, 100), ("K", 0, 100)],
    "HSL": [("H", 0, 360), ("S", 0, 100), ("L", 0, 100)],
    "HSV": [("H", 0, 360), ("S", 0, 100), ("V", 0, 100)],
    "V-HSV": [("H", 0, 360), ("S", 0, 100), ("L*", 0, 100)],
    "LAB": [("L", 0, 100), ("a", -128, 127), ("b", -128, 127)],
    "LCH": [("L", 0, 100), ("C", 0, 150), ("H", 0, 360)],
}


def space_from_rgb(space, rgb):
    r, g, b = rgb
    if space == "RGB":
        return [r * 255, g * 255, b * 255]
    if space == "CMYK":
        k = 1 - max(rgb)
        if k >= 1:
            return [0, 0, 0, 100]
        return [(1 - r - k) / (1 - k) * 100, (1 - g - k) / (1 - k) * 100, (1 - b - k) / (1 - k) * 100, k * 100]
    if space in ("HSL", "HSV", "V-HSV"):
        h, s, y = rgb_to_model(space, rgb)
        return [h * 360, s * 100, y * 100]
    lab = rgb2lab(np.array(rgb))
    if space == "LAB":
        return list(map(float, lab))
    c = math.hypot(lab[1], lab[2])
    hh = math.degrees(math.atan2(lab[2], lab[1])) % 360
    return [float(lab[0]), c, hh]


def space_to_rgb(space, v):
    if space == "RGB":
        return clip3([x / 255 for x in v])
    if space == "CMYK":
        c, m, y, k = [x / 100 for x in v]
        return clip3([(1 - c) * (1 - k), (1 - m) * (1 - k), (1 - y) * (1 - k)])
    if space in ("HSL", "HSV", "V-HSV"):
        return clip3(model_to_rgb(space, v[0] / 360, v[1] / 100, v[2] / 100))
    if space == "LAB":
        return clip3(lab2rgb(np.array(v)))
    L, C, H = v
    return clip3(lab2rgb(np.array([L, C * math.cos(math.radians(H)), C * math.sin(math.radians(H))])))


def lch_in_gamut(L, C, H):
    """уменьшает хрому, пока цвет не попадёт в sRGB"""
    hr = math.radians(H)
    lo, hi = 0.0, C
    rgb = lab2rgb(np.array([L, C * math.cos(hr), C * math.sin(hr)]))
    if in_gamut(rgb):
        return clip3(rgb)
    for _ in range(14):
        mid = (lo + hi) / 2
        if in_gamut(lab2rgb(np.array([L, mid * math.cos(hr), mid * math.sin(hr)]))):
            lo = mid
        else:
            hi = mid
    return clip3(lab2rgb(np.array([L, lo * math.cos(hr), lo * math.sin(hr)])))


def np_to_qimage(arr):
    arr = np.ascontiguousarray(np.clip(arr * 255 + 0.5, 0, 255).astype(np.uint8))
    h, w, ch = arr.shape
    fmt = QImage.Format_RGBA8888 if ch == 4 else QImage.Format_RGB888
    return QImage(arr.data, w, h, ch * w, fmt).copy()


def draw_checker(p, rect, size=6):
    p.save()
    p.setClipRect(rect)
    p.fillRect(rect, QColor(255, 255, 255))
    x0, y0 = int(rect.left()), int(rect.top())
    for yy in range(y0, int(rect.bottom()) + 1, size):
        for xx in range(x0, int(rect.right()) + 1, size):
            if ((xx - x0) // size + (yy - y0) // size) % 2:
                p.fillRect(xx, yy, size, size, QColor(200, 200, 200))
    p.restore()


# ============================================================== shared state
class ColorState(QObject):
    changed = Signal(object)          # source
    historyChanged = Signal()
    palettesChanged = Signal()

    def __init__(self):
        super().__init__()
        self.fg = (0.85, 0.35, 0.25)
        self.bg = (1.0, 1.0, 1.0)
        self.active = "fg"            # fg | bg
        self.transparent = False
        self.history = []
        self.palettes = {"Default": ["#000000", "#FFFFFF", "#E05A47", "#F2C14E", "#5B8E7D", "#3D5A80"]}
        self.current_palette = "Default"
        self.auto_send = False
        self._commit = QTimer(singleShot=True, interval=700)
        self._commit.timeout.connect(self.push_history)

    def color(self):
        return self.fg if self.active == "fg" else self.bg

    def set_color(self, rgb, source=None, commit=True):
        rgb = clip3(rgb)
        if self.active == "fg":
            self.fg = rgb
        else:
            self.bg = rgb
        self.transparent = False
        self.changed.emit(source)
        if commit:
            self._commit.start()
            if self.auto_send:
                send_to_apps(self)

    def set_external(self, fg, bg, active, transparent, source):
        """Цвет пришёл из CSP: обновить оба слота без повторной отправки."""
        new = (clip3(fg), clip3(bg), active, transparent)
        if new == (self.fg, self.bg, self.active, self.transparent):
            return
        prev = to_hex(self.color())
        self.fg, self.bg, self.active, self.transparent = new
        self.changed.emit(source)
        if to_hex(self.color()) != prev:
            self._commit.start()

    def set_active(self, which):
        self.active = which
        self.transparent = False
        self.changed.emit(None)

    def swap(self):
        self.fg, self.bg = self.bg, self.fg
        self.changed.emit(None)

    def push_history(self):
        hx = to_hex(self.color())
        if hx in self.history:
            self.history.remove(hx)
        self.history.insert(0, hx)
        del self.history[40:]
        self.historyChanged.emit()


def send_to_apps(state):
    """Отправка текущего цвета: Photoshop (COM, Windows) + буфер обмена (CSP: вставить HEX в окно выбора цвета)."""
    hx = to_hex(state.color())
    link = getattr(state, "csp", None)
    if link and link.connected:
        link.push()
        msg = f"{hx} → CSP (Companion)"
    else:
        QGuiApplication.clipboard().setText(hx)
        msg = f"{hx} скопирован в буфер"
    if sys.platform == "win32":
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
            msg += " · Photoshop обновлён"
        except Exception:
            pass
    return msg


# ============================================================== widgets
class ColorPickerWidget(QWidget):
    """Круг (кольцо оттенков + квадрат) или куб (плоскость + полоса оттенков)."""

    def __init__(self, state, model="HSV", shape="Wheel"):
        super().__init__()
        self.state, self.model, self.shape = state, model, shape
        self.h, self.s, self.y = rgb_to_model(model, state.color())
        self.setMinimumSize(160, 160)
        self._plane_key = self._ring_key = None
        self._plane = self._ring = None
        self._drag = None
        state.changed.connect(self._on_state)

    def _on_state(self, src):
        if src is self:
            return
        h, s, y = rgb_to_model(self.model, self.state.color())
        if s > 1e-4 and 1e-4 < y < 1 - 1e-4 or self.model == "HSV" and s > 1e-4 and y > 1e-4:
            self.h = h
        self.s, self.y = s, y
        self.update()

    def set_model(self, m):
        self.model = m
        self._plane_key = None
        self._on_state(None)

    def set_shape(self, sh):
        self.shape = sh
        self._plane_key = self._ring_key = None
        self.update()

    # geometry
    def _geo(self):
        w, h = self.width(), self.height()
        if self.shape == "Wheel":
            side = min(w, h) - 4
            cx, cy = w / 2, h / 2
            R = side / 2
            ring_w = max(12, R * 0.14)
            inner = (R - ring_w - 4) * math.sqrt(2)
            sq = QRectF(cx - inner / 2, cy - inner / 2, inner, inner)
            return dict(cx=cx, cy=cy, R=R, rw=ring_w, sq=sq)
        strip = 18
        side = min(w - strip - 8, h) - 4
        sq = QRectF(2, (h - side) / 2, side, side)
        st = QRectF(sq.right() + 8, sq.top(), strip, side)
        return dict(sq=sq, st=st)

    def _plane_img(self, rect):
        n = max(16, int(min(rect.width(), 220)))
        key = (round(self.h, 4), self.model, n)
        if key != self._plane_key:
            xs = np.linspace(0, 1, n)
            S, Y = np.meshgrid(xs, xs[::-1])
            self._plane = np_to_qimage(np.clip(model_to_rgb(self.model, self.h, S, Y), 0, 1))
            self._plane_key = key
        return self._plane

    def _ring_img(self, g):
        n = int(g["R"] * 2)
        key = (n, round(g["rw"]))
        if key != self._ring_key and n > 0:
            yy, xx = np.mgrid[0:n, 0:n] + 0.5
            dx, dy = xx - n / 2, yy - n / 2
            d = np.hypot(dx, dy)
            hue = (np.arctan2(-dy, dx) / (2 * np.pi)) % 1
            rgb = hsv2rgb(hue, 1, 1)
            a = np.clip(np.minimum(d - (n / 2 - g["rw"]), n / 2 - d), 0, 1)
            self._ring = np_to_qimage(np.concatenate([rgb * a[..., None], a[..., None]], -1))
            self._ring_key = key
        return self._ring

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        g = self._geo()
        sq = g["sq"]
        p.drawImage(sq, self._plane_img(sq))
        p.setPen(QPen(QColor(0, 0, 0, 90), 1))
        p.drawRect(sq)
        # plane marker
        mx, my = sq.left() + self.s * sq.width(), sq.top() + (1 - self.y) * sq.height()
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(Qt.white, 2))
        p.drawEllipse(QPointF(mx, my), 6, 6)
        p.setPen(QPen(Qt.black, 1))
        p.drawEllipse(QPointF(mx, my), 7.5, 7.5)
        if self.shape == "Wheel":
            img = self._ring_img(g)
            if img:
                p.drawImage(QPointF(g["cx"] - g["R"], g["cy"] - g["R"]), img)
            rm = g["R"] - g["rw"] / 2
            a = self.h * 2 * math.pi
            pt = QPointF(g["cx"] + math.cos(a) * rm, g["cy"] - math.sin(a) * rm)
            p.setPen(QPen(Qt.white, 2))
            p.drawEllipse(pt, g["rw"] / 2 - 1, g["rw"] / 2 - 1)
        else:
            st = g["st"]
            grad = QLinearGradient(st.topLeft(), st.bottomLeft())
            for i in range(13):
                grad.setColorAt(i / 12, QColor.fromHsvF((1 - i / 12) % 1 * 0.9999, 1, 1))
            p.fillRect(st, grad)
            yy = st.top() + (1 - self.h) * st.height()
            p.setPen(QPen(Qt.white, 2))
            p.drawRect(QRectF(st.left() - 2, yy - 3, st.width() + 4, 6))

    def mousePressEvent(self, e):
        g = self._geo()
        pos = e.position()
        if g["sq"].adjusted(-6, -6, 6, 6).contains(pos):
            self._drag = "plane"
        elif self.shape == "Wheel":
            self._drag = "ring" if math.hypot(pos.x() - g["cx"], pos.y() - g["cy"]) <= g["R"] else None
        else:
            self._drag = "strip" if g["st"].adjusted(-6, 0, 6, 0).contains(pos) else None
        self._apply(pos, False)

    def mouseMoveEvent(self, e):
        self._apply(e.position(), False)

    def mouseReleaseEvent(self, e):
        self._apply(e.position(), True)
        self._drag = None

    def _apply(self, pos, commit):
        if not self._drag:
            return
        g = self._geo()
        if self._drag == "plane":
            sq = g["sq"]
            self.s = min(1, max(0, (pos.x() - sq.left()) / sq.width()))
            self.y = min(1, max(0, 1 - (pos.y() - sq.top()) / sq.height()))
        elif self._drag == "ring":
            self.h = (math.atan2(-(pos.y() - g["cy"]), pos.x() - g["cx"]) / (2 * math.pi)) % 1
        else:
            st = g["st"]
            self.h = min(0.9999, max(0, 1 - (pos.y() - st.top()) / st.height()))
        self.state.set_color(model_to_rgb(self.model, self.h, self.s, self.y), self, commit)
        self.update()


class GradientSlider(QWidget):
    valueChanged = Signal(float, bool)   # t 0..1, released

    def __init__(self):
        super().__init__()
        self.t, self.stops = 0.0, [QColor(0, 0, 0), QColor(255, 255, 255)]
        self.setFixedHeight(16)
        self.setMinimumWidth(80)

    def set(self, t, stops):
        self.t, self.stops = t, stops
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        r = QRectF(4, 2, self.width() - 8, self.height() - 4)
        grad = QLinearGradient(r.topLeft(), r.topRight())
        for i, c in enumerate(self.stops):
            grad.setColorAt(i / (len(self.stops) - 1), c)
        p.fillRect(r, grad)
        x = r.left() + self.t * r.width()
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(Qt.black, 1))
        p.setBrush(Qt.white)
        p.drawPolygon(QPolygonF([QPointF(x - 4, self.height()), QPointF(x + 4, self.height()), QPointF(x, self.height() - 7)]))
        p.setPen(QPen(Qt.white, 1))
        p.drawLine(QPointF(x, r.top()), QPointF(x, r.bottom()))

    def _set_from(self, e, rel):
        self.t = min(1, max(0, (e.position().x() - 4) / max(1, self.width() - 8)))
        self.update()
        self.valueChanged.emit(self.t, rel)

    mousePressEvent = lambda self, e: self._set_from(e, False)
    mouseMoveEvent = lambda self, e: self._set_from(e, False)
    mouseReleaseEvent = lambda self, e: self._set_from(e, True)


class SliderGroup(QFrame):
    removed = Signal(object)

    def __init__(self, state, space):
        super().__init__()
        self.state, self.space = state, space
        self.setFrameShape(QFrame.StyledPanel)
        lay = QGridLayout(self)
        lay.setContentsMargins(4, 2, 4, 2)
        lay.setVerticalSpacing(2)
        title = QLabel(f"<b>{space}</b>")
        x = QToolButton(text="×")
        x.setAutoRaise(True)
        x.clicked.connect(lambda: self.removed.emit(self))
        lay.addWidget(title, 0, 0, 1, 2)
        lay.addWidget(x, 0, 2, Qt.AlignRight)
        self.vals = space_from_rgb(space, state.color())
        self.sliders, self.spins = [], []
        for i, (name, lo, hi) in enumerate(SPACES[space]):
            sl, sp = GradientSlider(), QSpinBox()
            sp.setRange(lo, hi)
            sp.setFixedWidth(58)
            sl.valueChanged.connect(lambda t, rel, i=i: self._chan(i, lo_hi(self.space, i, t), rel))
            sp.editingFinished.connect(lambda i=i, sp=sp: self._chan(i, sp.value(), True))
            lay.addWidget(QLabel(name), i + 1, 0)
            lay.addWidget(sl, i + 1, 1)
            lay.addWidget(sp, i + 1, 2)
            self.sliders.append(sl)
            self.spins.append(sp)
        state.changed.connect(self._on_state)
        self._refresh()

    def _on_state(self, src):
        if src is self:
            return
        new = space_from_rgb(self.space, self.state.color())
        # сохранить оттенок у ахроматических цветов
        if self.space in ("HSL", "HSV", "V-HSV") and new[1] < 0.05:
            new[0] = self.vals[0]
        if self.space == "LCH" and new[1] < 0.5:
            new[2] = self.vals[2]
        self.vals = new
        self._refresh()

    def _chan(self, i, v, rel):
        self.vals[i] = v
        self.state.set_color(space_to_rgb(self.space, self.vals), self, rel)
        self._refresh()

    def _refresh(self):
        for i, (name, lo, hi) in enumerate(SPACES[self.space]):
            stops = []
            for k in range(9):
                vv = list(self.vals)
                vv[i] = lo + (hi - lo) * k / 8
                stops.append(to_qcolor(space_to_rgb(self.space, vv)))
            self.sliders[i].set((self.vals[i] - lo) / (hi - lo), stops)
            self.spins[i].blockSignals(True)
            self.spins[i].setValue(round(self.vals[i]))
            self.spins[i].blockSignals(False)


def lo_hi(space, i, t):
    _, lo, hi = SPACES[space][i]
    return lo + (hi - lo) * t


class SwatchGrid(QWidget):
    picked = Signal(str)
    removeRequested = Signal(int)

    def __init__(self, cell=20):
        super().__init__()
        self.colors, self.cell = [], cell
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)

    def set_colors(self, colors):
        self.colors = list(colors)
        self.updateGeometry()
        self.update()

    def _cols(self):
        return max(1, (self.width() - 2) // (self.cell + 2))

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, w):
        cols = max(1, (w - 2) // (self.cell + 2))
        return max(self.cell + 4, math.ceil(len(self.colors) / cols) * (self.cell + 2) + 2)

    def sizeHint(self):
        from PySide6.QtCore import QSize
        return QSize(200, self.heightForWidth(max(self.width(), 200)))

    def resizeEvent(self, e):
        self.setMinimumHeight(self.heightForWidth(self.width()))

    def paintEvent(self, e):
        p = QPainter(self)
        cols = self._cols()
        for i, hx in enumerate(self.colors):
            r, c = divmod(i, cols)
            rect = QRectF(1 + c * (self.cell + 2), 1 + r * (self.cell + 2), self.cell, self.cell)
            p.fillRect(rect, QColor(hx))
            p.setPen(QColor(0, 0, 0, 60))
            p.drawRect(rect)
        if not self.colors:
            p.setPen(QColor(128, 128, 128))
            p.drawText(self.rect(), Qt.AlignCenter, "пусто")

    def _idx(self, pos):
        cols = self._cols()
        c, r = int((pos.x() - 1) // (self.cell + 2)), int((pos.y() - 1) // (self.cell + 2))
        i = r * cols + c
        return i if 0 <= c < cols and 0 <= i < len(self.colors) else -1

    def mousePressEvent(self, e):
        i = self._idx(e.position())
        if i < 0:
            return
        if e.button() == Qt.RightButton:
            self.removeRequested.emit(i)
        else:
            self.picked.emit(self.colors[i])


# ============================================================== modules
class Module(QWidget):
    TITLE = "Module"

    def __init__(self, state, cfg):
        super().__init__()
        self.state, self.cfg = state, dict(cfg or {})

    def get_config(self):
        return self.cfg


class PickerModule(Module):
    TITLE = "Color Picker"

    def __init__(self, state, cfg):
        super().__init__(state, cfg)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        top = QHBoxLayout()
        self.model = QComboBox()
        self.model.addItems(MODELS)
        self.model.setCurrentText(self.cfg.get("model", "HSV"))
        self.shape = QComboBox()
        self.shape.addItems(["Wheel", "Cube"])
        self.shape.setCurrentText(self.cfg.get("shape", "Wheel"))
        top.addWidget(self.model)
        top.addWidget(self.shape)
        lay.addLayout(top)
        self.w = ColorPickerWidget(state, self.model.currentText(), self._shape_key())
        lay.addWidget(self.w, 1)
        self.model.currentTextChanged.connect(self._upd)
        self.shape.currentTextChanged.connect(self._upd)

    def _shape_key(self):
        return "Wheel" if self.shape.currentText() == "Wheel" else "Square"

    def _upd(self):
        self.cfg = {"model": self.model.currentText(), "shape": self.shape.currentText()}
        self.w.set_model(self.cfg["model"])
        self.w.set_shape(self._shape_key())


class LumaPaletteModule(Module):
    TITLE = "Luma Palette"
    HUES = 12

    def __init__(self, state, cfg):
        super().__init__(state, cfg)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        self.info = QLabel()
        lay.addWidget(self.info)
        self.grid = SwatchGrid(cell=18)
        self.grid.picked.connect(lambda hx: state.set_color(from_hex(hx), self))
        lay.addWidget(self.grid)
        lay.addStretch()
        state.changed.connect(self._on_state)
        self._on_state(None)

    def _on_state(self, src):
        if src is self:
            return
        L, a, b = rgb2lab(np.array(self.state.color()))
        C = max(math.hypot(a, b), 18)
        H0 = math.degrees(math.atan2(b, a))
        out = []
        for cm in (0.5, 1.0, 1.6):
            for k in range(self.HUES):
                out.append(to_hex(lch_in_gamut(L, C * cm, H0 + k * 360 / self.HUES)))
        self.grid.set_colors(out)
        self.info.setText(f"L* = {L:.0f}  ·  ряды: хрома ×0.5 / ×1 / ×1.6")


class SlidersModule(Module):
    TITLE = "Color Sliders"

    def __init__(self, state, cfg):
        super().__init__(state, cfg)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        top = QHBoxLayout()
        self.combo = QComboBox()
        self.combo.addItems(SPACES.keys())
        add = QPushButton("+ слайдеры")
        add.clicked.connect(lambda: self.add_group(self.combo.currentText()))
        top.addWidget(self.combo, 1)
        top.addWidget(add)
        lay.addLayout(top)
        self.box = QVBoxLayout()
        lay.addLayout(self.box)
        lay.addStretch()
        self.groups = []
        for sp in self.cfg.get("spaces", ["HSV"]):
            self.add_group(sp)

    def add_group(self, space):
        g = SliderGroup(self.state, space)
        g.removed.connect(self._remove)
        self.groups.append(g)
        self.box.addWidget(g)

    def _remove(self, g):
        self.groups.remove(g)
        g.deleteLater()

    def get_config(self):
        return {"spaces": [g.space for g in self.groups]}


class HistoryModule(Module):
    TITLE = "History"

    def __init__(self, state, cfg):
        super().__init__(state, cfg)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        self.grid = SwatchGrid(cell=16)
        self.grid.picked.connect(lambda hx: state.set_color(from_hex(hx), self, False))
        self.grid.removeRequested.connect(self._rm)
        lay.addWidget(self.grid)
        clr = QPushButton("Очистить")
        clr.clicked.connect(self._clear)
        lay.addWidget(clr, 0, Qt.AlignRight)
        lay.addStretch()
        state.historyChanged.connect(lambda: self.grid.set_colors(state.history))
        self.grid.set_colors(state.history)

    def _rm(self, i):
        del self.state.history[i]
        self.state.historyChanged.emit()

    def _clear(self):
        self.state.history.clear()
        self.state.historyChanged.emit()


class ModesWidget(QWidget):
    def __init__(self, state):
        super().__init__()
        self.state = state
        self.setFixedSize(70, 60)
        state.changed.connect(lambda _: self.update())

    def _rects(self):
        return QRectF(2, 2, 40, 40), QRectF(26, 18, 40, 40)

    def paintEvent(self, e):
        p = QPainter(self)
        fr, br = self._rects()
        for which, r in (("bg", br), ("fg", fr)) if self.state.active == "fg" else (("fg", fr), ("bg", br)):
            p.fillRect(r, to_qcolor(getattr(self.state, which)))
            active = which == self.state.active
            if active and self.state.transparent:
                draw_checker(p, r)
            p.setPen(QPen(QColor("#2D8CFF") if active else QColor(90, 90, 90), 3 if active else 1))
            p.drawRect(r)

    def mousePressEvent(self, e):
        fr, br = self._rects()
        top = ("fg", fr) if self.state.active == "fg" else ("bg", br)
        if top[1].contains(e.position()):
            self.state.set_active(top[0])
        elif fr.contains(e.position()):
            self.state.set_active("fg")
        elif br.contains(e.position()):
            self.state.set_active("bg")


class ModesModule(Module):
    TITLE = "Color Modes"

    def __init__(self, state, cfg):
        super().__init__(state, cfg)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.addWidget(ModesWidget(state))
        col = QVBoxLayout()
        for txt, fn in (("⇄ Поменять", state.swap),
                        ("Ч/Б", self._reset),
                        ("▦ Прозрачный", self._transp)):
            b = QPushButton(txt)
            b.clicked.connect(fn)
            col.addWidget(b)
        lay.addLayout(col)
        lay.addStretch()

    def _reset(self):
        self.state.fg, self.state.bg = (0, 0, 0), (1, 1, 1)
        self.state.changed.emit(None)

    def _transp(self):
        self.state.transparent = not self.state.transparent
        self.state.changed.emit(None)


class SwatchesModule(Module):
    TITLE = "Swatches"

    def __init__(self, state, cfg):
        super().__init__(state, cfg)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        row = QHBoxLayout()
        self.combo = QComboBox()
        row.addWidget(self.combo, 1)
        for txt, tip, fn in (("＋", "Новая палитра", self._new), ("✎", "Переименовать", self._rename),
                             ("🗑", "Удалить палитру", self._delete), ("⤓", "Импорт (.gpl/.json/.txt/.hex)", self._import),
                             ("⤒", "Экспорт", self._export)):
            b = QToolButton(text=txt)
            b.setToolTip(tip)
            b.clicked.connect(fn)
            row.addWidget(b)
        lay.addLayout(row)
        self.grid = SwatchGrid(cell=20)
        self.grid.picked.connect(lambda hx: state.set_color(from_hex(hx), self))
        self.grid.removeRequested.connect(self._rm)
        lay.addWidget(self.grid)
        addb = QPushButton("+ Добавить текущий цвет")
        addb.clicked.connect(self._add)
        lay.addWidget(addb)
        # extraction
        ex = QGridLayout()
        self.acc = QSlider(Qt.Horizontal)
        self.acc.setRange(1, 100)
        self.acc.setValue(self.cfg.get("accuracy", 60))
        self.acc_lbl = QLabel()
        self.acc.valueChanged.connect(lambda v: self.acc_lbl.setText(f"{v}%"))
        self.acc_lbl.setText(f"{self.acc.value()}%")
        self.count = QSpinBox()
        self.count.setRange(2, 48)
        self.count.setValue(self.cfg.get("count", 10))
        exb = QPushButton("Извлечь из изображения…")
        exb.clicked.connect(self._extract)
        ex.addWidget(QLabel("Extraction Accuracy"), 0, 0)
        ex.addWidget(self.acc, 0, 1)
        ex.addWidget(self.acc_lbl, 0, 2)
        ex.addWidget(QLabel("Цветов"), 1, 0)
        ex.addWidget(self.count, 1, 1)
        ex.addWidget(exb, 2, 0, 1, 3)
        lay.addLayout(ex)
        lay.addStretch()
        self.combo.currentTextChanged.connect(self._sel)
        state.palettesChanged.connect(self._reload)
        self._reload()

    def get_config(self):
        return {"accuracy": self.acc.value(), "count": self.count.value()}

    def _reload(self):
        self.combo.blockSignals(True)
        self.combo.clear()
        self.combo.addItems(self.state.palettes.keys())
        self.combo.setCurrentText(self.state.current_palette)
        self.combo.blockSignals(False)
        self.grid.set_colors(self.state.palettes.get(self.state.current_palette, []))

    def _sel(self, name):
        if name:
            self.state.current_palette = name
            self.grid.set_colors(self.state.palettes.get(name, []))

    def _pal(self):
        return self.state.palettes.setdefault(self.state.current_palette, [])

    def _add(self):
        self._pal().append(to_hex(self.state.color()))
        self.state.palettesChanged.emit()

    def _rm(self, i):
        del self._pal()[i]
        self.state.palettesChanged.emit()

    def _new(self, colors=None, name=None):
        name = name or QInputDialog.getText(self, "Новая палитра", "Имя:")[0]
        if not name:
            return
        base, k = name, 2
        while name in self.state.palettes:
            name, k = f"{base} {k}", k + 1
        self.state.palettes[name] = list(colors or [])
        self.state.current_palette = name
        self.state.palettesChanged.emit()

    def _rename(self):
        old = self.state.current_palette
        new, ok = QInputDialog.getText(self, "Переименовать", "Имя:", text=old)
        if ok and new and new not in self.state.palettes:
            self.state.palettes = {(new if k == old else k): v for k, v in self.state.palettes.items()}
            self.state.current_palette = new
            self.state.palettesChanged.emit()

    def _delete(self):
        if len(self.state.palettes) <= 1:
            return
        if QMessageBox.question(self, "Удалить", f"Удалить «{self.state.current_palette}»?") == QMessageBox.Yes:
            del self.state.palettes[self.state.current_palette]
            self.state.current_palette = next(iter(self.state.palettes))
            self.state.palettesChanged.emit()

    def _import(self):
        path, _ = QFileDialog.getOpenFileName(self, "Импорт палитры", "", "Palettes (*.gpl *.json *.txt *.hex)")
        if not path:
            return
        cols = parse_palette(path)
        if cols:
            self._new(cols, os.path.splitext(os.path.basename(path))[0])

    def _export(self):
        path, _ = QFileDialog.getSaveFileName(self, "Экспорт", self.state.current_palette + ".gpl",
                                              "GIMP/Krita palette (*.gpl);;JSON (*.json);;HEX list (*.txt)")
        if path:
            write_palette(path, self.state.current_palette, self._pal())

    def _extract(self):
        path, _ = QFileDialog.getOpenFileName(self, "Изображение", "", "Images (*.png *.jpg *.jpeg *.bmp *.webp *.tif *.tiff)")
        if not path:
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            cols = extract_colors(path, self.count.value(), self.acc.value())
        finally:
            QApplication.restoreOverrideCursor()
        if cols:
            self._new(cols, "Из " + os.path.splitext(os.path.basename(path))[0])


class OutputModule(Module):
    TITLE = "Output / Send"

    def __init__(self, state, cfg):
        super().__init__(state, cfg)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        row = QHBoxLayout()
        self.preview = QLabel()
        self.preview.setFixedSize(36, 24)
        self.hex = QLineEdit()
        self.hex.setMaxLength(7)
        self.hex.editingFinished.connect(self._hex)
        row.addWidget(self.preview)
        row.addWidget(self.hex)
        lay.addLayout(row)
        send = QPushButton("Отправить в CSP / Photoshop")
        send.setToolTip("CSP — через Companion Mode (модуль CSP Companion).\nPhotoshop (Windows) — напрямую через COM.\nБез подключения HEX копируется в буфер.")
        send.clicked.connect(lambda: self.status.setText(send_to_apps(state)))
        lay.addWidget(send)
        self.auto = QCheckBox("Отправлять автоматически")
        self.auto.setChecked(state.auto_send)
        self.auto.toggled.connect(lambda v: setattr(state, "auto_send", v))
        lay.addWidget(self.auto)
        self.status = QLabel()
        self.status.setStyleSheet("color: gray")
        lay.addWidget(self.status)
        lay.addStretch()
        state.changed.connect(self._on_state)
        self._on_state(None)

    def _on_state(self, src):
        hx = to_hex(self.state.color())
        self.preview.setStyleSheet(f"background:{hx}; border:1px solid #555")
        if src is not self:
            self.hex.setText(hx)

    def _hex(self):
        rgb = from_hex(self.hex.text())
        if rgb:
            self.state.set_color(rgb, self)


class CSPLink(QObject):
    """Связь ColorState <-> CSP Companion Mode."""
    statusChanged = Signal(str, bool)
    SRC = "csp"

    def __init__(self, state):
        super().__init__()
        self.state, self.worker, self.connected = state, None, False
        self.text = "Не подключено"
        self.scan_timer = QTimer(interval=1000)
        self.scan_timer.timeout.connect(self._scan_tick)
        self._scan_left = 0
        state.changed.connect(self._on_state)

    # --- подключение
    def start_scan(self):
        self._scan_left = 90
        self._set_status("Откройте в CSP: File → Connect to smartphone. Ищу QR на экране…", False)
        self.scan_timer.start()
        self._scan_tick()

    def _scan_tick(self):
        self._scan_left -= 1
        try:
            url = cspc.scan_screens_for_qr()
        except RuntimeError as e:
            self.scan_timer.stop()
            self._set_status(f"{e}. Вставьте URL из QR вручную.", False)
            return
        if url:
            self.scan_timer.stop()
            self.connect_url(url)
        elif self._scan_left <= 0:
            self.scan_timer.stop()
            self._set_status("QR не найден. Окно CSP с QR должно быть видно на экране.", False)

    def connect_url(self, url):
        try:
            d = cspc.decode_qr_url(url)
        except Exception as e:
            self._set_status(f"Неверный QR/URL: {e}", False)
            return
        self._start(d, reconnect=False)

    def reconnect(self):
        d = cspc.load_session(APP_DIR)
        if not d:
            self._set_status("Нет сохранённой сессии — подключитесь через QR", False)
            return False
        self._start(d, reconnect=True)
        return True

    def _start(self, d, reconnect):
        self.disconnect()
        w = cspc.CompanionWorker(d["ips"], d["port"], d["password"], d["generation"], reconnect)
        w.status.connect(self._set_status)
        w.colorReceived.connect(self._on_csp_color)
        w.authenticated.connect(lambda sess: cspc.save_session(APP_DIR, sess))
        self.worker = w
        w.start()

    def disconnect(self):
        self.scan_timer.stop()
        if self.worker:
            self.worker.stop()
            self.worker.wait(3000)
            self.worker = None
        self._set_status("Не подключено", False)

    def _set_status(self, text, ok):
        self.connected, self.text = ok, text
        self.statusChanged.emit(text, ok)

    # --- цвет
    def _on_csp_color(self, d):
        fg = tuple(float(x) for x in hsv2rgb(*d["main"]))
        bg = tuple(float(x) for x in hsv2rgb(*d["sub"]))
        self.state.set_external(fg, bg, "bg" if d["index"] else "fg", d["transparent"], self.SRC)

    def _on_state(self, src):
        if src != self.SRC and self.connected:
            self.push()

    def push(self):
        if self.worker and self.connected:
            s = self.state
            self.worker.set_color(s.color(), 1 if s.active == "bg" else 0, s.transparent)


class CSPModule(Module):
    TITLE = "CSP Companion"

    def __init__(self, state, cfg):
        super().__init__(state, cfg)
        self.link = state.csp
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        self.lamp = QLabel()
        self.msg = QLabel(wordWrap=True)
        row = QHBoxLayout()
        row.addWidget(self.lamp)
        row.addWidget(self.msg, 1)
        lay.addLayout(row)
        g = QGridLayout()
        for i, (txt, fn) in enumerate((("Подключить (QR с экрана)", self.link.start_scan),
                                       ("Вставить URL…", self._paste),
                                       ("Переподключиться", self.link.reconnect),
                                       ("Отключить", self.link.disconnect))):
            b = QPushButton(txt)
            b.clicked.connect(fn)
            g.addWidget(b, i // 2, i % 2)
        lay.addLayout(g)
        hint = QLabel("CSP: File → Connect to smartphone.\nQR считывается автоматически, если окно видно.")
        hint.setStyleSheet("color: gray")
        lay.addWidget(hint)
        lay.addStretch()
        self.link.statusChanged.connect(self._show)
        self._show(self.link.text, self.link.connected)

    def _show(self, text, ok):
        self.lamp.setText("●")
        self.lamp.setStyleSheet(f"color: {'#2ECC71' if ok else '#888'}; font-size: 16px")
        self.msg.setText(text)

    def _paste(self):
        clip = QGuiApplication.clipboard().text()
        url, ok = QInputDialog.getText(self, "URL из QR CSP", "https://companion.clip-studio.com/…?s=…",
                                       text=clip if clip.startswith(cspc.QR_PREFIX) else "")
        if ok and url:
            self.link.connect_url(url)


MODULES = {m.TITLE: m for m in (PickerModule, LumaPaletteModule, SlidersModule, HistoryModule,
                                ModesModule, SwatchesModule, OutputModule, CSPModule)}


# ============================================================== palette io / extraction
def parse_palette(path):
    try:
        txt = open(path, encoding="utf-8", errors="ignore").read()
    except OSError:
        return []
    if path.lower().endswith(".json"):
        try:
            d = json.loads(txt)
            d = d.get("colors", d) if isinstance(d, dict) else d
            return [to_hex(from_hex(c)) for c in d if from_hex(str(c))]
        except Exception:
            return []
    out = []
    for line in txt.splitlines():
        line = line.strip()
        if not line or line.startswith(("#", "GIMP", "Name", "Columns")) and not (line.startswith("#") and from_hex(line[:7]) and len(line.split()[0]) == 7):
            continue
        parts = line.split()
        if len(parts) >= 3 and all(p.isdigit() for p in parts[:3]):
            out.append("#%02X%02X%02X" % tuple(int(p) for p in parts[:3]))
        elif from_hex(parts[0]) and len(parts[0].lstrip("#")) == 6:
            out.append(to_hex(from_hex(parts[0])))
    return out


def write_palette(path, name, colors):
    if path.lower().endswith(".json"):
        json.dump({"name": name, "colors": colors}, open(path, "w"), indent=2)
    elif path.lower().endswith(".txt"):
        open(path, "w").write("\n".join(colors))
    else:
        lines = ["GIMP Palette", f"Name: {name}", "Columns: 8", "#"]
        for hx in colors:
            c = QColor(hx)
            lines.append(f"{c.red():3d} {c.green():3d} {c.blue():3d}\t{hx}")
        open(path, "w").write("\n".join(lines) + "\n")


def extract_colors(path, k, accuracy):
    """k-means в пространстве LAB. accuracy 1..100 → размер выборки и число итераций."""
    img = QImage(path)
    if img.isNull():
        return []
    side = int(32 + accuracy / 100 * 352)
    img = img.scaled(side, side, Qt.KeepAspectRatio, Qt.SmoothTransformation).convertToFormat(QImage.Format_RGB888)
    w, h, bpl = img.width(), img.height(), img.bytesPerLine()
    arr = np.frombuffer(img.constBits(), np.uint8, count=h * bpl).reshape(h, bpl)[:, :w * 3].reshape(-1, 3) / 255.0
    lab = rgb2lab(arr)
    rng = np.random.default_rng(0)
    # k-means++ init
    cent = [lab[rng.integers(len(lab))]]
    for _ in range(k - 1):
        d = np.min(((lab[:, None] - np.array(cent)[None]) ** 2).sum(-1), 1)
        cent.append(lab[rng.choice(len(lab), p=d / d.sum())] if d.sum() > 0 else lab[rng.integers(len(lab))])
    cent = np.array(cent)
    for _ in range(4 + accuracy // 4):
        lbl = np.argmin(((lab[:, None] - cent[None]) ** 2).sum(-1), 1)
        new = np.array([lab[lbl == i].mean(0) if np.any(lbl == i) else cent[i] for i in range(k)])
        if np.allclose(new, cent, atol=0.05):
            break
        cent = new
    cent = cent[np.argsort(cent[:, 0])]
    return list(dict.fromkeys(to_hex(clip3(lab2rgb(c))) for c in cent))


# ============================================================== panels / main window
MIME = "application/x-dcp-module"


class Panel(QMainWindow):
    def __init__(self, state, name):
        super().__init__()
        self.state, self.name = state, name
        self.setDockNestingEnabled(True)
        self.setAcceptDrops(True)
        self.setDockOptions(QMainWindow.AnimatedDocks | QMainWindow.AllowNestedDocks | QMainWindow.AllowTabbedDocks)
        hint = QLabel("Перетащите модули сюда из библиотеки (☰ Модули)")
        hint.setAlignment(Qt.AlignCenter)
        hint.setStyleSheet("color: gray")
        self.setCentralWidget(hint)
        self.centralWidget().setMaximumSize(0, 0)
        self.docks = []

    def add_module(self, title, cfg=None, mid=None):
        cls = MODULES.get(title)
        if not cls:
            return
        dock = QDockWidget(title, self)
        dock.setObjectName(mid or uuid.uuid4().hex)
        dock.setWidget(cls(self.state, cfg))
        dock.setAttribute(Qt.WA_DeleteOnClose)
        dock.destroyed.connect(lambda *_, d=dock: self.docks.remove(d) if d in self.docks else None)
        self.addDockWidget(Qt.RightDockWidgetArea, dock)
        self.docks.append(dock)
        return dock

    def dragEnterEvent(self, e):
        if e.mimeData().hasFormat(MIME):
            e.acceptProposedAction()

    def dropEvent(self, e):
        self.add_module(bytes(e.mimeData().data(MIME)).decode())
        e.acceptProposedAction()

    def to_config(self):
        mods = []
        for d in self.docks:
            try:
                mods.append({"type": d.windowTitle(), "id": d.objectName(), "cfg": d.widget().get_config()})
            except RuntimeError:
                pass
        return {"name": self.name, "modules": mods, "state": bytes(self.saveState().toBase64()).decode()}

    @classmethod
    def from_config(cls, state, c):
        p = cls(state, c.get("name", "Панель"))
        for m in c.get("modules", []):
            p.add_module(m["type"], m.get("cfg"), m.get("id"))
        if c.get("state"):
            p.restoreState(QByteArray.fromBase64(c["state"].encode()))
        return p


class ModuleLibrary(QListWidget):
    def __init__(self):
        super().__init__()
        self.setDragEnabled(True)
        self.setMaximumWidth(150)
        for t in MODULES:
            self.addItem(QListWidgetItem(t))
        self.setToolTip("Перетащите модуль на панель (или двойной клик)")

    def startDrag(self, actions):
        it = self.currentItem()
        if not it:
            return
        md = QMimeData()
        md.setData(MIME, it.text().encode())
        drag = QDrag(self)
        drag.setMimeData(md)
        drag.exec(Qt.CopyAction)


class SettingsDialog(QDialog):
    def __init__(self, parent, cfg):
        super().__init__(parent)
        self.setWindowTitle("Всплытие у пера")
        f = QFormLayout(self)
        self.hotkey = QLineEdit(cfg.get("hotkey", "<ctrl>+<alt>+c"))
        self.middle = QCheckBox("Средняя кнопка / боковая кнопка пера")
        self.middle.setChecked(cfg.get("middle_click", False))
        self.autoret = QCheckBox("Возвращать на место, когда курсор уходит с окна")
        self.autoret.setChecked(cfg.get("auto_return", True))
        f.addRow("Горячая клавиша (pynput):", self.hotkey)
        f.addRow(self.middle)
        f.addRow(self.autoret)
        note = QLabel("Назначьте боковой кнопке пера в драйвере планшета\nсреднюю кнопку мыши или эту горячую клавишу.")
        note.setStyleSheet("color: gray")
        f.addRow(note)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        f.addRow(bb)

    def values(self):
        return {"hotkey": self.hotkey.text().strip(), "middle_click": self.middle.isChecked(),
                "auto_return": self.autoret.isChecked()}


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


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Dynamic Color Picker")
        self.state = ColorState()
        self.state.csp = CSPLink(self.state)
        self.cfg = self._load()
        self.pinned_pos = None
        self.popped = False

        tb = QToolBar()
        tb.setMovable(False)
        self.addToolBar(tb)
        self.act_lib = QAction("☰ Модули", self, checkable=True)
        self.act_lib.toggled.connect(lambda v: self.lib.setVisible(v))
        tb.addAction(self.act_lib)
        tb.addAction("＋ Панель", self.new_panel)
        tb.addAction("✎", self.rename_panel).setToolTip("Переименовать панель")
        tb.addSeparator()
        self.act_pin = QAction("📌 Закрепить", self, checkable=True)
        self.act_pin.toggled.connect(self.set_pinned)
        tb.addAction(self.act_pin)
        tb.addAction("⚙", self.settings).setToolTip("Всплытие у пера")

        body = QWidget()
        h = QHBoxLayout(body)
        h.setContentsMargins(0, 0, 0, 0)
        self.lib = ModuleLibrary()
        self.lib.itemDoubleClicked.connect(lambda it: self.tabs.currentWidget().add_module(it.text()))
        self.lib.setVisible(False)
        h.addWidget(self.lib)
        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.tabCloseRequested.connect(self.close_panel)
        h.addWidget(self.tabs, 1)
        self.setCentralWidget(body)

        self._apply_cfg()
        self.trigger = GlobalTrigger()
        self.trigger.fired.connect(self.popup_toggle, Qt.QueuedConnection)
        self._setup_trigger()
        self._leave = QTimer(singleShot=True, interval=700)
        self._leave.timeout.connect(self._maybe_return)
        self.state.csp.statusChanged.connect(lambda t, ok: self.statusBar().showMessage(("CSP ✓ " if ok else "CSP: ") + t, 0 if ok else 6000))
        if self.cfg.get("csp_autoreconnect", True) and cspc.load_session(APP_DIR):
            QTimer.singleShot(500, self.state.csp.reconnect)

    # ---------- config
    def _load(self):
        try:
            return json.load(open(CONFIG_PATH, encoding="utf-8"))
        except Exception:
            return {}

    def _apply_cfg(self):
        c = self.cfg
        s = self.state
        s.palettes = c.get("palettes", s.palettes) or s.palettes
        s.current_palette = c.get("current_palette", next(iter(s.palettes)))
        if s.current_palette not in s.palettes:
            s.current_palette = next(iter(s.palettes))
        s.history = c.get("history", [])
        s.auto_send = c.get("auto_send", False)
        if c.get("fg"):
            s.fg = from_hex(c["fg"]) or s.fg
        if c.get("bg"):
            s.bg = from_hex(c["bg"]) or s.bg
        panels = c.get("panels") or [
            {"name": "Основная", "modules": [{"type": "Color Picker"}, {"type": "Color Modes"},
                                             {"type": "Luma Palette"}, {"type": "History"}]},
            {"name": "Слайдеры и палитры", "modules": [{"type": "Color Sliders", "cfg": {"spaces": ["HSV", "LCH"]}},
                                                       {"type": "Swatches"}, {"type": "CSP Companion"}, {"type": "Output / Send"}]},
        ]
        for pc in panels:
            p = Panel.from_config(self.state, pc)
            self.tabs.addTab(p, p.name)
        self.tabs.setCurrentIndex(c.get("tab", 0))
        if c.get("geometry"):
            self.restoreGeometry(QByteArray.fromBase64(c["geometry"].encode()))
        else:
            self.resize(380, 620)
        if c.get("pinned"):
            self.pinned_pos = QPoint(*c.get("pinned_pos", [self.x(), self.y()]))
            self.act_pin.setChecked(True)

    def save(self):
        os.makedirs(APP_DIR, exist_ok=True)
        s = self.state
        c = dict(self.cfg)
        c.update({
            "panels": [self.tabs.widget(i).to_config() for i in range(self.tabs.count())],
            "tab": self.tabs.currentIndex(),
            "palettes": s.palettes, "current_palette": s.current_palette,
            "history": s.history, "auto_send": s.auto_send,
            "fg": to_hex(s.fg), "bg": to_hex(s.bg),
            "geometry": bytes(self.saveGeometry().toBase64()).decode(),
            "pinned": self.act_pin.isChecked(),
            "pinned_pos": [self.pinned_pos.x(), self.pinned_pos.y()] if self.pinned_pos else None,
        })
        json.dump(c, open(CONFIG_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    def closeEvent(self, e):
        if self.popped:
            self._return_home()
        self.save()
        self.trigger.stop()
        self.state.csp.disconnect()
        super().closeEvent(e)

    # ---------- panels
    def new_panel(self):
        name, ok = QInputDialog.getText(self, "Новая панель", "Имя:", text=f"Панель {self.tabs.count() + 1}")
        if ok and name:
            p = Panel(self.state, name)
            self.tabs.setCurrentIndex(self.tabs.addTab(p, name))
            self.act_lib.setChecked(True)

    def rename_panel(self):
        p = self.tabs.currentWidget()
        name, ok = QInputDialog.getText(self, "Переименовать", "Имя:", text=p.name)
        if ok and name:
            p.name = name
            self.tabs.setTabText(self.tabs.currentIndex(), name)

    def close_panel(self, i):
        if self.tabs.count() > 1 and QMessageBox.question(self, "Закрыть", f"Удалить панель «{self.tabs.tabText(i)}»?") == QMessageBox.Yes:
            self.tabs.widget(i).deleteLater()
            self.tabs.removeTab(i)

    # ---------- pin / popup
    def set_pinned(self, on):
        flags = self.windowFlags()
        self.setWindowFlag(Qt.WindowStaysOnTopHint, on)
        if on and not self.popped:
            self.pinned_pos = self.pos()
        self.show()

    def moveEvent(self, e):
        if self.act_pin.isChecked() and not self.popped and not getattr(self, "_moving", False):
            self.pinned_pos = self.pos()
        super().moveEvent(e)

    def _move(self, pt):
        self._moving = True
        self.move(pt)
        self._moving = False

    def popup_toggle(self):
        if self.popped:
            self._return_home()
            return
        cur = QCursor.pos()
        scr = QGuiApplication.screenAt(cur) or QGuiApplication.primaryScreen()
        g = scr.availableGeometry()
        fg = self.frameGeometry()
        x = min(max(g.left(), cur.x() - fg.width() // 2), g.right() - fg.width())
        y = min(max(g.top(), cur.y() - 40), g.bottom() - fg.height())
        if not self.act_pin.isChecked() and not self.pinned_pos:
            self.pinned_pos = self.pos()
        self.popped = True
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        self.showNormal()
        self._move(QPoint(x, y))
        self.raise_()
        self.activateWindow()

    def _return_home(self):
        self.popped = False
        if self.pinned_pos:
            self._move(self.pinned_pos)
        if not self.act_pin.isChecked():
            self.setWindowFlag(Qt.WindowStaysOnTopHint, False)
            self.show()

    def leaveEvent(self, e):
        if self.popped and self.cfg.get("auto_return", True):
            self._leave.start()
        super().leaveEvent(e)

    def enterEvent(self, e):
        self._leave.stop()
        super().enterEvent(e)

    def _maybe_return(self):
        if self.popped and not self.frameGeometry().contains(QCursor.pos()) and not QApplication.mouseButtons():
            self._return_home()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape and self.popped:
            self._return_home()
        super().keyPressEvent(e)

    def _setup_trigger(self):
        ok = self.trigger.configure(self.cfg.get("hotkey", "<ctrl>+<alt>+c"), self.cfg.get("middle_click", False))
        if not ok:
            self.statusBar().showMessage("pynput не установлен: всплытие у пера отключено (pip install pynput)", 8000)

    def settings(self):
        d = SettingsDialog(self, self.cfg)
        if d.exec():
            self.cfg.update(d.values())
            self._setup_trigger()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Dynamic Color Picker")
    app.setStyle("Fusion")
    w = MainWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
