# 键盘鼠标模拟器 (MouseController)

通过键盘按键控制鼠标光标移动与点击的 Windows 桌面工具。

## 功能特性

- **键盘控制鼠标**：按住修饰键（默认 `Menu`）配合方向键移动光标，使用括号键执行左/右点击
- **鼠标侧键模拟**：支持前进/后退侧键映射
- **三种速度曲线**：
  - **线性** — 速度随时间匀速增加
  - **传统** — 慢启动后快速上升（幂曲线）
  - **高速** — 快速达到高速后趋于平稳
- **实时曲线可视化**：右侧面板实时绘制速度-时间曲线，动态显示当前速度点
- **四种触发模式**：
  - **按住** — 按住修饰键时生效
  - **切换** — 按一下修饰键开启/关闭
  - **混合** — 短按（< 0.5s）切换，长按（≥ 0.5s）按住
  - **大写锁定** — 利用 CapsLock 状态控制
- **延迟补偿**：校准键盘延迟，移动时自动补偿，支持"瞬间回正"与"平滑缓冲"两种模式
- **按键绑定自定义**：
  - 修饰键与所有动作键均可自由录制
  - 每个动作支持主/备用两组绑定
  - 录制时按 ESC 清空当前绑定
- **退出组合键**：可绑定任意按键，按下后立即退出切换/混合模式
- **智能按键穿透**：组合键激活时仅拦截已绑定的动作键，未绑定按键（含 Ctrl+C/V 等快捷键）正常通行
- **悬浮提示窗**：黑色半透明浮窗实时显示"鼠标控制"状态，60% 透明度，可穿透点击
- **系统托盘**：关闭窗口时最小化到托盘，后台持续运行
- **开机自启**：一键添加到 Windows 启动项
- **修饰键双击注入**：快速双击修饰键时注入原生按键事件，不影响其他软件使用

## 编译环境

### 依赖项

| 依赖 | 版本要求 |
|------|----------|
| Python | ≥ 3.10 |
| PyQt6 | 6.10.2 |
| qfluentwidgets | 1.11.2 |
| pynput | 1.8.2 |
| PyInstaller | 仅打包时需要 |

### 开发环境准备

```bash
# 使用 Conda 创建虚拟环境（推荐）
conda create -n pyqt_env python=3.10
conda activate pyqt_env

# 安装依赖（使用 requirements.txt）
pip install -r requirements.txt

# 打包（可选）
pip install pyinstaller
```

### 打包构建

运行 `build.bat` 或直接执行：

```batch
call conda activate pyqt_env
pyinstaller --noconsole --icon=icon.png --add-data "icon.png;." --name=MouseController --onefile --clean main.py
```

产物为 `dist/MouseController.exe`，单文件无控制台窗口。

### 项目结构

```
├── main.py                 # 程序入口
├── main_window.py          # 主窗口 UI + 键盘监听 + 配置持久化
├── mouse_emulator.py       # 鼠标模拟后台线程 + 速度曲线算法
├── curve_widget.py         # 速度曲线可视化控件
├── floating_hint.py        # 悬浮提示窗
├── collapsible_section.py  # 可折叠卡片容器
├── latency_calibration.py  # 键盘延迟校准工具
├── icon.png                # 应用图标
├── build.bat               # 一键打包脚本
└── MouseController.spec    # PyInstaller 配置文件
```
