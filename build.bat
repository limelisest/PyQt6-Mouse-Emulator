@echo off
chcp 65001 >nul
call conda activate pyqt_env
pyinstaller --noconsole --icon=icon.png --add-data "icon.png;." --name=MouseController --onefile --clean main.py
pause