"""主窗口装配与信号接线。

布局:头部栏 + 三栏主体(编组 / 地图 / 任务+推理链)+ 底部时间线。
交互:
  · 左栏选组   → 联动推理链作用域,并按该组重算分层规划
  · 任务下达   → 后台线程调用 mock 规划器,完成后渲染推理链
"""
from __future__ import annotations
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout)
from PySide6.QtCore import Qt, QThread, Signal, QObject

from .config import C, APP_NAME, VERSION
from .theme import stylesheet
from .models.data import seed_groups
from .models.mock_llm import MockPlanner, PlanResult
from .widgets.header_bar import HeaderBar
from .widgets.group_tree import GroupTree
from .widgets.situation_map import SituationMap
from .widgets.task_panel import TaskPanel
from .widgets.reasoning_chain import ReasoningChain
from .widgets.timeline import Timeline


class PlanWorker(QObject):
    """在后台线程运行 mock 规划器,避免阻塞界面。"""
    done = Signal(object)   # PlanResult

    def __init__(self, instruction: str, group_id: str):
        super().__init__()
        self._instruction = instruction
        self._group_id = group_id
        self._planner = MockPlanner()

    def run(self):
        result = self._planner.plan(self._instruction, self._group_id)
        self.done.emit(result)


SCOPE = {"A": "全局 · A 组", "B": "全局 · B 组", "C": "全局 · C 组"}


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME}  ·  v{VERSION}")
        self.resize(1440, 900)
        self.setStyleSheet(stylesheet())

        self._groups = seed_groups()
        self._current_group = "A"
        self._thread: QThread | None = None

        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0); root.setSpacing(0)

        # 头部
        self.header = HeaderBar()
        root.addWidget(self.header)

        # 主体三栏
        grid = QWidget()
        g = QHBoxLayout(grid); g.setContentsMargins(10, 10, 10, 10); g.setSpacing(10)

        self.tree = GroupTree(self._groups)
        self.tree.setFixedWidth(272)
        g.addWidget(self.tree)

        self.map = SituationMap(self._groups)
        g.addWidget(self.map, 1)

        right = QWidget(); right.setFixedWidth(380)
        rv = QVBoxLayout(right); rv.setContentsMargins(0, 0, 0, 0); rv.setSpacing(10)
        self.task = TaskPanel()
        self.chain = ReasoningChain()
        rv.addWidget(self.task)
        rv.addWidget(self.chain, 1)
        g.addWidget(right)

        root.addWidget(grid, 1)

        # 底部时间线
        timeline_wrap = QWidget()
        tw = QVBoxLayout(timeline_wrap); tw.setContentsMargins(10, 0, 10, 10)
        tw.addWidget(Timeline())
        root.addWidget(timeline_wrap)

        self.setCentralWidget(central)

        # ---- 接线 ----
        self.tree.groupSelected.connect(self._on_group_selected)
        self.task.planRequested.connect(self._on_plan_requested)

        # 初次渲染
        self._run_plan(self.task.cmd.toPlainText().strip(), self._current_group)

    # ---- 分组选择 ----
    def _on_group_selected(self, gid: str):
        self._current_group = gid
        self.map.map.set_view(self._current_view())
        self._run_plan(self.task.cmd.toPlainText().strip(), gid)

    def _current_view(self) -> str:
        # 保持地图当前视图不变(默认态势)
        for b in self.map._bg.buttons():
            if b.isChecked():
                return b.property("view")
        return "sit"

    # ---- 任务下达 ----
    def _on_plan_requested(self, text: str):
        self._run_plan(text, self._current_group)

    def _run_plan(self, instruction: str, group_id: str):
        if self._thread and self._thread.isRunning():
            return
        self.task.set_generating(True)

        self._thread = QThread()
        self._worker = PlanWorker(instruction, group_id)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.done.connect(self._on_plan_done)
        self._worker.done.connect(self._thread.quit)
        self._thread.finished.connect(self._cleanup_thread)
        self._thread.start()

    def _on_plan_done(self, result: PlanResult):
        self.chain.render_plan(result, SCOPE.get(self._current_group, "全局"))
        self.task.set_generating(False)

    def _cleanup_thread(self):
        if self._thread:
            self._thread.deleteLater()
        self._thread = None
