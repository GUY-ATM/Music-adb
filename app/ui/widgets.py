# -*- coding: utf-8 -*-
"""通用界面小部件与样式辅助。"""

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor, QPainter
from PyQt5.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from qfluentwidgets import (ComboBox, CaptionLabel, IconWidget, SettingCard,
                            SimpleCardWidget, Slider, SubtitleLabel)


class SectionCard(SimpleCardWidget):
    """带标题的卡片容器：标题行(图标+标题) + 内容区。"""

    def __init__(self, title, icon=None, parent=None):
        super().__init__(parent)
        self.vBoxLayout = QVBoxLayout(self)
        self.vBoxLayout.setContentsMargins(18, 16, 18, 16)
        self.vBoxLayout.setSpacing(12)

        header = QHBoxLayout()
        header.setSpacing(8)
        if icon is not None:
            self.iconWidget = IconWidget(icon, self)
            self.iconWidget.setFixedSize(18, 18)
            header.addWidget(self.iconWidget)
        self.titleLabel = SubtitleLabel(title, self)
        header.addWidget(self.titleLabel)
        header.addStretch(1)
        self.headerLayout = header
        self.vBoxLayout.addLayout(header)


class Dot(QWidget):
    """状态圆点。"""

    def __init__(self, color="#8a8a8a", size=12, parent=None):
        super().__init__(parent)
        self._color = QColor(color)
        self.setFixedSize(size, size)

    def setColor(self, color):
        self._color = QColor(color)
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(self._color)
        p.drawEllipse(1, 1, self.width() - 2, self.height() - 2)


class WheelSlider(Slider):
    """支持鼠标滚轮调节的滑杆（滚轮步进通过信号交给页面处理）。"""

    wheelStepped = pyqtSignal(int)

    def __init__(self, orientation=Qt.Horizontal, step=5, parent=None):
        super().__init__(orientation, parent)
        self._step = step
        self.setMinimumHeight(32)

    def wheelEvent(self, e):
        d = e.angleDelta().y()
        if d > 0:
            self.wheelStepped.emit(self._step)
        elif d < 0:
            self.wheelStepped.emit(-self._step)
        e.accept()


class OptionCard(SettingCard):
    """下拉选择设置卡（不依赖 qconfig，直接回调）。"""

    optionChanged = pyqtSignal(object)

    def __init__(self, icon, title, content, options, current, parent=None):
        super().__init__(icon, title, content, parent)
        self.comboBox = ComboBox(self)
        self.comboBox.setMinimumWidth(140)
        for label, value in options:
            self.comboBox.addItem(label, userData=value)
        self.comboBox.setCurrentIndex(max(0, [v for _, v in options].index(current))
                                      if current in [v for _, v in options] else 0)
        self.hBoxLayout.addWidget(self.comboBox, 0, Qt.AlignRight)
        self.hBoxLayout.addSpacing(16)
        self.comboBox.currentIndexChanged.connect(
            lambda _i: self.optionChanged.emit(self.comboBox.currentData()))

    def value(self):
        return self.comboBox.currentData()


class HLine(QWidget):
    """细分隔线。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(1)
        self.setAutoFillBackground(True)
        self.setStyleSheet("background: rgba(120,120,120,40);")


def hint(text, parent=None):
    lbl = CaptionLabel(text, parent)
    lbl.setTextColor("#606060", "#a0a0a0")
    lbl.setWordWrap(True)
    return lbl
