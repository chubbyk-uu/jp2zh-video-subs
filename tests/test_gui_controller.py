import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from jp2zh_gui.controller import PipelineController
from jp2zh_gui.models import GuiConfig, GuiTask, TaskStatus


def application():
    return QApplication.instance() or QApplication([])


def wait_for_queue(controller: PipelineController, timeout_ms: int = 5000) -> bool:
    loop = QEventLoop()
    completed = {"value": False}

    def done():
        completed["value"] = True
        loop.quit()

    controller.queue_finished.connect(done)
    QTimer.singleShot(timeout_ms, loop.quit)
    loop.exec()
    return completed["value"]


def write_success_pipeline(path: Path) -> None:
    path.write_text(
        """
import argparse, json
from pathlib import Path
p = argparse.ArgumentParser(add_help=False)
p.add_argument('input')
p.add_argument('--event-log', type=Path, required=True)
p.add_argument('--cancel-file')
args, _ = p.parse_known_args()
events = [
    {'event': 'batch_started'},
    {'event': 'stage_started', 'stage': 'extract', 'stage_index': 1, 'stage_total': 6},
    {'event': 'stage_completed', 'stage': 'extract', 'stage_index': 1, 'stage_total': 6},
    {'event': 'stage_skipped', 'stage': 'asr', 'stage_index': 2, 'stage_total': 6},
    {'event': 'stage_skipped', 'stage': 'translate', 'stage_index': 3, 'stage_total': 6},
    {'event': 'stage_skipped', 'stage': 'ass', 'stage_index': 4, 'stage_total': 6},
    {'event': 'stage_skipped', 'stage': 'quality', 'stage_index': 5, 'stage_total': 6},
    {'event': 'stage_skipped', 'stage': 'cleanup', 'stage_index': 6, 'stage_total': 6},
    {'event': 'job_completed', 'outputs': {'ass': str(Path(args.input).with_suffix('.zh.ass'))}},
    {'event': 'batch_completed'},
]
with args.event_log.open('w', encoding='utf-8') as handle:
    for event in events:
        handle.write(json.dumps(event) + '\\n')
        handle.flush()
print('fake pipeline completed', flush=True)
""".lstrip(),
        encoding="utf-8",
    )


def write_cancellable_pipeline(path: Path) -> None:
    path.write_text(
        """
import argparse, json, time
from pathlib import Path
p = argparse.ArgumentParser(add_help=False)
p.add_argument('input')
p.add_argument('--event-log', type=Path, required=True)
p.add_argument('--cancel-file', type=Path, required=True)
args, _ = p.parse_known_args()
with args.event_log.open('w', encoding='utf-8') as handle:
    handle.write(json.dumps({'event': 'stage_started', 'stage': 'asr', 'stage_index': 2, 'stage_total': 6}) + '\\n')
    handle.flush()
    while not args.cancel_file.exists():
        time.sleep(0.02)
    handle.write(json.dumps({'event': 'stage_cancelled', 'stage': 'asr', 'stage_index': 2, 'stage_total': 6}) + '\\n')
    handle.write(json.dumps({'event': 'batch_cancelled'}) + '\\n')
    handle.flush()
raise SystemExit(130)
""".lstrip(),
        encoding="utf-8",
    )


def write_progress_pipeline(path: Path) -> None:
    path.write_text(
        """
import argparse, json
from pathlib import Path
p = argparse.ArgumentParser(add_help=False)
p.add_argument('input')
p.add_argument('--event-log', type=Path, required=True)
p.add_argument('--cancel-file')
args, _ = p.parse_known_args()
events = [
    {'event': 'stage_started', 'stage': 'asr', 'stage_index': 2, 'stage_total': 6},
    {'event': 'stage_progress', 'stage': 'asr', 'stage_index': 2, 'stage_total': 6,
     'progress': 0.5, 'status': '正在进行 Anime 识别（5/10）'},
    {'event': 'stage_completed', 'stage': 'asr', 'stage_index': 2, 'stage_total': 6},
    {'event': 'stage_skipped', 'stage': 'translate', 'stage_index': 3, 'stage_total': 6},
    {'event': 'stage_skipped', 'stage': 'ass', 'stage_index': 4, 'stage_total': 6},
    {'event': 'stage_skipped', 'stage': 'quality', 'stage_index': 5, 'stage_total': 6},
    {'event': 'stage_skipped', 'stage': 'cleanup', 'stage_index': 6, 'stage_total': 6},
    {'event': 'job_completed', 'outputs': {}},
]
with args.event_log.open('w', encoding='utf-8') as handle:
    for event in events:
        handle.write(json.dumps(event, ensure_ascii=False) + '\\n')
        handle.flush()
""".lstrip(),
        encoding="utf-8",
    )


def test_controller_runs_queue_and_applies_jsonl_events(tmp_path):
    application()
    fake_pipeline = tmp_path / "fake_pipeline.py"
    write_success_pipeline(fake_pipeline)
    tasks = [GuiTask(tmp_path / "one.mp4"), GuiTask(tmp_path / "two.mp4")]
    config = GuiConfig(output_dir=tmp_path / "out", work_dir=tmp_path / "work")
    controller = PipelineController(pipeline_script=fake_pipeline)
    logs = []
    controller.log_received.connect(logs.append)

    controller.start(tasks, config)

    assert wait_for_queue(controller)
    assert [task.status for task in tasks] == [TaskStatus.COMPLETED, TaskStatus.COMPLETED]
    assert all(task.progress_percent == 100 for task in tasks)
    assert tasks[0].outputs["ass"].name == "one.zh.ass"
    assert "fake pipeline completed" in "".join(logs)


def test_controller_applies_detailed_status_and_monotonic_stage_progress(tmp_path):
    application()
    fake_pipeline = tmp_path / "fake_pipeline.py"
    write_progress_pipeline(fake_pipeline)
    task = GuiTask(tmp_path / "one.mp4")
    controller = PipelineController(pipeline_script=fake_pipeline)
    seen = []
    controller.task_updated.connect(lambda updated: seen.append((updated.status_text, updated.progress_percent)))

    controller.start(
        [task],
        GuiConfig(output_dir=tmp_path / "out", work_dir=tmp_path / "work"),
    )

    assert wait_for_queue(controller)
    assert ("正在进行 Anime 识别（5/10）", 32) in seen
    assert task.status == TaskStatus.COMPLETED


def test_controller_cancel_stops_after_current_and_leaves_rest_waiting(tmp_path):
    application()
    fake_pipeline = tmp_path / "fake_pipeline.py"
    write_cancellable_pipeline(fake_pipeline)
    tasks = [GuiTask(tmp_path / "one.mp4"), GuiTask(tmp_path / "two.mp4")]
    config = GuiConfig(output_dir=tmp_path / "out", work_dir=tmp_path / "work")
    controller = PipelineController(pipeline_script=fake_pipeline)

    controller.start(tasks, config)
    QTimer.singleShot(150, controller.cancel)

    assert wait_for_queue(controller)
    assert tasks[0].status == TaskStatus.CANCELLED
    assert tasks[1].status == TaskStatus.WAITING
    assert not controller.is_running
