"""曲线可视化组件 — 实时绘制速度-时间曲线"""
from PyQt6.QtCore import Qt, QPointF
from PyQt6.QtGui import QPainter, QPainterPath, QPen, QColor, QFont, QPalette
from PyQt6.QtWidgets import QWidget

from mouse_emulator import (
    CURVE_LINEAR, CURVE_TRADITIONAL, CURVE_HIGH_SPEED,
    CURVE_LABELS, calc_curve_speed,
)


class CurveWidget(QWidget):
    """速度-时间曲线可视化"""

    MARGIN_LEFT = 55
    MARGIN_RIGHT = 20
    MARGIN_TOP = 15
    MARGIN_BOTTOM = 35

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(220)

        # ── 曲线参数 ──
        self.curve_type = CURVE_LINEAR
        self.deadzone = 0.0
        self.max_time = 1.5
        self.start_speed = 0.0
        self.max_speed = 1000.0
        self.intensity = 1.0

        # ── 实时状态 ──
        self._current_held = 0.0
        self._current_speed = 0.0

    # ──────────────────────── 公开接口 ────────────────────────
    def set_params(self, curve_type, deadzone, max_time, start_speed, max_speed, intensity):
        self.curve_type = curve_type
        self.deadzone = deadzone
        self.max_time = max_time
        self.start_speed = start_speed
        self.max_speed = max_speed
        self.intensity = intensity
        self.update()

    def set_current(self, held_time, speed):
        self._current_held = held_time
        self._current_speed = speed
        self.update()

    def reset_current(self):
        self._current_held = 0.0
        self._current_speed = 0.0
        self.update()

    # ──────────────────────── 绘制 ────────────────────────
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        pal = self.palette()
        txt = pal.color(QPalette.ColorRole.WindowText)
        mid = pal.color(QPalette.ColorRole.Mid)
        dark = pal.color(QPalette.ColorRole.Dark)
        light = pal.color(QPalette.ColorRole.Light)

        bg = pal.color(QPalette.ColorRole.Window)
        is_dark = bg.lightness() < 128
        grid_color = light if is_dark else mid
        axis_color = mid if is_dark else dark
        label_color = txt
        axis_label_color = QColor(txt.red(), txt.green(), txt.blue(), 180)

        w = self.width()
        h = self.height()

        plot_left = self.MARGIN_LEFT
        plot_right = w - self.MARGIN_RIGHT
        plot_top = self.MARGIN_TOP
        plot_bottom = h - self.MARGIN_BOTTOM
        plot_w = plot_right - plot_left
        plot_h = plot_bottom - plot_top

        # ── 背景 ──
        # 透明，与父窗口背景融合

        # ── 网格 ──
        pen_grid = QPen(grid_color, 1)
        p.setPen(pen_grid)
        for i in range(6):
            y = plot_top + plot_h * i / 5
            p.drawLine(int(plot_left), int(y), int(plot_right), int(y))
        for i in range(6):
            x = plot_left + plot_w * i / 5
            p.drawLine(int(x), int(plot_top), int(x), int(plot_bottom))

        # ── 坐标轴 ──
        pen_axis = QPen(axis_color, 2)
        p.setPen(pen_axis)
        p.drawLine(int(plot_left), int(plot_bottom), int(plot_right), int(plot_bottom))
        p.drawLine(int(plot_left), int(plot_top), int(plot_left), int(plot_bottom))

        # ── 坐标标签 ──
        font = QFont('Segoe UI', 8)
        p.setFont(font)
        p.setPen(label_color)
        display_time = max(self.max_time, 0.1)
        for i in range(6):
            t = display_time * i / 5
            x = plot_left + plot_w * (t / display_time)
            p.drawText(int(x) - 20, int(plot_bottom + 18), 40, 16,
                       Qt.AlignmentFlag.AlignCenter, f'{t:.1f}s')
        for i in range(6):
            s = self.max_speed * i / 5
            y = plot_bottom - plot_h * i / 5
            p.drawText(2, int(y) - 8, self.MARGIN_LEFT - 6, 16,
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                       f'{int(s)}')

        # ── 轴标签 ──
        p.setPen(axis_label_color)
        p.drawText(int(plot_left + plot_w / 2 - 20), int(h - 2), 40, 14,
                   Qt.AlignmentFlag.AlignCenter, '时间')
        p.save()
        p.translate(8, int(plot_top + plot_h / 2 + 20))
        p.rotate(-90)
        p.drawText(-20, 0, 40, 14, Qt.AlignmentFlag.AlignCenter, '速度 px/s')
        p.restore()

        # ── 死区标记 ──
        if self.deadzone > 0.001:
            dz_x = int(plot_left + plot_w * (self.deadzone / display_time))
            pen_dz = QPen(QColor(255, 80, 80, 120), 1)
            p.setPen(pen_dz)
            p.drawLine(dz_x, int(plot_top), dz_x, int(plot_bottom))
            p.setPen(QColor(255, 100, 100))
            font_sm = QFont('Segoe UI', 7)
            p.setFont(font_sm)
            p.drawText(dz_x - 25, int(plot_top - 12), 50, 12,
                       Qt.AlignmentFlag.AlignCenter, f'死区 {self.deadzone:.1f}s')

        # ── 曲线 ──
        curve_color = {
            CURVE_LINEAR: QColor(80, 180, 255),
            CURVE_TRADITIONAL: QColor(255, 180, 80),
            CURVE_HIGH_SPEED: QColor(80, 255, 140),
        }.get(self.curve_type, QColor(200, 200, 200))

        path = QPainterPath()
        first = True
        steps = 200
        for i in range(steps + 1):
            t = display_time * i / steps
            v = calc_curve_speed(
                self.curve_type, t,
                self.deadzone, self.max_time, self.start_speed, self.max_speed, self.intensity,
            )
            px = plot_left + plot_w * (t / display_time)
            py = plot_bottom - plot_h * (v / self.max_speed)
            if first:
                path.moveTo(px, py)
                first = False
            else:
                path.lineTo(px, py)

        pen_curve = QPen(curve_color, 2.5)
        p.setPen(pen_curve)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)

        # ── 当前实时位置光点 ──
        if self._current_held > 0 and self._current_speed > 0:
            cx = plot_left + plot_w * min(self._current_held / display_time, 1.0)
            cy = plot_bottom - plot_h * min(self._current_speed / self.max_speed, 1.0)

            glow = QColor(curve_color.red(), curve_color.green(), curve_color.blue(), 60)
            p.setBrush(glow)
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(cx, cy), 10, 10)

            p.setBrush(curve_color)
            p.drawEllipse(QPointF(cx, cy), 5, 5)

        # ── 图例 ──
        legend_x = int(plot_right - 120)
        legend_y = int(plot_top + 5)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(curve_color)
        p.drawRect(legend_x, legend_y, 14, 10)
        p.setPen(label_color)
        p.setFont(QFont('Segoe UI', 8))
        p.drawText(legend_x + 18, legend_y, 100, 12,
                   Qt.AlignmentFlag.AlignVCenter,
                   f'{CURVE_LABELS.get(self.curve_type, "")} 曲线')

    def sizeHint(self):
        from PyQt6.QtCore import QSize
        return QSize(300, 220)
