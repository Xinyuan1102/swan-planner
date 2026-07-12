"""Mock 大模型规划器。

以"预测实例"的方式模拟 Qwen3.6-27B(顶层/中层)与 Qwen2.5-7B(底层)的
输入输出。真实系统中,应替换为对推理服务的调用 —— 接口保持一致:
输入(自然语言指令 + 场景图 + 资源清单)→ 输出(结构化分层规划 + 推理链)。

输出严格遵循层间统一 Schema,便于下层解析与界面校验。
"""
from __future__ import annotations
from dataclasses import dataclass, field
import time

from ..config import MODEL_L1, MODEL_L2, MODEL_L3


@dataclass
class TaskItem:
    """层间传递的结构化任务(简化的统一 Schema)。"""
    group_id: str
    tag: str                       # 承担者:组号或平台号
    objective: str                 # 目标描述
    priority: str = ""             # P1 / P2 / ""
    constraints: list[str] = field(default_factory=list)
    success: str = ""              # 成功判据


@dataclass
class ReasoningNode:
    """推理链中的一层。"""
    layer: str                     # L1 / L2 / L3
    title: str
    model: str
    think: str                     # 该层的推理说明(可含 <b>/<kv> 富文本标记)
    tasks: list[TaskItem] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)   # 仅 L3:技能原语序列


@dataclass
class PlanResult:
    instruction: str
    chain: list[ReasoningNode]
    latency_ms: int                # 模拟推理耗时


class MockPlanner:
    """预测实例版规划器。plan() 返回一条完整的分层推理链。"""

    def plan(self, instruction: str, group_id: str = "A") -> PlanResult:
        t0 = time.time()
        # 模拟一次推理耗时(真实调用时由推理服务决定)
        time.sleep(0.25)
        chain = [self._l1(), self._l2(group_id), self._l3(group_id)]
        return PlanResult(instruction, chain, int((time.time() - t0) * 1000))

    # ---- 顶层:全局任务规划 ----
    def _l1(self) -> ReasoningNode:
        think = (
            "解析指令得到两条并行主线:<b>侦察</b>与<b>运输</b>,二者时空可并行。"
            "依据场景图,A 区含 <kv>建筑群_01</kv> 与一处 <kv>可疑目标(conf 0.71)</kv>,"
            "需空中广域覆盖;B 点运输跨越开阔地,存在通信盲区。"
            "→ 按<b>能力匹配</b>与<b>地理聚类</b>分为 3 组,预备组留作动态增援。"
        )
        tasks = [
            TaskItem("A", "A", "2×UAV 覆盖 A 区,定位并跟踪可疑目标", "P1",
                     ["规避禁飞区"], "目标置信度 > 0.85"),
            TaskItem("B", "B", "UGV+UAV 空地协同运输至 B 点,UAV 中继补盲", "P1",
                     ["通信不中断"], "物资送达 B 点补给区"),
            TaskItem("C", "C", "UGV 中心待命,响应增援请求", "",
                     [], "10s 内响应调度"),
        ]
        return ReasoningNode("L1", "顶层 · 全局任务规划", MODEL_L1, think, tasks)

    # ---- 中层:分组协调(此处以 A 组为例,可按 group_id 扩展) ----
    def _l2(self, group_id: str) -> ReasoningNode:
        table = {
            "A": ("中层 · A 组协调",
                  "将 A 区按覆盖率最优<b>划分为 3 个扇区</b>,2 架 UAV 分担(其一兼顾目标复核)。"
                  "目标置信度 > 0.85 即切换<b>跟踪</b>,并请求顶层裁决是否需 C 组抵近核实。",
                  [TaskItem("A", "UAV-01", "扇区 S1/S2 光电扫描"),
                   TaskItem("A", "UAV-02", "扇区 S3 + 目标 SAR 复核")]),
            "B": ("中层 · B 组协调",
                  "规划 UGV 主运输路径并<b>规避开阔地盲区</b>,UAV-04 以中继构型伴随,"
                  "在盲区节点前置<b>提前补链</b>;UGV 电量触发换电则请求 C 组接力。",
                  [TaskItem("B", "UGV-03", "沿主干道运输至 B 点"),
                   TaskItem("B", "UAV-04", "伴随中继 + 前方路况侦察")]),
            "C": ("中层 · C 组协调",
                  "保持<b>热待命</b>,持续订阅 A/B 组事件流;一旦收到增援请求,"
                  "在 10s 内生成抵近路径并接管子任务。",
                  [TaskItem("C", "UGV-05", "中心待命 · 订阅事件流")]),
        }
        title, think, tasks = table.get(group_id, table["A"])
        return ReasoningNode("L2", title, MODEL_L2, think, tasks)

    # ---- 底层:单平台执行(编译为技能原语) ----
    def _l3(self, group_id: str) -> ReasoningNode:
        table = {
            "A": ("底层 · UAV-01 执行",
                  "将\"扇区扫描\"编译为技能序列;VL 模型对回传画面做<b>目标确认与异常检测</b>,"
                  "导航与避障交由经典控制栈,LLM 不入控制环。",
                  ["goto(S1_wp1)", "scan(pattern=boustrophedon)",
                   "vl_detect(target)", "track(if conf>0.85)", "report(scene_graph)"]),
            "B": ("底层 · UGV-03 执行",
                  "将\"运输\"编译为技能序列;VL 模型识别地面障碍与可通行性,"
                  "路径跟踪与制动交由底盘控制栈执行。",
                  ["load(cargo)", "follow(route_main)", "vl_obstacle_check()",
                   "handover(B_point)", "report(status)"]),
            "C": ("底层 · UGV-05 执行",
                  "保持低功耗待命,仅运行事件监听技能,收到调度后再唤醒完整技能栈。",
                  ["standby(low_power)", "listen(event_bus)", "on_dispatch → wake()"]),
        }
        title, think, skills = table.get(group_id, table["A"])
        return ReasoningNode("L3", title, MODEL_L3, think, skills=skills)
