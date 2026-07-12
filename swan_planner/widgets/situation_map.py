"""中央 · 态势总览地图。

基于 QGraphicsView 绘制:栅格背景、任务区域、平台标记、路径规划、场景图。
支持三种视图切换:态势 / 路径规划 / 场景图。
"""
from __future__ import annotations
from PySide6.QtWidgets import (QGraphicsView, QGraphicsScene, QGraphicsItemGroup,
                               QGraphicsPolygonItem, QGraphicsPathItem,
                               QGraphicsEllipseItem, QGraphicsLineItem,
                               QGraphicsSimpleTextItem, QFrame, QVBoxLayout,
                               QHBoxLayout, QLabel, QPushButton, QButtonGroup, QWidget)
from PySide6.QtGui import (QPen, QBrush, QColor, QPolygonF, QPainterPath, QPainter,
                           QFont)
from PySide6.QtCore import Qt, QPointF, QRectF

from ..config import C
from ..models.data import (Group, Zone, SceneNode, seed_zones, seed_scene_graph)
from .common import Card, Dot

W, H = 900.0, 560.0   # 场景逻辑尺寸


def _pen(color, width=1.2, dash=None):
    p = QPen(QColor(color)); p.setWidthF(width); p.setCosmetic(True)
    if dash:
        p.setDashPattern(dash)
    return p


class MapView(QGraphicsView):
    def __init__(self, groups: list[Group]):
        self._scene = QGraphicsScene(0, 0, W, H)
        super().__init__(self._scene)
        self.setRenderHint(QPainter.Antialiasing)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setStyleSheet(f"border:none;background:#0A1019;")
        self._groups = groups

        self._draw_grid()
        self._layer_zones = self._draw_zones()
        self._layer_paths = self._draw_paths()
        self._layer_graph = self._draw_graph()
        self._draw_platforms()          # 平台始终显示

        self.set_view("sit")

    # ---- 背景栅格 ----
    def _draw_grid(self):
        self._scene.setBackgroundBrush(QColor("#0A1019"))
        pen = _pen("#152233", 1)
        step = 45
        x = 0
        while x <= W:
            self._scene.addLine(x, 0, x, H, pen); x += step
        y = 0
        while y <= H:
            self._scene.addLine(0, y, W, y, pen); y += step

    def _poly(self, zone: Zone) -> QPolygonF:
        return QPolygonF([QPointF(px * W, py * H) for px, py in zone.poly])

    # ---- 区域 ----
    def _draw_zones(self) -> QGraphicsItemGroup:
        grp = QGraphicsItemGroup(); self._scene.addItem(grp)
        for z in seed_zones():
            item = QGraphicsPolygonItem(self._poly(z))
            fill = QColor(z.color); fill.setAlphaF(0.06)
            item.setBrush(QBrush(fill))
            dash = [3, 4] if z.zid == "NF" else [6, 5]
            item.setPen(_pen(z.color, 1.4, dash))
            grp.addToGroup(item)
            # 标签
            fx, fy = z.poly[0]
            lab = QGraphicsSimpleTextItem(z.label)
            lab.setBrush(QColor(z.color)); lab.setFont(QFont("Space Grotesk", 11, QFont.DemiBold))
            lab.setPos(fx * W + 10, fy * H + 8)
            grp.addToGroup(lab)
            sub = QGraphicsSimpleTextItem(z.tag)
            sub.setBrush(QColor(z.color).lighter(120))
            sub.setFont(QFont("IBM Plex Mono", 8))
            sub.setPos(fx * W + 10, fy * H + 26)
            grp.addToGroup(sub)
        return grp

    # ---- 路径 ----
    def _draw_paths(self) -> QGraphicsItemGroup:
        grp = QGraphicsItemGroup(); self._scene.addItem(grp)
        specs = [
            ((0.23, 0.54), (0.28, 0.20), C.AIR, 1.6),
            ((0.23, 0.54), (0.36, 0.27), C.AIR, 1.6),
            ((0.20, 0.84), (0.78, 0.75), C.GROUND, 2.0),
        ]
        for (sx, sy), (ex, ey), col, w in specs:
            path = QPainterPath(QPointF(sx * W, sy * H))
            cx, cy = (sx + ex) / 2 * W, min(sy, ey) * H - 30
            path.quadTo(QPointF(cx, cy), QPointF(ex * W, ey * H))
            item = QGraphicsPathItem(path)
            item.setPen(_pen(col, w, [5, 5]))
            grp.addToGroup(item)
        return grp

    # ---- 场景图 ----
    def _draw_graph(self) -> QGraphicsItemGroup:
        grp = QGraphicsItemGroup(); self._scene.addItem(grp)
        nodes, edges = seed_scene_graph()
        pos = {n.nid: (n.x * W, n.y * H) for n in nodes}
        for a, b in edges:
            ax, ay = pos[a]; bx, by = pos[b]
            ln = QGraphicsLineItem(ax, ay, bx, by)
            ln.setPen(_pen("#3A4C63", 1.2))
            grp.addToGroup(ln)
        color_map = {"target": C.ALERT, "route": C.GROUND, "origin": C.OK, "object": C.SYS}
        for n in nodes:
            x, y = pos[n.nid]
            ring = QColor(color_map.get(n.kind, C.SYS))
            dot = QGraphicsEllipseItem(x - 6, y - 6, 12, 12)
            dot.setBrush(QBrush(QColor("#16212F"))); dot.setPen(_pen(ring.name(), 1.5))
            grp.addToGroup(dot)
            lab = QGraphicsSimpleTextItem(n.label)
            lab.setBrush(QColor(C.MUTED)); lab.setFont(QFont("IBM Plex Mono", 8))
            lab.setPos(x + 10, y - 8)
            grp.addToGroup(lab)
            if n.conf is not None:
                cf = QGraphicsSimpleTextItem(f"conf {n.conf:.2f}")
                cf.setBrush(QColor(C.ALERT)); cf.setFont(QFont("IBM Plex Mono", 8))
                cf.setPos(x + 10, y + 5)
                grp.addToGroup(cf)
        return grp

    # ---- 平台标记 ----
    def _draw_platforms(self):
        for g in self._groups:
            for p in g.members:
                x, y = p.x * W, p.y * H
                col = C.AIR if p.kind == "air" else C.GROUND
                if p.status == "待命":
                    col = "#3A4C63"
                if p.kind == "air":
                    tri = QPolygonF([QPointF(x, y - 9), QPointF(x + 8, y + 7), QPointF(x - 8, y + 7)])
                    item = QGraphicsPolygonItem(tri)
                else:
                    item = QGraphicsPolygonItem(QPolygonF([
                        QPointF(x - 7, y - 7), QPointF(x + 7, y - 7),
                        QPointF(x + 7, y + 7), QPointF(x - 7, y + 7)]))
                item.setBrush(QBrush(QColor(col)))
                item.setPen(_pen("#0A1019", 1.0))
                self._scene.addItem(item)
                lab = QGraphicsSimpleTextItem(p.pid)
                lab.setBrush(QColor(col).lighter(140))
                lab.setFont(QFont("IBM Plex Mono", 8))
                lab.setPos(x + 11, y - 7)
                self._scene.addItem(lab)

    # ---- 视图切换 ----
    def set_view(self, view: str):
        self._layer_zones.setVisible(view in ("sit", "path"))
        self._layer_paths.setVisible(view == "path")
        self._layer_graph.setVisible(view == "graph")

    def resizeEvent(self, e):
        self.fitInView(self._scene.sceneRect(), Qt.KeepAspectRatioByExpanding)
        super().resizeEvent(e)


class SituationMap(Card):
    def __init__(self, groups: list[Group]):
        super().__init__("态势总览", icon="⊕", sub="场景图融合 · 32 节点")

        # 视图切换按钮组(放进 header 右侧)
        tabs = QFrame(); tabs.setObjectName("MapTabs")
        tl = QHBoxLayout(tabs); tl.setContentsMargins(3, 3, 3, 3); tl.setSpacing(3)
        self._bg = QButtonGroup(self); self._bg.setExclusive(True)
        for key, text in [("sit", "态势"), ("path", "路径规划"), ("graph", "场景图")]:
            b = QPushButton(text); b.setObjectName("MapTab"); b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setProperty("view", key)
            self._bg.addButton(b)
            tl.addWidget(b)
            if key == "sit":
                b.setChecked(True)
        self.add_header_widget(tabs)
        self._bg.buttonClicked.connect(lambda b: self.map.set_view(b.property("view")))

        # 地图
        self.map = MapView(groups)
        wrap = QWidget(); wl = QVBoxLayout(wrap); wl.setContentsMargins(0, 0, 0, 0)
        wl.addWidget(self.map)
        self.body.addWidget(wrap)

        # 图例
        legend = QFrame()
        lg = QHBoxLayout(legend); lg.setContentsMargins(13, 6, 13, 8); lg.setSpacing(16)
        for color, text in [(C.AIR, "无人机 UAV"), (C.GROUND, "无人车 UGV"),
                            (C.ALERT, "禁飞/威胁"), (C.SYS, "场景图节点")]:
            item = QHBoxLayout(); item.setSpacing(6)
            item.addWidget(Dot(color)); item.addWidget(QLabel(text))
            box = QWidget(); box.setLayout(item)
            lg.addWidget(box)
        lg.addStretch(1)
        self.body.addWidget(legend)
