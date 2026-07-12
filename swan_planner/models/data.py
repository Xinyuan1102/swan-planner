"""数据模型与场景种子数据。

这里定义系统的领域对象(平台 / 分组 / 任务 / 场景图节点),
并提供一份"侦察-运输联合行动"的种子场景,供界面渲染与 mock 规划器使用。
真实系统中,这些对象应由集群上报与场景图融合动态生成。
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Literal

Kind = Literal["air", "ground"]


@dataclass
class Platform:
    pid: str                 # UAV-01 / UGV-03
    kind: Kind               # air / ground
    spec: str                # 平台描述
    battery: int             # 电量 %
    status: str              # 当前行为
    x: float                 # 地图归一化坐标 (0..1)
    y: float

    @property
    def busy(self) -> bool:
        return self.status not in ("待命",)


@dataclass
class Group:
    gid: str                 # A / B / C
    name: str                # 显示名
    task: str                # 组任务(顶层下达)
    members: list[Platform] = field(default_factory=list)


@dataclass
class SceneNode:
    nid: str
    label: str
    x: float
    y: float
    kind: str = "object"     # object / target / route / origin
    conf: float | None = None


@dataclass
class Zone:
    zid: str
    label: str
    tag: str
    color: str
    # 归一化多边形顶点
    poly: list[tuple[float, float]]


# --------------------------------------------------------------------------
# 种子场景:侦察-运输联合行动
# --------------------------------------------------------------------------
def seed_groups() -> list[Group]:
    return [
        Group("A", "A 组 · 空中侦察", "侦察 A 区并定位可疑目标", [
            Platform("UAV-01", "air", "四旋翼 · 光电吊舱", 86, "扇区扫描", 0.28, 0.20),
            Platform("UAV-02", "air", "四旋翼 · SAR",     78, "扇区扫描", 0.36, 0.27),
        ]),
        Group("B", "B 组 · 物资运输", "保障 B 点物资运输(空地协同)", [
            Platform("UGV-03", "ground", "六轮 · 载荷 40kg",   64, "路径行进", 0.56, 0.74),
            Platform("UAV-04", "air",    "四旋翼 · 中继护航",  31, "伴随护航", 0.56, 0.67),
        ]),
        Group("C", "C 组 · 待命预备", "中心待命,响应动态增援", [
            Platform("UGV-05", "ground", "履带 · 侦察搬运", 92, "待命", 0.16, 0.89),
        ]),
    ]


def seed_zones() -> list[Zone]:
    from ..config import C
    return [
        Zone("A", "A 区 · 侦察", "SECTOR SCAN · 3 fans", C.AIR,
             [(0.13, 0.16), (0.38, 0.12), (0.42, 0.41), (0.18, 0.48)]),
        Zone("B", "B 点 · 补给", "DELIVERY DZ", C.GROUND,
             [(0.71, 0.64), (0.88, 0.64), (0.88, 0.84), (0.71, 0.84)]),
        Zone("NF", "⃠ 禁飞区", "NO-FLY", C.ALERT,
             [(0.50, 0.32), (0.62, 0.29), (0.66, 0.50), (0.52, 0.54)]),
    ]


def seed_scene_graph() -> tuple[list[SceneNode], list[tuple[str, str]]]:
    nodes = [
        SceneNode("n1", "建筑群_01", 0.46, 0.25, "object"),
        SceneNode("n2", "可疑目标?", 0.58, 0.41, "target", conf=0.71),
        SceneNode("n3", "通路_主干道", 0.80, 0.43, "route"),
        SceneNode("n4", "出发点", 0.20, 0.80, "origin"),
        SceneNode("n5", "开阔地", 0.36, 0.54, "object"),
    ]
    edges = [("n1", "n2"), ("n1", "n5"), ("n2", "n5"),
             ("n2", "n3"), ("n5", "n4"), ("n4", "n3"), ("n3", "n2")]
    return nodes, edges
