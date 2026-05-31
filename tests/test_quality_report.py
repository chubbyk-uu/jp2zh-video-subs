from quality_report import (
    Entry,
    adjacent_duplicate_candidates,
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
