# Dynamic Color Picker

Модульная панель работы с цветом для Clip Studio Paint и Photoshop.

## Скачать

Готовый exe для Windows: **[Releases → latest → DynamicColorPicker.exe](../../releases/latest)**.
Пересобирается автоматически при каждом push в `main` (GitHub Actions).

## Интерфейс

Плавающая тёмная карточка без рамки. Слева вкладки панелей (1, 2, +; ПКМ — переименовать/удалить),
справа сверху ☰ меню и 📌 закрепление. ☰ → «Настроить панель»: слева живое превью,
справа Components / Swatches — компоненты добавляются кликом или перетаскиванием, порядок меняется за ⠿.

## Возможности

- Color Picker: HSV / HSL / V-HSV, круг или куб
- Luma Palette: оттенки с той же яркостью L*
- Слайдеры RGB, CMYK, HSL, HSV, V-HSV, LAB, LCH
- История, основной / фоновый / прозрачный цвет
- Палитры: создание, импорт/экспорт (.gpl/.json/.txt), извлечение из изображения (Extraction Accuracy)
- Компоненты собираются в панель в редакторе, несколько панелей-вкладок
- Закрепление окна и всплытие у кончика пера (горячая клавиша / средняя кнопка)
- Связь с CSP через Companion Mode (`File → Connect to smartphone`, QR считывается с экрана)
- Photoshop (Windows): цвет напрямую через COM

## Запуск из исходников

```
pip install PySide6 numpy opencv-python pynput pywin32
python dynamic_color_picker.py
```

Локальная сборка exe: `build.bat`.

## Примечание

Протокол CSP Companion Mode неофициальный, реализован по заметкам
[LumaPaletteCSP/PROTOCOL.md](https://github.com/andyubird/LumaPaletteCSP/blob/main/PROTOCOL.md).
Может перестать работать после обновления CSP.
