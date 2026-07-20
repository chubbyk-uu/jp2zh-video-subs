"""PySide6 main window for batch subtitle generation."""
from __future__ import annotations

from pathlib import Path

import json
import sys

from PySide6.QtCore import QCoreApplication, QPoint, QProcess, QSettings, Qt, QUrl
from PySide6.QtGui import QAction, QActionGroup, QColor, QCloseEvent, QDesktopServices, QDragEnterEvent, QDropEvent, QFont, QGuiApplication, QPainter
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QColorDialog,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFontComboBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QMenu,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QSplitterHandle,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from portable_runtime import portable_config_path, rebase_portable_path
from target_languages import DEFAULT_BATCH_SIZE_BY_TRANSLATOR, DEFAULT_WRAP_CHARS_BY_TARGET
from .controller import PipelineController
from .i18n import LanguageManager
from .models import (
    AsrPreset,
    CleanupPolicy,
    GuiConfig,
    GuiTask,
    PROJECT_ROOT,
    TaskStatus,
    TranslatorPreset,
    TargetLanguage,
    discover_dropped_videos,
    missing_model_files,
)
from .process_utils import hide_windows_console


def format_device_status(data: dict[str, object]) -> tuple[str, str]:
    torch_cuda = bool(data.get("torch_cuda"))
    onnx_cuda = bool(data.get("onnx_cuda"))
    llama_cuda = bool(data.get("llama_cuda"))
    onnx_status = str(data.get("onnx_status") or ("cuda" if onnx_cuda else "cpu"))
    vad_label = {
        "cuda": "✓",
        "cpu": "CPU",
        "missing_model": QCoreApplication.translate("DeviceStatus", "Not detected (model missing)"),
        "unavailable": QCoreApplication.translate("DeviceStatus", "Probe failed"),
    }.get(onnx_status, QCoreApplication.translate("DeviceStatus", "Unknown"))
    parts = [
        f"ASR {'✓' if torch_cuda else '✗'}",
        QCoreApplication.translate("DeviceStatus", "VAD {state}").format(state=vad_label),
        QCoreApplication.translate("DeviceStatus", "Translation {state}").format(state="✓" if llama_cuda else "CPU"),
    ]
    gpu_name = str(data.get("gpu_name") or "CUDA GPU")
    display_gpu_name = gpu_name.removeprefix("NVIDIA GeForce ")
    if torch_cuda and onnx_cuda and llama_cuda:
        return QCoreApplication.translate("DeviceStatus", "Device: CUDA · {gpu} (ASR ✓ / VAD ✓ / Translation ✓)").format(gpu=display_gpu_name), "#18864b"
    if torch_cuda:
        return QCoreApplication.translate("DeviceStatus", "Device: partial CUDA · {gpu} ({parts})").format(gpu=display_gpu_name, parts=" / ".join(parts)), "#a56500"
    return QCoreApplication.translate("DeviceStatus", "Device: CUDA unavailable; ASR cannot start ({parts})").format(parts=" / ".join(parts)), "#c0392b"


class LogSplitterHandle(QSplitterHandle):
    """Visible grip for resizing the log panel."""

    def __init__(self, orientation: Qt.Orientation, parent: QSplitter) -> None:
        super().__init__(orientation, parent)
        self.setCursor(Qt.CursorShape.SizeVerCursor)

    def enterEvent(self, event) -> None:  # noqa: N802 - Qt virtual method
        super().enterEvent(event)
        self.update()

    def leaveEvent(self, event) -> None:  # noqa: N802 - Qt virtual method
        super().leaveEvent(event)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt virtual method
        del event
        painter = QPainter(self)
        hovered = self.underMouse()
        painter.fillRect(self.rect(), QColor("#dbeafe" if hovered else "#edf0f3"))
        painter.setPen(QColor("#2563a8" if hovered else "#7b8794"))
        centre_x = self.rect().center().x()
        centre_y = self.rect().center().y()
        for offset in (-3, 0, 3):
            painter.drawLine(centre_x - 18, centre_y + offset, centre_x + 18, centre_y + offset)


class LogSplitter(QSplitter):
    def createHandle(self) -> QSplitterHandle:  # noqa: N802 - Qt virtual method
        return LogSplitterHandle(self.orientation(), self)


class FontComboBox(QFontComboBox):
    """Scrollable font dropdown backed by a QMenu-owned list."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._popup_menu: QMenu | None = None

    def showPopup(self) -> None:
        if self._popup_menu is not None:
            self._popup_menu.close()
        menu = QMenu(self)
        picker = QListWidget(menu)
        picker.setMinimumWidth(max(self.width(), 320))
        picker.setMaximumHeight(360)
        current_family = self.currentFont().family()
        current_row = 0
        for index in range(self.count()):
            family = self.itemText(index)
            item = QListWidgetItem(family)
            item.setFont(QFont(family, 11))
            picker.addItem(item)
            if family.casefold() == current_family.casefold():
                current_row = index
        picker.setCurrentRow(current_row)
        picker.scrollToItem(picker.currentItem())
        picker.itemClicked.connect(lambda item: self._select_font(item.text()))
        action = QWidgetAction(menu)
        action.setDefaultWidget(picker)
        menu.addAction(action)
        menu.aboutToHide.connect(self._font_menu_hidden)
        self._popup_menu = menu
        menu.popup(self.mapToGlobal(QPoint(0, self.height())))

    def hidePopup(self) -> None:
        if self._popup_menu is not None:
            self._popup_menu.close()

    def _select_font(self, family: str) -> None:
        self.setCurrentFont(QFont(family))
        if self._popup_menu is not None:
            self._popup_menu.close()

    def _font_menu_hidden(self) -> None:
        menu = self._popup_menu
        self._popup_menu = None
        if menu is not None:
            menu.deleteLater()


class AdvancedSettingsDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.target_language = TargetLanguage.SIMPLIFIED_CHINESE
        self.setMinimumSize(560, 480)
        self.resize(640, 480)
        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        self.tabs = tabs

        translation_tab = QWidget()
        translation_form = QFormLayout(translation_tab)
        translation_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.context_spin = QSpinBox()
        self.context_spin.setRange(0, 64)
        self.batch_spin = QSpinBox()
        self.batch_spin.setRange(0, 64)
        self.context_label = QLabel()
        self.batch_label = QLabel()
        self.translation_note = QLabel()
        translation_form.addRow(self.context_label, self.context_spin)
        translation_form.addRow(self.batch_label, self.batch_spin)
        translation_form.addRow(self.translation_note)
        tabs.addTab(translation_tab, "")

        style_tab = QWidget()
        style_form = QFormLayout(style_tab)
        style_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.wrap_check = QCheckBox()
        self.wrap_spin = QSpinBox()
        self.wrap_spin.setRange(1, 200)
        self.wrap_check.toggled.connect(self.wrap_spin.setEnabled)
        self.wrap_limit_label = QLabel()
        style_form.addRow(self.wrap_check)
        style_form.addRow(self.wrap_limit_label, self.wrap_spin)
        self.font_combo = FontComboBox()
        self.font_combo.setMaxVisibleItems(18)
        self.font_label = QLabel()
        style_form.addRow(self.font_label, self.font_combo)
        self.ja_font_combo = FontComboBox()
        self.ja_font_combo.setMaxVisibleItems(18)
        self.ja_font_label = QLabel()
        style_form.addRow(self.ja_font_label, self.ja_font_combo)
        self.zh_size_spin = QSpinBox()
        self.zh_size_spin.setRange(1, 200)
        self.ja_size_spin = QSpinBox()
        self.ja_size_spin.setRange(1, 200)
        self.zh_size_label = QLabel()
        self.ja_size_label = QLabel()
        style_form.addRow(self.zh_size_label, self.zh_size_spin)
        style_form.addRow(self.ja_size_label, self.ja_size_spin)

        self.colour_edits: dict[str, QLineEdit] = {}
        self.colour_buttons: dict[str, QPushButton] = {}
        self.colour_labels: dict[str, QLabel] = {}
        for key in ("zh", "ja", "male", "female"):
            edit = QLineEdit()
            edit.hide()
            button = QPushButton()
            button.setMinimumHeight(30)
            button.clicked.connect(lambda _checked=False, e=edit, b=button: self._choose_colour(e, b))
            self.colour_edits[key] = edit
            self.colour_buttons[key] = button
            label = QLabel()
            self.colour_labels[key] = label
            style_form.addRow(label, button)
        tabs.addTab(style_tab, "")
        layout.addWidget(tabs)

        self.restore_button = QPushButton()
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons = buttons
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        bottom = QHBoxLayout()
        bottom.addWidget(self.restore_button)
        bottom.addStretch()
        bottom.addWidget(buttons)
        layout.addLayout(bottom)
        self.restore_button.clicked.connect(self.restore_defaults)
        self.retranslate_ui()

    def retranslate_ui(self) -> None:
        self.setWindowTitle(self.tr("Advanced subtitle and translation settings"))
        self.context_spin.setToolTip(self.tr("Number of preceding lines supplied to the translation model; 0 translates each line independently."))
        self.batch_spin.setToolTip(self.tr("Maximum number of consecutive subtitles translated together; this is not GPU parallelism."))
        self.context_label.setText(self.tr("Translation context"))
        self.batch_label.setText(self.tr("Translation batch size"))
        self.translation_note.setText(self.tr("These settings affect translation context and grouping, not GPU parallelism."))
        self.tabs.setTabText(0, self.tr("Translation"))
        self.wrap_check.setText(self.tr("Wrap long subtitles"))
        self.wrap_check.setToolTip(self.tr("Wrap long Chinese text near punctuation and English text at a word boundary"))
        self.wrap_spin.setSuffix(self.tr(" chars"))
        self.wrap_spin.setToolTip(self.tr("Cue count and timing stay unchanged; English uses a separately evaluated default."))
        self.wrap_limit_label.setText(self.tr("Preferred line length"))
        self.font_label.setText(self.tr("Target subtitle font"))
        self.ja_font_label.setText(self.tr("Japanese subtitle font"))
        self.zh_size_label.setText(self.tr("Target font size"))
        self.ja_size_label.setText(self.tr("Japanese font size"))
        colour_names = {
            "zh": self.tr("Target colour"),
            "ja": self.tr("Japanese colour"),
            "male": self.tr("Male speaker colour"),
            "female": self.tr("Female speaker colour"),
        }
        for key, label in self.colour_labels.items():
            label.setText(colour_names[key])
            if self.colour_edits[key].text():
                self._refresh_colour_button(self.colour_edits[key], self.colour_buttons[key])
        self.tabs.setTabText(1, self.tr("Subtitle style"))
        self.restore_button.setText(self.tr("Restore defaults"))
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText(self.tr("OK"))
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(self.tr("Cancel"))

    def set_translator(self, translator: str) -> None:
        """Enable translator-specific controls without discarding saved values."""
        context_supported = translator != TranslatorPreset.SUGOI.value
        batch_supported = translator in (TranslatorPreset.GALTRANSL.value, TranslatorPreset.SUGOI.value)
        self.context_label.setEnabled(context_supported)
        self.context_spin.setEnabled(context_supported)
        self.batch_label.setEnabled(batch_supported)
        self.batch_spin.setEnabled(batch_supported)

    def set_target_language(self, target_language: TargetLanguage) -> None:
        self.target_language = target_language

    @staticmethod
    def _ass_colour_parts(value: str) -> tuple[int, int, int, str]:
        raw = value.removeprefix("&H").upper().zfill(8)
        return int(raw[6:8], 16), int(raw[4:6], 16), int(raw[2:4], 16), raw[:2]

    def _refresh_colour_button(self, edit: QLineEdit, button: QPushButton) -> None:
        red, green, blue, _alpha = self._ass_colour_parts(edit.text())
        rgb = f"#{red:02X}{green:02X}{blue:02X}"
        brightness = red * 299 + green * 587 + blue * 114
        foreground = "#000000" if brightness >= 128000 else "#ffffff"
        button.setText(rgb)
        button.setStyleSheet(f"background-color: {rgb}; color: {foreground};")
        button.setToolTip(self.tr("{value} (click to choose a colour)").format(value=edit.text()))

    def _choose_colour(self, edit: QLineEdit, button: QPushButton) -> None:
        red, green, blue, alpha = self._ass_colour_parts(edit.text())
        colour = QColorDialog.getColor(QColor(red, green, blue), self, self.tr("Choose subtitle colour"))
        if not colour.isValid():
            return
        edit.setText(f"&H{alpha}{colour.blue():02X}{colour.green():02X}{colour.red():02X}")
        self._refresh_colour_button(edit, button)

    def restore_defaults(self) -> None:
        defaults = GuiConfig()
        self.context_spin.setValue(defaults.context_size)
        english = self.target_language == TargetLanguage.ENGLISH
        self.batch_spin.setValue(
            DEFAULT_BATCH_SIZE_BY_TRANSLATOR["sugoi"] if english else defaults.translate_batch_size
        )
        self.wrap_check.setChecked(defaults.display_wrap_max_chars > 0)
        self.wrap_spin.setValue(
            DEFAULT_WRAP_CHARS_BY_TARGET[TargetLanguage.ENGLISH]
            if english
            else (defaults.display_wrap_max_chars or DEFAULT_WRAP_CHARS_BY_TARGET[TargetLanguage.SIMPLIFIED_CHINESE])
        )
        self.font_combo.setCurrentFont(QFont("Arial" if english else defaults.bilingual_font))
        self.ja_font_combo.setCurrentFont(QFont(defaults.bilingual_ja_font))
        self.zh_size_spin.setValue(defaults.bilingual_zh_font_size)
        self.ja_size_spin.setValue(defaults.bilingual_ja_font_size)
        for key, value in (
            ("zh", defaults.bilingual_zh_colour), ("ja", defaults.bilingual_ja_colour),
            ("male", defaults.bilingual_male_colour), ("female", defaults.bilingual_female_colour),
        ):
            self.colour_edits[key].setText(value)
            self._refresh_colour_button(self.colour_edits[key], self.colour_buttons[key])

    def snapshot(self) -> dict[str, object]:
        return {
            "context": self.context_spin.value(), "batch": self.batch_spin.value(),
            "wrap_enabled": self.wrap_check.isChecked(), "wrap": self.wrap_spin.value(),
            "font": self.font_combo.currentFont().family(),
            "ja_font": self.ja_font_combo.currentFont().family(), "zh_size": self.zh_size_spin.value(),
            "ja_size": self.ja_size_spin.value(),
            **{f"{key}_colour": edit.text() for key, edit in self.colour_edits.items()},
        }

    def restore_snapshot(self, values: dict[str, object]) -> None:
        self.context_spin.setValue(int(values["context"]))
        self.batch_spin.setValue(int(values["batch"]))
        self.wrap_check.setChecked(bool(values["wrap_enabled"]))
        self.wrap_spin.setValue(int(values["wrap"]))
        self.font_combo.setCurrentFont(QFont(str(values["font"])))
        self.ja_font_combo.setCurrentFont(QFont(str(values["ja_font"])))
        self.zh_size_spin.setValue(int(values["zh_size"]))
        self.ja_size_spin.setValue(int(values["ja_size"]))
        for key in self.colour_edits:
            self.colour_edits[key].setText(str(values[f"{key}_colour"]))
            self._refresh_colour_button(self.colour_edits[key], self.colour_buttons[key])


class MainWindow(QMainWindow):
    UI_SETTINGS_VERSION = 3
    DEFAULT_WINDOW_WIDTH = 1280
    DEFAULT_WINDOW_HEIGHT = 720
    DEFAULT_LOG_HEIGHT = 140

    def __init__(
        self,
        controller: PipelineController | None = None,
        settings: QSettings | None = None,
        language_manager: LanguageManager | None = None,
    ) -> None:
        super().__init__()
        self.controller = controller or PipelineController(self)
        self.tasks: list[GuiTask] = []
        self._rows_by_id: dict[str, int] = {}
        self.settings = settings or QSettings("jp2zh-video-subs", "jp2zh-video-subs")
        application = QApplication.instance()
        if application is None:
            raise RuntimeError("QApplication must be created before MainWindow")
        self.language_manager = language_manager or LanguageManager(application, self.settings)
        if language_manager is None:
            self.language_manager.start()
        self._close_when_finished = False
        self._device_probe = QProcess(self)
        self._last_device_data: dict[str, object] | None = None
        self._device_probe_state = "idle"
        self._log_splitter_initialised = False
        self._target_change_guard = False
        self._active_target = TargetLanguage.SIMPLIFIED_CHINESE
        self._last_chinese_translator = TranslatorPreset.GALTRANSL
        self._last_chinese_batch_size = DEFAULT_BATCH_SIZE_BY_TRANSLATOR["galtransl"]
        self._last_chinese_wrap = DEFAULT_WRAP_CHARS_BY_TARGET[TargetLanguage.SIMPLIFIED_CHINESE]
        self._last_chinese_font = "Microsoft YaHei"
        self._last_english_batch_size = DEFAULT_BATCH_SIZE_BY_TRANSLATOR["sugoi"]
        self._last_english_wrap = DEFAULT_WRAP_CHARS_BY_TARGET[TargetLanguage.ENGLISH]
        self._last_english_font = "Arial"
        hide_windows_console(self._device_probe)
        self.setMinimumSize(self.DEFAULT_WINDOW_WIDTH, self.DEFAULT_WINDOW_HEIGHT)
        self.resize(self.DEFAULT_WINDOW_WIDTH, self.DEFAULT_WINDOW_HEIGHT)
        self.setAcceptDrops(True)
        self._apply_visual_style()
        self._build_ui()
        self._connect_signals()
        self._restore_settings()
        self.retranslate_ui()
        self._update_model_status()
        if self.probe_on_startup_action.isChecked():
            self._start_device_probe()
        else:
            self._device_probe_state = "disabled"
            self._refresh_device_status_text()

    def _apply_visual_style(self) -> None:
        self.setStyleSheet("""
            QWidget { font-size: 10pt; }
            QLineEdit, QComboBox, QSpinBox { min-height: 30px; }
            QPushButton { min-height: 30px; padding: 2px 10px; }
            QPushButton#primaryButton {
                min-height: 32px; min-width: 112px; font-weight: 600;
                color: white; background: #2563a8; border: 1px solid #1f5797; border-radius: 3px;
            }
            QPushButton#primaryButton:hover { background: #2f74bd; }
            QPushButton#primaryButton:disabled { background: #9aabba; border-color: #8d9aa5; }
            QGroupBox { font-weight: 600; margin-top: 9px; }
            QGroupBox::title { subcontrol-origin: margin; left: 9px; padding: 0 4px; }
            QTableWidget { gridline-color: #d5d5d5; }
        """)

    def _build_ui(self) -> None:
        central = QWidget(self)
        outer = QVBoxLayout(central)

        input_group = QGroupBox()
        self.input_group = input_group
        input_layout = QVBoxLayout(input_group)
        self.task_table = QTableWidget(0, 4)
        self.task_table.horizontalHeader().setStretchLastSection(True)
        self.task_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.task_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.task_table.verticalHeader().setDefaultSectionSize(31)
        input_layout.addWidget(self.task_table)
        queue_buttons = QHBoxLayout()
        self.add_files_button = QPushButton()
        self.add_folder_button = QPushButton()
        self.remove_button = QPushButton()
        self.clear_button = QPushButton()
        for button in (self.add_files_button, self.add_folder_button, self.remove_button, self.clear_button):
            queue_buttons.addWidget(button)
        queue_buttons.addStretch()
        input_layout.addLayout(queue_buttons)

        settings_group = QGroupBox()
        self.settings_group = settings_group
        settings_group.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        settings_layout = QVBoxLayout(settings_group)
        settings_layout.setSpacing(5)
        model_layout = QGridLayout()
        self.model_layout = model_layout
        model_layout.setHorizontalSpacing(8)
        model_layout.setVerticalSpacing(2)
        self.asr_combo = QComboBox()
        self.asr_combo.setMinimumWidth(150)
        for preset in AsrPreset:
            self.asr_combo.addItem("", preset.value)
        self.translator_combo = QComboBox()
        self.translator_combo.setMinimumWidth(180)
        for preset in (TranslatorPreset.GALTRANSL, TranslatorPreset.SAKURA):
            self.translator_combo.addItem("", preset.value)
        self.target_language_combo = QComboBox()
        self.target_language_combo.setMinimumWidth(150)
        for language in TargetLanguage:
            self.target_language_combo.addItem("", language.value)
        self.cleanup_combo = QComboBox()
        for policy in CleanupPolicy:
            self.cleanup_combo.addItem("", policy.value)
        self.model_status_label = QLabel()
        self.device_status_label = QLabel()
        self.device_status_label.setWordWrap(False)
        self.device_status_label.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Preferred,
        )
        self.refresh_device_button = QPushButton()
        self.refresh_device_button.setMinimumWidth(90)
        self.output_edit = QLineEdit()
        self.output_browse = QPushButton()
        self.work_edit = QLineEdit()
        self.work_browse = QPushButton()
        self.asr_label = QLabel()
        self.translator_label = QLabel()
        self.target_language_label = QLabel()
        model_layout.addWidget(self.asr_label, 0, 0)
        model_layout.addWidget(self.target_language_label, 0, 1)
        model_layout.addWidget(self.translator_label, 0, 2)
        model_layout.addWidget(self.asr_combo, 1, 0)
        model_layout.addWidget(self.target_language_combo, 1, 1)
        model_layout.addWidget(self.translator_combo, 1, 2)
        model_layout.setColumnStretch(0, 3)
        model_layout.setColumnStretch(1, 3)
        model_layout.setColumnStretch(2, 4)
        settings_layout.addLayout(model_layout)
        status_row = QHBoxLayout()
        status_text = QVBoxLayout()
        status_text.setSpacing(2)
        status_text.addWidget(self.model_status_label)
        status_text.addWidget(self.device_status_label)
        status_row.addLayout(status_text, 1)
        status_row.addWidget(self.refresh_device_button)
        settings_layout.addLayout(status_row)
        path_layout = QGridLayout()
        self.path_layout = path_layout
        path_layout.setHorizontalSpacing(8)
        path_layout.setVerticalSpacing(1)
        self.output_label = QLabel()
        self.work_label = QLabel()
        self.cleanup_label = QLabel()
        for label in (self.output_label, self.work_label, self.cleanup_label):
            label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            label.setContentsMargins(0, 2, 0, 0)
        path_layout.addWidget(self.output_label, 0, 0)
        path_layout.addWidget(self.output_edit, 0, 1)
        path_layout.addWidget(self.output_browse, 0, 2)
        path_layout.addWidget(self.work_label, 1, 0)
        path_layout.addWidget(self.work_edit, 1, 1)
        path_layout.addWidget(self.work_browse, 1, 2)
        path_layout.addWidget(self.cleanup_label, 2, 0)
        path_layout.addWidget(self.cleanup_combo, 2, 1, 1, 2)
        path_layout.setColumnStretch(1, 1)
        settings_layout.addLayout(path_layout)

        common_group = QGroupBox()
        self.common_group = common_group
        common_group.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        common_layout = QGridLayout(common_group)
        common_layout.setContentsMargins(9, 7, 9, 7)
        common_layout.setVerticalSpacing(2)
        self.recursive_check = QCheckBox()
        self.bilingual_check = QCheckBox()
        self.quality_check = QCheckBox()
        self.resume_check = QCheckBox()
        self.copy_check = QCheckBox()
        self.speaker_check = QCheckBox()
        self.asr_batch_combo = QComboBox()
        self.asr_batch_combo.setMinimumWidth(260)
        self.asr_batch_combo.setMaximumWidth(275)
        for value in (24, 16, 8, 4):
            self.asr_batch_combo.addItem("", value)
        self.advanced_dialog = AdvancedSettingsDialog(self)
        self.context_spin = self.advanced_dialog.context_spin
        self.batch_spin = self.advanced_dialog.batch_spin
        self.wrap_spin = self.advanced_dialog.wrap_spin
        self.font_combo = self.advanced_dialog.font_combo
        self.ja_font_combo = self.advanced_dialog.ja_font_combo
        self.zh_size_spin = self.advanced_dialog.zh_size_spin
        self.ja_size_spin = self.advanced_dialog.ja_size_spin
        self.zh_colour_edit = self.advanced_dialog.colour_edits["zh"]
        self.ja_colour_edit = self.advanced_dialog.colour_edits["ja"]
        self.male_colour_edit = self.advanced_dialog.colour_edits["male"]
        self.female_colour_edit = self.advanced_dialog.colour_edits["female"]
        self.colour_buttons = self.advanced_dialog.colour_buttons
        common_layout.addWidget(self.recursive_check, 0, 0)
        common_layout.addWidget(self.bilingual_check, 0, 1)
        common_layout.addWidget(self.quality_check, 0, 2)
        common_layout.addWidget(self.resume_check, 1, 0)
        common_layout.addWidget(self.copy_check, 1, 1)
        common_layout.addWidget(self.speaker_check, 1, 2)
        performance_row = QHBoxLayout()
        self.asr_batch_label = QLabel()
        performance_row.addWidget(self.asr_batch_label)
        performance_row.addWidget(self.asr_batch_combo)
        self.batch_note = QLabel()
        self.batch_note.setStyleSheet("color: #666;")
        performance_row.addWidget(self.batch_note)
        performance_row.addStretch(1)
        common_layout.addLayout(performance_row, 2, 0, 1, 3)

        self.advanced_button = QPushButton()
        common_layout.addWidget(self.advanced_button, 3, 0, 1, 3)

        guidance_group = QGroupBox()
        self.guidance_group = guidance_group
        guidance_group.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        guidance_layout = QVBoxLayout(guidance_group)
        guidance_layout.setContentsMargins(9, 6, 9, 6)
        self.guidance_label = QLabel()
        self.guidance_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.guidance_label.setWordWrap(True)
        self.guidance_label.setStyleSheet("color: #666;")
        guidance_layout.addWidget(self.guidance_label, 1)

        settings_container = QWidget()
        settings_container_layout = QVBoxLayout(settings_container)
        settings_container_layout.setContentsMargins(0, 0, 0, 0)
        settings_container_layout.addWidget(settings_group)
        settings_container_layout.addWidget(common_group)
        settings_container_layout.addWidget(guidance_group, 1)

        content_splitter = QSplitter(Qt.Orientation.Horizontal)
        content_splitter.addWidget(input_group)
        content_splitter.addWidget(settings_container)
        content_splitter.setStretchFactor(0, 1)
        content_splitter.setStretchFactor(1, 1)
        content_splitter.setSizes([600, 650])

        progress_row = QHBoxLayout()
        self.current_label = QLabel()
        self.overall_progress = QProgressBar()
        self.overall_progress.setRange(0, 100)
        self.log_toggle = QCheckBox()
        self.log_toggle.setChecked(True)
        progress_row.addWidget(self.current_label)
        progress_row.addWidget(self.overall_progress, 1)
        progress_row.addWidget(self.log_toggle)

        content_panel = QWidget()
        self.content_panel = content_panel
        content_panel_layout = QVBoxLayout(content_panel)
        content_panel_layout.setContentsMargins(0, 0, 0, 0)
        content_panel_layout.addWidget(content_splitter, 1)
        content_panel_layout.addLayout(progress_row)

        self.log_edit = QPlainTextEdit()
        self.log_edit.setReadOnly(True)
        self.log_edit.setMaximumBlockCount(5000)
        self.log_edit.setMinimumHeight(100)

        log_splitter = LogSplitter(Qt.Orientation.Vertical)
        self.log_splitter = log_splitter
        log_splitter.setChildrenCollapsible(False)
        log_splitter.setHandleWidth(10)
        log_splitter.addWidget(content_panel)
        log_splitter.addWidget(self.log_edit)
        self.log_splitter_handle = log_splitter.handle(1)
        log_splitter.setStretchFactor(0, 0)
        log_splitter.setStretchFactor(1, 1)
        log_splitter.setSizes([500, self.DEFAULT_LOG_HEIGHT])
        outer.addWidget(log_splitter, 1)

        self.start_button = QPushButton()
        self.start_button.setObjectName("primaryButton")
        self.cancel_button = QPushButton()
        self.cancel_button.setEnabled(False)
        self.open_work_button = QPushButton()
        self.open_output_button = QPushButton()
        self.top_actions = QWidget()
        top_actions_layout = QHBoxLayout(self.top_actions)
        top_actions_layout.setContentsMargins(0, 1, 4, 1)
        top_actions_layout.setSpacing(6)
        for button in (self.start_button, self.cancel_button, self.open_work_button, self.open_output_button):
            top_actions_layout.addWidget(button)
        self.setCentralWidget(central)
        for control in (
            self.output_edit,
            self.output_browse,
            self.work_edit,
            self.work_browse,
            self.cleanup_combo,
        ):
            control.ensurePolished()
            control.setFixedHeight(32)
        self._build_language_menu()
        self.menuBar().setCornerWidget(self.top_actions, Qt.Corner.TopRightCorner)

    def _build_language_menu(self) -> None:
        self.settings_menu = self.menuBar().addMenu("")
        self.language_menu = self.settings_menu.addMenu("")
        self.language_actions: dict[str, QAction] = {}
        group = QActionGroup(self)
        group.setExclusive(True)
        for code in ("system", "zh_CN", "zh_TW", "en"):
            action = QAction(self)
            action.setCheckable(True)
            action.setData(code)
            action.triggered.connect(lambda _checked=False, value=code: self.language_manager.set_language(value))
            group.addAction(action)
            self.language_menu.addAction(action)
            self.language_actions[code] = action
        self.settings_menu.addSeparator()
        self.behaviour_menu = self.settings_menu.addMenu("")
        self.probe_on_startup_action = QAction(self)
        self.probe_on_startup_action.setCheckable(True)
        self.probe_on_startup_action.setChecked(True)
        self.open_output_on_finish_action = QAction(self)
        self.open_output_on_finish_action.setCheckable(True)
        self.behaviour_menu.addAction(self.probe_on_startup_action)
        self.behaviour_menu.addAction(self.open_output_on_finish_action)
        self.settings_menu.addSeparator()
        self.open_config_action = self.settings_menu.addAction("")
        self.reset_settings_action = self.settings_menu.addAction("")

        self.help_menu = self.menuBar().addMenu("")
        self.user_guide_action = self.help_menu.addAction("")
        self.help_menu.addSeparator()
        self.about_action = self.help_menu.addAction("")

    @staticmethod
    def _replace_combo_labels(combo: QComboBox, labels: dict[str | int, str]) -> None:
        current = combo.currentData()
        for index in range(combo.count()):
            value = combo.itemData(index)
            if value in labels:
                combo.setItemText(index, labels[value])
        restored = combo.findData(current)
        if restored >= 0:
            combo.setCurrentIndex(restored)

    def _align_settings_form_columns(self) -> None:
        label_width = max(
            label.sizeHint().width()
            for label in (self.output_label, self.work_label, self.cleanup_label)
        )
        self.path_layout.setColumnMinimumWidth(0, label_width)
        self.path_layout.invalidate()
        self.model_layout.invalidate()

    def retranslate_ui(self) -> None:
        self.setWindowTitle(self.tr("Japanese Video Subtitle Tool"))
        self.input_group.setTitle(self.tr("Input tasks (drop videos or folders here)"))
        self.task_table.setHorizontalHeaderLabels([
            self.tr("Video"), self.tr("Status"), self.tr("Progress"), self.tr("Output")
        ])
        self.add_files_button.setText(self.tr("Add videos"))
        self.add_folder_button.setText(self.tr("Add folder"))
        self.remove_button.setText(self.tr("Remove selected"))
        self.clear_button.setText(self.tr("Clear"))
        self.settings_group.setTitle(self.tr("Models and common settings"))
        self.asr_label.setText(self.tr("ASR model"))
        self.translator_label.setText(self.tr("Translation model"))
        self.target_language_label.setText(self.tr("Subtitle language"))
        self._replace_combo_labels(self.asr_combo, {
            AsrPreset.ANIME.value: self.tr("Anime (recommended)"),
            AsrPreset.QWEN.value: "Qwen",
        })
        self._replace_combo_labels(self.translator_combo, {
            TranslatorPreset.GALTRANSL.value: self.tr("GalTransl 7B (recommended)"),
            TranslatorPreset.SAKURA.value: "Sakura 14B",
            TranslatorPreset.SUGOI.value: "Sugoi 14B Ultra",
        })
        self._replace_combo_labels(self.target_language_combo, {
            TargetLanguage.SIMPLIFIED_CHINESE.value: self.tr("Simplified Chinese"),
            TargetLanguage.TRADITIONAL_CHINESE.value: self.tr("Traditional Chinese"),
            TargetLanguage.ENGLISH.value: self.tr("English"),
        })
        self.refresh_device_button.setText(self.tr("Probing…") if self._device_probe_state == "running" else self.tr("Refresh"))
        self.output_label.setText(self.tr("Output folder"))
        self.work_label.setText(self.tr("Work folder"))
        self.cleanup_label.setText(self.tr("After success"))
        self.output_browse.setText(self.tr("Browse…"))
        self.work_browse.setText(self.tr("Browse…"))
        self._replace_combo_labels(self.cleanup_combo, {
            CleanupPolicy.KEEP_ALL.value: self.tr("Keep all intermediate files"),
            CleanupPolicy.DELETE_AUDIO.value: self.tr("Delete WAV after success"),
            CleanupPolicy.FINAL_ONLY.value: self.tr("Keep only final subtitles, QC report, and logs"),
        })
        self.common_group.setTitle(self.tr("Output and performance"))
        self.recursive_check.setText(self.tr("Scan subfolders"))
        self.bilingual_check.setText(self.tr("Generate bilingual ASS"))
        self.quality_check.setText(self.tr("Generate quality report"))
        self.resume_check.setText(self.tr("Resume completed stages"))
        self.resume_check.setToolTip(self.tr("Reuse complete WAV, Japanese SRT, and translated subtitle files; disable this after changing models or key settings."))
        self.copy_check.setText(self.tr("Copy subtitles beside video"))
        self.speaker_check.setText(self.tr("Colour by speaker gender"))
        self.asr_batch_label.setText(self.tr("ASR batch size"))
        self._replace_combo_labels(self.asr_batch_combo, {
            24: self.tr("Performance (24; 14 GB+ VRAM)"),
            16: self.tr("Balanced (16)"),
            8: self.tr("Low VRAM (8)"),
            4: self.tr("Stability (4)"),
        })
        self.asr_batch_combo.setToolTip(self.tr("Affects ASR speed and VRAM usage; actual usage varies by model and GPU."))
        self.batch_note.setText(self.tr("Lower if VRAM is insufficient."))
        self.advanced_button.setText(self.tr("Advanced settings…"))
        self.advanced_button.setToolTip(self.tr("Advanced subtitle and translation settings…"))
        self.guidance_group.setTitle(self.tr("Tips"))
        self.guidance_label.setText(self.tr(
            "Drop videos or folders into the left panel\n"
            "The work folder stores intermediate files; the output folder stores final subtitles\n"
            "Do not reuse completed stages after changing models or key settings"
        ))
        self.log_toggle.setText(self.tr("Show logs"))
        resize_log_text = self.tr("Drag to resize the log panel")
        self.log_splitter_handle.setToolTip(resize_log_text)
        self.log_splitter_handle.setAccessibleName(resize_log_text)
        self.start_button.setText(self.tr("Start"))
        self.cancel_button.setText(self.tr("Cancel"))
        self.open_work_button.setText(self.tr("Open work folder"))
        self.open_output_button.setText(self.tr("Open output folder"))
        self.settings_menu.setTitle(self.tr("Settings"))
        self.language_menu.setTitle(self.tr("Language"))
        self.language_actions["system"].setText(self.tr("System language"))
        for code in ("zh_CN", "zh_TW", "en"):
            self.language_actions[code].setText(self.language_manager.specs[code].name)
        self.language_actions[self.language_manager.requested_code].setChecked(True)
        self.behaviour_menu.setTitle(self.tr("Startup and behaviour"))
        self.probe_on_startup_action.setText(self.tr("Probe device at startup"))
        self.open_output_on_finish_action.setText(self.tr("Open output folder when queue finishes"))
        self.open_config_action.setText(self.tr("Open configuration folder"))
        self.reset_settings_action.setText(self.tr("Restore all defaults…"))
        self.help_menu.setTitle(self.tr("Help"))
        self.user_guide_action.setText(self.tr("User guide"))
        self.about_action.setText(self.tr("About"))
        self.advanced_dialog.retranslate_ui()
        self.advanced_dialog.set_translator(str(self.translator_combo.currentData()))
        self._align_settings_form_columns()
        self._update_model_status()
        self._refresh_device_status_text()
        self._rerender_tasks()
        if not self.tasks:
            self.current_label.setText(self.tr("Waiting for tasks"))

    def _connect_signals(self) -> None:
        self.add_files_button.clicked.connect(self._choose_files)
        self.add_folder_button.clicked.connect(self._choose_folder)
        self.remove_button.clicked.connect(self._remove_selected)
        self.clear_button.clicked.connect(self._clear_tasks)
        self.output_browse.clicked.connect(lambda: self._choose_directory(self.output_edit))
        self.work_browse.clicked.connect(lambda: self._choose_directory(self.work_edit))
        self.start_button.clicked.connect(self._start)
        self.cancel_button.clicked.connect(self.controller.cancel)
        self.open_work_button.clicked.connect(self._open_work)
        self.open_output_button.clicked.connect(self._open_output)
        self.asr_combo.currentIndexChanged.connect(self._update_model_status)
        self.translator_combo.currentIndexChanged.connect(self._translator_changed)
        self.target_language_combo.currentIndexChanged.connect(self._target_language_changed)
        self.speaker_check.toggled.connect(self._update_model_status)
        self.advanced_button.clicked.connect(self._show_advanced_settings)
        self.refresh_device_button.clicked.connect(self._start_device_probe)
        self.log_toggle.toggled.connect(self.log_edit.setVisible)
        for edit in (self.output_edit, self.work_edit):
            edit.textChanged.connect(edit.setToolTip)
        self._device_probe.finished.connect(self._device_probe_finished)
        self.controller.task_updated.connect(self._update_task_row)
        self.controller.log_received.connect(self._append_log)
        self.controller.overall_progress_changed.connect(self.overall_progress.setValue)
        self.controller.running_changed.connect(self._set_running)
        self.controller.queue_finished.connect(self._queue_finished)
        self.language_manager.language_changed.connect(lambda _code: self.retranslate_ui())
        self.probe_on_startup_action.toggled.connect(
            lambda checked: self.settings.setValue("probe_device_on_startup", checked)
        )
        self.open_output_on_finish_action.toggled.connect(
            lambda checked: self.settings.setValue("open_output_on_finish", checked)
        )
        self.open_config_action.triggered.connect(self._open_config_folder)
        self.reset_settings_action.triggered.connect(self._restore_all_defaults)
        self.user_guide_action.triggered.connect(self._open_user_guide)
        self.about_action.triggered.connect(self._show_about)

    def _translator_changed(self) -> None:
        if self._target_change_guard:
            return
        if self._active_target != TargetLanguage.ENGLISH and self.translator_combo.currentData():
            self._last_chinese_translator = TranslatorPreset(self.translator_combo.currentData())
        self.advanced_dialog.set_translator(str(self.translator_combo.currentData()))
        self._update_model_status()

    def _populate_translator_combo(self, target: TargetLanguage, selected: TranslatorPreset) -> None:
        allowed = (
            (TranslatorPreset.SUGOI,)
            if target == TargetLanguage.ENGLISH
            else (TranslatorPreset.GALTRANSL, TranslatorPreset.SAKURA)
        )
        self.translator_combo.clear()
        for preset in allowed:
            self.translator_combo.addItem("", preset.value)
        wanted = selected if selected in allowed else allowed[0]
        self.translator_combo.setCurrentIndex(self.translator_combo.findData(wanted.value))
        self.translator_combo.setEnabled(len(allowed) > 1)
        self._replace_combo_labels(self.translator_combo, {
            TranslatorPreset.GALTRANSL.value: self.tr("GalTransl 7B (recommended)"),
            TranslatorPreset.SAKURA.value: "Sakura 14B",
            TranslatorPreset.SUGOI.value: "Sugoi 14B Ultra",
        })

    def _target_language_changed(self) -> None:
        if self._target_change_guard or self.target_language_combo.currentData() is None:
            return
        new_target = TargetLanguage(self.target_language_combo.currentData())
        old_target = self._active_target
        if old_target == new_target:
            return
        current_wrap = self.wrap_spin.value() if self.advanced_dialog.wrap_check.isChecked() else 0
        if old_target == TargetLanguage.ENGLISH:
            self._last_english_batch_size = self.batch_spin.value()
            self._last_english_wrap = current_wrap
            self._last_english_font = self.font_combo.currentFont().family()
        else:
            if self.translator_combo.currentData():
                self._last_chinese_translator = TranslatorPreset(self.translator_combo.currentData())
            self._last_chinese_batch_size = self.batch_spin.value()
            self._last_chinese_wrap = current_wrap
            self._last_chinese_font = self.font_combo.currentFont().family()

        self._target_change_guard = True
        try:
            if new_target == TargetLanguage.ENGLISH:
                self._populate_translator_combo(new_target, TranslatorPreset.SUGOI)
                batch, wrap = self._last_english_batch_size, self._last_english_wrap
                target_font = self._last_english_font
            else:
                self._populate_translator_combo(new_target, self._last_chinese_translator)
                batch, wrap = self._last_chinese_batch_size, self._last_chinese_wrap
                target_font = self._last_chinese_font
            self.batch_spin.setValue(batch)
            self.advanced_dialog.wrap_check.setChecked(wrap > 0)
            self.wrap_spin.setValue(wrap or DEFAULT_WRAP_CHARS_BY_TARGET[new_target])
            self.font_combo.setCurrentFont(QFont(target_font))
            self._active_target = new_target
        finally:
            self._target_change_guard = False
        self.advanced_dialog.set_target_language(new_target)
        self.advanced_dialog.set_translator(str(self.translator_combo.currentData()))
        self._update_model_status()

    def _update_log_splitter_floor(self) -> int | None:
        if not hasattr(self, "log_splitter"):
            return None
        extra_height = max(0, self.height() - self.DEFAULT_WINDOW_HEIGHT)
        content_floor = (
            self.log_splitter.height()
            - self.log_splitter.handleWidth()
            - self.DEFAULT_LOG_HEIGHT
            - extra_height
        )
        if content_floor > 0:
            self.content_panel.setMinimumHeight(content_floor)
            return content_floor
        return None

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt virtual method
        super().resizeEvent(event)
        self._update_log_splitter_floor()

    def showEvent(self, event) -> None:  # noqa: N802 - Qt virtual method
        super().showEvent(event)
        content_floor = self._update_log_splitter_floor()
        if not self._log_splitter_initialised and content_floor is not None:
            available_height = self.log_splitter.height() - self.log_splitter.handleWidth()
            self.log_splitter.setSizes([
                content_floor,
                max(self.log_edit.minimumHeight(), available_height - content_floor),
            ])
            self._log_splitter_initialised = True

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls() and any(url.isLocalFile() for url in event.mimeData().urls()):
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        paths = [Path(url.toLocalFile()) for url in event.mimeData().urls() if url.isLocalFile()]
        self.add_paths(paths)
        event.acceptProposedAction()

    def add_paths(self, paths: list[Path]) -> int:
        if self.controller.is_running:
            return 0
        videos = discover_dropped_videos(paths, self.recursive_check.isChecked())
        existing = {str(task.video).casefold() for task in self.tasks}
        added = 0
        for video in videos:
            if str(video).casefold() in existing:
                continue
            task = GuiTask(video)
            self.tasks.append(task)
            existing.add(str(video).casefold())
            self._append_task_row(task)
            added += 1
        return added

    def _task_status_text(self, task: GuiTask) -> str:
        if task.status == TaskStatus.RUNNING and task.stage:
            details = {
                "prepare_asr": self.tr("Preparing Japanese ASR"),
                "load_translation": self.tr("Loading translation model"),
                "generate_ass": self.tr("Generating bilingual ASS"),
                "generate_quality": self.tr("Generating quality report"),
                "anime_loading": self.tr("Loading Anime model"),
                "anime_recognising": self.tr("Running Anime recognition ({current}/{total})"),
                "forced_alignment": self.tr("Running forced alignment ({current}/{total})"),
                "qwen_recognising": self.tr("Running Qwen recognition ({current}/{total})"),
                "semantic_scenes": self.tr("Analysing semantic scenes"),
                "speech_segments": self.tr("Analysing speech segments"),
                "qwen_running": self.tr("Running Qwen Japanese ASR"),
                "asr_finalising": self.tr("Finalising Japanese subtitles"),
                "translating": self.tr("Translating subtitles ({current}/{total})"),
            }
            if task.detail_key in details:
                return details[task.detail_key].format(**task.detail_args)
            if task.detail:
                return task.detail
            stages = {
                "extract": self.tr("Extracting audio"),
                "asr": self.tr("Japanese ASR"),
                "translate": self.tr("Chinese translation"),
                "ass": self.tr("Generating ASS"),
                "quality": self.tr("Quality check"),
                "cleanup": self.tr("Cleaning intermediate files"),
            }
            return stages.get(task.stage, task.stage)
        statuses = {
            TaskStatus.WAITING: self.tr("Waiting"),
            TaskStatus.RUNNING: self.tr("Processing"),
            TaskStatus.COMPLETED: self.tr("Completed"),
            TaskStatus.FAILED: self.tr("Failed"),
            TaskStatus.CANCELLED: self.tr("Cancelled"),
        }
        return statuses[task.status]

    def _task_error_text(self, task: GuiTask) -> str:
        if task.error:
            return task.error
        errors = {
            "stage_failed": self.tr("Pipeline stage failed"),
            "job_failed": self.tr("Task failed"),
            "process_crashed": self.tr("Pipeline process crashed"),
            "exit_code": self.tr("Pipeline exit code: {code}"),
            "failed_to_start": self.tr("Could not start the pipeline process"),
        }
        if task.error_key in errors:
            return errors[task.error_key].format(**task.error_args)
        return ""

    def _rerender_tasks(self) -> None:
        for task in self.tasks:
            self._update_task_row(task)

    def _append_task_row(self, task: GuiTask) -> None:
        row = self.task_table.rowCount()
        self.task_table.insertRow(row)
        self._rows_by_id[task.task_id] = row
        video_item = QTableWidgetItem(str(task.video))
        video_item.setToolTip(str(task.video))
        task_text = self._task_status_text(task)
        status_item = QTableWidgetItem(task_text)
        status_item.setToolTip(task_text)
        self.task_table.setItem(row, 0, video_item)
        self.task_table.setItem(row, 1, status_item)
        self.task_table.setItem(row, 2, QTableWidgetItem(f"{task.progress_percent}%"))
        self.task_table.setItem(row, 3, QTableWidgetItem(""))

    def _update_task_row(self, task: GuiTask) -> None:
        row = self._rows_by_id.get(task.task_id)
        if row is None:
            return
        task_text = self._task_status_text(task)
        error_text = self._task_error_text(task)
        status_text = task_text if not error_text else self.tr("{status}: {error}").format(status=task_text, error=error_text)
        self.task_table.item(row, 1).setText(status_text)
        self.task_table.item(row, 1).setToolTip(status_text)
        self.task_table.item(row, 2).setText(f"{task.progress_percent}%")
        output = task.outputs.get("ass") or task.outputs.get("srt")
        output_text = str(output) if output else ""
        self.task_table.item(row, 3).setText(output_text)
        self.task_table.item(row, 3).setToolTip(output_text)
        if task.status == TaskStatus.RUNNING:
            self.current_label.setText(self.tr("{video} — {status}").format(video=task.video.name, status=task_text))
        elif task.status == TaskStatus.FAILED:
            self.log_toggle.setChecked(True)

    def _choose_files(self) -> None:
        names, _ = QFileDialog.getOpenFileNames(self, self.tr("Select videos"), "", self.tr("Video files (*.mp4 *.mkv *.mov *.avi *.wmv *.flv *.webm *.m4v *.ts)"))
        self.add_paths([Path(name) for name in names])

    def _choose_folder(self) -> None:
        name = QFileDialog.getExistingDirectory(self, self.tr("Select video folder"))
        if name:
            self.add_paths([Path(name)])

    def _choose_directory(self, target: QLineEdit) -> None:
        name = QFileDialog.getExistingDirectory(self, self.tr("Select folder"), target.text())
        if name:
            target.setText(name)
            target.setCursorPosition(0)

    def _show_advanced_settings(self) -> None:
        snapshot = self.advanced_dialog.snapshot()
        if self.advanced_dialog.exec() != QDialog.DialogCode.Accepted:
            self.advanced_dialog.restore_snapshot(snapshot)

    def _start_device_probe(self) -> None:
        if self._device_probe.state() != QProcess.ProcessState.NotRunning:
            return
        self._device_probe_state = "running"
        self._last_device_data = None
        self.device_status_label.setText(self.tr("Device: probing CUDA…"))
        self.device_status_label.setStyleSheet("color: #555;")
        self.refresh_device_button.setText(self.tr("Probing…"))
        probe_script = Path(__file__).with_name("device_probe.py")
        self._device_probe.start(sys.executable, [str(probe_script)])

    def _device_probe_finished(self, exit_code: int, _status: QProcess.ExitStatus) -> None:
        self.refresh_device_button.setText(self.tr("Refresh"))
        if exit_code != 0:
            self._device_probe_state = "failed"
            detail = bytes(self._device_probe.readAllStandardError()).decode("utf-8", errors="replace").strip()
            self.device_status_label.setText(self.tr("Device: probe failed"))
            self.device_status_label.setStyleSheet("color: #c0392b;")
            self.device_status_label.setToolTip(detail)
            return
        try:
            data = json.loads(bytes(self._device_probe.readAllStandardOutput()).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._device_probe_state = "invalid"
            self.device_status_label.setText(self.tr("Device: could not parse probe result"))
            self.device_status_label.setStyleSheet("color: #c0392b;")
            return
        self._device_probe_state = "ready"
        self._last_device_data = data
        text, colour = format_device_status(data)
        self.device_status_label.setText(text)
        self.device_status_label.setStyleSheet(f"color: {colour};")
        self.device_status_label.setToolTip(str(data.get("details") or ""))

    def _refresh_device_status_text(self) -> None:
        if self._device_probe_state == "running":
            self.device_status_label.setText(self.tr("Device: probing CUDA…"))
        elif self._device_probe_state == "disabled":
            self.device_status_label.setText(self.tr("Device: automatic startup probe disabled"))
            self.device_status_label.setStyleSheet("color: #555;")
        elif self._device_probe_state == "failed":
            self.device_status_label.setText(self.tr("Device: probe failed"))
        elif self._device_probe_state == "invalid":
            self.device_status_label.setText(self.tr("Device: could not parse probe result"))
        elif self._last_device_data is not None:
            text, colour = format_device_status(self._last_device_data)
            self.device_status_label.setText(text)
            self.device_status_label.setStyleSheet(f"color: {colour};")

    def _remove_selected(self) -> None:
        if self.controller.is_running:
            return
        rows = sorted({index.row() for index in self.task_table.selectedIndexes()}, reverse=True)
        for row in rows:
            task = self.tasks.pop(row)
            self.task_table.removeRow(row)
            self._rows_by_id.pop(task.task_id, None)
        self._rebuild_row_map()

    def _clear_tasks(self) -> None:
        if self.controller.is_running:
            return
        self.tasks.clear()
        self._rows_by_id.clear()
        self.task_table.setRowCount(0)
        self.overall_progress.setValue(0)

    def _rebuild_row_map(self) -> None:
        self._rows_by_id = {task.task_id: row for row, task in enumerate(self.tasks)}

    def _config_from_ui(self) -> GuiConfig:
        return GuiConfig(
            output_dir=Path(self.output_edit.text()).expanduser(),
            work_dir=Path(self.work_edit.text()).expanduser(),
            recursive=self.recursive_check.isChecked(),
            asr=AsrPreset(self.asr_combo.currentData()),
            translator=TranslatorPreset(self.translator_combo.currentData()),
            target_language=TargetLanguage(self.target_language_combo.currentData()),
            bilingual=self.bilingual_check.isChecked(),
            quality_report=self.quality_check.isChecked(),
            resume=self.resume_check.isChecked(),
            copy_to_video_dir=self.copy_check.isChecked(),
            cleanup_policy=CleanupPolicy(self.cleanup_combo.currentData()),
            asr_batch_size=int(self.asr_batch_combo.currentData()),
            context_size=self.context_spin.value(),
            translate_batch_size=self.batch_spin.value(),
            display_wrap_max_chars=self.wrap_spin.value() if self.advanced_dialog.wrap_check.isChecked() else 0,
            bilingual_font=self.font_combo.currentFont().family(),
            bilingual_ja_font=self.ja_font_combo.currentFont().family(),
            bilingual_zh_font_size=self.zh_size_spin.value(),
            bilingual_ja_font_size=self.ja_size_spin.value(),
            bilingual_zh_colour=self.zh_colour_edit.text().strip(),
            bilingual_ja_colour=self.ja_colour_edit.text().strip(),
            bilingual_male_colour=self.male_colour_edit.text().strip(),
            bilingual_female_colour=self.female_colour_edit.text().strip(),
            colour_by_speaker=self.speaker_check.isChecked(),
        )

    def _start(self) -> None:
        if not any(task.status == TaskStatus.WAITING for task in self.tasks):
            QMessageBox.information(self, self.tr("No tasks"), self.tr("Add a video task first."))
            return
        config = self._config_from_ui()
        errors = config.validate()
        if errors:
            messages = {
                "asr_batch_positive": self.tr("ASR batch size must be greater than 0."),
                "context_nonnegative": self.tr("Translation context cannot be negative."),
                "translate_batch_nonnegative": self.tr("Translation batch size cannot be negative."),
                "wrap_nonnegative": self.tr("Maximum characters per line cannot be negative."),
                "subtitle_size_positive": self.tr("Subtitle font sizes must be greater than 0."),
                "subtitle_font_required": self.tr("Subtitle font cannot be empty."),
                "translator_target_incompatible": self.tr("The selected translation model does not support this subtitle language."),
            }
            colour_names = {
                "zh": self.tr("Chinese colour"), "ja": self.tr("Japanese colour"),
                "male": self.tr("Male speaker colour"), "female": self.tr("Female speaker colour"),
            }
            rendered = []
            for issue in errors:
                if issue.code == "ass_colour_format":
                    rendered.append(self.tr("{field} must use ASS &HAABBGGRR format.").format(field=colour_names[str(issue.params["field"])]))
                else:
                    rendered.append(messages.get(issue.code, issue.code))
            QMessageBox.warning(self, self.tr("Invalid settings"), "\n".join(rendered))
            return
        missing = missing_model_files(config)
        if missing:
            preview = "\n".join(str(path) for path in missing[:8])
            QMessageBox.warning(self, self.tr("Models incomplete"), self.tr("The selected models are missing files:\n{files}").format(files=preview))
            return
        self._save_settings()
        self.controller.start(self.tasks, config)

    def _open_output(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(self.output_edit.text()).expanduser().resolve())))

    def _open_work(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(self.work_edit.text()).expanduser().resolve())))

    def _open_config_folder(self) -> None:
        config_folder = Path(self.settings.fileName()).expanduser().resolve().parent
        config_folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(config_folder)))

    def _open_user_guide(self) -> None:
        filename = "README-CN.md" if self.language_manager.current_code.startswith("zh") else "README.md"
        candidates = (PROJECT_ROOT / filename, PROJECT_ROOT / "app" / filename)
        guide = next((path for path in candidates if path.is_file()), None)
        if guide is None:
            QMessageBox.warning(
                self,
                self.tr("User guide unavailable"),
                self.tr("The local user guide could not be found."),
            )
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(guide.resolve())))

    def _show_about(self) -> None:
        QMessageBox.about(
            self,
            self.tr("About jp2zh Subtitle Tool"),
            self.tr(
                "<b>jp2zh Subtitle Tool</b><br><br>"
                "Generate Chinese or English subtitles from Japanese videos with local models.<br><br>"
                '<a href="https://github.com/chubbyk-uu/jp2zh-video-subs">Project on GitHub</a>'
            ),
        )

    def _restore_all_defaults(self) -> None:
        answer = QMessageBox.question(
            self,
            self.tr("Restore all defaults"),
            self.tr("Reset all GUI settings, including window layout, paths, models, appearance, and language?"),
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.settings.clear()
        self.language_manager.set_language("system")
        self._restore_settings()
        self.retranslate_ui()
        self._update_model_status()
        self.showNormal()
        self.resize(self.DEFAULT_WINDOW_WIDTH, self.DEFAULT_WINDOW_HEIGHT)
        self.centralWidget().layout().activate()
        available_height = self.log_splitter.height() - self.log_splitter.handleWidth()
        self.log_splitter.setSizes([
            max(0, available_height - self.DEFAULT_LOG_HEIGHT),
            self.DEFAULT_LOG_HEIGHT,
        ])
        if sys.platform == "win32":
            self._centre_on_primary_screen()

    def _update_model_status(self) -> None:
        config = self._config_from_ui()
        missing = missing_model_files(config)
        if missing:
            self.model_status_label.setText(self.tr("{count} model files missing").format(count=len(missing)))
            self.model_status_label.setStyleSheet("color: #c0392b;")
            self.model_status_label.setToolTip("\n".join(str(path) for path in missing))
        else:
            self.model_status_label.setText(self.tr("Selected model files are complete"))
            self.model_status_label.setStyleSheet("color: #18864b;")
            self.model_status_label.setToolTip("")

    def _append_log(self, text: str) -> None:
        cursor = self.log_edit.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        cursor.insertText(text)
        self.log_edit.setTextCursor(cursor)
        self.log_edit.ensureCursorVisible()

    def _set_running(self, running: bool) -> None:
        self.start_button.setEnabled(not running)
        self.cancel_button.setEnabled(running)
        for widget in (
            self.add_files_button, self.add_folder_button, self.remove_button, self.clear_button,
            self.settings_group, self.common_group,
        ):
            widget.setEnabled(not running)
        self.reset_settings_action.setEnabled(not running)

    def _restore_settings(self) -> None:
        defaults = GuiConfig()
        previous_version = self.settings.value("ui_settings_version", 0, int)
        migrate_common_defaults = previous_version < self.UI_SETTINGS_VERSION
        output_dir = self.settings.value("output_dir", str(defaults.output_dir), str)
        work_dir = self.settings.value("work_dir", str(defaults.work_dir), str)
        if portable_config_path() is not None:
            current_root = defaults.output_dir.parent
            previous_root = self.settings.value("portable_root", "", str)
            if previous_root:
                output_dir = str(rebase_portable_path(output_dir, previous_root, current_root))
                work_dir = str(rebase_portable_path(work_dir, previous_root, current_root))
            else:
                output_path = Path(output_dir)
                work_path = Path(work_dir)
                if (
                    output_path.parent == work_path.parent
                    and output_path.name == "outputs"
                    and work_path.name == "work"
                ):
                    output_dir = str(defaults.output_dir)
                    work_dir = str(defaults.work_dir)
        self.output_edit.setText(output_dir)
        self.work_edit.setText(work_dir)
        self._set_combo_value(self.asr_combo, self.settings.value("asr", defaults.asr.value, str))
        try:
            self._last_chinese_translator = TranslatorPreset(
                self.settings.value("last_chinese_translator", defaults.translator.value, str)
            )
        except ValueError:
            self._last_chinese_translator = defaults.translator
        self._last_chinese_font = self.settings.value("last_chinese_font", defaults.bilingual_font, str)
        self._last_english_font = self.settings.value("last_english_font", "Arial", str)
        self._last_chinese_batch_size = self.settings.value(
            "last_chinese_batch", defaults.translate_batch_size, int
        )
        self._last_chinese_wrap = self.settings.value(
            "last_chinese_wrap", defaults.display_wrap_max_chars, int
        )
        self._last_english_batch_size = self.settings.value(
            "last_english_batch", DEFAULT_BATCH_SIZE_BY_TRANSLATOR["sugoi"], int
        )
        self._last_english_wrap = self.settings.value(
            "last_english_wrap", DEFAULT_WRAP_CHARS_BY_TARGET[TargetLanguage.ENGLISH], int
        )
        try:
            restored_target = TargetLanguage(
                self.settings.value("target_language", defaults.target_language.value, str)
            )
        except ValueError:
            restored_target = defaults.target_language
        try:
            restored_translator = TranslatorPreset(
                self.settings.value("translator", defaults.translator.value, str)
            )
        except ValueError:
            restored_translator = defaults.translator
        self._target_change_guard = True
        try:
            self._set_combo_value(self.target_language_combo, restored_target.value)
            self._active_target = restored_target
            self._populate_translator_combo(restored_target, restored_translator)
        finally:
            self._target_change_guard = False
        self.advanced_dialog.set_target_language(restored_target)
        self._set_combo_value(self.cleanup_combo, self.settings.value("cleanup", defaults.cleanup_policy.value, str))
        self.recursive_check.setChecked(defaults.recursive if migrate_common_defaults else self.settings.value("recursive", defaults.recursive, bool))
        self.bilingual_check.setChecked(defaults.bilingual if migrate_common_defaults else self.settings.value("bilingual", defaults.bilingual, bool))
        self.quality_check.setChecked(self.settings.value("quality", defaults.quality_report, bool))
        self.resume_check.setChecked(defaults.resume if migrate_common_defaults else self.settings.value("resume", defaults.resume, bool))
        self.copy_check.setChecked(defaults.copy_to_video_dir if migrate_common_defaults else self.settings.value("copy", defaults.copy_to_video_dir, bool))
        self.speaker_check.setChecked(self.settings.value("speaker", defaults.colour_by_speaker, bool))
        self.log_toggle.setChecked(self.settings.value("show_log", True, bool))
        self.probe_on_startup_action.setChecked(
            self.settings.value("probe_device_on_startup", True, bool)
        )
        self.open_output_on_finish_action.setChecked(
            self.settings.value("open_output_on_finish", False, bool)
        )
        self._set_asr_batch_value(self.settings.value("asr_batch", defaults.asr_batch_size, int))
        self.context_spin.setValue(self.settings.value("context", defaults.context_size, int))
        self.batch_spin.setValue(self.settings.value("batch", defaults.translate_batch_size, int))
        wrap_value = self.settings.value("wrap", defaults.display_wrap_max_chars, int)
        self.advanced_dialog.wrap_check.setChecked(wrap_value > 0)
        self.wrap_spin.setValue(wrap_value or defaults.display_wrap_max_chars)
        self.font_combo.setCurrentFont(QFont(self.settings.value("font", defaults.bilingual_font, str)))
        self.ja_font_combo.setCurrentFont(QFont(self.settings.value("ja_font", defaults.bilingual_ja_font, str)))
        self.zh_size_spin.setValue(self.settings.value("zh_size", defaults.bilingual_zh_font_size, int))
        self.ja_size_spin.setValue(self.settings.value("ja_size", defaults.bilingual_ja_font_size, int))
        self.zh_colour_edit.setText(self.settings.value("zh_colour", defaults.bilingual_zh_colour, str))
        self.ja_colour_edit.setText(self.settings.value("ja_colour", defaults.bilingual_ja_colour, str))
        self.male_colour_edit.setText(self.settings.value("male_colour", defaults.bilingual_male_colour, str))
        self.female_colour_edit.setText(self.settings.value("female_colour", defaults.bilingual_female_colour, str))
        for key, edit in (
            ("zh", self.zh_colour_edit), ("ja", self.ja_colour_edit),
            ("male", self.male_colour_edit), ("female", self.female_colour_edit),
        ):
            self.advanced_dialog._refresh_colour_button(edit, self.colour_buttons[key])
        for edit in (self.output_edit, self.work_edit):
            edit.setCursorPosition(0)
            edit.setToolTip(edit.text())
        geometry = self.settings.value("geometry")
        if geometry is not None and self.settings.value("ui_settings_version", 0, int) == self.UI_SETTINGS_VERSION:
            self.restoreGeometry(geometry)
        elif sys.platform == "win32":
            self._centre_on_primary_screen()
        self.log_edit.setVisible(self.settings.value("show_log", True, bool))

    def _centre_on_primary_screen(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        available = screen.availableGeometry()
        self.move(
            available.x() + max(0, (available.width() - self.width()) // 2),
            available.y() + max(0, (available.height() - self.height()) // 2),
        )

    def _save_settings(self) -> None:
        config = self._config_from_ui()
        if config.target_language != TargetLanguage.ENGLISH:
            self._last_chinese_translator = config.translator
            self._last_chinese_font = config.bilingual_font
            self._last_chinese_batch_size = config.translate_batch_size
            self._last_chinese_wrap = config.display_wrap_max_chars
        else:
            self._last_english_font = config.bilingual_font
            self._last_english_batch_size = config.translate_batch_size
            self._last_english_wrap = config.display_wrap_max_chars
        values = {
            "output_dir": str(config.output_dir), "work_dir": str(config.work_dir),
            "asr": config.asr.value, "translator": config.translator.value,
            "target_language": config.target_language.value,
            "last_chinese_translator": self._last_chinese_translator.value,
            "last_chinese_font": self._last_chinese_font,
            "last_english_font": self._last_english_font,
            "last_chinese_batch": self._last_chinese_batch_size,
            "last_chinese_wrap": self._last_chinese_wrap,
            "last_english_batch": self._last_english_batch_size,
            "last_english_wrap": self._last_english_wrap,
            "cleanup": config.cleanup_policy.value, "recursive": config.recursive,
            "bilingual": config.bilingual, "quality": config.quality_report,
            "resume": config.resume, "copy": config.copy_to_video_dir,
            "speaker": config.colour_by_speaker, "context": config.context_size,
            "asr_batch": config.asr_batch_size,
            "batch": config.translate_batch_size, "wrap": config.display_wrap_max_chars,
            "font": config.bilingual_font, "ja_font": config.bilingual_ja_font,
            "zh_size": config.bilingual_zh_font_size,
            "ja_size": config.bilingual_ja_font_size,
            "zh_colour": config.bilingual_zh_colour, "ja_colour": config.bilingual_ja_colour,
            "male_colour": config.bilingual_male_colour, "female_colour": config.bilingual_female_colour,
            "show_log": self.log_toggle.isChecked(),
            "probe_device_on_startup": self.probe_on_startup_action.isChecked(),
            "open_output_on_finish": self.open_output_on_finish_action.isChecked(),
        }
        for key, value in values.items():
            self.settings.setValue(key, value)
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("ui_settings_version", self.UI_SETTINGS_VERSION)
        if portable_config_path() is not None:
            self.settings.setValue("portable_root", str(GuiConfig().output_dir.parent))

    @staticmethod
    def _set_combo_value(combo: QComboBox, value: str) -> None:
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)

    def _set_asr_batch_value(self, value: int) -> None:
        index = self.asr_batch_combo.findData(value)
        if index < 0:
            self.asr_batch_combo.addItem(self.tr("Custom (batch size {value})").format(value=value), value)
            index = self.asr_batch_combo.count() - 1
        self.asr_batch_combo.setCurrentIndex(index)

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.controller.is_running:
            answer = QMessageBox.question(self, self.tr("Task still running"), self.tr("Cancel the current task and exit?"))
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self._close_when_finished = True
            self.controller.cancel()
            event.ignore()
            return
        if self._device_probe.state() != QProcess.ProcessState.NotRunning:
            self._device_probe.kill()
            self._device_probe.waitForFinished(1000)
        self._save_settings()
        event.accept()

    def _queue_finished(self) -> None:
        self.current_label.setText(self.tr("Queue finished"))
        if self._close_when_finished:
            self._close_when_finished = False
            self.close()
        elif self.open_output_on_finish_action.isChecked():
            self._open_output()
