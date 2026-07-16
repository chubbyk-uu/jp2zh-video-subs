import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QListWidget

from jp2zh_gui.models import CleanupPolicy
from jp2zh_gui.window import MainWindow


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
        assert window.asr_batch_spin.value() > 0
        assert not window.advanced_dialog.isVisible()
        assert window.colour_buttons["zh"].text().startswith("#")
        assert window.bilingual_check.isChecked()
        assert window.copy_check.isChecked()
        assert not window.recursive_check.isChecked()
        assert not window.resume_check.isChecked()
    finally:
        window.close()


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
