from types import SimpleNamespace

from srt_utils import (
    Interval,
    compact_text,
    count_overlong_srt_lines,
    format_time,
    merge_intervals,
    overlap_seconds,
    padded_end,
    parse_time,
    srt_gaps,
    srt_time,
    wrap_display_text,
    wrap_english_display_text,
    wrap_srt_display_file,
)


def test_compact_text_removes_all_whitespace():
    assert compact_text("a b\tc\n d") == "abcd"
    assert compact_text("   ") == ""


def test_wrap_display_text_uses_punctuation_nearest_midpoint():
    text = "这是前半句。这里是后半句仍然很长。"
    assert wrap_display_text(text, 15) == "这是前半句。\n这里是后半句仍然很长。"


def test_wrap_display_text_counts_punctuation_and_does_not_force_break():
    assert wrap_display_text("一二三四五。", 6) == "一二三四五。"
    assert wrap_display_text("这是一段没有句末标点的很长字幕", 8) == "这是一段没有句末标点的很长字幕"
    assert wrap_display_text("前半句? 后半句!", 7) == "前半句?\n后半句!"


def test_wrap_srt_display_file_preserves_cue_count_and_timecodes(tmp_path):
    path = tmp_path / "out.srt"
    path.write_text(
        "1\n00:00:01,000 --> 00:00:03,000\n这是前半句。这里是后半句仍然很长。\n\n"
        "2\n00:00:04,000 --> 00:00:05,000\n短句。\n",
        encoding="utf-8",
    )
    assert wrap_srt_display_file(path, 15) == 1
    assert path.read_text(encoding="utf-8") == (
        "1\n00:00:01,000 --> 00:00:03,000\n这是前半句。\n这里是后半句仍然很长。\n\n"
        "2\n00:00:04,000 --> 00:00:05,000\n短句。\n"
    )


def test_wrap_english_display_text_uses_word_boundary():
    text = "This is a deliberately long English subtitle that should wrap cleanly between words."
    wrapped = wrap_english_display_text(text, 45)
    assert wrapped.count("\n") == 1
    assert wrapped.replace("\n", " ") == text
    assert all(len(line) <= 45 for line in wrapped.splitlines())


def test_wrap_english_display_text_keeps_two_line_layout_when_limit_is_impossible(tmp_path):
    text = " ".join(["lengthyword"] * 12)
    wrapped = wrap_english_display_text(text, 20)
    assert wrapped.count("\n") == 1
    assert max(map(len, wrapped.splitlines())) > 20

    path = tmp_path / "english.srt"
    path.write_text(f"1\n00:00:01,000 --> 00:00:03,000\n{wrapped}\n", encoding="utf-8")
    assert count_overlong_srt_lines(path, 20) == 1


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
