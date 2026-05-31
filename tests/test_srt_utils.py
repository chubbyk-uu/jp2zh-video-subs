from types import SimpleNamespace

from srt_utils import (
    Interval,
    compact_text,
    format_time,
    merge_intervals,
    overlap_seconds,
    parse_time,
    srt_gaps,
    srt_time,
)


def test_compact_text_removes_all_whitespace():
    assert compact_text("a b\tc\n d") == "abcd"
    assert compact_text("   ") == ""


def test_srt_time_formats_milliseconds():
    assert srt_time(0) == "00:00:00,000"
    assert srt_time(3661.5) == "01:01:01,500"


def test_parse_time_roundtrips_srt_time():
    for seconds in (0.0, 1.234, 3661.5, 7322.999):
        assert abs(parse_time(srt_time(seconds)) - seconds) < 1e-3


def test_format_time_clamps_negative():
    assert format_time(3661.5) == "01:01:01.500"
    assert format_time(-5) == "00:00:00.000"


def test_merge_intervals_merges_overlapping_and_adjacent():
    merged = merge_intervals([Interval(0, 2), Interval(1, 3), Interval(5, 6)])
    assert [(i.start, i.end) for i in merged] == [(0, 3), (5, 6)]
    assert merge_intervals([]) == []


def test_overlap_seconds_sums_clipped_overlap():
    intervals = [Interval(0, 2), Interval(4, 6)]
    assert overlap_seconds(Interval(1, 5), intervals) == 2.0
    assert overlap_seconds(Interval(10, 12), intervals) == 0.0


def test_srt_gaps_returns_gaps_between_entries():
    entries = [SimpleNamespace(start=0, end=1), SimpleNamespace(start=2, end=3), SimpleNamespace(start=3, end=5)]
    gaps = srt_gaps(entries)
    assert [(g.start, g.end) for g in gaps] == [(1, 2)]


def test_srt_gaps_sorts_input():
    entries = [SimpleNamespace(start=3, end=5), SimpleNamespace(start=0, end=1)]
    gaps = srt_gaps(entries)
    assert [(g.start, g.end) for g in gaps] == [(1, 3)]


def test_srt_gaps_ignores_contained_entry():
    # An entry fully inside an earlier one must not create a false gap after it.
    entries = [SimpleNamespace(start=0, end=10), SimpleNamespace(start=2, end=3), SimpleNamespace(start=12, end=14)]
    gaps = srt_gaps(entries)
    assert [(g.start, g.end) for g in gaps] == [(10, 12)]
