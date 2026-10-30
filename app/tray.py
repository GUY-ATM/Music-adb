# -*- coding: utf-8 -*-
"""系统托盘图标：常驻通知区域，提供右键菜单，并向外提供图标的屏幕位置。

Windows 的通知区域不会把滚轮消息转发给图标所属窗口（Qt 也仅在 X11 上提供
QSystemTrayIcon 的 wheel 事件），因此「在图标上滚动滚轮调音量」由全局低级
鼠标钩子配合本模块的 geometry_physical() 实现。
"""

import ctypes
import os
from ctypes import wintypes

from PyQt5.QtCore import QObject
from PyQt5.QtGui import QGuiApplication, QIcon
from PyQt5.QtWidgets import QMenu, QSystemTrayIcon

from .config import resource_path

user32 = ctypes.windll.user32
user32.FindWindowW.restype = wintypes.HWND
user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
user32.FindWindowExW.restype = wintypes.HWND
user32.FindWindowExW.argtypes = [wintypes.HWND, wintypes.HWND,
                                 wintypes.LPCWSTR, wintypes.LPCWSTR]
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]

# 图标被折叠时 geometry() 返回的其实就是溢出按钮，判定时留几像素容差
OVERFLOW_TOLERANCE = 6


def _tray_notify_left():
    """通知区域（TrayNotifyWnd）左边界，物理像素；取不到返回 None。"""
    try:
        tray = user32.FindWindowW("Shell_TrayWnd", None)
        if not tray:
            return None
        notify = user32.FindWindowExW(tray, None, "TrayNotifyWnd", None)
        if not notify:
            return None
        r = wintypes.RECT()
        user32.GetWindowRect(notify, ctypes.byref(r))
        return r.left
    except Exception:
        return None


def is_overflow_button(rect):
    """判断 geometry() 给出的矩形是否是通知区域的「^」折叠按钮。

    图标被折叠进浮层时，系统返回的是「^」按钮的位置，而该按钮恰好贴在
    通知区域最左侧；据此可区分「图标已固定到任务栏」与「图标被折叠」。
    """
    left = _tray_notify_left()
    if left is None:
        return False
    return rect[0] <= left + OVERFLOW_TOLERANCE


class TrayIcon(QObject):
    def __init__(self, window, ctl):
        super().__init__(window)
        self.window = window
        self.ctl = ctl
        self.hidden_in_overflow = False  # 图标是否被折叠在「^」浮层里

        self.tray = QSystemTrayIcon(self._load_icon(), self)
        self.tray.setToolTip("手机音乐控制 · 未连接")
        self.tray.setContextMenu(self._build_menu())
        self.tray.activated.connect(self._on_activated)
        self.tray.show()

    # ------------------------------------------------------------------
    # 初始化
    # ------------------------------------------------------------------
    def _load_icon(self):
        # 托盘图标用彩色版本：music.png 是黑底，在深色任务栏上几乎看不见
        for name in ("tray.ico", "tray.png", "music.png"):
            path = resource_path(name)
            if os.path.exists(path):
                return QIcon(path)
        from qfluentwidgets import FluentIcon
        return FluentIcon.MUSIC.icon()

    def _build_menu(self):
        self.menu = QMenu()
        self.showAction = self.menu.addAction("显示主界面")
        self.showAction.triggered.connect(self.show_window)
        self.menu.addSeparator()
        self.syncAction = self.menu.addAction("重新读取音量")
        self.syncAction.triggered.connect(self.ctl.sync_volume)
        self.muteAction = self.menu.addAction("静音")
        self.muteAction.triggered.connect(self.ctl.toggle_mute)
        self.menu.addSeparator()
        self.quitAction = self.menu.addAction("退出")
        self.quitAction.triggered.connect(self.window.close)
        return self.menu

    # ------------------------------------------------------------------
    # 交互
    # ------------------------------------------------------------------
    def show_window(self):
        self.window.showNormal()
        self.window.raise_()
        self.window.activateWindow()

    def _on_activated(self, reason):
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.show_window()

    # ------------------------------------------------------------------
    # 状态同步
    # ------------------------------------------------------------------
    def set_connected(self, ok):
        self.tray.setToolTip("手机音乐控制 · 已连接\n鼠标移到图标上滚动滚轮调节音量"
                             if ok else "手机音乐控制 · 未连接")

    def set_volume(self, cur, mx):
        self.tray.setToolTip(f"手机音乐控制 · 音量 {cur}/{mx}\n"
                             "鼠标移到图标上滚动滚轮调节音量")

    def set_muted(self, muted):
        self.muteAction.setText("取消静音" if muted else "静音")

    # ------------------------------------------------------------------
    # 位置
    # ------------------------------------------------------------------
    @staticmethod
    def is_available():
        return QSystemTrayIcon.isSystemTrayAvailable()

    def geometry_physical(self):
        """返回托盘图标的物理像素矩形 (x, y, 宽, 高)；无法滚轮调节时返回 None。

        Qt 的几何信息是逻辑坐标，需按图标所在屏幕的缩放比换算成物理像素，
        才能与低级鼠标钩子给出的屏幕坐标对齐。
        """
        self.hidden_in_overflow = False
        if not self.tray.isVisible():
            return None
        g = self.tray.geometry()
        if g.isNull() or g.width() <= 0 or g.height() <= 0:
            return None  # 图标被折叠进「隐藏的图标」浮层时拿不到位置
        scr = QGuiApplication.screenAt(g.center()) or QGuiApplication.primaryScreen()
        dpr = scr.devicePixelRatio() if scr else 1.0
        rect = (int(g.x() * dpr), int(g.y() * dpr),
                max(1, int(g.width() * dpr)), max(1, int(g.height() * dpr)))
        if is_overflow_button(rect):
            # 图标被折叠时系统返回的是「^」按钮，若照此拦截会在箭头上误调音量
            self.hidden_in_overflow = True
            return None
        return rect

    def hide(self):
        self.tray.hide()
