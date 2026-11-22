"""Ядро Dynamic Color Picker: цветовая математика, общее состояние, палитры, связь с CSP/Photoshop."""
import sys, os, json, math, colorsys
import numpy as np
from PySide6.QtCore import Qt, Signal, QObject, QTimer
from PySide6.QtGui import QColor, QImage, QGuiApplication
import csp_companion as cspc

APP_VERSION = "2.1.1"
GITHUB_REPO = "ankord-droid/DynamicColorPicker"

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


# ----- OKLab / OKLCH (перцептивно ровное смешивание и сдвиги тона)
_OK_M1 = np.array([[0.4122214708, 0.5363325363, 0.0514459929],
                   [0.2119034982, 0.6806995451, 0.1073969566],
                   [0.0883024619, 0.2817188376, 0.6299787005]])
_OK_M2 = np.array([[0.2104542553, 0.7936177850, -0.0040720468],
                   [1.9779984951, -2.4285922050, 0.4505937099],
                   [0.0259040371, 0.7827717662, -0.8086757660]])
_OK_M2I = np.linalg.inv(_OK_M2)
_OK_M1I = np.linalg.inv(_OK_M1)


def rgb2oklab(rgb):
    return np.cbrt(_lin(rgb) @ _OK_M1.T) @ _OK_M2.T


def oklab2rgb(lab):
    return _gam((np.asarray(lab, float) @ _OK_M2I.T) ** 3 @ _OK_M1I.T)


def oklch_in_gamut(L, C, H):
    """OKLCH (L 0..1, C, H°) -> sRGB, хрома уменьшается до попадания в гамму."""
    hr = math.radians(H)
    lo, hi = 0.0, max(0.0, C)
    f = lambda c: oklab2rgb(np.array([L, c * math.cos(hr), c * math.sin(hr)]))
    if in_gamut(f(hi)):
        return clip3(f(hi))
    for _ in range(16):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if in_gamut(f(mid)) else (lo, mid)
    return clip3(f(lo))


def rgb2oklch(rgb):
    L, a, b = rgb2oklab(np.array(rgb, float))
    return float(L), float(math.hypot(a, b)), float(math.degrees(math.atan2(b, a)) % 360)


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
        self.pinned = []              # закреплённые цвета истории
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
        if hx in self.pinned:
            return
        if hx in self.history:
            self.history.remove(hx)
        self.history.insert(0, hx)
        del self.history[40:]
        self.historyChanged.emit()

    def history_view(self):
        """Закреплённые цвета первыми, затем недавние."""
        return [(h, True) for h in self.pinned] + [(h, False) for h in self.history if h not in self.pinned]

    def toggle_pin(self, hx):
        if hx in self.pinned:
            self.pinned.remove(hx)
            if hx not in self.history:
                self.history.insert(0, hx)
        else:
            self.pinned.append(hx)
        self.historyChanged.emit()

    def remove_history(self, hx):
        if hx in self.pinned:
            self.pinned.remove(hx)
        if hx in self.history:
            self.history.remove(hx)
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


def qimage_rgb(img, side=None):
    """QImage -> массив (H, W, 3) float 0..1, по желанию уменьшенный до side."""
    if side:
        img = img.scaled(side, side, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    img = img.convertToFormat(QImage.Format_RGB888)
    w, h, bpl = img.width(), img.height(), img.bytesPerLine()
    return np.frombuffer(img.constBits(), np.uint8, count=h * bpl).reshape(h, bpl)[:, :w * 3].reshape(h, w, 3) / 255.0


def extract_colors(src, k, accuracy, mask=None):
    """k-means в пространстве LAB. src — путь или QImage. accuracy 1..100 → размер выборки и число итераций."""
    img = QImage(src) if isinstance(src, str) else src
    if img.isNull():
        return []
    side = int(32 + accuracy / 100 * 352)
    arr = qimage_rgb(img, side)
    if mask is not None:
        arr = arr[mask(arr.shape)]
    arr = arr.reshape(-1, 3)
    if len(arr) < k:
        return []
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


