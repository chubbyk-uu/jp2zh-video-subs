from argparse import Namespace

from fill_ja_srt_gaps import (
    fill_gaps,
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
