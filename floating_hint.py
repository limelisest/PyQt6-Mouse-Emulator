"""浮空提示窗 — 启用控制键时显示半透明提示"""
import ctypes
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPainter, QColor, QFont, QFontMetrics, QCursor
from PyQt6.QtWidgets import QWidget, QApplication


class FloatingHint(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        self._text = "鼠标控制"
        self._bg_color = QColor(0, 0, 0, 153)
        self._text_color = Qt.GlobalColor.white
        self._padding = 16
        self._corner_radius = 8
        self._font = QFont("Microsoft YaHei", 11)

        self._update_size()

    def showEvent(self, event):
        super().showEvent(event)
        hwnd = int(self.winId())
        ex_style = ctypes.windll.user32.GetWindowLongW(hwnd, -20)
        ex_style |= 0x80000  # WS_EX_LAYERED
        ex_style |= 0x20     # WS_EX_TRANSPARENT
        ctypes.windll.user32.SetWindowLongW(hwnd, -20, ex_style)

    def _update_size(self):
        fm = QFontMetrics(self._font)
        text_rect = fm.boundingRect(self._text)
        w = text_rect.width() + self._padding * 2
        h = text_rect.height() + self._padding * 2 + 4
        self.resize(w, h)

    def reposition(self):
        cursor_pos = QCursor.pos()
        screen = QApplication.screenAt(cursor_pos)
        if screen is None:
            screen = QApplication.primaryScreen()
        if screen is None:
            return
        geometry = screen.availableGeometry()
        x = geometry.x() + (geometry.width() - self.width()) // 2
        y = geometry.y() + geometry.height() - geometry.height() // 10 - self.height()
        self.move(int(x), int(y))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(self._bg_color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(self.rect(), self._corner_radius, self._corner_radius)
        painter.setPen(self._text_color)
        painter.setFont(self._font)
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._text)
