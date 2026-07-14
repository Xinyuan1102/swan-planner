"""场景描述解析(JSON → 可查询对象)。

真实系统中,场景描述由感知/场景图融合模块以 JSON 产出,作为 Qwen 的结构化输入。
本模块负责:加载 scene.json、提供几何查询(面积/形心/最高建筑/障碍规避路径)、
并通过 to_prompt_context() 序列化为紧凑文本 —— 即喂给规划大模型的场景上下文。

坐标在 JSON 中归一化(0..1),便于地图渲染;几何计算时按 AO 尺寸换算为米。
"""
from __future__ import annotations
from dataclasses import dataclass
from math import hypot
from pathlib import Path
import json
import heapq

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


# ---- 几何工具(米制) ----
def _dist(a, b):
    return hypot(a[0] - b[0], a[1] - b[1])


def _seg_point_dist(p, a, b):
    ax, ay = a; bx, by = b; px, py = p
    dx, dy = bx - ax, by - ay
    if dx == dy == 0:
        return _dist(p, a)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return _dist(p, (ax + t * dx, ay + t * dy))


def _poly_area(poly):
    n = len(poly); s = 0.0
    for i in range(n):
        x1, y1 = poly[i]; x2, y2 = poly[(i + 1) % n]
        s += x1 * y2 - x2 * y1
    return abs(s) / 2.0


def _centroid(poly):
    n = len(poly)
    return (sum(p[0] for p in poly) / n, sum(p[1] for p in poly) / n)


def _bbox(poly):
    xs = [p[0] for p in poly]; ys = [p[1] for p in poly]
    return min(xs), min(ys), max(xs), max(ys)


@dataclass
class Zone:
    zid: str
    name: str
    type: str
    poly_norm: list           # 归一化多边形(供地图)
    ceiling_m: float | None
    attrs: dict


@dataclass
class SceneObject:
    oid: str
    name: str
    type: str
    x: float                  # 归一化
    y: float
    attrs: dict


class Scene:
    """已解析的作战场景。所有 *_m 方法返回米制结果。"""

    def __init__(self, raw: dict):
        self.raw = raw
        self.ao_w, self.ao_h = raw["ao"]["size_m"]
        self.zones = {z["id"]: Zone(z["id"], z["name"], z["type"], z["poly"],
                                    z.get("ceiling_m"),
                                    {k: v for k, v in z.items()
                                     if k not in ("id", "name", "type", "poly", "ceiling_m")})
                      for z in raw["zones"]}
        self.objects = {o["id"]: SceneObject(o["id"], o["name"], o["type"],
                                             o["pos"][0], o["pos"][1],
                                             {k: v for k, v in o.items()
                                              if k not in ("id", "name", "type", "pos")})
                        for o in raw["objects"]}
        self.ground_edges = [tuple(e) for e in raw.get("ground_edges", [])]
        self.overlay_edges = [tuple(e) for e in raw.get("overlay_edges", [])]
        self.constraints = raw.get("constraints", [])

    # ---- 坐标换算 ----
    def to_m(self, x_norm, y_norm):
        return (x_norm * self.ao_w, y_norm * self.ao_h)

    def obj_m(self, oid):
        o = self.objects[oid]
        return self.to_m(o.x, o.y)

    def zone_poly_m(self, zid):
        return [self.to_m(px, py) for px, py in self.zones[zid].poly_norm]

    def zone_centroid_m(self, zid):
        return _centroid(self.zone_poly_m(zid))

    def zone_area_m2(self, zid):
        return _poly_area(self.zone_poly_m(zid))

    def zone_bbox_m(self, zid):
        return _bbox(self.zone_poly_m(zid))

    # ---- 查询 ----
    def zones_of(self, *types):
        return [z for z in self.zones.values() if z.type in types]

    def objects_of(self, *types):
        return [o for o in self.objects.values() if o.type in types]

    def no_fly_ceiling(self):
        c = [z.ceiling_m for z in self.zones_of("no_fly") if z.ceiling_m]
        return max(c) if c else 0

    def tallest_building_near_zone(self, zid, margin_m=50):
        x0, y0, x1, y1 = self.zone_bbox_m(zid)
        best = None
        for b in self.objects_of("building"):
            bx, by = self.obj_m(b.oid)
            if x0 - margin_m <= bx <= x1 + margin_m and y0 - margin_m <= by <= y1 + margin_m:
                if best is None or b.attrs.get("height_m", 0) > best.attrs.get("height_m", 0):
                    best = b
        return best

    def nearest_zone_to(self, x_norm, y_norm, *types):
        p = self.to_m(x_norm, y_norm)
        cands = self.zones_of(*types) if types else list(self.zones.values())
        return min(cands, key=lambda z: _dist(p, self.zone_centroid_m(z.zid)), default=None)

    # ---- 地面路径搜索(Dijkstra,障碍规避) ----
    def _ground_adj(self, avoid_obstacles: bool):
        obs = [(self.obj_m(o.oid), o.attrs.get("radius_m", 30))
               for o in self.objects_of("obstacle")] if avoid_obstacles else []
        adj = {}
        for a, b in self.ground_edges:
            pa, pb = self.obj_m(a), self.obj_m(b)
            length = _dist(pa, pb)
            penalty = 1.0
            for (oc, orad) in obs:
                if _seg_point_dist(oc, pa, pb) < orad:
                    penalty = 8.0            # 靠近障碍 → 强惩罚,促使绕行
            w = length * penalty
            adj.setdefault(a, []).append((b, w))
            adj.setdefault(b, []).append((a, w))
        return adj

    def _dijkstra(self, adj, src, dst):
        dist = {src: 0.0}; prev = {}; pq = [(0.0, src)]; seen = set()
        while pq:
            d, u = heapq.heappop(pq)
            if u in seen:
                continue
            seen.add(u)
            if u == dst:
                break
            for v, w in adj.get(u, []):
                nd = d + w
                if nd < dist.get(v, float("inf")):
                    dist[v] = nd; prev[v] = u
                    heapq.heappush(pq, (nd, v))
        if dst not in prev:
            return []
        path = [dst]; cur = dst
        while cur != src:
            cur = prev[cur]; path.append(cur)
        path.reverse()
        return path

    def shortest_ground_path(self, src="origin", dst="gb"):
        """在 ground_edges 子图上求最短路;靠近障碍的边施加高额代价以促成绕行。

        返回 (节点序列, 几何总长m, 是否为规避障碍而绕行)。
        绕障 = 考虑障碍的路径 与 纯几何最短路 不一致。
        """
        path = self._dijkstra(self._ground_adj(avoid_obstacles=True), src, dst)
        if not path:
            return [], 0.0, False
        geo = sum(_dist(self.obj_m(path[i]), self.obj_m(path[i + 1]))
                  for i in range(len(path) - 1))
        naive = self._dijkstra(self._ground_adj(avoid_obstacles=False), src, dst)
        detour = naive != path
        return path, geo, detour

    # ---- LLM 上下文序列化 ----
    def to_prompt_context(self) -> str:
        lines = ["[SCENE]"]
        for z in self.zones.values():
            c = "∞" if z.ceiling_m is None else f"{z.ceiling_m}m"
            extra = f" cargo={z.attrs['cargo_kg']}kg" if "cargo_kg" in z.attrs else ""
            lines.append(f"ZONE {z.zid} '{z.name}' type={z.type} "
                         f"area={self.zone_area_m2(z.zid):.0f}m² ceiling={c}{extra}")
        for o in self.objects_of("building", "target", "obstacle"):
            x, y = self.obj_m(o.oid)
            ex = ""
            if "height_m" in o.attrs:     ex += f" h={o.attrs['height_m']}m"
            if "confidence" in o.attrs:   ex += f" conf={o.attrs['confidence']}"
            if "radius_m" in o.attrs:     ex += f" r={o.attrs['radius_m']}m"
            lines.append(f"OBJ {o.oid} '{o.name}' type={o.type} pos=({x:.0f},{y:.0f}){ex}")
        for c in self.constraints:
            lines.append(f"CONSTRAINT {c['type']}: {c['desc']}")
        return "\n".join(lines)


def load_scene(path: str | Path = None) -> Scene:
    path = Path(path) if path else DATA_DIR / "scene.json"
    with open(path, encoding="utf-8") as f:
        return Scene(json.load(f))
