"""
Клиент Clip Studio Paint Companion Mode: Dynamic Color Picker подключается к CSP вместо смартфона.

Протокол неофициальный. Реализация написана по заметкам о реверс-инжиниринге:
  https://github.com/andyubird/LumaPaletteCSP/blob/main/PROTOCOL.md
  https://github.com/chocolatkey/clipremote
Celsys может изменить протокол в любом обновлении CSP.

Поток:
  1. CSP: File -> Connect to smartphone  -> QR c URL https://companion.clip-studio.com/rc/..?s=<hex>
  2. QR считывается с экрана (OpenCV) или URL вставляется вручную
  3. s = hex(XOR(plain, REMOTE_KEY)), plain = "ips\tport\tpassword\tgeneration"
  4. TCP -> Authenticate [generation, hex(XOR(pw, AUTH_KEY)), hex(XOR(new_pw, AUTH_KEY))]
  5. TellHeartbeat {"IdleTimerResetRequested":true}, опрос SyncColorCircleUIState, запись SetCurrentColor
"""
import base64
import colorsys
import json
import os
import secrets
import socket
import threading
import time
from urllib.parse import urlparse, parse_qs

from PySide6.QtCore import QThread, Signal

REMOTE_KEY = bytes([0x74, 0xB2, 0x92, 0x5B, 0x4A, 0x21, 0xDA])
AUTH_KEY = bytes([0xB6, 0xD5, 0x92, 0xC4, 0xA7, 0x83, 0xE1])
RECONNECT_MARKER = "{{(([[reconnection request marker]]))}}\r\n"
QR_PREFIX = "https://companion.clip-studio.com/"
MAX_U32 = 4294967295
T_CMD, T_OK, T_ERR, RS, TERM = 0x01, 0x06, 0x15, 0x1E, 0x00
HB_ACTIVE = '{"IdleTimerResetRequested":true}'
STALE_SYNC = ('{"IsManipulating":false,"HSVColorMainH":0,"HSVColorMainS":0,"HSVColorMainV":0,'
              '"CurrentColorIndex":0,"ColorSelectionModel":"HSV"}')


# ------------------------------------------------------------------ crypto / qr
def xor_cycle(data: bytes, key: bytes) -> bytes:
    return bytes(b ^ key[i % len(key)] for i, b in enumerate(data))


def decode_qr_url(url: str) -> dict:
    s = parse_qs(urlparse(url.strip()).query).get("s", [None])[0]
    if not s:
        raise ValueError("в URL нет параметра s")
    parts = xor_cycle(bytes.fromhex(s), REMOTE_KEY).decode("utf-8").split("\t")
    if len(parts) < 4:
        raise ValueError("неожиданный формат QR")
    return {"ips": [ip for ip in parts[0].split(",") if ip], "port": int(parts[1]),
            "password": parts[2], "generation": parts[3]}


def obfuscate(pw: str) -> str:
    return xor_cycle(pw.encode("utf-8"), AUTH_KEY).hex()


def new_password() -> str:
    return base64.b64encode(secrets.token_bytes(6)).decode().rstrip("=")


# ------------------------------------------------------------------ framing
def build_message(cmd: str, serial: int, detail: str = "") -> bytes:
    body = (f"$tcp_remote_command_protocol_version=1.0\x1e$command={cmd}\x1e"
            f"$serial={serial}\x1e$detail={detail}\x1e")
    return bytes([T_CMD]) + body.encode("utf-8") + bytes([TERM])


def drain_messages(buf: bytearray) -> list:
    """Извлекает все полные записи из buf (записи могут слипаться в одном recv)."""
    out = []
    while True:
        idx = buf.find(bytes([TERM]))
        if idx < 0:
            return out
        start = 0
        for j in range(idx - 1, -1, -1):
            if buf[j] in (T_CMD, T_OK, T_ERR):
                start = j
                break
        raw = bytes(buf[start:idx + 1])
        del buf[:idx + 1]
        if len(raw) < 10:
            continue
        msg = {"type": raw[0], "command": "", "serial": -1, "detail": {}}
        for part in raw[1:-1].split(bytes([RS])):
            k, _, v = part.decode("utf-8", "replace").lstrip("$").partition("=")
            if k == "command":
                msg["command"] = v
            elif k == "serial":
                msg["serial"] = int(v) if v.lstrip("-").isdigit() else -1
            elif k == "detail":
                v = v.rstrip("\x1e\x00")
                try:
                    msg["detail"] = json.loads(v) if v else {}
                except json.JSONDecodeError:
                    msg["detail"] = {}
        out.append(msg)


# ------------------------------------------------------------------ session file
def session_path(app_dir):
    return os.path.join(app_dir, "csp_session.json")


def load_session(app_dir):
    try:
        return json.load(open(session_path(app_dir), encoding="utf-8"))
    except Exception:
        return None


def save_session(app_dir, data):
    os.makedirs(app_dir, exist_ok=True)
    json.dump(data, open(session_path(app_dir), "w", encoding="utf-8"))


# ------------------------------------------------------------------ worker
class CompanionWorker(QThread):
    """Владеет сокетом. Читает цвет CSP и отправляет последний запрошенный цвет."""
    status = Signal(str, bool)          # текст, подключено
    colorReceived = Signal(dict)        # {"main":(h,s,v), "sub":(h,s,v), "index":0|1, "transparent":bool}
    toolReceived = Signal(dict)         # {"size": px, "alpha": %, "size_ok": bool, "alpha_ok": bool, "unit": str}
    authenticated = Signal(dict)        # данные сессии для сохранения

    POLL = 0.2
    HEARTBEAT = 1.5

    def __init__(self, ips, port, password, generation, reconnect=False):
        super().__init__()
        self.ips, self.port = list(ips), int(port)
        self.password, self.generation, self.reconnect = password, generation, reconnect
        self._sock = None
        self._serial = 0
        self._buf = bytearray()
        self._pending = None
        self._pending_size = None
        self._pending_alpha = None
        self._tool_quiet = 0.0
        self._tool = {"size": None, "alpha": None, "size_ok": False, "alpha_ok": False, "unit": "px"}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._quiet_until = 0.0

    # --- API из GUI-потока
    def set_brush_size(self, px):
        with self._lock:
            self._pending_size = float(px)

    def set_alpha(self, pct):
        with self._lock:
            self._pending_alpha = int(round(pct))

    def set_color(self, rgb, index, transparent=False):
        h, s, v = colorsys.rgb_to_hsv(*rgb)
        with self._lock:
            self._pending = {"ColorSpaceKind": "HSV", "IsColorTransparent": bool(transparent),
                             "HSVColorH": int(round(h * MAX_U32)), "HSVColorS": int(round(s * MAX_U32)),
                             "HSVColorV": int(round(v * MAX_U32)), "ColorIndex": int(index)}

    def stop(self):
        self._stop.set()

    # --- сеть
    def _send(self, cmd, detail="", timeout=3.0):
        serial = self._serial
        self._serial += 1
        self._sock.sendall(build_message(cmd, serial, detail))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for m in drain_messages(self._buf):
                self._absorb(m)
                if m["serial"] == serial:
                    return m
            self._sock.settimeout(max(0.05, deadline - time.monotonic()))
            try:
                chunk = self._sock.recv(65536)
            except socket.timeout:
                continue
            if not chunk:
                raise ConnectionError("CSP закрыл соединение")
            self._buf += chunk
        raise TimeoutError(f"нет ответа на {cmd}")

    def _absorb(self, m):
        d = m.get("detail")
        if isinstance(d, dict) and time.monotonic() >= self._tool_quiet and \
                ("CurrentToolBrushSize" in d or "CurrentToolAlphaPercent" in d or "IsToolBrushSizeAvailable" in d):
            t = dict(self._tool)
            if "CurrentToolBrushSize" in d:
                t["size"] = float(d["CurrentToolBrushSize"])
            if "CurrentToolAlphaPercent" in d:
                t["alpha"] = int(d["CurrentToolAlphaPercent"])
            t["size_ok"] = bool(d.get("IsToolBrushSizeAvailable", t["size"] is not None))
            t["alpha_ok"] = bool(d.get("IsToolAlphaAvailable", t["alpha"] is not None))
            t["unit"] = d.get("LengthUnitKind", t["unit"])
            if t != self._tool:
                self._tool = t
                self.toolReceived.emit(dict(t))
        if not isinstance(d, dict) or "HSVColorMainH" not in d or time.monotonic() < self._quiet_until:
            return
        f = lambda k: d.get(k, 0) / MAX_U32
        self.colorReceived.emit({
            "main": (f("HSVColorMainH"), f("HSVColorMainS"), f("HSVColorMainV")),
            "sub": (f("HSVColorSubH"), f("HSVColorSubS"), f("HSVColorSubV")),
            "index": min(1, int(d.get("CurrentColorIndex", 0))),
            "transparent": bool(d.get("IsCurrentColorTransparent", False)),
        })

    def _connect(self):
        err = None
        for ip in self.ips:
            try:
                self._sock = socket.create_connection((ip, self.port), timeout=4)
                self._sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                return ip
            except OSError as e:
                err = e
        raise ConnectionError(f"нет доступа к {self.ips}:{self.port} ({err})")

    def _authenticate(self, ip):
        if self.reconnect:
            curr, new = obfuscate(RECONNECT_MARKER), self.password
        else:
            curr, new_pw = obfuscate(self.password), new_password()
            new = new_pw
        detail = json.dumps([self.generation, curr, obfuscate(new)])
        r = self._send("Authenticate", detail)
        if r["type"] != T_OK:
            raise PermissionError(f"CSP отклонил авторизацию: {r['detail']}")
        self.password = new
        self.authenticated.emit({"ips": [ip], "port": self.port, "password": new, "generation": self.generation})
        for cmd, det in (("TellHeartbeat", HB_ACTIVE),
                         ("GetModifyKeyString", '{"CtrlPushed":false,"AltPushed":false,"ShiftPushed":false}'),
                         ("GetServerSelectedTabKind", ""), ("SetServerSelectedTabKind", ""),
                         ("TellHeartbeat", HB_ACTIVE)):
            self._send(cmd, det)

    def run(self):
        try:
            self.status.emit("Подключение…", False)
            ip = self._connect()
            self._authenticate(ip)
            self.status.emit(f"Подключено к CSP ({ip}:{self.port})", True)
            last_hb = last_poll = 0.0
            while not self._stop.is_set():
                now = time.monotonic()
                with self._lock:
                    pending, self._pending = self._pending, None
                    size, self._pending_size = self._pending_size, None
                    alpha, self._pending_alpha = self._pending_alpha, None
                if pending:
                    self._quiet_until = now + 0.35     # не принимать «эхо» старого цвета
                    self._send("SetCurrentColor", json.dumps(pending))
                if size is not None:                   # SetBrushSize / SetAlpha — «голое» число в detail
                    self._tool_quiet = now + 0.35
                    self._send("SetBrushSize", json.dumps(round(size, 2)))
                if alpha is not None:
                    self._tool_quiet = now + 0.35
                    self._send("SetAlpha", json.dumps(max(0, min(100, alpha))))
                if now - last_hb >= self.HEARTBEAT:
                    self._send("TellHeartbeat", HB_ACTIVE)
                    last_hb = now
                if now - last_poll >= self.POLL:
                    self._send("SyncColorCircleUIState", STALE_SYNC)
                    last_poll = now
                self._stop.wait(0.03)
        except Exception as e:
            self.status.emit(f"Отключено: {e}", False)
        else:
            self.status.emit("Отключено", False)
        finally:
            if self._sock:
                try:
                    self._sock.close()
                except OSError:
                    pass


# ------------------------------------------------------------------ QR на экране
def scan_screens_for_qr():
    """Снимок всех экранов -> поиск QR CSP. Возвращает URL или None. Нужен opencv-python."""
    import numpy as np
    from PySide6.QtGui import QGuiApplication, QImage
    try:
        import cv2
    except ImportError:
        raise RuntimeError("нужен пакет opencv-python (pip install opencv-python)")
    det = cv2.QRCodeDetector()
    for scr in QGuiApplication.screens():
        img = scr.grabWindow(0).toImage().convertToFormat(QImage.Format_Grayscale8)
        w, h, bpl = img.width(), img.height(), img.bytesPerLine()
        if w == 0 or h == 0:
            continue
        gray = np.frombuffer(img.constBits(), np.uint8, count=h * bpl).reshape(h, bpl)[:, :w].copy()
        for g in (gray, cv2.resize(gray, None, fx=0.5, fy=0.5)):
            try:
                ok, texts, _, _ = det.detectAndDecodeMulti(g)
            except cv2.error:
                ok, texts = False, []
            for t in (texts if ok else []):
                if t and t.startswith(QR_PREFIX):
                    return t
            t, _, _ = det.detectAndDecode(g)
            if t and t.startswith(QR_PREFIX):
                return t
    return None
