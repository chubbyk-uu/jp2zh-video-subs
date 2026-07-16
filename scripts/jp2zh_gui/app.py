from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from .window import MainWindow


def main() -> int:
    application = QApplication(sys.argv)
    application.setApplicationName("jp2zh-video-subs")
    window = MainWindow()
    window.show()
    return application.exec()
