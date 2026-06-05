from argparse import Namespace

from fill_ja_srt_gaps import (
    exceeds_compression_ratio,
    fill_gaps,
    gap_local_vad_threshold,
    is_high_risk_repeat_phrase,
    looks_like_hallucination,
    looks_like_noise,
    normalize_phrase,
    repeated_character_ratio,
    repeated_hallucination_texts,
    speech_clusters_for_gap,
    split_clip,
    split_clip_with_overlap,
)
from srt_utils import Interval
from transcribe_ja_srt import SubtitleEntry


def test_repeated_character_ratio():
    assert repeated_character_ratio("aaaa") == 1.0
    assert repeated_character_ratio("") == 1.0
    assert repeated_character_ratio("abcd") == 0.25


def test_gap_local_vad_threshold_scales_with_log_duration():
    assert gap_local_vad_threshold(10, 0.1, 0.5) == 0.5
    assert gap_local_vad_threshold(30, 0.1, 0.5) == 0.5
    assert round(gap_local_vad_threshold(300, 0.1, 0.5), 2) == 0.3
    assert gap_local_vad_threshold(3000, 0.1, 0.5) == 0.1


def test_looks_like_noise():
    assert looks_like_noise("", 3) is True
    assert looks_like_noise("ああ", 3) is True  # shorter than min chars
    assert looks_like_noise("ababab", 3) is True  # repeated 2-char token
    assert looks_like_noise("今日はいい天気", 3) is False


def test_split_clip():
    clips = split_clip(Interval(0, 10), 4)
    assert [(c.start, c.end) for c in clips] == [(0, 4), (4, 8), (8, 10)]
    assert len(split_clip(Interval(0, 3), 4)) == 1


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
    assert looks_like_hallucination("それではまた") is True
    assert looks_like_hallucination("アーメン") is True
    assert looks_like_hallucination("笑い声") is True
    assert looks_like_hallucination("拍手") is True
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
