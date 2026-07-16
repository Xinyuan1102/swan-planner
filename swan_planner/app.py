"""主窗口装配与信号接线。

执行逻辑(已优化):
  · 全局规划(L1)在后台线程执行,只在初始化与"生成方案"时触发;
  · 分组选择只做 L2/L3 的惰性组装(纯查询,毫秒级),不重算 L1。
数据流:JSON 场景 + 平台能力 → PlannerEngine 能力匹配分配 → 分组树 + 推理链。
"""
from __future__ import annotations
from pathlib import Path
from PySide6.QtWidgets import QMainWindow, QWidget, QVBoxLayout, QHBoxLayout
from PySide6.QtCore import Qt, QThread, Signal, QObject

from .config import APP_NAME, VERSION
from .theme import stylesheet
from .models.scene import load_scene
from .models.data import load_platforms
from .models.planner import PlannerEngine, GlobalPlan
from .widgets.header_bar import HeaderBar
from .widgets.group_tree import GroupTree
from .widgets.situation_map import SituationMap
from .widgets.task_panel import TaskPanel
from .widgets.reasoning_chain import ReasoningChain
from .widgets.timeline import Timeline

# 默认场景:社区片区(主干道 + 支路 + 3 栋建筑),100 台平台
_DATA = Path(__file__).resolve().parent / "data" / "scenarios"
SCENARIO_SCENE = _DATA / "large_scene.json"
SCENARIO_PLATFORMS = _DATA / "large_platforms.json"


class GlobalPlanWorker(QObject):
    """后台执行 L1 全局规划(含能力匹配分配)。"""
    done = Signal(object)   # GlobalPlan

    def __init__(self, engine: PlannerEngine, instruction: str):
        super().__init__()
        self._engine = engine
        self._instruction = instruction

    def run(self):
        self.done.emit(self._engine.plan_global(self._instruction))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME}  ·  v{VERSION}")
        self.resize(1440, 900)
        self.setStyleSheet(stylesheet())

        # ---- 后端:场景 + 平台能力 + 规划引擎 ----
        self.scene = load_scene(SCENARIO_SCENE)
        self.platforms = load_platforms(SCENARIO_PLATFORMS)
        self.engine = PlannerEngine(self.scene, self.platforms)
        self.global_plan: GlobalPlan | None = None
        self._current_group = "A"
        self._thread: QThread | None = None

        # ---- 布局 ----
        central = QWidget()
        root = QVBoxLayout(central); root.setContentsMargins(0, 0, 0, 0); root.setSpacing(0)

        self.header = HeaderBar()
        root.addWidget(self.header)

        grid = QWidget()
        g = QHBoxLayout(grid); g.setContentsMargins(10, 10, 10, 10); g.setSpacing(10)

        self.tree = GroupTree()
        self.tree.setFixedWidth(272)
        g.addWidget(self.tree)

        self.map = SituationMap([])          # 平台标记随分配结果更新
        g.addWidget(self.map, 1)

        right = QWidget(); right.setFixedWidth(380)
        rv = QVBoxLayout(right); rv.setContentsMargins(0, 0, 0, 0); rv.setSpacing(10)
        self.task = TaskPanel()
        self.chain = ReasoningChain()
        rv.addWidget(self.task); rv.addWidget(self.chain, 1)
        g.addWidget(right)
        root.addWidget(grid, 1)

        tl_wrap = QWidget()
        tw = QVBoxLayout(tl_wrap); tw.setContentsMargins(10, 0, 10, 10)
        tw.addWidget(Timeline())
        root.addWidget(tl_wrap)

        self.setCentralWidget(central)

        # ---- 接线 ----
        self.tree.groupSelected.connect(self._on_group_selected)
        self.task.planRequested.connect(self._on_plan_requested)

        # 初次全局规划
        self._run_global(self.task.cmd.toPlainText().strip())

    # ---- 分组选择:仅惰性组装 L2/L3 ----
    def _on_group_selected(self, gid: str):
        self._current_group = gid
        if self.global_plan is None:
            return
        result = self.engine.assemble(self.global_plan, gid)
        g = self.global_plan.group(gid)
        self.chain.render_plan(result, g.name if g else "全局")

    # ---- 任务下达:重新全局规划 ----
    def _on_plan_requested(self, text: str):
        self._run_global(text)

    def _run_global(self, instruction: str):
        if self._thread and self._thread.isRunning():
            return
        self.task.set_generating(True)
        self._thread = QThread()
        self._worker = GlobalPlanWorker(self.engine, instruction)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.done.connect(self._on_global_done)
        self._worker.done.connect(self._thread.quit)
        self._thread.finished.connect(self._cleanup_thread)
        self._thread.start()

    def _on_global_done(self, gp: GlobalPlan):
        self.global_plan = gp
        # 用能力匹配的分配结果刷新分组树与地图
        self.tree.set_groups(gp.as_groups())
        self.map.set_platforms([m for grp in gp.groups for m in grp.members])
        # 渲染当前组(set_groups 会触发 groupSelected → 已渲染);兜底再渲一次
        self._on_group_selected(self.tree._selected or self._current_group)
        self.task.set_generating(False)

    def _cleanup_thread(self):
        if self._thread:
            self._thread.deleteLater()
        self._thread = None
