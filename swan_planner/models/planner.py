"""规划引擎:基于 JSON 场景描述 + 平台能力档案,完成任务分配。

执行逻辑(已优化为分层惰性计算):
  · plan_global(instruction)  —— L1 顶层:解析指令 → 场景落地 → 构建带能力需求的
      任务规格 → 能力匹配分配平台 → 生成分组。全局只跑一次。
  · plan_group(global, gid)   —— L2/L3:对选定组做细化(扇区分解 / 路径搜索)与
      技能编译。按组惰性计算,选组时才触发,不重算 L1。

任务分配的核心是**能力匹配**:每个任务角色声明 required/preferred 能力与载荷需求,
引擎对候选平台做可行性过滤 + 打分(能力契合 + 就近 + 电量/续航),择优指派。
"""
from __future__ import annotations
from dataclasses import dataclass, field
from math import hypot, ceil
import time

from ..config import MODEL_L1, MODEL_L2, MODEL_L3
from .scene import Scene
from .data import Platform, Group

# 规划参数
SWATH_M = 100.0            # 单架 UAV 单趟扫描带宽
SURVEY_CLEARANCE_M = 20.0  # 扫描高度相对最高建筑的余量
RELAY_CLEARANCE_M = 20.0   # 中继高度相对禁飞天花板的余量
COVER_PER_UAV_M2 = 30000.0 # 单架 UAV 覆盖能力(用于估算所需架数)


# ==========================================================================
# 层间输出类型(统一 Schema)
# ==========================================================================
@dataclass
class TaskItem:
    group_id: str
    tag: str
    objective: str
    priority: str = ""
    constraints: list[str] = field(default_factory=list)
    success: str = ""


@dataclass
class ReasoningNode:
    layer: str
    title: str
    model: str
    think: str
    tasks: list[TaskItem] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)


@dataclass
class PlanResult:
    instruction: str
    chain: list[ReasoningNode]
    latency_ms: int


# ==========================================================================
# 任务规格与分配结果
# ==========================================================================
@dataclass
class RoleSpec:
    name: str                       # coverage / carrier / escort / reserve
    required_caps: list[str]
    preferred_caps: list[str]
    count: int
    payload_req: float = 0.0


@dataclass
class TaskSpec:
    tid: str
    gid: str
    name: str
    objective: str
    priority: str
    zone: str | None
    roles: list[RoleSpec]


@dataclass
class Assignment:
    pid: str
    role: str
    score: float
    reasons: list[str]


@dataclass
class GroupPlan:
    gid: str
    name: str
    objective: str
    spec: TaskSpec | None
    members: list[Platform]
    assignments: dict                # pid -> Assignment


@dataclass
class GlobalPlan:
    instruction: str
    scene_context: str
    objectives: list[str]
    tasks: list[TaskSpec]
    groups: list[GroupPlan]
    l1_node: ReasoningNode
    latency_ms: int

    def group(self, gid: str) -> GroupPlan | None:
        return next((g for g in self.groups if g.gid == gid), None)

    def as_groups(self) -> list[Group]:
        """转换为 UI 分组树可渲染的 Group 列表。"""
        return [Group(g.gid, g.name, g.objective, g.members) for g in self.groups]


_PRIORITY_RANK = {"P1": 0, "P2": 1, "": 2}


class PlannerEngine:
    def __init__(self, scene: Scene, platforms: list[Platform]):
        self.scene = scene
        self.platforms = platforms
        self._diag = hypot(scene.ao_w, scene.ao_h)

    # ----------------------------------------------------------------------
    # L1 顶层:全局任务规划
    # ----------------------------------------------------------------------
    def plan_global(self, instruction: str) -> GlobalPlan:
        t0 = time.time()
        time.sleep(0.25)                             # 模拟大模型推理耗时
        ctx = self.scene.to_prompt_context()
        objectives = self._parse_intent(instruction)
        tasks = self._build_task_specs(objectives)
        groups = self._allocate(tasks)
        l1 = self._l1_reasoning(objectives, groups)
        return GlobalPlan(instruction, ctx, [o[2] for o in objectives],
                          tasks, groups, l1, int((time.time() - t0) * 1000))

    def _parse_intent(self, instruction: str):
        """自然语言 → 目标列表 [(kind, zone_id, 描述)]。生产环境由 Qwen 完成。"""
        objs = []
        if any(k in instruction for k in ("侦察", "侦查", "搜索", "定位", "识别")):
            z = self.scene.nearest_zone_to(0.3, 0.3, "survey") or \
                (self.scene.zones_of("survey") or [None])[0]
            if z:
                objs.append(("survey", z.zid, z.attrs.get("objective", "侦察目标")))
        if any(k in instruction for k in ("运输", "物资", "补给", "运送", "保障")):
            z = (self.scene.zones_of("delivery") or [None])[0]
            if z:
                objs.append(("transport", z.zid, z.attrs.get("objective", "物资运输")))
        return objs

    def _build_task_specs(self, objectives) -> list[TaskSpec]:
        specs = []
        gid_map = {"survey": "A", "transport": "B"}
        for kind, zid, desc in objectives:
            z = self.scene.zones[zid]
            if kind == "survey":
                n = max(2, ceil(self.scene.zone_area_m2(zid) / COVER_PER_UAV_M2))
                specs.append(TaskSpec(
                    "T-SURVEY", "A", "A 组 · 空中侦察", desc,
                    z.attrs.get("priority", "P1"), zid,
                    [RoleSpec("coverage", ["aerial_survey"],
                              ["eo_imaging", "sar_imaging", "target_track", "target_confirm"], n)]))
            elif kind == "transport":
                cargo = z.attrs.get("cargo_kg", 0)
                specs.append(TaskSpec(
                    "T-TRANSPORT", "B", "B 组 · 物资运输", desc,
                    z.attrs.get("priority", "P1"), zid,
                    [RoleSpec("carrier", ["transport"], ["obstacle_detect", "ground_nav"],
                              1, payload_req=cargo),
                     RoleSpec("escort", ["comm_relay"], ["escort", "recon"], 1)]))
        return specs

    # ---- 能力匹配分配 ----
    def _feasible(self, p: Platform, role: RoleSpec) -> bool:
        if not set(role.required_caps).issubset(p.caps):
            return False
        if role.payload_req and p.payload_kg < role.payload_req:
            return False
        return True

    def _score(self, p: Platform, role: RoleSpec, task: TaskSpec) -> float:
        s = 100.0
        s += 12.0 * len(set(role.preferred_caps) & set(p.caps))     # 能力契合
        if task.zone:                                               # 就近
            pm = self.scene.to_m(p.x, p.y)
            zc = self.scene.zone_centroid_m(task.zone)
            d = hypot(pm[0] - zc[0], pm[1] - zc[1])
            s += 25.0 * max(0.0, 1 - d / self._diag)
        s += p.battery / 8.0                                        # 电量
        s += p.endurance_min / 20.0                                 # 续航
        return s

    def _reasons(self, p: Platform, role: RoleSpec, task: TaskSpec) -> list[str]:
        r = []
        matched = [c for c in role.required_caps + role.preferred_caps if c in p.caps]
        if matched:
            r.append("具备 " + "、".join(matched))
        if role.payload_req:
            r.append(f"载荷 {p.payload_kg:.0f}kg ≥ 需求 {role.payload_req:.0f}kg")
        if task.zone:
            pm = self.scene.to_m(p.x, p.y); zc = self.scene.zone_centroid_m(task.zone)
            r.append(f"距 {self.scene.zones[task.zone].name} {hypot(pm[0]-zc[0], pm[1]-zc[1]):.0f}m")
        if p.battery < 35:
            r.append(f"电量偏低 {p.battery}%")
        return r

    def _allocate(self, tasks: list[TaskSpec]) -> list[GroupPlan]:
        used: set[str] = set()
        groups: list[GroupPlan] = []
        for t in sorted(tasks, key=lambda x: _PRIORITY_RANK.get(x.priority, 2)):
            members, assigns = [], {}
            for role in t.roles:
                cands = [p for p in self.platforms
                         if p.pid not in used and self._feasible(p, role)]
                cands.sort(key=lambda p: self._score(p, role, t), reverse=True)
                for p in cands[:role.count]:
                    used.add(p.pid)
                    assigns[p.pid] = Assignment(p.pid, role.name,
                                                self._score(p, role, t),
                                                self._reasons(p, role, t))
                    members.append(p)
            groups.append(GroupPlan(t.gid, t.name, t.objective, t, members, assigns))
        # 预备组:未分配的平台
        reserve = [p for p in self.platforms if p.pid not in used]
        if reserve:
            groups.append(GroupPlan("C", "C 组 · 待命预备",
                                    "中心待命,响应动态增援", None, reserve,
                                    {p.pid: Assignment(p.pid, "reserve", 0.0,
                                                       ["能力冗余,编入预备"]) for p in reserve}))
        return groups

    def _l1_reasoning(self, objectives, groups: list[GroupPlan]) -> ReasoningNode:
        obj_kinds = [o[0] for o in objectives]
        nf = self.scene.no_fly_ceiling()
        tgt = (self.scene.objects_of("target") or [None])[0]
        tgt_txt = (f"含 <kv>{tgt.name}(conf {tgt.attrs.get('confidence')})</kv>"
                   if tgt else "")
        think = (
            f"解析指令得到 {len(objectives)} 条主线:"
            f"{'、'.join('<b>侦察</b>' if k=='survey' else '<b>运输</b>' for k in obj_kinds)}。"
            f"读取 JSON 场景:A 区 {tgt_txt},"
            f"禁飞区天花板 <kv>{nf}m</kv>,运输走廊存在 <kv>障碍_02</kv> 与通信盲区。"
            f"→ 按<b>能力匹配</b>指派:侦察需 aerial_survey,运输需 transport(载荷达标)+ comm_relay。"
        )
        tasks = []
        for g in groups:
            names = "、".join(m.pid for m in g.members)
            tasks.append(TaskItem(
                g.gid, g.gid, f"{g.objective} —— {names}",
                g.spec.priority if g.spec else "",
                success=(g.spec.roles[0].name if g.spec else "reserve")))
        return ReasoningNode("L1", "顶层 · 全局任务规划", MODEL_L1, think, tasks)

    # ----------------------------------------------------------------------
    # L2 / L3:按组细化(惰性)
    # ----------------------------------------------------------------------
    def plan_group(self, gp: GlobalPlan, gid: str) -> tuple[ReasoningNode, ReasoningNode]:
        g = gp.group(gid)
        if g is None:
            empty = ReasoningNode("L2", "中层 · 无此组", MODEL_L2, "该组不存在。")
            return empty, ReasoningNode("L3", "底层 · —", MODEL_L3, "—")
        if g.spec and g.spec.tid == "T-SURVEY":
            return self._l2_survey(g), self._l3_survey(g)
        if g.spec and g.spec.tid == "T-TRANSPORT":
            return self._l2_transport(g), self._l3_transport(g)
        return self._l2_reserve(g), self._l3_reserve(g)

    # ---- 侦察组 ----
    def _l2_survey(self, g: GroupPlan) -> ReasoningNode:
        zid = g.spec.zone
        x0, y0, x1, y1 = self.scene.zone_bbox_m(zid)
        width = x1 - x0
        sectors = max(len(g.members), ceil(width / SWATH_M))
        tallest = self.scene.tallest_building_near_zone(zid)
        h = tallest.attrs.get("height_m", 0) if tallest else 0
        alt = h + SURVEY_CLEARANCE_M
        tname = tallest.name if tallest else "无建筑"
        think = (
            f"读取 A 区多边形,面积 <kv>{self.scene.zone_area_m2(zid):.0f}m²</kv>、"
            f"宽 {width:.0f}m。按扫描带宽 {SWATH_M:.0f}m <b>划分为 {sectors} 个扇区</b>,"
            f"{len(g.members)} 架 UAV 轮流分担。扫描高度 = {tname} 高 {h}m + 余量 "
            f"{SURVEY_CLEARANCE_M:.0f}m = <kv>{alt:.0f}m AGL</kv>;目标 conf>0.85 即转跟踪。"
        )
        tasks = []
        for i, m in enumerate(g.members):
            mine = [f"S{j+1}" for j in range(sectors) if j % len(g.members) == i]
            role = g.assignments[m.pid].role
            extra = " + 目标复核" if "target_confirm" in m.caps else ""
            tasks.append(TaskItem("A", m.pid, f"扇区 {'/'.join(mine)} 扫描{extra}"))
        return ReasoningNode("L2", "中层 · A 组协调", MODEL_L2, think, tasks)

    def _l3_survey(self, g: GroupPlan) -> ReasoningNode:
        zid = g.spec.zone
        tallest = self.scene.tallest_building_near_zone(zid)
        alt = (tallest.attrs.get("height_m", 0) if tallest else 0) + SURVEY_CLEARANCE_M
        m = g.members[0]
        think = (f"将 {m.pid} 的\"扇区扫描\"编译为技能序列;VL 模型做<b>目标确认与异常检测</b>,"
                 f"导航/避障交由经典控制栈,LLM 不入控制环。")
        skills = [f"goto(S1_wp, alt={alt:.0f}m)", "scan(pattern=boustrophedon)",
                  "vl_detect(target)", "track(if conf>0.85)", "report(scene_json)"]
        return ReasoningNode("L3", f"底层 · {m.pid} 执行", MODEL_L3, think, skills=skills)

    # ---- 运输组 ----
    def _l2_transport(self, g: GroupPlan) -> ReasoningNode:
        path, geo, detour = self.scene.shortest_ground_path()
        relay_alt = self.scene.no_fly_ceiling() + RELAY_CLEARANCE_M
        carrier = next((m for m in g.members if g.assignments[m.pid].role == "carrier"), None)
        escort = next((m for m in g.members if g.assignments[m.pid].role == "escort"), None)
        detour_txt = "为规避 <kv>障碍_02</kv> 走上绕旁路" if detour else "沿主干道直行"
        think = (
            f"在地面通行子图上求 UGV 运输路径:<kv>{'→'.join(path)}</kv>,"
            f"长 <kv>{geo:.0f}m</kv>,{detour_txt}。"
            f"UAV 护航高度 = 禁飞天花板 {self.scene.no_fly_ceiling()}m + 余量 "
            f"{RELAY_CLEARANCE_M:.0f}m = <kv>{relay_alt:.0f}m</kv>,在开阔地通信盲区前置补链。"
        )
        tasks = []
        if carrier:
            tasks.append(TaskItem("B", carrier.pid, f"沿路径运输至补给点({geo:.0f}m)"))
        if escort:
            tasks.append(TaskItem("B", escort.pid, f"{relay_alt:.0f}m 伴随中继 + 前方侦察"))
        return ReasoningNode("L2", "中层 · B 组协调", MODEL_L2, think, tasks)

    def _l3_transport(self, g: GroupPlan) -> ReasoningNode:
        path, geo, _ = self.scene.shortest_ground_path()
        carrier = next((m for m in g.members if g.assignments[m.pid].role == "carrier"),
                       g.members[0])
        think = (f"将 {carrier.pid} 的\"运输\"编译为技能序列;VL 模型识别地面障碍与可通行性,"
                 f"路径跟踪/制动交由底盘控制栈。")
        skills = ["load(cargo)", f"follow(route=[{'→'.join(path)}])",
                  "vl_obstacle_check()", "handover(补给入口)", "report(status)"]
        return ReasoningNode("L3", f"底层 · {carrier.pid} 执行", MODEL_L3, think, skills=skills)

    # ---- 预备组 ----
    def _l2_reserve(self, g: GroupPlan) -> ReasoningNode:
        think = ("保持<b>热待命</b>,持续订阅 A/B 组事件流;收到增援请求后 "
                 "10s 内生成抵近路径并接管子任务。")
        tasks = [TaskItem("C", m.pid, "中心待命 · 订阅事件流") for m in g.members]
        return ReasoningNode("L2", "中层 · C 组协调", MODEL_L2, think, tasks)

    def _l3_reserve(self, g: GroupPlan) -> ReasoningNode:
        m = g.members[0]
        think = "保持低功耗待命,仅运行事件监听技能,收到调度后再唤醒完整技能栈。"
        skills = ["standby(low_power)", "listen(event_bus)", "on_dispatch → wake()"]
        return ReasoningNode("L3", f"底层 · {m.pid} 执行", MODEL_L3, think, skills=skills)

    # ----------------------------------------------------------------------
    # 组装:L1 + L2 + L3
    # ----------------------------------------------------------------------
    def assemble(self, gp: GlobalPlan, gid: str) -> PlanResult:
        l2, l3 = self.plan_group(gp, gid)
        return PlanResult(gp.instruction, [gp.l1_node, l2, l3], gp.latency_ms)
