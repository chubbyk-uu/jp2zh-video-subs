"""PySide6 main window for batch subtitle generation."""
from __future__ import annotations

from pathlib import Path

import json
import sys

from PySide6.QtCore import QPoint, QProcess, QSettings, Qt, QUrl
from PySide6.QtGui import QColor, QCloseEvent, QDesktopServices, QDragEnterEvent, QDropEvent, QFont, QFontDatabase
from PySide6.QtWidgets import (
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
    QSpinBox,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from .controller import PipelineController
from .models import (
    ASR_LABELS,
    CLEANUP_LABELS,
    TRANSLATOR_LABELS,
    AsrPreset,
    CleanupPolicy,
    GuiConfig,
    GuiTask,
    TaskStatus,
    TranslatorPreset,
    discover_dropped_videos,
    missing_model_files,
)


class AutoCloseComboBox(QComboBox):
    """Combo-box facade backed by QMenu instead of WSLg's sticky Qt popup."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._popup_menu: QMenu | None = None

    def showPopup(self) -> None:
        if self._popup_menu is not None:
            self._popup_menu.close()
        menu = QMenu(self)
        menu.setMinimumWidth(self.width())
        for index in range(self.count()):
            action = menu.addAction(self.itemIcon(index), self.itemText(index))
            action.setCheckable(True)
            action.setChecked(index == self.currentIndex())
            action.triggered.connect(lambda _checked=False, selected=index: self._select_menu_item(selected))
        menu.aboutToHide.connect(self._menu_hidden)
        self._popup_menu = menu
        menu.popup(self.mapToGlobal(QPoint(0, self.height())))

    def hidePopup(self) -> None:
        if self._popup_menu is not None:
            self._popup_menu.close()

    def _select_menu_item(self, index: int) -> None:
        self.setCurrentIndex(index)
        self.activated.emit(index)
        if self._popup_menu is not None:
            self._popup_menu.close()

    def _menu_hidden(self) -> None:
        menu = self._popup_menu
        self._popup_menu = None
        if menu is not None:
            menu.deleteLater()


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
        self.setWindowTitle("高级字幕与翻译设置")
        self.setMinimumSize(560, 440)
        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        self.tabs = tabs

        translation_tab = QWidget()
        translation_form = QFormLayout(translation_tab)
        self.context_spin = QSpinBox()
        self.context_spin.setRange(0, 64)
        self.context_spin.setToolTip("提供给翻译模型的前文轮数；0 表示逐句独立翻译。")
        self.batch_spin = QSpinBox()
        self.batch_spin.setRange(0, 64)
        self.batch_spin.setToolTip("GalTransl 连续字幕成组翻译的最大条数；不是 GPU 并行数。")
        translation_form.addRow("翻译上下文", self.context_spin)
        translation_form.addRow("翻译批大小", self.batch_spin)
        translation_form.addRow(QLabel("这些参数影响翻译语境和分组，不是显存并行参数。"))
        tabs.addTab(translation_tab, "翻译设置")

        style_tab = QWidget()
        style_form = QFormLayout(style_tab)
        self.wrap_check = QCheckBox("超过指定字数时，按最接近中间的标点分成两行")
        self.wrap_spin = QSpinBox()
        self.wrap_spin.setRange(1, 200)
        self.wrap_spin.setSuffix(" 字")
        self.wrap_spin.setToolTip("没有合适标点时不会强行断行；字幕条数和时间轴不变。")
        self.wrap_check.toggled.connect(self.wrap_spin.setEnabled)
        wrap_row = QHBoxLayout()
        wrap_row.addWidget(self.wrap_check)
        wrap_row.addWidget(self.wrap_spin)
        style_form.addRow("长字幕自动换行", wrap_row)
        self.font_combo = FontComboBox()
        self.font_combo.setMaxVisibleItems(18)
        style_form.addRow("字幕字体", self.font_combo)
        self.zh_size_spin = QSpinBox()
        self.zh_size_spin.setRange(1, 200)
        self.ja_size_spin = QSpinBox()
        self.ja_size_spin.setRange(1, 200)
        style_form.addRow("中文字号", self.zh_size_spin)
        style_form.addRow("日文字号", self.ja_size_spin)

        self.colour_edits: dict[str, QLineEdit] = {}
        self.colour_buttons: dict[str, QPushButton] = {}
        for label, key in (("中文颜色", "zh"), ("日文颜色", "ja"), ("男性颜色", "male"), ("女性颜色", "female")):
            edit = QLineEdit()
            edit.hide()
            button = QPushButton()
            button.setMinimumHeight(30)
            button.clicked.connect(lambda _checked=False, e=edit, b=button: self._choose_colour(e, b))
            self.colour_edits[key] = edit
            self.colour_buttons[key] = button
            style_form.addRow(label, button)
        tabs.addTab(style_tab, "字幕样式")
        layout.addWidget(tabs)

        restore_button = QPushButton("恢复默认值")
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("确定")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        bottom = QHBoxLayout()
        bottom.addWidget(restore_button)
        bottom.addStretch()
        bottom.addWidget(buttons)
        layout.addLayout(bottom)
        restore_button.clicked.connect(self.restore_defaults)

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
        button.setToolTip(f"{edit.text()}（点击选择颜色）")

    def _choose_colour(self, edit: QLineEdit, button: QPushButton) -> None:
        red, green, blue, alpha = self._ass_colour_parts(edit.text())
        colour = QColorDialog.getColor(QColor(red, green, blue), self, "选择字幕颜色")
        if not colour.isValid():
            return
        edit.setText(f"&H{alpha}{colour.blue():02X}{colour.green():02X}{colour.red():02X}")
        self._refresh_colour_button(edit, button)

    def restore_defaults(self) -> None:
        defaults = GuiConfig()
        self.context_spin.setValue(defaults.context_size)
        self.batch_spin.setValue(defaults.translate_batch_size)
        self.wrap_check.setChecked(defaults.display_wrap_max_chars > 0)
        self.wrap_spin.setValue(defaults.display_wrap_max_chars or 20)
        self.font_combo.setCurrentFont(QFont(defaults.bilingual_font))
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
            "font": self.font_combo.currentFont().family(), "zh_size": self.zh_size_spin.value(),
            "ja_size": self.ja_size_spin.value(),
            **{f"{key}_colour": edit.text() for key, edit in self.colour_edits.items()},
        }

    def restore_snapshot(self, values: dict[str, object]) -> None:
        self.context_spin.setValue(int(values["context"]))
        self.batch_spin.setValue(int(values["batch"]))
        self.wrap_check.setChecked(bool(values["wrap_enabled"]))
        self.wrap_spin.setValue(int(values["wrap"]))
        self.font_combo.setCurrentFont(QFont(str(values["font"])))
        self.zh_size_spin.setValue(int(values["zh_size"]))
        self.ja_size_spin.setValue(int(values["ja_size"]))
        for key in self.colour_edits:
            self.colour_edits[key].setText(str(values[f"{key}_colour"]))
            self._refresh_colour_button(self.colour_edits[key], self.colour_buttons[key])


class MainWindow(QMainWindow):
    UI_SETTINGS_VERSION = 3

    def __init__(self, controller: PipelineController | None = None, settings: QSettings | None = None) -> None:
        super().__init__()
        self.controller = controller or PipelineController(self)
        self.tasks: list[GuiTask] = []
        self._rows_by_id: dict[str, int] = {}
        self.settings = settings or QSettings("jp2zh-video-subs", "jp2zh-video-subs")
        self._close_when_finished = False
        self._device_probe = QProcess(self)
        self.setWindowTitle("日语视频中文字幕工具")
        self.setMinimumSize(1120, 680)
        self.resize(1280, 720)
        self.setAcceptDrops(True)
        self._apply_visual_style()
        self._build_ui()
        self._connect_signals()
        self._restore_settings()
        self._update_model_status()
        self._start_device_probe()

    def _apply_visual_style(self) -> None:
        families = set(QFontDatabase.families())
        family = "Microsoft YaHei UI" if "Microsoft YaHei UI" in families else "Microsoft YaHei" if "Microsoft YaHei" in families else self.font().family()
        font = QFont(family)
        font.setPointSize(10)
        self.setFont(font)
        self.setStyleSheet("""
            QWidget { font-family: "Microsoft YaHei"; font-size: 10pt; }
            QLineEdit, QComboBox, QSpinBox { min-height: 30px; }
            QPushButton { min-height: 30px; padding: 2px 10px; }
            QPushButton#primaryButton {
                min-height: 34px; min-width: 112px; font-weight: 600;
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

        input_group = QGroupBox("输入任务（可直接拖入视频或文件夹）")
        input_layout = QVBoxLayout(input_group)
        self.task_table = QTableWidget(0, 4)
        self.task_table.setHorizontalHeaderLabels(["视频", "状态", "进度", "输出"])
        self.task_table.horizontalHeader().setStretchLastSection(True)
        self.task_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.task_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.task_table.verticalHeader().setDefaultSectionSize(31)
        input_layout.addWidget(self.task_table)
        queue_buttons = QHBoxLayout()
        self.add_files_button = QPushButton("添加视频")
        self.add_folder_button = QPushButton("添加文件夹")
        self.remove_button = QPushButton("移除选中")
        self.clear_button = QPushButton("清空")
        for button in (self.add_files_button, self.add_folder_button, self.remove_button, self.clear_button):
            queue_buttons.addWidget(button)
        queue_buttons.addStretch()
        input_layout.addLayout(queue_buttons)

        settings_group = QGroupBox("模型与常用设置")
        self.settings_group = settings_group
        settings_layout = QVBoxLayout(settings_group)
        model_layout = QGridLayout()
        model_layout.setHorizontalSpacing(8)
        self.asr_combo = AutoCloseComboBox()
        self.asr_combo.setMinimumWidth(150)
        for preset, label in ASR_LABELS.items():
            self.asr_combo.addItem(label, preset.value)
        self.translator_combo = AutoCloseComboBox()
        self.translator_combo.setMinimumWidth(170)
        for preset, label in TRANSLATOR_LABELS.items():
            self.translator_combo.addItem(label, preset.value)
        self.cleanup_combo = AutoCloseComboBox()
        for policy, label in CLEANUP_LABELS.items():
            self.cleanup_combo.addItem(label, policy.value)
        self.model_status_label = QLabel()
        self.device_status_label = QLabel("运行设备：正在检测 CUDA…")
        self.device_status_label.setWordWrap(True)
        self.refresh_device_button = QPushButton("刷新")
        self.refresh_device_button.setMaximumWidth(72)
        self.output_edit = QLineEdit()
        self.output_browse = QPushButton("浏览…")
        self.work_edit = QLineEdit()
        self.work_browse = QPushButton("浏览…")
        model_layout.addWidget(QLabel("ASR 模型"), 0, 0)
        model_layout.addWidget(self.asr_combo, 0, 1)
        model_layout.addWidget(QLabel("翻译模型"), 0, 2)
        model_layout.addWidget(self.translator_combo, 0, 3)
        model_layout.setColumnStretch(1, 1)
        model_layout.setColumnStretch(3, 1)
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
        path_layout.setHorizontalSpacing(8)
        path_layout.addWidget(QLabel("输出目录"), 0, 0)
        path_layout.addWidget(self.output_edit, 0, 1)
        path_layout.addWidget(self.output_browse, 0, 2)
        path_layout.addWidget(QLabel("工作目录"), 1, 0)
        path_layout.addWidget(self.work_edit, 1, 1)
        path_layout.addWidget(self.work_browse, 1, 2)
        path_layout.addWidget(QLabel("成功后清理"), 2, 0)
        path_layout.addWidget(self.cleanup_combo, 2, 1, 1, 2)
        path_layout.setColumnStretch(1, 1)
        settings_layout.addLayout(path_layout)

        common_group = QGroupBox("输出与性能")
        self.common_group = common_group
        common_layout = QGridLayout(common_group)
        self.recursive_check = QCheckBox("递归扫描子目录")
        self.bilingual_check = QCheckBox("生成双语 ASS")
        self.quality_check = QCheckBox("生成质量报告")
        self.resume_check = QCheckBox("复用已完成阶段（断点续跑）")
        self.resume_check.setToolTip("复用已存在的完整 WAV、日语 SRT 和中文翻译；更换模型或参数后应关闭。")
        self.copy_check = QCheckBox("复制最终字幕到视频目录")
        self.speaker_check = QCheckBox("按说话人性别着色")
        self.asr_batch_spin = QSpinBox()
        self.asr_batch_spin.setRange(1, 128)
        self.asr_batch_spin.setToolTip("影响 ASR 速度和显存占用；默认 24，显存不足时建议降到 16。")
        self.advanced_dialog = AdvancedSettingsDialog(self)
        self.context_spin = self.advanced_dialog.context_spin
        self.batch_spin = self.advanced_dialog.batch_spin
        self.wrap_spin = self.advanced_dialog.wrap_spin
        self.font_combo = self.advanced_dialog.font_combo
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
        performance_form = QFormLayout()
        performance_form.addRow("ASR 批大小", self.asr_batch_spin)
        common_layout.addLayout(performance_form, 2, 0, 1, 3)
        serial_note = QLabel("GPU 任务并行数：1（避免多个模型叠加占用显存）")
        serial_note.setStyleSheet("color: #666;")
        common_layout.addWidget(serial_note, 3, 0, 1, 3)

        self.advanced_button = QPushButton("高级字幕与翻译设置…")
        common_layout.addWidget(self.advanced_button, 4, 0, 1, 3)

        settings_container = QWidget()
        settings_container_layout = QVBoxLayout(settings_container)
        settings_container_layout.setContentsMargins(0, 0, 0, 0)
        settings_container_layout.addWidget(settings_group)
        settings_container_layout.addWidget(common_group)
        settings_container_layout.addStretch()

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(input_group)
        splitter.addWidget(settings_container)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([600, 650])
        outer.addWidget(splitter, 1)

        progress_row = QHBoxLayout()
        self.current_label = QLabel("等待任务")
        self.overall_progress = QProgressBar()
        self.overall_progress.setRange(0, 100)
        progress_row.addWidget(self.current_label)
        progress_row.addWidget(self.overall_progress, 1)
        outer.addLayout(progress_row)
        self.log_edit = QPlainTextEdit()
        self.log_edit.setReadOnly(True)
        self.log_edit.setMaximumBlockCount(5000)
        outer.addWidget(self.log_edit, 1)

        action_row = QHBoxLayout()
        self.start_button = QPushButton("开始处理")
        self.start_button.setObjectName("primaryButton")
        self.cancel_button = QPushButton("取消")
        self.cancel_button.setEnabled(False)
        self.retry_button = QPushButton("重试失败任务")
        self.open_output_button = QPushButton("打开输出目录")
        action_row.addStretch()
        for button in (self.start_button, self.cancel_button, self.retry_button, self.open_output_button):
            action_row.addWidget(button)
        outer.addLayout(action_row)
        self.setCentralWidget(central)

    def _connect_signals(self) -> None:
        self.add_files_button.clicked.connect(self._choose_files)
        self.add_folder_button.clicked.connect(self._choose_folder)
        self.remove_button.clicked.connect(self._remove_selected)
        self.clear_button.clicked.connect(self._clear_tasks)
        self.output_browse.clicked.connect(lambda: self._choose_directory(self.output_edit))
        self.work_browse.clicked.connect(lambda: self._choose_directory(self.work_edit))
        self.start_button.clicked.connect(self._start)
        self.cancel_button.clicked.connect(self.controller.cancel)
        self.retry_button.clicked.connect(self._retry_failed)
        self.open_output_button.clicked.connect(self._open_output)
        self.asr_combo.currentIndexChanged.connect(self._update_model_status)
        self.translator_combo.currentIndexChanged.connect(self._update_model_status)
        self.speaker_check.toggled.connect(self._update_model_status)
        self.advanced_button.clicked.connect(self._show_advanced_settings)
        self.refresh_device_button.clicked.connect(self._start_device_probe)
        for edit in (self.output_edit, self.work_edit):
            edit.textChanged.connect(edit.setToolTip)
        self._device_probe.finished.connect(self._device_probe_finished)
        self.controller.task_updated.connect(self._update_task_row)
        self.controller.log_received.connect(self._append_log)
        self.controller.overall_progress_changed.connect(self.overall_progress.setValue)
        self.controller.running_changed.connect(self._set_running)
        self.controller.queue_finished.connect(self._queue_finished)

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

    def _append_task_row(self, task: GuiTask) -> None:
        row = self.task_table.rowCount()
        self.task_table.insertRow(row)
        self._rows_by_id[task.task_id] = row
        self.task_table.setItem(row, 0, QTableWidgetItem(str(task.video)))
        self.task_table.setItem(row, 1, QTableWidgetItem(task.status_text))
        self.task_table.setItem(row, 2, QTableWidgetItem(f"{task.progress_percent}%"))
        self.task_table.setItem(row, 3, QTableWidgetItem(""))

    def _update_task_row(self, task: GuiTask) -> None:
        row = self._rows_by_id.get(task.task_id)
        if row is None:
            return
        self.task_table.item(row, 1).setText(task.status_text if not task.error else f"{task.status_text}：{task.error}")
        self.task_table.item(row, 2).setText(f"{task.progress_percent}%")
        output = task.outputs.get("ass") or task.outputs.get("srt")
        self.task_table.item(row, 3).setText(str(output) if output else "")
        if task.status == TaskStatus.RUNNING:
            self.current_label.setText(f"{task.video.name} — {task.status_text}")

    def _choose_files(self) -> None:
        names, _ = QFileDialog.getOpenFileNames(self, "选择视频", "", "视频文件 (*.mp4 *.mkv *.mov *.avi *.wmv *.flv *.webm *.m4v *.ts)")
        self.add_paths([Path(name) for name in names])

    def _choose_folder(self) -> None:
        name = QFileDialog.getExistingDirectory(self, "选择视频文件夹")
        if name:
            self.add_paths([Path(name)])

    def _choose_directory(self, target: QLineEdit) -> None:
        name = QFileDialog.getExistingDirectory(self, "选择目录", target.text())
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
        self.device_status_label.setText("运行设备：正在检测 CUDA…")
        self.device_status_label.setStyleSheet("color: #555;")
        self.refresh_device_button.setText("检测中…")
        probe_script = Path(__file__).with_name("device_probe.py")
        self._device_probe.start(sys.executable, [str(probe_script)])

    def _device_probe_finished(self, exit_code: int, _status: QProcess.ExitStatus) -> None:
        self.refresh_device_button.setText("刷新")
        if exit_code != 0:
            detail = bytes(self._device_probe.readAllStandardError()).decode("utf-8", errors="replace").strip()
            self.device_status_label.setText("运行设备：检测失败")
            self.device_status_label.setStyleSheet("color: #c0392b;")
            self.device_status_label.setToolTip(detail)
            return
        try:
            data = json.loads(bytes(self._device_probe.readAllStandardOutput()).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self.device_status_label.setText("运行设备：检测结果无法解析")
            self.device_status_label.setStyleSheet("color: #c0392b;")
            return
        torch_cuda = bool(data.get("torch_cuda"))
        onnx_cuda = bool(data.get("onnx_cuda"))
        llama_cuda = bool(data.get("llama_cuda"))
        parts = [f"ASR {'✓' if torch_cuda else '✗'}", f"语音切分 {'✓' if onnx_cuda else 'CPU'}", f"翻译 {'✓' if llama_cuda else 'CPU'}"]
        gpu_name = str(data.get("gpu_name") or "CUDA GPU")
        display_gpu_name = gpu_name.removeprefix("NVIDIA GeForce ")
        if torch_cuda and onnx_cuda and llama_cuda:
            text, colour = f"运行设备：CUDA · {display_gpu_name}（ASR ✓ / VAD ✓ / 翻译 ✓）", "#18864b"
        elif torch_cuda:
            text, colour = f"运行设备：部分 CUDA · {display_gpu_name}（{' / '.join(parts)}）", "#a56500"
        else:
            text, colour = f"运行设备：CUDA 不可用，ASR 无法启动（{' / '.join(parts)}）", "#c0392b"
        self.device_status_label.setText(text)
        self.device_status_label.setStyleSheet(f"color: {colour};")
        self.device_status_label.setToolTip(str(data.get("details") or ""))

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
            bilingual=self.bilingual_check.isChecked(),
            quality_report=self.quality_check.isChecked(),
            resume=self.resume_check.isChecked(),
            copy_to_video_dir=self.copy_check.isChecked(),
            cleanup_policy=CleanupPolicy(self.cleanup_combo.currentData()),
            asr_batch_size=self.asr_batch_spin.value(),
            context_size=self.context_spin.value(),
            translate_batch_size=self.batch_spin.value(),
            display_wrap_max_chars=self.wrap_spin.value() if self.advanced_dialog.wrap_check.isChecked() else 0,
            bilingual_font=self.font_combo.currentFont().family(),
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
            QMessageBox.information(self, "没有任务", "请先添加视频，或重试失败任务。")
            return
        config = self._config_from_ui()
        errors = config.validate()
        if errors:
            QMessageBox.warning(self, "参数错误", "\n".join(errors))
            return
        missing = missing_model_files(config)
        if missing:
            preview = "\n".join(str(path) for path in missing[:8])
            QMessageBox.warning(self, "模型不完整", f"所选模型缺少文件：\n{preview}")
            return
        self._save_settings()
        self.controller.start(self.tasks, config)

    def _retry_failed(self) -> None:
        if self.controller.is_running:
            return
        for task in self.tasks:
            if task.status in (TaskStatus.FAILED, TaskStatus.CANCELLED):
                task.reset_for_retry()
                self._update_task_row(task)

    def _open_output(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(self.output_edit.text()).expanduser().resolve())))

    def _update_model_status(self) -> None:
        config = self._config_from_ui()
        missing = missing_model_files(config)
        if missing:
            self.model_status_label.setText(f"缺少 {len(missing)} 个模型文件")
            self.model_status_label.setStyleSheet("color: #c0392b;")
            self.model_status_label.setToolTip("\n".join(str(path) for path in missing))
        else:
            self.model_status_label.setText("所选模型文件完整")
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

    def _restore_settings(self) -> None:
        defaults = GuiConfig()
        previous_version = self.settings.value("ui_settings_version", 0, int)
        migrate_common_defaults = previous_version < self.UI_SETTINGS_VERSION
        self.output_edit.setText(self.settings.value("output_dir", str(defaults.output_dir), str))
        self.work_edit.setText(self.settings.value("work_dir", str(defaults.work_dir), str))
        self._set_combo_value(self.asr_combo, self.settings.value("asr", defaults.asr.value, str))
        self._set_combo_value(self.translator_combo, self.settings.value("translator", defaults.translator.value, str))
        self._set_combo_value(self.cleanup_combo, self.settings.value("cleanup", defaults.cleanup_policy.value, str))
        self.recursive_check.setChecked(defaults.recursive if migrate_common_defaults else self.settings.value("recursive", defaults.recursive, bool))
        self.bilingual_check.setChecked(defaults.bilingual if migrate_common_defaults else self.settings.value("bilingual", defaults.bilingual, bool))
        self.quality_check.setChecked(self.settings.value("quality", defaults.quality_report, bool))
        self.resume_check.setChecked(defaults.resume if migrate_common_defaults else self.settings.value("resume", defaults.resume, bool))
        self.copy_check.setChecked(defaults.copy_to_video_dir if migrate_common_defaults else self.settings.value("copy", defaults.copy_to_video_dir, bool))
        self.speaker_check.setChecked(self.settings.value("speaker", defaults.colour_by_speaker, bool))
        self.asr_batch_spin.setValue(self.settings.value("asr_batch", defaults.asr_batch_size, int))
        self.context_spin.setValue(self.settings.value("context", defaults.context_size, int))
        self.batch_spin.setValue(self.settings.value("batch", defaults.translate_batch_size, int))
        wrap_value = self.settings.value("wrap", defaults.display_wrap_max_chars, int)
        self.advanced_dialog.wrap_check.setChecked(wrap_value > 0)
        self.wrap_spin.setValue(wrap_value or defaults.display_wrap_max_chars)
        self.font_combo.setCurrentFont(QFont(self.settings.value("font", defaults.bilingual_font, str)))
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

    def _save_settings(self) -> None:
        config = self._config_from_ui()
        values = {
            "output_dir": str(config.output_dir), "work_dir": str(config.work_dir),
            "asr": config.asr.value, "translator": config.translator.value,
            "cleanup": config.cleanup_policy.value, "recursive": config.recursive,
            "bilingual": config.bilingual, "quality": config.quality_report,
            "resume": config.resume, "copy": config.copy_to_video_dir,
            "speaker": config.colour_by_speaker, "context": config.context_size,
            "asr_batch": config.asr_batch_size,
            "batch": config.translate_batch_size, "wrap": config.display_wrap_max_chars,
            "font": config.bilingual_font, "zh_size": config.bilingual_zh_font_size,
            "ja_size": config.bilingual_ja_font_size,
            "zh_colour": config.bilingual_zh_colour, "ja_colour": config.bilingual_ja_colour,
            "male_colour": config.bilingual_male_colour, "female_colour": config.bilingual_female_colour,
        }
        for key, value in values.items():
            self.settings.setValue(key, value)
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("ui_settings_version", self.UI_SETTINGS_VERSION)

    @staticmethod
    def _set_combo_value(combo: QComboBox, value: str) -> None:
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.controller.is_running:
            answer = QMessageBox.question(self, "任务仍在运行", "取消当前任务并退出吗？")
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
        self.current_label.setText("队列处理结束")
        if self._close_when_finished:
            self._close_when_finished = False
            self.close()
