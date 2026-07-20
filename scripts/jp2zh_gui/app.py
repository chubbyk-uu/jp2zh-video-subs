from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QLockFile, QSettings
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from portable_runtime import portable_config_path, single_instance_lock_path
from .i18n import LanguageManager
from .window import MainWindow


def acquire_instance_lock(lock_path: Path | None = None) -> QLockFile | None:
    path = lock_path or single_instance_lock_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    instance_lock = QLockFile(str(path))
    instance_lock.setStaleLockTime(0)
    return instance_lock if instance_lock.tryLock(0) else None


def main() -> int:
    application = QApplication(sys.argv)
    application.setApplicationName("jp2zh-video-subs")
    icon_path = Path(__file__).with_name("assets") / "app-icon.png"
    application.setWindowIcon(QIcon(str(icon_path)))
    config_path = portable_config_path()
    settings = (
        QSettings(str(config_path), QSettings.Format.IniFormat)
        if config_path is not None
        else QSettings("jp2zh-video-subs", "jp2zh-video-subs")
    )
    language_manager = LanguageManager(application, settings)
    language_manager.start()
    instance_lock = acquire_instance_lock()
    if instance_lock is None:
        QMessageBox.warning(
            None,
            QCoreApplication.translate("Application", "Application already running"),
            QCoreApplication.translate("Application", "jp2zh Subtitle Tool is already running."),
        )
        return 1
    window = MainWindow(settings=settings, language_manager=language_manager)
    window.show()
    # Keep the QLockFile alive until the QApplication event loop exits.
    return application.exec()
