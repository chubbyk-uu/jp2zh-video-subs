import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QSettings, QUrl
from PySide6.QtWidgets import QApplication, QDialog, QFileDialog, QListWidget, QMessageBox

from jp2zh_gui.models import CleanupPolicy, GuiTask, TaskStatus
import jp2zh_gui.window as window_module
from jp2zh_gui.window import MainWindow, format_device_status


def application():
    return QApplication.instance() or QApplication([])


def window_settings(tmp_path):
    return QSettings(str(tmp_path / "gui-test.ini"), QSettings.Format.IniFormat)


def test_main_window_has_model_and_cleanup_choices(tmp_path):
    application()
    window = MainWindow(settings=window_settings(tmp_path))
    try:
        assert window.asr_combo.count() == 2
        assert window.translator_combo.count() == 2
        assert window.cleanup_combo.count() == 3
        assert window.cleanup_combo.findData(CleanupPolicy.FINAL_ONLY.value) >= 0
        assert window.width() >= 1120
        assert window.asr_batch_combo.currentData() == 24
        assert [window.asr_batch_combo.itemData(i) for i in range(4)] == [24, 16, 8, 4]
        assert not window.advanced_dialog.isVisible()
        assert window.colour_buttons["zh"].text().startswith("#")
        assert window.bilingual_check.isChecked()
        assert window.copy_check.isChecked()
        assert not window.recursive_check.isChecked()
        assert not window.resume_check.isChecked()
        assert window.log_toggle.isChecked()
        assert not window.guidance_group.isHidden()
        assert window.guidance_label.alignment() & window_module.Qt.AlignmentFlag.AlignVCenter
        assert window.log_edit.maximumHeight() == 130
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


def test_auto_close_combo_hides_popup_after_activation(tmp_path):
    app = application()
    window = MainWindow(settings=window_settings(tmp_path))
    try:
        window.show()
        window.asr_combo.showPopup()
        menu = window.asr_combo._popup_menu
        assert menu is not None
        menu.actions()[1].trigger()
        app.processEvents()
        assert window.asr_combo.currentIndex() == 1
        assert window.asr_combo._popup_menu is None
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


def test_retry_failed_and_cancelled_tasks_resets_only_those_tasks(tmp_path):
    application()
    window = MainWindow(settings=window_settings(tmp_path))
    failed = GuiTask(Path("failed.mp4"), status=TaskStatus.FAILED, error="test failure")
    cancelled = GuiTask(Path("cancelled.mp4"), status=TaskStatus.CANCELLED)
    completed = GuiTask(Path("completed.mp4"), status=TaskStatus.COMPLETED)
    window.tasks = [failed, cancelled, completed]
    for task in window.tasks:
        window._append_task_row(task)
    try:
        window._retry_failed()
        assert failed.status == TaskStatus.WAITING
        assert failed.error == ""
        assert cancelled.status == TaskStatus.WAITING
        assert completed.status == TaskStatus.COMPLETED
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
