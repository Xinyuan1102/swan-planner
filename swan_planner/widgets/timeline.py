"""底部 · 分层执行时间线。

用甘特图呈现三层活动(L1 全局 / L2 分组 / L3 执行)在时间轴上的展开,
体现事件驱动特征:L1 仅在开头做一次分组,L2/L3 持续执行。
"""
from __future__ import annotations
from PySide6.QtWidgets import QFrame, QHBoxLayout, QVBoxLayout, QLabel, QWidget
from PySide6.QtGui import QPainter, QColor, QPen, QFont
from PySide6.QtCore import Qt, QRectF

from ..config import C
from .common import Dot

# (轨道名, [(start%, width%, color, 文本)])
TRACKS = [
    ("A组·侦察", [(2, 14, C.SYS, "分组"), (17, 20, C.OK, "扇区编排"),
                 (38, 40, C.AIR, "扫描 · 跟踪")]),
    ("B组·运输", [(2, 14, C.SYS, "分组"), (17, 16, C.OK, "路径协同"),
                 (34, 50, C.GROUND, "空地运输 · 中继补盲")]),
    ("C组·预备", [(2, 82, "#2A3A4E", "待命(可被 L1 动态调用)")]),
]
GRID_LABELS = ["T+0", "+10m", "+20m", "+30m", "+40m", "+50m"]
NOW_PCT = 46


class Gantt(QWidget):
    def __init__(self):
        super().__init__()
        self.setMinimumHeight(84)

    def paintEvent(self, e):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        left, right, top = 78, 16, 18
        lane_w = w - left - right
        row_h = 20; gap = 6

        # 网格竖线 + 刻度
        p.setFont(QFont("IBM Plex Mono", 8))
        for i, lab in enumerate(GRID_LABELS):
            gx = left + lane_w * i / (len(GRID_LABELS) - 1)
            p.setPen(QPen(QColor(C.LINE_SOFT), 1, Qt.DashLine))
            p.drawLine(gx, top, gx, h - 4)
            p.setPen(QColor(C.DIM))
            p.drawText(QRectF(gx + 3, 2, 60, 12), Qt.AlignLeft, lab)

        # 轨道
        for r, (name, segs) in enumerate(TRACKS):
            y = top + r * (row_h + gap)
            p.setPen(QColor(C.MUTED)); p.setFont(QFont("IBM Plex Mono", 8))
            p.drawText(QRectF(0, y, left - 6, row_h), Qt.AlignVCenter | Qt.AlignLeft, name)
            # lane 背景
            p.setPen(Qt.NoPen); p.setBrush(QColor("#0E1826"))
            p.drawRoundedRect(QRectF(left, y + 3, lane_w, 14), 4, 4)
            # 段
            for sx, sw, col, text in segs:
                rx = left + lane_w * sx / 100
                rw = lane_w * sw / 100
                p.setBrush(QColor(col))
                p.drawRoundedRect(QRectF(rx, y + 3, rw, 14), 4, 4)
                p.setPen(QColor("#0B111B") if col != "#2A3A4E" else QColor(C.MUTED))
                p.setFont(QFont("Inter", 8, QFont.DemiBold))
                p.drawText(QRectF(rx + 6, y + 3, rw - 8, 14),
                           Qt.AlignVCenter | Qt.AlignLeft, text)
                p.setPen(Qt.NoPen)

        # NOW 指示线
        nx = left + lane_w * NOW_PCT / 100
        p.setPen(QPen(QColor(C.ALERT), 2))
        p.drawLine(nx, top - 2, nx, h - 4)
        p.setBrush(QColor(C.ALERT)); p.setPen(Qt.NoPen)
        p.drawEllipse(QRectF(nx - 4, top - 6, 8, 8))


class Timeline(QFrame):
    def __init__(self):
        super().__init__()
        self.setObjectName("Card")
        self.setFixedHeight(120)
        lay = QHBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(0)

        # 左侧说明
        side = QFrame(); side.setFixedWidth(150)
        side.setStyleSheet(f"border-right:1px solid {C.LINE_SOFT};")
        sv = QVBoxLayout(side); sv.setContentsMargins(13, 11, 13, 11); sv.setSpacing(8)
        t = QLabel("执行时间线"); t.setStyleSheet("font-weight:600;font-size:12px;")
        sv.addWidget(t)
        for color, text in [(C.SYS, "L1 全局规划"), (C.OK, "L2 分组协调"),
                            (C.AIR, "L3 平台执行")]:
            row = QHBoxLayout(); row.setSpacing(7)
            row.addWidget(Dot(color)); lab = QLabel(text)
            lab.setStyleSheet(f"color:{C.MUTED};font-size:10px;"); row.addWidget(lab)
            row.addStretch(1)
            box = QWidget(); box.setLayout(row); sv.addWidget(box)
        sv.addStretch(1)
        lay.addWidget(side)

        lay.addWidget(Gantt(), 1)
