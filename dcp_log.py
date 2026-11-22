"""
Журнал ошибок Dynamic Color Picker: ~/.dynamic_color_picker/log.txt (+ crash.txt для аварийных падений).

- все необработанные исключения (в т.ч. в отрисовке Qt и в фоновых потоках) пишутся с трассировкой;
- предупреждения Qt пишутся в журнал;
- в exe без консоли stdout/stderr перенаправляются в журнал (иначе print() роняет программу);
- faulthandler пишет трассировку при жёстком падении (segfault) в crash.txt.
"""
import faulthandler
import logging
import os
import platform
import sys
import threading
import traceback
from logging.handlers import RotatingFileHandler

from dcp_core import APP_DIR, APP_VERSION

LOG_PATH = os.path.join(APP_DIR, "log.txt")
CRASH_PATH = os.path.join(APP_DIR, "crash.txt")
log = logging.getLogger("dcp")
_shown = set()
_crash_file = None


class _StreamToLog:
    def __init__(self, level):
        self.level = level
        self._buf = ""

    def write(self, s):
        self._buf += s
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            if line.strip():
                log.log(self.level, line.rstrip())

    def flush(self):
        pass

    def isatty(self):
        return False


def system_info():
    try:
        from PySide6 import __version__ as pyside
    except Exception:
        pyside = "?"
    return (f"Dynamic Color Picker {APP_VERSION} | {platform.platform()} | Python {platform.python_version()} | "
            f"PySide6 {pyside} | {'exe' if getattr(sys, 'frozen', False) else 'исходники'} | {sys.executable}")


def _report(kind, exc_type, exc, tb):
    text = "".join(traceback.format_exception(exc_type, exc, tb))
    log.error("%s:\n%s", kind, text.rstrip())
    key = (exc_type.__name__, str(exc)[:200])
    if key in _shown:
        return
    _shown.add(key)
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox
        from PySide6.QtCore import QTimer
        app = QApplication.instance()
        if app is None or threading.current_thread() is not threading.main_thread():
            return

        def show():
            box = QMessageBox()
            box.setIcon(QMessageBox.Warning)
            box.setWindowTitle("Dynamic Color Picker — ошибка")
            box.setText(f"Произошла ошибка: {exc_type.__name__}: {exc}\n\n"
                        f"Программа продолжит работу. Подробности записаны в журнал:\n{LOG_PATH}")
            box.setDetailedText(text)
            box.exec()
        QTimer.singleShot(0, show)
    except Exception:
        pass


def setup():
    """Вызывать первым делом в main(), до создания окон."""
    global _crash_file
    os.makedirs(APP_DIR, exist_ok=True)
    h = RotatingFileHandler(LOG_PATH, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", "%Y-%m-%d %H:%M:%S"))
    log.addHandler(h)
    log.setLevel(logging.INFO)
    if sys.stdout is None or getattr(sys, "frozen", False):
        sys.stdout = _StreamToLog(logging.INFO)
    if sys.stderr is None or getattr(sys, "frozen", False):
        sys.stderr = _StreamToLog(logging.WARNING)
    try:
        _crash_file = open(CRASH_PATH, "a", encoding="utf-8")
        faulthandler.enable(_crash_file)
    except Exception:
        pass
    sys.excepthook = lambda t, e, tb: _report("Необработанная ошибка", t, e, tb)
    threading.excepthook = lambda a: _report(f"Ошибка в потоке {a.thread.name if a.thread else '?'}",
                                             a.exc_type, a.exc_value, a.exc_traceback)
    try:
        from PySide6.QtCore import qInstallMessageHandler, QtMsgType

        def qt_handler(mode, ctx, msg):
            if "propagateSizeHints" in msg:
                return
            lvl = {QtMsgType.QtDebugMsg: logging.DEBUG, QtMsgType.QtInfoMsg: logging.INFO,
                   QtMsgType.QtWarningMsg: logging.WARNING}.get(mode, logging.ERROR)
            log.log(lvl, "Qt: %s", msg)
        qInstallMessageHandler(qt_handler)
    except Exception:
        pass
    log.info("=" * 60)
    log.info("Запуск: %s", system_info())


def open_log():
    from PySide6.QtGui import QDesktopServices
    from PySide6.QtCore import QUrl
    if not os.path.exists(LOG_PATH):
        open(LOG_PATH, "a").close()
    QDesktopServices.openUrl(QUrl.fromLocalFile(LOG_PATH))


def report_text(lines=200):
    """Сведения о системе + хвост журнала — для отправки при ошибке."""
    tail = ""
    try:
        with open(LOG_PATH, encoding="utf-8", errors="replace") as f:
            tail = "".join(f.readlines()[-lines:])
    except OSError:
        pass
    crash = ""
    try:
        if os.path.getsize(CRASH_PATH) > 0:
            with open(CRASH_PATH, encoding="utf-8", errors="replace") as f:
                crash = "\n--- crash.txt ---\n" + "".join(f.readlines()[-60:])
    except OSError:
        pass
    return f"{system_info()}\n\n--- log.txt (последние {lines} строк) ---\n{tail}{crash}"
