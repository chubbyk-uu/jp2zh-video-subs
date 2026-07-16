import json
import threading

import pytest

from pipeline_runtime import CancellationToken, EventWriter, PipelineCancelled


def test_event_writer_emits_utf8_jsonl_and_converts_paths(tmp_path):
    path = tmp_path / "events.jsonl"
    video = tmp_path / "日本語.mp4"

    with EventWriter(path) as events:
        events.emit(
            "stage_started",
            stage="asr",
            video=video,
            outputs={"subtitle": tmp_path / "字幕.ass"},
        )

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert payload["event"] == "stage_started"
    assert payload["stage"] == "asr"
    assert payload["video"] == str(video)
    assert payload["outputs"]["subtitle"] == str(tmp_path / "字幕.ass")
    assert payload["timestamp"].endswith("+00:00")


def test_disabled_event_writer_creates_no_file(tmp_path):
    with EventWriter() as events:
        events.emit("batch_started", job_total=2)

    assert list(tmp_path.iterdir()) == []


def test_event_writer_keeps_concurrent_jsonl_lines_intact(tmp_path):
    path = tmp_path / "events.jsonl"
    with EventWriter(path) as events:
        threads = [
            threading.Thread(target=lambda n=n: [events.emit("tick", worker=n, item=i) for i in range(50)])
            for n in range(3)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

    payloads = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert len(payloads) == 150
    assert {payload["worker"] for payload in payloads} == {0, 1, 2}


def test_cancellation_token_supports_in_process_request():
    token = CancellationToken()
    assert not token.is_cancelled()

    token.request()

    assert token.is_cancelled()
    with pytest.raises(PipelineCancelled):
        token.raise_if_cancelled()


def test_cancellation_token_observes_external_control_file(tmp_path):
    cancel_file = tmp_path / "cancel.requested"
    token = CancellationToken(cancel_file)
    assert not token.is_cancelled()

    cancel_file.touch()

    with pytest.raises(PipelineCancelled):
        token.raise_if_cancelled()
