import json
import threading
import subprocess
import sys
import time
from pathlib import Path

import pytest

from pipeline_runtime import CancellationToken, EventWriter, PipelineCancelled
from video_to_zh_srt import (
    JobLog,
    cleanup_intermediate_files,
    effective_cleanup_policy,
    output_path_for,
    run,
    run_pipeline,
    run_stage_command,
    srt_cue_count,
    translation_is_complete,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_run_pipeline_processes_all_jobs_in_order():
    order = []
    failures = run_pipeline(
        list(range(5)),
        extract=lambda job: None,
        process=lambda job: order.append(job),
        continue_on_error=True,
    )
    assert order == [0, 1, 2, 3, 4]
    assert failures == []


def test_run_pipeline_overlaps_extraction_with_processing():
    # While the first job is being processed, the second job's audio must already
    # be extracting in the background thread (one step ahead).
    extract_of_job1_started = threading.Event()
    seen_overlap = {}

    def extract(job):
        if job == 1:
            extract_of_job1_started.set()

    def process(job):
        if job == 0:
            seen_overlap["during_job0"] = extract_of_job1_started.wait(timeout=2)

    run_pipeline([0, 1, 2], extract, process, continue_on_error=True)
    assert seen_overlap["during_job0"] is True


def test_run_pipeline_bounds_prefetch_depth():
    # Extraction is instant, processing of job 0 is slow. With maxsize=1 the producer
    # can only get one item into the queue plus one more blocked on put(), so while
    # job 0 is still processing it must NOT have extracted all jobs ahead.
    import time

    extracted = []
    snapshot = {}

    def extract(job):
        extracted.append(job)

    def process(job):
        if job == 0:
            time.sleep(0.4)
            snapshot["while_job0"] = list(extracted)

    run_pipeline(list(range(6)), extract, process, continue_on_error=True)
    ahead = snapshot["while_job0"]
    # Prefetch happened (job 1 is ready) but is bounded: not all 6 extracted ahead.
    assert 1 in ahead
    assert len(ahead) <= 3, ahead
    # Everything still gets extracted by the end.
    assert sorted(extracted) == list(range(6))


def test_run_pipeline_continues_after_extraction_error():
    processed = []

    def extract(job):
        if job == 1:
            raise RuntimeError("ffmpeg failed")

    failures = run_pipeline([0, 1, 2], extract, lambda job: processed.append(job), continue_on_error=True)
    assert processed == [0, 2]
    assert [job for job, _ in failures] == [1]


def test_run_pipeline_sends_done_after_extraction_base_exception():
    processed = []

    def extract(_job):
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        run_pipeline([0, 1, 2], extract, lambda job: processed.append(job), continue_on_error=True)

    assert processed == []


def test_run_pipeline_raises_without_continue_on_error():
    def process(job):
        if job == 1:
            raise RuntimeError("gpu stage failed")

    with pytest.raises(RuntimeError):
        run_pipeline([0, 1, 2], lambda job: None, process, continue_on_error=False)


def test_run_pipeline_cancellation_stops_prefetch_without_deadlock():
    token = CancellationToken()
    processed = []

    def process(job):
        processed.append(job)
        token.request()
        token.raise_if_cancelled()

    started = time.monotonic()
    with pytest.raises(PipelineCancelled):
        run_pipeline(
            list(range(20)),
            extract=lambda job: None,
            process=process,
            continue_on_error=True,
            cancel_token=token,
        )

    assert processed == [0]
    assert time.monotonic() - started < 2


def test_run_terminates_a_running_child_when_cancelled():
    token = CancellationToken()
    timer = threading.Timer(0.2, token.request)
    timer.start()
    started = time.monotonic()
    try:
        with pytest.raises(PipelineCancelled):
            run([sys.executable, "-c", "import time; time.sleep(30)"], cancel_token=token)
    finally:
        timer.cancel()

    assert time.monotonic() - started < 3


def test_run_observes_external_cancel_file_while_child_is_running(tmp_path):
    cancel_file = tmp_path / "cancel.requested"
    token = CancellationToken(cancel_file)
    timer = threading.Timer(0.2, cancel_file.touch)
    timer.start()
    started = time.monotonic()
    try:
        with pytest.raises(PipelineCancelled):
            run([sys.executable, "-c", "import time; time.sleep(30)"], cancel_token=token)
    finally:
        timer.cancel()

    assert time.monotonic() - started < 3


def test_extract_audio_removes_partial_file_when_cancelled(tmp_path, monkeypatch):
    import video_to_zh_srt as pipeline

    audio = tmp_path / "sample.wav"
    partial = tmp_path / "sample.wav.part"

    def cancelled_run(command, _log, _cancel_token):
        Path(command[-1]).write_bytes(b"incomplete")
        raise PipelineCancelled("cancelled")

    monkeypatch.setattr(pipeline, "run", cancelled_run)
    with pytest.raises(PipelineCancelled):
        pipeline.extract_audio(
            tmp_path / "sample.mp4",
            audio,
            cancel_token=CancellationToken(),
        )

    assert not partial.exists()
    assert not audio.exists()


def test_run_stage_command_emits_completed_event_sequence(tmp_path):
    event_path = tmp_path / "events.jsonl"
    log = JobLog(tmp_path / "pipeline.log")
    try:
        with EventWriter(event_path) as events:
            run_stage_command(
                "asr",
                [sys.executable, "-c", "print('ok')"],
                log,
                events,
                CancellationToken(),
                tmp_path / "sample.mp4",
                1,
                2,
            )
    finally:
        log.close()

    payloads = [json.loads(line) for line in event_path.read_text(encoding="utf-8").splitlines()]
    assert [payload["event"] for payload in payloads] == ["stage_started", "stage_completed"]
    assert all(payload["stage"] == "asr" for payload in payloads)
    assert all(payload["stage_index"] == 2 and payload["stage_total"] == 6 for payload in payloads)
    assert all(payload["job_index"] == 1 and payload["job_total"] == 2 for payload in payloads)


def test_run_stage_command_emits_failed_event(tmp_path):
    event_path = tmp_path / "events.jsonl"
    log = JobLog(tmp_path / "pipeline.log")
    try:
        with EventWriter(event_path) as events:
            with pytest.raises(subprocess.CalledProcessError):
                run_stage_command(
                    "translate",
                    [sys.executable, "-c", "raise SystemExit(4)"],
                    log,
                    events,
                    CancellationToken(),
                    tmp_path / "sample.mp4",
                    1,
                    1,
                )
    finally:
        log.close()

    payloads = [json.loads(line) for line in event_path.read_text(encoding="utf-8").splitlines()]
    assert [payload["event"] for payload in payloads] == ["stage_started", "stage_failed"]
    assert payloads[-1]["stage"] == "translate"
    assert "returned non-zero exit status 4" in payloads[-1]["error"]


def test_run_stage_command_emits_cancelled_event(tmp_path):
    event_path = tmp_path / "events.jsonl"
    log = JobLog(tmp_path / "pipeline.log")
    token = CancellationToken()
    token.request()
    try:
        with EventWriter(event_path) as events:
            with pytest.raises(PipelineCancelled):
                run_stage_command(
                    "quality",
                    [sys.executable, "-c", "pass"],
                    log,
                    events,
                    token,
                    tmp_path / "sample.mp4",
                    1,
                    1,
                )
    finally:
        log.close()

    payloads = [json.loads(line) for line in event_path.read_text(encoding="utf-8").splitlines()]
    assert [payload["event"] for payload in payloads] == ["stage_started", "stage_cancelled"]


def test_process_video_stages_emits_skips_for_resumed_and_disabled_stages(tmp_path, monkeypatch):
    import argparse
    import video_to_zh_srt as pipeline

    video = tmp_path / "sample.mp4"
    job_dir = tmp_path / "work"
    job_dir.mkdir()
    audio = job_dir / "sample.wav"
    output = tmp_path / "sample.zh.srt"
    ja_srt = job_dir / "sample.ja.srt"
    ja_srt.write_text(SRT_TWO_CUES, encoding="utf-8")
    output.write_text(SRT_TWO_CUES, encoding="utf-8")
    monkeypatch.setattr(pipeline, "build_qwen_command", lambda *_args: ["unused-asr"])
    monkeypatch.setattr(pipeline, "build_translate_command", lambda *_args: ["unused-translate"])

    args = argparse.Namespace(
        resume=True,
        bilingual=False,
        quality_report=False,
        skip_quality_report=False,
        delete_audio=False,
        no_copy_to_video_dir=True,
        display_wrap_max_chars=0,
    )
    event_path = tmp_path / "events.jsonl"
    log = JobLog(job_dir / "pipeline.log")
    try:
        with EventWriter(event_path) as events:
            pipeline.process_video_stages(
                args,
                video,
                output,
                job_dir,
                audio,
                log,
                events=events,
                cancel_token=CancellationToken(),
                job_index=2,
                job_total=3,
            )
    finally:
        log.close()

    payloads = [json.loads(line) for line in event_path.read_text(encoding="utf-8").splitlines()]
    skipped = [(payload["stage"], payload["reason"]) for payload in payloads]
    assert skipped == [
        ("asr", "resume"),
        ("translate", "resume"),
        ("ass", "disabled"),
        ("quality", "disabled"),
        ("cleanup", "keep_all"),
    ]
    assert all(payload["event"] == "stage_skipped" for payload in payloads)
    assert all(payload["job_index"] == 2 and payload["job_total"] == 3 for payload in payloads)


SRT_TWO_CUES = """1
00:00:01,000 --> 00:00:02,000
こんにちは

2
00:00:03,000 --> 00:00:04,000
さようなら
"""


def test_srt_cue_count(tmp_path):
    srt = tmp_path / "a.srt"
    srt.write_text(SRT_TWO_CUES, encoding="utf-8")
    assert srt_cue_count(srt) == 2
    assert srt_cue_count(tmp_path / "missing.srt") == -1


def test_translation_is_complete_requires_matching_cue_counts(tmp_path):
    ja = tmp_path / "a.ja.srt"
    zh = tmp_path / "a.zh.srt"
    ja.write_text(SRT_TWO_CUES, encoding="utf-8")

    # Missing or empty translation: not complete.
    assert not translation_is_complete(zh, ja)
    zh.write_text("", encoding="utf-8")
    assert not translation_is_complete(zh, ja)

    # A crash mid-translation leaves fewer cues than the source: not complete.
    zh.write_text("1\n00:00:01,000 --> 00:00:02,000\n你好\n", encoding="utf-8")
    assert not translation_is_complete(zh, ja)

    # One cue per source cue: complete.
    zh.write_text(SRT_TWO_CUES.replace("こんにちは", "你好").replace("さようなら", "再见"), encoding="utf-8")
    assert translation_is_complete(zh, ja)


@pytest.mark.parametrize(
    ("policy", "remaining"),
    [
        ("keep_all", {"sample.wav", "sample.ja.srt", "sample.ja.srt.meta.json", "pipeline.log", "sample.quality.txt"}),
        ("delete_audio", {"sample.ja.srt", "sample.ja.srt.meta.json", "pipeline.log", "sample.quality.txt"}),
        ("final_only", {"pipeline.log", "sample.quality.txt"}),
    ],
)
def test_cleanup_intermediate_files_deletes_only_known_files(tmp_path, policy, remaining):
    audio = tmp_path / "sample.wav"
    ja_srt = tmp_path / "sample.ja.srt"
    for name in ("sample.wav", "sample.ja.srt", "sample.ja.srt.meta.json", "pipeline.log", "sample.quality.txt"):
        (tmp_path / name).write_text("x", encoding="utf-8")

    cleanup_intermediate_files(policy, audio, ja_srt)

    assert {path.name for path in tmp_path.iterdir()} == remaining


def test_effective_cleanup_policy_preserves_delete_audio_compatibility():
    import argparse

    assert effective_cleanup_policy(argparse.Namespace(cleanup_policy=None, delete_audio=False)) == "keep_all"
    assert effective_cleanup_policy(argparse.Namespace(cleanup_policy=None, delete_audio=True)) == "delete_audio"
    assert effective_cleanup_policy(argparse.Namespace(cleanup_policy="final_only", delete_audio=False)) == "final_only"
    with pytest.raises(SystemExit, match="conflicts"):
        effective_cleanup_policy(argparse.Namespace(cleanup_policy="final_only", delete_audio=True))


def test_output_path_for_includes_relative_parent_when_present(tmp_path):
    input_dir = tmp_path / "videos"
    output_dir = tmp_path / "outputs"
    input_dir.mkdir()
    video = input_dir / "set-a" / "sample.mp4"

    assert output_path_for(video, input_dir, output_dir, recursive=False) == (output_dir / "set-a__sample.zh.srt").resolve()


def test_output_path_for_keeps_flat_directory_names(tmp_path):
    input_dir = tmp_path / "videos"
    output_dir = tmp_path / "outputs"
    input_dir.mkdir()
    video = input_dir / "sample.mp4"

    assert output_path_for(video, input_dir, output_dir, recursive=False) == (output_dir / "sample.zh.srt").resolve()


def test_build_qwen_command_survives_unexposed_config_fields(tmp_path):
    """Regression: the orchestrator must not crash when QwenAsrConfig has a field with
    no matching --qwen-<field> flag. config_from_prefixed falls back to the dataclass
    default instead of raising AttributeError (which previously took down the pipeline)."""
    import argparse

    from video_to_zh_srt import build_qwen_command

    # Namespace with only the override sources present — every qwen_<field> is
    # absent, exactly the situation for the newly added text_backend/vad_backend/etc.
    ns = argparse.Namespace(language="ja", min_cue_seconds=0.3, asr="qwen")
    cmd = build_qwen_command(ns, tmp_path / "audio.wav", tmp_path / "out.ja.srt")

    assert str(tmp_path / "audio.wav") in cmd
    assert "--text-backend" in cmd          # unexposed field serialized from its default
    assert cmd[cmd.index("--text-backend") + 1] == "qwen"  # --asr qwen stays on qwen
    assert cmd[cmd.index("--timestamp-mode") + 1] == "aligner_fallback"
    assert cmd[cmd.index("--vad-backend") + 1] == "whisperseg"
    assert cmd[cmd.index("--scene-backend") + 1] == "semantic"
    assert cmd[cmd.index("--max-new-tokens") + 1] == "4096"
    assert cmd[cmd.index("--repetition-penalty") + 1] == "1.1"
    assert cmd[cmd.index("--max-tokens-per-second") + 1] == "20.0"
    assert cmd[cmd.index("--min-tokens-floor") + 1] == "256"
    assert cmd[cmd.index("--whisperseg-context-mode") + 1] == "none"
    assert cmd[cmd.index("--whisperseg-context-merge-gap") + 1] == "1.0"
    assert cmd[cmd.index("--whisperseg-context-target-seconds") + 1] == "10.0"
    assert cmd[cmd.index("--whisperseg-context-after-target-gap") + 1] == "0.2"
    assert cmd[cmd.index("--whisperseg-context-hard-max-seconds") + 1] == "15.0"


def test_top_level_rejects_qwen_vad_only_with_context_merge():
    import argparse

    from video_to_zh_srt import validate_runtime_args

    ns = argparse.Namespace(
        language="ja",
        min_cue_seconds=0.3,
        asr="qwen",
        qwen_timestamp_mode="vad_only",
        qwen_vad_backend="whisperseg",
        qwen_whisperseg_context_mode="merge",
    )

    with pytest.raises(SystemExit, match="Qwen vad_only cannot be combined"):
        validate_runtime_args(ns)


def test_top_level_allows_qwen_vad_only_with_context_none():
    import argparse

    from video_to_zh_srt import validate_runtime_args

    ns = argparse.Namespace(
        language="ja",
        min_cue_seconds=0.3,
        asr="qwen",
        qwen_timestamp_mode="vad_only",
        qwen_vad_backend="whisperseg",
        qwen_whisperseg_context_mode="none",
    )

    validate_runtime_args(ns)


def test_build_qwen_command_can_override_qwen_framing(tmp_path):
    import argparse

    from video_to_zh_srt import build_qwen_command

    ns = argparse.Namespace(
        language="ja",
        min_cue_seconds=0.3,
        asr="qwen",
        qwen_vad_backend="whisperseg",
        qwen_whisperseg_max_group=7.0,
        qwen_whisperseg_chunk_threshold=0.8,
        qwen_whisperseg_context_mode="merge",
        qwen_whisperseg_context_merge_gap=1.25,
        qwen_whisperseg_context_target_seconds=18.0,
        qwen_whisperseg_context_hard_max_seconds=36.0,
        qwen_scene_backend="semantic",
        qwen_scene_max_seconds=36.0,
    )
    cmd = build_qwen_command(ns, tmp_path / "audio.wav", tmp_path / "out.ja.srt")

    assert cmd[cmd.index("--text-backend") + 1] == "qwen"
    assert cmd[cmd.index("--vad-backend") + 1] == "whisperseg"
    assert cmd[cmd.index("--whisperseg-max-group") + 1] == "7.0"
    assert cmd[cmd.index("--whisperseg-chunk-threshold") + 1] == "0.8"
    assert cmd[cmd.index("--whisperseg-context-mode") + 1] == "merge"
    assert cmd[cmd.index("--whisperseg-context-merge-gap") + 1] == "1.25"
    assert cmd[cmd.index("--whisperseg-context-target-seconds") + 1] == "18.0"
    assert cmd[cmd.index("--whisperseg-context-hard-max-seconds") + 1] == "36.0"
    assert cmd[cmd.index("--scene-backend") + 1] == "semantic"
    assert cmd[cmd.index("--scene-max-seconds") + 1] == "36.0"


def test_build_qwen_command_asr_anime_selects_anime_backend(tmp_path):
    """--asr anime runs the shared qwen sub-script with text_backend=anime."""
    import argparse

    from video_to_zh_srt import build_qwen_command

    ns = argparse.Namespace(language="ja", min_cue_seconds=0.3, asr="anime")
    cmd = build_qwen_command(ns, tmp_path / "audio.wav", tmp_path / "out.ja.srt")

    assert cmd[cmd.index("--text-backend") + 1] == "anime"
    # anime defaults reach the shared sub-script through AnimeAsrConfig serialization
    assert cmd[cmd.index("--vad-backend") + 1] == "whisperseg"
    assert cmd[cmd.index("--timestamp-mode") + 1] == "aligner_fallback"
    assert cmd[cmd.index("--scene-backend") + 1] == "semantic"
    assert cmd[cmd.index("--whisperseg-chunk-threshold") + 1] == "0.5"


def test_build_qwen_command_asr_anime_uses_anime_prefixed_overrides(tmp_path):
    import argparse

    from video_to_zh_srt import build_qwen_command

    ns = argparse.Namespace(
        language="ja",
        min_cue_seconds=0.3,
        asr="anime",
        anime_batch_size=7,
        anime_timestamp_mode="aligner_fallback",
        anime_scene_backend="none",
        anime_whisperseg_chunk_threshold=0.75,
    )
    cmd = build_qwen_command(ns, tmp_path / "audio.wav", tmp_path / "out.ja.srt")

    assert cmd[cmd.index("--text-backend") + 1] == "anime"
    assert cmd[cmd.index("--batch-size") + 1] == "7"
    assert cmd[cmd.index("--timestamp-mode") + 1] == "aligner_fallback"
    assert cmd[cmd.index("--scene-backend") + 1] == "none"
    assert cmd[cmd.index("--whisperseg-chunk-threshold") + 1] == "0.75"


def test_build_qwen_command_asr_anime_legacy_alias_yields_to_anime_prefix(tmp_path):
    import argparse

    from cli_config import add_prefixed_dataclass_arguments
    from pipeline_configs import AnimeAsrConfig
    from video_to_zh_srt import ANIME_PREFIX_SKIP, build_qwen_command

    parser = argparse.ArgumentParser()
    parser.add_argument("--qwen-timestamp-mode", choices=("aligner_fallback", "aligner_only", "vad_only"), default=None)
    parser.add_argument("--asr", default="anime")
    parser.add_argument("--language", default="ja")
    parser.add_argument("--min-cue-seconds", type=float, default=0.3)
    add_prefixed_dataclass_arguments(
        parser,
        AnimeAsrConfig,
        "anime_",
        skip=ANIME_PREFIX_SKIP,
        default_none=True,
    )

    legacy = parser.parse_args(["--qwen-timestamp-mode", "aligner_fallback"])
    cmd = build_qwen_command(legacy, tmp_path / "audio.wav", tmp_path / "out.ja.srt")
    assert cmd[cmd.index("--timestamp-mode") + 1] == "aligner_fallback"

    explicit = parser.parse_args([
        "--qwen-timestamp-mode", "aligner_fallback",
        "--anime-timestamp-mode", "vad_only",
    ])
    cmd = build_qwen_command(explicit, tmp_path / "audio.wav", tmp_path / "out.ja.srt")
    assert cmd[cmd.index("--timestamp-mode") + 1] == "vad_only"


def test_build_quality_command_asr_anime_uses_whisperseg_backend(tmp_path):
    import argparse

    from video_to_zh_srt import build_quality_command

    ns = argparse.Namespace(asr="anime", vad_min_silence_ms=500, vad_speech_pad_ms=200)
    cmd = build_quality_command(
        ns,
        tmp_path / "in.ja.srt",
        tmp_path / "in.zh.srt",
        tmp_path / "in.wav",
        tmp_path / "quality.txt",
        tmp_path / "metrics.jsonl",
        "sample",
        tmp_path / "in.ja.srt.meta.json",
    )

    assert cmd[cmd.index("--vad-backend") + 1] == "whisperseg"
    assert cmd[cmd.index("--whisperseg-model") + 1] == "models/whisperseg/model.onnx"
    assert cmd[cmd.index("--whisperseg-hard-max-speech") + 1] == "8.0"
    assert cmd[cmd.index("--whisperseg-soft-split-lookback") + 1] == "1.0"


def test_build_quality_command_can_override_quality_vad_backend(tmp_path):
    import argparse

    from video_to_zh_srt import build_quality_command

    ns = argparse.Namespace(
        asr="anime",
        vad_min_silence_ms=500,
        vad_speech_pad_ms=200,
        quality_vad_backend="metadata",
    )
    cmd = build_quality_command(
        ns,
        tmp_path / "in.ja.srt",
        tmp_path / "in.zh.srt",
        tmp_path / "in.wav",
        tmp_path / "quality.txt",
        tmp_path / "metrics.jsonl",
        "sample",
        tmp_path / "in.ja.srt.meta.json",
    )

    assert cmd[cmd.index("--vad-backend") + 1] == "metadata"


def test_quality_report_is_opt_in_by_default():
    def printed_config(*extra: str) -> str:
        result = subprocess.run(
            [sys.executable, "scripts/video_to_zh_srt.py", "sample.mp4", "--print-config", *extra],
            cwd=PROJECT_ROOT,
            text=True,
            capture_output=True,
            check=True,
        )
        return result.stdout

    default = printed_config()
    assert "quality_report = false" in default
    assert "skip_quality_report = false" in default
    assert "display_wrap_max_chars = 20" in default
    assert "event_log" not in default
    assert "cancel_file" not in default

    enabled = printed_config("--quality-report")
    assert "quality_report = true" in enabled
    assert "skip_quality_report = false" in enabled

    legacy_skip = printed_config("--skip-quality-report")
    assert "quality_report = false" in legacy_skip
    assert "skip_quality_report = true" in legacy_skip


def test_build_qwen_command_asr_anime_can_select_aligner_mode(tmp_path):
    import argparse

    from video_to_zh_srt import build_qwen_command

    ns = argparse.Namespace(language="ja", min_cue_seconds=0.3, asr="anime", qwen_timestamp_mode="aligner_fallback")
    cmd = build_qwen_command(ns, tmp_path / "audio.wav", tmp_path / "out.ja.srt")

    assert cmd[cmd.index("--text-backend") + 1] == "anime"
    assert cmd[cmd.index("--timestamp-mode") + 1] == "aligner_fallback"


def test_build_qwen_command_asr_anime_can_disable_semantic_scene(tmp_path):
    import argparse

    from video_to_zh_srt import build_qwen_command

    ns = argparse.Namespace(language="ja", min_cue_seconds=0.3, asr="anime", qwen_scene_backend="none")
    cmd = build_qwen_command(ns, tmp_path / "audio.wav", tmp_path / "out.ja.srt")

    assert cmd[cmd.index("--text-backend") + 1] == "anime"
    assert cmd[cmd.index("--scene-backend") + 1] == "none"
