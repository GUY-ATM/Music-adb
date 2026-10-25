# -*- coding: utf-8 -*-
"""程序入口：初始化高 DPI、配置、后台线程、全局钩子与主窗口。"""

import ctypes
import os
import sys

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication

from app.config import load_config
from app.input_hooks import start_hook, stop_hook
from app.ui.main_window import MainWindow
from app.worker import start_worker


def main():
    # 高 DPI 感知（Windows）
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    load_config()
    app = QApplication(sys.argv)
    app.setApplicationName("手机音乐控制")
    app.setOrganizationName("PhoneMusicController")

    start_worker()
    start_hook()

    win = MainWindow()
    win.show()
    code = app.exec_()

    stop_hook()
    # 后台线程（worker / 钩子消息循环）仍在运行时直接退出，
    # 避免解释器销毁 Qt 对象期间发生访问冲突（退出码 0xC0000005）。
    try:  # 打包为 --noconsole 时 sys.stdout 为 None，不能直接 flush
        sys.stdout.flush()
    except Exception:
        pass
    os._exit(code)


if __name__ == "__main__":
    sys.exit(main())
