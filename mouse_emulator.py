"""鼠标模拟线程 — 曲线速度系统 + 平滑移动 + 拖拽状态"""
import time
import math
import ctypes
from PyQt6.QtCore import QThread
from pynput import mouse

# ══════════════════════════ 曲线类型常量 ══════════════════════════
CURVE_LINEAR = 'linear'
CURVE_TRADITIONAL = 'traditional'
CURVE_HIGH_SPEED = 'high_speed'

CURVE_LABELS = {
    CURVE_LINEAR: '线性',
    CURVE_TRADITIONAL: '传统',
    CURVE_HIGH_SPEED: '高速',
}

CURVE_PRESETS = {
    CURVE_LINEAR:       {'start_speed': 0,   'intensity': 1.0, 'deadzone': 0.0, 'max_time': 1.5, 'max_speed': 1000},
    CURVE_TRADITIONAL:  {'start_speed': 50,  'intensity': 3.0, 'deadzone': 0.0, 'max_time': 2.0, 'max_speed': 1200},
    CURVE_HIGH_SPEED:   {'start_speed': 200, 'intensity': 3.0, 'deadzone': 0.0, 'max_time': 0.8, 'max_speed': 1500},
}


def calc_curve_speed(curve_type, held_time, deadzone, max_time, start_speed, max_speed, intensity):
    """根据曲线类型计算当前速度

    :param curve_type:   'linear' / 'traditional' / 'high_speed'
    :param held_time:    当前按下时长（秒）
    :param deadzone:     死区时间（秒），死区内速度为 0
    :param max_time:     达到最大速度的时间（秒）
    :param start_speed:  启动速度 (px/s)
    :param max_speed:    最大速度 (px/s)
    :param intensity:    曲线强度 (>1 曲线更弯)
    """
    if held_time <= deadzone:
        return 0.0

    effective = (held_time - deadzone) / max(max_time - deadzone, 0.01)
    t = min(effective, 1.0)

    if curve_type == CURVE_LINEAR:
        factor = t
    elif curve_type == CURVE_TRADITIONAL:
        factor = t ** intensity
    elif curve_type == CURVE_HIGH_SPEED:
        factor = 1.0 - (1.0 - t) ** intensity
    else:
        factor = t

    return start_speed + (max_speed - start_speed) * factor


class MouseEmulatorThread(QThread):
    """后台鼠标控制线程"""

    def __init__(self):
        super().__init__()
        self.mouse_ctrl = mouse.Controller()

        self.running = True
        self.enabled = False
        self.exclusive_mod = True
        self.mod_mode = 'hold'
        self.caps_as_mod = False   # 大写锁作为启动键

        # ── 键名配置 ──
        self.mod_key_id = 'menu'
        self.keys_config = {
            'up': 'w', 'down': 's', 'left': 'a', 'right': 'd',
            'click_l': '[', 'click_r': ']',
            'scroll_up': 'p', 'scroll_down': ';',
            'center_window': 'c',
            'back': '-', 'forward': '=',
        }

        # ── 底层虚拟键码配置 ──
        self.mod_vks = [93]  # 组合键列表（AND 逻辑）
        self.vk_config = {
            'up': 87, 'down': 83, 'left': 65, 'right': 68,
            'click_l': 219, 'click_r': 221,
            'scroll_up': 80, 'scroll_down': 186,
            'center_window': 67,
            'back': 189, 'forward': 187,
        }
        self.vk_to_action = {v: k for k, v in self.vk_config.items()}

        self.active_directions = set()
        self._keys_held = set()   # 当前按下的 vk
        self.is_mod_pressed = False
        self.mod_toggled = False
        self.is_left_pressed = False
        self.is_right_pressed = False
        self.is_back_pressed = False
        self.is_forward_pressed = False

        # ── 曲线参数（默认线性） ──
        self.curve_type = CURVE_LINEAR
        self.deadzone = 0.0
        self.max_time = 1.5
        self.start_speed = 0.0
        self.max_speed = 1000.0
        self.intensity = 1.0
        self.scroll_step = 3
        self.latency_ms = 0   # 延迟补偿（毫秒），0 = 关闭
        self.comp_buffer_ms = 0  # 回退缓冲时间（毫秒），0 = 瞬移
        self.latency_threshold_ms = 1000  # 补偿阈值（毫秒），按下超过此时长才触发

        # ── 内部状态 ──
        self._current_speed = 0.0
        self._time_held = 0.0
        self._loop_delay = 0.01
        self._remainder_x = 0.0
        self._remainder_y = 0.0
        self._was_moving = False
        self._pos_history = []
        # ── 回退动画状态 ──
        self._comp_state = 'idle'  # 'idle' / 'active'
        self._comp_sx = 0.0
        self._comp_sy = 0.0
        self._comp_tx = 0.0
        self._comp_ty = 0.0
        self._comp_t0 = 0.0

    # ────────────────────────── 主循环 ──────────────────────────
    def run(self):
        while self.running:
            # ── 回退动画中 ──
            if self._comp_state == 'active':
                if self.active_directions or self.is_left_pressed or self.is_right_pressed:
                    self._comp_state = 'idle'
                else:
                    self._tick_compensation()
                time.sleep(self._loop_delay)
                continue

            if not self.enabled or not self.is_mod_pressed or not self.active_directions:
                if self._was_moving and self.latency_ms > 0 and self._time_held * 1000 >= self.latency_threshold_ms:
                    if self.comp_buffer_ms > 0:
                        self._start_compensation()
                    else:
                        self._compensate_latency()
                self._was_moving = False
                self._reset_state()
                time.sleep(self._loop_delay)
                continue

            self._was_moving = True
            self._pos_history.append((time.time(), *self.mouse_ctrl.position))

            self._time_held += self._loop_delay
            self._current_speed = calc_curve_speed(
                self.curve_type, self._time_held,
                self.deadzone, self.max_time, self.start_speed, self.max_speed, self.intensity,
            )

            dx, dy = self._calc_direction()
            if dx != 0 or dy != 0:
                self._move(dx, dy)

            time.sleep(self._loop_delay)

    # ────────────────────────── 内部方法 ──────────────────────────
    def _reset_state(self):
        self._current_speed = 0.0
        self._time_held = 0.0
        self._remainder_x = 0.0
        self._remainder_y = 0.0
        self._pos_history.clear()

    def _calc_direction(self):
        dx, dy = 0, 0
        if 'up' in self.active_directions:    dy -= 1
        if 'down' in self.active_directions:  dy += 1
        if 'left' in self.active_directions:  dx -= 1
        if 'right' in self.active_directions: dx += 1
        return dx, dy

    def _move(self, dx, dy):
        length = math.sqrt(dx ** 2 + dy ** 2)
        dx /= length
        dy /= length

        exact_x = dx * self._current_speed * self._loop_delay + self._remainder_x
        exact_y = dy * self._current_speed * self._loop_delay + self._remainder_y

        step_x = int(exact_x)
        step_y = int(exact_y)

        self._remainder_x = exact_x - step_x
        self._remainder_y = exact_y - step_y

        if step_x != 0 or step_y != 0:
            ctypes.windll.user32.ShowCursor(True)
            self.mouse_ctrl.move(step_x, step_y)

    # ────────────────────────── 延迟补偿 ──────────────────────────
    def _compensate_latency(self):
        if not self._pos_history:
            return
        target_time = time.time() - self.latency_ms / 1000.0
        best = self._pos_history[0]
        for entry in self._pos_history:
            if entry[0] <= target_time:
                best = entry
            else:
                break
        self.mouse_ctrl.position = (best[1], best[2])
        self._pos_history.clear()

    def _start_compensation(self):
        if not self._pos_history:
            return
        target_time = time.time() - self.latency_ms / 1000.0
        best = self._pos_history[0]
        for entry in self._pos_history:
            if entry[0] <= target_time:
                best = entry
            else:
                break
        self._comp_sx, self._comp_sy = self.mouse_ctrl.position
        self._comp_tx = best[1]
        self._comp_ty = best[2]
        self._comp_t0 = time.time()
        self._comp_state = 'active'
        self._pos_history.clear()

    def _tick_compensation(self):
        elapsed_ms = (time.time() - self._comp_t0) * 1000.0
        if elapsed_ms >= self.comp_buffer_ms:
            self.mouse_ctrl.position = (self._comp_tx, self._comp_ty)
            self._comp_state = 'idle'
        else:
            t = elapsed_ms / self.comp_buffer_ms
            x = self._comp_sx + (self._comp_tx - self._comp_sx) * t
            y = self._comp_sy + (self._comp_ty - self._comp_sy) * t
            self.mouse_ctrl.position = (int(x), int(y))

    # ────────────────────────── 大写锁状态 ──────────────────────────
    def is_capslock_on(self):
        try:
            return ctypes.windll.user32.GetKeyState(0x14) & 1
        except Exception:
            return False

    # ────────────────────────── 生命周期 ──────────────────────────
    def stop(self):
        if self.is_left_pressed:
            self.mouse_ctrl.release(mouse.Button.left)
        if self.is_right_pressed:
            self.mouse_ctrl.release(mouse.Button.right)
        if self.is_back_pressed:
            self.mouse_ctrl.release(mouse.Button.x1)
        if self.is_forward_pressed:
            self.mouse_ctrl.release(mouse.Button.x2)
        self.running = False
        self.wait()
