"""
Управление CSP через Companion Mode: Быстрый доступ (DoQuickAccess), Холст (DoNavigator), Кисть (SetBrushSize/SetAlpha).
Все три — компоненты панели (группа «CSP Control» в редакторе).
"""
import math

from PySide6.QtCore import Qt, QRectF, QPointF, QPoint
from PySide6.QtGui import QPainter, QColor, QPen, QPainterPath
from PySide6.QtWidgets import QMenu

import dcp_app as ui
from dcp_extras import _label

NAV = [  # (CommandType, подпись, глиф)
    ("ZoomOut", "Уменьшить", "−"), ("ZoomIn", "Увеличить", "+"), ("Fitting", "Вписать в окно", "⤢"),
    ("PixelSize", "100%", "1:1"), ("RotateLeft", "Повернуть влево", "↶"), ("RotateRight", "Повернуть вправо", "↷"),
    ("Rotate0", "Сбросить поворот", "⟲"), ("ReverseHorz", "Отразить по горизонтали", "⇋"),
    ("ReverseVert", "Отразить по вертикали", "⇵"), ("ResetPosition", "Сбросить положение", "⌖"),
]


def _btn(p, r, hover=False, checked=False):
    p.setPen(Qt.NoPen)
    p.setBrush(ui.ACCENT if checked else (ui.BTN_HI if hover else ui.BTN))
    p.drawRoundedRect(r, 7, 7)


def _offline(p, rect, text="Нет связи с CSP — ☰ → Подключение к CSP"):
    _label(p, rect, text, ui.DIM, Qt.AlignCenter)


class _ButtonGrid(ui.Comp):
    """Общая сетка кнопок с подсветкой при наведении."""
    CELL, GAP, TOP = 34, 6, 22

    def __init__(self, app, opts=None):
        super().__init__(app, opts)
        self.link = self.state.csp
        self._hover = -1
        self.setMouseTracking(True)
        self.link.statusChanged.connect(self._relayout)

    def _relayout(self, *_):
        self.app.relayout()
        self.update()

    def _cols(self, w=None):
        w = w or self.width()
        return max(1, int((w + self.GAP) // (self.CELL + self.GAP)))

    def _rects(self, n):
        c = self._cols()
        return [QRectF((i % c) * (self.CELL + self.GAP), self.TOP + (i // c) * (self.CELL + self.GAP),
                       self.CELL, self.CELL) for i in range(n)]

    def _grid_h(self, n, w):
        return self.TOP + max(1, math.ceil(n / self._cols(w))) * (self.CELL + self.GAP)

    def mouseMoveEvent(self, e):
        h = next((i for i, r in enumerate(self._rects(self._count())) if r.contains(e.position())), -1)
        if h != self._hover:
            self._hover = h
            self.update()
            self.setToolTip(self._tip(h) if h >= 0 else "")

    def leaveEvent(self, e):
        self._hover = -1
        self.update()


class QuickAccessComp(_ButtonGrid):
    """Ваши кнопки из Quick Access CSP (инструменты и команды) + отмена / повтор."""
    KEY = "quick_access"
    FIXED = [("undo", "Отменить (Ctrl+Z)", "↶"), ("redo", "Повторить", "↷")]

    def __init__(self, app, opts=None):
        super().__init__(app, opts)
        self.link.quickChanged.connect(self._relayout)

    def _items(self):
        ls = self.link
        if not ls.qa_sets:
            return []
        idx = self.opts.get("set", ls.qa_current)
        idx = idx if 0 <= idx < len(ls.qa_sets) else 0
        return ls.qa_sets[idx]["items"]

    def _count(self):
        return len(self.FIXED) + len(self._items())

    def heightFor(self, w):
        if not self.link.connected:
            return 46
        return self._grid_h(self._count(), w)

    def _tip(self, i):
        if i < len(self.FIXED):
            return self.FIXED[i][1]
        it = self._items()[i - len(self.FIXED)]
        return it.get("name") or it.get("ItemIDCommandName") or "Инструмент"

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        ls = self.link
        name = ls.qa_sets[self.opts.get("set", ls.qa_current)]["name"] if ls.qa_sets and \
            0 <= self.opts.get("set", ls.qa_current) < len(ls.qa_sets) else ""
        _label(p, QRectF(0, 0, self.width(), 18), "Быстрый доступ" + (f" · {name}  ▾" if name else "  ▾"),
               ui.TXT, bold=True)
        if not ls.connected:
            _offline(p, QRectF(0, 20, self.width(), 24))
            return
        items = self._items()
        f = p.font()
        for i, r in enumerate(self._rects(self._count())):
            _btn(p, r, hover=(i == self._hover))
            if i < len(self.FIXED):
                f.setPointSizeF(13)
                p.setFont(f)
                p.setPen(ui.TITLE)
                p.drawText(r, Qt.AlignCenter, self.FIXED[i][2])
                continue
            it = items[i - len(self.FIXED)]
            img = ls.icons.get(ls.item_key(it))
            if img is not None:
                s = 24
                p.drawImage(QRectF(r.center().x() - s / 2, r.center().y() - s / 2, s, s), img)
            else:
                f.setPointSizeF(7)
                p.setFont(f)
                p.setPen(ui.TXT)
                p.drawText(r.adjusted(2, 2, -2, -2), Qt.AlignCenter | Qt.TextWordWrap, (it.get("name") or "?")[:10])

    def mousePressEvent(self, e):
        pos = e.position()
        if pos.y() < 20:
            m = QMenu(self)
            for i, st in enumerate(self.link.qa_sets):
                a = m.addAction(("●  " if i == self.opts.get("set", self.link.qa_current) else "    ") + st["name"])
                a.triggered.connect(lambda _=False, i=i: (self.opts.__setitem__("set", i), self._relayout()))
            m.addSeparator()
            m.addAction("    Обновить из CSP", self.link.refresh_quick)
            m.exec(e.globalPosition().toPoint())
            return
        for i, r in enumerate(self._rects(self._count())):
            if r.contains(pos):
                if i < len(self.FIXED):
                    self.link.command(self.FIXED[i][0])
                else:
                    self.link.do_item(self._items()[i - len(self.FIXED)])
                return


class CanvasNavComp(_ButtonGrid):
    """Холст CSP: масштаб, поворот, отражение. Колёсико — масштаб, Shift+колёсико — поворот."""
    KEY = "canvas_nav"

    def _count(self):
        return len(NAV)

    def _tip(self, i):
        return NAV[i][1]

    def heightFor(self, w):
        return self._grid_h(len(NAV), w)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        _label(p, QRectF(0, 0, self.width(), 18), "Холст", ui.TXT, bold=True)
        _label(p, QRectF(0, 0, self.width(), 18), "колёсико — масштаб, Shift — поворот", ui.DIM,
               Qt.AlignRight | Qt.AlignVCenter)
        p.setOpacity(1.0 if self.link.connected else 0.4)
        f = p.font()
        for i, r in enumerate(self._rects(len(NAV))):
            _btn(p, r, hover=(i == self._hover))
            f.setPointSizeF(9 if len(NAV[i][2]) > 1 else 13)
            p.setFont(f)
            p.setPen(ui.TITLE)
            p.drawText(r, Qt.AlignCenter, NAV[i][2])

    def mousePressEvent(self, e):
        for i, r in enumerate(self._rects(len(NAV))):
            if r.contains(e.position()):
                self.link.navigator(NAV[i][0])

    def wheelEvent(self, e):
        d = e.angleDelta().y() or e.angleDelta().x()
        if not d:
            return
        if e.modifiers() & Qt.ShiftModifier:
            self.link.navigator("RotateRight" if d > 0 else "RotateLeft")
        else:
            self.link.navigator("ZoomIn" if d > 0 else "ZoomOut")
        e.accept()

    def adjust(self, step, pos):
        for _ in range(min(5, abs(step))):
            self.link.navigator("ZoomIn" if step > 0 else "ZoomOut")
        return True


class BrushComp(ui.Comp):
    """Размер и непрозрачность кисти CSP прямо в панели."""
    KEY = "brush"

    def __init__(self, app, opts=None):
        super().__init__(app, opts)
        self.link = self.state.csp
        self._drag = -1
        self.link.toolChanged.connect(self._repaint)
        self.link.statusChanged.connect(self._repaint)
        self.setToolTip("Колёсико над строкой — шаг (Shift — крупнее). Клик по числу — точный ввод")

    def heightFor(self, w):
        return 82

    def _bar(self, i):
        return QRectF(24, 24 + i * 26 + 6, self.width() - 24 - 58, 6)

    def _vals(self):
        import dcp_brush as b
        t = self.link.tool
        sz, al = t.get("size"), t.get("alpha")
        return [(b.size_to_t(sz) if sz else 0, f"{b.fmt_size(sz)} px" if sz else "—"),
                ((al or 0) / 100, f"{al}%" if al is not None else "—")]

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        _label(p, QRectF(0, 0, self.width(), 18), "Кисть", ui.TXT, bold=True)
        if not self.link.connected:
            _label(p, QRectF(60, 0, self.width() - 60, 18), "нет связи с CSP", ui.DIM, Qt.AlignRight | Qt.AlignVCenter)
            p.setOpacity(0.4)
        vals = self._vals()
        for i, (name, (t, text)) in enumerate(zip(("⌀", "α"), vals)):
            r = self._bar(i)
            _label(p, QRectF(0, r.center().y() - 9, 20, 18), name, ui.DIM)
            _label(p, QRectF(self.width() - 56, r.center().y() - 9, 56, 18), text, ui.TXT, Qt.AlignRight | Qt.AlignVCenter)
            if i == 0:
                stops = [ui.GROOVE, ui.SCROLL, ui.ICON_HI]
            else:
                stops = [QColor(20, 20, 20, 30), QColor(20, 20, 20, 255)]
            ui.draw_bar(p, r, stops, t)

    def _row(self, pos):
        i = int((pos.y() - 24) // 26)
        return i if 0 <= i < 2 else -1

    def mousePressEvent(self, e):
        if not self.link.connected:
            return
        i = self._row(e.position())
        if i < 0:
            return
        if e.position().x() > self.width() - 58:
            import dcp_brush as b
            t = self.link.tool
            if i == 0:
                ui.NumPad.open(self, "Размер кисти, px", t.get("size") or 10, b.SIZE_MIN, b.SIZE_MAX,
                               lambda v: self.link.set_brush_size(v), self.mapToGlobal(QPoint(self.width(), 0)))
            else:
                ui.NumPad.open(self, "Непрозрачность, %", t.get("alpha") or 100, 0, 100,
                               lambda v: self.link.set_alpha(v), self.mapToGlobal(QPoint(self.width(), 26)))
            return
        self._drag = i
        self._apply(e.position())

    def mouseMoveEvent(self, e):
        if self._drag >= 0:
            self._apply(e.position())

    def mouseReleaseEvent(self, e):
        self._drag = -1

    def _apply(self, pos):
        import dcp_brush as b
        r = self._bar(self._drag)
        t = min(1.0, max(0.0, (pos.x() - r.left()) / r.width()))
        if self._drag == 0:
            self.link.set_brush_size(b.t_to_size(t))
        else:
            self.link.set_alpha(t * 100)
        self.update()

    def adjust(self, step, pos):
        i = self._row(pos)
        if i < 0 or not self.link.connected:
            return False
        t = self.link.tool
        if i == 0 and t.get("size"):
            import dcp_brush as b
            self.link.set_brush_size(min(b.SIZE_MAX, max(b.SIZE_MIN, t["size"] * (1.06 ** step))))
        elif i == 1 and t.get("alpha") is not None:
            self.link.set_alpha(min(100, max(0, t["alpha"] + step)))
        self.update()
        return True


ui.EXTRA_COMPONENTS.update({"quick_access": QuickAccessComp, "canvas_nav": CanvasNavComp, "brush": BrushComp})
ui.COMPONENTS.insert(3, ("CSP Control", [("quick_access", "Quick Access", "▤"), ("canvas_nav", "Canvas", "⤢"),
                                         ("brush", "Brush", "●")]))
