"""主窗口 — 左右分栏 UI + 曲线可视化 + 键盘监听 + 配置持久化 + 系统托盘"""
import sys
import json
import os
import time
import ctypes
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject, QEvent
from PyQt6.QtGui import QIcon, QAction
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSystemTrayIcon, QMenu, QApplication,
    QSlider, QLabel, QScrollArea,
)
from qfluentwidgets import (
    SpinBox, DoubleSpinBox, SwitchButton, CardWidget,
    SubtitleLabel, BodyLabel, PushButton, ComboBox,
    setTheme, Theme, MSFluentWindow,
)
from pynput import keyboard, mouse

from latency_calibration import LatencyCalibrationWindow
from mouse_emulator import (
    MouseEmulatorThread,
    CURVE_LINEAR, CURVE_TRADITIONAL, CURVE_HIGH_SPEED,
    CURVE_LABELS, CURVE_PRESETS,
)
from curve_widget import CurveWidget
from floating_hint import FloatingHint
from collapsible_section import CollapsibleSection

class _NoWheelFilter(QObject):
    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Wheel:
            event.ignore()
            return True
        return super().eventFilter(obj, event)


def _no_wheel(widget):
    widget.installEventFilter(_NoWheelFilter(widget))


def _resource_path(relative_path):
    if getattr(sys, 'frozen', False):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), relative_path)

ICON_PATH = _resource_path('icon.png')

CONFIG_DIR = os.path.join(os.getenv('APPDATA', os.path.expanduser('~')), 'MouseController')
os.makedirs(CONFIG_DIR, exist_ok=True)
CONFIG_PATH = os.path.join(CONFIG_DIR, 'config.json')

RUN_REG_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'


def _check_boot_reg():
    import winreg
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_REG_KEY, 0, winreg.KEY_QUERY_VALUE)
        try:
            val, _ = winreg.QueryValueEx(key, 'MouseController')
            return val == sys.executable
        except FileNotFoundError:
            return False
        finally:
            winreg.CloseKey(key)
    except Exception:
        return False


class MainWindow(MSFluentWindow):
    key_recorded_signal = pyqtSignal(str, str, object)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("键盘鼠标模拟器")
        self.setWindowIcon(QIcon(ICON_PATH))
        self.resize(550, 750)
        self.setMicaEffectEnabled(True)
        self.navigationInterface.hide()
        setTheme(Theme.AUTO)

        self.titleBar.setIcon(QIcon(ICON_PATH))
        self.titleBar.titleLabel.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.titleBar.setFixedHeight(32)

        self.emulator = MouseEmulatorThread()
        self._kb_ctrl = keyboard.Controller()
        self.recording_target = None
        self.key_buttons = {}
        self._alt_held = False
        self._alt_tab_used = False

        self._init_ui()
        self._init_tray()
        self._load_config()
        self.key_recorded_signal.connect(self._handle_key_recorded)
        self._init_listener()
        self.emulator.start()

        # ── 定时刷新曲线实时位置 ──
        self._curve_timer = QTimer(self)
        self._curve_timer.timeout.connect(self._poll_curve_state)
        self._curve_timer.start(50)

        # ── 浮空提示窗 ──
        self._floating_hint = FloatingHint()

        # ── 定时检查大写锁状态 ──
        self._capslock_timer = QTimer(self)
        self._capslock_timer.timeout.connect(self._poll_capslock_state)
        self._capslock_timer.start(100)

        # ── 定时控制浮空提示窗 ──
        self._hint_timer = QTimer(self)
        self._hint_timer.timeout.connect(self._poll_hint_state)
        self._hint_timer.start(200)

    # ══════════════════════════ UI 布局 ══════════════════════════
    def _init_ui(self):
        content = QWidget()
        root = QVBoxLayout(content)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        root.addWidget(SubtitleLabel("键盘鼠标模拟器", self))

        sw_row = QHBoxLayout()
        sw_row.addWidget(BodyLabel("启用模拟器:", self))
        self.enable_switch = SwitchButton(self)
        self.enable_switch.checkedChanged.connect(self._toggle_emulator)
        sw_row.addWidget(self.enable_switch)
        sw_row.addStretch(1)
        root.addLayout(sw_row)

        # ── 按键设置 ──
        key_section = CollapsibleSection("按键设置", self)
        key_cl = key_section.content_layout()

        mod_row = QHBoxLayout()
        mod_row.addWidget(BodyLabel("组合键", self))
        self.mode_combo = ComboBox(self)
        self.mode_combo.addItems(['按住触发', '按下切换', '混合模式', '大写锁模式'])
        self.mode_combo.setCurrentIndex(0)
        self.mode_combo.currentIndexChanged.connect(self._update_mod_mode)
        mod_row.addWidget(self.mode_combo)
        mod_btn = PushButton(str(self.emulator.mod_key_id).upper(), self)
        mod_btn.setFixedWidth(100)
        mod_btn.setFixedHeight(32)
        mod_btn.clicked.connect(lambda: self._start_recording('mod'))
        self.key_buttons['mod'] = mod_btn
        mod_row.addWidget(mod_btn)
        mod2_btn = PushButton('未设置', self)
        mod2_btn.setFixedWidth(100)
        mod2_btn.setFixedHeight(32)
        mod2_btn.clicked.connect(lambda: self._start_recording('mod2'))
        self.key_buttons['mod2'] = mod2_btn
        mod_row.addWidget(mod2_btn)
        key_cl.addLayout(mod_row)

        self._create_key_btn(key_cl, "退出组合键", "exit_mod", '未设置')
        self._create_key_btn(key_cl, "上移键", "up", self.emulator.keys_config['up'])
        self._create_key_btn(key_cl, "下移键", "down", self.emulator.keys_config['down'])
        self._create_key_btn(key_cl, "左移键", "left", self.emulator.keys_config['left'])
        self._create_key_btn(key_cl, "右移键", "right", self.emulator.keys_config['right'])
        self._create_key_btn(key_cl, "左键拖拽/点击", "click_l", self.emulator.keys_config['click_l'])
        self._create_key_btn(key_cl, "右键拖拽/点击", "click_r", self.emulator.keys_config['click_r'])
        self._create_key_btn(key_cl, "滚轮向上", "scroll_up", self.emulator.keys_config['scroll_up'])
        self._create_key_btn(key_cl, "滚轮向下", "scroll_down", self.emulator.keys_config['scroll_down'])
        self._create_key_btn(key_cl, "后退键 (侧键)", "back", self.emulator.keys_config['back'])
        self._create_key_btn(key_cl, "前进键 (侧键)", "forward", self.emulator.keys_config['forward'])
        self._create_key_btn(key_cl, "窗口居中", "center_window", self.emulator.keys_config['center_window'])
        root.addWidget(key_section)

        # ── 曲线设置 ──
        curve_section = CollapsibleSection("曲线设置", self)
        curve_cl = curve_section.content_layout()

        preset_row = QHBoxLayout()
        preset_row.addWidget(BodyLabel("曲线预设:", self))
        self.curve_combo = ComboBox(self)
        self.curve_combo.addItems([CURVE_LABELS[t] for t in
                                   (CURVE_LINEAR, CURVE_TRADITIONAL, CURVE_HIGH_SPEED)])
        self.curve_combo.setCurrentIndex(0)
        self.curve_combo.currentIndexChanged.connect(self._on_preset_changed)
        preset_row.addWidget(self.curve_combo)
        preset_row.addStretch(1)
        curve_cl.addLayout(preset_row)

        self.curve_widget = CurveWidget(self)
        self.curve_widget.setMinimumHeight(180)
        curve_cl.addWidget(self.curve_widget)

        self._add_param_row(curve_cl, "启动速度 (px/s)", "start_speed",
                            1000, 0, 50, int)
        self._add_param_row(curve_cl, "死区 (秒)", "deadzone",
                            300, 0.0, 0.01, float)
        self._add_param_row(curve_cl, "最大速度时间 (秒)", "max_time",
                            500, 1.5, 0.1, float)
        self._add_param_row(curve_cl, "最大速度 (px/s)", "max_speed",
                            3000, 1000, 50, int)
        self._add_param_row(curve_cl, "曲线强度", "intensity",
                            500, 1.0, 0.1, float)
        root.addWidget(curve_section)

        # ── 其他设置 ──
        other_section = CollapsibleSection("其他设置", self)
        other_cl = other_section.content_layout()

        ex_row = QHBoxLayout()
        ex_row.addWidget(BodyLabel("独占组合键:", self))
        ex_row.addStretch(1)
        self.exclusive_switch = SwitchButton(self)
        self.exclusive_switch.setChecked(True)
        self.exclusive_switch.checkedChanged.connect(self._update_exclusive_mod)
        ex_row.addWidget(self.exclusive_switch)
        other_cl.addLayout(ex_row)

        boot_row = QHBoxLayout()
        boot_row.addWidget(BodyLabel("开机自启:", self))
        boot_row.addStretch(1)
        self.boot_switch = SwitchButton(self)
        self.boot_switch.setChecked(_check_boot_reg())
        self.boot_switch.checkedChanged.connect(self._toggle_boot)
        boot_row.addWidget(self.boot_switch)
        other_cl.addLayout(boot_row)

        hint_row = QHBoxLayout()
        hint_row.addWidget(BodyLabel("浮空提示窗:", self))
        hint_row.addStretch(1)
        self.hint_switch = SwitchButton(self)
        self.hint_switch.setChecked(True)
        hint_row.addWidget(self.hint_switch)
        other_cl.addLayout(hint_row)

        scroll_row = QHBoxLayout()
        scroll_row.addWidget(BodyLabel("滚轮步进 (行):", self))
        scroll_row.addStretch(1)
        self.scroll_step_box = SpinBox(self)
        self.scroll_step_box.setRange(1, 9999)
        self.scroll_step_box.setValue(3)
        self.scroll_step_box.setFixedWidth(150)
        self.scroll_step_box.setFixedHeight(32)
        self.scroll_step_box.valueChanged.connect(self._update_curve_params)
        _no_wheel(self.scroll_step_box)
        scroll_row.addWidget(self.scroll_step_box)
        other_cl.addLayout(scroll_row)

        lat_row = QHBoxLayout()
        lat_row.addWidget(BodyLabel("延迟补偿 (ms):", self))
        self.latency_slider = QSlider(Qt.Orientation.Horizontal, self)
        self.latency_slider.setRange(0, 500)
        self.latency_slider.setValue(0)
        self.latency_slider.valueChanged.connect(self._on_latency_slider)
        _no_wheel(self.latency_slider)
        lat_row.addWidget(self.latency_slider, 1)
        calibrate_btn = PushButton("校准", self)
        calibrate_btn.setFixedHeight(32)
        calibrate_btn.clicked.connect(self._open_calibration)
        lat_row.addWidget(calibrate_btn)
        self.latency_box = SpinBox(self)
        self.latency_box.setRange(0, 500)
        self.latency_box.setValue(0)
        self.latency_box.setFixedWidth(150)
        self.latency_box.setFixedHeight(32)
        self.latency_box.valueChanged.connect(self._on_latency_spinbox)
        _no_wheel(self.latency_box)
        lat_row.addWidget(self.latency_box)
        other_cl.addLayout(lat_row)

        thr_row = QHBoxLayout()
        thr_row.addWidget(BodyLabel("补偿阈值 (ms):", self))
        self.threshold_slider = QSlider(Qt.Orientation.Horizontal, self)
        self.threshold_slider.setRange(0, 5000)
        self.threshold_slider.setValue(1000)
        self.threshold_slider.valueChanged.connect(self._on_threshold_slider)
        _no_wheel(self.threshold_slider)
        thr_row.addWidget(self.threshold_slider, 1)
        self.threshold_box = SpinBox(self)
        self.threshold_box.setRange(0, 5000)
        self.threshold_box.setValue(1000)
        self.threshold_box.setFixedWidth(150)
        self.threshold_box.setFixedHeight(32)
        self.threshold_box.valueChanged.connect(self._on_threshold_spinbox)
        _no_wheel(self.threshold_box)
        thr_row.addWidget(self.threshold_box)
        other_cl.addLayout(thr_row)

        buf_row = QHBoxLayout()
        buf_row.addWidget(BodyLabel("回退缓冲 (ms):", self))
        self.buffer_slider = QSlider(Qt.Orientation.Horizontal, self)
        self.buffer_slider.setRange(0, 500)
        self.buffer_slider.setValue(0)
        self.buffer_slider.valueChanged.connect(self._on_buffer_slider)
        _no_wheel(self.buffer_slider)
        buf_row.addWidget(self.buffer_slider, 1)
        self.buffer_box = SpinBox(self)
        self.buffer_box.setRange(0, 500)
        self.buffer_box.setValue(0)
        self.buffer_box.setFixedWidth(150)
        self.buffer_box.setFixedHeight(32)
        self.buffer_box.valueChanged.connect(self._on_buffer_spinbox)
        _no_wheel(self.buffer_box)
        buf_row.addWidget(self.buffer_box)
        other_cl.addLayout(buf_row)

        alt_row = QHBoxLayout()
        alt_row.addWidget(BodyLabel("Alt+Tab 释放居中:", self))
        alt_row.addStretch(1)
        self.alt_center_switch = SwitchButton(self)
        self.alt_center_switch.setChecked(False)
        self.alt_center_switch.checkedChanged.connect(self._on_alt_center_toggle)
        alt_row.addWidget(self.alt_center_switch)
        other_cl.addLayout(alt_row)



        clear_btn = PushButton("清除配置数据", self)
        clear_btn.setFixedHeight(32)
        clear_btn.clicked.connect(self._clear_data)
        other_cl.addWidget(clear_btn)

        root.addWidget(other_section)
        root.addStretch(1)

        # ── 默认折叠曲线设置和其他设置 ──
        curve_section.collapse()
        other_section.collapse()

        # ── 应用初始预设 ──
        self._apply_preset(CURVE_LINEAR)

        scroll = QScrollArea(self)
        scroll.setWidget(content)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        scroll.viewport().setAutoFillBackground(False)
        scroll.viewport().setStyleSheet("background: transparent; border: none;")
        self.stackedWidget.addWidget(scroll)

    # ──────────────────────── 带滑块的参数行 ────────────────────────
    def _add_param_row(self, parent, label, key, slider_max, default, step, val_type):
        row = QHBoxLayout()
        row.addWidget(BodyLabel(label, self))

        slider = QSlider(Qt.Orientation.Horizontal, self)
        slider.setRange(0, slider_max)
        slider.setValue(default if val_type is int else int(default * 100))
        slider.valueChanged.connect(lambda v, k=key: self._on_slider_changed(k, v))
        _no_wheel(slider)
        row.addWidget(slider, 1)

        if val_type is float:
            box = DoubleSpinBox(self)
            box.setDecimals(2)
            box.setRange(0.0, 1000000.0)
            box.setSingleStep(step)
        else:
            box = SpinBox(self)
            box.setRange(0, 1000000)
            box.setSingleStep(int(step))
        box.setValue(default)
        _no_wheel(box)
        box.setFixedHeight(32)
        box.setFixedWidth(150)
        box.valueChanged.connect(lambda v, k=key: self._on_spinbox_changed(k, v))
        row.addWidget(box)
        parent.addLayout(row)

        setattr(self, f'_slider_{key}', slider)
        setattr(self, f'_input_{key}', box)
        setattr(self, f'_slider_max_{key}', slider_max)
        setattr(self, f'_val_type_{key}', val_type)

    def _on_slider_changed(self, key, value):
        box = getattr(self, f'_input_{key}')
        box.blockSignals(True)
        if getattr(self, f'_val_type_{key}') is float:
            box.setValue(value / 100.0)
        else:
            box.setValue(value)
        box.blockSignals(False)
        self._update_curve_params()

    def _on_spinbox_changed(self, key, value):
        slider = getattr(self, f'_slider_{key}')
        slider.blockSignals(True)
        if getattr(self, f'_val_type_{key}') is float:
            slider.setValue(int(value * 100))
        else:
            slider.setValue(int(value))
        slider.blockSignals(False)
        self._update_curve_params()

    # ──────────────────────── 预设切换 ────────────────────────
    def _on_preset_changed(self, index):
        keys = [CURVE_LINEAR, CURVE_TRADITIONAL, CURVE_HIGH_SPEED]
        self._apply_preset(keys[index])

    def _apply_preset(self, curve_type):
        preset = CURVE_PRESETS[curve_type]
        self.emulator.curve_type = curve_type

        for key in ('start_speed', 'deadzone', 'max_time', 'max_speed', 'intensity'):
            val = preset[key]
            box = getattr(self, f'_input_{key}')
            slider = getattr(self, f'_slider_{key}')
            box.blockSignals(True)
            slider.blockSignals(True)
            box.setValue(int(val) if key in ('start_speed', 'max_speed') else val)
            if key in ('start_speed', 'max_speed'):
                slider.setValue(int(val))
            else:
                slider.setValue(int(val * 100))
            box.blockSignals(False)
            slider.blockSignals(False)

        self._sync_emulator()
        self.curve_widget.set_params(
            curve_type,
            preset['deadzone'], preset['max_time'],
            preset['start_speed'], preset['max_speed'], preset['intensity'],
        )

    # ──────────────────────── 参数同步 ────────────────────────
    def _update_curve_params(self):
        self._sync_emulator()
        self.curve_widget.set_params(
            self.emulator.curve_type,
            self._input_deadzone.value(), self._input_max_time.value(),
            self._input_start_speed.value(), self._input_max_speed.value(),
            self._input_intensity.value(),
        )

    def _sync_emulator(self):
        self.emulator.start_speed = float(self._input_start_speed.value())
        self.emulator.deadzone = float(self._input_deadzone.value())
        self.emulator.max_time = float(self._input_max_time.value())
        self.emulator.max_speed = float(self._input_max_speed.value())
        self.emulator.intensity = float(self._input_intensity.value())
        self.emulator.scroll_step = int(self.scroll_step_box.value())
        self.emulator.latency_ms = int(self.latency_box.value())
        self.emulator.comp_buffer_ms = int(self.buffer_box.value())
        self.emulator.latency_threshold_ms = int(self.threshold_box.value())

    def _on_latency_slider(self, value):
        self.latency_box.blockSignals(True)
        self.latency_box.setValue(value)
        self.latency_box.blockSignals(False)
        self.emulator.latency_ms = value

    def _on_latency_spinbox(self, value):
        self.latency_slider.blockSignals(True)
        self.latency_slider.setValue(value)
        self.latency_slider.blockSignals(False)
        self.emulator.latency_ms = value

    def _on_buffer_slider(self, value):
        self.buffer_box.blockSignals(True)
        self.buffer_box.setValue(value)
        self.buffer_box.blockSignals(False)
        self.emulator.comp_buffer_ms = value

    def _on_buffer_spinbox(self, value):
        self.buffer_slider.blockSignals(True)
        self.buffer_slider.setValue(value)
        self.buffer_slider.blockSignals(False)
        self.emulator.comp_buffer_ms = value

    def _on_threshold_slider(self, value):
        self.threshold_box.blockSignals(True)
        self.threshold_box.setValue(value)
        self.threshold_box.blockSignals(False)
        self.emulator.latency_threshold_ms = value

    def _on_threshold_spinbox(self, value):
        self.threshold_slider.blockSignals(True)
        self.threshold_slider.setValue(value)
        self.threshold_slider.blockSignals(False)
        self.emulator.latency_threshold_ms = value

    def _open_calibration(self):
        if hasattr(self, '_calibration_win') and self._calibration_win.isVisible():
            self._calibration_win.raise_()
            self._calibration_win.activateWindow()
            return
        self._calibration_win = LatencyCalibrationWindow(
            callback=lambda v: self.latency_box.setValue(v))
        self._calibration_win.show()

    def _poll_hint_state(self):
        if not self.hint_switch.isChecked():
            if self._floating_hint.isVisible():
                self._floating_hint.hide()
            return
        em = self.emulator
        if em.enabled and (em.is_mod_pressed or em.mod_toggled) and em.mod_mode != 'capslock':
            if not self._floating_hint.isVisible():
                self._floating_hint.show()
            self._floating_hint.reposition()
        else:
            if self._floating_hint.isVisible():
                self._floating_hint.hide()

    def _poll_curve_state(self):
        em = self.emulator
        if em.enabled and em.is_mod_pressed and em.active_directions:
            self.curve_widget.set_current(em._time_held, em._current_speed)
        else:
            self.curve_widget.reset_current()

    # ──────────────────────── 开关 ────────────────────────
    def _toggle_emulator(self, checked):
        self.emulator.enabled = checked
        self.tray_toggle_action.setChecked(checked)
        self.tray_toggle_action.setText('启用映射' if checked else '关闭映射')
        self._update_capslock_ui()
        self._save_config()

    def _update_exclusive_mod(self, checked):
        self.emulator.exclusive_mod = checked

    def _update_mod_mode(self, index):
        modes = ['hold', 'toggle', 'hybrid', 'capslock']
        self.emulator.mod_mode = modes[index]
        if modes[index] != 'hybrid':
            self.emulator.mod_toggled = False
        self._update_capslock_ui()

    def _update_capslock_ui(self):
        """根据当前模式更新 UI 状态"""
        is_capslock_mode = self.emulator.mod_mode == 'capslock'
        # 大写锁模式下禁用组合键按钮
        if 'mod' in self.key_buttons:
            self.key_buttons['mod'].setEnabled(not is_capslock_mode)

    def _poll_capslock_state(self):
        """定时检查大写锁状态"""
        if self.emulator.mod_mode != 'capslock' or not self.emulator.enabled:
            return
        caps_on = self.emulator.is_capslock_on()
        if caps_on != self.emulator.is_mod_pressed:
            self.emulator.is_mod_pressed = caps_on
            if not caps_on:
                self._safe_release_mouse()

    def _center_cursor(self):
        try:
            user32 = ctypes.windll.user32
            hwnd = user32.GetForegroundWindow()
            rect = ctypes.wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            x = (rect.left + rect.right) // 2
            y = (rect.top + rect.bottom) // 2
            self.emulator.mouse_ctrl.position = (x, y)
        except Exception:
            pass

    def _on_alt_center_toggle(self, checked):
        pass



    # ──────────────────────── 按键绑定 UI ────────────────────────
    def _create_key_btn(self, parent_layout, label_text, target_id, default_val):
        row = QHBoxLayout()
        row.addWidget(BodyLabel(label_text, self))
        btn = PushButton(str(default_val).upper(), self)
        btn.setFixedWidth(100)
        btn.setFixedHeight(32)
        btn.clicked.connect(lambda _=False, tid=target_id: self._start_recording(tid))
        self.key_buttons[target_id] = btn

        btn2 = PushButton('未设置', self)
        btn2.setFixedWidth(100)
        btn2.setFixedHeight(32)
        btn2.clicked.connect(lambda _=False, tid=target_id + '2': self._start_recording(tid))
        self.key_buttons[target_id + '2'] = btn2

        row.addStretch(1)
        row.addWidget(btn)
        row.addWidget(btn2)
        parent_layout.addLayout(row)

    # ══════════════════════════ 按键录制 ══════════════════════════
    def _start_recording(self, target_id):
        self.recording_target = target_id
        self.key_buttons[target_id].setText("正在录制...")
        self.key_buttons[target_id].clearFocus()

    def _handle_key_recorded(self, target_id, key_id, vk):
        if key_id is None:
            self.key_buttons[target_id].setText("录制失败")
            self._save_config()
            return

        is_esc = key_id == 'esc'
        is_secondary = target_id.endswith('2')
        base_id = target_id[:-1] if is_secondary else target_id

        if base_id == 'mod':
            if is_esc:
                if is_secondary:
                    key_id = ''
                    vk = None
                else:
                    key_id = 'menu'
                    vk = 93
            if key_id:
                self.emulator.mod_key_id = key_id
                if vk is not None:
                    self.emulator.mod_vk = vk
            self.key_buttons[target_id].setText(key_id.upper() if key_id else '未设置')
        elif is_secondary:
            if is_esc:
                self.emulator.keys_config2.pop(base_id, None)
                old_vk = self.emulator.vk_config2.pop(base_id, None)
                if old_vk:
                    self.emulator.vk_to_action2.pop(old_vk, None)
                self.key_buttons[target_id].setText('未设置')
            else:
                self.emulator.keys_config2[base_id] = key_id
                if vk is None and len(key_id) == 1:
                    vk = ord(key_id.upper())
                if vk is not None:
                    self.emulator.vk_config2[base_id] = vk
                    self.emulator.vk_to_action2[vk] = base_id
                self.key_buttons[target_id].setText(key_id.upper())
        else:
            if is_esc:
                self.emulator.keys_config[target_id] = ''
                self.emulator.vk_config.pop(target_id, None)
                self.emulator.vk_to_action = {v: k for k, v in self.emulator.vk_config.items()}
                self.key_buttons[target_id].setText('未设置')
            else:
                self.emulator.keys_config[target_id] = key_id
                if vk is None and len(key_id) == 1:
                    vk = ord(key_id.upper())
                if vk is not None:
                    self.emulator.vk_config[target_id] = vk
                    self.emulator.vk_to_action = {v: k for k, v in self.emulator.vk_config.items()}
                self.key_buttons[target_id].setText(key_id.upper())
        self._save_config()

    # ══════════════════════════ 键盘监听 ══════════════════════════
    def _init_listener(self):
        kwargs = {'on_press': self._on_press, 'on_release': self._on_release}
        if sys.platform == 'win32':
            kwargs['win32_event_filter'] = self._win32_event_filter
        self.listener = keyboard.Listener(**kwargs)
        self.listener.start()

    def _win32_event_filter(self, msg, data):
        if self.recording_target:
            return True
        if not self.emulator.enabled:
            return True

        vk = data.vkCode
        is_press = msg in (256, 260)
        is_release = msg in (257, 261)

        # ── 追踪当前按下的键 ──
        if is_press:
            self.emulator._keys_held.add(vk)
        elif is_release:
            self.emulator._keys_held.discard(vk)

        # ── Alt+Tab 跟踪（仅在启动键按下时）──
        if self.emulator.is_mod_pressed and self.alt_center_switch.isChecked():
            if vk in (18, 164, 165) and is_press:
                self._alt_held = True
                self._alt_tab_used = False
            elif vk == 9 and is_press and self._alt_held:
                self._alt_tab_used = True
            elif vk in (18, 164, 165) and is_release:
                self._alt_held = False

        # 大写锁模式下，跳过组合键处理，直接检查方向键
        if self.emulator.mod_mode == 'capslock':
            # 不抑制大写锁按键本身
            if vk == 0x14:  # VK_CAPITAL
                return True
            if self.emulator.is_mod_pressed:
                action = self.emulator.vk_to_action.get(vk) or self.emulator.vk_to_action2.get(vk)
                if action:
                    if is_press:
                        self._trigger_action_press(action)
                    elif is_release:
                        self._trigger_action_release(action)
                self.listener.suppress_event()
            return True

        if vk == self.emulator.mod_vk:
            if self.emulator.mod_mode == 'toggle':
                if is_press:
                    self.emulator.mod_toggled = not self.emulator.mod_toggled
                    self.emulator.is_mod_pressed = self.emulator.mod_toggled
                    if not self.emulator.mod_toggled:
                        self._safe_release_mouse()
                self.listener.suppress_event()
            elif self.emulator.mod_mode == 'hybrid':
                HYBRID_THRESHOLD = 0.5
                if is_press:
                    self.emulator.is_mod_pressed = True
                    self.emulator._mod_used = False
                    self.emulator._mod_press_time = time.time()
                    self.listener.suppress_event()
                elif is_release:
                    held = time.time() - self.emulator._mod_press_time
                    if held < HYBRID_THRESHOLD:
                        self.emulator.mod_toggled = not self.emulator.mod_toggled
                        self.emulator.is_mod_pressed = self.emulator.mod_toggled
                        if not self.emulator.mod_toggled:
                            self._safe_release_mouse()
                    else:
                        self.emulator.mod_toggled = False
                        self.emulator.is_mod_pressed = False
                        self._safe_release_mouse()
                    self.listener.suppress_event()
            else:
                # 按住模式：按下立即抑制，0.2s 内无动作则注入原生单击
                TAP_THRESHOLD = 0.2
                if is_press:
                    self.emulator.is_mod_pressed = True
                    self.emulator._mod_used = False
                    self.emulator._mod_press_time = time.time()
                    self.listener.suppress_event()
                elif is_release:
                    held = time.time() - self.emulator._mod_press_time
                    self.emulator.is_mod_pressed = False
                    self._safe_release_mouse()
                    if held < TAP_THRESHOLD and not self.emulator._mod_used:
                        self._inject_modifier_tap()
                    else:
                        self.listener.suppress_event()
            return True

        if self.emulator.is_mod_pressed:
            # 检查退出组合键
            if vk in (self.emulator.vk_config.get('exit_mod'), self.emulator.vk_config2.get('exit_mod')):
                self.emulator.mod_toggled = False
                self.emulator.is_mod_pressed = False
                self._safe_release_mouse()
                self.listener.suppress_event()
                return True

            action = self.emulator.vk_to_action.get(vk) or self.emulator.vk_to_action2.get(vk)
            if action:
                if is_press:
                    self._trigger_action_press(action)
                elif is_release:
                    self._trigger_action_release(action)
                self.listener.suppress_event()
                return True

        return True

    def _on_press(self, key):
        vk = self._get_vk(key)
        key_id = self._get_key_id(key)

        if self.recording_target:
            if key_id != self.emulator.mod_key_id:
                self.key_recorded_signal.emit(self.recording_target, key_id, vk)
                self.recording_target = None
            return

        if not self.emulator.enabled:
            return

        # 大写锁模式下，跳过组合键处理
        if self.emulator.mod_mode == 'capslock':
            if not self.emulator.is_mod_pressed:
                return
            if sys.platform == 'win32':
                return
            action = self._get_action_by_key_id(key_id)
            if action:
                self._trigger_action_press(action)
            return

        if self.emulator.is_mod_pressed and key_id in (
            self.emulator.keys_config.get('exit_mod'),
            self.emulator.keys_config2.get('exit_mod'),
        ):
            self.emulator.mod_toggled = False
            self.emulator.is_mod_pressed = False
            self._safe_release_mouse()
            return

        if key_id == self.emulator.mod_key_id:
            if self.emulator.mod_mode == 'toggle':
                self.emulator.mod_toggled = not self.emulator.mod_toggled
                self.emulator.is_mod_pressed = self.emulator.mod_toggled
                if not self.emulator.mod_toggled:
                    self._safe_release_mouse()
            elif self.emulator.mod_mode == 'hybrid':
                self.emulator.is_mod_pressed = True
                self.emulator._mod_used = False
                self.emulator._mod_press_time = time.time()
            else:
                self.emulator.is_mod_pressed = True
        if not self.emulator.is_mod_pressed:
            return
        if sys.platform == 'win32':
            return

        action = self._get_action_by_key_id(key_id)
        if action:
            self._trigger_action_press(action)

    def _on_release(self, key):
        key_id = self._get_key_id(key)

        # Alt 释放 -> 窗口居中
        if key_id in ('alt', 'alt_l', 'alt_r', 'alt_gr') and self.alt_center_switch.isChecked() and self._alt_tab_used:
            self._alt_tab_used = False
            QTimer.singleShot(100, self._center_cursor)

        # 大写锁模式下，跳过组合键处理
        if self.emulator.mod_mode == 'capslock':
            if sys.platform == 'win32':
                return
            action = self._get_action_by_key_id(key_id)
            if action:
                self._trigger_action_release(action)
            return

        if key_id == self.emulator.mod_key_id:
            if self.emulator.mod_mode == 'toggle':
                return
            elif self.emulator.mod_mode == 'hybrid':
                HYBRID_THRESHOLD = 0.5
                held = time.time() - self.emulator._mod_press_time
                if held < HYBRID_THRESHOLD:
                    self.emulator.mod_toggled = not self.emulator.mod_toggled
                    self.emulator.is_mod_pressed = self.emulator.mod_toggled
                    if not self.emulator.mod_toggled:
                        self._safe_release_mouse()
                else:
                    self.emulator.mod_toggled = False
                    self.emulator.is_mod_pressed = False
                    self._safe_release_mouse()
                return
            self.emulator.is_mod_pressed = False
            self._safe_release_mouse()
            return
        if sys.platform == 'win32':
            return

        action = self._get_action_by_key_id(key_id)
        if action:
            self._trigger_action_release(action)

    # ══════════════════════════ 动作触发 ══════════════════════════
    def _trigger_action_press(self, action):
        self.emulator._mod_used = True
        if action in ('up', 'down', 'left', 'right'):
            self.emulator.active_directions.add(action)
        elif action == 'click_l' and not self.emulator.is_left_pressed:
            self.emulator.is_left_pressed = True
            self.emulator.mouse_ctrl.press(mouse.Button.left)
        elif action == 'click_r' and not self.emulator.is_right_pressed:
            self.emulator.is_right_pressed = True
            self.emulator.mouse_ctrl.press(mouse.Button.right)
        elif action == 'scroll_up':
            self.emulator.mouse_ctrl.scroll(0, self.emulator.scroll_step)
        elif action == 'scroll_down':
            self.emulator.mouse_ctrl.scroll(0, -self.emulator.scroll_step)
        elif action == 'back' and not self.emulator.is_back_pressed:
            self.emulator.is_back_pressed = True
            self.emulator.mouse_ctrl.press(mouse.Button.x1)
        elif action == 'forward' and not self.emulator.is_forward_pressed:
            self.emulator.is_forward_pressed = True
            self.emulator.mouse_ctrl.press(mouse.Button.x2)
        elif action == 'center_window':
            self._center_cursor()

    def _trigger_action_release(self, action):
        if action in ('up', 'down', 'left', 'right'):
            self.emulator.active_directions.discard(action)
        elif action == 'click_l' and self.emulator.is_left_pressed:
            self.emulator.mouse_ctrl.release(mouse.Button.left)
            self.emulator.is_left_pressed = False
        elif action == 'click_r' and self.emulator.is_right_pressed:
            self.emulator.mouse_ctrl.release(mouse.Button.right)
            self.emulator.is_right_pressed = False
        elif action == 'back' and self.emulator.is_back_pressed:
            self.emulator.mouse_ctrl.release(mouse.Button.x1)
            self.emulator.is_back_pressed = False
        elif action == 'forward' and self.emulator.is_forward_pressed:
            self.emulator.mouse_ctrl.release(mouse.Button.x2)
            self.emulator.is_forward_pressed = False

    def _safe_release_mouse(self):
        self.emulator.active_directions.clear()
        if self.emulator.is_left_pressed:
            self.emulator.mouse_ctrl.release(mouse.Button.left)
            self.emulator.is_left_pressed = False
        if self.emulator.is_right_pressed:
            self.emulator.mouse_ctrl.release(mouse.Button.right)
            self.emulator.is_right_pressed = False
        if self.emulator.is_back_pressed:
            self.emulator.mouse_ctrl.release(mouse.Button.x1)
            self.emulator.is_back_pressed = False
        if self.emulator.is_forward_pressed:
            self.emulator.mouse_ctrl.release(mouse.Button.x2)
            self.emulator.is_forward_pressed = False

    def _inject_modifier_tap(self):
        """注入原生修饰键单击"""
        try:
            from pynput.keyboard import Key, KeyCode
            vk = self.emulator.mod_vk
            if vk == 93:
                key = Key.menu
            elif vk in (18, 165, 164):
                key = Key.alt
            elif vk in (17, 163, 161):
                key = Key.ctrl
            elif vk in (16, 160, 161):
                key = Key.shift
            else:
                key = KeyCode.from_vk(vk)
            self._kb_ctrl.press(key)
            self._kb_ctrl.release(key)
        except Exception:
            pass

    # ══════════════════════════ 工具方法 ══════════════════════════
    @staticmethod
    def _get_key_id(key):
        if hasattr(key, 'name'):
            return key.name
        if hasattr(key, 'char') and key.char:
            return key.char.lower()
        return str(key).replace("'", "")

    @staticmethod
    def _get_vk(key):
        if hasattr(key, 'vk'):
            return key.vk
        if hasattr(key, 'value') and hasattr(key.value, 'vk'):
            return key.value.vk
        return None

    def _get_action_by_key_id(self, key_id):
        for action, mapped_id in self.emulator.keys_config.items():
            if mapped_id and mapped_id == key_id:
                return action
        for action, mapped_id in self.emulator.keys_config2.items():
            if mapped_id and mapped_id == key_id:
                return action
        return None

    # ══════════════════════════ 配置持久化 ══════════════════════════
    def _load_config(self):
        if not os.path.exists(CONFIG_PATH):
            self._apply_preset(CURVE_LINEAR)
            return
        try:
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
        except Exception:
            self._apply_preset(CURVE_LINEAR)
            return

        self.emulator.curve_type = cfg.get('curve_type', CURVE_LINEAR)
        idx = [CURVE_LINEAR, CURVE_TRADITIONAL, CURVE_HIGH_SPEED].index(
            self.emulator.curve_type)
        self.curve_combo.setCurrentIndex(idx)

        mod_mode = cfg.get('mod_mode', 'hold')
        self.emulator.mod_mode = mod_mode
        mode_index = {'hold': 0, 'toggle': 1, 'hybrid': 2, 'capslock': 3}.get(mod_mode, 0)
        self.mode_combo.setCurrentIndex(mode_index)
        self._update_capslock_ui()

        # ── 恢复开关状态 ──
        enabled = cfg.get('enabled', False)
        self.emulator.enabled = enabled
        self.enable_switch.blockSignals(True)
        self.enable_switch.setChecked(enabled)
        self.enable_switch.blockSignals(False)
        self.tray_toggle_action.setChecked(enabled)
        self.tray_toggle_action.setText('启用映射' if enabled else '关闭映射')

        excl = cfg.get('exclusive_mod', True)
        self.emulator.exclusive_mod = excl
        self.exclusive_switch.blockSignals(True)
        self.exclusive_switch.setChecked(excl)
        self.exclusive_switch.blockSignals(False)

        boot = cfg.get('boot', _check_boot_reg())
        self.boot_switch.blockSignals(True)
        self.boot_switch.setChecked(boot)
        self.boot_switch.blockSignals(False)

        hint = cfg.get('hint_enabled', True)
        self.hint_switch.blockSignals(True)
        self.hint_switch.setChecked(hint)
        self.hint_switch.blockSignals(False)

        for key in ('start_speed', 'deadzone', 'max_time', 'max_speed', 'intensity'):
            val = cfg.get(key, 0)
            box = getattr(self, f'_input_{key}')
            slider = getattr(self, f'_slider_{key}')
            box.blockSignals(True)
            slider.blockSignals(True)
            box.setValue(int(val) if key in ('start_speed', 'max_speed') else val)
            if key in ('start_speed', 'max_speed'):
                slider.setValue(int(val))
            else:
                slider.setValue(int(val * 100))
            box.blockSignals(False)
            slider.blockSignals(False)

        scroll = cfg.get('scroll_step', 3)
        self.scroll_step_box.blockSignals(True)
        self.scroll_step_box.setValue(scroll)
        self.scroll_step_box.blockSignals(False)

        latency = cfg.get('latency_ms', 0)
        self.latency_slider.blockSignals(True)
        self.latency_box.blockSignals(True)
        self.latency_slider.setValue(latency)
        self.latency_box.setValue(latency)
        self.latency_slider.blockSignals(False)
        self.latency_box.blockSignals(False)

        buf = cfg.get('comp_buffer_ms', 0)
        self.buffer_slider.blockSignals(True)
        self.buffer_box.blockSignals(True)
        self.buffer_slider.setValue(buf)
        self.buffer_box.setValue(buf)
        self.buffer_slider.blockSignals(False)
        self.buffer_box.blockSignals(False)

        thr = cfg.get('latency_threshold_ms', 1000)
        self.threshold_slider.blockSignals(True)
        self.threshold_box.blockSignals(True)
        self.threshold_slider.setValue(thr)
        self.threshold_box.setValue(thr)
        self.threshold_slider.blockSignals(False)
        self.threshold_box.blockSignals(False)

        alt = cfg.get('alt_center', False)
        self.alt_center_switch.blockSignals(True)
        self.alt_center_switch.setChecked(alt)
        self.alt_center_switch.blockSignals(False)

        self._sync_emulator()
        self._update_curve_params()

        # ── 恢复按键绑定 ──
        saved_keys = cfg.get('keys_config', {})
        for action, key_id in saved_keys.items():
            if action not in self.emulator.keys_config:
                self.emulator.keys_config[action] = ''
            if key_id:
                self.emulator.keys_config[action] = key_id
            btn = self.key_buttons.get(action)
            if btn:
                btn.setText(key_id.upper() if key_id else '未设置')
        saved_vks = cfg.get('vk_config', {})
        for action, vk in saved_vks.items():
            if vk:
                self.emulator.vk_config[action] = int(vk)
        self.emulator.vk_to_action = {v: k for k, v in self.emulator.vk_config.items()}
        mod_id = cfg.get('mod_key_id', 'menu')
        self.emulator.mod_key_id = mod_id
        self.emulator.mod_vk = cfg.get('mod_vk', 93)
        mod_btn = self.key_buttons.get('mod')
        if mod_btn:
            mod_btn.setText(mod_id.upper())

        keys2 = cfg.get('keys_config2', {})
        self.emulator.keys_config2 = dict(keys2)
        vks2 = cfg.get('vk_config2', {})
        self.emulator.vk_config2 = {k: int(v) for k, v in vks2.items() if v}
        self.emulator.vk_to_action2 = {v: k for k, v in self.emulator.vk_config2.items()}
        for action, key_id in keys2.items():
            btn = self.key_buttons.get(action + '2')
            if btn:
                btn.setText(key_id.upper())

    def _clear_data(self):
        """清除所有配置数据，恢复默认设置"""
        if os.path.exists(CONFIG_PATH):
            try:
                os.remove(CONFIG_PATH)
            except Exception:
                pass

        # 重置曲线
        self._apply_preset(CURVE_LINEAR)
        self.curve_combo.setCurrentIndex(0)

        # 重置触发模式
        self.emulator.mod_mode = 'hold'
        self.mode_combo.setCurrentIndex(0)
        self._update_capslock_ui()

        # 重置开关
        self.emulator.enabled = False
        self.enable_switch.blockSignals(True)
        self.enable_switch.setChecked(False)
        self.enable_switch.blockSignals(False)
        self.tray_toggle_action.setChecked(False)
        self.tray_toggle_action.setText('关闭映射')

        self.emulator.exclusive_mod = True
        self.exclusive_switch.blockSignals(True)
        self.exclusive_switch.setChecked(True)
        self.exclusive_switch.blockSignals(False)

        # 清除开机自启注册表
        self._toggle_boot(False)
        self.boot_switch.blockSignals(True)
        self.boot_switch.setChecked(False)
        self.boot_switch.blockSignals(False)

        # 重置浮空提示窗
        self.hint_switch.blockSignals(True)
        self.hint_switch.setChecked(True)
        self.hint_switch.blockSignals(False)

        # 重置组合键
        self.emulator.mod_key_id = 'menu'
        self.emulator.mod_vk = 93
        mod_btn = self.key_buttons.get('mod')
        if mod_btn:
            mod_btn.setText('MENU')

        # 重置自定义键
        default_keys = {
            'up': 'w', 'down': 's', 'left': 'a', 'right': 'd',
            'click_l': '[', 'click_r': ']',
            'scroll_up': 'p', 'scroll_down': ';',
            'center_window': 'c',
            'back': '-', 'forward': '=',
        }
        default_vks = {
            'up': 87, 'down': 83, 'left': 65, 'right': 68,
            'click_l': 219, 'click_r': 221,
            'scroll_up': 80, 'scroll_down': 186,
            'center_window': 67,
            'back': 189, 'forward': 187,
        }
        self.emulator.keys_config = dict(default_keys)
        self.emulator.vk_config = dict(default_vks)
        self.emulator.vk_to_action = {v: k for k, v in default_vks.items()}
        for action_id, key_id in default_keys.items():
            btn = self.key_buttons.get(action_id)
            if btn:
                btn.setText(key_id.upper())

        # 重置备用按键
        self.emulator.keys_config2.clear()
        self.emulator.vk_config2.clear()
        self.emulator.vk_to_action2.clear()
        for action_id in list(default_keys) + ['exit_mod']:
            btn2 = self.key_buttons.get(action_id + '2')
            if btn2:
                btn2.setText('未设置')

        # 重置退出组合键
        self.emulator.keys_config.pop('exit_mod', None)
        self.emulator.vk_config.pop('exit_mod', None)
        btn_exit = self.key_buttons.get('exit_mod')
        if btn_exit:
            btn_exit.setText('未设置')

        # 重置滚轮步进
        self.emulator.scroll_step = 3
        self.scroll_step_box.blockSignals(True)
        self.scroll_step_box.setValue(3)
        self.scroll_step_box.blockSignals(False)

        self.emulator.latency_ms = 0
        self.latency_slider.blockSignals(True)
        self.latency_box.blockSignals(True)
        self.latency_slider.setValue(0)
        self.latency_box.setValue(0)
        self.latency_slider.blockSignals(False)
        self.latency_box.blockSignals(False)

        self.emulator.comp_buffer_ms = 0
        self.buffer_slider.blockSignals(True)
        self.buffer_box.blockSignals(True)
        self.buffer_slider.setValue(0)
        self.buffer_box.setValue(0)
        self.buffer_slider.blockSignals(False)
        self.buffer_box.blockSignals(False)

        self.emulator.latency_threshold_ms = 1000
        self.threshold_slider.blockSignals(True)
        self.threshold_box.blockSignals(True)
        self.threshold_slider.setValue(1000)
        self.threshold_box.setValue(1000)
        self.threshold_slider.blockSignals(False)
        self.threshold_box.blockSignals(False)

        self.alt_center_switch.blockSignals(True)
        self.alt_center_switch.setChecked(False)
        self.alt_center_switch.blockSignals(False)

        self._sync_emulator()
        self._update_curve_params()
        self._save_config()

    def _save_config(self):
        cfg = {
            'curve_type': self.emulator.curve_type,
            'mod_mode': self.emulator.mod_mode,
            'enabled': self.emulator.enabled,
            'exclusive_mod': self.emulator.exclusive_mod,
            'boot': self.boot_switch.isChecked(),
            'mod_key_id': self.emulator.mod_key_id,
            'mod_vk': self.emulator.mod_vk,
            'keys_config': dict(self.emulator.keys_config),
            'vk_config': {k: int(v) for k, v in self.emulator.vk_config.items() if v is not None},
            'keys_config2': dict(self.emulator.keys_config2),
            'vk_config2': {k: int(v) for k, v in self.emulator.vk_config2.items() if v is not None},
            'start_speed': self._input_start_speed.value(),
            'deadzone': self._input_deadzone.value(),
            'max_time': self._input_max_time.value(),
            'max_speed': self._input_max_speed.value(),
            'intensity': self._input_intensity.value(),
            'scroll_step': self.scroll_step_box.value(),
            'latency_ms': self.latency_box.value(),
            'comp_buffer_ms': self.buffer_box.value(),
            'latency_threshold_ms': self.threshold_box.value(),
            'alt_center': self.alt_center_switch.isChecked(),
            'hint_enabled': self.hint_switch.isChecked(),
        }
        try:
            with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
                json.dump(cfg, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    # ══════════════════════════ 开机启动（注册表） ══════════════════════════
    def _toggle_boot(self, checked):
        import winreg
        key_path = r'Software\Microsoft\Windows\CurrentVersion\Run'
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0,
                                 winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE)
        except Exception:
            key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path)
        try:
            if checked:
                exe = sys.executable
                winreg.SetValueEx(key, 'MouseController', 0, winreg.REG_SZ, exe)
            else:
                try:
                    winreg.DeleteValue(key, 'MouseController')
                except FileNotFoundError:
                    pass
            winreg.CloseKey(key)
        except Exception:
            winreg.CloseKey(key)
            self.boot_switch.setChecked(not checked)

    # ══════════════════════════ 系统托盘 ══════════════════════════
    def _init_tray(self):
        self.tray = QSystemTrayIcon(self)
        self.tray.setIcon(QIcon(ICON_PATH))
        self.tray.setToolTip('键盘鼠标模拟器')

        menu = QMenu()

        self.tray_toggle_action = QAction('启用映射', menu)
        self.tray_toggle_action.setCheckable(True)
        self.tray_toggle_action.setChecked(False)
        self.tray_toggle_action.triggered.connect(self._tray_toggle)
        menu.addAction(self.tray_toggle_action)

        menu.addSeparator()

        show_action = QAction('打开主界面', menu)
        show_action.triggered.connect(self._tray_show)
        menu.addAction(show_action)

        quit_action = QAction('退出', menu)
        quit_action.triggered.connect(self._tray_quit)
        menu.addAction(quit_action)

        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._tray_activated)
        self.tray.show()

    def _tray_toggle(self, checked):
        self.emulator.enabled = checked
        self.enable_switch.blockSignals(True)
        self.enable_switch.setChecked(checked)
        self.enable_switch.blockSignals(False)
        self._update_capslock_ui()
        self._save_config()

    def _tray_show(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._tray_show()

    def _tray_quit(self):
        self._save_config()
        self._curve_timer.stop()
        self._capslock_timer.stop()
        self._hint_timer.stop()
        self._floating_hint.hide()
        self.emulator.stop()
        self.listener.stop()
        self.tray.hide()
        QApplication.quit()

    # ══════════════════════════ 生命周期 ══════════════════════════
    def closeEvent(self, event):
        self._save_config()
        self.hide()
        event.ignore()  # 关闭窗口 → 最小化到托盘

    def mousePressEvent(self, event):
        w = QApplication.focusWidget()
        if w:
            w.clearFocus()
        super().mousePressEvent(event)
