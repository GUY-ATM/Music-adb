# -*- coding: utf-8 -*-
"""Windows 全局输入钩子（与 Tkinter 版本逻辑一致，移植入独立模块）。

- WH_MOUSE_LL：捕获鼠标侧键/中键/右键，用于切歌绑定
- WH_KEYBOARD_LL：捕获媒体键（上一曲/下一曲/播放暂停/停止），并支持录制键盘按键绑定，
  兼容把侧键映射为媒体键的鼠标驱动（如英菲克）
"""

import ctypes
import threading
import time

from .bus import capture_q, cmd_q, CONNECTED
from .config import (MOD_ALT, MOD_CTRL, MOD_SHIFT, MODIFIER_VKS, VALID_BUTTONS,
                     cfg, make_key_binding, parse_key_binding)

WH_MOUSE_LL = 14
WM_LBUTTONDOWN = 0x0201
WM_RBUTTONDOWN = 0x0204
WM_MBUTTONDOWN = 0x0207
WM_XBUTTONDOWN = 0x020B
WM_NCXBUTTONDOWN = 0x00AB  # 非客户区侧键按下（AutoHotkey 同时处理此消息）
XBUTTON1 = 1  # 后退键
XBUTTON2 = 2  # 前进键

WH_KEYBOARD_LL = 13
WM_KEYDOWN = 0x0100
WM_SYSKEYDOWN = 0x0104
VK_SHIFT = 0x10
VK_CONTROL = 0x11
VK_MENU = 0x12  # Alt
VK_ESCAPE = 0x1B
VK_MEDIA_NEXT_TRACK = 0xB0
VK_MEDIA_PREV_TRACK = 0xB1
VK_MEDIA_STOP = 0xB2
VK_MEDIA_PLAY_PAUSE = 0xB3

# 媒体键 -> (adb 指令码, 动作名称)
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

WM_QUIT = 0x0012

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

# CallNextHookEx 必须在回调内被调用，需声明参数类型，否则 64 位句柄/参数会溢出
user32.CallNextHookEx.restype = ctypes.c_ssize_t
user32.CallNextHookEx.argtypes = [
    ctypes.c_void_p, ctypes.c_int, ctypes.c_ssize_t, ctypes.c_ssize_t
]
# 查询修饰键当前是否按下（用于录制/匹配 Ctrl / Alt / Shift 组合）
user32.GetAsyncKeyState.restype = ctypes.c_short
user32.GetAsyncKeyState.argtypes = [ctypes.c_int]


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
mouse_hook_ok = False
keyboard_hook_ok = False
_hook_ready = threading.Event()

# 媒体键去抖：同一按键短时间内重复（长按自动重复）不重复触发
_media_last = {}

# 键盘绑定去抖：长按产生的自动重复只触发一次
_kb_bound_last = {}

# 捕获状态：非 None 表示正在等待用户按下某个鼠标或键盘按键（值为 "prev" 或 "next"）
capture_action = {"which": None}


def _current_mods():
    """读取当前按下的修饰键，返回 MOD_CTRL / MOD_ALT / MOD_SHIFT 位组合。"""
    mods = 0
    if user32.GetAsyncKeyState(VK_CONTROL) & 0x8000:
        mods |= MOD_CTRL
    if user32.GetAsyncKeyState(VK_MENU) & 0x8000:
        mods |= MOD_ALT
    if user32.GetAsyncKeyState(VK_SHIFT) & 0x8000:
        mods |= MOD_SHIFT
    return mods


def _match_key_binding(vk, mods):
    """返回命中的键盘绑定 (adb 指令码, 动作名)，未命中返回 None。"""
    for key, code, label in (("next_button", "87", "下一曲"),
                             ("prev_button", "88", "上一曲")):
        if parse_key_binding(cfg.get(key)) == (vk, mods):
            return code, label
    return None


def _resolve_button(wParam, lParam):
    """根据消息类型返回统一的鼠标按键标识，未识别返回 None。"""
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
                # 捕获模式：只捕获可绑定按键；左键用于界面操作，一律放行
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
            vk = info.vkCode

            # 录制模式：捕获键盘按键（忽略裸修饰键与媒体键；Esc 取消）
            which = capture_action["which"]
            if which:
                if vk in MODIFIER_VKS or vk in MEDIA_KEY_MAP:
                    return user32.CallNextHookEx(_kb_hook_handle, nCode, wParam, lParam)
                capture_action["which"] = None
                if vk == VK_ESCAPE:
                    capture_q.put((which, "cancel"))
                else:
                    capture_q.put((which, make_key_binding(vk, _current_mods())))
                return 1  # 拦截这次按键，避免副作用

            mapped = MEDIA_KEY_MAP.get(vk)
            if mapped and CONNECTED["ok"]:  # 未连接时媒体键直接放行给系统
                now = time.time()
                if now - _media_last.get(vk, 0) > 0.35:  # 去抖，长按不连续触发
                    _media_last[vk] = now
                    cmd_q.put(("keyevent", mapped[0], mapped[1]))
                if cfg.get("swallow_media_keys"):
                    return 1

            # 正常模式：匹配用户录制的键盘绑定（独占该组合键）
            if CONNECTED["ok"]:
                mods = _current_mods()
                hit = _match_key_binding(vk, mods)
                if hit:
                    now = time.time()
                    if now - _kb_bound_last.get((vk, mods), 0) > 0.35:
                        _kb_bound_last[(vk, mods)] = now
                        cmd_q.put(("keyevent", hit[0], hit[1]))
                    return 1
        return user32.CallNextHookEx(_kb_hook_handle, nCode, wParam, lParam)
    except Exception:
        return user32.CallNextHookEx(_kb_hook_handle, nCode, wParam, lParam)


def _message_loop():
    """在同一线程内：安装鼠标+键盘低级钩子并运行消息循环。

    低级钩子必须在「安装钩子的线程」内泵消息，回调才会被触发，
    因此安装与 GetMessage 循环必须放在同一个线程里。
    """
    global _hook_proc_ref, _hook_handle, mouse_hook_ok
    global _kb_proc_ref, _kb_hook_handle, keyboard_hook_ok
    global _hook_thread_id
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
    mouse_hook_ok = bool(_hook_handle)
    _kb_hook_handle = user32.SetWindowsHookExW(WH_KEYBOARD_LL, _kb_proc_ref, hmod, 0)
    keyboard_hook_ok = bool(_kb_hook_handle)
    _hook_ready.set()

    msg = MSG()
    while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
        user32.TranslateMessage(ctypes.byref(msg))
        user32.DispatchMessageW(ctypes.byref(msg))


def start_hook():
    _hook_ready.clear()
    threading.Thread(target=_message_loop, daemon=True).start()
    _hook_ready.wait(timeout=5)
    return mouse_hook_ok


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
