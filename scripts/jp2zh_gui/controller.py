"""QProcess controller bridging the GUI queue to the existing pipeline CLI."""
from __future__ import annotations

import json
import shutil
import sys
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QObject, QProcess, QTimer, Signal

from .models import GuiConfig, GuiTask, PIPELINE_SCRIPT, PROJECT_ROOT, TaskStatus
from .process_utils import hide_windows_console


class PipelineController(QObject):
    task_updated = Signal(object)
    log_received = Signal(str)
    overall_progress_changed = Signal(int)
    running_changed = Signal(bool)
    queue_finished = Signal()

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        pipeline_script: Path = PIPELINE_SCRIPT,
        python_executable: Path | str = sys.executable,
    ) -> None:
        super().__init__(parent)
        self.pipeline_script = pipeline_script
        self.python_executable = python_executable
        self.tasks: list[GuiTask] = []
        self.config = GuiConfig()
        self.process: QProcess | None = None
        self.current_task: GuiTask | None = None
        self.event_path: Path | None = None
        self.cancel_path: Path | None = None
        self._event_offset = 0
        self._event_buffer = b""
        self._stop_after_current = False
        self._runtime_dir: Path | None = None
        self._event_timer = QTimer(self)
        self._event_timer.setInterval(100)
        self._event_timer.timeout.connect(self._read_events)

    @property
    def is_running(self) -> bool:
        return self.process is not None and self.process.state() != QProcess.ProcessState.NotRunning

    def start(self, tasks: list[GuiTask], config: GuiConfig) -> None:
        if self.is_running:
            raise RuntimeError("Pipeline queue is already running")
        self.tasks = tasks
        self.config = replace(config)
        self._stop_after_current = False
        self._runtime_dir = config.work_dir / ".gui" / uuid4().hex
        self._runtime_dir.mkdir(parents=True, exist_ok=True)
        self.running_changed.emit(True)
        self._start_next_task()

    def cancel(self) -> None:
        if not self.is_running or self.cancel_path is None:
            return
        self._stop_after_current = True
        try:
            self.cancel_path.parent.mkdir(parents=True, exist_ok=True)
            self.cancel_path.touch(exist_ok=True)
        except OSError as exc:
            self.log_received.emit("\n" + self.tr("Could not write cancellation file: {error}").format(error=exc) + "\n")
            return
        self.log_received.emit("\n" + self.tr("Cancellation requested; waiting for the current stage to exit safely…") + "\n")

    def _start_next_task(self) -> None:
        if self._stop_after_current:
            self._finish_queue()
            return
        task = next((item for item in self.tasks if item.status == TaskStatus.WAITING), None)
        if task is None:
            self._finish_queue()
            return

        assert self._runtime_dir is not None
        self.current_task = task
        task.status = TaskStatus.RUNNING
        task.error = ""
        task.error_key = ""
        task.error_args.clear()
        task.stage = None
        task.stage_index = 0
        task.completed_stages = 0
        task.detail_key = ""
        task.detail_args.clear()
        self.event_path = self._runtime_dir / f"{task.task_id}.events.jsonl"
        self.cancel_path = self._runtime_dir / f"{task.task_id}.cancel.requested"
        self.event_path.unlink(missing_ok=True)
        self.cancel_path.unlink(missing_ok=True)
        self._event_offset = 0
        self._event_buffer = b""
        self.task_updated.emit(task)
        self._emit_overall_progress()

        command = self.config.build_command(
            task.video,
            self.event_path,
            self.cancel_path,
            python_executable=self.python_executable,
            pipeline_script=self.pipeline_script,
        )
        process = QProcess(self)
        hide_windows_console(process)
        process.setWorkingDirectory(str(PROJECT_ROOT))
        process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        process.readyReadStandardOutput.connect(self._read_process_output)
        process.finished.connect(self._process_finished)
        process.errorOccurred.connect(self._process_error)
        self.process = process
        self._event_timer.start()
        self.log_received.emit("\n" + self.tr("▶ Starting: {video}").format(video=task.video) + "\n")
        process.start(command[0], command[1:])

    def _read_process_output(self) -> None:
        if self.process is None:
            return
        data = bytes(self.process.readAllStandardOutput())
        if data:
            self.log_received.emit(data.decode("utf-8", errors="replace"))

    def _read_events(self) -> None:
        if self.event_path is None or not self.event_path.exists():
            return
        try:
            with self.event_path.open("rb") as handle:
                handle.seek(self._event_offset)
                data = handle.read()
                self._event_offset = handle.tell()
        except OSError:
            return
        if not data:
            return
        chunks = (self._event_buffer + data).split(b"\n")
        self._event_buffer = chunks.pop()
        for raw_line in chunks:
            if not raw_line:
                continue
            try:
                payload = json.loads(raw_line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                self.log_received.emit("\n" + self.tr("Could not parse pipeline event: {error}").format(error=exc) + "\n")
                continue
            self._apply_event(payload)

    def _apply_event(self, payload: dict) -> None:
        task = self.current_task
        if task is None:
            return
        event = payload.get("event")
        if event == "stage_started":
            task.stage = payload.get("stage")
            task.stage_index = int(payload.get("stage_index", task.stage_index))
            task.stage_total = int(payload.get("stage_total", task.stage_total))
            task.stage_progress = 0.0
            task.detail_key = str(payload.get("status_key") or "")
            task.detail_args = dict(payload.get("status_args") or {})
            task.detail = str(payload.get("status") or "")
        elif event == "stage_progress":
            task.stage = payload.get("stage", task.stage)
            task.stage_index = int(payload.get("stage_index", task.stage_index))
            task.stage_total = int(payload.get("stage_total", task.stage_total))
            task.stage_progress = max(
                task.stage_progress,
                min(1.0, max(0.0, float(payload.get("progress", task.stage_progress)))),
            )
            task.detail_key = str(payload.get("status_key") or task.detail_key)
            task.detail_args = dict(payload.get("status_args") or task.detail_args)
            task.detail = str(payload.get("status") or task.detail)
        elif event in ("stage_completed", "stage_skipped"):
            task.stage = payload.get("stage")
            task.stage_index = int(payload.get("stage_index", task.stage_index))
            task.stage_total = int(payload.get("stage_total", task.stage_total))
            task.completed_stages = max(task.completed_stages, task.stage_index)
            task.stage_progress = 1.0
            task.detail_key = str(payload.get("status_key") or "")
            task.detail_args = dict(payload.get("status_args") or {})
            task.detail = str(payload.get("status") or "")
        elif event == "stage_failed":
            task.error_key = "stage_failed"
            task.error = str(payload.get("error") or "")
        elif event == "stage_cancelled":
            task.status = TaskStatus.CANCELLED
        elif event == "job_completed":
            task.outputs = {key: Path(value) for key, value in payload.get("outputs", {}).items()}
        elif event == "job_failed":
            task.error_key = "job_failed"
            task.error = str(payload.get("error") or "")
        self.task_updated.emit(task)
        self._emit_overall_progress()

    def _process_finished(self, exit_code: int, exit_status: QProcess.ExitStatus) -> None:
        self._read_process_output()
        self._read_events()
        self._event_timer.stop()
        task = self.current_task
        if task is not None:
            if exit_status == QProcess.ExitStatus.CrashExit:
                task.status = TaskStatus.FAILED
                if not task.error:
                    task.error_key = "process_crashed"
            elif exit_code == 0:
                task.status = TaskStatus.COMPLETED
                task.completed_stages = task.stage_total
                task.stage_progress = 1.0
            elif exit_code == 130 or self._stop_after_current:
                task.status = TaskStatus.CANCELLED
            else:
                task.status = TaskStatus.FAILED
                if not task.error:
                    task.error_key = "exit_code"
                    task.error_args = {"code": exit_code}
            self.task_updated.emit(task)
        self.process = None
        process = self.sender()
        if isinstance(process, QProcess):
            process.deleteLater()
        self.current_task = None
        self._emit_overall_progress()
        QTimer.singleShot(0, self._start_next_task)

    def _process_error(self, error: QProcess.ProcessError) -> None:
        if error != QProcess.ProcessError.FailedToStart or self.current_task is None:
            return
        task = self.current_task
        task.status = TaskStatus.FAILED
        task.error_key = "failed_to_start"
        self.task_updated.emit(task)
        self._event_timer.stop()
        if self.process is not None:
            self.process.deleteLater()
        self.process = None
        self.current_task = None
        self._emit_overall_progress()
        QTimer.singleShot(0, self._start_next_task)

    def _emit_overall_progress(self) -> None:
        if not self.tasks:
            self.overall_progress_changed.emit(0)
            return
        total = sum(task.progress_percent for task in self.tasks)
        self.overall_progress_changed.emit(round(total / len(self.tasks)))

    def _finish_queue(self) -> None:
        self._event_timer.stop()
        self.process = None
        self.current_task = None
        self._cleanup_runtime_dir()
        self.running_changed.emit(False)
        self._emit_overall_progress()
        self.queue_finished.emit()

    def _cleanup_runtime_dir(self) -> None:
        runtime_dir = self._runtime_dir
        self._runtime_dir = None
        self.event_path = None
        self.cancel_path = None
        if runtime_dir is None:
            return
        try:
            shutil.rmtree(runtime_dir)
        except FileNotFoundError:
            pass
        except OSError as exc:
            self.log_received.emit("\n" + self.tr("Could not clean GUI runtime files: {error}").format(error=exc) + "\n")
