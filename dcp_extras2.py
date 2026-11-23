"""
Компоненты для живописи: Атмосферная перспектива, Контроль контраста, Кожа и материалы.
Все расчёты оттенков — в OKLab/OKLCH (перцептивно ровно).
"""
import math

import numpy as np
from PySide6.QtCore import Qt, QPointF, QRectF, QPoint
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QMenu

import dcp_app as ui
from dcp_core import (rgb2lab, to_qcolor, to_hex, from_hex, clip3, rgb2oklab, oklab2rgb, oklch_in_gamut, rgb2oklch,
                      lch_in_gamut, _lin, luma_of, LUMA_METRIC)
from dcp_extras import _chip, _label


def _mix(rgb_a, rgb_b, t):
    la, lb = rgb2oklab(np.array(rgb_a)), rgb2oklab(np.array(rgb_b))
    return clip3(oklab2rgb(la * (1 - t) + lb * t))


def _menu_pick(widget, items, current, cb, at):
    m = QMenu(widget)
    for k, label in items:
        a = m.addAction(("●  " if k == current else "    ") + label)
        a.triggered.connect(lambda _=False, k=k: cb(k))
    m.exec(widget.mapToGlobal(at))


# ============================================================== Атмосферная перспектива
AIR = {
    "day": ("Ясный день", "#B9CDE8"),
    "haze": ("Дымка / туман", "#C9CED4"),
    "sunset": ("Закат", "#E7B79C"),
    "dusk": ("Сумерки", "#7D7FA8"),
    "night": ("Ночь", "#2A3552"),
    "dust": ("Пыль / пустыня", "#D6C3A0"),
}


class AtmosphereComp(ui.Comp):
    """Сдвигает цвет к цвету воздуха по мере удаления: дальше — светлее, холоднее, менее насыщенно."""
    KEY = "atmosphere"

    def __init__(self, app, opts=None):
        super().__init__(app, opts)
        self.opts.setdefault("air", "day")
        self.opts.setdefault("custom", None)
        self.dist = 0.0
        self.base = self.state.color()
        self._drag = False
        self.state.changed.connect(self._on_state)
        self.setToolTip("Слайдер — расстояние. База — цвет, выбранный в других компонентах. Колёсико — шаг")

    def heightFor(self, w):
        return 74

    def _on_state(self, src):
        if src is not self:
            self.base = self.state.color()
            self.dist = 0.0
        self.update()

    def _air(self):
        if self.opts["air"] == "custom" and self.opts["custom"]:
            return from_hex(self.opts["custom"])
        return from_hex(AIR.get(self.opts["air"], AIR["day"])[1])

    def _at(self, d):
        return _mix(self.base, self._air(), min(0.9, d ** 0.85 * 0.9))

    def _bar(self):
        return QRectF(4, 30, self.width() - 8, 8)

    def _cells(self):
        n = 7
        w = self.width()
        cw = (w - (n - 1) * 4) / n
        return [(QRectF(i * (cw + 4), 48, cw, 22), i / (n - 1)) for i in range(n)]

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        name = "Свой" if self.opts["air"] == "custom" else AIR.get(self.opts["air"], AIR["day"])[0]
        _label(p, QRectF(0, 0, self.width() - 60, 20), f"Атмосфера · {name}  ▾", ui.TXT, bold=True)
        _label(p, QRectF(self.width() - 80, 0, 80, 20), f"{self.dist * 100:.0f}%", ui.DIM, Qt.AlignRight | Qt.AlignVCenter)
        stops = [to_qcolor(self._at(k / 8)) for k in range(9)]
        ui.draw_bar(p, self._bar(), stops, self.dist)
        cur = to_hex(self.state.color())
        for r, d in self._cells():
            hx = to_hex(self._at(d))
            _chip(p, r, hx, active=hx == cur, rad=4)

    def mousePressEvent(self, e):
        pos = e.position()
        if pos.y() < 22:
            items = list((k, v[0]) for k, v in AIR.items()) + [("custom", "Свой: текущий цвет как воздух")]
            _menu_pick(self, items, self.opts["air"], self._set_air, QPoint(0, 22))
            return
        if self._bar().adjusted(-6, -8, 6, 8).contains(pos):
            self._drag = True
            self._apply(pos, False)
            return
        for r, d in self._cells():
            if r.contains(pos):
                self.dist = d
                self.state.set_color(self._at(d), self)
                self.update()

    def _set_air(self, k):
        if k == "custom":
            self.opts["custom"] = to_hex(self.state.color())
        self.opts["air"] = k
        self.update()

    def mouseMoveEvent(self, e):
        if self._drag:
            self._apply(e.position(), False)

    def mouseReleaseEvent(self, e):
        if self._drag:
            self._apply(e.position(), True)
        self._drag = False

    def _apply(self, pos, commit):
        r = self._bar()
        self.dist = min(1.0, max(0.0, (pos.x() - r.left()) / r.width()))
        self.state.set_color(self._at(self.dist), self, commit)
        self.update()

    def adjust(self, step, pos):
        self.dist = min(1.0, max(0.0, self.dist + 0.05 * step))
        self.state.set_color(self._at(self.dist), self, True)
        self.update()
        return True


# ============================================================== Контроль контраста
def _rel_lum(rgb):
    return float(_lin(np.array(rgb)) @ np.array([0.2126, 0.7152, 0.0722]))


class ContrastComp(ui.Comp):
    """Разница яркости между основным и фоновым цветом: читается ли силуэт."""
    KEY = "contrast"

    def __init__(self, app, opts=None):
        super().__init__(app, opts)
        self.state.changed.connect(self._repaint)
        self.setToolTip("ΔL* — разница светлоты основного и фонового цвета. ПКМ — поменять их местами")

    def heightFor(self, w):
        return 66

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        fg, bg = self.state.fg, self.state.bg
        L1, L2 = luma_of(fg), luma_of(bg)
        dL = abs(L1 - L2)
        y1, y2 = _rel_lum(fg), _rel_lum(bg)
        ratio = (max(y1, y2) + 0.05) / (min(y1, y2) + 0.05)
        if dL >= 40:
            verdict, col = "сильный — силуэт читается", QColor("#2ECC71")
        elif dL >= 20:
            verdict, col = "средний", QColor("#F2C14E")
        elif dL >= 10:
            verdict, col = "слабый — формы сливаются", QColor("#F08A4B")
        else:
            verdict, col = "почти нет — силуэт пропадёт", QColor("#E5484D")
        # образец: фигура основного цвета на фоне
        box = QRectF(0, 4, 58, 58)
        p.setPen(Qt.NoPen)
        p.setBrush(to_qcolor(bg))
        p.drawRoundedRect(box, 8, 8)
        p.setBrush(to_qcolor(fg))
        p.drawEllipse(QRectF(14, 14, 30, 38))
        tag = "ΔL*" if LUMA_METRIC["value"] == "cielab" else "ΔLuma"
        _label(p, QRectF(68, 2, self.width() - 68, 18), f"Контраст {tag} {dL:.0f}  ·  {ratio:.1f}:1", ui.TXT, bold=True)
        _label(p, QRectF(68, 20, self.width() - 68, 16), verdict, col)
        bar = QRectF(68, 44, self.width() - 72, 8)
        g_stops = [to_qcolor(lch_in_gamut(k * 10, 0, 0)) for k in range(11)]
        ui.draw_bar(p, bar, g_stops, 0, knob=None)
        for L, c in ((L1, fg), (L2, bg)):
            x = bar.left() + L / 100 * bar.width()
            p.setPen(QPen(QColor("#F4F6FB"), 2))
            p.setBrush(to_qcolor(c))
            p.drawEllipse(QPointF(x, bar.center().y()), 6, 6)
        x1 = bar.left() + min(L1, L2) / 100 * bar.width()
        x2 = bar.left() + max(L1, L2) / 100 * bar.width()
        p.setPen(QPen(col, 2))
        p.drawLine(QPointF(x1, bar.top() - 4), QPointF(x2, bar.top() - 4))

    def mousePressEvent(self, e):
        if e.button() == Qt.RightButton:
            self.state.swap()


# ============================================================== Кожа и материалы
# параметры рампы: dl — шаг светлоты; тени: hue-цель, сдвиг°/шаг, рост хромы/шаг; блики: то же
RAMPS = {
    "skin":   dict(dl=0.075, sh=28, sa=5, sc=0.12, hh=75, ha=3, hc=-0.14),
    "gold":   dict(dl=0.13, sh=55, sa=7, sc=0.02, hh=95, ha=6, hc=-0.28),
    "silver": dict(dl=0.15, sh=255, sa=10, sc=0.40, hh=240, ha=4, hc=-0.30),
    "copper": dict(dl=0.12, sh=30, sa=6, sc=0.05, hh=70, ha=7, hc=-0.22),
    "steel":  dict(dl=0.13, sh=250, sa=10, sc=0.25, hh=230, ha=4, hc=-0.25),
    "cloth":  dict(dl=0.055, sh=270, sa=4, sc=0.06, hh=85, ha=2, hc=-0.05),
    "velvet": dict(dl=0.09, sh=0, sa=0, sc=0.16, hh=0, ha=0, hc=0.10),
    "silk":   dict(dl=0.10, sh=280, sa=4, sc=0.05, hh=60, ha=3, hc=-0.22),
    "wood":   dict(dl=0.08, sh=35, sa=5, sc=0.08, hh=80, ha=4, hc=-0.10),
    "leaves": dict(dl=0.08, sh=200, sa=9, sc=0.05, hh=110, ha=8, hc=-0.05),
}
MATERIALS = [
    ("Кожа", [("Светлая", "#F3D2C1", "skin"), ("Светлая тёплая", "#EAC0A0", "skin"), ("Средняя", "#D19E7C", "skin"),
              ("Оливковая", "#B9875F", "skin"), ("Смуглая", "#8D5A3B", "skin"), ("Тёмная", "#5A3825", "skin")]),
    ("Металл", [("Золото", "#C9A23A", "gold"), ("Серебро", "#A8AEB8", "silver"), ("Медь", "#B8693A", "copper"),
                ("Сталь", "#6E7681", "steel")]),
    ("Ткань", [("Деним", "#3E5C88", "cloth"), ("Лён", "#D9CDB6", "cloth"), ("Бархат", "#8C1C2E", "velvet"),
               ("Шёлк", "#B0304A", "silk")]),
    ("Природа", [("Дерево", "#8A5A35", "wood"), ("Листва", "#4E7A3A", "leaves")]),
]
TYPE_NAMES = {"skin": "кожа", "gold": "золото", "silver": "серебро", "copper": "медь", "steel": "сталь",
              "cloth": "матовая ткань", "velvet": "бархат", "silk": "шёлк", "wood": "дерево", "leaves": "листва"}
STEP_NAMES = ["глуб. тень", "тень", "полутень", "база", "свет", "яркий свет", "блик"]


def _toward(h, target, deg):
    d = (target - h + 540) % 360 - 180
    return h + max(-abs(d), min(abs(d), math.copysign(deg, d)))


def material_ramp(base_hex, kind):
    L, C, H = rgb2oklch(from_hex(base_hex))
    p = RAMPS.get(kind, RAMPS["cloth"])
    out = []
    for step in range(-3, 4):
        k = abs(step)
        if step < 0:
            h = _toward(H, p["sh"], p["sa"] * k) if p["sa"] else H
            c = max(0.0, C * (1 + p["sc"] * k)) if C > 0.004 else 0.012 * k * (p["sc"] > 0.2)
            l = L - p["dl"] * k
        elif step > 0:
            h = _toward(H, p["hh"], p["ha"] * k) if p["ha"] else H
            c = max(0.0, C * (1 + p["hc"] * k))
            room = max(0.0, 0.975 - L)                     # запас светлоты до белого
            boost = 1.25 if kind in ("silk", "gold", "silver", "steel", "copper") and k == 3 else 1
            l = L + min(p["dl"] * k * boost, room * k / 3.2)
        else:
            h, c, l = H, C, L
        out.append(to_hex(oklch_in_gamut(min(0.99, max(0.04, l)), c, h % 360)))
    return out


class MaterialsComp(ui.Comp):
    """Готовые рампы для кожи разных тонов, металлов, тканей, дерева и листвы — с правильными тенями и бликами."""
    KEY = "materials"

    def __init__(self, app, opts=None):
        super().__init__(app, opts)
        self.opts.setdefault("item", ["Кожа", "Средняя"])
        self.opts.setdefault("custom", None)       # [hex, kind] — от текущего цвета
        self.state.changed.connect(self._repaint)
        self.setToolTip("Клик по заголовку — материал. ПКМ по рампе — сохранить как набор")

    def heightFor(self, w):
        return 62

    def _current(self):
        if self.opts["custom"]:
            hx, kind = self.opts["custom"]
            return f"Текущий цвет ({TYPE_NAMES.get(kind, kind)})", hx, kind
        cat, name = self.opts["item"]
        for c, items in MATERIALS:
            if c == cat:
                for n, hx, kind in items:
                    if n == name:
                        return f"{cat}: {n}", hx, kind
        n, hx, kind = MATERIALS[0][1][2]
        return f"Кожа: {n}", hx, kind

    def _cells(self):
        n = 7
        cw = (self.width() - (n - 1) * 3) / n
        return [QRectF(i * (cw + 3), 22, cw, 26) for i in range(n)]

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        title, hx, kind = self._current()
        _label(p, QRectF(0, 0, self.width(), 20), title + "  ▾", ui.TXT, bold=True)
        cur = to_hex(self.state.color())
        ramp = material_ramp(hx, kind)
        f = p.font()
        f.setPointSizeF(max(6.5, f.pointSizeF() - 1.5))
        for i, (r, c) in enumerate(zip(self._cells(), ramp)):
            _chip(p, r, c, active=c == cur, rad=4)
            if i in (0, 3, 6):
                p.setFont(f)
                _label(p, QRectF(r.left() - 10, r.bottom() + 1, r.width() + 20, 12), STEP_NAMES[i], ui.DIM,
                       Qt.AlignCenter)

    def mousePressEvent(self, e):
        pos = e.position()
        if pos.y() < 20:
            self._menu(e.globalPosition().toPoint())
            return
        title, hx, kind = self._current()
        ramp = material_ramp(hx, kind)
        for r, c in zip(self._cells(), ramp):
            if r.contains(pos):
                if e.button() == Qt.RightButton:
                    m = QMenu(self)
                    m.addAction("Сохранить рампу как набор", lambda: self._save(title, ramp))
                    m.exec(e.globalPosition().toPoint())
                else:
                    self.state.set_color(from_hex(c), self)
                return

    def _menu(self, gpos):
        m = QMenu(self)
        for cat, items in MATERIALS:
            sub = m.addMenu(cat)
            for n, hx, kind in items:
                a = sub.addAction(n)
                a.triggered.connect(lambda _=False, c=cat, n=n: self._pick(c, n))
        m.addSeparator()
        sub = m.addMenu("От текущего цвета как…")
        for kind, name in TYPE_NAMES.items():
            a = sub.addAction(name)
            a.triggered.connect(lambda _=False, k=kind: self._custom(k))
        m.exec(gpos)

    def _pick(self, cat, n):
        self.opts["item"] = [cat, n]
        self.opts["custom"] = None
        self.update()

    def _custom(self, kind):
        self.opts["custom"] = [to_hex(self.state.color()), kind]
        self.update()

    def _save(self, title, ramp):
        name, k = title, 2
        while name in self.state.palettes:
            name, k = f"{title} {k}", k + 1
        self.state.palettes[name] = list(ramp)
        self.state.current_palette = name
        self.state.palettesChanged.emit()


ui.EXTRA_COMPONENTS.update({"atmosphere": AtmosphereComp, "contrast": ContrastComp, "materials": MaterialsComp})
ui.COMPONENTS.insert(2, ("Painting", [("atmosphere", "Atmosphere", "◍"), ("contrast", "Contrast", "◑"),
                                      ("materials", "Skin & Materials", "◆")]))
