"""左栏 · 集群编组(顶层规划器输出)。

以卡片形式展示各组及其成员平台,空/地平台双色编码。
点击某组会发出 groupSelected 信号,联动地图与推理链。
"""
from __future__ import annotations
from PySide6.QtWidgets import (QFrame, QVBoxLayout, QHBoxLayout, QLabel, QWidget,
                               QScrollArea)
from PySide6.QtCore import Qt, Signal

from ..config import C
from ..models.data import Group, Platform
from .common import Card


class UnitRow(QFrame):
    def __init__(self, p: Platform):
        super().__init__()
        accent = C.AIR if p.kind == "air" else C.GROUND
        self.setStyleSheet(
            f"QFrame{{background:#0F1A28;border:1px solid {C.LINE_SOFT};border-radius:7px;}}")
        lay = QHBoxLayout(self); lay.setContentsMargins(9, 6, 9, 6); lay.setSpacing(9)

        icon = QLabel("✈" if p.kind == "air" else "▣")
        icon.setFixedSize(22, 22); icon.setAlignment(Qt.AlignCenter)
        icon.setStyleSheet(
            f"color:{accent};background:rgba(255,255,255,0.03);"
            f"border:1px solid {accent};border-radius:6px;font-size:11px;")
        lay.addWidget(icon)

        col = QVBoxLayout(); col.setSpacing(1)
        name = QLabel(p.pid); name.setStyleSheet(f"font-family:monospace;font-size:12px;font-weight:600;")
        spec = QLabel(p.spec); spec.setStyleSheet(f"color:{C.DIM};font-size:10px;")
        col.addWidget(name); col.addWidget(spec)
        lay.addLayout(col)
        lay.addStretch(1)

        stat = QVBoxLayout(); stat.setSpacing(1); stat.setAlignment(Qt.AlignRight)
        bat_color = C.WARN if p.battery < 35 else C.MUTED
        bat = QLabel(f"{p.battery}%")
        bat.setStyleSheet(f"font-family:monospace;font-size:11px;color:{bat_color};")
        bat.setAlignment(Qt.AlignRight)
        st_color = C.OK if not p.busy else C.AIR
        st = QLabel(p.status); st.setStyleSheet(f"color:{st_color};font-size:10px;")
        st.setAlignment(Qt.AlignRight)
        stat.addWidget(bat); stat.addWidget(st)
        lay.addLayout(stat)


class GroupCard(QFrame):
    clicked = Signal(str)

    def __init__(self, g: Group):
        super().__init__()
        self.gid = g.gid
        self._color = C.GROUP.get(g.gid, C.SYS)
        self._selected = False
        self.setCursor(Qt.PointingHandCursor)
        self._apply_style()

        lay = QVBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(0)

        # 头部
        head = QWidget()
        h = QHBoxLayout(head); h.setContentsMargins(11, 10, 11, 8); h.setSpacing(9)
        bar = QLabel(); bar.setFixedSize(3, 30)
        bar.setStyleSheet(f"background:{self._color};border-radius:2px;")
        h.addWidget(bar)
        col = QVBoxLayout(); col.setSpacing(1)
        name = QLabel(g.name); name.setStyleSheet("font-weight:600;font-size:13px;")
        task = QLabel(g.task); task.setStyleSheet(f"color:{C.MUTED};font-size:10px;")
        col.addWidget(name); col.addWidget(task)
        h.addLayout(col); h.addStretch(1)
        n_air = sum(1 for m in g.members if m.kind == "air")
        n_gnd = sum(1 for m in g.members if m.kind == "ground")
        parts = ([f"{n_air} UAV"] if n_air else []) + ([f"{n_gnd} UGV"] if n_gnd else [])
        cnt = QLabel(" · ".join(parts)); cnt.setStyleSheet(f"color:{C.DIM};font-size:10px;font-family:monospace;")
        h.addWidget(cnt)
        lay.addWidget(head)

        # 成员
        body = QWidget()
        b = QVBoxLayout(body); b.setContentsMargins(9, 0, 9, 9); b.setSpacing(6)
        for m in g.members:
            b.addWidget(UnitRow(m))
        lay.addWidget(body)

    def _apply_style(self):
        border = self._color if self._selected else C.LINE_SOFT
        glow = f"border:1px solid {border};"
        self.setStyleSheet(
            f"GroupCard{{background:{C.PANEL2};border-radius:9px;{glow}}}")

    def set_selected(self, on: bool):
        self._selected = on
        self._apply_style()

    def mousePressEvent(self, e):
        self.clicked.emit(self.gid)
        super().mousePressEvent(e)


class GroupTree(Card):
    groupSelected = Signal(str)

    def __init__(self, groups: list[Group]):
        super().__init__("集群编组", icon="◈")
        tier = QLabel("顶层 · Qwen3.6-27B"); tier.setObjectName("TierTag")
        self.add_header_widget(tier)

        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        inner = QWidget()
        v = QVBoxLayout(inner); v.setContentsMargins(8, 8, 8, 8); v.setSpacing(8)
        self._cards: dict[str, GroupCard] = {}
        for g in groups:
            card = GroupCard(g)
            card.clicked.connect(self._on_select)
            self._cards[g.gid] = card
            v.addWidget(card)
        v.addStretch(1)
        scroll.setWidget(inner)
        self.body.addWidget(scroll)

        if groups:
            self._on_select(groups[0].gid)

    def _on_select(self, gid: str):
        for k, c in self._cards.items():
            c.set_selected(k == gid)
        self.groupSelected.emit(gid)
