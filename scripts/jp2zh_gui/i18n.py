"""Qt translation loading, locale resolution, and UI font selection."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QLibraryInfo, QLocale, QObject, QSettings, QTranslator, Signal
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication


TRANSLATIONS_DIR = Path(__file__).with_name("translations")
MANIFEST_PATH = TRANSLATIONS_DIR / "languages.json"
_active_manager: LanguageManager | None = None


@dataclass(frozen=True)
class LanguageSpec:
    code: str
    name: str
    aliases: tuple[str, ...]
    qm: str | None
    qt_qm: str | None


def load_language_specs(path: Path = MANIFEST_PATH) -> dict[str, LanguageSpec]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    specs: dict[str, LanguageSpec] = {}
    for item in raw["languages"]:
        code = str(item["code"])
        if code in specs:
            raise ValueError(f"duplicate language code: {code}")
        specs[code] = LanguageSpec(
            code=code,
            name=str(item["name"]),
            aliases=tuple(str(alias) for alias in item.get("aliases", [])),
            qm=str(item["qm"]) if item.get("qm") else None,
            qt_qm=str(item["qt_qm"]) if item.get("qt_qm") else None,
        )
    required = {"system", "zh_CN", "zh_TW", "en"}
    if not required.issubset(specs):
        raise ValueError(f"language manifest missing: {', '.join(sorted(required - specs.keys()))}")
    return specs


def normalise_locale(locale_name: str) -> str:
    return locale_name.split(".", 1)[0].replace("-", "_")


def resolve_language_code(requested: str, system_locale: str, specs: dict[str, LanguageSpec]) -> str:
    candidate = normalise_locale(system_locale) if requested == "system" else normalise_locale(requested)
    folded = candidate.casefold()
    for code, spec in specs.items():
        if code == "system":
            continue
        if folded == code.casefold() or folded in {normalise_locale(alias).casefold() for alias in spec.aliases}:
            return code
    language = folded.split("_", 1)[0]
    if language == "zh":
        return "zh_CN"
    if language == "en":
        return "en"
    return "en"


def translated(context: str, source: str, **values: object) -> str:
    text = QCoreApplication.translate(context, source)
    return text.format(**values) if values else text


class LanguageManager(QObject):
    language_changed = Signal(str)

    def __init__(
        self,
        application: QApplication,
        settings: QSettings,
        *,
        manifest_path: Path = MANIFEST_PATH,
        system_locale: str | None = None,
    ) -> None:
        super().__init__(application)
        self.application = application
        self.settings = settings
        self.manifest_path = manifest_path
        self.translations_dir = manifest_path.parent
        self.specs = load_language_specs(manifest_path)
        self.system_locale = system_locale or QLocale.system().name()
        self.requested_code = "system"
        self.current_code = "en"
        self._project_translator: QTranslator | None = None
        self._qt_translator: QTranslator | None = None

    def start(self) -> str:
        return self.set_language(self.settings.value("ui_language", "system", str), persist=False)

    def set_language(self, requested: str, *, persist: bool = True) -> str:
        global _active_manager
        if _active_manager is not None and _active_manager is not self:
            _active_manager._remove_translators()
        _active_manager = self
        if requested not in self.specs:
            requested = "system"
        resolved = resolve_language_code(requested, self.system_locale, self.specs)
        self._remove_translators()
        loaded_code = self._install_translators(resolved)
        self.requested_code = requested
        self.current_code = loaded_code
        if persist:
            self.settings.setValue("ui_language", requested)
            self.settings.sync()
        self._apply_ui_font()
        self.language_changed.emit(loaded_code)
        return loaded_code

    def _install_translators(self, code: str) -> str:
        spec = self.specs[code]
        if spec.qm:
            project = QTranslator(self)
            if not project.load(str(self.translations_dir / spec.qm)):
                return "en"
            self.application.installTranslator(project)
            self._project_translator = project
        if spec.qt_qm:
            qt = QTranslator(self)
            qt_path = Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)) / spec.qt_qm
            if qt.load(str(qt_path)):
                self.application.installTranslator(qt)
                self._qt_translator = qt
        return code

    def _remove_translators(self) -> None:
        for translator in (self._project_translator, self._qt_translator):
            if translator is not None:
                self.application.removeTranslator(translator)
                translator.deleteLater()
        self._project_translator = None
        self._qt_translator = None

    def _apply_ui_font(self) -> None:
        preferred = ("Microsoft YaHei UI", "Microsoft YaHei") if self.current_code.startswith("zh") else ("Segoe UI",)
        families = set(QFontDatabase.families())
        family = next((name for name in preferred if name in families), self.application.font().family())
        font = QFont(family)
        font.setPointSize(10)
        self.application.setFont(font)
