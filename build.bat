@chcp 65001 >nul
@echo off
REM Сборка Dynamic Color Picker в один exe.
REM Положите рядом: dynamic_color_picker.py, csp_companion.py, (опционально) icon.ico
REM Нужен Python 3.10+ с python.org (галочка "Add to PATH").
cd /d "%~dp0"

python -m venv .venv || goto :err
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install PySide6 numpy opencv-python-headless pynput pywin32 pyinstaller || goto :err

set ICON=
if exist icon.ico set ICON=--icon icon.ico

pyinstaller --noconfirm --clean --onefile --windowed ^
  --name DynamicColorPicker %ICON% ^
  --hidden-import csp_companion ^
  --hidden-import pynput.keyboard._win32 ^
  --hidden-import pynput.mouse._win32 ^
  --hidden-import win32com.client ^
  --exclude-module PySide6.QtWebEngineCore ^
  --exclude-module PySide6.Qt3DCore ^
  --exclude-module PySide6.QtQuick ^
  --exclude-module PySide6.QtQml ^
  --exclude-module PySide6.QtMultimedia ^
  --exclude-module tkinter ^
  dynamic_color_picker.py || goto :err

echo.
echo Готово: dist\DynamicColorPicker.exe
pause
exit /b 0

:err
echo.
echo Ошибка сборки.
pause
exit /b 1
