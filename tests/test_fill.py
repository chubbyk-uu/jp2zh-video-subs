from argparse import Namespace

import fill_ja_srt_gaps as fill_module
from fill_ja_srt_gaps import (
    exceeds_compression_ratio,
    context_duplicate_fill_entries,
    fill_gaps,
    gap_windows,
    is_high_risk_repeat_phrase,
    looks_like_low_confidence_low_vad_support,
    looks_like_hallucination,
    looks_like_noise,
    normalize_phrase,
    repeated_hallucination_texts,
    srt_gaps_with_boundaries,
    speech_clusters_for_gap,
    split_clip_with_overlap,
)
from hallucination_filters import repeated_character_ratio
from srt_utils import Interval
from transcribe_ja_srt import SubtitleEntry
from quality_report import Entry


def test_repeated_character_ratio():
    assert repeated_character_ratio("aaaa") == 1.0
    assert repeated_character_ratio("") == 1.0
    assert repeated_character_ratio("abcd") == 0.25


def test_gap_windows_use_overlap_and_cover_trailing_gap():
    windows = gap_windows(Interval(0, 12), window_seconds=5, overlap_seconds=3)

    assert [(item.start, item.end) for item in windows] == [
        (0, 5),
        (2, 7),
        (4, 9),
        (6, 11),
        (8, 12),
    ]


def test_looks_like_noise():
    assert looks_like_noise("", 3) is True
    assert looks_like_noise("ああ", 3) is True  # shorter than min chars
    assert looks_like_noise("ababab", 3) is True  # repeated 2-char token
    assert looks_like_noise("今日はいい天気", 3) is False


def test_split_clip_with_overlap_only_splits_long_clips():
    assert [(c.start, c.end) for c in split_clip_with_overlap(Interval(0, 3), 4, 1)] == [(0, 3)]
    clips = split_clip_with_overlap(Interval(0, 10), 4, 1)
    assert [(c.start, c.end) for c in clips] == [(0, 4), (3, 7), (6, 10)]


def test_extreme_compression_ratio_filter_is_for_repetition_outliers():
    assert exceeds_compression_ratio(SubtitleEntry(0.0, 1.0, "普通の台詞", compression_ratio=3.0), 25.0) is False
    assert exceeds_compression_ratio(SubtitleEntry(0.0, 1.0, "いいからしゃべれ", compression_ratio=10.45), 25.0) is False
    assert exceeds_compression_ratio(SubtitleEntry(0.0, 1.0, "あっはっはっはっは", compression_ratio=29.2), 25.0) is True


def test_looks_like_hallucination_flags_only_platform_boilerplate():
    # Platform boilerplate.
    assert looks_like_hallucination("ご視聴ありがとうございました") is True
    assert looks_like_hallucination("チャンネル登録お願いします") is True
    assert looks_like_hallucination("最後まで見てくれてありがとう。また見てね!") is True
    assert looks_like_hallucination("ぜひ購読してサブスクリプションをお願いします") is True
    assert looks_like_hallucination("コメント欄と概要欄を見てください") is True
    assert looks_like_hallucination("AlphaFamilyを使っています") is True
    assert looks_like_hallucination("エルミックで画像を撮りました") is True
    assert looks_like_hallucination("それではまた") is True
    assert looks_like_hallucination("アーメン") is True
    assert looks_like_hallucination("笑い声") is True
    assert looks_like_hallucination("拍手") is True
    assert looks_like_hallucination("🐬🐬🐬") is True
    assert looks_like_hallucination("タンジェント") is True
    assert looks_like_hallucination("コサインタンジェント") is True
    # Ordinary dialogue phrases are not filtered by text alone.
    assert looks_like_hallucination("おやすみなさい") is False
    assert looks_like_hallucination("ありがとうございました") is False
    assert looks_like_hallucination("バイバイ") is False
    assert looks_like_hallucination("おはようございます") is False
    assert looks_like_hallucination("気持ちいい") is False
    assert looks_like_hallucination("やばい") is False
    assert looks_like_hallucination("すごい") is False
    assert looks_like_hallucination("お疲れ様でした") is False


def test_normalize_phrase_strips_trailing_punctuation():
    assert normalize_phrase("ありがとうございました。") == normalize_phrase("ありがとうございました")
    assert normalize_phrase("いいね！") == "いいね"


def test_is_high_risk_repeat_phrase_matches_fixed_greetings():
    assert is_high_risk_repeat_phrase("おやすみなさい") is True
    assert is_high_risk_repeat_phrase("どうもありがとうございました") is True
    assert is_high_risk_repeat_phrase("お疲れ様でした") is True
    assert is_high_risk_repeat_phrase("おいしい") is False
    assert is_high_risk_repeat_phrase("気持ちいい") is False


def test_repeated_hallucination_texts_requires_repeat_and_low_confidence():
    def entry(text, avg_logprob=-0.2, no_speech_prob=0.1):
        return SubtitleEntry(0.0, 1.0, text, avg_logprob, no_speech_prob)

    entries = (
        [entry("ありがとうございました", no_speech_prob=0.9)]
        + [entry("ありがとうございました。", no_speech_prob=0.9)]
        + [entry("ありがとうございました", no_speech_prob=0.9)] * 8
        + [entry("気持ちいい")] * 10
    )
    repeated = repeated_hallucination_texts(
        entries,
        min_repeats=10,
        no_speech_prob_at_least=0.75,
        avg_logprob_at_most=-0.8,
        high_risk_max_repeats=20,
    )
    assert "ありがとうございました" in repeated
    assert "気持ちいい" not in repeated


def test_repeated_hallucination_texts_can_use_low_avg_logprob():
    entries = [SubtitleEntry(0.0, 1.0, "またね", -0.9, 0.2) for _ in range(10)]

    repeated = repeated_hallucination_texts(
        entries,
        min_repeats=10,
        no_speech_prob_at_least=0.75,
        avg_logprob_at_most=-0.8,
        high_risk_max_repeats=20,
    )

    assert repeated == {"またね"}


def test_repeated_hallucination_texts_drops_extreme_high_risk_repeats():
    entries = [SubtitleEntry(0.0, 1.0, "おやすみなさい", -0.2, 0.1) for _ in range(20)]

    repeated = repeated_hallucination_texts(
        entries,
        min_repeats=10,
        no_speech_prob_at_least=0.75,
        avg_logprob_at_most=-0.8,
        high_risk_max_repeats=20,
    )

    assert repeated == {"おやすみなさい"}


def test_repeated_hallucination_texts_groups_high_risk_variants_by_core():
    # Greeting hallucinations carry varying trailing junk, so each exact variant
    # appears only once; they must still be counted together by the core phrase.
    entries = [
        SubtitleEntry(0.0, 1.0, "おやすみなさいはい", -0.2, 0.1),
        SubtitleEntry(10.0, 11.0, "おやすみなさいああ", -0.2, 0.1),
        SubtitleEntry(20.0, 21.0, "おやすみなさいうんうん", -0.2, 0.1),
        SubtitleEntry(30.0, 31.0, "今日はいい天気ですね", -0.2, 0.1),
    ]

    repeated = repeated_hallucination_texts(
        entries,
        min_repeats=10,
        no_speech_prob_at_least=0.75,
        avg_logprob_at_most=-0.8,
        high_risk_max_repeats=3,
    )

    assert repeated == {"おやすみなさいはい", "おやすみなさいああ", "おやすみなさいうんうん"}


def test_fill_gaps_with_no_entries_writes_empty_output(tmp_path):
    # A silent/music-only clip transcribes to nothing; gap filling must not crash,
    # it should just emit an empty SRT (no audio decode or model load needed).
    output = tmp_path / "out.srt"
    fills = tmp_path / "fills.srt"
    metadata = tmp_path / "fills.tsv"
    args = Namespace(
        input=None,
        output=output,
        fills_output=fills,
        fills_metadata_output=metadata,
    )

    stats = fill_gaps(args, model=None, existing_entries=[])

    assert stats.kept_entries == 0
    assert output.read_text(encoding="utf-8") == ""
    assert fills.read_text(encoding="utf-8") == ""
    # Metadata file still carries its header row.
    assert metadata.read_text(encoding="utf-8").startswith("status\treason")


def test_speech_clusters_for_gap_merges_close_segments():
    gap = Interval(0, 20)
    speech = [Interval(1, 3), Interval(3.5, 5), Interval(15, 18)]
    clusters = speech_clusters_for_gap(gap, speech, max_cluster_gap=2.0, pad=0.0)
    assert [(round(c.start, 1), round(c.end, 1)) for c in clusters] == [(1, 5), (15, 18)]


def test_srt_gaps_with_boundaries_includes_leading_and_trailing_gaps():
    entries = [Entry(1, 10, 20, "a"), Entry(2, 30, 40, "b")]

    gaps = srt_gaps_with_boundaries(entries, audio_duration=50)

    assert [(gap.start, gap.end) for gap in gaps] == [(0.0, 10), (20, 30), (40, 50)]


def test_fill_uses_gap_local_vad_for_each_gap(monkeypatch, tmp_path):
    calls = {"local": 0}

    def local_vad(*args, **kwargs):
        calls["local"] += 1
        return []

    monkeypatch.setattr(fill_module, "decode_audio", lambda *args, **kwargs: [0] * 160000)
    monkeypatch.setattr(fill_module, "speech_intervals_from_gap_audio", local_vad)

    args = Namespace(
        input=None,
        audio=tmp_path / "audio.wav",
        output=tmp_path / "out.srt",
        fills_output=tmp_path / "fills.srt",
        fills_metadata_output=tmp_path / "fills.tsv",
        vad_min_silence_ms=500,
        vad_speech_pad_ms=400,
        existing_pad_seconds=0.1,
        min_gap_seconds=2.0,
        min_speech_seconds=1.0,
        gap_local_vad_threshold=0.60,
        gap_local_vad_window_min_gap_seconds=6.0,
        gap_local_vad_window_seconds=5.0,
        gap_local_vad_window_overlap_seconds=3.0,
        gap_local_asr_pad_seconds=1.0,
        gap_local_asr_max_clip_seconds=30.0,
        gap_local_asr_overlap_seconds=5.0,
        main_local_batch_size=24,
        max_cluster_gap=2.0,
        max_existing_overlap_seconds=1.0,
        min_clip_seconds=0.6,
        min_fill_chars=1,
        duplicate_window_seconds=8.0,
        max_fill_compression_ratio=25.0,
        hallucination_min_repeats=10,
        hallucination_repeat_no_speech_prob=0.75,
        hallucination_repeat_avg_logprob=-0.8,
        hallucination_high_risk_max_repeats=3,
    )
    existing = [Entry(1, 1.0, 2.0, "a")]

    fill_gaps(args, model=object(), existing_entries=existing)

    assert calls["local"] == 3


def test_low_confidence_low_vad_support_filter_targets_long_weak_entries(monkeypatch):
    args = Namespace(
        fill_support_min_chars=8,
        fill_support_avg_logprob=-0.95,
        fill_support_no_speech_prob=0.45,
        fill_support_vad_threshold=0.5,
        fill_support_pad_seconds=0.2,
        fill_support_max_ratio=0.45,
        vad_min_silence_ms=500,
        vad_speech_pad_ms=400,
    )

    weak_long = SubtitleEntry(10.0, 14.0, "明日は早く出発します。", avg_logprob=-1.2, no_speech_prob=0.5)
    short_reaction = SubtitleEntry(20.0, 21.0, "はい", avg_logprob=-1.2, no_speech_prob=0.9)
    supported_long = SubtitleEntry(30.0, 32.0, "今日はいい天気ですね。", avg_logprob=-1.2, no_speech_prob=0.5)

    monkeypatch.setattr(fill_module, "fill_vad_support_seconds", lambda *args, **kwargs: 0.5)
    assert looks_like_low_confidence_low_vad_support([], weak_long, args) is True
    assert looks_like_low_confidence_low_vad_support([], short_reaction, args) is False

    monkeypatch.setattr(fill_module, "fill_vad_support_seconds", lambda *args, **kwargs: 1.5)
    assert looks_like_low_confidence_low_vad_support([], supported_long, args) is False


def test_context_key_strips_punctuation_and_whitespace():
    assert fill_module.context_key("テスト、です！") == "テストです"
    assert fill_module.context_key("「引用」…（笑）") == "引用笑"
    assert fill_module.context_key("いい天気 ですね。") == "いい天気ですね"


def test_context_duplicate_fill_entries_drop_punctuation_only_variant():
    existing = [Entry(1, 10.0, 12.0, "今日は、いい天気ですね！")]
    fills = [SubtitleEntry(12.1, 13.0, "今日はいい天気ですね", avg_logprob=-0.2, no_speech_prob=0.1)]

    dropped = context_duplicate_fill_entries(fills, existing)

    assert dropped == {id(fills[0])}


def test_context_duplicate_fill_entries_drop_existing_fragment():
    existing = [Entry(1, 10.0, 12.0, "今日はいい天気ですね")]
    fills = [SubtitleEntry(12.1, 13.0, "いい天気ですね", avg_logprob=-0.2, no_speech_prob=0.1)]

    dropped = context_duplicate_fill_entries(fills, existing)

    assert dropped == {id(fills[0])}


def test_context_duplicate_fill_entries_drop_weaker_fill_fragment():
    existing = []
    fills = [
        SubtitleEntry(20.0, 21.8, "明日は早く出発します", avg_logprob=-0.2, no_speech_prob=0.1),
        SubtitleEntry(21.8, 22.8, "早く出発します", avg_logprob=-0.8, no_speech_prob=0.6),
    ]

    dropped = context_duplicate_fill_entries(fills, existing)

    assert dropped == {id(fills[1])}


def test_context_duplicate_fill_entries_keeps_far_similar_text():
    existing = [Entry(1, 10.0, 11.0, "また行きます")]
    fills = [SubtitleEntry(20.0, 21.0, "また", avg_logprob=-0.2, no_speech_prob=0.1)]

    dropped = context_duplicate_fill_entries(fills, existing)

    assert dropped == set()


def test_looks_like_looping_repetition_catches_in_segment_loops():
    from hallucination_filters import looks_like_noise
    assert looks_like_noise("はい、はい、はい、はい、はい、はい、はい、はい、はい、はい、はい", 1)
    assert looks_like_noise("おやすみなさいうんうんうんうんうんうんうんうんうんうん", 1)
    # natural short responses and normal sentences survive
    assert not looks_like_noise("はい", 1)
    assert not looks_like_noise("今日はいい天気ですね", 1)
