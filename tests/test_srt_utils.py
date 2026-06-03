from types import SimpleNamespace

from srt_utils import (
    Interval,
    compact_text,
    format_time,
    merge_intervals,
    overlap_seconds,
    padded_end,
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


def test_padded_end_extends_by_lead_out():
    assert padded_end(10.0, 11.0, 20.0, lead_out=0.5, min_display=0.0) == 11.5


def test_padded_end_uses_min_display_when_larger():
    assert padded_end(10.0, 10.5, 20.0, lead_out=0.2, min_display=1.5) == 11.5


def test_padded_end_clamps_before_next_start():
    assert round(padded_end(10.0, 11.0, 11.3, lead_out=1.0, min_display=0.0, min_gap=0.04), 3) == 11.26


def test_padded_end_never_shortens_back_to_back_cues():
    assert padded_end(10.0, 11.0, 11.0, lead_out=0.5, min_display=1.5, min_gap=0.04) == 11.0


def test_padded_end_last_cue_uses_desired_end():
    assert padded_end(10.0, 11.0, None, lead_out=0.5, min_display=2.0) == 12.0
