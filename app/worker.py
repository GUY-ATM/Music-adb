# -*- coding: utf-8 -*-
"""后台命令线程：所有 adb 调用都在这里串行执行，避免阻塞 UI。"""

import threading

from . import adb
from .bus import cmd_q, result_q, CONNECTED
from .config import cfg, save_config


def worker_loop():
    pending = None  # 被本轮挤出来、留到下一轮处理的命令
    while True:
        item = pending if pending is not None else cmd_q.get()
        pending = None
        if item is None:
            break
        kind = item[0]
        if kind == "keyevent":
            _, code, label = item
            if not CONNECTED["ok"]:
                result_q.put((label, False, "未连接设备，请先点击「连接」"))
                continue
            ok, out = adb.send_keyevent(code)
            result_q.put((label, ok, out))
        elif kind == "volume_get":
            v, out = adb.read_volume()
            if v is None:
                result_q.put(("音量同步", False, out))
            else:
                result_q.put(("音量同步", True, f"{v[0]},{v[1]}"))
        elif kind == "volume_set":
            _, target = item
            # 连续滚轮会排下一串音量命令，只保留最新的目标值，避免越调越落后
            while True:
                try:
                    nxt = cmd_q.get_nowait()
                except Exception:
                    break
                if nxt[0] == "volume_set":
                    target = nxt[1]
                else:
                    pending = nxt
                    break
            if not CONNECTED["ok"]:
                result_q.put(("音量", False, "未连接设备，请先点击「连接」"))
                continue
            ok, out = adb.set_volume_absolute(target)
            result_q.put(("音量", ok, out))
        elif kind == "connect":
            _, addr = item
            ok, out = adb.connect_device(addr)
            CONNECTED["ok"] = ok
            cfg["device"] = addr.strip()
            save_config()
            result_q.put(("连接设备", ok, out))
        elif kind == "disconnect":
            CONNECTED["ok"] = False
            result_q.put(("断开设备", True, "已断开（未连接状态，操作已冻结）"))
        elif kind == "devices":
            ok, out = adb.list_devices()
            result_q.put(("检测设备", ok, out))


def start_worker():
    t = threading.Thread(target=worker_loop, daemon=True)
    t.start()
    return t
