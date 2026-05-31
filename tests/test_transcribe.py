from transcribe_ja_srt import (
    SubtitleEntry,
    estimate_display_duration,
    merge_short_entries,
    resolve_overlaps,
)


def test_resolve_overlaps_trims_overlap():
    out = resolve_overlaps([SubtitleEntry(0, 5, "x"), SubtitleEntry(3, 6, "y")])
    assert out[0].end == 3
    assert out[1].start == 3


def test_resolve_overlaps_sorts_by_start():
    out = resolve_overlaps([SubtitleEntry(5, 6, "b"), SubtitleEntry(0, 1, "a")])
    assert [e.text for e in out] == ["a", "b"]


def test_resolve_overlaps_keeps_same_start_nonzero():
    # Two cues sharing a start time must not be trimmed to zero duration.
    out = resolve_overlaps([SubtitleEntry(0, 2, "a"), SubtitleEntry(0, 5, "b")])
    assert out[0].end == 2


def test_estimate_display_duration_clamps():
    assert estimate_display_duration("", 1.0, 10.0) == 1.0
    assert estimate_display_duration("あ" * 100, 1.0, 10.0) == 10.0


def test_merge_short_entries_merges_trailing_punctuation():
    entries = [SubtitleEntry(0, 1, "はい"), SubtitleEntry(1.2, 2, "。")]
    merged = merge_short_entries(entries, max_merge_gap=1.0, max_chars=42)
    assert len(merged) == 1
    assert merged[0].text == "はい。"
    assert merged[0].end == 2
