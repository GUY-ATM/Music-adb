# -*- coding: utf-8 -*-
"""应用配置：读写 config.json，保持与原 Tkinter 版本完全一致的数据格式。"""

import json
import os
import sys

def app_dir():
    """程序所在目录：打包后为 exe 目录，开发时为项目根目录。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


CONFIG_PATH = os.path.join(app_dir(), "config.json")


def resource_path(name):
    """随程序打包的资源路径：打包后位于临时解包目录，开发时为项目根目录。"""
    return os.path.join(getattr(sys, "_MEIPASS", app_dir()), name)

# 鼠标按键标识 -> 显示名
BTN_LABEL = {
    "left": "左键",
    "right": "右键",
    "middle": "中键",
    "x1": "后退键(侧键)",
    "x2": "前进键(侧键)",
}

# 可绑定到切歌的鼠标按键。左键留作界面操作，禁止绑定，避免误捕获。
VALID_BUTTONS = ("x1", "x2", "middle", "right")

# 键盘绑定格式："vk:<虚拟键码>[+ctrl][+alt][+shift]"，例如 "vk:112"（F1）、"vk:65+ctrl"
MOD_CTRL = 1
MOD_ALT = 2
MOD_SHIFT = 4
BINDING_GUIDE = ("支持鼠标侧键/中键/右键，以及任意键盘按键（可带 Ctrl / Alt / Shift 组合）；"
                 "系统媒体键由媒体键通道自动识别，无需录制。")

# 修饰键自身的键码：录制时忽略，不单独作为绑定
MODIFIER_VKS = {
    0x10, 0x11, 0x12,        # Shift / Ctrl / Alt
    0x5B, 0x5C,              # Win 左右
    0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5,  # 左右 Shift / Ctrl / Alt
}


def _build_key_names():
    names = {
        0x08: "Backspace", 0x09: "Tab", 0x0D: "Enter", 0x13: "Pause",
        0x14: "CapsLock", 0x1B: "Esc", 0x20: "Space", 0x21: "PageUp",
        0x22: "PageDown", 0x23: "End", 0x24: "Home", 0x25: "←",
        0x26: "↑", 0x27: "→", 0x28: "↓", 0x2D: "Insert", 0x2E: "Delete",
        0x90: "NumLock", 0x91: "ScrollLock",
        0xBA: ";", 0xBB: "=", 0xBC: ",", 0xBD: "-", 0xBE: ".",
        0xBF: "/", 0xC0: "`", 0xDB: "[", 0xDC: "\\", 0xDD: "]", 0xDE: "'",
        0xB0: "媒体下一曲", 0xB1: "媒体上一曲",
        0xB2: "媒体停止", 0xB3: "媒体播放/暂停",
    }
    for i in range(10):
        names[0x30 + i] = str(i)           # 主键盘数字
        names[0x60 + i] = f"小键盘{i}"      # 小键盘数字
    for i in range(26):
        names[0x41 + i] = chr(0x41 + i)    # 字母
    for i in range(24):
        names[0x70 + i] = f"F{i + 1}"      # F1~F24
    return names


KEY_NAMES = _build_key_names()


def make_key_binding(vk, mods=0):
    """由虚拟键码与修饰位生成绑定字符串。"""
    suffix = ""
    if mods & MOD_CTRL:
        suffix += "+ctrl"
    if mods & MOD_ALT:
        suffix += "+alt"
    if mods & MOD_SHIFT:
        suffix += "+shift"
    return f"vk:{int(vk)}{suffix}"


def parse_key_binding(binding):
    """解析键盘绑定字符串，返回 (vk, mods)；非键盘绑定或非法时返回 None。"""
    if not isinstance(binding, str) or not binding.startswith("vk:"):
        return None
    parts = binding[3:].split("+")
    try:
        vk = int(parts[0])
    except (TypeError, ValueError):
        return None
    if not 0 < vk < 256:
        return None
    mods = 0
    for p in parts[1:]:
        p = p.strip().lower()
        if p == "ctrl":
            mods |= MOD_CTRL
        elif p == "alt":
            mods |= MOD_ALT
        elif p == "shift":
            mods |= MOD_SHIFT
        else:
            return None
    return vk, mods


def binding_display(binding):
    """绑定的可读名称：鼠标按键用中文名，键盘用「Ctrl+F1」形式。"""
    if binding in BTN_LABEL:
        return BTN_LABEL[binding]
    parsed = parse_key_binding(binding)
    if parsed:
        vk, mods = parsed
        names = [n for n, m in (("Ctrl", MOD_CTRL), ("Alt", MOD_ALT), ("Shift", MOD_SHIFT))
                 if mods & m]
        names.append(KEY_NAMES.get(vk, f"VK{vk}"))
        return "+".join(names)
    return str(binding)


def is_valid_binding(binding):
    """鼠标按键或可解析的键盘绑定都视为合法。"""
    return binding in VALID_BUTTONS or parse_key_binding(binding) is not None


DEFAULT_CONFIG = {
    "adb_path": "",          # 留空则自动查找
    "device": "",            # 设备序列号或 "ip:port"；USB 连接留空
    "prev_button": "x1",     # 上一曲绑定：鼠标按键标识或 vk:xx
    "next_button": "x2",     # 下一曲绑定：鼠标按键标识或 vk:xx
    "swallow_bound": False,  # 拦截已绑定的按键，避免浏览器后退/前进
    "swallow_media_keys": False,  # 拦截媒体键，避免被其它音乐软件同时响应
    "topmost": True,         # 窗口置顶
    "theme": "auto",         # 界面主题：auto / light / dark（新增项，不影响旧字段）
}

cfg = dict(DEFAULT_CONFIG)


def load_config():
    """读取配置；非法或遗留的按键绑定自动恢复为默认侧键。

    注意：必须原地更新 cfg，不能重新赋值。其它模块通过 `from .config import cfg`
    持有该字典的引用，一旦替换对象，它们就会继续读写旧的默认字典，
    导致设置既不被读取也不被保存（例如主题改了重启后失效）。
    """
    data = dict(DEFAULT_CONFIG)
    try:
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data.update(json.load(f))
    except Exception:
        pass
    cfg.clear()
    cfg.update(data)
    for k in ("prev_button", "next_button"):
        if not is_valid_binding(cfg.get(k)):
            cfg[k] = DEFAULT_CONFIG[k]


def save_config():
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
