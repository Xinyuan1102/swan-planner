"""右栏(下) · 分层规划推理链。

自上而下渲染 L1(全局规划)→ L2(分组协调)→ L3(平台执行)三层,
每层标注所用模型,并强调"LLM 不入控制环"。
"""
from __future__ import annotations
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                               QScrollArea, QFrame, QSizePolicy)
from PySide6.QtCore import Qt

from ..config import C
from ..models.mock_llm import PlanResult, ReasoningNode, TaskItem
from .common import Card


def _rich(text: str) -> str:
    """把 mock 推理文本里的简易标记转成 HTML。"""
    return (text.replace("<b>", f"<b style='color:{C.TEXT}'>")
                .replace("<kv>", f"<span style='color:{C.AIR}'>")
                .replace("</kv>", "</span>"))


class TaskLine(QFrame):
    def __init__(self, item: TaskItem):
        super().__init__()
        color = C.GROUP.get(item.group_id, C.SYS)
        self.setStyleSheet(
            f"QFrame{{background:#0F1A28;border:1px solid {C.LINE_SOFT};"
            f"border-left:3px solid {color};border-radius:6px;}}")
        lay = QHBoxLayout(self); lay.setContentsMargins(10, 7, 10, 7); lay.setSpacing(8)
        tag = QLabel(item.tag)
        tag.setStyleSheet(f"font-family:monospace;font-weight:600;font-size:10px;color:{C.TEXT};")
        lay.addWidget(tag)
        obj = QLabel(item.objective); obj.setWordWrap(True)
        obj.setStyleSheet(f"color:{C.MUTED};font-size:11px;")
        lay.addWidget(obj, 1)
        if item.priority:
            pri = QLabel(item.priority)
            pri.setStyleSheet(
                f"color:{C.WARN};border:1px solid rgba(240,180,41,0.27);"
                f"border-radius:4px;padding:1px 5px;font-size:9px;")
            lay.addWidget(pri)


class SkillChip(QLabel):
    def __init__(self, text: str, ground=False):
        super().__init__(text)
        color = C.GROUND if ground else C.AIR
        self.setStyleSheet(
            f"color:{color};background:rgba(255,255,255,0.02);"
            f"border:1px solid {color};border-radius:5px;padding:3px 7px;"
            f"font-family:monospace;font-size:10px;")


class LayerNode(QWidget):
    """推理链中的一层(带左侧竖轴与圆形层级标记)。"""
    def __init__(self, node: ReasoningNode, is_last: bool):
        super().__init__()
        color = {"L1": C.SYS, "L2": C.OK, "L3": C.AIR}[node.layer]
        root = QHBoxLayout(self); root.setContentsMargins(0, 0, 0, 14); root.setSpacing(0)

        # 左侧轴 + 标记
        rail = QVBoxLayout(); rail.setContentsMargins(2, 3, 11, 0); rail.setSpacing(0)
        marker = QLabel(node.layer.replace("L", ""))
        marker.setFixedSize(18, 18); marker.setAlignment(Qt.AlignCenter)
        marker.setStyleSheet(
            f"background:{color};color:#0B111B;border-radius:9px;"
            f"font-weight:700;font-size:9px;font-family:monospace;")
        rail.addWidget(marker)
        if not is_last:
            line = QFrame(); line.setFixedWidth(2)
            line.setStyleSheet(f"background:{C.LINE};")
            line.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
            wrap = QHBoxLayout(); wrap.setContentsMargins(8, 4, 0, 0)
            wrap.addWidget(line)
            rail.addLayout(wrap, 1)
        root.addLayout(rail)

        # 右侧内容
        col = QVBoxLayout(); col.setSpacing(7)
        head = QHBoxLayout(); head.setSpacing(8)
        title = QLabel(node.title); title.setStyleSheet("font-weight:600;font-size:12px;")
        head.addWidget(title); head.addStretch(1)
        model = QLabel(node.model)
        model.setStyleSheet(
            f"color:{C.DIM};font-family:monospace;font-size:9px;"
            f"border:1px solid {C.LINE_SOFT};border-radius:5px;padding:2px 6px;")
        head.addWidget(model)
        col.addLayout(head)

        think = QLabel(_rich(node.think)); think.setWordWrap(True)
        think.setTextFormat(Qt.RichText)
        think.setStyleSheet(
            f"background:#0E1826;border:1px solid {C.LINE_SOFT};border-radius:8px;"
            f"padding:9px 11px;color:{C.MUTED};font-size:11px;")
        col.addWidget(think)

        for item in node.tasks:
            col.addWidget(TaskLine(item))

        if node.skills:
            flow = QHBoxLayout(); flow.setSpacing(5); flow.setContentsMargins(0, 2, 0, 0)
            wrapf = QWidget(); wrapf.setLayout(flow)
            ground = "UGV" in node.title
            for s in node.skills:
                flow.addWidget(SkillChip(s, ground))
            flow.addStretch(1)
            col.addWidget(wrapf)

        root.addLayout(col, 1)


class ReasoningChain(Card):
    def __init__(self):
        super().__init__("分层规划推理链", icon="⛓")
        self.scope = QLabel("全局 · A 组"); self.scope.setObjectName("CardSub")
        self.add_header_widget(self.scope)

        self.scroll = QScrollArea(); self.scroll.setWidgetResizable(True)
        self._inner = QWidget()
        self._v = QVBoxLayout(self._inner)
        self._v.setContentsMargins(12, 10, 12, 12); self._v.setSpacing(0)
        self._v.addStretch(1)
        self.scroll.setWidget(self._inner)
        self.body.addWidget(self.scroll)

    def render_plan(self, result: PlanResult, scope_text: str):
        self.scope.setText(scope_text)
        # 清空
        while self._v.count():
            it = self._v.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        for i, node in enumerate(result.chain):
            self._v.addWidget(LayerNode(node, is_last=(i == len(result.chain) - 1)))
        self._v.addStretch(1)
