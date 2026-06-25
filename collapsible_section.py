"""可折叠卡片容器"""
from PyQt6.QtCore import Qt, QEvent
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout
from qfluentwidgets import CardWidget, BodyLabel


class CollapsibleSection(CardWidget):
    def __init__(self, title, parent=None):
        super().__init__(parent)
        self._expanded = True

        self._main_layout = QVBoxLayout(self)
        self._main_layout.setContentsMargins(0, 0, 0, 0)
        self._main_layout.setSpacing(0)

        # 可点击的标题栏
        self._header = QWidget(self)
        self._header.setFixedHeight(38)
        self._header.setCursor(Qt.CursorShape.PointingHandCursor)
        self._header.installEventFilter(self)
        hl = QHBoxLayout(self._header)
        hl.setContentsMargins(16, 0, 16, 0)
        self._title_label = BodyLabel(title, self)
        hl.addWidget(self._title_label)
        hl.addStretch()
        self._arrow = BodyLabel("▲", self)
        hl.addWidget(self._arrow)
        self._main_layout.addWidget(self._header)

        # 内容区域
        self._content = QWidget(self)
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(16, 4, 16, 16)
        self._main_layout.addWidget(self._content)

    def eventFilter(self, obj, event):
        if not hasattr(self, '_header'):
            return super().eventFilter(obj, event)
        if obj is self._header and event.type() == QEvent.Type.MouseButtonRelease:
            self._toggle()
            return True
        return super().eventFilter(obj, event)

    def _toggle(self):
        self._expanded = not self._expanded
        self._content.setVisible(self._expanded)
        self._arrow.setText("▲" if self._expanded else "▼")

    def content_layout(self):
        return self._content_layout

    def expand(self):
        if not self._expanded:
            self._toggle()

    def collapse(self):
        if self._expanded:
            self._toggle()
