#!/usr/bin/env python3
"""空地异构集群任务规划系统 · 程序入口。

运行:
    pip install -r requirements.txt
    python main.py
"""
import sys
from PySide6.QtWidgets import QApplication

from swan_planner.app import MainWindow


def main():
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
