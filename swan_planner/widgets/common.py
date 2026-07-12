"""通用 UI 构件:卡片容器、分隔线、彩色圆点等。"""
from __future__ import annotations
from PySide6.QtWidgets import (QFrame, QVBoxLayout, QHBoxLayout, QLabel, QWidget)
from PySide6.QtCore import Qt

from ..config import C


class Card(QFrame):
    """带标题栏的圆角卡片容器。

    通过 .body 布局向卡片主体添加内容;通过 header 右侧插槽放置标签/控件。
    """
    def __init__(self, title: str, icon: str = "", sub: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ---- header ----
        header = QFrame(); header.setObjectName("CardHeader")
        header.setFixedHeight(42)
        h = QHBoxLayout(header); h.setContentsMargins(13, 0, 13, 0); h.setSpacing(8)
        t = QLabel(f"{icon}  {title}".strip()) if icon else QLabel(title)
        t.setObjectName("CardTitle")
        h.addWidget(t)
        if sub:
            s = QLabel(sub); s.setObjectName("CardSub")
            h.addWidget(s)
        h.addStretch(1)
        self.header_layout = h
        outer.addWidget(header)

        # ---- body ----
        body = QWidget()
        self.body = QVBoxLayout(body)
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setSpacing(0)
        outer.addWidget(body, 1)

    def add_header_widget(self, w: QWidget):
        self.header_layout.addWidget(w)


class Dot(QLabel):
    """小彩色方点(用于图例/层级标记)。"""
    def __init__(self, color: str, size: int = 9, radius: int = 2):
        super().__init__()
        self.setFixedSize(size, size)
        self.setStyleSheet(f"background:{color};border-radius:{radius}px;")


def hline() -> QFrame:
    ln = QFrame(); ln.setFrameShape(QFrame.HLine)
    ln.setStyleSheet(f"color:{C.LINE_SOFT};background:{C.LINE_SOFT};max-height:1px;")
    return ln
