import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QProcess, QSettings, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication, QComboBox, QDialog, QFileDialog, QListWidget, QMessageBox

from jp2zh_gui.models import CleanupPolicy, GuiConfig, GuiTask, TargetLanguage, TaskStatus, TranslatorPreset
import jp2zh_gui.window as window_module
from jp2zh_gui.window import MainWindow, format_device_status


def application():
    return QApplication.instance() or QApplication([])


def window_settings(tmp_path):
    settings = QSettings(str(tmp_path / "gui-test.ini"), QSettings.Format.IniFormat)
    if not settings.contains("ui_language"):
        settings.setValue("ui_language", "zh_CN")
    return settings


def test_main_window_has_model_and_cleanup_choices(tmp_path):
    application()
    window = MainWindow(settings=window_settings(tmp_path))
    try:
        assert window.asr_combo.count() == 2
        assert window.translator_combo.count() == 2
        assert window.target_language_combo.count() == 3
        assert window.cleanup_combo.count() == 3
        assert window.cleanup_combo.findData(CleanupPolicy.FINAL_ONLY.value) >= 0
        assert window.minimumSize().toTuple() == (1280, 720)
        assert window.size().toTuple() == (1280, 720)
        assert window.asr_batch_combo.currentData() == 24
        assert [window.asr_batch_combo.itemData(i) for i in range(4)] == [24, 16, 8, 4]
        assert not window.advanced_dialog.isVisible()
        assert window.colour_buttons["zh"].text().startswith("#")
        assert window.bilingual_check.isChecked()
        assert window.copy_check.isChecked()
        assert not window.recursive_check.isChecked()
        assert not window.resume_check.isChecked()
        assert window.log_toggle.isChecked()
        assert window.probe_on_startup_action.isChecked()
        assert not window.open_output_on_finish_action.isChecked()
        assert not window.guidance_group.isHidden()
        assert window.guidance_label.alignment() & window_module.Qt.AlignmentFlag.AlignVCenter
        assert window.log_edit.maximumHeight() > 130
    finally:
        window.close()


def test_extra_window_height_defaults_to_log_and_splitter_remains_adjustable(tmp_path):
    app = application()
    window = MainWindow(settings=window_settings(tmp_path))
    try:
        window.resize(1280, 720)
        window.show()
        app.processEvents()
        default_content_height = window.content_panel.height()
        default_log_height = window.log_edit.height()

        window.resize(1280, 900)
        app.processEvents()
        grown_log_height = window.log_edit.height()
        assert abs(window.content_panel.height() - default_content_height) <= 1
        assert grown_log_height > default_log_height

        window.log_splitter.setSizes([window.log_splitter.height(), default_log_height])
        app.processEvents()
        assert window.content_panel.height() > default_content_height
        assert window.log_edit.height() < grown_log_height

        window.log_splitter.setSizes([0, window.log_splitter.height()])
        app.processEvents()
        assert window.content_panel.height() >= default_content_height
        assert window.log_splitter.handleWidth() == 10
        assert window.log_splitter_handle.cursor().shape() == window_module.Qt.CursorShape.SizeVerCursor
        assert window.log_splitter_handle.toolTip() == "拖动调整日志高度"
    finally:
        window.close()


def test_log_panel_can_be_hidden_and_setting_is_restored(tmp_path):
    app = application()
    settings = window_settings(tmp_path)
    first = MainWindow(settings=settings)
    try:
        first.show()
        first.log_toggle.setChecked(False)
        app.processEvents()
        assert not first.log_edit.isVisible()
        first._save_settings()
        settings.sync()
    finally:
        first.close()

    second = MainWindow(settings=settings)
    try:
        second.show()
        app.processEvents()
        assert not second.log_toggle.isChecked()
        assert not second.log_edit.isVisible()
    finally:
        second.close()


def test_main_window_add_paths_expands_folder_and_deduplicates(tmp_path):
    application()
    first = tmp_path / "first.mp4"
    nested_dir = tmp_path / "nested"
    nested_dir.mkdir()
    second = nested_dir / "second.mkv"
    first.touch()
    second.touch()
    window = MainWindow(settings=window_settings(tmp_path))
    try:
        window.recursive_check.setChecked(True)
        assert window.add_paths([tmp_path, first]) == 2
        assert window.add_paths([first]) == 0
        assert window.task_table.rowCount() == 2
        assert {task.video for task in window.tasks} == {first.resolve(), second.resolve()}
    finally:
        window.close()


def test_native_model_combos_keep_target_language_enabled(tmp_path):
    application()
    window = MainWindow(settings=window_settings(tmp_path))
    try:
        assert type(window.asr_combo) is QComboBox
        assert type(window.target_language_combo) is QComboBox
        assert type(window.translator_combo) is QComboBox
        for _ in range(3):
            window.asr_combo.setCurrentIndex(1 - window.asr_combo.currentIndex())
            window.target_language_combo.setCurrentIndex(
                window.target_language_combo.findData(TargetLanguage.ENGLISH.value)
            )
            assert window.target_language_combo.isEnabled()
            assert not window.translator_combo.isEnabled()
            window.target_language_combo.setCurrentIndex(
                window.target_language_combo.findData(TargetLanguage.SIMPLIFIED_CHINESE.value)
            )
            assert window.target_language_combo.isEnabled()
            assert window.translator_combo.isEnabled()
    finally:
        window.close()


def test_advanced_wrap_can_be_disabled(tmp_path):
    application()
    window = MainWindow(settings=window_settings(tmp_path))
    try:
        window.advanced_dialog.wrap_check.setChecked(False)
        assert window._config_from_ui().display_wrap_max_chars == 0
        window.advanced_dialog.wrap_check.setChecked(True)
        window.wrap_spin.setValue(20)
        assert window._config_from_ui().display_wrap_max_chars == 20
    finally:
        window.close()


def test_translation_batch_is_disabled_for_sakura(tmp_path):
    application()
    window = MainWindow(settings=window_settings(tmp_path))
    try:
        assert window.translator_combo.currentData() == TranslatorPreset.GALTRANSL.value
        assert window.batch_spin.isEnabled()
        assert window.advanced_dialog.batch_label.text() == "翻译批大小"

        window.translator_combo.setCurrentIndex(
            window.translator_combo.findData(TranslatorPreset.SAKURA.value)
        )
        assert not window.batch_spin.isEnabled()
        assert not window.advanced_dialog.batch_label.isEnabled()

        window.translator_combo.setCurrentIndex(
            window.translator_combo.findData(TranslatorPreset.GALTRANSL.value)
        )
        assert window.batch_spin.isEnabled()
        assert window.advanced_dialog.batch_label.isEnabled()
    finally:
        window.close()


def test_target_language_switches_translator_and_restores_chinese_choice(tmp_path):
    application()
    window = MainWindow(settings=window_settings(tmp_path))
    try:
        window.translator_combo.setCurrentIndex(window.translator_combo.findData(TranslatorPreset.SAKURA.value))
        window.batch_spin.setValue(7)
        window.wrap_spin.setValue(18)
        window.target_language_combo.setCurrentIndex(
            window.target_language_combo.findData(TargetLanguage.ENGLISH.value)
        )
        assert window.translator_combo.currentData() == TranslatorPreset.SUGOI.value
        assert not window.translator_combo.isEnabled()
        assert window.batch_spin.value() == 10
        assert window.wrap_spin.value() == 60
        assert window.font_combo.currentFont().family() != "Microsoft YaHei"
        assert window.ja_font_combo.currentFont().family() == "Microsoft YaHei"
        assert not window.context_spin.isEnabled()

        window.target_language_combo.setCurrentIndex(
            window.target_language_combo.findData(TargetLanguage.TRADITIONAL_CHINESE.value)
        )
        assert window.translator_combo.currentData() == TranslatorPreset.SAKURA.value
        assert window.translator_combo.isEnabled()
        assert window.batch_spin.value() == 7
        assert window.wrap_spin.value() == 18
        assert window.font_combo.currentFont().family() == "Microsoft YaHei"
        assert window.context_spin.isEnabled()
    finally:
        window.close()


def test_english_target_persists_and_keeps_last_chinese_translator(tmp_path):
    application()
    settings = window_settings(tmp_path)
    first = MainWindow(settings=settings)
    try:
        first.translator_combo.setCurrentIndex(first.translator_combo.findData(TranslatorPreset.SAKURA.value))
        first.batch_spin.setValue(7)
        first.wrap_spin.setValue(18)
        first.target_language_combo.setCurrentIndex(
            first.target_language_combo.findData(TargetLanguage.ENGLISH.value)
        )
        first.batch_spin.setValue(9)
        first.wrap_spin.setValue(40)
        first._save_settings()
        settings.sync()
    finally:
        first.close()

    second = MainWindow(settings=settings)
    try:
        assert second.target_language_combo.currentData() == TargetLanguage.ENGLISH.value
        assert second.translator_combo.currentData() == TranslatorPreset.SUGOI.value
        second.target_language_combo.setCurrentIndex(
            second.target_language_combo.findData(TargetLanguage.SIMPLIFIED_CHINESE.value)
        )
        assert second.translator_combo.currentData() == TranslatorPreset.SAKURA.value
        assert second.batch_spin.value() == 7
        assert second.wrap_spin.value() == 18
        second.target_language_combo.setCurrentIndex(
            second.target_language_combo.findData(TargetLanguage.ENGLISH.value)
        )
        assert second.batch_spin.value() == 9
        assert second.wrap_spin.value() == 40
    finally:
        second.close()


def test_restore_defaults_uses_target_language_translation_defaults(tmp_path):
    application()
    window = MainWindow(settings=window_settings(tmp_path))
    try:
        window.target_language_combo.setCurrentIndex(
            window.target_language_combo.findData(TargetLanguage.ENGLISH.value)
        )
        window.batch_spin.setValue(4)
        window.wrap_spin.setValue(24)
        window.advanced_dialog.restore_defaults()
        assert window.batch_spin.value() == 10
        assert window.wrap_spin.value() == 60
        assert window.font_combo.currentFont().family() != "Microsoft YaHei"

        window.target_language_combo.setCurrentIndex(
            window.target_language_combo.findData(TargetLanguage.SIMPLIFIED_CHINESE.value)
        )
        window.advanced_dialog.restore_defaults()
        assert window.batch_spin.value() == GuiConfig().translate_batch_size
        assert window.wrap_spin.value() == GuiConfig().display_wrap_max_chars
    finally:
        window.close()


def test_font_combo_menu_selects_and_destroys_popup(tmp_path):
    app = application()
    window = MainWindow(settings=window_settings(tmp_path))
    try:
        combo = window.font_combo
        combo.showPopup()
        menu = combo._popup_menu
        assert menu is not None
        picker = menu.findChild(QListWidget)
        assert picker is not None
        target = picker.item(1 if picker.count() > 1 else 0)
        target_family = target.text()
        picker.itemClicked.emit(target)
        app.processEvents()
        assert combo._popup_menu is None
        assert combo.currentFont().family().casefold() == target_family.casefold()
    finally:
        window.close()


def test_device_refresh_keeps_focus_off_output_path(tmp_path):
    app = application()
    window = MainWindow(settings=window_settings(tmp_path))
    try:
        window.show()
        window._device_probe.waitForFinished(15000)
        app.processEvents()
        window.refresh_device_button.setFocus()
        window._start_device_probe()
        app.processEvents()
        assert window.refresh_device_button.hasFocus()
        assert not window.output_edit.hasFocus()
        assert window.refresh_device_button.text() == "检测中…"
    finally:
        window.close()


def test_device_status_does_not_report_cpu_when_whisperseg_model_is_missing():
    text, colour = format_device_status(
        {
            "torch_cuda": True,
            "onnx_cuda": False,
            "onnx_status": "missing_model",
            "llama_cuda": True,
            "gpu_name": "NVIDIA GeForce RTX 5080",
        }
    )

    assert "语音切分 未检测（缺少模型）" in text
    assert "语音切分 CPU" not in text
    assert colour == "#a56500"


def test_device_status_still_reports_cpu_after_a_real_cpu_probe():
    text, _colour = format_device_status(
        {
            "torch_cuda": True,
            "onnx_cuda": False,
            "onnx_status": "cpu",
            "llama_cuda": True,
            "gpu_name": "GPU",
        }
    )

    assert "语音切分 CPU" in text


def test_drop_event_adds_local_video_and_accepts_action(tmp_path):
    application()
    video = tmp_path / "拖放 测试.mp4"
    video.touch()

    class MimeData:
        @staticmethod
        def urls():
            return [QUrl.fromLocalFile(str(video))]

    class DropEvent:
        accepted = False

        @staticmethod
        def mimeData():
            return MimeData()

        def acceptProposedAction(self):
            self.accepted = True

    window = MainWindow(settings=window_settings(tmp_path))
    event = DropEvent()
    try:
        window.dropEvent(event)
        assert event.accepted
        assert [task.video for task in window.tasks] == [video.resolve()]
    finally:
        window.close()


def test_choose_files_uses_dialog_result_and_adds_video(tmp_path, monkeypatch):
    application()
    video = tmp_path / "dialog.mp4"
    video.touch()
    monkeypatch.setattr(QFileDialog, "getOpenFileNames", lambda *_args: ([str(video)], ""))
    window = MainWindow(settings=window_settings(tmp_path))
    try:
        window._choose_files()
        assert [task.video for task in window.tasks] == [video.resolve()]
    finally:
        window.close()


def test_saved_settings_restore_in_new_window(tmp_path):
    application()
    settings = window_settings(tmp_path)
    first = MainWindow(settings=settings)
    try:
        first._set_asr_batch_value(13)
        first.quality_check.setChecked(True)
        first.resume_check.setChecked(True)
        first.cleanup_combo.setCurrentIndex(first.cleanup_combo.findData(CleanupPolicy.FINAL_ONLY.value))
        first.context_spin.setValue(9)
        first.zh_size_spin.setValue(41)
        first.probe_on_startup_action.setChecked(False)
        first.open_output_on_finish_action.setChecked(True)
        first._save_settings()
        settings.sync()
    finally:
        first.close()

    second = MainWindow(settings=settings)
    try:
        assert second.asr_batch_combo.currentData() == 13
        assert second.quality_check.isChecked()
        assert second.resume_check.isChecked()
        assert second.cleanup_combo.currentData() == CleanupPolicy.FINAL_ONLY.value
        assert second.context_spin.value() == 9
        assert second.zh_size_spin.value() == 41
        assert not second.probe_on_startup_action.isChecked()
        assert second.open_output_on_finish_action.isChecked()
        assert second._device_probe.state() == QProcess.ProcessState.NotRunning
        assert "已关闭启动时自动检测" in second.device_status_label.text()
    finally:
        second.close()


def test_advanced_dialog_cancel_restores_snapshot(tmp_path, monkeypatch):
    application()
    window = MainWindow(settings=window_settings(tmp_path))
    original_context = window.context_spin.value()

    def reject_after_change():
        window.context_spin.setValue(original_context + 5)
        return QDialog.DialogCode.Rejected

    monkeypatch.setattr(window.advanced_dialog, "exec", reject_after_change)
    try:
        window._show_advanced_settings()
        assert window.context_spin.value() == original_context
    finally:
        window.close()


def test_missing_model_files_blocks_start_and_shows_paths(tmp_path, monkeypatch):
    application()
    video = tmp_path / "input.mp4"
    video.touch()
    missing = tmp_path / "models" / "missing.gguf"
    shown: list[tuple[str, str]] = []
    monkeypatch.setattr(window_module, "missing_model_files", lambda _config: [missing])
    monkeypatch.setattr(QMessageBox, "warning", lambda _parent, title, text: shown.append((title, text)))
    window = MainWindow(settings=window_settings(tmp_path))
    window.add_paths([video])
    started = False

    def record_start(*_args):
        nonlocal started
        started = True

    monkeypatch.setattr(window.controller, "start", record_start)
    try:
        window._start()
        assert not started
        assert shown == [("模型不完整", f"所选模型缺少文件：\n{missing}")]
    finally:
        window.close()


def test_settings_actions_open_config_and_local_guide(tmp_path, monkeypatch):
    application()
    opened: list[QUrl] = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: opened.append(url) or True)
    settings = window_settings(tmp_path)
    window = MainWindow(settings=settings)
    try:
        window._open_config_folder()
        assert Path(opened[-1].toLocalFile()) == Path(settings.fileName()).resolve().parent
        window._open_user_guide()
        assert Path(opened[-1].toLocalFile()).name == "README-CN.md"
    finally:
        window.close()


def test_top_directory_buttons_open_configured_folders(tmp_path, monkeypatch):
    application()
    opened: list[QUrl] = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: opened.append(url) or True)
    window = MainWindow(settings=window_settings(tmp_path))
    try:
        output_dir = tmp_path / "output"
        work_dir = tmp_path / "work"
        window.output_edit.setText(str(output_dir))
        window.work_edit.setText(str(work_dir))
        window.open_work_button.click()
        window.open_output_button.click()
        assert [Path(url.toLocalFile()) for url in opened] == [work_dir.resolve(), output_dir.resolve()]
        assert window.menuBar().cornerWidget(Qt.Corner.TopRightCorner) is window.top_actions
    finally:
        window.close()


def test_queue_finish_can_open_output_folder(tmp_path, monkeypatch):
    application()
    window = MainWindow(settings=window_settings(tmp_path))
    opened = []
    monkeypatch.setattr(window, "_open_output", lambda: opened.append(True))
    try:
        window.open_output_on_finish_action.setChecked(True)
        window._queue_finished()
        assert opened == [True]
    finally:
        window.close()


def test_restore_all_defaults_resets_settings_and_language(tmp_path, monkeypatch):
    app = application()
    settings = window_settings(tmp_path)
    window = MainWindow(settings=settings)
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args: QMessageBox.StandardButton.Yes,
    )
    try:
        window.output_edit.setText(str(tmp_path / "custom-output"))
        window.quality_check.setChecked(True)
        window.probe_on_startup_action.setChecked(False)
        window.open_output_on_finish_action.setChecked(True)
        window.language_manager.set_language("en")
        window.show()
        window.resize(1440, 900)
        app.processEvents()
        window.log_splitter.setSizes([window.content_panel.minimumHeight(), window.log_splitter.height()])
        window.log_toggle.setChecked(False)
        window._save_settings()

        window._restore_all_defaults()
        app.processEvents()

        assert window.output_edit.text() == str(window_module.GuiConfig().output_dir)
        assert not window.quality_check.isChecked()
        assert window.probe_on_startup_action.isChecked()
        assert not window.open_output_on_finish_action.isChecked()
        assert window.language_manager.requested_code == "system"
        assert settings.value("ui_language") == "system"
        assert window.size().toTuple() == (1280, 720)
        assert window.log_toggle.isChecked()
        assert window.log_edit.isVisible()
        assert abs(window.log_edit.height() - window.DEFAULT_LOG_HEIGHT) <= 1
    finally:
        window.close()
