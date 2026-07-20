import os
import string
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QMessageBox

from jp2zh_gui.i18n import LanguageManager, load_language_specs, resolve_language_code
from jp2zh_gui.models import AsrPreset, GuiTask, TaskStatus
import jp2zh_gui.window as window_module
from jp2zh_gui.window import MainWindow


def application():
    return QApplication.instance() or QApplication([])


def settings_at(tmp_path: Path) -> QSettings:
    return QSettings(str(tmp_path / "i18n.ini"), QSettings.Format.IniFormat)


def test_locale_resolution_and_unsupported_fallback():
    specs = load_language_specs()
    assert resolve_language_code("system", "zh-CN", specs) == "zh_CN"
    assert resolve_language_code("system", "zh_Hant", specs) == "zh_TW"
    assert resolve_language_code("system", "zh_HK.UTF-8", specs) == "zh_TW"
    assert resolve_language_code("system", "fr_FR", specs) == "en"
    assert resolve_language_code("en", "zh_CN", specs) == "en"


def test_language_manager_persists_choice_and_missing_catalog_falls_back(tmp_path):
    app = application()
    settings = settings_at(tmp_path)
    manager = LanguageManager(app, settings, system_locale="en_US")
    assert manager.start() == "en"
    assert manager.set_language("zh_CN") == "zh_CN"
    assert settings.value("ui_language") == "zh_CN"

    broken_manifest = tmp_path / "translations" / "languages.json"
    broken_manifest.parent.mkdir()
    broken_manifest.write_text(
        '{"languages":['
        '{"code":"system","name":"System","aliases":[],"qm":null,"qt_qm":null},'
        '{"code":"zh_CN","name":"简体中文","aliases":[],"qm":"missing.qm","qt_qm":null},'
        '{"code":"zh_TW","name":"繁體中文","aliases":[],"qm":"missing-tw.qm","qt_qm":null},'
        '{"code":"en","name":"English","aliases":[],"qm":null,"qt_qm":null}'
        ']}',
        encoding="utf-8",
    )
    fallback = LanguageManager(app, settings, manifest_path=broken_manifest, system_locale="zh_CN")
    assert fallback.set_language("zh_CN", persist=False) == "en"


def test_runtime_language_switch_preserves_values_and_rerenders_tasks(tmp_path):
    app = application()
    settings = settings_at(tmp_path)
    settings.setValue("ui_language", "zh_CN")
    manager = LanguageManager(app, settings, system_locale="zh_CN")
    manager.start()
    window = MainWindow(settings=settings, language_manager=manager)
    task = GuiTask(
        tmp_path / "sample.mp4",
        status=TaskStatus.RUNNING,
        stage="asr",
        detail_key="anime_recognising",
        detail_args={"current": 5, "total": 12},
        stage_progress=0.5,
    )
    window.tasks.append(task)
    window._append_task_row(task)
    window.asr_combo.setCurrentIndex(window.asr_combo.findData(AsrPreset.QWEN.value))
    try:
        assert window.windowTitle() == "日语视频中文字幕工具"
        assert "正在进行 Anime 识别" in window.task_table.item(0, 1).text()

        manager.set_language("en")
        app.processEvents()
        assert window.windowTitle() == "Japanese Video Subtitle Tool"
        assert "Running Anime recognition" in window.task_table.item(0, 1).text()
        assert window.asr_combo.currentData() == AsrPreset.QWEN.value
        assert task.detail_args == {"current": 5, "total": 12}

        manager.set_language("zh_TW")
        app.processEvents()
        assert window.windowTitle() == "日文影片中文字幕工具"
        assert window.language_actions["zh_TW"].isChecked()
    finally:
        window.close()


def test_english_main_window_fits_key_labels_at_1280_width(tmp_path):
    app = application()
    settings = settings_at(tmp_path)
    settings.setValue("ui_language", "en")
    manager = LanguageManager(app, settings, system_locale="en_US")
    manager.start()
    window = MainWindow(settings=settings, language_manager=manager)
    try:
        window.resize(1280, 720)
        window.show()
        app.processEvents()
        assert window.minimumSize().toTuple() == (1280, 720)
        assert window.minimumSizeHint().width() <= 1280
        assert window.settings_group.height() == window.settings_group.sizeHint().height()
        assert window.common_group.height() == window.common_group.sizeHint().height()
        assert window.refresh_device_button.sizeHint().width() <= window.refresh_device_button.width()
        assert window.asr_combo.sizeHint().width() <= window.asr_combo.width()
        assert window.target_language_combo.sizeHint().width() <= window.target_language_combo.width()
        assert window.translator_combo.sizeHint().width() <= window.translator_combo.width()
        assert window.asr_label.geometry().top() == window.target_language_label.geometry().top()
        assert window.target_language_label.geometry().top() == window.translator_label.geometry().top()
        assert window.asr_combo.geometry().top() == window.target_language_combo.geometry().top()
        assert window.target_language_combo.geometry().top() == window.translator_combo.geometry().top()
        for widget in (window.recursive_check, window.resume_check, window.copy_check, window.speaker_check):
            assert widget.sizeHint().width() <= widget.width(), widget.text()
        assert window.batch_note.sizeHint().width() <= window.batch_note.width()
        assert {
            widget.height()
            for widget in (
                window.output_edit,
                window.output_browse,
                window.work_edit,
                window.work_browse,
                window.cleanup_combo,
            )
        } == {32}
    finally:
        window.close()


def test_restore_defaults_keeps_settings_controls_aligned(tmp_path, monkeypatch):
    app = application()
    settings = settings_at(tmp_path)
    settings.setValue("ui_language", "en")
    manager = LanguageManager(app, settings, system_locale="zh_CN")
    manager.start()
    window = MainWindow(settings=settings, language_manager=manager)
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args: QMessageBox.StandardButton.Yes,
    )
    try:
        window.resize(1280, 720)
        window.show()
        app.processEvents()

        window._restore_all_defaults()
        app.processEvents()

        assert manager.current_code == "zh_CN"
        control_x = {
            widget.mapTo(window.settings_group, widget.rect().topLeft()).x()
            for widget in (window.output_edit, window.work_edit, window.cleanup_combo)
        }
        assert len(control_x) == 1
        assert window.asr_combo.geometry().top() == window.target_language_combo.geometry().top()
        assert window.target_language_combo.geometry().top() == window.translator_combo.geometry().top()
        for label in (window.output_label, window.work_label, window.cleanup_label):
            assert label.contentsMargins().top() == 2
        control_heights = {
            widget.height()
            for widget in (window.output_edit, window.work_edit, window.cleanup_combo)
        }
        assert control_heights == {32}
    finally:
        window.close()


def test_model_status_is_retranslated_for_complete_and_missing_models(tmp_path, monkeypatch):
    app = application()
    settings = settings_at(tmp_path)
    settings.setValue("ui_language", "zh_CN")
    manager = LanguageManager(app, settings, system_locale="zh_CN")
    manager.start()
    state = {"missing": False}
    monkeypatch.setattr(
        window_module,
        "missing_model_files",
        lambda _config: [tmp_path / "one", tmp_path / "two"] if state["missing"] else [],
    )
    window = MainWindow(settings=settings, language_manager=manager)
    try:
        assert window.model_status_label.text() == "所选模型文件完整"
        manager.set_language("zh_TW")
        app.processEvents()
        assert window.model_status_label.text() == "所選模型檔案完整"
        manager.set_language("en")
        app.processEvents()
        assert window.model_status_label.text() == "Selected model files are complete"

        state["missing"] = True
        manager.set_language("zh_CN")
        app.processEvents()
        assert window.model_status_label.text() == "缺少 2 个模型文件"
        manager.set_language("zh_TW")
        app.processEvents()
        assert window.model_status_label.text() == "缺少 2 個模型檔案"
        manager.set_language("en")
        app.processEvents()
        assert window.model_status_label.text() == "2 model files missing"
    finally:
        window.close()


def test_english_advanced_wrap_control_fits_dialog(tmp_path):
    app = application()
    settings = settings_at(tmp_path)
    settings.setValue("ui_language", "en")
    manager = LanguageManager(app, settings, system_locale="en_US")
    manager.start()
    window = MainWindow(settings=settings, language_manager=manager)
    dialog = window.advanced_dialog
    try:
        dialog.tabs.setCurrentIndex(1)
        dialog.show()
        app.processEvents()
        dialog.resize(560, 440)
        app.processEvents()
        assert dialog.wrap_check.text() == "Wrap long subtitles"
        assert dialog.wrap_check.sizeHint().width() <= dialog.wrap_check.width()
        spin_right = dialog.wrap_spin.mapTo(dialog, dialog.wrap_spin.rect().bottomRight()).x()
        assert spin_right <= dialog.contentsRect().right()
        assert dialog.minimumWidth() == 560
        assert dialog.width() == 560
    finally:
        window.close()


def test_catalogs_are_complete_and_preserve_format_placeholders():
    translations = Path(__file__).resolve().parents[1] / "scripts" / "jp2zh_gui" / "translations"
    formatter = string.Formatter()
    for path in (translations / "jp2zh_zh_CN.ts", translations / "jp2zh_zh_TW.ts"):
        tree = ET.parse(path)
        for message in tree.findall(".//message"):
            source = message.findtext("source") or ""
            translation = message.find("translation")
            assert translation is not None
            assert translation.get("type") != "unfinished"
            translated_text = translation.text or ""
            source_fields = {name for _, name, _, _ in formatter.parse(source) if name}
            translated_fields = {name for _, name, _, _ in formatter.parse(translated_text) if name}
            assert translated_fields == source_fields, source
