"""
Глобальные горячие клавиши (работают, когда активен CSP / Photoshop).
Отдельная клавиатура / макропад: назначьте её клавиши действиям в «Настройки → Горячие клавиши».

Клавиши хранятся как виртуальные коды Windows: "vk17+vk18+vk67" = Ctrl+Alt+C.
Поддерживаются нажатие и отпускание (для Follow Mode: держите — панель видна, отпустили — скрылась).
На Windows назначенные клавиши можно не передавать в другие программы (suppress).
"""
import sys
import threading

from PySide6.QtCore import QObject, Signal

ACTIONS = [
    ("call", "Вызов панели (у пера; удержание — Follow)"),
    ("toggle", "Показать / скрыть панель"),
    ("next_panel", "Следующая панель"),
    ("prev_panel", "Предыдущая панель"),
    ("panel_1", "Панель 1"), ("panel_2", "Панель 2"), ("panel_3", "Панель 3"), ("panel_4", "Панель 4"),
    ("adjust_up", "HoverAdjust + (элемент под курсором)"),
    ("adjust_down", "HoverAdjust − (элемент под курсором)"),
    ("hue_up", "Оттенок +"), ("hue_down", "Оттенок −"),
    ("luma_up", "Яркость +"), ("luma_down", "Яркость −"),
    ("sat_up", "Насыщенность +"), ("sat_down", "Насыщенность −"),
    ("swap", "Поменять основной / фоновый"),
    ("select_fg", "Выбрать основной цвет"), ("select_bg", "Выбрать фоновый цвет"),
    ("transparent", "Прозрачный цвет"),
    ("cycle_model", "Сменить модель круга (HSV/HSL/V-HSV)"),
    ("add_swatch", "Добавить цвет в набор"),
    ("pin", "Временное закрепление (булавка)"),
    ("eyedropper", "Пипетка с экрана (с лупой)"),
    ("pick_under_cursor", "Взять цвет под курсором (мгновенно)"),
    ("scan_canvas", "Обновить палитру холста"),
]
DEFAULT_BINDINGS = {"call": "vk17+vk18+vk67"}   # Ctrl+Alt+C

MOD_VK = {160: 16, 161: 16, 162: 17, 163: 17, 164: 18, 165: 18, 91: 91, 92: 91}
MODIFIERS = {16, 17, 18, 91}
VK_NAMES = {8: "Backspace", 9: "Tab", 13: "Enter", 16: "Shift", 17: "Ctrl", 18: "Alt", 19: "Pause", 20: "CapsLock",
            27: "Esc", 32: "Space", 33: "PgUp", 34: "PgDn", 35: "End", 36: "Home", 37: "←", 38: "↑", 39: "→",
            40: "↓", 45: "Ins", 46: "Del", 91: "Win", 93: "Menu", 106: "Num*", 107: "Num+", 109: "Num−",
            110: "Num.", 111: "Num/", 144: "NumLock", 145: "ScrollLock", 186: ";", 187: "=", 188: ",", 189: "-",
            190: ".", 191: "/", 192: "`", 219: "[", 220: "\\", 221: "]", 222: "'", 173: "Mute", 174: "Vol−",
            175: "Vol+", 176: "Next", 177: "Prev", 179: "Play"}

_X_NAMES = {"ctrl": 17, "ctrl_l": 17, "ctrl_r": 17, "alt": 18, "alt_l": 18, "alt_r": 18, "alt_gr": 18,
            "shift": 16, "shift_l": 16, "shift_r": 16, "cmd": 91, "cmd_l": 91, "cmd_r": 91}


def vk_name(t):
    if t.startswith("vk"):
        v = int(t[2:])
        if 65 <= v <= 90 or 48 <= v <= 57:
            return chr(v)
        if 96 <= v <= 105:
            return f"Num{v - 96}"
        if 112 <= v <= 135:
            return f"F{v - 111}"
        return VK_NAMES.get(v, f"VK{v}")
    return t.capitalize()


def combo_tokens(s):
    return [t for t in (s or "").split("+") if t]


def combo_name(s):
    toks = combo_tokens(s)
    if not toks:
        return "—"
    order = {"vk17": 0, "vk18": 1, "vk16": 2, "vk91": 3}
    toks.sort(key=lambda t: order.get(t, 10))
    return "+".join(vk_name(t) for t in toks)


def _is_mod(t):
    return t in ("vk16", "vk17", "vk18", "vk91")


class HotkeyManager(QObject):
    pressed = Signal(str)
    released = Signal(str)
    recorded = Signal(str)

    def __init__(self):
        super().__init__()
        self.bindings = {}
        self.suppress = True
        self.middle_click = False
        self._down = set()
        self._active = set()
        self._suppressed = set()
        self._rec = None
        self._lock = threading.Lock()
        self._kb = self._ms = None
        self.available = True

    # ---------------- config
    def configure(self, bindings, suppress=True, middle_click=False):
        self.bindings = {a: s for a, s in (bindings or {}).items() if s}
        self.suppress = suppress
        self.middle_click = middle_click
        self.start()

    def start(self):
        self.stop()
        try:
            from pynput import keyboard, mouse
        except ImportError:
            self.available = False
            return False
        if sys.platform == "win32":
            self._kb = keyboard.Listener(win32_event_filter=self._win_filter)
        else:
            self._kb = keyboard.Listener(on_press=lambda k: self._press(self._token(k)),
                                         on_release=lambda k: self._release(self._token(k)))
        self._kb.daemon = True
        self._kb.start()
        if self.middle_click:
            def on_click(x, y, btn, pressed):
                if btn == mouse.Button.middle:
                    (self.pressed if pressed else self.released).emit("call")
            self._ms = mouse.Listener(on_click=on_click)
            self._ms.daemon = True
            self._ms.start()
        return True

    def stop(self):
        for l in (self._kb, self._ms):
            if l:
                try:
                    l.stop()
                except Exception:
                    pass
        self._kb = self._ms = None
        self._down.clear()
        self._active.clear()

    def record(self):
        """Следующая нажатая комбинация придёт сигналом recorded (Esc — отмена)."""
        with self._lock:
            self._rec = set()

    def cancel_record(self):
        with self._lock:
            self._rec = None

    # ---------------- key handling
    def _token(self, key):
        try:
            from pynput.keyboard import Key
        except ImportError:
            return None
        if isinstance(key, Key):
            if key.name in _X_NAMES:
                return f"vk{_X_NAMES[key.name]}"
            vk = getattr(key.value, "vk", None)
            return f"vk{vk}" if vk is not None else key.name
        vk = getattr(key, "vk", None)
        ch = getattr(key, "char", None)
        if ch and ch.isalnum() and len(ch) == 1:
            return f"vk{ord(ch.upper())}"
        return f"vk{vk}" if vk is not None else (ch or None)

    def _win_filter(self, msg, data):
        vk = MOD_VK.get(data.vkCode, data.vkCode)
        t = f"vk{vk}"
        if msg in (0x100, 0x104):
            sup = self._press(t)
        elif msg in (0x101, 0x105):
            sup = self._release(t)
        else:
            return True
        if sup and self._kb:
            self._kb.suppress_event()
        return True

    def _press(self, t):
        """Возвращает True, если событие нужно подавить."""
        if not t:
            return False
        with self._lock:
            repeat = t in self._down
            self._down.add(t)
            if self._rec is not None:
                if t != "vk27":
                    self._rec.add(t)
                return True
            if repeat:
                return t in self._suppressed
            hit = False
            for act, s in self.bindings.items():
                toks = set(combo_tokens(s))
                if t in toks and toks <= self._down and act not in self._active:
                    # точное совпадение модификаторов: лишние Ctrl/Alt/Shift не допускаются
                    extra_mods = {x for x in self._down if _is_mod(x)} - toks
                    if extra_mods:
                        continue
                    self._active.add(act)
                    self.pressed.emit(act)
                    hit = True
            if hit and self.suppress and not _is_mod(t):
                self._suppressed.add(t)
                return True
            return False

    def _release(self, t):
        if not t:
            return False
        with self._lock:
            self._down.discard(t)
            if self._rec is not None:
                if t == "vk27" and not self._rec:
                    self._rec = None
                    self.recorded.emit("")
                    return True
                if not self._down:
                    combo = "+".join(sorted(self._rec, key=lambda x: (not _is_mod(x), x)))
                    self._rec = None
                    if combo:
                        self.recorded.emit(combo)
                return True
            for act in list(self._active):
                if t in combo_tokens(self.bindings.get(act, "")):
                    self._active.discard(act)
                    self.released.emit(act)
            if t in self._suppressed:
                self._suppressed.discard(t)
                return True
            return False
