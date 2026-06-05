from transcribe_ja_srt import (
    SubtitleEntry,
    estimate_display_duration,
    filter_hallucination_entries,
    merge_orphan_prefix_entries,
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


def test_merge_short_entries_preserves_confidence_metadata():
    entries = [
        SubtitleEntry(0, 1, "あ", avg_logprob=-0.2, no_speech_prob=0.1, compression_ratio=0.8),
        SubtitleEntry(1.1, 2, "い", avg_logprob=-0.7, no_speech_prob=0.6, compression_ratio=1.4),
    ]
    merged = merge_short_entries(entries, max_merge_gap=1.0, max_chars=42)
    assert len(merged) == 1
    assert merged[0].avg_logprob == -0.7
    assert merged[0].no_speech_prob == 0.6
    assert merged[0].compression_ratio == 1.4


def test_filter_hallucination_entries_removes_main_asr_boilerplate_and_symbols():
    entries = [
        SubtitleEntry(0, 1, "今日はいい天気ですね"),
        SubtitleEntry(1, 2, "ご視聴ありがとうございました"),
        SubtitleEntry(2, 3, "ありがとうございました"),
        SubtitleEntry(30, 31, "ありがとうございました"),
        SubtitleEntry(40, 41, "🐬🐬🐬"),
        SubtitleEntry(42, 43, "タンジェント"),
    ]

    kept, filtered = filter_hallucination_entries(entries)

    assert [entry.text for entry in kept] == ["今日はいい天気ですね", "ありがとうございました"]
    assert [entry.text for entry in filtered] == [
        "ご視聴ありがとうございました",
        "ありがとうございました",
        "🐬🐬🐬",
        "タンジェント",
    ]


def test_merge_orphan_prefix_entries_joins_broken_words():
    entries = [
        SubtitleEntry(0, 1, "気"),
        SubtitleEntry(5, 6, "持ちいい"),
        SubtitleEntry(10, 11, "ブ"),
        SubtitleEntry(16, 17, "ックピット"),
        SubtitleEntry(20, 21, "さ"),
        SubtitleEntry(25, 26, "っきから"),
    ]

    merged = merge_orphan_prefix_entries(entries, max_gap=10.0, max_duration=12.0, max_chars=42)

    assert [entry.text for entry in merged] == ["気持ちいい", "ブックピット", "さっきから"]


def test_merge_orphan_prefix_entries_does_not_join_normal_short_lines():
    entries = [
        SubtitleEntry(0, 1, "はい"),
        SubtitleEntry(2, 3, "頑張って"),
        SubtitleEntry(4, 5, "あ"),
        SubtitleEntry(6, 7, "そうです"),
    ]

    merged = merge_orphan_prefix_entries(entries, max_gap=10.0, max_duration=12.0, max_chars=42)

    assert [entry.text for entry in merged] == ["はい", "頑張って", "あ", "そうです"]
