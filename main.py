#!/usr/bin/env python3
"""
Video to Script — 桌面应用
从视频文件自动提取剧本结构、钩子分析和人物图谱
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from ui.main_window import MainWindow
from ui.styles import APP_STYLESHEET


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Video to Script")
    app.setApplicationVersion("2.1.7")
    # macOS 使用原生风格，Windows/Linux 使用 Fusion
    if sys.platform == "darwin":
        app.setStyle("macOS")
    else:
        app.setStyle("Fusion")
    app.setStyleSheet(APP_STYLESHEET)

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
