from transcribe_ja_srt import SubtitleEntry
from transcribe_ja_srt_qwen import (
    ISOLATED_INTERJECTION_CORES,
    _interjection_core,
    drop_isolated_interjections,
)


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


def test_disabled_thresholds_keep_everything():
    entries = [
        SubtitleEntry(0.0, 0.5, "うん。"),
        SubtitleEntry(10.0, 10.5, "うん。"),
        SubtitleEntry(20.0, 20.5, "うん。"),
    ]
    kept, dropped = drop_isolated_interjections(entries, min_silence=0.0, run_min=0)
    assert kept == entries
    assert dropped == []
