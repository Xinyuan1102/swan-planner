"""领域对象与数据加载。

平台(含能力档案)从 data/platforms.json 加载;地图渲染用的区域 / 场景节点
从 data/scene.json 派生 —— 保证界面与规划器共享同一份场景描述。
分组不再硬编码,而是由 planner 依据能力匹配动态生成。
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Literal
from pathlib import Path
import json

from .scene import load_scene, Scene

Kind = Literal["air", "ground"]
DATA_DIR = Path(__file__).resolve().parent.parent / "data"


@dataclass
class Platform:
    pid: str
    kind: Kind
    spec: str
    battery: int
    status: str
    x: float                       # 归一化坐标(供地图)
    y: float
    caps: list[str] = field(default_factory=list)      # 能力档案
    payload_kg: float = 0.0
    endurance_min: int = 0
    sensors: list[str] = field(default_factory=list)

    @property
    def busy(self) -> bool:
        return self.status not in ("待命",)


@dataclass
class Group:
    gid: str
    name: str
    task: str
    members: list[Platform] = field(default_factory=list)


# ---- 地图渲染用的轻量类型(从 JSON 场景派生) ----
@dataclass
class Zone:
    zid: str
    label: str
    tag: str
    color: str
    poly: list[tuple[float, float]]


@dataclass
class SceneNode:
    nid: str
    label: str
    x: float
    y: float
    kind: str = "object"
    conf: float | None = None


# --------------------------------------------------------------------------
# 加载器
# --------------------------------------------------------------------------
def load_platforms(path: str | Path = None) -> list[Platform]:
    path = Path(path) if path else DATA_DIR / "platforms.json"
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    out = []
    for p in raw["platforms"]:
        out.append(Platform(
            pid=p["id"], kind=p["kind"], spec=p["spec"],
            battery=p["battery"], status=p.get("status", "待命"),
            x=p["pos"][0], y=p["pos"][1],
            caps=p.get("capabilities", []), payload_kg=p.get("payload_kg", 0),
            endurance_min=p.get("endurance_min", 0), sensors=p.get("sensors", []),
        ))
    return out


# ---- 地图数据(从场景派生) ----
_ZONE_STYLE = {
    "survey":   ("SECTOR SCAN", "#4FC3E8"),
    "delivery": ("DELIVERY DZ", "#E0A23C"),
    "no_fly":   ("NO-FLY",      "#E5484D"),
}
_OBJ_KIND = {"building": "object", "target": "target", "route": "route",
             "origin": "origin", "terrain": "object"}


def seed_zones(scene: Scene = None) -> list[Zone]:
    scene = scene or load_scene()
    out = []
    for z in scene.zones.values():
        tag, color = _ZONE_STYLE.get(z.type, ("", "#7C86FF"))
        label = z.name if z.type != "no_fly" else "⃠ " + z.name
        out.append(Zone(z.zid, label, tag, color, z.poly_norm))
    return out


def seed_scene_graph(scene: Scene = None):
    """返回 (显著语义节点, 叠加边),供 2D 态势图的"场景图"视图。"""
    scene = scene or load_scene()
    salient = ("building", "target", "route", "origin", "terrain")
    nodes = []
    for o in scene.objects.values():
        if o.type in salient:
            nodes.append(SceneNode(o.oid, o.name, o.x, o.y,
                                   _OBJ_KIND.get(o.type, "object"),
                                   o.attrs.get("confidence")))
    edges = [(a, b) for a, b in scene.overlay_edges]
    return nodes, edges
