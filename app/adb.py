# -*- coding: utf-8 -*-
"""ADB 业务层：与 Tkinter 版本完全一致的命令、解析和返回值语义。"""

import os
import re
import subprocess

from .config import cfg

VOLUME_STREAM = "3"  # STREAM_MUSIC

# 控制通道说明（针对 HyperOS/MIUI 实测）：
# - `input keyevent` 因缺 INJECT_EVENTS 权限被禁止；
# - `media` 命令被移除；
# - 媒体控制用 `cmd media_session dispatch`；
# - 音量控制用 `cmd audio adj-volume`（`cmd media_session volume` 为空操作）。
MEDIA_ACTIONS = {
    "87": ("dispatch", "next"),        # 下一曲
    "88": ("dispatch", "previous"),    # 上一曲
    "85": ("dispatch", "play-pause"),  # 播放/暂停
    "86": ("dispatch", "stop"),        # 停止
    "164": ("volume", "MUTE"),         # 静音
    "163": ("volume", "UNMUTE"),       # 取消静音
}


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


def run_adb(args, timeout=8):
    """执行 adb 命令，返回 (是否成功, 输出)。"""
    try:
        r = subprocess.run(
            [find_adb()] + args, capture_output=True, text=True, timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
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
    addr = (addr or "").strip()
    if ":" in addr:
        ok, out = run_adb(["connect", addr], timeout=12)
        if not ok:
            return False, out
    ok, out = run_adb(["devices"])
    if ok and addr and addr not in out:
        return False, "设备未连接：\n" + out
    return True, out


def send_keyevent(code):
    """向手机下发一个按键事件，返回 (是否成功, 输出)。"""
    d = device_args()
    kind, arg = MEDIA_ACTIONS.get(code, (None, None))
    if kind == "dispatch":
        return run_adb(d + ["shell", "cmd", "media_session", "dispatch", arg])
    if kind == "volume":
        return run_adb(d + ["shell", "cmd", "audio", "adj-volume", VOLUME_STREAM, arg])
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

    `cmd audio adj-volume` 每次调节一档（通常 10），按差值分多档下发后回读校验，
    最多微调 4 轮，避免档位差异导致偏差。
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


def list_devices():
    return run_adb(["devices"])
