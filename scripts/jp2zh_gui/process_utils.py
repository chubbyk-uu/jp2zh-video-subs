"""Platform-specific process launch helpers for the desktop GUI."""
from __future__ import annotations

import sys

from PySide6.QtCore import QProcess


CREATE_NO_WINDOW = 0x08000000


def hide_windows_console(process: QProcess) -> None:
    """Prevent a console window when a GUI process launches a Windows child."""
    if sys.platform != "win32" or not hasattr(process, "setCreateProcessArgumentsModifier"):
        return

    def add_flag(arguments) -> None:
        arguments.flags |= CREATE_NO_WINDOW

    process.setCreateProcessArgumentsModifier(add_flag)
