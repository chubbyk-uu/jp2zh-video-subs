from types import SimpleNamespace

from quality_report import (
    Entry,
    adjacent_duplicate_candidates,
    build_report,
    parse_fills_metadata,
    parse_srt,
    percentile,
    possible_japanese_text_left,
    repeated_fill_phrase_warnings,
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


def test_parse_fills_metadata(tmp_path):
    path = tmp_path / "fills.tsv"
    path.write_text(
        "status\treason\tstart\tend\tduration\tclip_start\tclip_end\tavg_logprob\tno_speech_prob\tcompression_ratio\ttext\n"
        "kept\t\t1.000\t2.000\t1.000\t0.500\t2.500\t-0.4200\t0.1000\t1.2300\tこんにちは\n",
        encoding="utf-8",
    )

    rows = parse_fills_metadata(path)

    assert len(rows) == 1
    assert rows[0].status == "kept"
    assert rows[0].start == 1.0
    assert rows[0].avg_logprob == -0.42
    assert rows[0].no_speech_prob == 0.1
    assert rows[0].compression_ratio == 1.23


def _fills_tsv(tmp_path):
    path = tmp_path / "fills.tsv"
    path.write_text(
        "status\treason\tstart\tend\tduration\tclip_start\tclip_end\t"
        "avg_logprob\tno_speech_prob\tcompression_ratio\ttext\n"
        # kept, all metrics healthy -> not flagged
        "kept\t\t10.0\t12.0\t2.0\t9.0\t20.0\t-0.30\t0.10\t1.20\tgood-line\n"
        # kept, every metric past threshold -> flagged as low confidence
        "kept\t\t30.0\t33.0\t3.0\t28.0\t40.0\t-1.50\t0.80\t3.10\tbad-line\n"
        # filtered, counted by reason, never flagged as kept
        "filtered\tnoise\t50.0\t50.5\t0.5\t49.0\t60.0\t-0.90\t0.20\t1.10\t.\n",
        encoding="utf-8",
    )
    return path


def _report_args(tmp_path):
    return SimpleNamespace(
        ja_srt=None,
        zh_srt=None,
        audio=None,
        fills_metadata=_fills_tsv(tmp_path),
        warn_avg_logprob_below=-0.80,
        warn_no_speech_prob_above=0.50,
        warn_compression_ratio_above=2.20,
        warn_repeated_fill_phrase_count=5,
        max_samples=20,
    )


def test_build_report_flags_low_confidence_fills(tmp_path):
    report = build_report(_report_args(tmp_path))
    assert "[Gap Fill Metadata]" in report
    assert "kept_entries: 2" in report
    assert "filtered_entries: 1" in report
    assert "filtered_reasons: noise=1" in report
    assert "low_confidence_kept_entries: 1" in report
    # Only the low-confidence kept line is listed (text=...) in the warning list;
    # the healthy one is not, though both appear under kept_fill_samples.
    assert "text=bad-line" in report
    assert "text=good-line" not in report
    assert "kept_fill_samples:" in report
    assert "repeated_kept_fill_phrases: 0" in report


def test_repeated_fill_phrase_warnings_counts_kept_repeated_phrases(tmp_path):
    path = tmp_path / "fills.tsv"
    path.write_text(
        "status\treason\tstart\tend\tduration\tclip_start\tclip_end\t"
        "avg_logprob\tno_speech_prob\tcompression_ratio\ttext\n"
        + "".join(
            f"kept\t\t{i}.0\t{i + 1}.0\t1.0\t{i}.0\t{i + 1}.0\t-0.50\t0.80\t1.10\tおやすみなさい\n"
            for i in range(5)
        )
        + "filtered\tnoise\t10.0\t11.0\t1.0\t10.0\t11.0\t-0.50\t0.80\t1.10\tおやすみなさい\n",
        encoding="utf-8",
    )
    rows = parse_fills_metadata(path)

    warnings = repeated_fill_phrase_warnings(rows, 5)

    assert len(warnings) == 1
    assert warnings[0][0] == "おやすみなさい"
    assert len(warnings[0][1]) == 5


def test_build_report_lists_repeated_kept_fill_phrases(tmp_path):
    path = tmp_path / "repeated-fills.tsv"
    path.write_text(
        "status\treason\tstart\tend\tduration\tclip_start\tclip_end\t"
        "avg_logprob\tno_speech_prob\tcompression_ratio\ttext\n"
        + "".join(
            f"kept\t\t{i}.0\t{i + 1}.0\t1.0\t{i}.0\t{i + 1}.0\t-0.50\t0.80\t1.10\tありがとうございました。\n"
            for i in range(5)
        ),
        encoding="utf-8",
    )
    args = _report_args(tmp_path)
    args.fills_metadata = path

    report = build_report(args)

    assert "repeated_kept_fill_phrases: 1" in report
    assert "count=5" in report
    assert "text=ありがとうございました" in report


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
        '{"entries": 2, "elapsed_seconds": 90.0, "chunks": [],'
        ' "recapture": {"gap_spans": 3, "clips": 5, "entries_added": 4}}',
        encoding="utf-8",
    )
    args = _report_args(tmp_path)
    args.ja_srt = ja
    args.zh_srt = zh
    args.fills_metadata = None
    args.qwen_metadata = qwen_meta

    metrics: dict = {}
    report = build_report(args, metrics)

    assert metrics["ja_entries"] == 2
    assert metrics["zh_entries"] == 2
    assert metrics["kana_left"] == 0
    assert metrics["adjacent_duplicates"] == 1
    assert metrics["recapture_gap_spans"] == 3
    assert metrics["recapture_entries_added"] == 4
    assert metrics["asr_elapsed_min"] == 1.5
    assert "recapture: gap_spans=3 clips=5 entries_added=4" in report


def test_build_report_respects_relaxed_thresholds(tmp_path):
    args = _report_args(tmp_path)
    # Loosen every threshold so even the bad line is no longer flagged.
    args.warn_avg_logprob_below = -2.0
    args.warn_no_speech_prob_above = 0.99
    args.warn_compression_ratio_above = 5.0
    report = build_report(args)
    assert "low_confidence_kept_entries: 0" in report
    # Nothing is flagged, so no text=... warning line appears (the line still shows
    # under kept_fill_samples, which is not a low-confidence warning).
    assert "text=bad-line" not in report
