"""键盘延迟校准窗口 — 横向下落式校准"""
import time
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel
from qfluentwidgets import SubtitleLabel, BodyLabel, PushButton

TRACK_W = 320
TRACK_H = 50
LINE_W = 3
TARGET_X = 260
FALL_MS = 1000


class LatencyCalibrationWindow(QWidget):

    def __init__(self, callback=None):
        super().__init__()
        self.setWindowTitle("键盘延迟校准")
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint)
        self.setFixedSize(380, 260)

        self._callback = callback
        self._samples = []
        self._is_running = False
        self._target_n = 10
        self._crossed = False
        self._expected = 0.0
        self._t0 = 0.0

        self._anim = QTimer(self)
        self._anim.timeout.connect(self._tick)
        self._beat = QTimer(self)
        self._beat.timeout.connect(self._drop)

        self._init_ui()

    def _init_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(10)

        root.addWidget(SubtitleLabel("键盘延迟校准", self))

        tip = BodyLabel("红线经过蓝线时按下空格键", self)
        tip.setWordWrap(True)
        root.addWidget(tip)

        self._track = QLabel(self)
        self._track.setFixedSize(TRACK_W, TRACK_H)
        self._track.setStyleSheet("background-color:#1e1e1e; border:1px solid #444;")

        self._blue = QLabel(self._track)
        self._blue.setGeometry(TARGET_X, 0, LINE_W, TRACK_H)
        self._blue.setStyleSheet("background-color:#0078d4;")

        self._red = QLabel(self._track)
        self._red.setGeometry(-LINE_W, 0, LINE_W, TRACK_H)
        self._red.setStyleSheet("background-color:#ff4444;")

        root.addWidget(self._track, alignment=Qt.AlignmentFlag.AlignCenter)

        self._prog = BodyLabel("进度: 0 / 10", self)
        root.addWidget(self._prog)

        self._res = BodyLabel("测量结果: --", self)
        root.addWidget(self._res)

        btn = QHBoxLayout()
        self._btn_start = PushButton("开始校准", self)
        self._btn_start.clicked.connect(self._start)
        btn.addWidget(self._btn_start)
        self._btn_apply = PushButton("应用并关闭", self)
        self._btn_apply.clicked.connect(self._apply)
        self._btn_apply.setEnabled(False)
        btn.addWidget(self._btn_apply)
        root.addLayout(btn)

    def _start(self):
        self._samples = []
        self._is_running = True
        self._crossed = False
        self._btn_start.setEnabled(False)
        self._btn_apply.setEnabled(False)
        self._prog.setText("进度: 0 / 10")
        self._res.setText("测量中...")
        self._beat.start(1000)
        self._drop()

    def _drop(self):
        if not self._is_running:
            return
        self._red.move(-LINE_W, 0)
        self._t0 = time.time() * 1000
        self._crossed = False
        self._anim.start(16)

    def _tick(self):
        if not self._is_running:
            return
        now = time.time() * 1000
        progress = min((now - self._t0) / FALL_MS, 1.0)
        x = int(progress * (TRACK_W + LINE_W)) - LINE_W
        self._red.move(x, 0)

        if not self._crossed and x >= TARGET_X:
            self._expected = now
            self._crossed = True

        if progress >= 1.0:
            self._anim.stop()
            self._crossed = False

    def keyPressEvent(self, e):
        if not self._is_running or not self._crossed:
            return
        if e.key() != Qt.Key.Key_Space:
            return

        self._crossed = False
        latency = max(0, time.time() * 1000 - self._expected)
        self._samples.append(latency)
        n = len(self._samples)
        avg = sum(self._samples) / n
        self._prog.setText(f"进度: {n} / {self._target_n}")
        self._res.setText(f"当前: {latency:.0f}ms  平均: {avg:.0f}ms")
        if n >= self._target_n:
            self._finish()

    def _finish(self):
        self._is_running = False
        self._anim.stop()
        self._beat.stop()
        self._btn_start.setEnabled(True)
        self._btn_apply.setEnabled(True)
        avg = sum(self._samples) / len(self._samples)
        self._res.setText(f"校准完成! 平均延迟: {avg:.0f}ms")

    def _apply(self):
        if not self._samples:
            return
        if self._callback:
            self._callback(int(sum(self._samples) / len(self._samples)))
        self.close()

    def closeEvent(self, e):
        self._is_running = False
        self._anim.stop()
        self._beat.stop()
        e.accept()
