import json
from types import SimpleNamespace

from quality_report import (
    Entry,
    adjacent_duplicate_candidates,
    build_report,
    parse_srt,
    percentile,
    possible_japanese_text_left,
    reference_recall,
    reference_segments,
)


def test_percentile():
    assert percentile([], 0.5) == 0.0
    assert percentile([1, 2, 3, 4, 5], 0.5) == 3
    assert percentile([1, 2, 3, 4], 0.5) == 2.5


def test_parse_srt_skips_blocks_without_timecode(tmp_path):
    path = tmp_path / "x.srt"
    path.write_text(
        "1\n00:00:01,000 --> 00:00:02,000\nhello\n\n"
        "2\nnotatimecode\nbad\n",
        encoding="utf-8",
    )
    entries = parse_srt(path)
    assert len(entries) == 1
    assert entries[0].text == "hello"
    assert entries[0].start == 1.0
    assert entries[0].end == 2.0


def test_parse_srt_accepts_timecode_settings(tmp_path):
    path = tmp_path / "settings.srt"
    path.write_text(
        "1\n00:00:01,000 --> 00:00:02,500 position:50%\nhello\n\n",
        encoding="utf-8",
    )

    entries = parse_srt(path)

    assert len(entries) == 1
    assert entries[0].start == 1.0
    assert entries[0].end == 2.5


def test_parse_srt_missing_file_returns_empty(tmp_path):
    assert parse_srt(tmp_path / "missing.srt") == []


def test_adjacent_duplicate_candidates_flags_zh_dup_when_ja_differs():
    ja = [Entry("1", 0, 1, "A"), Entry("2", 1, 2, "B")]
    zh = [Entry("1", 0, 1, "译"), Entry("2", 1, 2, "译")]
    candidates = adjacent_duplicate_candidates(ja, zh)
    assert len(candidates) == 1


def test_adjacent_duplicate_candidates_ignores_when_ja_also_duplicates():
    ja = [Entry("1", 0, 1, "A"), Entry("2", 1, 2, "A")]
    zh = [Entry("1", 0, 1, "译"), Entry("2", 1, 2, "译")]
    assert adjacent_duplicate_candidates(ja, zh) == []


def test_possible_japanese_text_left_flags_kana_and_non_simplified_cjk():
    entries = [
        Entry("1", 0, 1, "这里是简体中文，双方状态很好，争取写清楚，保持安静，回到旧地方"),
        Entry("2", 1, 2, "関係者？"),
        Entry("3", 2, 3, "こんにちは"),
    ]

    candidates = possible_japanese_text_left(entries)

    assert [(item.index, reason) for item, reason in candidates] == [
        ("2", "non_simplified_cjk"),
        ("3", "kana"),
    ]


def _report_args(tmp_path):
    return SimpleNamespace(
        ja_srt=None,
        zh_srt=None,
        audio=None,
        qwen_metadata=None,
        reference_srt=[],
        vad_backend="auto",
        whisperseg_model="models/whisperseg/model.onnx",
        whisperseg_max_speech=5.0,
        whisperseg_max_group=5.0,
        whisperseg_chunk_threshold=0.5,
        whisperseg_threshold=0.35,
        whisperseg_min_frame_seconds=0.1,
        min_gap_seconds=10.0,
        min_speech_seconds=2.0,
        subtitle_pad_seconds=0.5,
        max_samples=20,
    )


def test_build_report_lists_possible_japanese_or_traditional_left(tmp_path):
    zh = tmp_path / "zh.srt"
    zh.write_text(
        "1\n00:00:01,000 --> 00:00:02,000\n関係者？\n\n"
        "2\n00:00:03,000 --> 00:00:04,000\n你好\n\n",
        encoding="utf-8",
    )
    args = _report_args(tmp_path)
    args.zh_srt = zh

    report = build_report(args)

    assert "possible_japanese_or_traditional_left: 1" in report
    assert "possible non_simplified_cjk at 1" in report


def test_build_report_lists_qwen_metadata(tmp_path):
    qwen_meta = tmp_path / "sample.ja.srt.meta.json"
    qwen_meta.write_text(
        """{
          "mode": "vad",
          "vad_chunks": true,
          "vad_threshold": 0.1,
          "batch_size": 24,
          "entries": 3,
          "elapsed_seconds": 120.0,
          "chunks": [
            {"start": 0.0, "end": 10.0, "text": "こんにちは", "segments": 2, "seconds": 4.0},
            {"start": 20.0, "end": 25.0, "text": "", "segments": 0, "seconds": 2.0}
          ]
        }""",
        encoding="utf-8",
    )
    args = _report_args(tmp_path)
    args.qwen_metadata = qwen_meta

    report = build_report(args)

    assert "[Qwen ASR Metadata]" in report
    assert "mode: vad" in report
    assert "vad_threshold: 0.1" in report
    assert "chunk_count: 2" in report
    assert "empty_text_chunks: 1" in report
    assert "segments_from_chunks: 2" in report
    assert "entries_after_postprocess: 3" in report


def test_build_report_can_use_metadata_speech_regions_for_audio_gaps(tmp_path):
    ja = tmp_path / "candidate.ja.srt"
    ja.write_text(
        "1\n00:00:00,000 --> 00:00:01,000\n最初\n\n"
        "2\n00:00:06,000 --> 00:00:07,000\n最後\n\n",
        encoding="utf-8",
    )
    qwen_meta = tmp_path / "candidate.ja.srt.meta.json"
    qwen_meta.write_text(
        json.dumps(
            {
                "chunks": [
                    {
                        "start": 2.0,
                        "end": 5.0,
                        "text": "抜け候補",
                        "segments": 1,
                        "seconds": 0.1,
                        "speech_regions": [[0.5, 2.5]],
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    args = _report_args(tmp_path)
    args.ja_srt = ja
    args.qwen_metadata = qwen_meta
    args.vad_backend = "metadata"
    args.min_gap_seconds = 1.0
    args.min_speech_seconds = 1.0

    metrics: dict = {}
    report = build_report(args, metrics)

    assert "[Audio-aware subtitle gaps]" in report
    assert "vad_backend: metadata" in report
    assert "vad_speech_total_s: 2.0" in report
    assert "subtitle_gaps_with_vad_speech: 1" in report
    assert metrics["vad_backend"] == "metadata"
    assert metrics["gaps_with_vad_speech"] == 1


def test_reference_recall_uses_reading_normalization():
    candidate = [Entry("1", 1.0, 2.0, "乾杯")]
    reference = reference_segments([Entry("1", 1.0, 2.0, "かんぱい")], min_reading=3)

    hit, total, missed = reference_recall(candidate, reference, pad=0.5, threshold=0.34)

    assert (hit, total, missed) == (1, 1, [])


def test_build_report_lists_reference_aware_comparison(tmp_path):
    ja = tmp_path / "candidate.ja.srt"
    ja.write_text(
        "1\n00:00:01,000 --> 00:00:02,000\n乾杯\n\n",
        encoding="utf-8",
    )
    ref = tmp_path / "ref.srt"
    ref.write_text(
        "1\n00:00:01,000 --> 00:00:02,000\nかんぱい\n\n"
        "2\n00:00:05,000 --> 00:00:06,000\nまたね\n\n",
        encoding="utf-8",
    )
    args = _report_args(tmp_path)
    args.ja_srt = ja
    args.reference_srt = [f"ref={ref}"]
    args.reference_pad_seconds = 0.5
    args.reference_match_threshold = 0.34
    args.reference_min_reading_chars = 3

    metrics: dict = {}
    report = build_report(args, metrics)

    assert "[Reference-aware ASR comparison]" in report
    assert "ref: recall=50.0% (1/2)" in report
    assert "missed ref 00:00:05.000 -> 00:00:06.000 またね" in report
    assert metrics["reference_ref_recall"] == 0.5


def test_build_report_fills_metrics_dict(tmp_path):
    ja = tmp_path / "x.ja.srt"
    ja.write_text(
        "1\n00:00:01,000 --> 00:00:02,000\nこんにちは\n\n"
        "2\n00:00:03,000 --> 00:00:04,000\nさようなら\n\n",
        encoding="utf-8",
    )
    zh = tmp_path / "x.zh.srt"
    zh.write_text(
        "1\n00:00:01,000 --> 00:00:02,000\n你好\n\n"
        "2\n00:00:03,000 --> 00:00:04,000\n你好\n\n",
        encoding="utf-8",
    )
    qwen_meta = tmp_path / "x.ja.srt.meta.json"
    qwen_meta.write_text(
        '{"entries": 2, "elapsed_seconds": 90.0, "chunks": []}',
        encoding="utf-8",
    )
    args = _report_args(tmp_path)
    args.ja_srt = ja
    args.zh_srt = zh
    args.qwen_metadata = qwen_meta

    metrics: dict = {}
    report = build_report(args, metrics)

    assert metrics["ja_entries"] == 2
    assert metrics["zh_entries"] == 2
    assert metrics["kana_left"] == 0
    assert metrics["adjacent_duplicates"] == 1
    assert metrics["asr_elapsed_min"] == 1.5
