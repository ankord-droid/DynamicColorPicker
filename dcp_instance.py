"""
Один экземпляр программы и обновление «скачал новый exe — запустил».

handoff(version):
  - работающей копии нет           -> запускаемся;
  - работает более старая версия   -> она сохраняет настройки и закрывается, запускаемся мы;
  - работает та же или новее        -> она показывает панель, мы выходим.

check_replace(panel): если новая версия запущена не из того места, где жила прежняя, — предложить
записать себя на место старого exe (ярлыки и автозапуск продолжат работать).
"""
import os
import shutil
import sys
import time

from PySide6.QtCore import QObject, Qt
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QMessageBox, QLabel, QScrollArea

from dcp_core import APP_VERSION

SERVER = "DynamicColorPicker-ankord-droid"


def _ver(s):
    out = []
    for part in (s or "0").lstrip("vV").split("."):
        num = "".join(ch for ch in part if ch.isdigit())
        out.append(int(num) if num else 0)
    return tuple(out + [0] * (3 - len(out)))


def handoff(version=APP_VERSION):
    """True — продолжать запуск; False — уже работает та же/новее версия (она показана)."""
    sock = QLocalSocket()
    sock.connectToServer(SERVER)
    if not sock.waitForConnected(400):
        return True
    sock.write(f"HELLO {version}\n".encode())
    sock.flush()
    reply = ""
    if sock.waitForReadyRead(4000):
        reply = bytes(sock.readAll()).decode(errors="ignore").strip()
    sock.disconnectFromServer()
    if reply.startswith("BYE"):
        for _ in range(80):                    # ждём, пока старая копия закроется (до 8 с)
            time.sleep(0.1)
            t = QLocalSocket()
            t.connectToServer(SERVER)
            if not t.waitForConnected(100):
                break
            t.disconnectFromServer()
        time.sleep(0.4)
        return True
    return False


class InstanceServer(QObject):
    def __init__(self, panel):
        super().__init__(panel)
        self.panel = panel
        QLocalServer.removeServer(SERVER)
        self.srv = QLocalServer(self)
        self.srv.listen(SERVER)
        self.srv.newConnection.connect(self._conn)

    def _conn(self):
        c = self.srv.nextPendingConnection()
        if c is None:
            return
        c.readyRead.connect(lambda c=c: self._read(c))

    def _read(self, c):
        msg = bytes(c.readAll()).decode(errors="ignore").strip()
        other = msg.split(" ", 1)[1] if msg.startswith("HELLO ") else "0"
        import logging
        if _ver(other) > _ver(APP_VERSION):
            logging.getLogger("dcp").info("Запущена новая версия %s — закрываюсь для обновления", other)
            c.write(b"BYE\n")
            c.flush()
            c.waitForBytesWritten(1000)
            self.srv.close()
            self.panel.quit()
        else:
            c.write(b"SHOWN\n")
            c.flush()
            self.panel._show_home()


def _notes_text():
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    try:
        return open(os.path.join(base, "RELEASE_NOTES.md"), encoding="utf-8").read()
    except OSError:
        return f"Dynamic Color Picker {APP_VERSION}"


def whats_new(panel):
    import dcp_app as ui
    d = ui.DarkDialog(panel, f"Что нового в {APP_VERSION}")
    d.setFixedWidth(560)
    lab = QLabel()
    lab.setTextFormat(Qt.MarkdownText)
    lab.setWordWrap(True)
    lab.setText(_notes_text())
    lab.setTextInteractionFlags(Qt.TextBrowserInteraction)
    lab.setOpenExternalLinks(True)
    sa = QScrollArea()
    sa.setWidgetResizable(True)
    sa.setWidget(lab)
    sa.setFixedHeight(420)
    d.outer.addWidget(sa)
    ok = ui.pill("Понятно", "primary")
    ok.clicked.connect(d.accept)
    d.outer.addWidget(ok)
    d.center_on(panel)
    d.exec()


def check_replace(panel):
    """Вызывается после старта. Заменяет старую копию exe и показывает «Что нового»."""
    cfg = panel.cfg
    last = cfg.get("last_version")
    if last is None and cfg.get("layouts"):
        last = "2.2.0"                         # настройки от версии без учёта версий
    prev = cfg.get("exe_path")
    newer = last is not None and _ver(APP_VERSION) > _ver(last)
    frozen = getattr(sys, "frozen", False)
    cur = sys.executable if frozen else None
    if frozen:
        cfg["exe_path"] = cur
    if frozen and newer and prev and os.path.exists(prev) and os.path.normcase(prev) != os.path.normcase(cur):
        _offer_replace(panel, prev, cur, last)
    cfg["last_version"] = APP_VERSION
    if newer:
        whats_new(panel)


def _offer_replace(panel, prev, cur, last):
    box = QMessageBox(panel)
    box.setWindowTitle("Обновление Dynamic Color Picker")
    box.setText(f"Найдена прежняя версия {last}:\n{prev}\n\n"
                f"Заменить её этой версией ({APP_VERSION})? Ярлыки и автозапуск продолжат работать, "
                f"а скачанный файл потом можно удалить.")
    yes = box.addButton("Заменить", QMessageBox.AcceptRole)
    box.addButton("Не сейчас", QMessageBox.RejectRole)
    box.exec()
    if box.clickedButton() is not yes:
        return
    import logging
    lg = logging.getLogger("dcp")
    while True:
        err = None
        for _ in range(10):
            try:
                tmp = prev + ".new"
                shutil.copy2(cur, tmp)
                os.replace(tmp, prev)
                err = None
                break
            except OSError as e:
                err = e
                time.sleep(0.3)
        if err is None:
            lg.info("Старая копия заменена: %s", prev)
            panel.cfg["exe_path"] = prev
            panel.tray.showMessage("Dynamic Color Picker", f"Обновлено до {APP_VERSION}. "
                                   "Скачанный файл можно удалить.", panel.tray.MessageIcon.Information, 5000)
            return
        lg.warning("Не удалось заменить %s: %s", prev, err)
        r = QMessageBox.warning(panel, "Обновление", f"Не удалось заменить файл:\n{prev}\n\n{err}\n\n"
                                "Если старая версия ещё открыта — закройте её (значок в трее → Выход).",
                                QMessageBox.Retry | QMessageBox.Cancel)
        if r != QMessageBox.Retry:
            return
