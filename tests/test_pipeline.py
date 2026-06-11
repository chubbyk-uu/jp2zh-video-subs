import threading

import pytest

from video_to_zh_srt import run_pipeline, srt_cue_count, translation_is_complete


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
