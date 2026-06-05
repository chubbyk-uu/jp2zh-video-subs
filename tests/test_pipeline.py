from argparse import Namespace
import threading

import pytest

from video_to_zh_srt import apply_preset_defaults, run_pipeline


def preset_args(preset: str, **overrides):
    args = Namespace(
        preset=preset,
        vad_threshold=None,
        fill_min_gap_seconds=None,
        fill_min_speech_seconds=None,
        fill_max_clip_seconds=None,
        fill_min_chars=None,
        fill_min_clip_seconds=None,
        fill_clip_pad_seconds=None,
        fill_existing_pad_seconds=None,
        fill_max_existing_overlap_seconds=None,
        fill_max_cluster_gap=None,
        fill_duplicate_window_seconds=None,
        gap_local_vad=False,
    )
    for key, value in overrides.items():
        setattr(args, key, value)
    return args


def test_apply_preset_defaults_uses_coverage_by_default():
    args = preset_args("coverage")
    apply_preset_defaults(args)
    assert args.vad_threshold == 0.05
    assert args.fill_min_gap_seconds == 2.0
    assert args.fill_min_speech_seconds == 1.0
    assert args.fill_min_clip_seconds == 0.6
    assert args.fill_clip_pad_seconds == 0.4
    assert args.fill_existing_pad_seconds == 0.1
    assert args.fill_max_existing_overlap_seconds == 1.0
    assert args.gap_local_vad is False


def test_apply_preset_defaults_uses_fast_conservative_values():
    args = preset_args("fast")
    apply_preset_defaults(args)
    assert args.vad_threshold == 0.20
    assert args.fill_min_gap_seconds == 6.0
    assert args.fill_min_speech_seconds == 2.0
    assert args.fill_min_clip_seconds == 1.0
    assert args.fill_clip_pad_seconds == 0.6
    assert args.fill_existing_pad_seconds == 0.3
    assert args.fill_max_existing_overlap_seconds == 0.5
    assert args.gap_local_vad is False


def test_apply_preset_defaults_high_coverage_enables_gap_local_vad():
    args = preset_args("high-coverage")
    apply_preset_defaults(args)
    assert args.vad_threshold == 0.05
    assert args.fill_min_gap_seconds == 2.0
    assert args.gap_local_vad is True


def test_apply_preset_defaults_keeps_explicit_overrides():
    args = preset_args("fast", vad_threshold=0.25, fill_min_gap_seconds=8.0, gap_local_vad=True)
    apply_preset_defaults(args)
    assert args.vad_threshold == 0.25
    assert args.fill_min_gap_seconds == 8.0
    assert args.fill_min_speech_seconds == 2.0
    assert args.gap_local_vad is True


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


def test_run_pipeline_raises_without_continue_on_error():
    def process(job):
        if job == 1:
            raise RuntimeError("gpu stage failed")

    with pytest.raises(RuntimeError):
        run_pipeline([0, 1, 2], lambda job: None, process, continue_on_error=False)
