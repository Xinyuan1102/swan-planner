"""规划引擎:场景驱动的任务群编成 + 全局最优指派。

相对 v0.2 的三处优化(面向 100 台规模):

1. **全局最优指派** —— 原贪心逐任务挑 top-N,多任务争抢同一批平台时明显偏离最优。
   现构建「角色槽位 × 平台」代价矩阵,用匈牙利算法(scipy)求总效用最大的指派;
   scipy 不可用时回退贪心。O(n³),100 台规模毫秒级。

2. **分队编成(Squad)** —— L1 不再直接指派个体,而是产出「任务群 → 分队」两级编成,
   个体归 L2 管。L1 输出规模与建筑数(而非平台数)成正比。

3. **场景驱动任务规格** —— 角色需求由场景实算:封控点按周长、室内分队按楼层、
   破障分队按"需破门入口数 + 无旁路的受阻通路数"。改场景即改编成,无需改代码。
"""
from __future__ import annotations
from dataclasses import dataclass, field
from math import hypot, ceil
import time

from ..config import MODEL_L1, MODEL_L2, MODEL_L3
from .scene import Scene
from .data import Platform, Group

try:
    from scipy.optimize import linear_sum_assignment
    import numpy as np
    _HAS_SCIPY = True
except ImportError:
    _HAS_SCIPY = False

SURVEY_CLEARANCE_M = 20.0
RELAY_CLEARANCE_M = 20.0
CORDON_SPACING_M = 160.0
INFEASIBLE = 1e6


@dataclass
class TaskItem:
    group_id: str
    tag: str
    objective: str
    priority: str = ""
    constraints: list = field(default_factory=list)
    success: str = ""


@dataclass
class ReasoningNode:
    layer: str
    title: str
    model: str
    think: str
    tasks: list = field(default_factory=list)
    skills: list = field(default_factory=list)


@dataclass
class PlanResult:
    instruction: str
    chain: list
    latency_ms: int


@dataclass
class RoleSpec:
    name: str
    label: str
    required_caps: list
    preferred_caps: list
    count: int
    payload_req: float = 0.0


@dataclass
class TaskSpec:
    tid: str
    gid: str
    name: str
    objective: str
    priority: str
    zone: str
    roles: list
    kind: str = "structure"


@dataclass
class Assignment:
    pid: str
    role: str
    score: float
    reasons: list


@dataclass
class Squad:
    """分队:任务群内承担同一角色的平台集合(L2 管理的最小编成单位)。"""
    role: str
    label: str
    members: list
    demand: int

    @property
    def shortfall(self) -> int:
        return max(0, self.demand - len(self.members))


@dataclass
class GroupPlan:
    gid: str
    name: str
    objective: str
    spec: TaskSpec
    members: list
    assignments: dict
    squads: list = field(default_factory=list)


@dataclass
class GlobalPlan:
    instruction: str
    scene_context: str
    objectives: list
    tasks: list
    groups: list
    l1_node: ReasoningNode
    latency_ms: int
    solver: str = "hungarian"
    shortfalls: list = field(default_factory=list)

    def group(self, gid: str):
        return next((g for g in self.groups if g.gid == gid), None)

    def as_groups(self):
        out = []
        for g in self.groups:
            grp = Group(g.gid, g.name, g.objective, g.members)
            grp.squads = g.squads          # 供 UI 做分队聚合渲染
            out.append(grp)
        return out


_PRIORITY_RANK = {"P1": 0, "P2": 1, "": 2}
_PRIORITY_WEIGHT = {"P1": 1.35, "P2": 1.0, "": 0.7}
SPECIALIST_PENALTY = 26.0      # 稀缺专才被派去干通用活的惩罚上限


class PlannerEngine:
    def __init__(self, scene: Scene, platforms: list):
        self.scene = scene
        self.platforms = platforms
        self._diag = hypot(scene.ao_w, scene.ao_h)
        self._supply = {}        # cap -> 具备该能力的平台数
        self._pressure = {}      # cap -> 需求/供给 压力比

    # ---------------- 供给 / 稀缺度 ----------------
    def _calc_supply(self):
        sup = {}
        for p in self.platforms:
            for c in p.caps:
                sup[c] = sup.get(c, 0) + 1
        return sup

    def _calc_pressure(self, specs):
        """每种能力的需求压力 = 需要它的角色槽位总数 / 供给。"""
        demand = {}
        for t in specs:
            for r in t.roles:
                for c in r.required_caps:
                    demand[c] = demand.get(c, 0) + r.count
        return {c: demand.get(c, 0) / max(1, self._supply.get(c, 0))
                for c in set(list(demand) + list(self._supply))}

    def _effective_supply(self, specs):
        """有效供给:稀缺能力优先预留后,各能力还剩多少平台可用。

        例:UGV-I 同时具 indoor_nav(仅它提供)与 ground_recon(与 UGV-R 共享)。
        室内清查需 6 台 UGV-I → 这 6 台不应再计入封控的可用供给。
        故按"提供者数量升序"(越稀缺越先预留)依次扣减,得到真实可用量。
        """
        demand = {}
        for t in specs:
            for r in t.roles:
                for c in r.required_caps:
                    demand[c] = demand.get(c, 0) + r.count

        pool = {p.pid: set(p.caps) for p in self.platforms}
        eff = {}
        for cap in sorted(demand, key=lambda c: self._supply.get(c, 0)):
            providers = [pid for pid, caps in pool.items() if cap in caps]
            eff[cap] = len(providers)
            for pid in providers[:min(demand[cap], len(providers))]:
                pool.pop(pid, None)          # 已预留,不再计入后续能力的供给
        return eff

    def _scale_to_supply(self, specs):
        """供给感知的需求下调。

        某能力的需求超过**有效供给**时(如封控需 29 而扣除室内预留后仅剩 14),
        按优先级加权比例下调各角色需求 —— 即降低封控密度(加大间距),
        而不是一边报缺编、一边让干不了这活的预备队闲置。
        """
        eff = self._effective_supply(specs)
        notes = []
        for cap, sup in eff.items():
            roles = [(t, r) for t in specs for r in t.roles if cap in r.required_caps]
            demand = sum(r.count for _, r in roles)
            if demand <= sup or not roles:
                continue
            factor = sup / demand
            for t, r in roles:
                w = _PRIORITY_WEIGHT.get(t.priority, 1.0)
                r.count = max(1, int(r.count * factor * w / 1.35 + 0.5))
            after = sum(r.count for _, r in roles)
            notes.append("%s 需求 %d > 可用 %d,密度下调至 %d" % (cap, demand, sup, after))
        return notes

    # ---------------- L1 ----------------
    def plan_global(self, instruction: str) -> GlobalPlan:
        t0 = time.time()
        ctx = self.scene.to_prompt_context()
        tasks = self._build_task_specs(instruction)
        # 供给感知:先算稀缺度,再按供给下调超额需求
        self._supply = self._calc_supply()
        scale_notes = self._scale_to_supply(tasks)
        self._pressure = self._calc_pressure(tasks)
        groups, solver, shortfalls = self._allocate(tasks)
        l1 = self._l1_reasoning(tasks, groups, solver, shortfalls, scale_notes)
        return GlobalPlan(instruction, ctx, [t.objective for t in tasks],
                          tasks, groups, l1, int((time.time() - t0) * 1000),
                          solver, shortfalls)

    def _build_task_specs(self, instruction: str) -> list:
        specs = []
        for i, z in enumerate(self.scene.zones_of("structure")):
            floors = z.attrs.get("floors", 1)
            x0, y0, x1, y1 = self.scene.zone_bbox_m(z.zid)
            perim = 2 * ((x1 - x0) + (y1 - y0))
            n_cordon = max(2, ceil(perim / CORDON_SPACING_M))

            entries = [self.scene.objects[e] for e in z.attrs.get("entries", [])
                       if e in self.scene.objects]
            n_breach = sum(1 for e in entries if e.attrs.get("breach_req"))
            main_entry = next((e for e in entries if e.attrs.get("breach_req")), None)
            if main_entry:
                route, _, _ = self.scene.shortest_ground_path("stage", main_entry.oid)
                n_breach += len(self.scene.path_blockers(route))
            n_breach = max(1, n_breach)

            roles = [
                RoleSpec("air_survey", "空中广域侦察", ["aerial_survey"],
                         ["eo_imaging", "target_track"], 2),
                RoleSpec("air_facade", "立面/热成像", ["facade_scan"],
                         ["thermal_imaging", "target_confirm"], max(1, ceil(floors / 4))),
                RoleSpec("air_relay", "空中中继", ["comm_relay", "loiter"], ["mesh_node"], 1),
                RoleSpec("cordon", "楼周封控", ["ground_recon"],
                         ["eo_imaging", "obstacle_detect"], n_cordon),
                RoleSpec("breach", "破障开门", ["breach"],
                         ["clear_obstacle", "manipulator"], n_breach),
                RoleSpec("indoor", "室内清查", ["indoor_nav"],
                         ["stair_climb", "eo_imaging"], max(1, ceil(floors / 3))),
                RoleSpec("micro", "室内空中", ["indoor_flight"], ["target_confirm"],
                         max(1, ceil(floors / 4))),
                RoleSpec("gnd_relay", "地面中继", ["mesh_node"], ["comm_relay"], 1),
                RoleSpec("transport", "器材前送", ["transport"], ["obstacle_detect"], 1, 20),
                RoleSpec("medevac", "伤员后送", ["casevac"], [], 1, 100),
            ]
            specs.append(TaskSpec(
                "T-" + z.zid, chr(ord("A") + i), z.name + " 任务群",
                z.attrs.get("objective", "建筑封控清查"),
                z.attrs.get("priority", "P1"), z.zid, roles, "structure"))

        for z in self.scene.zones_of("cordon"):
            x0, y0, x1, y1 = self.scene.zone_bbox_m(z.zid)
            perim = 2 * ((x1 - x0) + (y1 - y0))
            n = max(4, ceil(perim / CORDON_SPACING_M))
            specs.append(TaskSpec(
                "T-CORDON", chr(ord("A") + len(specs)), z.name + " 任务群",
                z.attrs.get("objective", "外围封控"),
                z.attrs.get("priority", "P1"), z.zid,
                [RoleSpec("cordon", "外围封控", ["ground_recon"], ["obstacle_detect"], n),
                 RoleSpec("gnd_relay", "链路保障", ["mesh_node"], ["comm_relay"], 2),
                 RoleSpec("air_survey", "空中监视", ["aerial_survey"], ["target_track"], 2)],
                "cordon"))

        # ---- 兼容广域侦察 / 物资运输型场景 ----
        for z in self.scene.zones_of("survey"):
            n = max(2, ceil(self.scene.zone_area_m2(z.zid) / 30000.0))
            specs.append(TaskSpec(
                "T-" + z.zid, chr(ord("A") + len(specs)), z.name + " 任务群",
                z.attrs.get("objective", "广域侦察"),
                z.attrs.get("priority", "P1"), z.zid,
                [RoleSpec("air_survey", "扇区覆盖", ["aerial_survey"],
                          ["eo_imaging", "sar_imaging", "target_track", "target_confirm"], n)],
                "survey"))

        for z in self.scene.zones_of("delivery"):
            cargo = z.attrs.get("cargo_kg", 0)
            specs.append(TaskSpec(
                "T-" + z.zid, chr(ord("A") + len(specs)), z.name + " 任务群",
                z.attrs.get("objective", "物资运输"),
                z.attrs.get("priority", "P1"), z.zid,
                [RoleSpec("carrier", "运输", ["transport"],
                          ["obstacle_detect", "ground_nav"], 1, cargo),
                 RoleSpec("escort", "中继护航", ["comm_relay"], ["escort", "recon"], 1)],
                "transport"))
        return specs

    # ---------------- 可行性 / 打分 ----------------
    def _feasible(self, p: Platform, role: RoleSpec) -> bool:
        if not set(role.required_caps).issubset(p.caps):
            return False
        if role.payload_req and p.payload_kg < role.payload_req:
            return False
        return True

    def _score(self, p: Platform, role: RoleSpec, task: TaskSpec) -> float:
        s = 100.0
        s += 12.0 * len(set(role.preferred_caps) & set(p.caps))
        if task.zone:
            pm = self.scene.to_m(p.x, p.y)
            zc = self.scene.zone_centroid_m(task.zone)
            d = hypot(pm[0] - zc[0], pm[1] - zc[1])
            s += 25.0 * max(0.0, 1 - d / self._diag)
        s += p.battery / 8.0
        s += p.endurance_min / 20.0
        s -= self._specialist_penalty(p, role)
        return s * _PRIORITY_WEIGHT.get(task.priority, 1.0)

    def _specialist_penalty(self, p: Platform, role: RoleSpec) -> float:
        """专才保护:平台身上"本角色用不到、但别处正紧缺"的能力越多,扣分越多。

        避免把 UGV-I(室内侦察)这类稀缺专才拿去做楼周封控这种通用活,
        导致真正需要它的室内清查缺编。惩罚随该能力的需求压力上升。
        """
        useful = set(role.required_caps) | set(role.preferred_caps)
        pen = 0.0
        for c in set(p.caps) - useful:
            pressure = self._pressure.get(c, 0.0)
            if pressure > 0:
                pen += SPECIALIST_PENALTY * min(1.0, pressure)
        return pen

    def _reasons(self, p: Platform, role: RoleSpec, task: TaskSpec) -> list:
        r = []
        matched = [c for c in role.required_caps + role.preferred_caps if c in p.caps]
        if matched:
            r.append("具备 " + "、".join(matched))
        if role.payload_req:
            r.append("载荷 %.0fkg >= %.0fkg" % (p.payload_kg, role.payload_req))
        if task.zone:
            pm = self.scene.to_m(p.x, p.y); zc = self.scene.zone_centroid_m(task.zone)
            r.append("距 %s %.0fm" % (self.scene.zones[task.zone].name,
                                      hypot(pm[0] - zc[0], pm[1] - zc[1])))
        if p.battery < 35:
            r.append("电量偏低 %d%%" % p.battery)
        return r

    # ---------------- 两阶段全局最优指派 ----------------
    def _allocate(self, tasks: list):
        """两阶段指派,避免低优先级任务群被"饿死"。

        单纯的全局标量最优会让 P1 任务吃掉共享的稀缺平台(如 UGV-I 同时具备
        indoor_nav 与 ground_recon),导致 P2 建筑连 1 台室内平台都分不到 ——
        全局效用最高,但战术上不可接受。

        阶段一:每个角色先保 1 个槽位(不分优先级)→ 保障各任务群最小可行编成;
        阶段二:剩余槽位按优先级加权,在余量平台中求全局最优。
        """
        min_slots, rest_slots = [], []
        for t in tasks:
            for role in t.roles:
                if role.count >= 1:
                    min_slots.append((t, role))
                    rest_slots.extend([(t, role)] * (role.count - 1))
        if not min_slots:
            return [], "none", []

        used: set = set()
        solver = "hungarian" if _HAS_SCIPY else "greedy"
        pairs = self._solve(min_slots, used) + self._solve(rest_slots, used)

        by_task = {}
        for (t, role), p in pairs:
            by_task.setdefault(t.tid, {}).setdefault(role.name, []).append(p)

        groups, shortfalls = [], []
        for t in tasks:
            role_map = by_task.get(t.tid, {})
            squads, members, assigns = [], [], {}
            for role in t.roles:
                got = role_map.get(role.name, [])
                squads.append(Squad(role.name, role.label, got, role.count))
                for p in got:
                    assigns[p.pid] = Assignment(p.pid, role.name,
                                                self._score(p, role, t),
                                                self._reasons(p, role, t))
                    members.append(p)
                if len(got) < role.count:
                    shortfalls.append("%s · %s 缺编 %d/%d" %
                                      (t.name, role.label, role.count - len(got), role.count))
            groups.append(GroupPlan(t.gid, t.name, t.objective, t, members, assigns, squads))

        reserve = [p for p in self.platforms if p.pid not in used]
        if reserve:
            gid = chr(ord("A") + len(tasks))
            groups.append(GroupPlan(
                gid, "预备队", "集结区待命,响应动态增援", None, reserve,
                {p.pid: Assignment(p.pid, "reserve", 0.0, ["能力冗余,编入预备"])
                 for p in reserve},
                [Squad("reserve", "预备", reserve, 0)]))
        return groups, solver, shortfalls

    def _solve(self, slots, used: set):
        """在未占用平台中为给定槽位求指派;就地更新 used。"""
        if not slots:
            return []
        avail = [p for p in self.platforms if p.pid not in used]
        if not avail:
            return []
        pairs = (self._hungarian(slots, avail) if _HAS_SCIPY
                 else self._greedy(slots, avail))
        for _, p in pairs:
            used.add(p.pid)
        return pairs

    def _hungarian(self, slots, avail):
        cost = np.full((len(slots), len(avail)), INFEASIBLE, dtype=float)
        for i, (t, role) in enumerate(slots):
            for j, p in enumerate(avail):
                if self._feasible(p, role):
                    cost[i, j] = -self._score(p, role, t)
        rows, cols = linear_sum_assignment(cost)
        return [(slots[i], avail[j]) for i, j in zip(rows, cols)
                if cost[i, j] < INFEASIBLE / 2]

    def _greedy(self, slots, avail):
        taken, pairs = set(), []
        order = sorted(range(len(slots)),
                       key=lambda i: _PRIORITY_RANK.get(slots[i][0].priority, 2))
        for i in order:
            t, role = slots[i]
            cands = [p for p in avail
                     if p.pid not in taken and self._feasible(p, role)]
            if not cands:
                continue
            best = max(cands, key=lambda p: self._score(p, role, t))
            taken.add(best.pid)
            pairs.append(((t, role), best))
        return pairs

    # ---------------- L1 推理 ----------------
    def _l1_reasoning(self, tasks, groups, solver, shortfalls, scale_notes=None) -> ReasoningNode:
        n_struct = len([t for t in tasks if t.kind == "structure"])
        n_slot = sum(r.count for t in tasks for r in t.roles)
        n_used = sum(len(g.members) for g in groups if g.spec)
        nf = self.scene.no_fly_ceiling()
        solver_txt = ("<b>匈牙利算法</b>求全局最优指派" if solver == "hungarian"
                      else "贪心指派(scipy 不可用)")
        scale_txt = ""
        if scale_notes:
            scale_txt = ("<b>供给感知下调</b>:%s。" % ";".join(scale_notes))
        sf = ("<kv>残余缺编 %d 项</kv>,已记入告警。" % len(shortfalls)) if shortfalls else ""
        think = (
            "读取 JSON 场景:<kv>%d 栋建筑</kv> + 主干道/支路通行网,禁飞带天花板 <kv>%dm</kv>,"
            "主干道路障(有旁路可绕)、A 支路受阻(无旁路→须清障)。"
            "→ 每栋建筑编成一个<b>任务群</b>,另设总封控圈任务群;"
            "角色需求由场景实算(封控点按周长、室内分队按楼层、破障按受阻通路数)。%s"
            "共 <kv>%d 个角色槽位</kv>,对 %d 台平台用%s(含<b>专才保护</b>:"
            "稀缺能力不派通用活),已编 <kv>%d</kv> 台,余者入预备队。%s"
            % (n_struct, nf, scale_txt, n_slot, len(self.platforms), solver_txt, n_used, sf))
        items = []
        for g in groups:
            if g.spec:
                brief = "、".join("%s×%d" % (s.label, len(s.members))
                                 for s in g.squads if s.members)
                items.append(TaskItem(g.gid, g.gid, "%s —— %s" % (g.objective, brief),
                                      g.spec.priority))
            else:
                items.append(TaskItem(g.gid, g.gid, "%s —— %d 台" % (g.objective, len(g.members))))
        return ReasoningNode("L1", "顶层 · 全局任务规划", MODEL_L1, think, items)

    # ---------------- L2 / L3 ----------------
    def plan_group(self, gp: GlobalPlan, gid: str):
        g = gp.group(gid)
        if g is None:
            e = ReasoningNode("L2", "中层 · 无此组", MODEL_L2, "该组不存在。")
            return e, ReasoningNode("L3", "底层 · —", MODEL_L3, "—")
        if g.spec is None:
            return self._l2_reserve(g), self._l3_reserve(g)
        if g.spec.kind == "cordon":
            return self._l2_cordon(g), self._l3_cordon(g)
        if g.spec.kind == "survey":
            return self._l2_survey(g), self._l3_survey(g)
        if g.spec.kind == "transport":
            return self._l2_transport(g), self._l3_transport(g)
        return self._l2_structure(g), self._l3_structure(g)

    # ---- 广域侦察型 ----
    def _l2_survey(self, g: GroupPlan) -> ReasoningNode:
        zid = g.spec.zone
        x0, y0, x1, y1 = self.scene.zone_bbox_m(zid)
        width = x1 - x0
        n = max(len(g.members), 1)
        sectors = max(n, ceil(width / 100.0))
        tallest = self.scene.tallest_building_near_zone(zid)
        h = tallest.attrs.get("height_m", 0) if tallest else 0
        alt = h + SURVEY_CLEARANCE_M
        think = ("读取区域多边形,面积 <kv>%.0fm²</kv>、宽 %.0fm。按扫描带宽 100m "
                 "<b>划分为 %d 个扇区</b>,%d 架 UAV 分担。扫描高度 = 最高建筑 %dm + 余量 "
                 "%.0fm = <kv>%.0fm AGL</kv>;目标 conf>0.85 即转跟踪。"
                 % (self.scene.zone_area_m2(zid), width, sectors, n, h,
                    SURVEY_CLEARANCE_M, alt))
        items = []
        for i, m in enumerate(g.members):
            mine = [f"S{j+1}" for j in range(sectors) if j % n == i]
            extra = " + 目标复核" if "target_confirm" in m.caps else ""
            items.append(TaskItem(g.gid, m.pid, "扇区 %s 扫描%s" % ("/".join(mine), extra)))
        return ReasoningNode("L2", "中层 · " + g.name, MODEL_L2, think, items)

    def _l3_survey(self, g: GroupPlan) -> ReasoningNode:
        if not g.members:
            return ReasoningNode("L3", "底层 · 无可用平台", MODEL_L3, "该组无成员。")
        tallest = self.scene.tallest_building_near_zone(g.spec.zone)
        alt = (tallest.attrs.get("height_m", 0) if tallest else 0) + SURVEY_CLEARANCE_M
        m = g.members[0]
        think = ("将 %s 的扇区扫描编译为技能序列;VL 模型做目标确认与异常检测,"
                 "导航/避障交由经典控制栈,LLM 不入控制环。" % m.pid)
        skills = ["goto(S1_wp, alt=%.0fm)" % alt, "scan(pattern=boustrophedon)",
                  "vl_detect(target)", "track(if conf>0.85)", "report(scene_json)"]
        return ReasoningNode("L3", "底层 · %s 执行" % m.pid, MODEL_L3, think, skills=skills)

    # ---- 物资运输型 ----
    def _l2_transport(self, g: GroupPlan) -> ReasoningNode:
        route, geo, detour = self.scene.shortest_ground_path()
        blockers = self.scene.path_blockers(route) if route else []
        relay_alt = self.scene.no_fly_ceiling() + RELAY_CLEARANCE_M
        carrier = next((m for m in g.members
                        if g.assignments[m.pid].role == "carrier"), None)
        escort = next((m for m in g.members
                       if g.assignments[m.pid].role == "escort"), None)
        if blockers:
            blk = ",通路受 <kv>%s</kv> 阻断且无旁路 → 须先清障" % "、".join(b.name for b in blockers)
        elif detour:
            blk = ",<b>绕行</b>规避路障"
        else:
            blk = ",沿主干道直行"
        think = ("在地面通行子图上求运输路径:<kv>%s</kv>,长 <kv>%.0fm</kv>%s。"
                 "护航高度 = 禁飞天花板 %dm + 余量 %.0fm = <kv>%.0fm</kv>,"
                 "在通信盲区前置补链。"
                 % ("→".join(route) if route else "无可行路径", geo, blk,
                    self.scene.no_fly_ceiling(), RELAY_CLEARANCE_M, relay_alt))
        items = []
        if carrier:
            items.append(TaskItem(g.gid, carrier.pid, "沿路径运输至补给点(%.0fm)" % geo))
        if escort:
            items.append(TaskItem(g.gid, escort.pid, "%.0fm 伴随中继 + 前方侦察" % relay_alt))
        return ReasoningNode("L2", "中层 · " + g.name, MODEL_L2, think, items)

    def _l3_transport(self, g: GroupPlan) -> ReasoningNode:
        if not g.members:
            return ReasoningNode("L3", "底层 · 无可用平台", MODEL_L3, "该组无成员。")
        route, _, _ = self.scene.shortest_ground_path()
        carrier = next((m for m in g.members
                        if g.assignments[m.pid].role == "carrier"), g.members[0])
        think = ("将 %s 的运输编译为技能序列;VL 模型识别地面障碍与可通行性,"
                 "路径跟踪/制动交由底盘控制栈。" % carrier.pid)
        skills = ["load(cargo)", "follow(route=[%s])" % "→".join(route),
                  "vl_obstacle_check()", "handover(delivery_zone)", "report(status)"]
        return ReasoningNode("L3", "底层 · %s 执行" % carrier.pid, MODEL_L3, think, skills=skills)

    def _l2_structure(self, g: GroupPlan) -> ReasoningNode:
        z = self.scene.zones[g.spec.zone]
        floors = z.attrs.get("floors", 1)
        hm = z.attrs.get("height_m", 0)
        alt = hm + SURVEY_CLEARANCE_M
        entry = next((self.scene.objects[e] for e in z.attrs.get("entries", [])
                      if e in self.scene.objects
                      and self.scene.objects[e].attrs.get("breach_req")), None)
        route, geo, detour, blockers = [], 0.0, False, []
        if entry:
            route, geo, detour = self.scene.shortest_ground_path("stage", entry.oid)
            blockers = self.scene.path_blockers(route)
        if blockers:
            blk = (",通路受 <kv>%s</kv> 阻断且无旁路 → 破障分队须先行清除"
                   % "、".join(b.name for b in blockers))
        elif detour:
            blk = ",<b>绕行</b>规避路障"
        else:
            blk = ",通路畅通"
        think = (
            "任务群细化为 %d 个分队。%s 高 %dm/%dF → 广域侦察高度 <kv>%.0fm AGL</kv>"
            "(低于禁飞带 %dm),立面逐层扫描 3→%dm。抵近路径 <kv>%.0fm</kv>%s。"
            "室内清查按楼层分配,微型机先探、履带随后。"
            % (len([s for s in g.squads if s.members]), z.name, hm, floors, alt,
               self.scene.no_fly_ceiling(), hm, geo, blk))
        items = [TaskItem(g.gid, s.label,
                          "、".join(m.pid for m in s.members) +
                          ("  [缺编 %d]" % s.shortfall if s.shortfall else ""))
                 for s in g.squads if s.members or s.shortfall]
        return ReasoningNode("L2", "中层 · " + g.name, MODEL_L2, think, items)

    def _l3_structure(self, g: GroupPlan) -> ReasoningNode:
        z = self.scene.zones[g.spec.zone]
        alt = z.attrs.get("height_m", 0) + SURVEY_CLEARANCE_M
        sq = next((s for s in g.squads if s.role == "air_facade" and s.members), None)
        m = sq.members[0] if sq else (g.members[0] if g.members else None)
        if m is None:
            return ReasoningNode("L3", "底层 · 无可用平台", MODEL_L3, "该组无成员。")
        think = ("将 %s 的立面扫描编译为技能序列;VL 模型做目标确认,"
                 "导航/避障交由经典控制栈,LLM 不入控制环。" % m.pid)
        skills = ["takeoff(alt=%.0fm)" % alt, "goto(%s)" % z.zid,
                  "facade_scan(alt=3→%dm, step=3m)" % z.attrs.get("height_m", 0),
                  "vl_confirm(target)", "report(scene_json)"]
        return ReasoningNode("L3", "底层 · %s 执行" % m.pid, MODEL_L3, think, skills=skills)

    def _l2_cordon(self, g: GroupPlan) -> ReasoningNode:
        pts = [o for o in self.scene.objects.values() if o.attrs.get("road") == "cordon"]
        think = ("沿总封控圈布设 <kv>%d 个封控点</kv>(按周长 / %.0fm 间距实算),"
                 "控制主干道两端与四角;地面中继构 mesh,空中监视覆盖楼间连络路。"
                 "<b>封控闭合是内部清查的前置门禁</b>(ROE)。"
                 % (len(pts), CORDON_SPACING_M))
        items = [TaskItem(g.gid, s.label, "、".join(m.pid for m in s.members))
                 for s in g.squads if s.members]
        return ReasoningNode("L2", "中层 · " + g.name, MODEL_L2, think, items)

    def _l3_cordon(self, g: GroupPlan) -> ReasoningNode:
        m = g.members[0] if g.members else None
        if m is None:
            return ReasoningNode("L3", "底层 · 无可用平台", MODEL_L3, "该组无成员。")
        think = "将 %s 的封控编译为技能序列,到位后转入持续监视。" % m.pid
        skills = ["follow(route→cordon_pt)", "cordon_hold()",
                  "vl_detect(person|vehicle)", "report(event)"]
        return ReasoningNode("L3", "底层 · %s 执行" % m.pid, MODEL_L3, think, skills=skills)

    def _l2_reserve(self, g: GroupPlan) -> ReasoningNode:
        by_type = {}
        for m in g.members:
            by_type[m.pid[:5]] = by_type.get(m.pid[:5], 0) + 1
        brief = "、".join("%s×%d" % (k, v) for k, v in sorted(by_type.items()))
        think = ("预备队 <kv>%d 台</kv>(%s)保持热待命,订阅各任务群事件流;"
                 "收到增援请求后由 L1 动态编入。" % (len(g.members), brief))
        items = [TaskItem(g.gid, "预备", "%d 台 · 订阅事件流" % len(g.members))]
        return ReasoningNode("L2", "中层 · 预备队协调", MODEL_L2, think, items)

    def _l3_reserve(self, g: GroupPlan) -> ReasoningNode:
        m = g.members[0]
        think = "保持低功耗待命,仅运行事件监听技能,收到调度后唤醒完整技能栈。"
        skills = ["standby(low_power)", "listen(event_bus)", "on_dispatch → wake()"]
        return ReasoningNode("L3", "底层 · %s 执行" % m.pid, MODEL_L3, think, skills=skills)

    def assemble(self, gp: GlobalPlan, gid: str) -> PlanResult:
        l2, l3 = self.plan_group(gp, gid)
        return PlanResult(gp.instruction, [gp.l1_node, l2, l3], gp.latency_ms)
