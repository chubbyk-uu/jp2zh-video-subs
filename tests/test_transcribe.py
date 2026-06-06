import types

from transcribe_ja_srt import (
    SubtitleEntry,
    drop_adjacent_near_duplicates,
    estimate_display_duration,
    filter_hallucination_entries,
    filter_main_local_entries,
    merge_orphan_prefix_entries,
    merge_short_entries,
    resolve_overlaps,
    sliding_windows,
    speech_clusters,
    split_clip_with_overlap,
)
from srt_utils import Interval


def _main_filter_args(**overrides):
    base = dict(
        main_min_chars=1,
        main_max_compression_ratio=25.0,
        main_duplicate_window_seconds=2.0,
        hallucination_min_repeats=10,
        hallucination_repeat_no_speech_prob=0.75,
        hallucination_repeat_avg_logprob=-0.80,
        hallucination_high_risk_max_repeats=3,
    )
    base.update(overrides)
    return types.SimpleNamespace(**base)


def test_filter_main_local_keeps_short_responses_drops_moaning():
    entries = [
        SubtitleEntry(1.0, 2.0, "はい"),
        SubtitleEntry(3.0, 4.0, "うん"),
        SubtitleEntry(5.0, 7.0, "ああああ"),
        SubtitleEntry(8.0, 10.0, "今日はいい天気ですね"),
    ]
    kept, dropped = filter_main_local_entries(entries, _main_filter_args())
    assert [e.text for e in kept] == ["はい", "うん", "今日はいい天気ですね"]
    assert [e.text for e in dropped] == ["ああああ"]


def test_filter_main_local_drops_adjacent_duplicate_from_clip_overlap():
    entries = [
        SubtitleEntry(10.0, 11.0, "こんにちは"),
        SubtitleEntry(10.5, 11.5, "こんにちは"),
        SubtitleEntry(30.0, 31.0, "こんにちは"),
    ]
    kept, dropped = filter_main_local_entries(entries, _main_filter_args())
    # The overlap duplicate at 10.5 is removed; the far-apart one at 30s survives.
    assert [(e.start, e.text) for e in kept] == [(10.0, "こんにちは"), (30.0, "こんにちは")]
    assert len(dropped) == 1


def test_drop_adjacent_near_duplicates_keeps_fuller_twin():
    entries = [
        SubtitleEntry(10.0, 10.36, "いやいや今選んでください"),       # squeezed twin
        SubtitleEntry(10.36, 11.94, "いやいや、今選んでください"),     # fuller version
        SubtitleEntry(20.0, 21.0, "はい"),
        SubtitleEntry(21.0, 23.0, "ありがとうございます"),            # adjacent but unrelated
    ]
    kept = drop_adjacent_near_duplicates(entries, max_gap=0.5, similarity=0.6, squeeze_seconds=0.8)
    assert [e.text for e in kept] == ["いやいや、今選んでください", "はい", "ありがとうございます"]


def test_drop_adjacent_near_duplicates_keeps_genuine_repeats_at_normal_duration():
    # Real repeated moaning at normal durations must NOT be deduped — only the
    # squeezed flash twin is removed.
    entries = [
        SubtitleEntry(10.0, 11.5, "気持ちいい"),
        SubtitleEntry(11.5, 13.0, "気持ちいい、気持ちいい"),
        SubtitleEntry(13.0, 14.5, "気持ちいい?"),
    ]
    kept = drop_adjacent_near_duplicates(entries, max_gap=0.5, similarity=0.6, squeeze_seconds=0.8)
    assert len(kept) == 3


def test_filter_main_local_repeat_backstop_drops_high_risk_signoff():
    entries = [SubtitleEntry(float(i * 30), float(i * 30 + 1), "おやすみなさい") for i in range(4)]
    kept, dropped = filter_main_local_entries(entries, _main_filter_args())
    assert kept == []
    assert len(dropped) == 4


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


def test_sliding_windows_uses_overlap_step():
    windows = sliding_windows(20.0, window_seconds=8.0, overlap_seconds=4.0)

    assert [(item.start, item.end) for item in windows] == [
        (0.0, 8.0),
        (4.0, 12.0),
        (8.0, 16.0),
        (12.0, 20.0),
    ]


def test_speech_clusters_pads_and_merges_nearby_intervals():
    # (10,12)+(13.5,14) merge by the 2s cluster gap into (10,14); (20,21) stays
    # separate. Padding by 3s makes the two padded clusters touch at 17.0, so the
    # post-pad merge fuses them rather than transcribing the overlap twice.
    clusters = speech_clusters(
        [Interval(10.0, 12.0), Interval(13.5, 14.0), Interval(20.0, 21.0)],
        max_cluster_gap=2.0,
        pad_seconds=3.0,
        audio_duration=30.0,
    )

    assert [(item.start, item.end) for item in clusters] == [(7.0, 24.0)]


def test_speech_clusters_keeps_distant_clusters_separate():
    # A real silence gap wider than 2*pad must survive the post-pad merge.
    clusters = speech_clusters(
        [Interval(10.0, 12.0), Interval(40.0, 41.0)],
        max_cluster_gap=2.0,
        pad_seconds=3.0,
        audio_duration=60.0,
    )

    assert [(item.start, item.end) for item in clusters] == [(7.0, 15.0), (37.0, 44.0)]


def test_split_clip_with_overlap_keeps_context_between_long_clips():
    clips = split_clip_with_overlap(Interval(0.0, 100.0), max_clip_seconds=45.0, overlap_seconds=5.0)

    assert [(item.start, item.end) for item in clips] == [
        (0.0, 45.0),
        (40.0, 85.0),
        (80.0, 100.0),
    ]
