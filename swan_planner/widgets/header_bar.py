"""顶部头部栏:品牌标识、当前任务、作战时钟、告警、人在回路开关。"""
from __future__ import annotations
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QVBoxLayout, QLabel, QWidget,
                               QCheckBox)
from PySide6.QtCore import Qt, QTimer, QTime

from ..config import C, APP_NAME, APP_SUBTITLE


class BrandMark(QLabel):
    def __init__(self):
        super().__init__()
        self.setFixedSize(30, 30)
        self.setStyleSheet(
            f"border-radius:8px;"
            f"background:qlineargradient(x1:0,y1:0,x2:1,y2:1,"
            f"stop:0 {C.AIR}, stop:1 {C.SYS});")


class HeaderBar(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Header")
        self.setFixedHeight(58)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(18, 0, 18, 0)
        lay.setSpacing(18)

        # 品牌
        brand = QHBoxLayout(); brand.setSpacing(11)
        brand.addWidget(BrandMark())
        col = QVBoxLayout(); col.setSpacing(1)
        b = QLabel(APP_NAME); b.setObjectName("Brand")
        s = QLabel(APP_SUBTITLE); s.setObjectName("BrandSub")
        col.addWidget(b); col.addWidget(s)
        brand.addLayout(col)
        lay.addLayout(brand)

        # 任务盒
        mbox = QFrame(); mbox.setObjectName("MissionBox")
        mb = QHBoxLayout(mbox); mb.setContentsMargins(14, 6, 14, 6); mb.setSpacing(14)
        mcol = QVBoxLayout(); mcol.setSpacing(1)
        mcol.addWidget(self._lbl("当前任务", "MissionLabel"))
        mcol.addWidget(self._lbl("侦察-运输联合行动", "MissionName"))
        mb.addLayout(mcol)
        pill = QLabel("● 执行中"); pill.setObjectName("Pill")
        mb.addWidget(pill)
        lay.addWidget(mbox)

        lay.addStretch(1)

        # 告警
        alert = QLabel("⚠  告警  2"); alert.setObjectName("Alert")
        lay.addWidget(alert)

        # 时钟
        clockcol = QVBoxLayout(); clockcol.setSpacing(0)
        clockcol.addWidget(self._lbl("作战时钟", "MissionLabel"))
        self.clock = QLabel("00:00:00"); self.clock.setObjectName("Clock")
        clockcol.addWidget(self.clock)
        lay.addLayout(clockcol)

        # 人在回路
        self.hil = QCheckBox("人在回路审核")
        self.hil.setChecked(True)
        self.hil.setCursor(Qt.PointingHandCursor)
        lay.addWidget(self.hil)

        # 计时器
        self._t = QTime(0, 0, 0)
        timer = QTimer(self); timer.timeout.connect(self._tick); timer.start(1000)

    def _lbl(self, text, obj):
        l = QLabel(text); l.setObjectName(obj); return l

    def _tick(self):
        self._t = self._t.addSecs(1)
        self.clock.setText(self._t.toString("HH:mm:ss"))
