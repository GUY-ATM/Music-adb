# -*- coding: utf-8 -*-
"""
手机音乐控制器
- 鼠标按键全局控制手机音乐的上/下一曲（按键可自定义，支持捕获鼠标输入）
- 音量通过鼠标在窗口内拖动滑杆调节
- 通过 ADB 向安卓手机发送按键指令

按键码参考：
    KEYCODE_MEDIA_NEXT     87    下一曲
    KEYCODE_MEDIA_PREVIOUS 88    上一曲
    KEYCODE_MEDIA_PLAY_PAUSE 85  播放/暂停
    KEYCODE_VOLUME_UP      24    音量+
    KEYCODE_VOLUME_DOWN    25    音量-
    KEYCODE_VOLUME_MUTE    164   静音
"""

import ctypes
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox

# ---------------------------------------------------------------------------
# 常量与配置
# ---------------------------------------------------------------------------
APP_DIR = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, "frozen", False) else __file__))
CONFIG_PATH = os.path.join(APP_DIR, "config.json")

# 鼠标按键名称 -> (代码标识, 显示名)
BTN_LABEL = {
    "left": "左键",
    "right": "右键",
    "middle": "中键",
    "x1": "后退键(侧键)",
    "x2": "前进键(侧键)",
}

# 可绑定到切歌的按键。左键留作界面操作（点按钮/取消），禁止绑定，避免误捕获。
VALID_BUTTONS = ("x1", "x2", "middle", "right")

DEFAULT_CONFIG = {
    "adb_path": "",          # 留空则自动查找
    "device": "",            # 设备序列号或 "ip:port"（例如 192.168.1.10:5555）；USB 留空
    "prev_button": "x1",     # 上一曲对应的鼠标按键
    "next_button": "x2",     # 下一曲对应的鼠标按键
    "swallow_bound": False,  # 是否拦截已绑定的按键，避免浏览器后退/前进等副作用
    "swallow_media_keys": False,  # 是否拦截媒体键，避免被系统/其他音乐软件同时响应
    "topmost": True,         # 窗口是否置顶
}

cfg = dict(DEFAULT_CONFIG)


def load_config():
    global cfg
    try:
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = {**DEFAULT_CONFIG, **json.load(f)}
    except Exception:
        cfg = dict(DEFAULT_CONFIG)
    # 校正非法/遗留的按键绑定（例如之前误存成 "left" 的），恢复默认侧键
    for k in ("prev_button", "next_button"):
        if cfg.get(k) not in VALID_BUTTONS:
            cfg[k] = DEFAULT_CONFIG[k]


def save_config():
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def find_adb():
    """自动查找 adb.exe；优先使用配置里的路径。"""
    if cfg.get("adb_path"):
        return cfg["adb_path"]
    candidates = [
        os.path.join(os.environ.get("ANDROID_HOME", ""), "platform-tools", "adb.exe"),
        os.path.expandvars(r"%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe"),
        r"C:\Users\HUAWEI\AppData\Local\Android\Sdk\platform-tools\adb.exe",
    ]
    for c in candidates:
        if c and os.path.exists(c):
            return c
    return "adb"


# ---------------------------------------------------------------------------
# 线程安全的命令队列 / 结果队列 / 按键捕获队列
# ---------------------------------------------------------------------------
cmd_q = queue.Queue()       # 元素: (类型, ...)
result_q = queue.Queue()    # 元素: (标签, 是否成功, 消息)
capture_q = queue.Queue()   # 元素: (动作 "prev"/"next", 按键代码)


def run_adb(args, timeout=8):
    """执行 adb 命令，返回 (是否成功, 输出)。"""
    try:
        r = subprocess.run(
            [find_adb()] + args, capture_output=True, text=True, timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)  # 避免每次都闪一个命令行窗口
        )
        out = (r.stdout or "").strip() + ((" | " + r.stderr.strip()) if r.stderr and r.stderr.strip() else "")
        return r.returncode == 0, out
    except FileNotFoundError:
        return False, "未找到 adb，请在界面中设置 adb 路径"
    except subprocess.TimeoutExpired:
        return False, "adb 命令超时"
    except Exception as e:
        return False, str(e)


def device_args():
    d = cfg.get("device", "").strip()
    return ["-s", d] if d else []


def connect_device(addr):
    """如果设备地址形如 ip:port，先执行 adb connect。"""
    addr = addr.strip()
    if ":" in addr:
        ok, out = run_adb(["connect", addr], timeout=12)
        if not ok:
            return False, out
    ok, out = run_adb(["devices"])
    if ok and addr and addr not in out:
        return False, "设备未连接：\n" + out
    return True, out


# 控制通道说明（针对 HyperOS/MIUI）：
# - `input keyevent` 因缺 INJECT_EVENTS 权限被禁止；
# - `media` 命令被移除；
# - 媒体控制（切歌/播放暂停）用 `cmd media_session dispatch`；
# - 音量控制用 `cmd audio adj-volume`（`cmd media_session volume` 实测为空操作，不生效）。
MEDIA_ACTIONS = {
    "87":  ("dispatch", "next"),        # 下一曲
    "88":  ("dispatch", "previous"),    # 上一曲
    "85":  ("dispatch", "play-pause"),  # 播放/暂停
    "86":  ("dispatch", "stop"),        # 停止
    "164": ("volume", "MUTE"),          # 静音
    "163": ("volume", "UNMUTE"),        # 取消静音
}

VOLUME_STREAM = "3"  # STREAM_MUSIC


def send_keyevent(code):
    """向手机下发一个按键事件，返回 (是否成功, 输出)。"""
    d = device_args()
    kind, arg = MEDIA_ACTIONS.get(code, (None, None))
    if kind == "dispatch":
        return run_adb(d + ["shell", "cmd", "media_session", "dispatch", arg])
    if kind == "volume":
        # 实测：仅 `cmd audio adj-volume` 能真正改变音量（media_session volume 为无效空操作）
        return run_adb(d + ["shell", "cmd", "audio", "adj-volume", VOLUME_STREAM, arg])
    # 未知按键兜底
    return run_adb(d + ["shell", "cmd", "media_session", "dispatch", code])


def read_volume():
    """读取音乐流音量，返回 ((当前值, 最大值) 或 None, 原始输出)。"""
    ok, out = run_adb(device_args() + ["shell", "cmd", "media_session", "volume",
                                       "--stream", VOLUME_STREAM, "--get"])
    if not ok:
        return None, out
    m = re.search(r"volume is (\d+) in range \[(\d+)\.\.(\d+)\]", out or "")
    if not m:
        return None, out
    return (int(m.group(1)), int(m.group(3))), out


def set_volume_absolute(target):
    """把音乐流音量设为 target（0~max），返回 (是否成功, 输出)。

    `cmd audio adj-volume` 每次调节一档（通常 10），因此按差值分多档下发；
    下发后重新读取实际值，如未达到目标则继续微调（最多 4 轮），避免档位差异导致偏差。
    """
    detail = ""
    for _ in range(4):
        v, out = read_volume()
        if v is None:
            return False, out
        cur, mx = v
        target = max(0, min(target, mx))
        delta = target - cur
        if delta == 0:
            return True, f"音量 {cur}/{mx}"
        n = max(1, round(abs(delta) / 10))
        adj = "RAISE" if delta > 0 else "LOWER"
        chain = "; ".join([f"cmd audio adj-volume {VOLUME_STREAM} {adj}"] * n)
        ok, detail = run_adb(device_args() + ["shell", chain], timeout=15)
        if not ok:
            return False, detail
    v, out = read_volume()
    if v is None:
        return False, out
    return True, f"音量 {v[0]}/{v[1]}"


def worker_loop():
    while True:
        item = cmd_q.get()
        if item is None:
            break
        kind = item[0]
        if kind == "keyevent":
            _, code, label = item
            if not CONNECTED["ok"]:
                result_q.put((label, False, "未连接设备，请先点击「连接」"))
                continue
            ok, out = send_keyevent(code)
            result_q.put((label, ok, out))
        elif kind == "volume_get":
            v, out = read_volume()
            if v is None:
                result_q.put(("音量同步", False, out))
            else:
                result_q.put(("音量同步", True, f"{v[0]},{v[1]}"))
        elif kind == "volume_set":
            _, target = item
            if not CONNECTED["ok"]:
                result_q.put(("音量", False, "未连接设备，请先点击「连接」"))
                continue
            ok, out = set_volume_absolute(target)
            result_q.put(("音量", ok, out))
        elif kind == "connect":
            _, addr = item
            ok, out = connect_device(addr)
            CONNECTED["ok"] = ok
            cfg["device"] = addr.strip()
            save_config()
            result_q.put(("连接设备", ok, out))
        elif kind == "devices":
            ok, out = run_adb(["devices"])
            result_q.put(("检测设备", ok, out))


# ---------------------------------------------------------------------------
# Windows 鼠标低级钩子 (WH_MOUSE_LL)，捕获全局鼠标按键
# ---------------------------------------------------------------------------
WH_MOUSE_LL = 14
WM_LBUTTONDOWN = 0x0201
WM_RBUTTONDOWN = 0x0204
WM_MBUTTONDOWN = 0x0207
WM_XBUTTONDOWN = 0x020B
WM_NCXBUTTONDOWN = 0x00AB  # 非客户区侧键按下（AutoHotkey 同时处理此消息，某些输入源只发 NC 变体）
XBUTTON1 = 1  # 后退键
XBUTTON2 = 2  # 前进键

# ---- 键盘低级钩子：捕获「媒体键」（上一曲/下一曲/播放暂停）----
# 很多鼠标驱动把侧键的“切换上下曲”实现为发送这些媒体键，
# 因此本程序模拟为音乐软件来接收它们，从而间接控制手机。
WH_KEYBOARD_LL = 13
WM_KEYDOWN = 0x0100
WM_SYSKEYDOWN = 0x0104
VK_MEDIA_NEXT_TRACK = 0xB0
VK_MEDIA_PREV_TRACK = 0xB1
VK_MEDIA_STOP = 0xB2
VK_MEDIA_PLAY_PAUSE = 0xB3

# 媒体键 -> (adb keyevent 码, 动作名称)
MEDIA_KEY_MAP = {
    VK_MEDIA_NEXT_TRACK: ("87", "下一曲"),
    VK_MEDIA_PREV_TRACK: ("88", "上一曲"),
    VK_MEDIA_PLAY_PAUSE: ("85", "播放/暂停"),
    VK_MEDIA_STOP: ("86", "停止"),
}

BUTTON_FROM_WPARAM = {
    WM_LBUTTONDOWN: "left",
    WM_RBUTTONDOWN: "right",
    WM_MBUTTONDOWN: "middle",
}

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

# CallNextHookEx 必须在回调内被调用，需声明参数类型，否则 64 位句柄/参数会溢出
user32.CallNextHookEx.restype = ctypes.c_ssize_t
user32.CallNextHookEx.argtypes = [
    ctypes.c_void_p, ctypes.c_int, ctypes.c_ssize_t, ctypes.c_ssize_t
]


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("pt", POINT),
        ("mouseData", ctypes.c_ulong),
        ("flags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", ctypes.c_uint),
        ("scanCode", ctypes.c_uint),
        ("flags", ctypes.c_uint),
        ("time", ctypes.c_uint),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", ctypes.c_void_p),
        ("message", ctypes.c_uint),
        ("wParam", ctypes.c_ssize_t),
        ("lParam", ctypes.c_ssize_t),
        ("time", ctypes.c_uint),
        ("pt", POINT),
    ]


HOOKPROC = ctypes.WINFUNCTYPE(
    ctypes.c_ssize_t, ctypes.c_int, ctypes.c_ssize_t, ctypes.c_ssize_t
)

_hook_proc_ref = None
_hook_handle = None
_kb_proc_ref = None
_kb_hook_handle = None
_hook_thread_id = 0
_hook_ok = False       # 鼠标钩子是否安装成功
_kb_hook_ok = False    # 键盘钩子是否安装成功
_hook_ready = threading.Event()

# 媒体键去抖：同一按键短时间内重复（长按自动重复）不重复触发
_media_last = {}

# 捕获状态：非 None 表示正在等待用户按下某个鼠标按键（值为 "prev" 或 "next"）
capture_action = {"which": None}

# 连接状态：只有用户点击「连接」并成功后才置为 True，未连接时所有控制操作冻结
CONNECTED = {"ok": False}

WM_QUIT = 0x0012


def _resolve_button(wParam, lParam):
    """根据消息类型返回统一的鼠标按键标识，未识别返回 None。

    侧键同时处理 WM_XBUTTONDOWN(0x020B) 与 WM_NCXBUTTONDOWN(0x00AB)，
    与 AutoHotkey 的 LowLevelMouseProc 保持一致（HIWORD(mouseData) 取 XBUTTON1/2）。
    """
    if wParam in (WM_XBUTTONDOWN, WM_NCXBUTTONDOWN):
        info = ctypes.cast(lParam, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
        xb = (info.mouseData >> 16) & 0xFFFF  # 等价于 HIWORD(mouseData)
        if xb == XBUTTON1:
            return "x1"
        if xb == XBUTTON2:
            return "x2"
        return None
    return BUTTON_FROM_WPARAM.get(wParam)


def _hook_callback(nCode, wParam, lParam):
    try:
        if nCode == 0:  # HC_ACTION
            btn = _resolve_button(wParam, lParam)
            if btn:
                # 捕获模式：只捕获可绑定按键；左键用于界面操作（点按钮/取消），一律放行
                if capture_action["which"]:
                    if btn in VALID_BUTTONS:
                        capture_q.put((capture_action["which"], btn))
                        capture_action["which"] = None
                        return 1  # 拦截这次按键，避免副作用
                    return user32.CallNextHookEx(_hook_handle, nCode, wParam, lParam)
                # 未连接设备：不触发任何控制，按键一律放行
                if not CONNECTED["ok"]:
                    return user32.CallNextHookEx(_hook_handle, nCode, wParam, lParam)
                # 正常模式：匹配已绑定的按键
                if btn == cfg.get("next_button"):
                    cmd_q.put(("keyevent", "87", "下一曲"))
                    if cfg.get("swallow_bound"):
                        return 1
                elif btn == cfg.get("prev_button"):
                    cmd_q.put(("keyevent", "88", "上一曲"))
                    if cfg.get("swallow_bound"):
                        return 1
        return user32.CallNextHookEx(_hook_handle, nCode, wParam, lParam)
    except Exception:
        return user32.CallNextHookEx(_hook_handle, nCode, wParam, lParam)


def _keyboard_callback(nCode, wParam, lParam):
    try:
        if nCode == 0 and wParam in (WM_KEYDOWN, WM_SYSKEYDOWN):
            info = ctypes.cast(lParam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
            mapped = MEDIA_KEY_MAP.get(info.vkCode)
            if mapped and CONNECTED["ok"]:  # 未连接时媒体键不处理，直接放行给系统
                now = time.time()
                if now - _media_last.get(info.vkCode, 0) > 0.35:  # 去抖，长按不连续触发
                    _media_last[info.vkCode] = now
                    cmd_q.put(("keyevent", mapped[0], mapped[1]))
                if cfg.get("swallow_media_keys"):
                    return 1
        return user32.CallNextHookEx(_kb_hook_handle, nCode, wParam, lParam)
    except Exception:
        return user32.CallNextHookEx(_kb_hook_handle, nCode, wParam, lParam)


def _message_loop():
    """在同一线程内：安装鼠标+键盘低级钩子并运行消息循环。

    低级钩子(WH_MOUSE_LL / WH_KEYBOARD_LL)必须在「安装钩子的线程」内泵消息，
    回调才会被触发，因此安装与 GetMessage 循环必须放在同一个线程里。
    """
    global _hook_proc_ref, _hook_handle, _hook_ok
    global _kb_proc_ref, _kb_hook_handle, _kb_hook_ok
    _hook_thread_id = kernel32.GetCurrentThreadId()

    _hook_proc_ref = HOOKPROC(_hook_callback)
    _kb_proc_ref = HOOKPROC(_keyboard_callback)

    user32.SetWindowsHookExW.restype = ctypes.c_void_p
    user32.SetWindowsHookExW.argtypes = [
        ctypes.c_int, HOOKPROC, ctypes.c_void_p, ctypes.c_ulong
    ]
    kernel32.GetModuleHandleW.restype = ctypes.c_void_p
    kernel32.GetModuleHandleW.argtypes = [ctypes.c_wchar_p]
    hmod = kernel32.GetModuleHandleW(None)

    _hook_handle = user32.SetWindowsHookExW(WH_MOUSE_LL, _hook_proc_ref, hmod, 0)
    _hook_ok = bool(_hook_handle)
    _kb_hook_handle = user32.SetWindowsHookExW(WH_KEYBOARD_LL, _kb_proc_ref, hmod, 0)
    _kb_hook_ok = bool(_kb_hook_handle)
    _hook_ready.set()

    msg = MSG()
    while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
        user32.TranslateMessage(ctypes.byref(msg))
        user32.DispatchMessageW(ctypes.byref(msg))


def start_hook():
    _hook_ready.clear()
    threading.Thread(target=_message_loop, daemon=True).start()
    _hook_ready.wait(timeout=5)
    return _hook_ok


def stop_hook():
    global _hook_handle, _kb_hook_handle
    if _hook_handle:
        user32.UnhookWindowsHookEx(_hook_handle)
        _hook_handle = None
    if _kb_hook_handle:
        user32.UnhookWindowsHookEx(_kb_hook_handle)
        _kb_hook_handle = None
    if _hook_thread_id:
        user32.PostThreadMessageW(_hook_thread_id, WM_QUIT, 0, 0)


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------
class App:
    def __init__(self, root):
        self.root = root
        root.title("手机音乐控制")
        root.resizable(False, False)

        # 高 DPI 感知
        try:
            ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        except Exception:
            try:
                ctypes.windll.shcore.SetProcessDpiAwareness(1)
            except Exception:
                pass

        pad = {"padx": 8, "pady": 4}

        # 连接状态
        self.status_dot = tk.Label(root, text="●", fg="gray", font=("", 14))
        self.status_dot.grid(row=0, column=0, sticky="e", padx=(10, 0))
        self.status_label = tk.Label(root, text="未检测设备", anchor="w")
        self.status_label.grid(row=0, column=1, columnspan=3, sticky="w", **pad)

        # 设备设置
        tk.Label(root, text="设备:").grid(row=1, column=0, sticky="e", **pad)
        self.device_var = tk.StringVar(value=cfg.get("device", ""))
        tk.Entry(root, textvariable=self.device_var, width=24).grid(
            row=1, column=1, columnspan=2, sticky="we", **pad
        )
        tk.Button(root, text="连接", command=self.on_connect).grid(row=1, column=3, **pad)

        tk.Label(root, text="adb:").grid(row=2, column=0, sticky="e", **pad)
        self.adb_var = tk.StringVar(value=cfg.get("adb_path", ""))
        tk.Entry(root, textvariable=self.adb_var, width=24).grid(
            row=2, column=1, columnspan=3, sticky="we", **pad
        )

        tk.Label(root, text="提示: USB 连接设备留空；WiFi 连接填 手机IP:5555",
                 fg="gray").grid(row=3, column=1, columnspan=3, sticky="w", **pad)

        # 按键设置（捕获鼠标输入）
        bind_frame = tk.LabelFrame(root, text="切歌按键设置")
        bind_frame.grid(row=4, column=0, columnspan=4, sticky="we", padx=8, pady=4)
        self.btn_prev = tk.Button(bind_frame, text="设置上一曲", width=10,
                                  command=lambda: self.start_capture("prev"))
        self.btn_prev.pack(side="left", padx=6, pady=4)
        self.btn_next = tk.Button(bind_frame, text="设置下一曲", width=10,
                                  command=lambda: self.start_capture("next"))
        self.btn_next.pack(side="left", padx=6, pady=4)
        self.btn_cancel = tk.Button(bind_frame, text="取消", width=6, state="disabled",
                                    command=self.cancel_capture)
        self.btn_cancel.pack(side="left", padx=6, pady=4)

        self.bind_label = tk.Label(root, text="", fg="#444")
        self.bind_label.grid(row=5, column=0, columnspan=4, sticky="w", padx=10)
        self.capture_hint = tk.Label(root, text="", fg="#b45f06", anchor="w")
        self.capture_hint.grid(row=6, column=0, columnspan=4, sticky="w", padx=10)

        # 音量（滑杆，鼠标拖动 / 滚轮调节）
        self.vol_frame = tk.LabelFrame(root, text="音量（拖动滑杆或用滚轮调节）")
        vol = self.vol_frame
        vol.grid(row=7, column=0, columnspan=4, sticky="we", padx=8, pady=4)
        self._vol_syncing = False   # 由设备同步数值时，忽略滑杆回调
        self._pending_vol = None    # 待下发的目标音量
        self._vol_after = None      # 拖动节流定时器
        self.vol_slider = tk.Scale(vol, from_=0, to=150, orient="horizontal",
                                   showvalue=0, resolution=1, length=300,
                                   command=self.on_volume_slide)
        self.vol_slider.pack(side="left", padx=(10, 6), pady=6)
        self.vol_slider.bind("<ButtonRelease-1>", self.on_volume_release)
        self.vol_value_label = tk.Label(vol, text="--", width=6, fg="#444")
        self.vol_value_label.pack(side="left")
        self.mute_btn = tk.Button(vol, text="静音", width=8, command=self.on_mute)
        self.mute_btn.pack(side="left", padx=6, pady=4)

        # 音乐（按键为主，这里作为鼠标备用）
        media = tk.LabelFrame(root, text="音乐")
        media.grid(row=8, column=0, columnspan=4, sticky="we", padx=8, pady=4)
        self.btn_prev_song = tk.Button(media, text="上一曲", width=8, command=self.on_prev)
        self.btn_prev_song.pack(side="left", padx=6, pady=4)
        self.btn_play = tk.Button(media, text="播放/暂停", width=8, command=self.on_play_pause)
        self.btn_play.pack(side="left", padx=6, pady=4)
        self.btn_next_song = tk.Button(media, text="下一曲", width=8, command=self.on_next)
        self.btn_next_song.pack(side="left", padx=6, pady=4)

        # 选项
        opt = tk.LabelFrame(root, text="选项")
        opt.grid(row=9, column=0, columnspan=4, sticky="we", padx=8, pady=4)
        self.top_var = tk.BooleanVar(value=cfg.get("topmost", True))
        tk.Checkbutton(opt, text="窗口置顶", variable=self.top_var,
                       command=self.on_topmost).pack(side="left", padx=6)
        self.swallow_var = tk.BooleanVar(value=cfg.get("swallow_bound", False))
        tk.Checkbutton(opt, text="拦截已绑定的按键(避免浏览器后退)", variable=self.swallow_var,
                       command=self.on_swallow).pack(side="left", padx=6)
        self.swallow_media_var = tk.BooleanVar(value=cfg.get("swallow_media_keys", False))
        tk.Checkbutton(opt, text="拦截媒体键", variable=self.swallow_media_var,
                       command=self.on_swallow_media).pack(side="left", padx=6)

        # 媒体键提示：程序模拟为音乐软件，侧键映射的“切歌媒体键”可直接生效
        self.media_label = tk.Label(
            root, fg="#666",
            text="已开启媒体键监听：鼠标侧键若映射为「上一曲/下一曲媒体键」，将直接控制手机。"
        )
        self.media_label.grid(row=10, column=0, columnspan=4, sticky="w", padx=10)

        self.msg_label = tk.Text(root, height=3, width=60, wrap="word",
                                 fg="blue", relief="solid", borderwidth=1, background="#fafafa")
        self.msg_label.grid(row=11, column=0, columnspan=3, sticky="we", padx=8, pady=(0, 6))
        self.msg_label.config(state="disabled")
        self.copy_btn = tk.Button(root, text="复制", width=6, command=self.copy_msg)
        self.copy_btn.grid(row=11, column=3, sticky="we", padx=(0, 8), pady=(0, 6))

        self.on_topmost()
        self.update_bind_label()

        # 未连接前冻结所有控制操作
        self.set_connected(CONNECTED["ok"])

        # 滚轮调音量：绑定到窗口级，仅当指针位于音量区域时生效
        root.bind_all("<MouseWheel>", self.on_volume_wheel)
        root.bind_all("<Button-4>", self.on_volume_wheel)  # 兼容部分触控板/非 Windows 环境
        root.bind_all("<Button-5>", self.on_volume_wheel)

        # 启动钩子与后台线程
        start_hook()
        if not _hook_ok and not _kb_hook_ok:
            messagebox.showwarning("提示", "钩子启动失败，切歌按键与捕获将不可用，界面按钮仍可用。")
        threading.Thread(target=worker_loop, daemon=True).start()

        # 启动时检测一次设备
        root.after(300, lambda: cmd_q.put(("devices",)))
        self._poll()

        root.protocol("WM_DELETE_WINDOW", self.on_close)

    # ----- 按键捕获 -----
    def start_capture(self, which):
        if not self.connected:
            self.set_msg("请先点击「连接」连接手机，再设置切歌按键。", "red")
            return
        if not _hook_ok:
            messagebox.showwarning("提示", "鼠标钩子未启动，无法捕获按键。")
            return
        capture_action["which"] = which
        name = "上一曲" if which == "prev" else "下一曲"
        self.capture_hint.config(text=f"请按下用于「{name}」的侧键（点「取消」退出，左键不会作为绑定）")
        self.btn_prev.config(state="disabled")
        self.btn_next.config(state="disabled")
        self.btn_cancel.config(state="normal")

    def cancel_capture(self):
        capture_action["which"] = None
        self.capture_hint.config(text="")
        self.btn_prev.config(state="normal")
        self.btn_next.config(state="normal")
        self.btn_cancel.config(state="disabled")

    def apply_capture(self, which, btn):
        cfg["prev_button" if which == "prev" else "next_button"] = btn
        save_config()
        self.cancel_capture()
        self.update_bind_label()

    def update_bind_label(self):
        prev = cfg.get("prev_button", "x1")
        nxt = cfg.get("next_button", "x2")
        self.bind_label.config(
            text=f"上一曲: {BTN_LABEL.get(prev, prev)}    下一曲: {BTN_LABEL.get(nxt, nxt)}")

    def set_connected(self, ok):
        """未连接设备时冻结所有控制操作，连接成功后解锁。"""
        self.connected = ok
        state = "normal" if ok else "disabled"
        for w in (self.btn_prev, self.btn_next, self.vol_slider, self.mute_btn,
                  self.btn_prev_song, self.btn_play, self.btn_next_song):
            w.config(state=state)
        if not ok:
            self._pending_vol = None
            self.vol_value_label.config(text="--")

    # ----- 动作 -----
    def on_next(self):
        cmd_q.put(("keyevent", "87", "下一曲"))

    def on_prev(self):
        cmd_q.put(("keyevent", "88", "上一曲"))

    def on_play_pause(self):
        cmd_q.put(("keyevent", "85", "播放/暂停"))

    # ----- 音量滑杆 -----
    def on_volume_slide(self, val):
        if self._vol_syncing or not self.connected:
            return
        self._pending_vol = int(float(val))
        self.vol_value_label.config(text=str(self._pending_vol))
        if self._vol_after is None:  # 拖动节流：0.2 秒内只下发一次，避免刷屏 adb
            self._vol_after = self.root.after(200, self._flush_volume)

    def on_volume_release(self, _event=None):
        self._flush_volume()

    def _in_volume_area(self, widget):
        """判断某个控件是否位于音量区域（用于限定滚轮生效范围）。"""
        while widget is not None:
            if widget is self.vol_frame:
                return True
            widget = getattr(widget, "master", None)
        return False

    def on_volume_wheel(self, event):
        """鼠标滚轮在音量区域上滚动时，按一档调节音量。"""
        if not self.connected:
            return
        if not self._in_volume_area(self.root.winfo_containing(event.x_root, event.y_root)):
            return
        num = getattr(event, "num", None)
        if num == 4 or getattr(event, "delta", 0) > 0:
            step = 5
        elif num == 5 or getattr(event, "delta", 0) < 0:
            step = -5
        else:
            return
        cur = int(float(self.vol_slider.get()))
        mx = int(float(self.vol_slider.cget("to")))
        self.vol_slider.set(max(0, min(mx, cur + step)))
        self.on_volume_slide(self.vol_slider.get())
        return "break"

    def _flush_volume(self):
        if self._vol_after is not None:
            try:
                self.root.after_cancel(self._vol_after)
            except Exception:
                pass
            self._vol_after = None
        if self._pending_vol is None or not self.connected:
            return
        target, self._pending_vol = self._pending_vol, None
        cmd_q.put(("volume_set", target))

    def sync_volume(self, cur, mx):
        """把设备实际音量同步到滑杆上。"""
        self._vol_syncing = True
        try:
            self.vol_slider.config(to=mx)
            self.vol_slider.set(cur)
        finally:
            self._vol_syncing = False
        self.vol_value_label.config(text=str(cur))

    def on_mute(self):
        self.muted = not getattr(self, "muted", False)
        code, name = ("164", "静音") if self.muted else ("163", "取消静音")
        cmd_q.put(("keyevent", code, name))
        self.mute_btn.config(text="取消静音" if self.muted else "静音")

    def on_connect(self):
        cfg["device"] = self.device_var.get().strip()
        cfg["adb_path"] = self.adb_var.get().strip()
        save_config()
        cmd_q.put(("connect", cfg["device"]))

    def on_topmost(self):
        v = self.top_var.get()
        cfg["topmost"] = v
        self.root.attributes("-topmost", v)
        save_config()

    def on_swallow(self):
        cfg["swallow_bound"] = self.swallow_var.get()
        save_config()

    def on_swallow_media(self):
        cfg["swallow_media_keys"] = self.swallow_media_var.get()
        save_config()

    def set_msg(self, text, color="blue"):
        """在可复制的文本框里显示信息。"""
        self.msg_label.config(state="normal")
        self.msg_label.delete("1.0", "end")
        self.msg_label.insert("1.0", text)
        self.msg_label.config(fg=color)
        self.msg_label.config(state="disabled")

    def copy_msg(self):
        """把当前信息复制到剪贴板。"""
        text = self.msg_label.get("1.0", "end").strip()
        if text:
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            self.root.update()

    def on_close(self):
        stop_hook()
        cmd_q.put(None)
        self.root.destroy()

    # ----- 轮询结果与捕获事件 -----
    def _poll(self):
        # 捕获事件
        while not capture_q.empty():
            try:
                which, btn = capture_q.get_nowait()
            except queue.Empty:
                break
            self.apply_capture(which, btn)

        # 命令结果
        while not result_q.empty():
            try:
                label, ok, msg = result_q.get_nowait()
            except queue.Empty:
                break
            if label == "检测设备":
                detected = "adb" in (msg or "") and "\t" in msg
                if detected:
                    # 仅提示检测到设备，仍需用户点击「连接」才解锁操作
                    self.status_dot.config(fg="orange")
                    self.status_label.config(text="检测到设备，请点击「连接」")
                else:
                    self.status_dot.config(fg="orange")
                    self.status_label.config(text="未检测到设备")
            elif label == "连接设备":
                if ok:
                    self.status_dot.config(fg="green")
                    self.status_label.config(text="设备已连接")
                    self.set_connected(True)
                    cmd_q.put(("volume_get",))  # 连上后同步手机当前音量到滑杆
                else:
                    self.status_dot.config(fg="red")
                    self.status_label.config(text="连接失败")
                    self.set_connected(False)
                self.set_msg(msg if msg else "", "red" if not ok else "green")
            elif label == "音量同步":
                if ok:
                    try:
                        cur, mx = (int(x) for x in msg.split(","))
                    except Exception:
                        cur = None
                    if cur is not None:
                        self.sync_volume(cur, mx)
                else:
                    self.set_msg(f"读取音量失败 — {msg}", "red")
            elif label == "音量":
                self.set_msg(f"{label}: {'成功 — ' + msg if ok else '失败 — ' + msg}",
                             "green" if ok else "red")
            else:
                self.set_msg(f"{label}: {'成功' if ok else '失败'} {('' if ok else '— ' + msg)}",
                             "green" if ok else "red")
        self.root.after(150, self._poll)


def main():
    load_config()
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        try:
            messagebox.showerror("启动失败", str(e))
        except Exception:
            pass
        raise