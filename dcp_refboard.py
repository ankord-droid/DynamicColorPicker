"""
Референс-доска и генератор палитры.

Референс-доска — окно поверх всех: несколько картинок (Ctrl+V, перетаскивание, «Открыть»), миниатюры,
масштаб колёсиком, панорама ПКМ/СКМ, отражение, оттенки серого, пипетка ЛКМ, выделение области Shift+ЛКМ,
прозрачность окна и режим «сквозь клик». Картинки хранятся в ~/.dynamic_color_picker/refs.

Генератор палитры — из картинки или выделенной области: основные / яркие / приглушённые / тональные группы,
сортировка, доля каждого цвета, сохранение в наборы и экспорт.
"""
import json
import math
import os
import shutil
import time
import uuid

import numpy as np
from PySide6.QtCore import Qt, QPointF, QRectF, QPoint, QRect, QTimer, QSize, Signal, QUrl
from PySide6.QtGui import (QColor, QPainter, QPen, QImage, QPixmap, QGuiApplication, QCursor, QTransform,
                           QPainterPath)
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton, QSlider,
                               QSpinBox, QComboBox, QMenu, QFileDialog, QSizeGrip, QApplication, QMessageBox,
                               QScrollArea)

import dcp_app as ui
from dcp_core import APP_DIR, rgb2lab, lab2rgb, to_qcolor, to_hex, from_hex, clip3, qimage_rgb
from dcp_formats import export_palette, EXPORT_FILTER

REF_DIR = os.path.join(APP_DIR, "refs")
IMG_EXT = (".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff", ".gif")


# ============================================================== k-means с долями
def kmeans_lab(lab, k, iters=12, seed=0):
    """lab (N,3) -> (центры (k,3), доли (k,))"""
    n = len(lab)
    if n == 0:
        return np.zeros((0, 3)), np.zeros(0)
    k = max(1, min(k, n))
    rng = np.random.default_rng(seed)
    if n > 30000:
        lab = lab[rng.choice(n, 30000, replace=False)]
        n = len(lab)
    cent = [lab[rng.integers(n)]]
    for _ in range(k - 1):
        d = np.min(((lab[:, None] - np.array(cent)[None]) ** 2).sum(-1), 1)
        cent.append(lab[rng.choice(n, p=d / d.sum())] if d.sum() > 0 else lab[rng.integers(n)])
    cent = np.array(cent)
    for _ in range(iters):
        lbl = np.argmin(((lab[:, None] - cent[None]) ** 2).sum(-1), 1)
        new = np.array([lab[lbl == i].mean(0) if np.any(lbl == i) else cent[i] for i in range(k)])
        if np.allclose(new, cent, atol=0.05):
            cent = new
            break
        cent = new
    lbl = np.argmin(((lab[:, None] - cent[None]) ** 2).sum(-1), 1)
    share = np.bincount(lbl, minlength=k) / n
    keep = share > 0
    return cent[keep], share[keep]


MODES = [("main", "Основные цвета"), ("vivid", "Яркие акценты"), ("muted", "Приглушённые"),
         ("tonal", "Свет / средние / тени")]
SORTS = [("share", "по доле"), ("hue", "по тону"), ("light", "по яркости")]


def generate_palette(img, mode, count, accuracy, region=None):
    """Возвращает список групп [(подпись, [(hex, доля), ...]), ...]."""
    if img is None or img.isNull():
        return []
    if region is not None and not region.isEmpty():
        img = img.copy(region)
    side = int(64 + accuracy / 100 * 448)
    arr = qimage_rgb(img, side).reshape(-1, 3)
    lab = rgb2lab(arr)
    chroma = np.hypot(lab[:, 1], lab[:, 2])
    iters = 6 + accuracy // 8

    def pack(cent, share):
        return [(to_hex(clip3(lab2rgb(c))), float(s)) for c, s in zip(cent, share)]

    if mode == "vivid":
        thr = max(20.0, float(np.percentile(chroma, 65)))
        sel = lab[chroma >= thr]
        if len(sel) < count:
            sel = lab[np.argsort(chroma)[-max(count * 20, 200):]]
        return [("", pack(*kmeans_lab(sel, count, iters)))]
    if mode == "muted":
        thr = min(25.0, float(np.percentile(chroma, 50)))
        sel = lab[chroma <= thr]
        if len(sel) < count:
            sel = lab[np.argsort(chroma)[:max(count * 20, 200)]]
        return [("", pack(*kmeans_lab(sel, count, iters)))]
    if mode == "tonal":
        L = lab[:, 0]
        per = max(2, round(count / 3))
        out = []
        for name, m in (("свет", L >= 66), ("средние", (L >= 33) & (L < 66)), ("тени", L < 33)):
            sel = lab[m]
            if len(sel) >= per:
                c, s = kmeans_lab(sel, per, iters)
                out.append((name, pack(c, s * m.mean())))
        return out
    return [("", pack(*kmeans_lab(lab, count, iters)))]


def sort_group(cols, how):
    if how == "hue":
        def key(c):
            L, a, b = rgb2lab(np.array(from_hex(c[0])))
            return (math.hypot(a, b) < 8, math.degrees(math.atan2(b, a)) % 360)
        return sorted(cols, key=key)
    if how == "light":
        return sorted(cols, key=lambda c: -float(rgb2lab(np.array(from_hex(c[0])))[0]))
    return sorted(cols, key=lambda c: -c[1])


# ============================================================== генератор палитры
class ShareChips(QWidget):
    picked = Signal(str)

    def __init__(self):
        super().__init__()
        self.groups = []
        self.setMinimumHeight(60)

    def set_groups(self, groups):
        self.groups = groups
        rows = sum(1 + (len(g[1]) - 1) // 8 for g in groups) or 1
        self.setMinimumHeight(rows * 62 + 4)
        self.update()

    def _cells(self):
        out = []
        y = 0
        w = self.width()
        cw = (w - 7 * 6 - 70) / 8
        for label, cols in self.groups:
            for i, (hx, share) in enumerate(cols):
                r, c = divmod(i, 8)
                out.append((label if i == 0 else None, QRectF(70 + c * (cw + 6), y + r * 62, cw, 40), hx, share,
                            y + r * 62))
            y += (1 + (len(cols) - 1) // 8) * 62
        return out

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        for label, r, hx, share, y in self._cells():
            if label:
                p.setPen(ui.DIM)
                p.drawText(QRectF(0, y, 66, 40), Qt.AlignVCenter | Qt.AlignLeft, label)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(hx))
            p.drawRoundedRect(r, 6, 6)
            bar = QRectF(r.left(), r.bottom() + 5, r.width(), 4)
            p.setBrush(ui.GROOVE)
            p.drawRoundedRect(bar, 2, 2)
            p.setBrush(ui.ACCENT)
            p.drawRoundedRect(QRectF(bar.left(), bar.top(), max(3.0, bar.width() * min(1.0, share * 3)), 4), 2, 2)
            p.setPen(ui.DIM)
            p.drawText(QRectF(r.left(), bar.bottom() + 1, r.width(), 12), Qt.AlignCenter, f"{share * 100:.0f}%")

    def mousePressEvent(self, e):
        for _, r, hx, _, _ in self._cells():
            if r.contains(e.position()):
                self.picked.emit(hx)


class PaletteGenerator(ui.DarkDialog):
    def __init__(self, panel, img, title="Генератор палитры", region=None):
        super().__init__(panel, title)
        self.panel, self.state = panel, panel.state
        self.img, self.region = img, region
        self.setMinimumWidth(640)
        root = QHBoxLayout()
        root.setSpacing(16)
        self.outer.addLayout(root)
        prev = QLabel()
        prev.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
        src = img.copy(region) if region is not None and not region.isEmpty() else img
        pm = QPixmap.fromImage(src).scaled(240, 300, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        prev.setPixmap(pm)
        prev.setFixedWidth(250)
        root.addWidget(prev)
        right = QVBoxLayout()
        g = QGridLayout()
        g.setColumnStretch(1, 1)
        self.mode = QComboBox()
        for k, t in MODES:
            self.mode.addItem(t, k)
        self.sort = QComboBox()
        for k, t in SORTS:
            self.sort.addItem(t, k)
        self.count = QSpinBox()
        self.count.setRange(3, 32)
        self.count.setValue(panel.cfg.get("gen_count", 8))
        self.acc = QSlider(Qt.Horizontal)
        self.acc.setRange(1, 100)
        self.acc.setValue(panel.cfg.get("gen_acc", 60))
        for r, (lab, w) in enumerate((("Режим", self.mode), ("Сортировка", self.sort), ("Цветов", self.count),
                                      ("Extraction Accuracy", self.acc))):
            l = QLabel(lab)
            l.setObjectName("head")
            g.addWidget(l, r, 0)
            g.addWidget(w, r, 1)
        right.addLayout(g)
        self.chips = ShareChips()
        self.chips.picked.connect(lambda hx: self.state.set_color(from_hex(hx), None))
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setWidget(self.chips)
        sa.setMinimumHeight(200)
        right.addWidget(sa, 1)
        row = QHBoxLayout()
        save = ui.pill("Сохранить в наборы", "primary")
        save.clicked.connect(self._save)
        exp = ui.pill("Экспорт…", "ghost")
        exp.clicked.connect(self._export)
        row.addWidget(exp)
        row.addWidget(save, 2)
        right.addLayout(row)
        root.addLayout(right, 1)
        self._t = QTimer(self, singleShot=True, interval=150)
        self._t.timeout.connect(self._run)
        for sig in (self.mode.currentIndexChanged, self.sort.currentIndexChanged, self.count.valueChanged):
            sig.connect(lambda *_: self._t.start())
        self.acc.sliderReleased.connect(self._t.start)
        self.groups = []
        self._run()
        self.center_on(panel)

    def _run(self):
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            groups = generate_palette(self.img, self.mode.currentData(), self.count.value(), self.acc.value(),
                                      self.region)
        finally:
            QApplication.restoreOverrideCursor()
        self.groups = [(lab, sort_group(cols, self.sort.currentData())) for lab, cols in groups]
        self.chips.set_groups(self.groups)
        self.panel.cfg["gen_count"] = self.count.value()
        self.panel.cfg["gen_acc"] = self.acc.value()

    def _colors(self):
        return [hx for _, cols in self.groups for hx, _ in cols]

    def _save(self):
        cols = self._colors()
        if not cols:
            return
        base = "Палитра " + dict(MODES)[self.mode.currentData()].lower()
        name, k = base, 2
        while name in self.state.palettes:
            name, k = f"{base} {k}", k + 1
        self.state.palettes[name] = cols
        self.state.current_palette = name
        self.state.palettesChanged.emit()
        self.panel.tray.showMessage("Dynamic Color Picker", f"Сохранено в наборы: «{name}»",
                                    ui.QSystemTrayIcon.Information, 2500)

    def _export(self):
        cols = self._colors()
        if not cols:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Экспорт палитры", "Палитра.cls", EXPORT_FILTER)
        if path:
            export_palette(path, os.path.splitext(os.path.basename(path))[0], cols)


# ============================================================== референс-доска
class RefCanvas(QWidget):
    picked = Signal(tuple, bool)       # rgb, commit

    def __init__(self):
        super().__init__()
        self.img = None
        self.gray = None
        self.zoom, self.off = 1.0, QPointF(0, 0)
        self.flip = False
        self.gray_on = False
        self.region = None              # QRect в координатах изображения
        self._pan = None
        self._sel = None
        self._picking = False
        self._before = None
        self._mpos = QPointF()
        self.setMouseTracking(True)
        self.setCursor(Qt.CrossCursor)
        self.setMinimumSize(200, 150)

    def set_image(self, img):
        self.img = img
        self.gray = img.convertToFormat(QImage.Format_Grayscale8) if img is not None else None
        self.region = None
        self.fit()

    def fit(self):
        if not self.img:
            return
        w, h = self.width(), self.height()
        self.zoom = min(w / self.img.width(), h / self.img.height()) * 0.96
        self.off = QPointF((w - self.img.width() * self.zoom) / 2, (h - self.img.height() * self.zoom) / 2)
        self.update()

    def resizeEvent(self, e):
        if self.img and e.oldSize().width() > 0:
            self.fit()

    def _xf(self):
        t = QTransform()
        t.translate(self.off.x(), self.off.y())
        t.scale(self.zoom, self.zoom)
        if self.flip:
            t.translate(self.img.width(), 0)
            t.scale(-1, 1)
        return t

    def _to_img(self, pos):
        inv, ok = self._xf().inverted()
        pt = inv.map(pos)
        return pt

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 60))
        p.drawRoundedRect(QRectF(self.rect()), 10, 10)
        if not self.img:
            p.setPen(ui.DIM)
            p.drawText(self.rect(), Qt.AlignCenter,
                       "Ctrl+V — вставить из буфера\nили перетащите картинки сюда")
            return
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(self.rect()), 10, 10)
        p.setClipPath(clip)
        p.setRenderHint(QPainter.SmoothPixmapTransform, self.zoom < 2)
        p.setTransform(self._xf())
        p.drawImage(0, 0, self.gray if self.gray_on else self.img)
        if self.region is not None:
            p.setPen(QPen(ui.ACCENT, 2 / self.zoom, Qt.DashLine))
            p.setBrush(Qt.NoBrush)
            p.drawRect(QRectF(self.region))
        p.resetTransform()
        if self._sel:
            p.setPen(QPen(ui.ACCENT, 1.5, Qt.DashLine))
            p.drawRect(QRectF(self._sel[0], self._sel[1]).normalized())
        if self._picking and self._before:
            ui.draw_compare(p, self._mpos, self._cur, self._before, self.rect())

    def _color_at(self, pos):
        pt = self._to_img(pos)
        x, y = int(pt.x()), int(pt.y())
        if not (0 <= x < self.img.width() and 0 <= y < self.img.height()):
            return None
        acc, n = np.zeros(3), 0
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                xx, yy = x + dx, y + dy
                if 0 <= xx < self.img.width() and 0 <= yy < self.img.height():
                    c = self.img.pixelColor(xx, yy)
                    acc += (c.redF(), c.greenF(), c.blueF())
                    n += 1
        return tuple(float(v) for v in acc / n)

    def wheelEvent(self, e):
        if not self.img:
            return
        f = 1.15 ** ((e.angleDelta().y() or e.angleDelta().x()) / 120)
        z = min(40.0, max(0.02, self.zoom * f))
        pos = e.position()
        self.off = pos - (pos - self.off) * (z / self.zoom)
        self.zoom = z
        self.update()

    def mousePressEvent(self, e):
        if not self.img:
            return
        pos = e.position()
        if e.button() in (Qt.RightButton, Qt.MiddleButton):
            self._pan = (pos, QPointF(self.off))
            self.setCursor(Qt.ClosedHandCursor)
        elif e.button() == Qt.LeftButton and e.modifiers() & Qt.ShiftModifier:
            self._sel = [pos, pos]
        elif e.button() == Qt.LeftButton:
            self._picking = True
            self._before = None
            self._pick(pos, False)

    def mouseMoveEvent(self, e):
        pos = e.position()
        if self._pan:
            self.off = self._pan[1] + (pos - self._pan[0])
            self.update()
        elif self._sel:
            self._sel[1] = pos
            self.update()
        elif self._picking:
            self._pick(pos, False)

    def mouseReleaseEvent(self, e):
        pos = e.position()
        if self._pan:
            self._pan = None
            self.setCursor(Qt.CrossCursor)
        elif self._sel:
            a, b = self._to_img(self._sel[0]), self._to_img(self._sel[1])
            r = QRectF(a, b).normalized().toRect().intersected(self.img.rect())
            self.region = r if r.width() > 4 and r.height() > 4 else None
            self._sel = None
            self.update()
        elif self._picking:
            self._pick(pos, True)
            self._picking = False
            self.update()

    def _pick(self, pos, commit):
        c = self._color_at(pos)
        self._mpos = pos
        if c:
            if self._before is None:
                self._before = self.window().panel.state.color()
            self._cur = c
            self.picked.emit(c, commit)
        self.update()


class ThumbStrip(QWidget):
    selected = Signal(int)
    removed = Signal(int)
    T = 52

    def __init__(self):
        super().__init__()
        self.thumbs, self.cur = [], 0
        self.setFixedHeight(self.T + 8)

    def set_thumbs(self, thumbs, cur):
        self.thumbs, self.cur = thumbs, cur
        self.update()

    def _rects(self):
        return [QRectF(4 + i * (self.T + 6), 4, self.T, self.T) for i in range(len(self.thumbs))]

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        for i, (r, pm) in enumerate(zip(self._rects(), self.thumbs)):
            path = QPainterPath()
            path.addRoundedRect(r, 6, 6)
            p.save()
            p.setClipPath(path)
            p.fillRect(r, ui.CARD2)
            src = QRectF(pm.rect())
            s = min(src.width(), src.height())
            p.drawPixmap(r, pm, QRectF(src.center().x() - s / 2, src.center().y() - s / 2, s, s))
            p.restore()
            if i == self.cur:
                p.setPen(QPen(ui.ACCENT, 2))
                p.setBrush(Qt.NoBrush)
                p.drawRoundedRect(r.adjusted(-1, -1, 1, 1), 7, 7)

    def mousePressEvent(self, e):
        for i, r in enumerate(self._rects()):
            if r.contains(e.position()):
                if e.button() == Qt.RightButton:
                    m = QMenu(self)
                    m.addAction("Убрать с доски", lambda i=i: self.removed.emit(i))
                    m.exec(e.globalPosition().toPoint())
                else:
                    self.selected.emit(i)

    def wheelEvent(self, e):
        if self.thumbs:
            d = -1 if (e.angleDelta().y() or e.angleDelta().x()) > 0 else 1
            self.selected.emit((self.cur + d) % len(self.thumbs))


def tbtn(text, tip):
    b = QPushButton(text)
    b.setObjectName("tbtn")
    b.setToolTip(tip)
    b.setCursor(Qt.PointingHandCursor)
    b.setFixedSize(28, 26)
    return b


class RefBoard(QWidget):
    """Окно референсов поверх всех программ."""

    def __init__(self, panel):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAcceptDrops(True)
        self.setWindowTitle("Референсы — Dynamic Color Picker")
        self.panel = panel
        self.cfg = panel.cfg
        os.makedirs(REF_DIR, exist_ok=True)
        self.files = [f for f in self.cfg.get("refs", []) if os.path.exists(os.path.join(REF_DIR, f))]
        self.cur = min(self.cfg.get("ref_cur", 0), max(0, len(self.files) - 1))
        self._drag = None
        self.clickthrough = False

        lay = QVBoxLayout(self)
        m = ui.SHADOW + 10
        lay.setContentsMargins(m, m, m, m)
        lay.setSpacing(8)
        head = QHBoxLayout()
        head.setSpacing(2)
        t = QLabel("Референсы")
        t.setObjectName("title")
        head.addWidget(t)
        head.addSpacing(8)
        for text, tip, fn in (("＋", "Открыть картинки", self.open_files),
                              ("⧉", "Вставить из буфера (Ctrl+V)", self.paste),
                              ("⤢", "Вписать в окно", lambda: self.canvas.fit()),
                              ("⇋", "Отразить по горизонтали", self._flip),
                              ("◐", "Оттенки серого — проверка тона", self._gray),
                              ("▦", "Генератор палитры (из выделения — Shift+ЛКМ)", self.generator),
                              ("◌", "Сквозь клик — окно не мешает рисовать", self.toggle_clickthrough)):
            b = tbtn(text, tip)
            b.clicked.connect(fn)
            head.addWidget(b)
        head.addStretch()
        self.op = QSlider(Qt.Horizontal)
        self.op.setRange(25, 100)
        self.op.setValue(int(self.cfg.get("ref_opacity", 100)))
        self.op.setFixedWidth(70)
        self.op.setToolTip("Прозрачность окна")
        self.op.valueChanged.connect(self._opacity)
        head.addWidget(self.op)
        x = ui.IconButton("close", self, 24, "Закрыть")
        x.clicked.connect(self.hide)
        head.addWidget(x)
        lay.addLayout(head)
        self.canvas = RefCanvas()
        self.canvas.picked.connect(lambda c, commit: self.panel.state.set_color(c, None, commit))
        lay.addWidget(self.canvas, 1)
        bottom = QHBoxLayout()
        self.strip = ThumbStrip()
        self.strip.selected.connect(self.select)
        self.strip.removed.connect(self.remove)
        bottom.addWidget(self.strip, 1)
        grip = QSizeGrip(self)
        grip.setFixedSize(16, 16)
        bottom.addWidget(grip, 0, Qt.AlignBottom | Qt.AlignRight)
        lay.addLayout(bottom)
        hint = QLabel("ЛКМ — пипетка · Shift+ЛКМ — область · колёсико — масштаб · ПКМ — двигать")
        hint.setStyleSheet(f"color:{ui.DIM.name()}; font-size:8pt")
        lay.addWidget(hint)

        g = self.cfg.get("ref_geom")
        if g:
            self.setGeometry(*g)
        else:
            self.resize(520, 460)
            scr = QGuiApplication.primaryScreen().availableGeometry()
            self.move(scr.left() + 80, scr.top() + 120)
        self._opacity(self.op.value())
        self._thumbs = {}
        self._load_current()

    # ---- окно
    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        ui.paint_card(p, QRectF(self.rect()).adjusted(ui.SHADOW, ui.SHADOW, -ui.SHADOW, -ui.SHADOW))

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag = e.globalPosition().toPoint() - self.pos()

    def mouseMoveEvent(self, e):
        if self._drag is not None:
            self.move(e.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, e):
        self._drag = None

    def keyPressEvent(self, e):
        if e.matches(e.StandardKey.Paste) if hasattr(e, "StandardKey") else False:
            self.paste()
        elif e.key() == Qt.Key_V and e.modifiers() & Qt.ControlModifier:
            self.paste()
        elif e.key() == Qt.Key_Escape:
            self.canvas.region = None
            self.canvas.update()
        elif e.key() in (Qt.Key_Right, Qt.Key_PageDown) and self.files:
            self.select((self.cur + 1) % len(self.files))
        elif e.key() in (Qt.Key_Left, Qt.Key_PageUp) and self.files:
            self.select((self.cur - 1) % len(self.files))
        elif e.key() == Qt.Key_Delete and self.files:
            self.remove(self.cur)

    def save_state(self):
        self.cfg["refs"] = self.files
        self.cfg["ref_cur"] = self.cur
        self.cfg["ref_opacity"] = self.op.value()
        g = self.geometry()
        self.cfg["ref_geom"] = [g.x(), g.y(), g.width(), g.height()]
        self.cfg["ref_open"] = self.isVisible()

    def hideEvent(self, e):
        self.save_state()

    def _opacity(self, v):
        self.setWindowOpacity(v / 100)

    def _flip(self):
        self.canvas.flip = not self.canvas.flip
        self.canvas.update()

    def _gray(self):
        self.canvas.gray_on = not self.canvas.gray_on
        self.canvas.update()

    def toggle_clickthrough(self):
        self.clickthrough = not self.clickthrough
        geo = self.geometry()
        self.setWindowFlag(Qt.WindowTransparentForInput, self.clickthrough)
        self.setGeometry(geo)
        self.show()
        if self.clickthrough:
            if self.op.value() > 70:
                self.setWindowOpacity(0.6)
            self.panel.tray.showMessage("Референсы", "Режим «сквозь клик» включён. Выключить: меню панели → "
                                        "Референс-доска → «Сквозь клик» или горячая клавиша.",
                                        ui.QSystemTrayIcon.Information, 4000)
        else:
            self._opacity(self.op.value())

    # ---- картинки
    def _add_image(self, img=None, path=None):
        name = f"{int(time.time())}_{uuid.uuid4().hex[:6]}"
        if path:
            ext = os.path.splitext(path)[1].lower()
            if ext not in IMG_EXT:
                return False
            dst = name + ext
            shutil.copyfile(path, os.path.join(REF_DIR, dst))
        else:
            if img is None or img.isNull():
                return False
            dst = name + ".png"
            img.save(os.path.join(REF_DIR, dst))
        self.files.append(dst)
        self.cur = len(self.files) - 1
        return True

    def _after_add(self):
        self._load_current()
        self.save_state()

    def open_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Референсы", "", "Изображения (*.png *.jpg *.jpeg *.bmp *.webp *.tif *.tiff *.gif)")
        if any([self._add_image(path=p) for p in paths]):
            self._after_add()

    def paste(self):
        md = QGuiApplication.clipboard().mimeData()
        added = False
        if md.hasImage():
            added = self._add_image(img=QImage(md.imageData()))
        elif md.hasUrls():
            added = any([self._add_image(path=u.toLocalFile()) for u in md.urls() if u.isLocalFile()])
        elif md.hasText() and os.path.isfile(md.text().strip().strip('"')):
            added = self._add_image(path=md.text().strip().strip('"'))
        if added:
            self._after_add()
        else:
            self.panel.tray.showMessage("Референсы", "В буфере нет картинки.", ui.QSystemTrayIcon.Information, 2000)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls() or e.mimeData().hasImage():
            e.acceptProposedAction()

    def dropEvent(self, e):
        md = e.mimeData()
        added = False
        if md.hasUrls():
            added = any([self._add_image(path=u.toLocalFile()) for u in md.urls() if u.isLocalFile()])
        if not added and md.hasImage():
            added = self._add_image(img=QImage(md.imageData()))
        if added:
            self._after_add()

    def select(self, i):
        if 0 <= i < len(self.files):
            self.cur = i
            self._load_current()

    def remove(self, i):
        if not 0 <= i < len(self.files):
            return
        f = self.files.pop(i)
        self._thumbs.pop(f, None)
        try:
            os.remove(os.path.join(REF_DIR, f))
        except OSError:
            pass
        self.cur = min(self.cur, max(0, len(self.files) - 1))
        self._load_current()
        self.save_state()

    def _thumb(self, f):
        if f not in self._thumbs:
            img = QImage(os.path.join(REF_DIR, f))
            self._thumbs[f] = QPixmap.fromImage(img.scaled(120, 120, Qt.KeepAspectRatioByExpanding,
                                                           Qt.SmoothTransformation))
        return self._thumbs[f]

    def _load_current(self):
        img = QImage(os.path.join(REF_DIR, self.files[self.cur])) if self.files else None
        self.canvas.set_image(img if img is not None and not img.isNull() else None)
        self.strip.set_thumbs([self._thumb(f) for f in self.files], self.cur)

    def current_image(self):
        return self.canvas.img

    def generator(self):
        if not self.canvas.img:
            return
        PaletteGenerator(self.panel, self.canvas.img, "Палитра из референса", self.canvas.region).exec()
