#!/usr/bin/env python3
"""从 JSON 场景描述渲染态势地图 PNG。

地图完全由 scene.json 驱动(区域 / 物体 / 通行边),路径由 scene.py 的
Dijkstra 实算得出 —— 保证地图与规划结果始终一致,不会各画各的。

用法:
    python tools/render_scene_map.py [scene.json] [out.png]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtGui import (QImage, QPainter, QColor, QPen, QBrush, QPolygonF,
                           QFont, QPainterPath)
from PySide6.QtCore import Qt, QPointF, QRectF

from swan_planner.config import C
from swan_planner.models.scene import load_scene

W, H = 1180, 840          # 画布像素
PAD = 46                  # 边距

ZONE_STYLE = {            # type: (描边色, 填充alpha, 虚线, 标签)
    "structure": (C.TEXT,   0.10, None,   "主楼 · 目标建筑"),
    "cordon":   (C.OK,     0.04, [7, 6],  "外围封控圈"),
    "open":     (C.GROUND, 0.05, [4, 4],  "社区广场"),
    "staging":  (C.SYS,    0.07, [4, 4],  "集结/展开区"),
    "no_fly":   (C.ALERT,  0.07, [3, 4],  "禁飞带"),
}


def pen(color, w=1.4, dash=None):
    p = QPen(QColor(color)); p.setWidthF(w)
    if dash:
        p.setDashPattern(dash)
    return p


class Renderer:
    def __init__(self, scene):
        self.sc = scene
        self.iw = W - 2 * PAD
        self.ih = H - 2 * PAD

    def px(self, xn, yn):
        """归一化坐标 → 像素。"""
        return QPointF(PAD + xn * self.iw, PAD + yn * self.ih)

    def draw(self, path_out):
        img = QImage(W, H, QImage.Format_ARGB32)
        img.fill(QColor("#0A1019"))
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)

        self._grid(p)
        self._zones(p)
        self._ground_net(p)
        self._approach(p)
        self._cordon(p)
        self._objects(p)
        self._building_detail(p)
        self._legend(p)
        self._title(p)

        p.end()
        img.save(path_out)
        return path_out

    # ---- 背景栅格 ----
    def _grid(self, p):
        p.setPen(pen("#142132", 1))
        step = 40
        for x in range(PAD, W - PAD + 1, step):
            p.drawLine(x, PAD, x, H - PAD)
        for y in range(PAD, H - PAD + 1, step):
            p.drawLine(PAD, y, W - PAD, y)
        # 外框 + 比例尺
        p.setPen(pen(C.LINE, 1.5))
        p.drawRect(PAD, PAD, self.iw, self.ih)
        # 比例尺:AO 宽 420m
        bar_m = 50.0
        bar_px = self.iw * (bar_m / self.sc.ao_w)
        bx, by = PAD + 14, H - PAD - 18
        p.setPen(pen(C.MUTED, 2))
        p.drawLine(bx, by, bx + bar_px, by)
        p.drawLine(bx, by - 4, bx, by + 4)
        p.drawLine(bx + bar_px, by - 4, bx + bar_px, by + 4)
        p.setFont(QFont("IBM Plex Mono", 9))
        p.setPen(QColor(C.MUTED))
        p.drawText(QRectF(bx, by - 22, 90, 14), Qt.AlignLeft, f"{bar_m:.0f} m")

    # ---- 功能区 ----
    def _zones(self, p):
        for z in self.sc.zones.values():
            stroke, alpha, dash, _ = ZONE_STYLE.get(z.type, (C.SYS, 0.05, None, z.name))
            poly = QPolygonF([self.px(x, y) for x, y in z.poly_norm])
            fill = QColor(stroke); fill.setAlphaF(alpha)
            p.setBrush(QBrush(fill))
            p.setPen(pen(stroke, 1.8 if z.type == "structure" else 1.4, dash))
            p.drawPolygon(poly)

            # 区域标签置于左上角
            xs = [pt.x() for pt in poly]; ys = [pt.y() for pt in poly]
            p.setPen(QColor(stroke))
            p.setFont(QFont("Arial", 11, QFont.Bold))
            label = z.name
            if z.type == "structure":
                label = f"{z.name}  {z.attrs.get('floors')}F / {z.attrs.get('height_m')}m"
            if z.type == "no_fly":
                label = f"⃠ {z.name}  ceiling {z.ceiling_m}m"
            p.drawText(QRectF(min(xs) + 8, min(ys) + 6, 320, 18), Qt.AlignLeft, label)

    # ---- 地面通行网 ----
    def _ground_net(self, p):
        p.setPen(pen("#33465e", 1.6, [5, 5]))
        for a, b in self.sc.ground_edges:
            oa, ob = self.sc.objects[a], self.sc.objects[b]
            p.drawLine(self.px(oa.x, oa.y), self.px(ob.x, ob.y))

    # ---- 抵近路径(实算,含绕障 / 受阻标记) ----
    def _approach(self, p):
        """为每栋建筑渲染由 Dijkstra 实算的抵近路径。"""
        targets = []
        for z in self.sc.zones_of("structure"):
            for eid in z.attrs.get("entries", []):
                o = self.sc.objects.get(eid)
                if o is not None and o.attrs.get("breach_req"):
                    targets.append((z.name, eid))
                    break
        if not targets:                      # 回退:小场景的固定终点
            targets = [("抵近", "hold")] if "hold" in self.sc.objects else []

        for name, dst in targets:
            route, geo, detour = self.sc.shortest_ground_path("stage", dst)
            if not route:
                continue
            blockers = self.sc.path_blockers(route)
            path = QPainterPath(self.px(*self._xy(route[0])))
            for nid in route[1:]:
                path.lineTo(self.px(*self._xy(nid)))
            col = C.ALERT if blockers else C.GROUND
            glow = QColor(col); glow.setAlphaF(0.20)
            p.setPen(QPen(glow, 9, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.drawPath(path)
            p.setPen(QPen(QColor(col), 2.4, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.drawPath(path)

            mid = self.px(*self._xy(route[len(route) // 2]))
            tag = "%.0fm" % geo
            if blockers:
                tag += " · 受阻需清障"
            elif detour:
                tag += " · 绕障"
            p.setFont(QFont("IBM Plex Mono", 8, QFont.Bold))
            p.setPen(QColor(col))
            p.drawText(QRectF(mid.x() - 110, mid.y() + 10, 220, 14), Qt.AlignHCenter, tag)

    def _xy(self, nid):
        o = self.sc.objects[nid]
        return (o.x, o.y)

    # ---- 封控点 ----
    def _cordon(self, p):
        for oid in ("c_nw", "c_ne", "c_sw", "c_se"):
            if oid not in self.sc.objects:
                continue
            o = self.sc.objects[oid]
            c = self.px(o.x, o.y)
            ring = QColor(C.OK); ring.setAlphaF(0.16)
            p.setBrush(QBrush(ring)); p.setPen(Qt.NoPen)
            p.drawEllipse(c, 17, 17)
            p.setBrush(QBrush(QColor(C.OK))); p.setPen(pen("#0A1019", 1.2))
            p.drawEllipse(c, 5.5, 5.5)
            p.setPen(QColor(C.OK)); p.setFont(QFont("IBM Plex Mono", 8, QFont.Bold))
            p.drawText(QRectF(c.x() - 40, c.y() - 32, 80, 14), Qt.AlignHCenter,
                       o.name.replace("封控点 ", "CORDON "))

    # ---- 物体 ----
    def _objects(self, p):
        for o in self.sc.objects.values():
            c = self.px(o.x, o.y)

            if o.type == "waypoint" and not o.oid.startswith("c_"):
                p.setBrush(QBrush(QColor("#43587280"))); p.setPen(pen("#5C6C82", 1))
                p.drawEllipse(c, 3.5, 3.5)
                p.setPen(QColor(C.DIM)); p.setFont(QFont("IBM Plex Mono", 7))
                p.drawText(QRectF(c.x() + 6, c.y() - 12, 70, 12), Qt.AlignLeft, o.oid)

            elif o.type == "origin":
                p.setBrush(QBrush(QColor(C.SYS))); p.setPen(pen("#0A1019", 1.2))
                p.drawEllipse(c, 6, 6)
                p.setPen(QColor(C.SYS)); p.setFont(QFont("Arial", 9, QFont.Bold))
                p.drawText(QRectF(c.x() - 60, c.y() + 10, 120, 14), Qt.AlignHCenter, "集结点 · 10 平台")

            elif o.type == "entry":
                need = o.attrs.get("breach_req")
                col = C.ALERT if need else C.WARN
                p.setBrush(QBrush(QColor(col))); p.setPen(pen("#0A1019", 1.2))
                p.drawRect(QRectF(c.x() - 6, c.y() - 4, 12, 8))
                p.setPen(QColor(col)); p.setFont(QFont("Arial", 9, QFont.Bold))
                tag = f"{o.name}" + ("(需破门)" if need else "(免破门)")
                dy = 10 if o.oid == "e_main" else -24
                p.drawText(QRectF(c.x() - 70, c.y() + dy, 140, 14), Qt.AlignHCenter, tag)

            elif o.type == "target":
                halo = QColor(C.ALERT); halo.setAlphaF(0.18)
                p.setBrush(QBrush(halo)); p.setPen(Qt.NoPen)
                p.drawEllipse(c, 16, 16)
                p.setBrush(Qt.NoBrush); p.setPen(pen(C.ALERT, 2))
                p.drawEllipse(c, 7, 7)
                p.drawLine(c.x() - 12, c.y(), c.x() + 12, c.y())
                p.drawLine(c.x(), c.y() - 12, c.x(), c.y() + 12)
                p.setFont(QFont("IBM Plex Mono", 8, QFont.Bold))
                p.drawText(QRectF(c.x() - 90, c.y() - 32, 180, 13), Qt.AlignHCenter,
                           f"{o.name}  conf {o.attrs.get('confidence')}")

            elif o.type == "obstacle":
                r_px = self.iw * (o.attrs.get("radius_m", 8) / self.sc.ao_w)
                fill = QColor(C.ALERT); fill.setAlphaF(0.13)
                p.setBrush(QBrush(fill)); p.setPen(pen(C.ALERT, 1.2, [3, 3]))
                p.drawEllipse(c, r_px, r_px)
                p.setPen(QColor(C.ALERT)); p.setFont(QFont("Arial", 8))
                p.drawText(QRectF(c.x() - 80, c.y() + r_px + 3, 160, 13),
                           Qt.AlignHCenter, f"{o.name} r={o.attrs.get('radius_m')}m")

            elif o.type == "terrain" and o.attrs.get("comm_blind"):
                fill = QColor(C.WARN); fill.setAlphaF(0.10)
                p.setBrush(QBrush(fill)); p.setPen(pen(C.WARN, 1.2, [2, 3]))
                p.drawEllipse(c, 40, 26)
                p.setPen(QColor(C.WARN)); p.setFont(QFont("Arial", 8, QFont.Bold))
                p.drawText(QRectF(c.x() - 80, c.y() - 8, 160, 13), Qt.AlignHCenter, "通信盲区")

    # ---- 建筑内部细节(目标楼层提示) ----
    def _building_detail(self, p):
        z = self.sc.zones.get("z_building")
        if not z:
            return
        poly = [self.px(x, y) for x, y in z.poly_norm]
        xs = [pt.x() for pt in poly]; ys = [pt.y() for pt in poly]
        # 楼顶标记
        p.setPen(pen(C.MUTED, 1, [2, 3]))
        p.drawLine(min(xs) + 6, (min(ys) + max(ys)) / 2, max(xs) - 6, (min(ys) + max(ys)) / 2)
        p.setPen(QColor(C.MUTED)); p.setFont(QFont("IBM Plex Mono", 8))
        p.drawText(QRectF(min(xs), max(ys) - 22, max(xs) - min(xs), 14),
                   Qt.AlignHCenter, "ROOF · 楼顶(UAV-02 扫描)")

    # ---- 图例 ----
    def _legend(self, p):
        items = [
            (C.GROUND, "抵近路径(实算 · 可绕障)"),
            (C.ALERT,  "受阻通路(无旁路 · 须清障)"),
            (C.OK,     "封控点 CORDON ×4"),
            (C.WARN,   "目标 / 障碍 / 盲区"),
            (C.WARN,   "通信盲区 / 免破门入口"),
            (C.SYS,    "集结展开区"),
            ("#33465e", "地面通行网(ground_edges)"),
        ]
        bw, bh = 260, len(items) * 19 + 16
        bx, by = W - PAD - bw - 8, H - PAD - bh - 8
        bg = QColor("#0C1521"); bg.setAlphaF(0.92)
        p.setBrush(QBrush(bg)); p.setPen(pen(C.LINE, 1))
        p.drawRoundedRect(QRectF(bx, by, bw, bh), 8, 8)
        p.setFont(QFont("Arial", 9))
        for i, (col, text) in enumerate(items):
            y = by + 12 + i * 19
            p.setBrush(QBrush(QColor(col))); p.setPen(Qt.NoPen)
            p.drawRoundedRect(QRectF(bx + 12, y + 2, 10, 10), 2, 2)
            p.setPen(QColor(C.MUTED))
            p.drawText(QRectF(bx + 30, y, bw - 40, 14), Qt.AlignLeft, text)

    # ---- 标题 ----
    def _title(self, p):
        p.setPen(QColor(C.TEXT)); p.setFont(QFont("Arial", 15, QFont.Bold))
        p.drawText(QRectF(PAD, 12, 900, 20), Qt.AlignLeft,
                   self.sc.raw["ao"]["name"] + " · 态势图")
        p.setPen(QColor(C.DIM)); p.setFont(QFont("IBM Plex Mono", 9))
        p.drawText(QRectF(PAD, 30, 700, 14), Qt.AlignLeft,
                   f"AO {self.sc.ao_w:.0f}×{self.sc.ao_h:.0f}m  ·  "
                   f"{len(self.sc.zones_of('structure'))} 栋建筑  ·  "
                   f"{len(self.sc.ground_edges)} 条通行边  ·  rendered from scene.json")


def main():
    scene_path = sys.argv[1] if len(sys.argv) > 1 else \
        "swan_planner/data/scenarios/community_scene.json"
    out = sys.argv[2] if len(sys.argv) > 2 else "docs/community_map.png"

    from PySide6.QtGui import QGuiApplication
    app = QGuiApplication([])          # QImage/QPainter 需要 GUI application
    sc = load_scene(scene_path)
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Renderer(sc).draw(out)
    print(f"地图已渲染: {out}")


if __name__ == "__main__":
    main()
