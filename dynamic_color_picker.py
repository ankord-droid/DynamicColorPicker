#!/usr/bin/env python3
"""
Dynamic Color Picker — плавающая модульная панель цвета для Clip Studio Paint и Photoshop.

Зависимости:  pip install PySide6 numpy
Опционально:  opencv-python (QR CSP с экрана), pynput (горячие клавиши), pywin32 (Photoshop)
Запуск:       python dynamic_color_picker.py
"""
from dcp_app import main

if __name__ == "__main__":
    main()
