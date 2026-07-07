import threading

import pytest

from video_to_zh_srt import output_path_for, run_pipeline, srt_cue_count, translation_is_complete


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


def test_build_qwen_command_asr_anime_selects_anime_backend(tmp_path):
    """--asr anime runs the shared qwen sub-script with text_backend=anime."""
    import argparse

    from video_to_zh_srt import build_qwen_command

    ns = argparse.Namespace(language="ja", min_cue_seconds=0.3, asr="anime")
    cmd = build_qwen_command(ns, tmp_path / "audio.wav", tmp_path / "out.ja.srt")

    assert cmd[cmd.index("--text-backend") + 1] == "anime"
    # anime defaults reach the sub-script through the shared QwenAsrConfig serialization
    assert cmd[cmd.index("--vad-backend") + 1] == "whisperseg"
    assert cmd[cmd.index("--timestamp-mode") + 1] == "vad_only"
    assert cmd[cmd.index("--scene-backend") + 1] == "semantic"


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
        None,
        tmp_path / "in.ja.srt.meta.json",
    )

    assert cmd[cmd.index("--vad-backend") + 1] == "whisperseg"
    assert cmd[cmd.index("--whisperseg-model") + 1] == "models/whisperseg/model.onnx"


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
        None,
        tmp_path / "in.ja.srt.meta.json",
    )

    assert cmd[cmd.index("--vad-backend") + 1] == "metadata"


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
