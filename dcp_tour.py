"""
Обучение: пошаговый тур с подсветкой.

Тур затемняет экран вокруг панели, подсвечивает нужную часть и на время показывает в панели
тот компонент, о котором рассказывает (с ним можно играть прямо во время шага).
После завершения или пропуска панели возвращаются как были. Запуск: первый старт или ☰ → Обучение.
"""
import copy

from PySide6.QtCore import Qt, QObject, QTimer, QRect, QRectF, QPoint
from PySide6.QtGui import QPainter, QColor, QPen, QPainterPath, QGuiApplication
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel

import dcp_app as ui

B = "<b>%s</b>"

STEPS = [
    dict(title="Добро пожаловать в Dynamic Color Picker", target="panel", items=None, text=
         "Это плавающая панель цвета для <b>Clip Studio Paint</b> и <b>Photoshop</b>. Она собирается из "
         "<b>компонентов</b>: круга, палитр, слайдеров, инструментов для живописи.<br><br>"
         "Сейчас по очереди покажу каждый. Подсвеченную часть можно трогать прямо во время обучения. "
         "Ваши панели после тура вернутся как были.<br><br>"
         "<span style='color:gray'>← → — листать, Esc — выйти.</span>"),
    dict(title="Панели", target="tabs", items=None, text=
         "Слева — вкладки панелей. Можно держать <b>до 4 панелей</b> с разными наборами компонентов: например, "
         "одну для подбора цвета, другую для живописи.<br><br>"
         "• клик — переключить, <b>+</b> — новая панель<br>"
         "• ПКМ — переименовать, дублировать, удалить<br>"
         "• колёсико над вкладками — листать<br><br>"
         "Панель может переключаться сама по активной программе: Настройки → Система → Профили."),
    dict(title="Пипетка, меню и закрепление", target="header", items=None, text=
         "<b>Пипетка</b> — берёт цвет с любого места экрана: появится лупа, клик — взять, Esc — отмена.<br><br>"
         "<b>☰ Меню</b> — редактор панели, референс-доска, генератор палитры, подключение к CSP, настройки, "
         "горячие клавиши, резервная копия.<br><br>"
         "<b>📌 Булавка</b> — режим отображения:<br>"
         "• <b>Follow</b> — панель появляется у пера по кнопке вызова и исчезает, когда кнопку отпустили<br>"
         "• <b>булавка вкл.</b> — панель стоит на месте, кнопка вызова временно приносит её к перу<br>"
         "• <b>Pinned</b> (в настройках) — панель всегда на экране, кнопка показывает и скрывает её"),
    dict(title="Связь с Clip Studio Paint", target="dot", items=None, text=
         "Точка рядом с логотипом показывает связь с CSP: <span style='color:#2ECC71'>зелёная</span> — подключено.<br><br>"
         "Как подключить: ☰ → Подключение к CSP → «Подключить по QR», затем в CSP: "
         "<b>File → Connect to smartphone</b>. QR-код считается с экрана сам.<br><br>"
         "После этого любой цвет, выбранный в панели, сразу становится цветом кисти в CSP, "
         "а смена цвета в CSP видна в панели."),
    dict(title="Цветовой круг", target="comps", items=["wheel"], text=
         "<b>Кольцо</b> — оттенок (hue): жёлтый сверху, оттенки идут по часовой стрелке.<br>"
         "<b>Квадрат</b> — насыщенность (вправо) × яркость (вверх).<br><br>"
         "Пока тянете, рядом с пером виден кружок <b>«было / стало»</b>: верхняя половина — новый цвет, нижняя — прежний.<br><br>"
         "Кнопка в правом нижнем углу — модель (HSV / HSL / V-HSV) и вид: <b>круг</b> или <b>куб</b> "
         "(квадрат и вертикальная полоса оттенков).<br><br>"
         "<b>Колёсико</b> над кругом — оттенок ±1°, с Shift — ±5°. Попробуйте!"),
    dict(title="HSV, HSL и V-HSV — в чём разница", target="comps", items=["wheel"], text=
         "<b>HSV</b> — правый верхний угол квадрата: самый чистый и яркий цвет. "
         "Удобно подбирать насыщенные цвета.<br><br>"
         "<b>HSL</b> — треугольник: вверх к белому, вниз к чёрному, чистый цвет посередине (L = 50%). "
         "Работает как краска: добавили белил — светлее, добавили чёрного — темнее.<br><br>"
         "<b>V-HSV</b> — как HSV, но по вертикали <b>воспринимаемая светлота</b>. В обычном HSV жёлтый и синий "
         "при одинаковом V выглядят совсем разной светлоты, а в V-HSV одинаковая высота значит одинаковый тон. "
         "Выбирайте V-HSV, когда важны тональные отношения."),
    dict(title="Luma-Based Palette", target="comps", items=["luma"], text=
         "Все цвета <b>той же светлоты (luma)</b>, что и текущий. Меняете оттенок и насыщенность — тон не прыгает. "
         "По умолчанию светлота считается так же, как серый режим CSP и Photoshop (Rec.601); "
         "вариант «по восприятию» (CIE L*) — в Настройки → Вид.<br><br>"
         "• центр «пятна» — серый, к краю — насыщеннее, направление — оттенок<br>"
         "• форма пятна — все цвета, которые экран может показать на этой светлоте<br>"
         "• <b>слайдер снизу</b> — светлота; светлая полоса вокруг ручки — диапазон близкого тона (±8)<br>"
         "• кнопка-кораблик — режим <b>Full</b>: все оттенки × вся светлота<br><br>"
         "Пример: поменять тёплую тень на холодную, не сломав тональный рисунок."),
    dict(title="Слайдеры: RGB, HSV, LAB", target="comps", items=["slider:RGB", "slider:HSV", "slider:LAB"], text=
         "Одни и те же цвета, но разные «ручки»:<br><br>"
         "<b>RGB</b> — как экран смешивает свет: красный, зелёный, синий (0–255). Точно, но не интуитивно.<br><br>"
         "<b>HSV</b> — оттенок, насыщенность, яркость. Удобно «по-художественному»: "
         "сделать чуть насыщеннее, сдвинуть к жёлтому.<br><br>"
         "<b>LAB</b> — <b>L</b> — настоящая воспринимаемая светлота, <b>a</b> — зелёный ↔ красный, "
         "<b>b</b> — синий ↔ жёлтый. Меняете a/b — светлота на глаз не меняется."),
    dict(title="Слайдеры: LCH, CMYK, V-HSV", target="comps", items=["slider:LCH", "slider:CMYK", "slider:V-HSV"], text=
         "<b>LCH</b> — тот же LAB в «круговом» виде: L — светлота, C — хрома (насыщенность), H — оттенок. "
         "Лучший выбор, чтобы сдвигать оттенок без скачков светлоты.<br><br>"
         "<b>CMYK</b> — краски печати: голубой, пурпурный, жёлтый, чёрный. Нужен для макетов в печать.<br><br>"
         "<b>V-HSV</b> — HSV с воспринимаемой светлотой вместо V.<br><br>"
         "• <b>клик по числу</b> справа — экранная цифровая клавиатура<br>"
         "• <b>колёсико</b> над строкой — изменить ровно этот параметр"),
    dict(title="Основной и фоновый цвет, контраст", target="comps", items=["fgbg", "contrast"], text=
         "<b>Таблетки</b>: основной цвет, фоновый, прозрачный. Клик — выбрать слот, ПКМ — поменять "
         "основной и фоновый местами. Выбранный слот отправляется в CSP.<br><br>"
         "<b>Контраст</b> — разница светлоты основного и фонового (ΔL*) и оценка: "
         "читается ли силуэт. Меньше 10 — фигура сольётся с фоном."),
    dict(title="История и наборы цветов", target="comps", items=["history", "swatches"], text=
         "<b>История</b> — недавние цвета. ПКМ → <b>«Закрепить»</b>: закреплённый цвет стоит первым и не вытесняется.<br><br>"
         "<b>Наборы</b> — свои палитры. «+» — добавить текущий цвет, ПКМ — удалить, клик по названию — другой набор.<br>"
         "Импорт и экспорт <b>.cls</b> (CSP), <b>.ase</b>, <b>.aco</b> — в редакторе панели на вкладке Swatches."),
    dict(title="Гармонии и смешивание", target="comps", items=["harmony", "mixer"], text=
         "<b>Гармонии</b> — цвета, которые сочетаются с текущим: дополнительные, триада, аналоговые и др. "
         "Клик по заголовку — схема, колёсико — повернуть схему.<br><br>"
         "<b>Смешивание</b> — переход A → B в OKLab, без серой «грязи» посередине. "
         "Клик по краю — взять текущий цвет, ПКМ — средний цвет, колёсико — число шагов. "
         "Нужно для переходов, светотени, рефлексов."),
    dict(title="Свет, тень и тон", target="comps", items=["light_shadow", "value"], text=
         "<b>Свет и тень</b> — оттенки текущего цвета под <b>цвет освещения</b> (клик по заголовку: закат, лампа, "
         "луна, свой…). Свет смешивается с цветом источника, тень — с цветом окружения. "
         "Колёсико — сила влияния.<br><br>"
         "<b>Тон</b> — светлота L* текущего цвета и номер ступени из 5/7/9. "
         "Клик по ступени — тот же оттенок в этой светлоте."),
    dict(title="Гамут-маска", target="comps", items=["gamut"], text=
         "Метод Джеймса Гарни: вы ограничиваете палитру картины фигурой на круге. "
         "Цвета вне маски затемнены, а выбор <b>прижимается к маске</b>.<br><br>"
         "• ПКМ-перетаскивание — двигать маску, колёсико — повернуть, Ctrl+колёсико — размер<br>"
         "• кнопка в углу — форма маски и <b>«Нарисовать новую маску»</b>: ставьте точки кликами, "
         "тяните их, ПКМ — удалить, Enter — сохранить. Свои маски появятся в этом же меню."),
    dict(title="Атмосфера и материалы", target="comps", items=["atmosphere", "materials"], text=
         "<b>Атмосфера</b> — слайдер «расстояние»: цвет уходит к цвету воздуха (день, дымка, закат, ночь…). "
         "Дальние планы становятся светлее, холоднее и менее насыщенными.<br><br>"
         "<b>Кожа и материалы</b> — готовые рампы от глубокой тени до блика: тона кожи, металлы, ткани, "
         "дерево, листва. Можно построить рампу и от текущего цвета. ПКМ — сохранить как набор."),
    dict(title="Палитра холста", target="comps", items=["canvas"], text=
         "Цвета, которые уже есть в вашей работе. Кнопка с пунктирной рамкой — один раз обвести холст на экране, "
         "⟳ — обновить, дискета — сохранить как набор.<br><br>"
         "Помогает не плодить почти одинаковые оттенки и держать палитру картины цельной."),
    dict(title="Управление CSP", target="comps", items=["quick_access", "canvas_nav", "brush"], text=
         "Группа <b>CSP Control</b> работает через подключение к CSP:<br><br>"
         "<b>Быстрый доступ</b> — кнопки из вашего набора Quick Access в CSP (инструменты, команды) "
         "плюс отмена и повтор. Клик по заголовку — другой набор или «Обновить из CSP».<br><br>"
         "<b>Холст</b> — масштаб, поворот, отражение, «вписать». Колёсико над компонентом — масштаб, "
         "Shift+колёсико — поворот.<br><br>"
         "<b>Кисть</b> — размер и непрозрачность текущего инструмента.<br><br>"
         "Всё это можно назначить и на клавиши макропада: ☰ → Горячие клавиши."),
    dict(title="Референс-доска и генератор палитры", target="menu", items=None, text=
         "☰ → <b>Референс-доска</b> — окно поверх всех программ. В него вставляются картинки через "
         "<b>Ctrl+V</b> или перетаскиванием. ЛКМ — пипетка, Shift+ЛКМ — выделить область, "
         "◐ — серый режим для проверки тона, «сквозь клик» — положить референс поверх холста.<br><br>"
         "☰ → <b>Генератор палитры</b> — палитра из картинки или выделения: основные, яркие, приглушённые, "
         "«свет / средние / тени», с долей каждого цвета.<br><br>"
         "☰ → <b>Окно кисти</b> — размер и непрозрачность кисти CSP двумя вертикальными слайдерами "
         "(нужно подключение к CSP)."),
    dict(title="Как собрать свою панель", target="menu", items=None, text=
         "☰ → <b>Настроить панель</b>. Слева — живое превью, справа — все компоненты по группам.<br><br>"
         "• клик или перетаскивание — добавить компонент<br>"
         "• ⠿ — перетащить, чтобы поменять порядок; «−» — убрать<br>"
         "• вкладка <b>Swatches</b> — наборы цветов: импорт, экспорт, извлечение из картинки"),
    dict(title="Горячие клавиши и HoverAdjust", target="panel", items=None, text=
         "☰ → <b>Горячие клавиши</b>: назначьте клавиши отдельной клавиатуры или макропада — вызов панели, "
         "панели 1–4, пипетку, референсы, ±оттенок, ±светлоту и др. Клавиши работают, даже когда активен CSP.<br><br>"
         "<b>HoverAdjust</b>: наведите курсор на круг, палитру или слайдер и крутите колёсико или диск — "
         "меняется именно этот параметр.<br><br>"
         "Кнопка вызова, нажатая над панелью, листает панели."),
    dict(title="Готово!", target="panel", items=None, text=
         "Это всё. Повторить обучение можно в любой момент: <b>☰ → Обучение</b>.<br><br>"
         "Если что-то сломается: ☰ → Журнал ошибок → «Скопировать отчёт».<br><br>Приятного рисования!"),
]


class PanelHighlight(QWidget):
    """Подсветка внутри самой панели: затемнение вокруг нужной части + пульсирующая рамка.
    Дочерний виджет с WA_TransparentForMouseEvents — клики всегда проходят к панели,
    остальной экран не затеняется и не блокируется."""

    def __init__(self, panel):
        super().__init__(panel)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.hole = QRect()
        self.phase = 0.0

    def set_hole(self, local_rect):
        p = self.parentWidget()
        if self.geometry() != p.rect():
            self.setGeometry(p.rect())
        self.hole = local_rect
        self.raise_()
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        panel = self.parentWidget()
        card = QPainterPath()
        card.addRoundedRect(panel.card_rect(), 16, 16)
        tabs = panel._tab_rects()
        for r in tabs:
            card.addRoundedRect(r, 8, 8)
        hole = QPainterPath()
        hr = QRectF(self.hole).adjusted(-4, -4, 4, 4)
        hole.addRoundedRect(hr, 10, 10)
        p.fillPath(card.subtracted(hole), QColor(6, 9, 16, 150))
        a = int(140 + 100 * abs(1 - (self.phase % 2)))
        p.setPen(QPen(QColor(47, 107, 255, a), 3))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(hr, 10, 10)


class TourCard(QWidget):
    def __init__(self, tour):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.tour = tour
        self.setFixedWidth(400)
        lay = QVBoxLayout(self)
        m = ui.SHADOW + 16
        lay.setContentsMargins(m, m - 2, m, m)
        lay.setSpacing(8)
        self.step = QLabel()
        self.step.setObjectName("head")
        lay.addWidget(self.step)
        self.title = QLabel()
        self.title.setObjectName("title")
        self.title.setStyleSheet("font-size:12pt")
        self.title.setWordWrap(True)
        lay.addWidget(self.title)
        self.text = QLabel()
        self.text.setWordWrap(True)
        self.text.setTextFormat(Qt.RichText)
        lay.addWidget(self.text)
        row = QHBoxLayout()
        self.skip = ui.pill("Пропустить", "ghost")
        self.back = ui.pill("←  Назад", "ghost")
        self.next = ui.pill("Далее  →", "primary")
        self.skip.clicked.connect(tour.finish)
        self.back.clicked.connect(lambda: tour.go(tour.i - 1))
        self.next.clicked.connect(lambda: tour.go(tour.i + 1))
        row.addWidget(self.skip)
        row.addStretch()
        row.addWidget(self.back)
        row.addWidget(self.next)
        lay.addLayout(row)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        ui.paint_card(p, QRectF(self.rect()).adjusted(ui.SHADOW, ui.SHADOW, -ui.SHADOW, -ui.SHADOW))

    def keyPressEvent(self, e):
        k = e.key()
        if k in (Qt.Key_Right, Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.tour.go(self.tour.i + 1)
        elif k == Qt.Key_Left:
            self.tour.go(self.tour.i - 1)
        elif k == Qt.Key_Escape:
            self.tour.finish()


class Tour(QObject):
    def __init__(self, panel):
        super().__init__(panel)
        self.panel = panel
        self.i = -1
        self.backup = copy.deepcopy(panel.layouts[panel.cur]["items"]) if panel.body is None else \
            copy.deepcopy(panel.body.items())
        panel._tour = self
        panel._show_home()
        self.dim = PanelHighlight(panel)
        self.card = TourCard(self)
        self.timer = QTimer(self, interval=60)
        self.timer.timeout.connect(self._tick)

    def start(self):
        self.dim.show()
        self.card.show()
        self.timer.start()
        self.go(0)

    def _set_items(self, items):
        p = self.panel
        want = copy.deepcopy(self.backup) if items is None else [{"key": k} for k in items]
        if p.body is not None and [c.KEY for c in p.body.comps] == [it["key"] for it in want]:
            return
        if p.body is not None:
            p.body.hide()
            p.body.deleteLater()
            p.body = None
        p.layouts[p.cur]["items"] = want
        p.build_body()

    def go(self, i):
        if i >= len(STEPS):
            self.finish()
            return
        if i < 0:
            return
        self.i = i
        st = STEPS[i]
        self._set_items(st["items"])
        self.card.step.setText(f"Обучение · {i + 1} из {len(STEPS)}")
        self.card.title.setText(st["title"])
        self.card.text.setText(st["text"])
        self.card.back.setEnabled(i > 0)
        self.card.next.setText("Готово" if i == len(STEPS) - 1 else "Далее  →")
        self.card.adjustSize()
        QTimer.singleShot(30, self._tick)
        self.dim.raise_()
        self.card.raise_()
        self.card.activateWindow()
        self.card.setFocus()

    def _target(self):
        p = self.panel
        t = STEPS[self.i]["target"]
        g = lambda r: QRect(p.mapToGlobal(r.topLeft().toPoint() if isinstance(r, QRectF) else r.topLeft()),
                            r.size().toSize() if isinstance(r, QRectF) else r.size())
        if t == "tabs":
            rs = p._tab_rects()
            r = rs[0]
            for x in rs[1:]:
                r = r.united(x)
            return g(r)
        if t == "header":
            r = p.eye_btn.geometry().united(p.menu_btn.geometry()).united(p.pin_btn.geometry())
            return g(r)
        if t == "menu":
            return g(p.menu_btn.geometry())
        if t == "dot":
            return g(p.logo.geometry().united(p.dot.geometry()))
        if t == "comps" and p.body is not None and p.body.comps:
            r = None
            for c in p.body.comps:
                cr = QRect(c.mapToGlobal(QPoint(0, 0)), c.size())
                r = cr if r is None else r.united(cr)
            return r
        return g(p.card_rect())

    def _tick(self):
        if self.i < 0:
            return
        if not self.panel.isVisible():
            self.panel._show_home()
        tr = self._target()
        self.dim.phase += 0.08
        self.dim.set_hole(QRect(self.panel.mapFromGlobal(tr.topLeft()), tr.size()))
        # карточка — справа от панели, иначе слева; по высоте — у подсвеченной области
        pg = self.panel.frameGeometry()
        scr = (QGuiApplication.screenAt(pg.center()) or QGuiApplication.primaryScreen()).availableGeometry()
        cw, ch = self.card.width(), self.card.sizeHint().height()
        x = pg.right() - ui.SHADOW + 6
        if x + cw > scr.right():
            x = pg.left() + ui.SHADOW - cw - 6
        x = max(scr.left(), min(x, scr.right() - cw))
        y = max(scr.top(), min(tr.center().y() - ch // 2, scr.bottom() - ch))
        if self.card.pos() != QPoint(x, y):
            self.card.move(x, y)
        if self.card.height() != ch:
            self.card.resize(cw, ch)

    def finish(self):
        self.timer.stop()
        self._set_items(None)
        self.dim.hide()
        self.card.close()
        self.dim.deleteLater()
        self.card.deleteLater()
        self.panel._tour = None
        self.panel.cfg["tour_done"] = True
        self.panel.update()
        self.deleteLater()


def start_tour(panel):
    if getattr(panel, "_tour", None):
        return
    Tour(panel).start()
