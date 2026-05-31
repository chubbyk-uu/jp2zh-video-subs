from fill_ja_srt_gaps import (
    looks_like_noise,
    repeated_character_ratio,
    speech_clusters_for_gap,
    split_clip,
)
from srt_utils import Interval


def test_repeated_character_ratio():
    assert repeated_character_ratio("aaaa") == 1.0
    assert repeated_character_ratio("") == 1.0
    assert repeated_character_ratio("abcd") == 0.25


def test_looks_like_noise():
    assert looks_like_noise("", 3) is True
    assert looks_like_noise("ああ", 3) is True  # shorter than min chars
    assert looks_like_noise("ababab", 3) is True  # repeated 2-char token
    assert looks_like_noise("今日はいい天気", 3) is False


def test_split_clip():
    clips = split_clip(Interval(0, 10), 4)
    assert [(c.start, c.end) for c in clips] == [(0, 4), (4, 8), (8, 10)]
    assert len(split_clip(Interval(0, 3), 4)) == 1


def test_speech_clusters_for_gap_merges_close_segments():
    gap = Interval(0, 20)
    speech = [Interval(1, 3), Interval(3.5, 5), Interval(15, 18)]
    clusters = speech_clusters_for_gap(gap, speech, max_cluster_gap=2.0, pad=0.0)
    assert [(round(c.start, 1), round(c.end, 1)) for c in clusters] == [(1, 5), (15, 18)]
