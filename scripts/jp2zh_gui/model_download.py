"""Modal model manager and subprocess controller for Hugging Face downloads."""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from urllib.parse import urlsplit

from PySide6.QtCore import (
    QObject,
    QProcess,
    QProcessEnvironment,
    QSettings,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from model_catalog import (
    MODEL_DOWNLOAD_ENDPOINTS,
    MODEL_DOWNLOAD_SPECS,
    MODEL_SPEC_BY_KEY,
    ModelInstallState,
    ModelDownloadSpec,
    model_install_state,
)
from portable_runtime import scripts_dir
from .models import PROJECT_ROOT
from .process_utils import hide_windows_console


DOWNLOAD_SCRIPT = scripts_dir(Path(__file__)) / "download_models.py"


class ModelDownloadController(QObject):
    event_received = Signal(object)
    log_received = Signal(str)
    finished = Signal(bool, bool)

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        python_executable: Path | str = sys.executable,
        download_script: Path = DOWNLOAD_SCRIPT,
    ) -> None:
        super().__init__(parent)
        self.python_executable = python_executable
        self.download_script = download_script
        self.process: QProcess | None = None
        self._stdout_buffer = b""
        self._cancel_requested = False
        self._finished_emitted = False

    @property
    def is_running(self) -> bool:
        return self.process is not None and self.process.state() != QProcess.ProcessState.NotRunning

    def start(
        self,
        keys: list[str],
        source: str,
        root: Path = PROJECT_ROOT,
        *,
        force: bool = False,
        proxy: str | None = None,
        download_backend: str = "auto",
    ) -> None:
        if self.is_running:
            raise RuntimeError("A model download is already running")
        if source not in MODEL_DOWNLOAD_ENDPOINTS:
            raise ValueError(f"Unknown model download source: {source}")
        if download_backend not in {"auto", "compat"}:
            raise ValueError(f"Unknown download backend: {download_backend}")
        command = [
            str(self.python_executable),
            str(self.download_script),
            "--root",
            str(root),
            "--source",
            source,
            "--download-backend",
            download_backend,
        ]
        for key in keys:
            command.extend(("--model", key))
        if force:
            command.append("--force")
        if proxy:
            command.extend(("--proxy", proxy))

        process = QProcess(self)
        hide_windows_console(process)
        process.setWorkingDirectory(str(root))
        process.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        environment = process.processEnvironment()
        if environment.isEmpty():
            environment = QProcessEnvironment.systemEnvironment()
        environment.remove("HF_HUB_OFFLINE")
        environment.remove("TRANSFORMERS_OFFLINE")
        environment.insert("PYTHONUTF8", "1")
        environment.insert("NO_COLOR", "1")
        if proxy:
            for name in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
                environment.insert(name, proxy)
        process.setProcessEnvironment(environment)
        process.readyReadStandardOutput.connect(self._read_stdout)
        process.readyReadStandardError.connect(self._read_stderr)
        process.finished.connect(self._process_finished)
        process.errorOccurred.connect(self._process_error)
        self.process = process
        self._stdout_buffer = b""
        self._cancel_requested = False
        self._finished_emitted = False
        process.start(command[0], command[1:])

    def cancel(self) -> None:
        if not self.is_running or self.process is None:
            return
        self._cancel_requested = True
        self.process.terminate()
        QTimer.singleShot(2500, self._kill_if_running)

    def _kill_if_running(self) -> None:
        if self.is_running and self.process is not None:
            self.process.kill()

    def _read_stdout(self) -> None:
        if self.process is None:
            return
        data = self._stdout_buffer + bytes(self.process.readAllStandardOutput())
        chunks = data.split(b"\n")
        self._stdout_buffer = chunks.pop()
        for raw in chunks:
            self._apply_stdout_line(raw)

    def _apply_stdout_line(self, raw: bytes) -> None:
        if not raw:
            return
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self.log_received.emit(raw.decode("utf-8", errors="replace") + "\n")
            return
        self.event_received.emit(payload)

    def _read_stderr(self) -> None:
        if self.process is None:
            return
        data = bytes(self.process.readAllStandardError())
        if data:
            self.log_received.emit(data.decode("utf-8", errors="replace"))

    def _process_finished(
        self,
        exit_code: int,
        exit_status: QProcess.ExitStatus,
    ) -> None:
        if self._finished_emitted:
            return
        self._finished_emitted = True
        self._read_stdout()
        if self._stdout_buffer:
            self._apply_stdout_line(self._stdout_buffer)
            self._stdout_buffer = b""
        self._read_stderr()
        cancelled = self._cancel_requested
        success = (
            not cancelled
            and exit_status == QProcess.ExitStatus.NormalExit
            and exit_code == 0
        )
        process = self.process
        self.process = None
        if process is not None:
            process.deleteLater()
        self.finished.emit(success, cancelled)

    def _process_error(self, error: QProcess.ProcessError) -> None:
        if (
            error != QProcess.ProcessError.FailedToStart
            or self._finished_emitted
        ):
            return
        self._finished_emitted = True
        self.event_received.emit(
            {
                "type": "error",
                "phase": "startup",
                "error_type": "FailedToStart",
                "message": self.tr("Could not start the model downloader."),
            }
        )
        process = self.process
        self.process = None
        if process is not None:
            process.deleteLater()
        self.finished.emit(False, False)


class ModelDownloadDialog(QDialog):
    models_changed = Signal()

    def __init__(
        self,
        parent: QWidget | None,
        *,
        current_model_keys: tuple[str, ...],
        settings: QSettings,
        root: Path = PROJECT_ROOT,
        controller: ModelDownloadController | None = None,
    ) -> None:
        super().__init__(parent)
        self.settings = settings
        self.root = root
        self.current_model_keys = set(current_model_keys)
        self.controller = controller or ModelDownloadController(self)
        self._rows_by_key: dict[str, int] = {}
        self._failed_key: str | None = None
        self._error_reported = False
        self._close_after_cancel = False
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setMinimumSize(820, 560)
        self.resize(900, 620)
        self._build_ui()
        self._connect_signals()
        self._populate_rows()
        self.retranslate_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        source_layout = QGridLayout()
        self.source_label = QLabel()
        self.source_label.setMinimumWidth(110)
        self.source_combo = QComboBox()
        self.source_combo.setMinimumWidth(190)
        self.source_combo.addItem("", "official")
        self.source_combo.addItem("", "mirror")
        source = self.settings.value("model_download_source", "official", str)
        index = self.source_combo.findData(source)
        self.source_combo.setCurrentIndex(index if index >= 0 else 0)
        self.proxy_check = QCheckBox()
        self.proxy_edit = QLineEdit()
        self.proxy_edit.setMinimumWidth(210)
        self.proxy_edit.setText(
            self.settings.value(
                "model_download_proxy_url",
                "http://127.0.0.1:7890",
                str,
            )
        )
        proxy_enabled = self.settings.value(
            "model_download_proxy_enabled",
            False,
            bool,
        )
        self.proxy_check.setChecked(proxy_enabled)
        self.proxy_edit.setEnabled(proxy_enabled)
        self.native_backend_check = QCheckBox()
        self.native_backend_check.setChecked(
            self.settings.value(
                "model_download_prefer_native",
                True,
                bool,
            )
        )
        self.source_note = QLabel()
        self.source_note.setStyleSheet("color: #8a5a00;")
        source_layout.addWidget(self.source_label, 0, 0)
        source_layout.addWidget(self.source_combo, 0, 1)
        source_layout.addWidget(self.proxy_check, 0, 2)
        source_layout.addWidget(self.proxy_edit, 0, 3)
        source_layout.addWidget(self.native_backend_check, 1, 1, 1, 2)
        source_layout.addWidget(self.source_note, 1, 3)
        source_layout.setColumnStretch(3, 1)
        layout.addLayout(source_layout)

        self.table = QTableWidget(0, 5)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(34)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.table, 1)

        selection_row = QHBoxLayout()
        self.select_current_button = QPushButton()
        self.select_missing_button = QPushButton()
        self.delete_button = QPushButton()
        self.delete_button.setStyleSheet("color: #b42318;")
        selection_row.addWidget(self.select_current_button)
        selection_row.addWidget(self.select_missing_button)
        selection_row.addStretch()
        selection_row.addWidget(self.delete_button)
        layout.addLayout(selection_row)

        progress_grid = QGridLayout()
        self.queue_status_label = QLabel()
        self.current_status_label = QLabel()
        self.overall_progress = QProgressBar()
        self.model_progress = QProgressBar()
        self.transfer_label = QLabel()
        progress_grid.addWidget(self.queue_status_label, 0, 0)
        progress_grid.addWidget(self.overall_progress, 0, 1)
        progress_grid.addWidget(self.current_status_label, 1, 0)
        progress_grid.addWidget(self.model_progress, 1, 1)
        progress_grid.addWidget(self.transfer_label, 2, 1)
        progress_grid.setColumnStretch(1, 1)
        layout.addLayout(progress_grid)

        self.details_button = QPushButton()
        self.details_button.setCheckable(True)
        self.log_edit = QPlainTextEdit()
        self.log_edit.setReadOnly(True)
        self.log_edit.setMaximumBlockCount(3000)
        self.log_edit.setVisible(False)
        layout.addWidget(self.details_button, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self.log_edit)

        buttons = QHBoxLayout()
        buttons.addStretch()
        self.start_button = QPushButton()
        self.start_button.setObjectName("primaryButton")
        self.redownload_button = QPushButton()
        self.cancel_button = QPushButton()
        self.close_button = QPushButton()
        self.cancel_button.setEnabled(False)
        buttons.addWidget(self.start_button)
        buttons.addWidget(self.redownload_button)
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.close_button)
        layout.addLayout(buttons)

    def _connect_signals(self) -> None:
        self.source_combo.currentIndexChanged.connect(self._source_changed)
        self.proxy_check.toggled.connect(self._proxy_setting_changed)
        self.proxy_edit.textChanged.connect(self._proxy_setting_changed)
        self.native_backend_check.toggled.connect(
            self._download_backend_setting_changed
        )
        self.select_current_button.clicked.connect(self._select_current_models)
        self.select_missing_button.clicked.connect(self._select_all_missing)
        self.delete_button.clicked.connect(self._delete_selected)
        self.start_button.clicked.connect(lambda: self._start_download(force=False))
        self.redownload_button.clicked.connect(
            lambda: self._start_download(force=True)
        )
        self.cancel_button.clicked.connect(self._cancel_download)
        self.close_button.clicked.connect(self.reject)
        self.details_button.toggled.connect(self.log_edit.setVisible)
        self.controller.event_received.connect(self._apply_event)
        self.controller.log_received.connect(self._append_log)
        self.controller.finished.connect(self._download_finished)

    def _populate_rows(self) -> None:
        self.table.setRowCount(len(MODEL_DOWNLOAD_SPECS))
        for row, spec in enumerate(MODEL_DOWNLOAD_SPECS):
            self._rows_by_key[spec.key] = row
            check_item = QTableWidgetItem()
            check_item.setData(Qt.ItemDataRole.UserRole, spec.key)
            self.table.setItem(row, 0, check_item)
            self.table.setItem(row, 1, QTableWidgetItem(spec.name))
            self.table.setItem(row, 2, QTableWidgetItem())
            self.table.setItem(row, 3, QTableWidgetItem())
            size_item = QTableWidgetItem("—")
            size_item.setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            self.table.setItem(row, 4, size_item)
        self._refresh_rows(initial=True)

    def _refresh_rows(self, *, initial: bool = False) -> None:
        for spec in MODEL_DOWNLOAD_SPECS:
            row = self._rows_by_key[spec.key]
            state = model_install_state(spec, self.root)
            check_item = self.table.item(row, 0)
            check_item.setFlags(
                Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable
            )
            if initial:
                selected = (
                    spec.key in self.current_model_keys
                    and state != ModelInstallState.INSTALLED
                )
                check_item.setCheckState(
                    Qt.CheckState.Checked
                    if selected
                    else Qt.CheckState.Unchecked
                )
            elif check_item.checkState() not in (
                Qt.CheckState.Checked,
                Qt.CheckState.Unchecked,
            ):
                check_item.setCheckState(Qt.CheckState.Unchecked)
            status = "failed" if spec.key == self._failed_key else state.value
            self.table.item(row, 3).setText(self._status_text(status))

    def _selected_keys(self) -> list[str]:
        return [
            spec.key
            for spec in MODEL_DOWNLOAD_SPECS
            if self.table.item(self._rows_by_key[spec.key], 0).checkState()
            == Qt.CheckState.Checked
        ]

    def _select_current_models(self) -> None:
        self._set_checked_keys(self.current_model_keys)

    def _select_all_missing(self) -> None:
        keys = {
            spec.key
            for spec in MODEL_DOWNLOAD_SPECS
            if model_install_state(spec, self.root) != ModelInstallState.INSTALLED
        }
        self._set_checked_keys(keys)

    def _set_checked_keys(self, keys: set[str]) -> None:
        for spec in MODEL_DOWNLOAD_SPECS:
            checked = spec.key in keys
            self.table.item(self._rows_by_key[spec.key], 0).setCheckState(
                Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
            )

    def _source_changed(self) -> None:
        source = str(self.source_combo.currentData())
        self.settings.setValue("model_download_source", source)
        self._refresh_source_note()

    def _proxy_setting_changed(self) -> None:
        enabled = self.proxy_check.isChecked()
        self.proxy_edit.setEnabled(enabled and not self.controller.is_running)
        self.settings.setValue("model_download_proxy_enabled", enabled)
        self.settings.setValue(
            "model_download_proxy_url",
            self.proxy_edit.text().strip(),
        )

    def _download_backend_setting_changed(self, checked: bool) -> None:
        self.settings.setValue("model_download_prefer_native", checked)

    def _validated_proxy(self) -> str | None:
        if not self.proxy_check.isChecked():
            return None
        value = self.proxy_edit.text().strip()
        parsed = urlsplit(value)
        try:
            port = parsed.port
        except ValueError as exc:
            raise ValueError(self.tr("The proxy port is invalid.")) from exc
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or port is None
            or parsed.username
            or parsed.password
        ):
            raise ValueError(
                self.tr(
                    "Enter an HTTP proxy such as http://127.0.0.1:7890 "
                    "without a username or password."
                )
            )
        return value

    def _start_download(self, *, force: bool) -> None:
        keys = self._selected_keys()
        if not keys:
            QMessageBox.information(
                self,
                self.tr("No models selected"),
                self.tr("Select at least one missing or partial model first."),
            )
            return
        if not force:
            keys = [
                key
                for key in keys
                if model_install_state(
                    MODEL_SPEC_BY_KEY[key],
                    self.root,
                )
                != ModelInstallState.INSTALLED
            ]
            if not keys:
                QMessageBox.information(
                    self,
                    self.tr("Models already installed"),
                    self.tr(
                        "The selected models are already installed. "
                        "Use Re-download selected to replace them."
                    ),
                )
                return
        try:
            proxy = self._validated_proxy()
        except ValueError as exc:
            QMessageBox.warning(
                self,
                self.tr("Invalid proxy"),
                str(exc),
            )
            return
        self._failed_key = None
        self._error_reported = False
        self.log_edit.clear()
        self._append_log(
            self.tr("Source: {source}").format(
                source=self.source_combo.currentText()
            )
        )
        self._append_log(
            self.tr("Proxy: {proxy}").format(proxy=proxy)
            if proxy
            else self.tr("Proxy: disabled")
        )
        self._append_log(
            self.tr("Mode: re-download and replace")
            if force
            else self.tr("Mode: download missing or partial models")
        )
        self._append_log(
            self.tr("Selected models: {models}").format(
                models=", ".join(self._model_name(key) for key in keys)
            )
        )
        self._append_log(
            self.tr(
                "Download mode: prefer Hugging Face/Xet with compatibility fallback"
            )
            if self.native_backend_check.isChecked()
            else self.tr("Download mode: compatibility HTTP only")
        )
        self.queue_status_label.setStyleSheet("")
        self.current_status_label.clear()
        self.overall_progress.setRange(0, 0)
        self.model_progress.setRange(0, 0)
        self.transfer_label.clear()
        self._refresh_rows()
        self._set_running(True)
        self.controller.start(
            keys,
            str(self.source_combo.currentData()),
            self.root,
            force=force,
            proxy=proxy,
            download_backend=(
                "auto"
                if self.native_backend_check.isChecked()
                else "compat"
            ),
        )

    def _delete_selected(self) -> None:
        specs = [
            spec
            for spec in MODEL_DOWNLOAD_SPECS
            if spec.key in self._selected_keys()
            and spec.destination(self.root).exists()
        ]
        if not specs:
            QMessageBox.information(
                self,
                self.tr("Nothing to delete"),
                self.tr("None of the selected models has local files."),
            )
            return
        names = "\n".join(f"• {spec.name}" for spec in specs)
        answer = QMessageBox.warning(
            self,
            self.tr("Delete selected models"),
            self.tr(
                "Permanently delete these models, including cached and partial files?\n\n"
                "{models}"
            ).format(models=names),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        failures: list[str] = []
        deleted: set[str] = set()
        for spec in specs:
            try:
                destination = self._safe_model_destination(spec)
                if not destination.is_dir() or destination.is_symlink():
                    raise RuntimeError(self.tr("Model path is not a normal directory"))
                shutil.rmtree(destination)
                deleted.add(spec.key)
            except Exception as exc:
                failures.append(f"{spec.name}: {exc}")
        self._set_checked_keys(set(self._selected_keys()).difference(deleted))
        self._failed_key = None
        self._refresh_rows()
        self.models_changed.emit()
        if failures:
            QMessageBox.critical(
                self,
                self.tr("Could not delete some models"),
                "\n".join(failures),
            )
            return
        self.queue_status_label.setText(
            self.tr("{count} models deleted").format(count=len(deleted))
        )
        self.queue_status_label.setStyleSheet("color: #18864b;")

    def _safe_model_destination(self, spec: ModelDownloadSpec) -> Path:
        models_root = (self.root / "models").resolve()
        destination = spec.destination(self.root)
        resolved = destination.resolve()
        if resolved == models_root or not resolved.is_relative_to(models_root):
            raise RuntimeError(self.tr("Refusing to delete a path outside the models folder"))
        return destination

    def _cancel_download(self) -> None:
        if not self.controller.is_running:
            return
        self.queue_status_label.setText(self.tr("Cancelling; partial files will be kept…"))
        self.cancel_button.setEnabled(False)
        self.controller.cancel()

    def _set_running(self, running: bool) -> None:
        self.source_combo.setEnabled(not running)
        self.proxy_check.setEnabled(not running)
        self.proxy_edit.setEnabled(not running and self.proxy_check.isChecked())
        self.native_backend_check.setEnabled(not running)
        self.table.setEnabled(not running)
        self.select_current_button.setEnabled(not running)
        self.select_missing_button.setEnabled(not running)
        self.delete_button.setEnabled(not running)
        self.start_button.setEnabled(not running)
        self.redownload_button.setEnabled(not running)
        self.cancel_button.setEnabled(running)

    def _apply_event(self, payload: dict[str, object]) -> None:
        event = str(payload.get("type") or "")
        key = str(payload.get("model") or "")
        if event == "model_query_started":
            self._set_model_status(key, "querying")
        elif event == "model_queued":
            self._set_model_status(key, str(payload.get("state") or "missing"))
            self._set_model_size(key, payload.get("total_bytes"))
        elif event == "model_skipped":
            self._set_model_status(key, "installed")
        elif event == "queue_started":
            count = int(payload.get("model_count") or 0)
            self.queue_status_label.setText(
                self.tr("{count} models queued").format(count=count)
            )
            self._set_progress_range(self.overall_progress, payload.get("overall_total_bytes"))
        elif event == "model_started":
            index = int(payload.get("index") or 0)
            count = int(payload.get("count") or 0)
            name = self._model_name(key)
            self.current_status_label.setText(
                self.tr("Downloading {model} ({current}/{total})").format(
                    model=name,
                    current=index,
                    total=count,
                )
            )
            self._set_model_status(key, "downloading")
            self._set_progress_range(self.model_progress, payload.get("total_bytes"))
        elif event == "progress":
            self._update_progress(payload)
        elif event == "model_completed":
            self._set_model_status(key, "installed")
        elif event == "error":
            self._error_reported = True
            self._failed_key = key or None
            if key:
                self._set_model_status(key, "failed")
            message = str(payload.get("message") or self.tr("Unknown download error"))
            self.queue_status_label.setText(self.tr("Download failed: {error}").format(error=message))
            self.queue_status_label.setStyleSheet("color: #c0392b;")
            self.details_button.setChecked(True)
        elif event == "finished":
            completed = int(payload.get("completed") or 0)
            self.queue_status_label.setText(
                self.tr("{count} models downloaded successfully").format(count=completed)
            )
            self.queue_status_label.setStyleSheet("color: #18864b;")
        self._append_event_detail(payload)

    def _append_event_detail(self, payload: dict[str, object]) -> None:
        event = str(payload.get("type") or "")
        key = str(payload.get("model") or "")
        model = self._model_name(key) if key else ""
        if event == "started":
            self._append_log(self.tr("Download helper started."))
        elif event == "model_query_started":
            self._append_log(
                self.tr("Querying metadata: {model}").format(model=model)
            )
        elif event == "model_queued":
            size = payload.get("total_bytes")
            size_text = (
                self._format_bytes(int(size))
                if size is not None
                else self.tr("unknown")
            )
            self._append_log(
                self.tr("Queued: {model} ({size})").format(
                    model=model,
                    size=size_text,
                )
            )
        elif event == "model_skipped":
            self._append_log(
                self.tr("Skipped installed model: {model}").format(model=model)
            )
        elif event == "model_started":
            self._append_log(
                self.tr("Downloading: {model}").format(model=model)
            )
        elif event == "model_completed":
            self._append_log(
                self.tr("Completed: {model}").format(model=model)
            )
        elif event == "error":
            self._append_log(
                self.tr("Error: {error}").format(
                    error=str(payload.get("message") or ""),
                )
            )
        elif event == "finished":
            self._append_log(self.tr("Download queue completed."))

    def _update_progress(self, payload: dict[str, object]) -> None:
        downloaded = int(payload.get("downloaded_bytes") or 0)
        total = payload.get("total_bytes")
        overall_downloaded = int(payload.get("overall_downloaded_bytes") or 0)
        overall_total = payload.get("overall_total_bytes")
        speed = int(payload.get("speed_bytes_per_second") or 0)
        self._set_progress_value(self.model_progress, downloaded, total)
        self._set_progress_value(self.overall_progress, overall_downloaded, overall_total)
        total_text = self._format_bytes(int(total)) if total is not None else self.tr("unknown")
        self.transfer_label.setText(
            self.tr("{downloaded} / {total} · average {speed}/s").format(
                downloaded=self._format_bytes(downloaded),
                total=total_text,
                speed=self._format_bytes(speed),
            )
        )

    def _download_finished(self, success: bool, cancelled: bool) -> None:
        self._set_running(False)
        self._refresh_rows()
        self.models_changed.emit()
        if cancelled:
            self.queue_status_label.setText(self.tr("Download cancelled; partial files were kept."))
            self.queue_status_label.setStyleSheet("color: #8a5a00;")
        elif not success and not self._error_reported:
            self.queue_status_label.setText(self.tr("Model download failed."))
            self.queue_status_label.setStyleSheet("color: #c0392b;")
        if self._close_after_cancel:
            self._close_after_cancel = False
            super().reject()

    def _set_model_status(self, key: str, status: str) -> None:
        row = self._rows_by_key.get(key)
        if row is not None:
            self.table.item(row, 3).setText(self._status_text(status))

    def _set_model_size(self, key: str, value: object) -> None:
        row = self._rows_by_key.get(key)
        if row is not None and value is not None:
            self.table.item(row, 4).setText(self._format_bytes(int(value)))

    def _model_name(self, key: str) -> str:
        return next((spec.name for spec in MODEL_DOWNLOAD_SPECS if spec.key == key), key)

    def _purpose_text(self, key: str) -> str:
        purposes = {
            "anime-whisper": self.tr("Anime speech recognition"),
            "whisperseg": self.tr("Speech segmentation"),
            "qwen-forced-aligner": self.tr("Subtitle timestamp alignment"),
            "galtransl-7b": self.tr("Recommended Chinese translation"),
            "qwen-asr-1.7b": self.tr("Optional Qwen speech recognition"),
            "sakura-14b": self.tr("Optional Chinese translation"),
            "sugoi-14b": self.tr("Experimental English translation"),
            "speaker-gender": self.tr("Optional speaker colouring"),
        }
        return purposes.get(key, self.tr("Model download"))

    @staticmethod
    def _set_progress_range(bar: QProgressBar, total: object) -> None:
        if total is None:
            bar.setRange(0, 0)
        else:
            bar.setRange(0, 1000)
            bar.setValue(0)

    @staticmethod
    def _set_progress_value(bar: QProgressBar, value: int, total: object) -> None:
        if total is None or int(total) <= 0:
            bar.setRange(0, 0)
            return
        bar.setRange(0, 1000)
        bar.setValue(min(1000, round(1000 * value / int(total))))

    @staticmethod
    def _format_bytes(value: int) -> str:
        size = float(max(0, value))
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if size < 1024 or unit == "TB":
                return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"

    def _status_text(self, status: str) -> str:
        return {
            "installed": self.tr("Installed"),
            "partial": self.tr("Partial; resumable"),
            "missing": self.tr("Missing"),
            "querying": self.tr("Querying…"),
            "downloading": self.tr("Downloading…"),
            "failed": self.tr("Failed"),
        }.get(status, status)

    def _append_log(self, text: str) -> None:
        self.log_edit.appendPlainText(text.rstrip())

    def _refresh_source_note(self) -> None:
        self.source_note.setText(
            self.tr("Third-party mirror; do not use a private access token.")
            if self.source_combo.currentData() == "mirror"
            else ""
        )

    def retranslate_ui(self) -> None:
        self.setWindowTitle(self.tr("Model manager"))
        self.source_label.setText(self.tr("Download source"))
        self.source_combo.setItemText(
            self.source_combo.findData("official"),
            self.tr("Hugging Face official"),
        )
        self.source_combo.setItemText(
            self.source_combo.findData("mirror"),
            self.tr("HF-Mirror (third-party)"),
        )
        self.proxy_check.setText(self.tr("Use proxy"))
        self.proxy_edit.setPlaceholderText("http://127.0.0.1:7890")
        self.proxy_edit.setToolTip(
            self.tr(
                "Optional HTTP proxy used only by model downloads, "
                "for example http://127.0.0.1:7890."
            )
        )
        self.native_backend_check.setText(
            self.tr("Prefer Hugging Face/Xet (recommended)")
        )
        self.native_backend_check.setToolTip(
            self.tr(
                "Turn this off to use resumable compatibility HTTP directly."
            )
        )
        self.table.setHorizontalHeaderLabels(
            [
                self.tr("Download"),
                self.tr("Model"),
                self.tr("Purpose"),
                self.tr("Status"),
                self.tr("Size"),
            ]
        )
        for spec in MODEL_DOWNLOAD_SPECS:
            row = self._rows_by_key[spec.key]
            self.table.item(row, 2).setText(self._purpose_text(spec.key))
        self.select_current_button.setText(self.tr("Select current configuration"))
        self.select_missing_button.setText(self.tr("Select all missing"))
        self.delete_button.setText(self.tr("Delete selected…"))
        self.queue_status_label.setText(self.tr("Ready"))
        self.current_status_label.setText(self.tr("Current model"))
        self.details_button.setText(self.tr("Show download details"))
        if not self.log_edit.toPlainText():
            self.log_edit.setPlainText(
                self.tr("Download details will appear after a task starts.")
            )
        self.start_button.setText(self.tr("Download selected"))
        self.redownload_button.setText(self.tr("Re-download selected"))
        self.cancel_button.setText(self.tr("Cancel download"))
        self.close_button.setText(self.tr("Close"))
        self._refresh_source_note()
        self._refresh_rows()

    def reject(self) -> None:
        if not self.controller.is_running:
            super().reject()
            return
        answer = QMessageBox.question(
            self,
            self.tr("Cancel model download"),
            self.tr("Cancel the current download, keep partial files, and close this window?"),
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._close_after_cancel = True
        self._cancel_download()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt virtual method
        if self.controller.is_running:
            event.ignore()
            self.reject()
            return
        super().closeEvent(event)
