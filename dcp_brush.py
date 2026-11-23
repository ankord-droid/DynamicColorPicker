"""
Окно «Кисть» — размер и прозрачность текущего инструмента CSP, как отдельная панель в CSP.

Значения читаются из CSP через Companion Mode (CurrentToolBrushSize / CurrentToolAlphaPercent)
и отправляются командами SetBrushSize / SetAlpha. Размер — по логарифмической шкале 0.5…2000 px.
Колёсико над слайдером — шаг (Shift — крупнее), клик по кружку со значением — точный ввод.
"""
import math

from PySide6.QtCore import Qt, QRectF, QPointF, QPoint, Signal
from PySide6.QtGui import QPainter, QColor, QPen, QLinearGradient, QGuiApplication
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel

import dcp_app as ui

SIZE_MIN, SIZE_MAX = 0.5, 2000.0
_LOGR = math.log(SIZE_MAX / SIZE_MIN)


def size_to_t(px):
    return min(1.0, max(0.0, math.log(max(SIZE_MIN, px) / SIZE_MIN) / _LOGR))


def t_to_size(t):
    return SIZE_MIN * math.exp(min(1.0, max(0.0, t)) * _LOGR)


def fmt_size(px):
    return f"{px:.1f}" if px < 100 else f"{px:.0f}"


class VSlider(QWidget):
    """Вертикальный слайдер с кружком-значением сверху (как в CSP)."""
    moved = Signal(float, bool)     # t 0..1 (верх = 1), отпущено
    badgeClicked = Signal()

    def __init__(self, kind):
        super().__init__()
        self.kind = kind            # "size" | "alpha"
        self.t = 0.5
        self.text = "—"
        self.unit = ""
        self.enabled_ = False
        self._drag = False
        self._acc = 0.0
        self.setMinimumSize(48, 220)
        self.setCursor(Qt.PointingHandCursor)

    def set_value(self, t, text, unit, enabled):
        self.t, self.text, self.unit, self.enabled_ = t, text, unit, enabled
        self.update()

    def _badge(self):
        d = min(self.width() - 6, 44)
        return QRectF((self.width() - d) / 2, 2, d, d)

    def _track(self):
        b = self._badge()
        return QRectF(self.width() / 2 - 4, b.bottom() + 16, 8, self.height() - b.bottom() - 28)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setOpacity(1.0 if self.enabled_ else 0.45)
        b, tr = self._badge(), self._track()
        # кружок значения
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#E9A7C3") if self.kind == "alpha" else ui.BTN_HI)
        p.drawEllipse(b)
        p.setPen(QColor("#1D2333") if self.kind == "alpha" else ui.TITLE)
        f = p.font()
        f.setBold(True)
        f.setPointSizeF(8.5 if len(self.text) <= 4 else 7.5)
        p.setFont(f)
        p.drawText(b.adjusted(0, 4, 0, -b.height() / 2 + 6), Qt.AlignCenter, self.text)
        f.setBold(False)
        f.setPointSizeF(7.5)
        p.setFont(f)
        p.drawText(b.adjusted(0, b.height() / 2 - 2, 0, -4), Qt.AlignCenter, self.unit)
        # дорожка
        if self.kind == "alpha":
            p.save()
            p.setClipRect(tr)
            for yy in range(int(tr.top()), int(tr.bottom()) + 1, 4):
                for xx in range(int(tr.left()), int(tr.right()) + 1, 4):
                    p.fillRect(xx, yy, 4, 4, ui.CHK2 if ((xx // 4) + (yy // 4)) % 2 else ui.CHK1)
            p.restore()
            g = QLinearGradient(tr.topLeft(), tr.bottomLeft())
            g.setColorAt(0, QColor(15, 15, 15, 255))
            g.setColorAt(1, QColor(15, 15, 15, 0))
            p.setBrush(g)
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(tr, 4, 4)
        else:
            p.setPen(Qt.NoPen)
            p.setBrush(ui.GROOVE)
            p.drawRoundedRect(tr, 4, 4)
            y = tr.bottom() - self.t * tr.height()
            p.setBrush(ui.SCROLL)
            p.drawRoundedRect(QRectF(tr.left(), y, tr.width(), tr.bottom() - y), 4, 4)
        # ручка
        y = tr.bottom() - self.t * tr.height()
        p.setBrush(QColor(0, 0, 0, 90))
        p.drawEllipse(QPointF(tr.center().x(), y + 1), 11, 11)
        p.setBrush(QColor("#4A4F5C") if self.kind == "size" else QColor("#3A3F4C"))
        p.setPen(QPen(QColor("#F4F6FB"), 1.5))
        p.drawEllipse(QPointF(tr.center().x(), y), 10, 10)

    def _t_at(self, y):
        tr = self._track()
        return min(1.0, max(0.0, (tr.bottom() - y) / tr.height()))

    def mousePressEvent(self, e):
        if not self.enabled_:
            return
        if self._badge().contains(e.position()):
            self.badgeClicked.emit()
            return
        self._drag = True
        self.t = self._t_at(e.position().y())
        self.moved.emit(self.t, False)
        self.update()

    def mouseMoveEvent(self, e):
        if self._drag:
            self.t = self._t_at(e.position().y())
            self.moved.emit(self.t, False)
            self.update()

    def mouseReleaseEvent(self, e):
        if self._drag:
            self.moved.emit(self.t, True)
        self._drag = False

    def wheelEvent(self, e):
        if not self.enabled_:
            return
        self._acc += (e.angleDelta().y() or e.angleDelta().x()) / 120
        steps = int(self._acc)
        if not steps:
            return
        self._acc -= steps
        k = 5 if e.modifiers() & Qt.ShiftModifier else 1
        self.window().nudge(self.kind, steps * k)


class BrushWindow(QWidget):
    def __init__(self, panel):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowTitle("Кисть — Dynamic Color Picker")
        self.panel = panel
        self.link = panel.state.csp
        self._drag = None
        lay = QVBoxLayout(self)
        m = ui.SHADOW + 8
        lay.setContentsMargins(m, m - 2, m, m)
        lay.setSpacing(4)
        head = QHBoxLayout()
        t = QLabel("Кисть")
        t.setObjectName("head")
        t.setStyleSheet("padding-top:0")
        head.addWidget(t)
        head.addStretch()
        x = ui.IconButton("close", self, 20, "Закрыть")
        x.clicked.connect(self.hide)
        head.addWidget(x)
        lay.addLayout(head)
        row = QHBoxLayout()
        row.setSpacing(6)
        self.size = VSlider("size")
        self.alpha = VSlider("alpha")
        self.size.setToolTip("Размер кисти. Колёсико — шаг, Shift — крупнее, клик по кружку — точное значение")
        self.alpha.setToolTip("Непрозрачность кисти. Колёсико — ±1%, Shift — ±5%, клик по кружку — точное значение")
        self.size.moved.connect(lambda t, rel: self.link.set_brush_size(t_to_size(t)) or self._refresh())
        self.alpha.moved.connect(lambda t, rel: self.link.set_alpha(t * 100) or self._refresh())
        self.size.badgeClicked.connect(lambda: self._numpad("size"))
        self.alpha.badgeClicked.connect(lambda: self._numpad("alpha"))
        row.addWidget(self.size)
        row.addWidget(self.alpha)
        lay.addLayout(row, 1)
        self.setFixedWidth(2 * m + 2 * 48 + 6)
        self.resize(self.width(), int(panel.cfg.get("brush_h", 360)))
        g = panel.cfg.get("brush_pos")
        if g:
            self.move(*g)
        else:
            pg = panel.frameGeometry()
            self.move(pg.left() - self.width() + 6, pg.top())
        self.link.toolChanged.connect(self._refresh)
        self.link.statusChanged.connect(lambda *_: self._refresh())
        self._refresh()

    def _refresh(self, *_):
        t = self.link.tool
        on = self.link.connected
        sz, al = t.get("size"), t.get("alpha")
        self.size.set_value(size_to_t(sz) if sz else 0.5, fmt_size(sz) if sz else "—", t.get("unit") or "px",
                            on and t.get("size_ok", sz is not None) and sz is not None)
        self.alpha.set_value((al or 0) / 100, f"{al}" if al is not None else "—", "%",
                             on and t.get("alpha_ok", al is not None) and al is not None)
        tip = "" if on else "Нет связи с CSP — ☰ → Подключение к CSP"
        self.setToolTip(tip)

    def nudge(self, kind, steps):
        t = self.link.tool
        if kind == "size" and t.get("size"):
            self.link.set_brush_size(min(SIZE_MAX, max(SIZE_MIN, t["size"] * (1.06 ** steps))))
        elif kind == "alpha" and t.get("alpha") is not None:
            self.link.set_alpha(min(100, max(0, t["alpha"] + steps)))
        self._refresh()

    def _numpad(self, kind):
        t = self.link.tool
        if kind == "size":
            ui.NumPad.open(self, "Размер кисти, px", t.get("size") or 10, SIZE_MIN, SIZE_MAX,
                           lambda v: (self.link.set_brush_size(v), self._refresh()), self.mapToGlobal(QPoint(self.width(), 0)))
        else:
            ui.NumPad.open(self, "Непрозрачность, %", t.get("alpha") or 100, 0, 100,
                           lambda v: (self.link.set_alpha(v), self._refresh()), self.mapToGlobal(QPoint(self.width(), 0)))

    # ---- окно
    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        ui.paint_card(p, QRectF(self.rect()).adjusted(ui.SHADOW, ui.SHADOW, -ui.SHADOW, -ui.SHADOW), 12)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag = e.globalPosition().toPoint() - self.pos()
            self._resize = e.position().y() > self.height() - ui.SHADOW - 10

    def mouseMoveEvent(self, e):
        if self._drag is None:
            return
        if getattr(self, "_resize", False):
            self.resize(self.width(), max(240, int(e.position().y()) + ui.SHADOW))
        else:
            self.move(e.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, e):
        self._drag = None
        self.save_state()

    def save_state(self):
        self.panel.cfg["brush_pos"] = [self.x(), self.y()]
        self.panel.cfg["brush_h"] = self.height()
        self.panel.cfg["brush_open"] = self.isVisible()

    def hideEvent(self, e):
        self.save_state()
