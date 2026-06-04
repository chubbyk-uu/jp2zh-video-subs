from types import SimpleNamespace

from quality_report import (
    Entry,
    adjacent_duplicate_candidates,
    build_report,
    parse_fills_metadata,
    parse_srt,
    percentile,
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
