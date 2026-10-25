# -*- coding: utf-8 -*-
"""主窗口：FluentWindow 导航 + 控制器（连接 UI 与后台业务）。"""

import os
import time

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QColor, QIcon

from qfluentwidgets import (FluentIcon, FluentWindow, InfoBar, InfoBarPosition,
                            NavigationItemPosition, Theme, isDarkTheme, setTheme)

from .. import input_hooks
from ..bus import CONNECTED, capture_q, cmd_q, result_q
from ..config import (binding_display, cfg, is_valid_binding, resource_path,
                      save_config)
from .pages import DevicePage, LogPage, PlaybackPage, SettingsPage, VolumePage


class MainWindow(FluentWindow):
    def __init__(self):
        super().__init__()
        self.cfg = cfg
        self.muted = False
        self._capture = None

        self.setWindowTitle("手机音乐控制")
        icon_file = resource_path("music.png")
        if os.path.exists(icon_file):
            self.setWindowIcon(QIcon(icon_file))
        else:
            self.setWindowIcon(FluentIcon.MUSIC.icon())
        # 关闭 Mica：让窗口背景由 Qt 按当前主题绘制，避免「深色主题 + 浅色系统」时文字不可读
        self.setMicaEffectEnabled(False)
        self.setCustomBackgroundColor(QColor(243, 243, 243), QColor(32, 32, 32))
        self.resize(980, 720)
        self.setMinimumSize(880, 620)

        self.devicePage = DevicePage(self)
        self.playbackPage = PlaybackPage(self)
        self.volumePage = VolumePage(self)
        self.logPage = LogPage(self)
        self.settingsPage = SettingsPage(self)

        self.addSubInterface(self.devicePage, FluentIcon.CONNECT, "连接设备")
        self.addSubInterface(self.playbackPage, FluentIcon.MUSIC, "播放控制")
        self.addSubInterface(self.volumePage, FluentIcon.MIX_VOLUMES, "音量")
        self.addSubInterface(self.logPage, FluentIcon.DOCUMENT, "运行日志")
        self.addSubInterface(self.settingsPage, FluentIcon.SETTING, "设置",
                             NavigationItemPosition.BOTTOM)
        self.navigationInterface.setExpandWidth(200)
        self.navigationInterface.setMinimumExpandWidth(700)
        self.navigationInterface.setMenuButtonVisible(False)
        self.navigationInterface.expand(useAni=False)

        if self.cfg.get("topmost", True):
            self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        self._apply_theme(self.cfg.get("theme", "auto"))

        self.set_connected(False, "未连接")
        self.log(f"程序已启动，输入钩子：鼠标={'正常' if input_hooks.mouse_hook_ok else '失败'}，"
                 f"键盘={'正常' if input_hooks.keyboard_hook_ok else '失败'}")

        self.timer = QTimer(self)
        self.timer.setInterval(120)
        self.timer.timeout.connect(self.poll)
        self.timer.start()

    # ------------------------------------------------------------------
    # 控制器接口（供各页面调用）
    # ------------------------------------------------------------------
    def is_connected(self):
        return CONNECTED["ok"]

    def toast(self, title, content="", success=True, duration=2500):
        fn = InfoBar.success if success else InfoBar.error
        fn(title=title, content=content, orient=Qt.Horizontal, isClosable=True,
           position=InfoBarPosition.TOP_RIGHT, duration=duration, parent=self)

    def log(self, text):
        self.logPage.append(f"[{time.strftime('%H:%M:%S')}] {text}")

    def connect(self):
        addr = self.devicePage.addrEdit.text().strip()
        self.devicePage.set_status("连接中…", "#c8a400")
        cmd_q.put(("connect", addr))

    def detect(self):
        self.devicePage.devicesLabel.setText("正在检测设备…")
        cmd_q.put(("devices",))

    def disconnect(self):
        cmd_q.put(("disconnect",))

    def send_key(self, code, label):
        if not self.is_connected():
            self.toast("未连接设备", "请先在「连接设备」页点击连接", success=False)
            return
        cmd_q.put(("keyevent", code, label))

    def sync_volume(self):
        if not self.is_connected():
            self.toast("未连接设备", "请先连接手机", success=False)
            return
        self.volumePage._pending = None
        cmd_q.put(("volume_get",))

    def set_volume(self, target):
        cmd_q.put(("volume_set", int(target)))

    def toggle_mute(self):
        if not self.is_connected():
            self.toast("未连接设备", "请先连接手机", success=False)
            return
        self.muted = not self.muted
        self.volumePage.muteBtn.setText("取消静音" if self.muted else "静音")
        cmd_q.put(("keyevent", "164" if self.muted else "163",
                   "静音" if self.muted else "取消静音"))

    def request_capture(self, which):
        if not self.is_connected():
            self.toast("未连接设备", "请先连接手机，再设置切歌按键", success=False)
            return
        if not (input_hooks.mouse_hook_ok or input_hooks.keyboard_hook_ok):
            self.toast("输入钩子未安装", "无法捕获按键，请重启程序", success=False)
            return
        self._capture = which
        input_hooks.capture_action["which"] = which
        self.playbackPage.set_capturing(which)
        self.set_connected(True, "等待按键…", busy=True)

    def cancel_capture(self):
        self._capture = None
        input_hooks.capture_action["which"] = None
        self.playbackPage.set_capturing(None)
        self.set_connected(True, "设备已连接")

    def set_theme(self, value):
        self._apply_theme(value)
        self.cfg["theme"] = value
        save_config()

    def _apply_theme(self, value):
        setTheme({"auto": Theme.AUTO, "light": Theme.LIGHT, "dark": Theme.DARK}.get(
            value, Theme.AUTO))
        self._sync_title_bar_buttons()

    def _sync_title_bar_buttons(self):
        """按当前主题显式设置标题栏按钮颜色。

        最小化/最大化/关闭按钮由 qframelesswindow 手工绘制，图标与背景色取自
        QSS 的 qproperty-normalColor 等属性。这些属性在窗口首次显示时会被重置为
        默认黑色，导致深色主题下按钮不可见；因此在按钮自身上落一份样式表，
        使其在后续每次样式刷新时都能稳定生效。
        """
        light = not isDarkTheme()
        icon = "black" if light else "white"
        hover_bg = "rgba(0, 0, 0, 26)" if light else "rgba(255, 255, 255, 26)"
        pressed_bg = "rgba(0, 0, 0, 51)" if light else "rgba(255, 255, 255, 51)"

        for btn in (self.titleBar.minBtn, self.titleBar.maxBtn):
            btn.setStyleSheet(f"""
* {{
    qproperty-normalColor: {icon};
    qproperty-hoverColor: {icon};
    qproperty-pressedColor: {icon};
    qproperty-normalBackgroundColor: transparent;
    qproperty-hoverBackgroundColor: {hover_bg};
    qproperty-pressedBackgroundColor: {pressed_bg};
}}""")
            btn.update()

        closeBtn = self.titleBar.closeBtn
        closeBtn.setStyleSheet(f"""
* {{
    qproperty-normalColor: {icon};
    qproperty-normalBackgroundColor: transparent;
    qproperty-hoverColor: white;
    qproperty-hoverBackgroundColor: rgb(232, 17, 35);
    qproperty-pressedColor: white;
    qproperty-pressedBackgroundColor: rgb(241, 112, 122);
}}""")
        closeBtn.update()

    def set_topmost(self, checked):
        self.cfg["topmost"] = bool(checked)
        save_config()
        self.setWindowFlag(Qt.WindowStaysOnTopHint, bool(checked))
        self.show()

    def set_option(self, key, value):
        self.cfg[key] = value
        save_config()

    # ------------------------------------------------------------------
    # 状态与后台结果
    # ------------------------------------------------------------------
    def set_connected(self, ok, status_text, busy=False):
        """统一维护连接状态：冻结/解锁所有控制控件。"""
        CONNECTED["ok"] = ok and not busy
        self.devicePage.set_status(status_text, "#2e8b57" if ok else "#8a8a8a")
        self.devicePage.connectBtn.setEnabled(not busy)
        self.devicePage.disconnectBtn.setEnabled(ok and not busy)
        self.playbackPage.set_available(ok and not busy)
        self.volumePage.set_available(ok and not busy)

    def on_connect_ok(self, ok, msg):
        if ok:
            self.set_connected(True, "设备已连接")
            self.devicePage.addrEdit.setText(self.cfg.get("device", ""))
            self.log(f"连接成功：{msg.splitlines()[0] if msg else ''}")
            self.toast("连接成功", "现在可以用侧键切歌、调节音量了")
            cmd_q.put(("volume_get",))
        else:
            self.set_connected(False, "连接失败")
            self.log(f"连接失败：{msg}")
            self.toast("连接失败", "请检查 USB 调试 / 设备地址", success=False)

    def poll(self):
        while True:
            try:
                label, ok, msg = result_q.get_nowait()
            except Exception:
                break
            self.handle_result(label, ok, msg)
        while True:
            try:
                which, btn = capture_q.get_nowait()
            except Exception:
                break
            self.finish_capture(which, btn)

    def handle_result(self, label, ok, msg):
        if label == "检测设备":
            if ok:
                self.devicePage.devicesLabel.setText(msg or "未检测到设备")
                self.log("已检测设备：\n" + (msg or ""))
            else:
                self.devicePage.devicesLabel.setText(msg or "检测失败")
                self.log("检测设备失败：" + (msg or ""))
        elif label == "连接设备":
            self.on_connect_ok(ok, msg)
        elif label == "断开设备":
            self.set_connected(False, "未连接")
            self.log("已断开设备，所有控制已冻结")
        elif label == "音量同步":
            if ok:
                try:
                    cur, mx = (int(x) for x in msg.split(","))
                    self.volumePage.sync(cur, mx)
                    self.log(f"已读取音量：{cur}/{mx}")
                except Exception:
                    self.log(f"音量解析失败：{msg}")
            else:
                self.log("读取音量失败：" + (msg or ""))
                self.toast("读取音量失败", msg or "", success=False)
        elif label == "音量":
            self.log(f"音量调节{'成功' if ok else '失败'}：{msg}")
            if ok:
                # 回读实际值，避免档位换算误差
                try:
                    cur, mx = (int(x) for x in msg.replace("音量", "").strip().split("/"))
                    self.volumePage.sync(cur, mx)
                except Exception:
                    pass
            else:
                self.toast("音量调节失败", msg or "", success=False)
        else:
            self.log(f"{label}{'成功' if ok else '失败'}：" + (msg or ""))
            if not ok:
                self.toast(f"{label}失败", msg or "", success=False, duration=4000)

    def finish_capture(self, which, binding):
        # 键盘 Esc 取消录制
        if binding == "cancel":
            self.cancel_capture()
            self.log("已取消按键绑定")
            return
        if not is_valid_binding(binding):
            self.cancel_capture()
            self.toast("绑定失败", "无法识别的按键", success=False)
            return

        key = "prev_button" if which == "prev" else "next_button"
        other = "next_button" if which == "prev" else "prev_button"
        if binding == self.cfg.get(other):
            self.cancel_capture()
            name = "上一曲" if which == "prev" else "下一曲"
            other_name = "下一曲" if which == "prev" else "上一曲"
            text = binding_display(binding)
            self.log(f"绑定失败：「{name}」与「{other_name}」不能使用同一个按键（{text}）")
            self.toast("按键重复", f"{text} 已用于「{other_name}」", success=False)
            return

        self.cfg[key] = binding
        save_config()
        self._capture = None
        self.playbackPage.set_capturing(None)
        self.playbackPage.update_bindings()
        self.settingsPage.update_bindings()
        self.set_connected(True, "设备已连接")
        name = "上一曲" if which == "prev" else "下一曲"
        text = binding_display(binding)
        self.log(f"「{name}」已绑定到 {text}")
        self.toast("绑定成功", f"{name} = {text}")

    def closeEvent(self, e):
        self.timer.stop()
        input_hooks.capture_action["which"] = None
        input_hooks.stop_hook()
        cmd_q.put(None)
        save_config()
        super().closeEvent(e)
