"""右栏(上) · 任务下达。

自然语言指令输入 → 触发 mock 规划器 → 输出结构化分层方案。
"""
from __future__ import annotations
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QTextEdit,
                               QPushButton, QLabel)
from PySide6.QtCore import Qt, Signal

from ..config import C
from .common import Card

DEFAULT_CMD = ("侦察 A 区域并定位可疑目标,同时保障 B 点的物资运输,"
               "全程规避已知禁飞区。")


class TaskPanel(Card):
    planRequested = Signal(str)   # 发出待规划的指令文本

    def __init__(self):
        super().__init__("任务下达", icon="✎", sub="自然语言 → 结构化方案")

        wrap = QWidget()
        v = QVBoxLayout(wrap); v.setContentsMargins(13, 12, 13, 13); v.setSpacing(10)

        self.cmd = QTextEdit(); self.cmd.setObjectName("Cmd")
        self.cmd.setPlainText(DEFAULT_CMD)
        self.cmd.setFixedHeight(70)
        v.addWidget(self.cmd)

        chips = QHBoxLayout(); chips.setSpacing(8)
        for t in ["＋ 附加约束", "载入场景图", "资源清单"]:
            b = QPushButton(t); b.setObjectName("Chip"); b.setCursor(Qt.PointingHandCursor)
            chips.addWidget(b)
        chips.addStretch(1)
        v.addLayout(chips)

        row = QHBoxLayout(); row.setSpacing(8)
        self.gen = QPushButton("⟳  生成分组方案"); self.gen.setObjectName("Primary")
        self.gen.setCursor(Qt.PointingHandCursor)
        self.gen.clicked.connect(self._emit)
        self.review = QPushButton("审核下发"); self.review.setObjectName("Ghost")
        self.review.setCursor(Qt.PointingHandCursor)
        self.review.setToolTip("人在回路:需指挥员确认后下发")
        row.addWidget(self.gen, 1); row.addWidget(self.review)
        v.addLayout(row)

        self.body.addWidget(wrap)
        self.body.addStretch(1)

    def _emit(self):
        self.planRequested.emit(self.cmd.toPlainText().strip())

    def set_generating(self, on: bool):
        self.gen.setEnabled(not on)
        self.gen.setText("⟳  规划中…" if on else "⟳  生成分组方案")
