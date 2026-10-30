# -*- coding: utf-8 -*-
"""应用页面：连接、播放、音量、日志、设置。仅负责界面表现，业务通过控制器调用。"""

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import QFileDialog, QHBoxLayout, QVBoxLayout, QWidget

from qfluentwidgets import (BodyLabel, CaptionLabel, FluentIcon, LineEdit,
                            PrimaryPushButton, PushButton, ScrollArea,
                            SettingCard, SettingCardGroup, SwitchSettingCard,
                            TextEdit, TitleLabel)

from ..adb import volume_index, volume_percent
from ..config import BINDING_GUIDE, binding_display
from .widgets import Dot, OptionCard, SectionCard, WheelSlider, hint

CAPTURE_HINT = (f"{BINDING_GUIDE}左键用于界面操作，不参与绑定；"
                "录制的键盘按键会被程序独占，建议使用 F1~F12 或 Ctrl/Alt 组合键。")


def money_font_size(label, size=36):
    """设置大号数字字体。

    注意：QFont.setWeight 在 Qt5 只接受 QFont::Weight 枚举（0~87），
    传入 600 这类数值会被当成非法权重，导致数字渲染成方块。
    """
    f = QFont("Segoe UI")
    f.setPointSize(size)
    f.setWeight(QFont.DemiBold)
    label.setFont(f)


class BasePage(ScrollArea):
    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.setObjectName(title.replace(" ", "_"))
        self.view = QWidget()
        self.vBoxLayout = QVBoxLayout(self.view)
        self.vBoxLayout.setContentsMargins(28, 24, 28, 24)
        self.vBoxLayout.setSpacing(16)
        self.setWidget(self.view)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.enableTransparentBackground()

        self.titleLabel = TitleLabel(title, self)
        self.vBoxLayout.addWidget(self.titleLabel)


# ---------------------------------------------------------------------------
# 连接设备
# ---------------------------------------------------------------------------
class DevicePage(BasePage):
    def __init__(self, ctl, parent=None):
        super().__init__("连接设备", parent)
        self.ctl = ctl

        card = SectionCard("设备状态", FluentIcon.CONNECT)
        statusRow = QHBoxLayout()
        self.dot = Dot("#c8a400", 12)
        self.statusLabel = BodyLabel("未连接", card)
        statusRow.addWidget(self.dot)
        statusRow.addWidget(self.statusLabel)
        statusRow.addStretch(1)
        self.connectBtn = PrimaryPushButton(FluentIcon.CONNECT, "连接", card)
        self.connectBtn.clicked.connect(self.ctl.connect)
        self.detectBtn = PushButton(FluentIcon.SYNC, "检测设备", card)
        self.detectBtn.clicked.connect(self.ctl.detect)
        self.disconnectBtn = PushButton(FluentIcon.CANCEL, "断开", card)
        self.disconnectBtn.clicked.connect(self.ctl.disconnect)
        self.disconnectBtn.setEnabled(False)
        statusRow.addWidget(self.detectBtn)
        statusRow.addWidget(self.connectBtn)
        statusRow.addWidget(self.disconnectBtn)
        card.vBoxLayout.addLayout(statusRow)

        addrRow = QHBoxLayout()
        addrRow.setSpacing(8)
        addrRow.addWidget(BodyLabel("设备地址", card))
        self.addrEdit = LineEdit(card)
        self.addrEdit.setPlaceholderText("USB 连接请留空；WiFi 连接填 手机IP:5555")
        self.addrEdit.setText(self.ctl.cfg.get("device", ""))
        self.addrEdit.setClearButtonEnabled(True)
        self.addrEdit.setMinimumWidth(320)
        addrRow.addWidget(self.addrEdit, 1)
        card.vBoxLayout.addLayout(addrRow)
        card.vBoxLayout.addWidget(hint("设备地址会随连接自动保存，下次启动自动带出。", card))

        self.devicesLabel = CaptionLabel("", card)
        self.devicesLabel.setTextColor("#606060", "#a0a0a0")
        self.devicesLabel.setWordWrap(True)
        card.vBoxLayout.addWidget(self.devicesLabel)
        self.vBoxLayout.addWidget(card)

        helpCard = SectionCard("使用步骤", FluentIcon.INFO)
        steps = [
            "1. 手机开启「开发者选项 → USB 调试」，用数据线连接电脑。",
            "2. WiFi 连接时先在手机执行 adb tcpip 5555，再填写「手机IP:5555」。",
            "3. 点击「连接」，状态变绿后即可使用侧键切歌与音量控制。",
            "4. 未连接时界面控件与侧键都会被冻结，不会误操作。",
        ]
        for s in steps:
            helpCard.vBoxLayout.addWidget(hint(s, helpCard))
        self.vBoxLayout.addWidget(helpCard)
        self.vBoxLayout.addStretch(1)

    def set_status(self, text, color):
        self.statusLabel.setText(text)
        self.dot.setColor(color)


# ---------------------------------------------------------------------------
# 播放控制
# ---------------------------------------------------------------------------
class PlaybackPage(BasePage):
    def __init__(self, ctl, parent=None):
        super().__init__("播放控制", parent)
        self.ctl = ctl

        card = SectionCard("播放控制", FluentIcon.MUSIC)
        row = QHBoxLayout()
        row.setSpacing(12)
        self.prevBtn = PushButton(FluentIcon.SKIP_BACK, "上一曲", card)
        self.prevBtn.clicked.connect(lambda: self.ctl.send_key("88", "上一曲"))
        self.playBtn = PrimaryPushButton(FluentIcon.PLAY, "播放 / 暂停", card)
        self.playBtn.clicked.connect(lambda: self.ctl.send_key("85", "播放/暂停"))
        self.nextBtn = PushButton(FluentIcon.SKIP_FORWARD, "下一曲", card)
        self.nextBtn.clicked.connect(lambda: self.ctl.send_key("87", "下一曲"))
        for b in (self.prevBtn, self.playBtn, self.nextBtn):
            b.setMinimumWidth(130)
            row.addWidget(b)
        row.addStretch(1)
        card.vBoxLayout.addLayout(row)
        card.vBoxLayout.addWidget(hint("也可以直接用鼠标侧键，无需窗口处于前台。", card))
        self.vBoxLayout.addWidget(card)

        bindCard = SectionCard("切歌按键绑定", FluentIcon.SPEED_HIGH)
        self.bindLabel = BodyLabel("", bindCard)
        bindCard.vBoxLayout.addWidget(self.bindLabel)

        bindRow = QHBoxLayout()
        bindRow.setSpacing(12)
        self.bindPrevBtn = PushButton(FluentIcon.SKIP_BACK, "设置上一曲", bindCard)
        self.bindPrevBtn.clicked.connect(lambda: self.ctl.request_capture("prev"))
        self.bindNextBtn = PushButton(FluentIcon.SKIP_FORWARD, "设置下一曲", bindCard)
        self.bindNextBtn.clicked.connect(lambda: self.ctl.request_capture("next"))
        self.cancelCaptureBtn = PushButton(FluentIcon.CANCEL, "取消", bindCard)
        self.cancelCaptureBtn.clicked.connect(self.ctl.cancel_capture)
        self.cancelCaptureBtn.setEnabled(False)
        for b in (self.bindPrevBtn, self.bindNextBtn, self.cancelCaptureBtn):
            bindRow.addWidget(b)
        bindRow.addStretch(1)
        bindCard.vBoxLayout.addLayout(bindRow)
        self.captureHint = hint(CAPTURE_HINT, bindCard)
        bindCard.vBoxLayout.addWidget(self.captureHint)
        self.vBoxLayout.addWidget(bindCard)

        mediaCard = SectionCard("鼠标媒体键（推荐）", FluentIcon.HEADPHONE)
        mediaCard.vBoxLayout.addWidget(hint(
            "若鼠标驱动把侧键设置为「上一曲 / 下一曲」，程序会直接接收系统媒体键，"
            "无需额外绑定；此通道与自行录制的鼠标/键盘按键可同时生效：", mediaCard))
        for name, value in (("下一曲", "按侧键 → 手机下一曲"),
                            ("上一曲", "按侧键 → 手机上一曲"),
                            ("播放 / 暂停", "按侧键 → 手机播放/暂停"),
                            ("停止", "按侧键 → 手机停止")):
            kv = QHBoxLayout()
            kv.setSpacing(16)
            key = BodyLabel(name, mediaCard)
            key.setFixedWidth(90)
            kv.addWidget(key)
            kv.addWidget(BodyLabel(value, mediaCard))
            kv.addStretch(1)
            mediaCard.vBoxLayout.addLayout(kv)
        self.vBoxLayout.addWidget(mediaCard)
        self.vBoxLayout.addStretch(1)

        self.update_bindings()

    def update_bindings(self):
        cfg = self.ctl.cfg
        prev = binding_display(cfg.get("prev_button"))
        nxt = binding_display(cfg.get("next_button"))
        self.bindLabel.setText(f"当前：上一曲 = {prev}    下一曲 = {nxt}")

    def set_capturing(self, which):
        active = which is not None
        self.cancelCaptureBtn.setEnabled(active)
        self.bindPrevBtn.setEnabled(not active and self.ctl.is_connected())
        self.bindNextBtn.setEnabled(not active and self.ctl.is_connected())
        if active:
            name = "上一曲" if which == "prev" else "下一曲"
            self.captureHint.setText(
                f"正在等待按键… 请按下要用于「{name}」的鼠标按键或键盘按键"
                f"（可先按住 Ctrl / Alt / Shift；Esc 或「取消」退出）。")
        else:
            self.captureHint.setText(CAPTURE_HINT)

    def set_available(self, ok):
        for b in (self.prevBtn, self.playBtn, self.nextBtn):
            b.setEnabled(ok)
        if not self.cancelCaptureBtn.isEnabled():
            self.bindPrevBtn.setEnabled(ok)
            self.bindNextBtn.setEnabled(ok)


# ---------------------------------------------------------------------------
# 音量
# ---------------------------------------------------------------------------
class VolumePage(BasePage):
    def __init__(self, ctl, parent=None):
        super().__init__("音量", parent)
        self.ctl = ctl
        self._syncing = False
        self._pending = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(200)
        self._timer.timeout.connect(self._flush)
        self.muted = False

        card = SectionCard("音乐音量", FluentIcon.MIX_VOLUMES)

        numRow = QHBoxLayout()
        numRow.setSpacing(6)
        self.valueLabel = TitleLabel("--", card)
        money_font_size(self.valueLabel, 36)
        self.maxLabel = CaptionLabel("", card)
        self.maxLabel.setTextColor("#606060", "#a0a0a0")
        self.maxLabel.setContentsMargins(0, 0, 0, 8)
        numRow.addWidget(self.valueLabel, 0, Qt.AlignBottom)
        numRow.addWidget(self.maxLabel, 0, Qt.AlignBottom)
        numRow.addStretch(1)
        card.vBoxLayout.addLayout(numRow)

        self.slider = WheelSlider(Qt.Horizontal, 1, card)
        self.slider.setRange(0, 100)
        self.slider.setValue(0)
        self._mx = 0  # 手机音量范围的档位上限，用于百分比与档位换算
        self.slider.setMinimumHeight(36)
        self.slider.valueChanged.connect(self.on_slide)
        self.slider.wheelStepped.connect(self.on_wheel)
        card.vBoxLayout.addWidget(self.slider)

        btnRow = QHBoxLayout()
        btnRow.setSpacing(12)
        self.muteBtn = PushButton(FluentIcon.MUTE, "静音", card)
        self.muteBtn.clicked.connect(self.ctl.toggle_mute)
        self.syncBtn = PushButton(FluentIcon.SYNC, "重新读取", card)
        self.syncBtn.clicked.connect(self.ctl.sync_volume)
        btnRow.addWidget(self.muteBtn)
        btnRow.addWidget(self.syncBtn)
        btnRow.addStretch(1)
        card.vBoxLayout.addLayout(btnRow)

        card.vBoxLayout.addWidget(hint(
            "拖动滑杆，或把鼠标放在滑杆上滚动滚轮，按 1% 一档调节；调节为静默下发，手机不会弹音量条。"
            "程序运行时，也可以把鼠标移到任务栏通知区域的托盘图标上滚动滚轮调节音量"
            "（图标被收进「^」浮层时，先把它从浮层拖到任务栏上固定）。", card))
        self.vBoxLayout.addWidget(card)
        self.vBoxLayout.addStretch(1)

    # --- 滑杆逻辑（滑杆值为百分比，0~100）---
    def on_slide(self, value):
        if self._syncing:
            return
        self._pending = int(value)
        self.valueLabel.setText(f"{self._pending}%")
        if not self._timer.isActive():
            self._timer.start()

    def on_wheel(self, step):
        if self._syncing or not self.ctl.is_connected():
            return
        cur = int(self.slider.value())
        self.slider.setValue(max(0, min(100, cur + step)))

    def _flush(self):
        if self._pending is None or not self.ctl.is_connected() or self._mx <= 0:
            return
        target, self._pending = self._pending, None
        self.ctl.set_volume(volume_index(target, self._mx))

    def sync(self, cur, mx):
        self._mx = int(mx)
        pct = volume_percent(cur, mx)
        self._syncing = True
        try:
            self.slider.setRange(0, 100)
            self.slider.setValue(pct)
        finally:
            self._syncing = False
        self.valueLabel.setText(f"{pct}%")
        self.maxLabel.setText(f"档位 {cur}/{mx}")

    def set_available(self, ok):
        for w in (self.slider, self.muteBtn, self.syncBtn):
            w.setEnabled(ok)
        if not ok:
            self._pending = None
            self.valueLabel.setText("--")
            self.maxLabel.setText("")


# ---------------------------------------------------------------------------
# 日志
# ---------------------------------------------------------------------------
class LogPage(BasePage):
    def __init__(self, ctl, parent=None):
        super().__init__("运行日志", parent)
        self.ctl = ctl

        card = SectionCard("日志与错误信息", FluentIcon.DOCUMENT)
        self.edit = TextEdit(card)
        self.edit.setReadOnly(True)
        self.edit.setMinimumHeight(360)
        self.edit.setPlaceholderText("运行信息会显示在这里，可直接选中复制。")
        card.vBoxLayout.addWidget(self.edit)

        row = QHBoxLayout()
        row.setSpacing(12)
        self.copyBtn = PrimaryPushButton(FluentIcon.COPY, "复制全部", card)
        self.copyBtn.clicked.connect(self.copy_all)
        self.clearBtn = PushButton(FluentIcon.BROOM, "清空", card)
        self.clearBtn.clicked.connect(self.edit.clear)
        row.addWidget(self.copyBtn)
        row.addWidget(self.clearBtn)
        row.addStretch(1)
        card.vBoxLayout.addLayout(row)
        self.vBoxLayout.addWidget(card)
        self.vBoxLayout.addStretch(1)

    def append(self, text):
        self.edit.append(text)

    def copy_all(self):
        from PyQt5.QtWidgets import QApplication
        QApplication.clipboard().setText(self.edit.toPlainText())
        self.ctl.toast("已复制", "日志内容已复制到剪贴板", success=True)


# ---------------------------------------------------------------------------
# 设置
# ---------------------------------------------------------------------------
class SettingsPage(BasePage):
    def __init__(self, ctl, parent=None):
        super().__init__("设置", parent)
        self.ctl = ctl

        group = SettingCardGroup("通用", self.view)
        self.themeCard = OptionCard(
            FluentIcon.BRUSH, "界面主题", "跟随系统 / 浅色 / 深色",
            [("跟随系统", "auto"), ("浅色", "light"), ("深色", "dark")],
            self.ctl.cfg.get("theme", "auto"), group)
        self.themeCard.optionChanged.connect(self.ctl.set_theme)
        group.addSettingCard(self.themeCard)

        self.topCard = SwitchSettingCard(
            FluentIcon.BACKGROUND_FILL, "窗口置顶", "让控制窗口始终显示在最前", parent=group)
        self.topCard.setChecked(bool(self.ctl.cfg.get("topmost", True)))
        self.topCard.checkedChanged.connect(self.ctl.set_topmost)
        group.addSettingCard(self.topCard)
        self.vBoxLayout.addWidget(group)

        hookGroup = SettingCardGroup("输入处理", self.view)
        self.swallowBoundCard = SwitchSettingCard(
            FluentIcon.SPEED_MEDIUM, "拦截已绑定的鼠标按键",
            "避免浏览器把侧键当成后退/前进", parent=hookGroup)
        self.swallowBoundCard.setChecked(bool(self.ctl.cfg.get("swallow_bound", False)))
        self.swallowBoundCard.checkedChanged.connect(
            lambda v: self.ctl.set_option("swallow_bound", v))
        hookGroup.addSettingCard(self.swallowBoundCard)

        self.swallowMediaCard = SwitchSettingCard(
            FluentIcon.HEADPHONE, "拦截媒体键",
            "独占媒体键，避免其它音乐软件同时响应", parent=hookGroup)
        self.swallowMediaCard.setChecked(bool(self.ctl.cfg.get("swallow_media_keys", False)))
        self.swallowMediaCard.checkedChanged.connect(
            lambda v: self.ctl.set_option("swallow_media_keys", v))
        hookGroup.addSettingCard(self.swallowMediaCard)
        self.vBoxLayout.addWidget(hookGroup)

        adbGroup = SettingCardGroup("高级", self.view)
        adbCard = SettingCard(FluentIcon.DEVELOPER_TOOLS, "adb 路径",
                              "留空则自动查找 Android SDK 中的 adb.exe", adbGroup)
        self.adbEdit = LineEdit(adbCard)
        self.adbEdit.setPlaceholderText("例如 C:\\platform-tools\\adb.exe")
        self.adbEdit.setText(self.ctl.cfg.get("adb_path", ""))
        self.adbEdit.setMinimumWidth(240)
        browseBtn = PushButton(FluentIcon.FOLDER, "浏览", adbCard)
        browseBtn.clicked.connect(self.browse_adb)
        saveBtn = PushButton(FluentIcon.SAVE, "保存", adbCard)
        saveBtn.clicked.connect(self.save_adb)
        adbCard.hBoxLayout.addWidget(self.adbEdit, 0, Qt.AlignRight)
        adbCard.hBoxLayout.addWidget(browseBtn, 0, Qt.AlignRight)
        adbCard.hBoxLayout.addWidget(saveBtn, 0, Qt.AlignRight)
        adbCard.hBoxLayout.addSpacing(16)
        self.adbCard = adbCard
        adbGroup.addSettingCard(adbCard)
        self.vBoxLayout.addWidget(adbGroup)

        aboutCard = SectionCard("关于", FluentIcon.INFO)
        self.bindNote = BodyLabel("", aboutCard)
        aboutCard.vBoxLayout.addWidget(self.bindNote)
        aboutCard.vBoxLayout.addWidget(hint(
            "手机音乐控制 — PyQt-Fluent-Widgets 界面版本。鼠标/键盘切歌绑定与系统媒体键通道"
            "可同时生效，音量与播放控制均通过 adb 下发。", aboutCard))
        self.vBoxLayout.addWidget(aboutCard)
        self.vBoxLayout.addStretch(1)
        self.update_bindings()

    def update_bindings(self):
        """刷新「切歌按键」说明（绑定变化后由主窗口调用）。"""
        prev = binding_display(self.ctl.cfg.get("prev_button"))
        nxt = binding_display(self.ctl.cfg.get("next_button"))
        self.bindNote.setText(f"切歌按键：上一曲 = {prev}，下一曲 = {nxt}")

    def browse_adb(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择 adb.exe", "", "adb (adb.exe);;所有文件 (*)")
        if path:
            self.adbEdit.setText(path)

    def save_adb(self):
        self.ctl.set_option("adb_path", self.adbEdit.text().strip())
        self.ctl.toast("已保存", "adb 路径已更新", success=True)
