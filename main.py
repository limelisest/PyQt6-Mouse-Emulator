"""键盘模拟鼠标 — 程序入口"""
import sys
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication
from main_window import MainWindow

if __name__ == '__main__':
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    window = MainWindow()
    if not window._admin_relaunching:
        window.show()
        sys.exit(app.exec())