from transcribe_ja_srt import SubtitleEntry
from transcribe_ja_srt_qwen import (
    ISOLATED_INTERJECTION_CORES,
    _RawItem,
    _interjection_core,
    drop_isolated_interjections,
    sentences_from_alignment,
    uncovered_gap_spans,
)


def aligned_entries(text: str, chars: list[tuple[str, float, float]], **overrides):
    """Build cues from `text` with one aligner item per content character."""
    items = [_RawItem(c, s, e) for c, s, e in chars]
    kwargs = dict(
        offset=0.0,
        max_chars=26,
        max_duration=8.0,
        min_duration=0.0,
        max_internal_gap=2.0,
        max_char_seconds=0.5,
    )
    kwargs.update(overrides)
    return sentences_from_alignment(text, items, **kwargs)


def test_interjection_core_strips_punctuation_elongation_small_kana():
    assert _interjection_core("あー…。") == "あ"
    assert _interjection_core("うーん。") == "うん"
    assert _interjection_core("んっ、んっ") == "んん"
    assert _interjection_core("ねえ、ねえ。") == "ねえねえ"


def test_interjection_core_handles_nfkc_ellipsis():
    # NFKC turns … into ASCII "...", which must also be stripped (regression:
    # 「あ…」 previously failed to match because "." was not in the drop set).
    assert _interjection_core("「あ…」") == "あ"
    assert _interjection_core("「あ…」") in ISOLATED_INTERJECTION_CORES


def test_interjection_core_keeps_real_words():
    assert _interjection_core("気持ちいい") not in ISOLATED_INTERJECTION_CORES
    assert _interjection_core("いくよ") not in ISOLATED_INTERJECTION_CORES
    assert _interjection_core("だめ…") not in ISOLATED_INTERJECTION_CORES


def test_isolated_filler_walled_by_silence_is_dropped():
    entries = [
        SubtitleEntry(0.0, 1.0, "今日はいい天気ですね"),
        SubtitleEntry(10.0, 10.5, "うん。"),
        SubtitleEntry(20.0, 21.0, "そうですね"),
    ]
    kept, dropped = drop_isolated_interjections(entries, min_silence=3.0)
    assert [e.text for e in kept] == ["今日はいい天気ですね", "そうですね"]
    assert [e.text for e in dropped] == ["うん。"]


def test_filler_next_to_speech_is_kept():
    # A genuine one-word reply sits close to the line it answers: the lead gap is
    # under min_silence, so neither rule fires.
    entries = [
        SubtitleEntry(0.0, 1.0, "行きましょうか"),
        SubtitleEntry(1.5, 2.0, "うん。"),
        SubtitleEntry(10.0, 11.0, "次の話です"),
    ]
    kept, dropped = drop_isolated_interjections(entries, min_silence=3.0)
    assert dropped == []
    assert len(kept) == 3


def test_filler_chain_is_dropped_even_next_to_speech():
    # Music-bed signature: 3+ bare fillers in a row with small gaps. The chain rule
    # fires even though no individual cue is walled by min_silence.
    fillers = [SubtitleEntry(3.0 + 2.5 * i, 3.5 + 2.5 * i, "うん。") for i in range(4)]
    entries = [SubtitleEntry(0.0, 1.0, "そろそろ始めようか"), *fillers, SubtitleEntry(12.0, 13.0, "次の話です")]
    kept, dropped = drop_isolated_interjections(entries, min_silence=3.0)
    assert [e.text for e in kept] == ["そろそろ始めようか", "次の話です"]
    assert len(dropped) == 4


def test_short_filler_group_bracketed_by_silence_is_dropped():
    # Two fillers (below run_min) still go when the group as a whole is walled by
    # min_silence on both sides.
    entries = [
        SubtitleEntry(0.0, 1.0, "今日はいい天気ですね"),
        SubtitleEntry(5.0, 5.5, "うん。"),
        SubtitleEntry(6.5, 7.0, "ああ。"),
        SubtitleEntry(15.0, 16.0, "そうですね"),
    ]
    kept, dropped = drop_isolated_interjections(entries, min_silence=3.0)
    assert [e.text for e in dropped] == ["うん。", "ああ。"]
    assert len(kept) == 2


def test_real_word_cue_is_never_dropped_even_isolated():
    entries = [
        SubtitleEntry(0.0, 1.0, "今日はいい天気ですね"),
        SubtitleEntry(10.0, 10.5, "だめ"),
        SubtitleEntry(20.0, 21.0, "そうですね"),
    ]
    kept, dropped = drop_isolated_interjections(entries, min_silence=3.0)
    assert dropped == []
    assert len(kept) == 3


def test_real_word_cue_breaks_a_filler_chain():
    entries = [
        SubtitleEntry(0.0, 1.0, "そろそろ始めようか"),
        SubtitleEntry(2.0, 2.5, "あ。"),
        SubtitleEntry(3.0, 3.5, "あ。"),
        SubtitleEntry(4.0, 5.0, "気持ちいい"),
        SubtitleEntry(5.5, 6.0, "ん。"),
        SubtitleEntry(6.5, 7.0, "ん。"),
        SubtitleEntry(8.0, 9.0, "次の話です"),
    ]
    kept, dropped = drop_isolated_interjections(entries, min_silence=3.0)
    # Each filler run is only 2 long and hugs real speech, so everything stays.
    assert dropped == []
    assert len(kept) == 7


def test_list_edges_count_as_infinite_silence():
    entries = [SubtitleEntry(50.0, 50.5, "うん。")]
    kept, dropped = drop_isolated_interjections(entries, min_silence=3.0)
    assert kept == []
    assert [e.text for e in dropped] == ["うん。"]


def test_collapse_leading_filler_run_keeps_real_speech_and_its_timing():
    # うん、うん、うん、一人。 -> うん、一人。 The kept うん is the one adjacent to
    # the real words, so the cue starts at its aligner time (1.2), not at 0.0 and
    # not at a proportionally re-derived guess.
    chars = [
        ("う", 0.0, 0.1), ("ん", 0.1, 0.2),
        ("う", 0.6, 0.7), ("ん", 0.7, 0.8),
        ("う", 1.2, 1.3), ("ん", 1.3, 1.4),
        ("一", 1.8, 2.0), ("人", 2.0, 2.2),
    ]
    entries = aligned_entries("うん、うん、うん、一人。", chars)
    assert len(entries) == 1
    assert entries[0].text == "うん、一人。"
    assert entries[0].start == 1.2
    assert entries[0].end == 2.2


def test_collapse_trailing_filler_run_keeps_first_instance():
    chars = [
        ("一", 0.0, 0.2), ("人", 0.2, 0.4),
        ("う", 1.0, 1.1), ("ん", 1.1, 1.2),
        ("う", 1.6, 1.7), ("ん", 1.7, 1.8),
        ("う", 2.2, 2.3), ("ん", 2.3, 2.4),
    ]
    entries = aligned_entries("一人、うん、うん、うん。", chars)
    assert len(entries) == 1
    assert entries[0].text == "一人、うん、"
    assert entries[0].start == 0.0
    assert entries[0].end == 1.2


def test_collapse_whole_cue_repetition_feeds_the_silence_gate():
    # A cue that is nothing but repetition collapses to its first instance; the
    # result is a plain single filler that drop_isolated_interjections then
    # judges with the usual silence/chain rules.
    chars = [
        ("う", 0.0, 0.1), ("ん", 0.1, 0.2),
        ("う", 0.5, 0.6), ("ん", 0.6, 0.7),
        ("う", 1.0, 1.1), ("ん", 1.1, 1.2),
    ]
    entries = aligned_entries("うんうんうん。", chars)
    assert len(entries) == 1
    assert entries[0].text == "うん"
    assert entries[0].start == 0.0
    assert entries[0].end == 0.2
    assert _interjection_core(entries[0].text) in ISOLATED_INTERJECTION_CORES


def test_collapse_keeps_lexical_double_mora_interjections():
    # ええ (huh?/yes) and ああ are interjection words in their own right, listed in
    # ISOLATED_INTERJECTION_CORES — not padding. They must survive collapse intact
    # (regression: ええ。 was being rewritten to え).
    for word in ("ええ", "ああ", "おお"):
        chars = [(word[0], 0.0, 0.1), (word[1], 0.1, 0.2)]
        entries = aligned_entries(f"{word}。", chars)
        assert entries[0].text == f"{word}。", word


def test_collapse_keeps_lexical_interjection_before_real_speech():
    chars = [
        ("あ", 0.0, 0.1), ("あ", 0.1, 0.2),
        ("一", 0.6, 0.8), ("人", 0.8, 1.0),
    ]
    entries = aligned_entries("ああ、一人。", chars)
    assert entries[0].text == "ああ、一人。"


def test_collapse_never_touches_repetition_inside_real_words():
    # ああいう starts with あ×2 but the run's right edge has no punctuation — the
    # boundary guard keeps real words intact.
    chars = [
        ("あ", 0.0, 0.1), ("あ", 0.1, 0.2),
        ("い", 0.2, 0.3), ("う", 0.3, 0.4),
        ("人", 0.4, 0.6),
    ]
    entries = aligned_entries("ああいう人。", chars)
    assert len(entries) == 1
    assert entries[0].text == "ああいう人。"


def test_collapse_requires_punctuation_boundary_before_real_speech():
    # うんうんうん一人 (no punctuation at the run edge): conservative, no collapse.
    chars = [
        ("う", 0.0, 0.1), ("ん", 0.1, 0.2),
        ("う", 0.5, 0.6), ("ん", 0.6, 0.7),
        ("う", 1.0, 1.1), ("ん", 1.1, 1.2),
        ("一", 1.4, 1.6), ("人", 1.6, 1.8),
    ]
    entries = aligned_entries("うんうんうん一人。", chars)
    assert len(entries) == 1
    assert entries[0].text == "うんうんうん一人。"


def test_collapse_can_be_disabled():
    chars = [
        ("う", 0.0, 0.1), ("ん", 0.1, 0.2),
        ("う", 0.6, 0.7), ("ん", 0.7, 0.8),
        ("一", 1.2, 1.4), ("人", 1.4, 1.6),
    ]
    entries = aligned_entries("うん、うん、一人。", chars, collapse_fillers=False)
    assert entries[0].text == "うん、うん、一人。"


def test_internal_gap_keeps_short_sentence_tail_fragment():
    chars = [
        ("何", 0.0, 0.1),
        ("欲", 0.2, 0.3),
        ("し", 0.3, 0.4),
        ("い", 0.4, 0.5),
        ("ん", 0.5, 0.6),
        ("だ", 5.2, 5.2),
    ]
    entries = aligned_entries("何欲しいんだ。", chars)
    assert [e.text for e in entries] == ["何欲しいんだ。"]


def test_internal_gap_keeps_particle_prefix_fragment():
    chars = [
        ("会", 0.0, 0.1),
        ("長", 0.1, 0.2),
        ("の", 0.2, 0.3),
        ("せ", 3.6, 3.7),
        ("い", 3.7, 3.8),
        ("で", 3.8, 3.9),
        ("す", 3.9, 4.0),
    ]
    entries = aligned_entries("会長のせいです。", chars)
    assert [e.text for e in entries] == ["会長のせいです。"]


def test_internal_gap_keeps_verb_conjugation_fragment():
    chars = [
        ("出", 0.0, 0.1),
        ("ち", 2.5, 2.6),
        ("ゃ", 2.6, 2.7),
        ("う", 2.7, 2.8),
        ("か", 2.8, 2.9),
        ("ら", 2.9, 3.0),
    ]
    entries = aligned_entries("出ちゃうから。", chars)
    assert [e.text for e in entries] == ["出ちゃうから。"]


def test_internal_gap_keeps_noda_sentence_tail():
    chars = [
        ("ど", 0.0, 0.1),
        ("う", 0.1, 0.2),
        ("し", 0.2, 0.3),
        ("た", 0.3, 0.4),
        ("ん", 4.4, 4.5),
        ("だ", 4.5, 4.6),
    ]
    entries = aligned_entries("どうしたんだ？", chars)
    assert [e.text for e in entries] == ["どうしたんだ？"]


def test_internal_gap_keeps_masen_polite_tail():
    chars = [
        ("す", 0.0, 0.1),
        ("み", 0.1, 0.2),
        ("ま", 4.0, 4.1),
        ("せ", 4.1, 4.2),
        ("ん", 4.2, 4.3),
    ]
    entries = aligned_entries("すみません。", chars)
    assert [e.text for e in entries] == ["すみません。"]


def test_internal_gap_still_splits_non_fragment_pause():
    chars = [
        ("早", 0.0, 0.1),
        ("く", 0.1, 0.2),
        ("来", 4.0, 4.1),
        ("て", 4.1, 4.2),
    ]
    entries = aligned_entries("早く来て。", chars)
    assert [e.text for e in entries] == ["早く", "来て。"]


def test_collapse_small_kana_rides_along():
    # んっ、んっ、んっ collapses to a single ん-instance (small kana ride along),
    # which the interjection core machinery then recognises.
    chars = [
        ("ん", 0.0, 0.1), ("っ", 0.1, 0.2),
        ("ん", 0.6, 0.7), ("っ", 0.7, 0.8),
        ("ん", 1.2, 1.3), ("っ", 1.3, 1.4),
    ]
    entries = aligned_entries("んっ、んっ、んっ。", chars)
    assert len(entries) == 1
    assert _interjection_core(entries[0].text) in ISOLATED_INTERJECTION_CORES


def test_uncovered_gap_spans_finds_internal_and_edge_gaps():
    entries = [
        SubtitleEntry(15.0, 16.0, "一行目"),
        SubtitleEntry(18.0, 19.0, "二行目"),
        SubtitleEntry(40.0, 41.0, "三行目"),
    ]
    spans = uncovered_gap_spans(entries, duration=60.0, min_gap=10.0)
    # Leading silence, the 19->40 gap, and the trailing tail; the 2s gap is ignored.
    assert [(s.start, s.end) for s in spans] == [(0.0, 15.0), (19.0, 40.0), (41.0, 60.0)]


def test_uncovered_gap_spans_handles_overlapping_cues():
    # prev_end must track the furthest end seen, or an enclosed short cue would
    # reopen an already-covered region.
    entries = [
        SubtitleEntry(0.0, 30.0, "長い行"),
        SubtitleEntry(5.0, 6.0, "中の行"),
    ]
    spans = uncovered_gap_spans(entries, duration=45.0, min_gap=10.0)
    assert [(s.start, s.end) for s in spans] == [(30.0, 45.0)]


def test_uncovered_gap_spans_empty_entries_covers_whole_timeline():
    spans = uncovered_gap_spans([], duration=20.0, min_gap=10.0)
    assert [(s.start, s.end) for s in spans] == [(0.0, 20.0)]


def test_uncovered_gap_spans_zero_min_gap_short_timeline():
    assert uncovered_gap_spans([], duration=5.0, min_gap=10.0) == []


def test_unanchored_hai_run_is_dropped():
    # Metronomic はい far from any real line (quiet audio labelled as 「はい」)
    # is an ordinary filler run and goes.
    hais = [SubtitleEntry(8.0 + 2.5 * i, 8.8 + 2.5 * i, "はい。") for i in range(4)]
    entries = [SubtitleEntry(0.0, 1.0, "始めようか"), *hais, SubtitleEntry(30.0, 31.0, "次です")]
    kept, dropped = drop_isolated_interjections(entries, min_silence=3.0)
    assert [e.text for e in kept] == ["始めようか", "次です"]
    assert len(dropped) == 4


def test_anchored_hai_reply_is_kept_even_walled_by_silence():
    # A はい answering a line that just ended is a genuine reply: exempt from the
    # silence-bracket rule even with nothing else around it.
    entries = [
        SubtitleEntry(0.0, 1.0, "準備はいい？"),
        SubtitleEntry(2.5, 3.3, "はい。"),
        SubtitleEntry(20.0, 21.0, "では行こう"),
    ]
    kept, dropped = drop_isolated_interjections(entries, min_silence=3.0)
    assert dropped == []
    assert len(kept) == 3


def test_unanchored_lone_hai_walled_by_silence_is_dropped():
    # The same lone はい drifting 9s after the question is noise, not an answer.
    entries = [
        SubtitleEntry(0.0, 1.0, "準備はいい？"),
        SubtitleEntry(10.0, 10.8, "はい。"),
        SubtitleEntry(20.0, 21.0, "では行こう"),
    ]
    kept, dropped = drop_isolated_interjections(entries, min_silence=3.0)
    assert [e.text for e in dropped] == ["はい。"]
    assert len(kept) == 2


def test_anchored_hai_survives_while_following_noise_run_drops():
    # Real pattern: a genuine answer right after the question, then a metronomic
    # noise run. The anchored head is kept; only the unanchored tail goes, and the
    # anchored reply does not chain with it.
    entries = [
        SubtitleEntry(0.0, 1.5, "できてますか。"),
        SubtitleEntry(1.5, 2.3, "はい。"),
        SubtitleEntry(9.5, 10.3, "はい。"),
        SubtitleEntry(17.5, 18.3, "はい。"),
        SubtitleEntry(24.5, 25.3, "はい。"),
        SubtitleEntry(40.0, 41.0, "次です"),
    ]
    kept, dropped = drop_isolated_interjections(entries, min_silence=3.0)
    assert [e.text for e in kept] == ["できてますか。", "はい。", "次です"]
    assert kept[1].start == 1.5
    assert len(dropped) == 3


def test_hai_in_a_mixed_filler_chain_is_dropped():
    # はい buried in a うん/あ filler run joins the chain and goes with it.
    entries = [
        SubtitleEntry(0.0, 1.0, "始めようか"),
        SubtitleEntry(5.0, 5.8, "うん。"),
        SubtitleEntry(7.0, 7.8, "はい。"),
        SubtitleEntry(9.0, 9.8, "あ。"),
        SubtitleEntry(20.0, 21.0, "次です"),
    ]
    kept, dropped = drop_isolated_interjections(entries, min_silence=3.0)
    assert [e.text for e in kept] == ["始めようか", "次です"]
    assert [e.text for e in dropped] == ["うん。", "はい。", "あ。"]


def test_pair_of_hai_is_kept():
    # Two はい (below the 3-run threshold) are a plausible real double reply; kept.
    entries = [
        SubtitleEntry(0.0, 1.0, "いい？"),
        SubtitleEntry(2.0, 2.8, "はい。"),
        SubtitleEntry(3.0, 3.8, "はい。"),
        SubtitleEntry(20.0, 21.0, "次です"),
    ]
    kept, dropped = drop_isolated_interjections(entries, min_silence=3.0)
    assert dropped == []
    assert len(kept) == 4


def test_disabled_thresholds_keep_everything():
    entries = [
        SubtitleEntry(0.0, 0.5, "うん。"),
        SubtitleEntry(10.0, 10.5, "うん。"),
        SubtitleEntry(20.0, 20.5, "うん。"),
    ]
    kept, dropped = drop_isolated_interjections(entries, min_silence=0.0, run_min=0)
    assert kept == entries
    assert dropped == []
