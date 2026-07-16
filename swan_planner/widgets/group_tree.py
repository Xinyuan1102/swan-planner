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


class SquadRow(QFrame):
    """分队聚合行:角色 + 台数 + 机型构成 + 缺编标记。"""
    def __init__(self, sq):
        super().__init__()
        kinds = {}
        for m in sq.members:
            kinds[m.pid[:5]] = kinds.get(m.pid[:5], 0) + 1
        air = sum(1 for m in sq.members if m.kind == "air")
        accent = C.AIR if air > len(sq.members) / 2 else C.GROUND
        if not sq.members:
            accent = C.ALERT
        self.setStyleSheet(
            "QFrame{background:#0F1A28;border:1px solid %s;border-left:3px solid %s;"
            "border-radius:6px;}" % (C.LINE_SOFT, accent))
        lay = QHBoxLayout(self); lay.setContentsMargins(8, 5, 8, 5); lay.setSpacing(8)

        name = QLabel(sq.label)
        name.setStyleSheet("font-size:11px;font-weight:600;")
        lay.addWidget(name)

        cnt = QLabel("×%d" % len(sq.members))
        cnt.setStyleSheet("font-family:monospace;font-size:11px;color:%s;" % accent)
        lay.addWidget(cnt)
        lay.addStretch(1)

        comp = QLabel(" ".join("%s×%d" % (k, v) for k, v in sorted(kinds.items())))
        comp.setStyleSheet("font-family:monospace;font-size:9px;color:%s;" % C.DIM)
        lay.addWidget(comp)

        if sq.shortfall:
            sf = QLabel("缺%d" % sq.shortfall)
            sf.setStyleSheet(
                "color:%s;border:1px solid %s;border-radius:4px;"
                "padding:0 4px;font-size:9px;" % (C.ALERT, C.ALERT))
            lay.addWidget(sf)


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

        # 成员:100 台规模下按"分队"聚合展示,不逐台罗列
        body = QWidget()
        b = QVBoxLayout(body); b.setContentsMargins(9, 0, 9, 9); b.setSpacing(5)
        squads = getattr(g, "squads", None)
        if squads:
            for sq in squads:
                if sq.members or sq.shortfall:
                    b.addWidget(SquadRow(sq))
        else:
            for m in g.members[:6]:
                b.addWidget(UnitRow(m))
            if len(g.members) > 6:
                more = QLabel("… 另 %d 台" % (len(g.members) - 6))
                more.setStyleSheet("color:%s;font-size:10px;padding-left:4px;" % C.DIM)
                b.addWidget(more)
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

    def __init__(self, groups: list[Group] = None):
        super().__init__("集群编组", icon="◈")
        tier = QLabel("顶层 · Qwen3.6-27B"); tier.setObjectName("TierTag")
        self.add_header_widget(tier)

        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        self._inner = QWidget()
        self._v = QVBoxLayout(self._inner)
        self._v.setContentsMargins(8, 8, 8, 8); self._v.setSpacing(8)
        self._v.addStretch(1)
        scroll.setWidget(self._inner)
        self.body.addWidget(scroll)

        self._cards: dict[str, GroupCard] = {}
        self._selected: str | None = None
        if groups:
            self.set_groups(groups)

    def set_groups(self, groups: list[Group]):
        """用分配结果重建分组卡片(保持当前选中项若仍存在)。"""
        # 清空现有卡片(保留末尾 stretch)
        while self._v.count() > 1:
            it = self._v.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        self._cards.clear()
        for i, g in enumerate(groups):
            card = GroupCard(g)
            card.clicked.connect(self._on_select)
            self._cards[g.gid] = card
            self._v.insertWidget(i, card)
        # 选中项:沿用旧的,否则选第一个
        keep = self._selected if self._selected in self._cards else (
            groups[0].gid if groups else None)
        if keep:
            self._on_select(keep)

    def _on_select(self, gid: str):
        self._selected = gid
        for k, c in self._cards.items():
            c.set_selected(k == gid)
        self.groupSelected.emit(gid)
