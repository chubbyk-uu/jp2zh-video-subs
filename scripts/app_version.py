"""Application version shown by the GUI and exposed through Qt."""

APP_VERSION = "0.1.0"
APP_BUILD = "2026.07.27-release"


def display_version() -> str:
    return f"{APP_VERSION} ({APP_BUILD})"
