#!/usr/bin/env python3
"""生成大规模场景与集群 JSON。

场景:1200×800m,一条东西向主干道 + 多条南北支路,3 栋建筑。
集群:100 台平台 = 10 种类型 × 10 台(6 种 UGV + 4 种 UAV)。

用法:
    python tools/gen_large_scenario.py
"""
import json
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "swan_planner" / "data" / "scenarios"
AO_W, AO_H = 1200.0, 800.0


def nx(x_m):  return round(x_m / AO_W, 4)
def ny(y_m):  return round(y_m / AO_H, 4)


# ==========================================================================
# 场景
# ==========================================================================
def build_scene():
    objects, ground_edges, zones = [], [], []

    # ---- 主干道:东西向,y=430m,M0..M8 ----
    main_y = 430.0
    main_xs = [80, 220, 360, 500, 640, 780, 920, 1060, 1150]
    for i, x in enumerate(main_xs):
        objects.append({"id": f"M{i}", "name": f"主干道 M{i}", "type": "waypoint",
                        "pos": [nx(x), ny(main_y)], "road": "main"})
    for i in range(len(main_xs) - 1):
        ground_edges.append([f"M{i}", f"M{i+1}"])

    # ---- 支路:从主干道分出,通向 3 栋建筑与广场 ----
    # (支路 id 前缀, 起点主干道节点, 途经点(m), 终点名)
    branches = [
        ("A", "M2", [(360, 330), (360, 240)], "办公楼南侧"),      # 北向 → BLD-A
        ("B", "M4", [(640, 530), (640, 620)], "居民楼北侧"),      # 南向 → BLD-B
        ("C", "M6", [(920, 330), (920, 235)], "仓库南侧"),        # 北向 → BLD-C
        ("D", "M3", [(500, 560), (430, 640)], "社区广场"),        # 南向 → 广场
        ("E", "M5", [(780, 320), (700, 250)], "楼间连络路"),      # 北向 → A/C 之间
    ]
    for tag, root, pts, _name in branches:
        prev = root
        for j, (x, y) in enumerate(pts):
            nid = f"{tag}{j+1}"
            objects.append({"id": nid, "name": f"支路 {nid}", "type": "waypoint",
                            "pos": [nx(x), ny(y)], "road": "branch"})
            ground_edges.append([prev, nid])
            prev = nid
    # 连络路:把 A 支路末端与 E 支路末端相连(形成环路,提供备用通路)
    ground_edges.append(["A2", "E2"])
    ground_edges.append(["E2", "C2"])

    # ---- 建筑 ----
    def rect(cx, cy, w, h):
        return [[nx(cx - w / 2), ny(cy - h / 2)], [nx(cx + w / 2), ny(cy - h / 2)],
                [nx(cx + w / 2), ny(cy + h / 2)], [nx(cx - w / 2), ny(cy + h / 2)]]

    buildings = [
        ("z_bldA", "BLD-A · 办公楼", 360, 190, 150, 90, 26, 8, "P1",
         "查明办公楼内人员,必要时突入清查"),
        ("z_bldB", "BLD-B · 居民楼", 640, 670, 170, 80, 18, 6, "P1",
         "封控居民楼,逐层核查"),
        ("z_bldC", "BLD-C · 仓库",   920, 185, 130, 80, 9,  2, "P2",
         "仓库外围侦察与内部查验"),
    ]
    for zid, name, cx, cy, w, h, hm, fl, pri, obj in buildings:
        zones.append({
            "id": zid, "name": name, "type": "structure",
            "poly": rect(cx, cy, w, h),
            "height_m": hm, "floors": fl, "priority": pri,
            "entries": [f"{zid}_e1", f"{zid}_e2"], "objective": obj,
        })

    # 建筑入口(朝向主干道一侧 + 背侧)
    entries = [
        ("z_bldA_e1", "A 楼主入口", 360, 235, True),
        ("z_bldA_e2", "A 楼后门",   360, 145, False),
        ("z_bldB_e1", "B 楼主入口", 640, 630, True),
        ("z_bldB_e2", "B 楼后门",   640, 710, False),
        ("z_bldC_e1", "C 库卷帘门", 920, 225, True),
        ("z_bldC_e2", "C 库侧门",   920, 145, False),
    ]
    for eid, nm, x, y, breach in entries:
        objects.append({"id": eid, "name": nm, "type": "entry",
                        "pos": [nx(x), ny(y)], "state": "closed", "breach_req": breach})

    # 支路末端接入口
    ground_edges += [["A2", "z_bldA_e1"], ["B2", "z_bldB_e1"], ["C2", "z_bldC_e1"]]

    # ---- 封控圈(围绕 3 栋楼的总封控) ----
    zones.append({
        "id": "z_cordon", "name": "总封控圈", "type": "cordon",
        "poly": [[nx(250), ny(110)], [nx(1030), ny(110)],
                 [nx(1030), ny(730)], [nx(250), ny(730)]],
        "priority": "P1", "objective": "封控三栋建筑及连接道路"})

    # ---- 集结区 / 广场 / 禁飞带 ----
    zones.append({"id": "z_stage", "name": "集结/展开区", "type": "staging",
                  "poly": rect(90, 620, 130, 150), "ground_access": True})
    zones.append({"id": "z_plaza", "name": "社区广场", "type": "open",
                  "poly": rect(420, 660, 130, 90), "ground_access": True})
    zones.append({"id": "z_nofly", "name": "高压线禁飞带", "type": "no_fly",
                  "poly": [[nx(40), ny(40)], [nx(1160), ny(40)],
                           [nx(1160), ny(95)], [nx(40), ny(95)]],
                  "ceiling_m": 60})

    objects.append({"id": "stage", "name": "集结点", "type": "origin",
                    "pos": [nx(90), ny(620)]})
    ground_edges.append(["stage", "M0"])
    ground_edges.append(["D2", "stage"])           # 广场支路回接集结区

    # ---- 封控点(主干道两端 + 四角) ----
    cordons = [("K_W", 260, 430), ("K_E", 1020, 430),
               ("K_NW", 260, 120), ("K_NE", 1020, 120),
               ("K_SW", 260, 720), ("K_SE", 1020, 720)]
    for cid, x, y in cordons:
        objects.append({"id": cid, "name": f"封控点 {cid[2:]}", "type": "waypoint",
                        "pos": [nx(x), ny(y)], "road": "cordon"})
    ground_edges += [["M1", "K_W"], ["M7", "K_E"],
                     ["K_W", "K_NW"], ["K_W", "K_SW"],
                     ["K_E", "K_NE"], ["K_E", "K_SE"]]

    # ---- 目标 / 障碍 / 盲区 ----
    objects += [
        {"id": "tgt_A3", "name": "疑似人员_A楼3F", "type": "target",
         "pos": [nx(340), ny(180)], "floor": 3, "confidence": 0.62},
        {"id": "tgt_B5", "name": "疑似人员_B楼5F", "type": "target",
         "pos": [nx(660), ny(660)], "floor": 5, "confidence": 0.55},
        {"id": "obs_main", "name": "路障_主干道", "type": "obstacle",
         "pos": [nx(570), ny(430)], "radius_m": 22},          # 阻断 M3-M4 直行
        {"id": "obs_A", "name": "废弃车辆_A支路", "type": "obstacle",
         "pos": [nx(360), ny(290)], "radius_m": 14},
        {"id": "blind_A", "name": "A楼背面盲区", "type": "terrain",
         "pos": [nx(360), ny(130)], "comm_blind": True},
        {"id": "blind_C", "name": "仓库区盲区", "type": "terrain",
         "pos": [nx(920), ny(130)], "comm_blind": True},
    ]

    # 主干道被路障阻断 → 提供北侧绕行旁路 M3→N1→N2→M4
    objects += [
        {"id": "N1", "name": "绕行 N1", "type": "waypoint", "pos": [nx(520), ny(360)], "road": "bypass"},
        {"id": "N2", "name": "绕行 N2", "type": "waypoint", "pos": [nx(620), ny(360)], "road": "bypass"},
    ]
    ground_edges += [["M3", "N1"], ["N1", "N2"], ["N2", "M4"]]

    constraints = [
        {"type": "no_fly", "ref": "z_nofly", "desc": "北侧高压线禁飞带,天花板 60m"},
        {"type": "comm", "ref": "blind_A", "desc": "A 楼背面通信盲区,需中继补链"},
        {"type": "comm", "ref": "blind_C", "desc": "仓库区通信盲区"},
        {"type": "obstacle", "ref": "obs_main", "desc": "路障阻断主干道 M3-M4,需绕行或清障"},
        {"type": "obstacle", "ref": "obs_A", "desc": "废弃车辆阻断 A 支路"},
        {"type": "roe", "desc": "内部清查前须完成外围封控;破门需人工确认"},
    ]

    return {
        "ao": {"name": "社区片区(主干道 + 支路 + 3 栋建筑)", "size_m": [AO_W, AO_H]},
        "zones": zones, "objects": objects,
        "ground_edges": ground_edges,
        "overlay_edges": [["tgt_A3", "z_bldA_e1"], ["tgt_B5", "z_bldB_e1"],
                          ["obs_main", "M3"], ["blind_A", "z_bldA_e2"]],
        "constraints": constraints,
    }


# ==========================================================================
# 集群:10 种类型 × 10 台 = 100
# ==========================================================================
TYPES = [
    # (前缀, kind, 规格, 能力, 载荷kg, 续航min, 速度, 传感器, 额外)
    ("UGV-T", "ground", "六轮 · 通用运输",
     ["transport", "ground_nav", "obstacle_detect"], 40, 120, 6, ["EO", "LiDAR"], {}),
    ("UGV-B", "ground", "履带 · 破障开门",
     ["breach", "clear_obstacle", "ground_nav", "manipulator"], 20, 90, 4, ["EO"], {}),
    ("UGV-R", "ground", "四轮 · 外围侦察",
     ["ground_recon", "ground_nav", "eo_imaging", "obstacle_detect"], 10, 140, 8, ["EO", "LiDAR"], {}),
    ("UGV-C", "ground", "四轮 · 通信中继车",
     ["comm_relay", "ground_nav", "mesh_node"], 15, 180, 7, ["EO"], {}),
    ("UGV-I", "ground", "小型履带 · 室内侦察",
     ["indoor_nav", "ground_recon", "eo_imaging", "stair_climb"], 5, 70, 2, ["EO", "LiDAR"], {"width_m": 0.5}),
    ("UGV-M", "ground", "六轮 · 医疗后送",
     ["transport", "casevac", "ground_nav"], 120, 110, 5, ["EO"], {}),
    ("UAV-S", "air", "四旋翼 · EO 广域侦察",
     ["aerial_survey", "eo_imaging", "target_track"], 0, 38, 18, ["EO"], {}),
    ("UAV-T", "air", "四旋翼 · 热成像/立面扫描",
     ["aerial_survey", "thermal_imaging", "facade_scan", "target_confirm"], 0, 34, 15, ["IR", "EO"], {}),
    ("UAV-C", "air", "四旋翼 · 空中中继",
     ["comm_relay", "mesh_node", "loiter"], 2, 45, 14, ["EO"], {}),
    ("UAV-M", "air", "微型穿越机 · 室内",
     ["indoor_flight", "eo_imaging", "target_confirm"], 0, 9, 10, ["EO"], {"width_m": 0.25}),
]

PER_TYPE = 10


def build_platforms():
    """在集结区内按类型分块排布,电量带轻微差异以驱动打分。"""
    plats = []
    sx0, sy0 = 30.0, 550.0        # 集结区左上(米)
    for ti, (prefix, kind, spec, caps, pay, endur, spd, sensors, extra) in enumerate(TYPES):
        for i in range(PER_TYPE):
            # 排布:每类一列,10 台两列 5 行
            col = ti * 12.0 + (i // 5) * 5.0
            row = (i % 5) * 14.0
            x = sx0 + col
            y = sy0 + row
            battery = 95 - (i * 3) - (2 if kind == "air" else 0)     # 72..95
            p = {
                "id": f"{prefix}{i+1:02d}", "kind": kind, "spec": spec,
                "battery": battery, "pos": [nx(x), ny(y)], "status": "待命",
                "capabilities": caps, "payload_kg": pay,
                "endurance_min": endur, "max_speed_ms": spd, "sensors": sensors,
            }
            p.update(extra)
            plats.append(p)
    return {"platforms": plats}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    scene = build_scene()
    plats = build_platforms()
    (OUT / "large_scene.json").write_text(
        json.dumps(scene, ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT / "large_platforms.json").write_text(
        json.dumps(plats, ensure_ascii=False, indent=1), encoding="utf-8")

    n_g = sum(1 for p in plats["platforms"] if p["kind"] == "ground")
    print(f"场景: {len(scene['zones'])} 区域 / {len(scene['objects'])} 物体 / "
          f"{len(scene['ground_edges'])} 通行边")
    print(f"集群: {len(plats['platforms'])} 台 = {n_g} 车 + "
          f"{len(plats['platforms']) - n_g} 机 / {len(TYPES)} 种类型")
    print("已写入:", OUT / "large_scene.json", "|", OUT / "large_platforms.json")


if __name__ == "__main__":
    main()
