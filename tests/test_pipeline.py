import json
import threading
import subprocess
import sys
import time
from pathlib import Path

import pytest

from atomic_io import atomic_text_writer
from pipeline_runtime import CancellationToken, EventWriter, PipelineCancelled
from video_to_zh_srt import (
    JobLog,
    VideoJob,
    asr_manifest_path,
    asr_provenance_matches,
    audio_manifest_path,
    audio_provenance_matches,
    cleanup_intermediate_files,
    effective_cleanup_policy,
    main,
    output_path_for,
    run,
    run_pipeline,
    run_stage_command,
    require_python_module,
    srt_cue_count,
    translation_is_complete,
    translation_provenance_matches,
    validate_job_paths,
    write_asr_provenance,
    write_audio_provenance,
    write_translation_provenance,
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


def test_run_pipeline_fail_fast_cancels_inflight_prefetch_and_preserves_error(
    tmp_path, monkeypatch
):
    import video_to_zh_srt as pipeline

    token = CancellationToken()
    prefetch_started = threading.Event()
    prefetch_stopped = threading.Event()

    def fake_run(command, _log, cancel_token):
        partial = Path(command[-1])
        partial.write_bytes(b"partial")
        if partial.name.startswith("1.wav"):
            prefetch_started.set()
            while not cancel_token.is_cancelled():
                time.sleep(0.01)
            prefetch_stopped.set()
            raise PipelineCancelled("prefetch cancelled")

    monkeypatch.setattr(pipeline, "run", fake_run)

    def extract(job):
        pipeline.extract_audio(
            tmp_path / f"{job}.mp4",
            tmp_path / f"{job}.wav",
            cancel_token=token,
        )

    def process(job):
        if job == 0:
            assert prefetch_started.wait(timeout=2)
            raise RuntimeError("GPU stage failed")

    with pytest.raises(RuntimeError, match="GPU stage failed"):
        run_pipeline(
            [0, 1, 2],
            extract,
            process,
            continue_on_error=False,
            cancel_token=token,
        )

    assert token.is_cancelled()
    assert prefetch_stopped.wait(timeout=1)
    assert not (tmp_path / "1.wav.part").exists()
    assert not (tmp_path / "1.wav").exists()


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


def test_atomic_text_writer_keeps_previous_output_when_write_fails(tmp_path):
    final = tmp_path / "result.srt"
    partial = tmp_path / "result.srt.part"
    final.write_text("previous", encoding="utf-8")
    with pytest.raises(RuntimeError):
        with atomic_text_writer(final) as output:
            output.write("broken")
            raise RuntimeError("interrupted")

    assert final.read_text(encoding="utf-8") == "previous"
    assert not partial.exists()


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


def test_run_stage_command_converts_child_output_to_progress_events(tmp_path):
    event_path = tmp_path / "events.jsonl"
    log = JobLog(tmp_path / "pipeline.log")
    command = [
        sys.executable,
        "-c",
        "print('anime ASR: clips=10', flush=True); "
        "print('[anime-gen] 5/10 elapsed=1s eta=1s', flush=True); "
        "print('[anime-align] 4/8 elapsed=1s collapsed=0', flush=True)",
    ]
    try:
        with EventWriter(event_path) as events:
            run_stage_command(
                "asr",
                command,
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
    progress = [payload for payload in payloads if payload["event"] == "stage_progress"]
    assert [payload["status"] for payload in progress] == [
        "正在加载 Anime 模型",
        "正在进行 Anime 识别（5/10）",
        "正在进行强制对齐（4/8）",
    ]
    assert progress[1]["progress"] == pytest.approx(0.425)
    assert progress[2]["progress"] == pytest.approx(0.835)


def test_translate_progress_does_not_depend_on_command_argument_order(tmp_path):
    event_path = tmp_path / "events.jsonl"
    log = JobLog(tmp_path / "pipeline.log")
    command = [
        sys.executable,
        "-c",
        "print('1: First', flush=True); print('2: Second', flush=True)",
        "an-unrelated-extra-argument",
    ]
    try:
        with EventWriter(event_path) as events:
            run_stage_command(
                "translate",
                command,
                log,
                events,
                CancellationToken(),
                tmp_path / "sample.mp4",
                1,
                1,
                progress_total=2,
            )
    finally:
        log.close()

    payloads = [json.loads(line) for line in event_path.read_text(encoding="utf-8").splitlines()]
    progress = [payload for payload in payloads if payload["event"] == "stage_progress"]
    assert [payload["status_args"]["current"] for payload in progress] == [1, 2]
    assert progress[-1]["progress"] == 1.0


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
    audio.write_bytes(b"audio")
    video.write_bytes(b"video")
    output = tmp_path / "sample.zh.srt"
    ja_srt = job_dir / "sample.ja.srt"
    ja_srt.write_text(SRT_TWO_CUES, encoding="utf-8")
    output.write_text(SRT_TWO_CUES, encoding="utf-8")
    qwen_model = tmp_path / "qwen-model.bin"
    aligner_model = tmp_path / "aligner-model.bin"
    translate_model = tmp_path / "translate-model.gguf"
    for model in (qwen_model, aligner_model, translate_model):
        model.write_bytes(b"model")
    monkeypatch.setattr(pipeline, "QWEN_ASR_MODEL", qwen_model)
    monkeypatch.setattr(pipeline, "QWEN_ALIGNER_MODEL", aligner_model)
    monkeypatch.setattr(pipeline, "GALTRANSL_MODEL", translate_model)
    monkeypatch.setattr(pipeline, "build_qwen_command", lambda *_args: ["unused-asr"])
    monkeypatch.setattr(pipeline, "build_translate_command", lambda *_args: ["unused-translate"])

    args = argparse.Namespace(
        asr="qwen",
        translator="galtransl",
        target_language="zh-Hans",
        resume=True,
        bilingual=False,
        quality_report=False,
        skip_quality_report=False,
        delete_audio=False,
        no_copy_to_video_dir=True,
        display_wrap_max_chars=0,
    )
    ja_meta = ja_srt.with_suffix(".srt.meta.json")
    ja_meta.write_text("{}", encoding="utf-8")
    write_asr_provenance(asr_manifest_path(ja_srt), args, audio, ja_srt, ja_meta)
    write_translation_provenance(
        job_dir / "sample.zh-Hans.translation.json", args, ja_srt, output
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


def test_translation_provenance_rejects_target_or_backend_change(tmp_path):
    import argparse

    path = tmp_path / "translation.json"
    args = argparse.Namespace(
        translator="galtransl", target_language="zh-Hans", context_size=6,
        translate_batch_size=8, lead_out_seconds=0.5, min_display_seconds=1.5,
    )
    write_translation_provenance(path, args)
    assert translation_provenance_matches(path, args)
    args.target_language = "zh-Hant"
    assert not translation_provenance_matches(path, args)
    args.target_language = "zh-Hans"
    args.translator = "sakura"
    assert not translation_provenance_matches(path, args)


def test_translation_provenance_rejects_same_cue_count_with_changed_source(tmp_path):
    import argparse

    path = tmp_path / "translation.json"
    ja = tmp_path / "sample.ja.srt"
    output = tmp_path / "sample.zh-s.srt"
    ja.write_text(SRT_TWO_CUES, encoding="utf-8")
    output.write_text(SRT_TWO_CUES, encoding="utf-8")
    args = argparse.Namespace(
        translator="galtransl",
        target_language="zh-Hans",
        context_size=6,
        translate_batch_size=8,
        lead_out_seconds=0.5,
        min_display_seconds=1.5,
    )
    write_translation_provenance(path, args, ja, output)
    assert translation_provenance_matches(path, args, ja, output)

    ja.write_text(SRT_TWO_CUES.replace("こんにちは", "こんばんは"), encoding="utf-8")
    assert srt_cue_count(ja) == 2
    assert not translation_provenance_matches(path, args, ja, output)


def test_audio_provenance_rejects_replaced_input_or_audio(tmp_path):
    video = tmp_path / "sample.mp4"
    audio = tmp_path / "sample.wav"
    manifest = audio_manifest_path(audio)
    video.write_bytes(b"video-v1")
    audio.write_bytes(b"audio-v1")
    write_audio_provenance(manifest, video, audio)
    assert audio_provenance_matches(manifest, video, audio)

    video.write_bytes(b"video-v2-longer")
    assert not audio_provenance_matches(manifest, video, audio)
    video.write_bytes(b"video-v1")
    write_audio_provenance(manifest, video, audio)
    audio.write_bytes(b"audio-v2")
    assert not audio_provenance_matches(manifest, video, audio)


def test_asr_provenance_rejects_config_change(tmp_path, monkeypatch):
    import argparse
    import video_to_zh_srt as pipeline

    audio = tmp_path / "sample.wav"
    ja = tmp_path / "sample.ja.srt"
    meta = tmp_path / "sample.ja.srt.meta.json"
    manifest = asr_manifest_path(ja)
    qwen_model = tmp_path / "qwen-model.bin"
    aligner_model = tmp_path / "aligner-model.bin"
    for path, data in (
        (audio, b"audio"),
        (ja, b"subtitle"),
        (meta, b"{}"),
        (qwen_model, b"qwen"),
        (aligner_model, b"aligner"),
    ):
        path.write_bytes(data)
    monkeypatch.setattr(pipeline, "QWEN_ASR_MODEL", qwen_model)
    monkeypatch.setattr(pipeline, "QWEN_ALIGNER_MODEL", aligner_model)
    args = argparse.Namespace(asr="qwen", language="ja", min_cue_seconds=0.3)
    write_asr_provenance(manifest, args, audio, ja, meta)
    assert asr_provenance_matches(manifest, args, audio, ja, meta)

    args.qwen_batch_size = 8
    assert not asr_provenance_matches(manifest, args, audio, ja, meta)
    args.qwen_batch_size = 24
    qwen_model.write_bytes(b"changed-qwen-model")
    assert not asr_provenance_matches(manifest, args, audio, ja, meta)


def test_sugoi_provenance_normalizes_batch_zero_and_ignores_context(tmp_path):
    import argparse

    path = tmp_path / "translation.json"
    args = argparse.Namespace(
        translator="sugoi", target_language="en", context_size=None,
        translate_batch_size=0, display_wrap_max_chars=None,
        lead_out_seconds=0.5, min_display_seconds=1.5,
    )
    write_translation_provenance(path, args)
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored["context_size"] is None
    assert stored["translate_batch_size"] == 1


def test_top_level_rejects_context_for_sugoi():
    import argparse

    from video_to_zh_srt import validate_runtime_args

    args = argparse.Namespace(
        translator="sugoi", target_language="en", context_size=6, asr="anime"
    )
    with pytest.raises(SystemExit, match="not supported by the Sugoi"):
        validate_runtime_args(args)


def test_top_level_rejects_invalid_asr_numeric_before_file_probes(monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "video_to_zh_srt.py",
            "missing-input.mp4",
            "--asr",
            "qwen",
            "--qwen-batch-size",
            "0",
        ],
    )

    with pytest.raises(SystemExit, match=r"--qwen-batch-size must be greater than 0"):
        main()


def test_opencc_dependency_probe_has_actionable_error(monkeypatch):
    def missing(_module):
        raise ImportError("not installed")

    monkeypatch.setattr("video_to_zh_srt.importlib.import_module", missing)
    with pytest.raises(SystemExit, match=r"Missing OpenCC Python package \(opencc\)"):
        require_python_module("opencc", "OpenCC")


@pytest.mark.parametrize(
    ("policy", "remaining"),
    [
        (
            "keep_all",
            {
                "sample.wav",
                "sample.wav.manifest.json",
                "sample.ja.srt",
                "sample.ja.srt.meta.json",
                "sample.ja.srt.manifest.json",
                "pipeline.log",
                "sample.quality.txt",
            },
        ),
        (
            "delete_audio",
            {
                "sample.ja.srt",
                "sample.ja.srt.meta.json",
                "sample.ja.srt.manifest.json",
                "pipeline.log",
                "sample.quality.txt",
            },
        ),
        ("final_only", {"pipeline.log", "sample.quality.txt"}),
    ],
)
def test_cleanup_intermediate_files_deletes_only_known_files(tmp_path, policy, remaining):
    audio = tmp_path / "sample.wav"
    ja_srt = tmp_path / "sample.ja.srt"
    for name in (
        "sample.wav",
        "sample.wav.manifest.json",
        "sample.ja.srt",
        "sample.ja.srt.meta.json",
        "sample.ja.srt.manifest.json",
        "pipeline.log",
        "sample.quality.txt",
    ):
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

    assert output_path_for(video, input_dir, output_dir, recursive=False) == (output_dir / "set-a__sample.zh-s.srt").resolve()


def test_output_path_for_keeps_flat_directory_names(tmp_path):
    input_dir = tmp_path / "videos"
    output_dir = tmp_path / "outputs"
    input_dir.mkdir()
    video = input_dir / "sample.mp4"

    assert output_path_for(video, input_dir, output_dir, recursive=False) == (output_dir / "sample.zh-s.srt").resolve()


def test_validate_job_paths_rejects_non_srt_explicit_output(tmp_path):
    import argparse

    video = tmp_path / "sample.mp4"
    job = VideoJob(1, video, tmp_path / "output.txt", tmp_path / "work", tmp_path / "work" / "sample.wav")
    args = argparse.Namespace(target_language="zh-Hans", bilingual=False, no_copy_to_video_dir=True)

    with pytest.raises(SystemExit, match=r"--output must use the \.srt extension"):
        validate_job_paths([job], args, explicit_output=True)


def test_validate_job_paths_rejects_output_equal_to_input_video(tmp_path):
    import argparse

    video = tmp_path / "sample.mp4"
    job = VideoJob(1, video, video, tmp_path / "work", tmp_path / "work" / "sample.wav")
    args = argparse.Namespace(target_language="zh-Hans", bilingual=False, no_copy_to_video_dir=True)

    with pytest.raises(SystemExit, match="input video and output SRT"):
        validate_job_paths([job], args)


def test_validate_job_paths_rejects_output_collision_with_intermediate(tmp_path):
    import argparse

    video = tmp_path / "sample.mp4"
    work = tmp_path / "work"
    job = VideoJob(1, video, work / "sample.ja.srt", work, work / "sample.wav")
    args = argparse.Namespace(target_language="zh-Hans", bilingual=False, no_copy_to_video_dir=True)

    with pytest.raises(SystemExit, match="output SRT and Japanese SRT"):
        validate_job_paths([job], args, explicit_output=True)


def test_validate_job_paths_uses_windows_case_insensitive_comparison(tmp_path):
    import argparse

    video = tmp_path / "sample.mp4"
    work = tmp_path / "work"
    job = VideoJob(1, video, work / "SAMPLE.JA.SRT", work, work / "sample.wav")
    args = argparse.Namespace(target_language="zh-Hans", bilingual=False, no_copy_to_video_dir=True)

    with pytest.raises(SystemExit, match="collision"):
        validate_job_paths([job], args, explicit_output=True, case_insensitive=True)


@pytest.mark.parametrize(
    ("target_language", "expected"),
    (("zh-Hans", "sample.zh-s.srt"), ("zh-Hant", "sample.zh-t.srt"), ("en", "sample.en.srt")),
)
def test_output_path_for_uses_target_language_suffix(tmp_path, target_language, expected):
    video = tmp_path / "sample.mp4"
    assert output_path_for(video, video, tmp_path / "out", False, target_language) == (tmp_path / "out" / expected).resolve()


def test_english_print_config_uses_arial_target_font(monkeypatch, capsys):
    monkeypatch.setattr(
        sys,
        "argv",
        ["video_to_zh_srt.py", "unused.mp4", "--target-language", "en", "--translator", "sugoi", "--print-config"],
    )
    main()
    assert 'bilingual_font = "Arial"' in capsys.readouterr().out


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
    # None means the runtime chooses the language-aware default (Chinese 20,
    # English 60), so this key is intentionally absent from printed TOML.
    assert "display_wrap_max_chars" not in default
    assert 'target_language = "zh-Hans"' in default
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
