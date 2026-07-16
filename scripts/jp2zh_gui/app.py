from __future__ import annotations

import sys

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from portable_runtime import portable_config_path
from .window import MainWindow


def main() -> int:
    application = QApplication(sys.argv)
    application.setApplicationName("jp2zh-video-subs")
    config_path = portable_config_path()
    settings = (
        QSettings(str(config_path), QSettings.Format.IniFormat)
        if config_path is not None
        else QSettings("jp2zh-video-subs", "jp2zh-video-subs")
    )
    window = MainWindow(settings=settings)
    window.show()
    return application.exec()
