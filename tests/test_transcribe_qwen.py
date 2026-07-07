import argparse

import numpy as np
import pytest

from srt_utils import Interval
from transcribe_ja_srt import SubtitleEntry
from transcribe_ja_srt_qwen import (
    ISOLATED_INTERJECTION_CORES,
    ChunkJob,
    _RawItem,
    _clip_relative_speech,
    _interjection_core,
    _time_aligned_job,
    _time_anime_job,
    apply_qwen_generation_config,
    build_qwen_jobs,
    build_whisperseg_jobs,
    drop_isolated_interjections,
    entries_from_raw,
    qwen_batch_token_budget,
    qwen_aligner_language,
    reframe_collapsed_jobs,
    resolve_qwen_generation_config,
    sentences_from_alignment,
    split_into_units,
    uncovered_gap_spans,
    vad_only_items_for_text,
)
import whisperseg_vad
from whisperseg_vad import SpeechSegment


def _shaping_args(**overrides):
    """A minimal Namespace with the cue-shaping knobs chunk_entries/_time_anime_job read."""
    base = dict(
        phrase_max_chars=26, phrase_max_duration=8.0, min_duration=0.0,
        phrase_max_internal_gap=2.0, phrase_max_char_seconds=0.5,
        collapse_filler_repetition=True,
        timestamp_mode="aligner_fallback", collapse_recovery=True,
    )
    base.update(overrides)
    return argparse.Namespace(**base)


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


def _finalize_args(*extra: str):
    from transcribe_ja_srt_qwen import build_parser
    return build_parser().parse_args(["a.wav", "out.srt", *extra])


def test_filter_hallucinations_enables_near_dup_squeeze_filter():
    from transcribe_ja_srt_qwen import finalize_qwen_entries
    # Overlapping-clip twin: the second cue is the same line up to punctuation and
    # has been squeezed by resolve_overlaps to a sub-squeeze-window flash.
    entries = [
        SubtitleEntry(10.0, 12.0, "いやいや今選んでください"),
        SubtitleEntry(12.05, 12.35, "いやいや、今選んでください"),
    ]
    kept = finalize_qwen_entries(list(entries), _finalize_args("--filter-hallucinations"))
    assert [e.text for e in kept] == ["いやいや今選んでください"]


def test_near_dup_squeeze_filter_stays_off_by_default():
    from transcribe_ja_srt_qwen import finalize_qwen_entries
    entries = [
        SubtitleEntry(10.0, 12.0, "いやいや今選んでください"),
        SubtitleEntry(12.05, 12.35, "いやいや、今選んでください"),
    ]
    kept = finalize_qwen_entries(list(entries), _finalize_args())
    assert len(kept) == 2


# ---- anime backend bridge ----

def test_qwen_aligner_language_normalizes_codes_to_names():
    assert qwen_aligner_language("ja") == "Japanese"
    assert qwen_aligner_language("Japanese") == "Japanese"
    assert qwen_aligner_language(" Japanese ") == "Japanese"
    assert qwen_aligner_language("en") == "English"
    assert qwen_aligner_language("") == "Japanese"


class _Obj:
    pass


def test_resolve_qwen_generation_config_prefers_thinker_path():
    wrapper = _Obj()
    wrapper.model = _Obj()
    wrapper.model.thinker = _Obj()
    wrapper.model.thinker.generation_config = _Obj()

    config, path = resolve_qwen_generation_config(wrapper)

    assert config is wrapper.model.thinker.generation_config
    assert path == "model.model.thinker.generation_config"


def test_apply_qwen_generation_config_sets_repetition_penalty():
    wrapper = _Obj()
    wrapper.model = _Obj()
    wrapper.model.thinker = _Obj()
    wrapper.model.thinker.generation_config = _Obj()

    result = apply_qwen_generation_config(wrapper, argparse.Namespace(repetition_penalty=1.1))

    assert result == {
        "applied": True,
        "path": "model.model.thinker.generation_config",
        "repetition_penalty": 1.1,
    }
    assert wrapper.model.thinker.generation_config.repetition_penalty == 1.1


def test_qwen_batch_token_budget_uses_per_batch_max():
    jobs = [
        ChunkJob(0.0, 5.0, 0.0, 5.0),
        ChunkJob(10.0, 30.0, 10.0, 30.0),
    ]
    args = argparse.Namespace(max_new_tokens=4096, max_tokens_per_second=20.0, min_tokens_floor=256)

    budget = qwen_batch_token_budget(jobs, args)

    assert budget == {"per_clip": [256, 400], "batch_budget": 400}


def test_whisperseg_resolve_model_path_local_only(tmp_path, monkeypatch):
    model = tmp_path / "model.onnx"
    model.write_bytes(b"onnx")
    assert whisperseg_vad.resolve_model_path(str(model)) == str(model)

    monkeypatch.setattr(whisperseg_vad, "DEFAULT_MODEL_PATH", model)
    assert whisperseg_vad.resolve_model_path() == str(model)

    monkeypatch.setattr(whisperseg_vad, "DEFAULT_MODEL_PATH", tmp_path / "missing.onnx")
    with pytest.raises(SystemExit):
        whisperseg_vad.resolve_model_path()


def test_whisperseg_jobs_use_min_frame_not_legacy_vad_min_clip(monkeypatch, tmp_path):
    class FakeWhisperSegVAD:
        def __init__(self, **_kwargs):
            pass

        def segment(self, _audio, _sample_rate):
            return [[SpeechSegment(1.0, 1.2)]]

        def cleanup(self):
            pass

    model = tmp_path / "model.onnx"
    model.write_bytes(b"onnx")
    monkeypatch.setattr(whisperseg_vad, "WhisperSegVAD", FakeWhisperSegVAD)

    args = argparse.Namespace(
        whisperseg_model=str(model),
        whisperseg_threshold=0.35,
        whisperseg_max_speech=5.0,
        whisperseg_max_group=5.0,
        whisperseg_chunk_threshold=0.5,
        whisperseg_min_frame_seconds=0.1,
        vad_min_clip_seconds=0.3,
        scene_backend="none",
    )

    jobs = build_whisperseg_jobs(np.zeros(16000 * 3, dtype=np.float32), 16000, 3.0, args)

    assert len(jobs) == 1
    assert jobs[0].start == pytest.approx(1.0)
    assert jobs[0].end == pytest.approx(1.2)


def test_build_qwen_jobs_default_uses_current_vad(monkeypatch):
    calls = []
    expected = [ChunkJob(1.0, 2.0, 1.0, 2.0)]

    def fake_build_vad_jobs(audio, samplerate, duration, args):
        calls.append((audio, samplerate, duration, args))
        return expected

    monkeypatch.setattr("transcribe_ja_srt_qwen.build_vad_jobs", fake_build_vad_jobs)
    args = argparse.Namespace(vad_chunks=True, vad_backend="current")

    jobs, mode = build_qwen_jobs(np.zeros(16000, dtype=np.float32), 16000, 1.0, args)

    assert jobs is expected
    assert mode == "vad"
    assert len(calls) == 1


def test_build_qwen_jobs_can_opt_into_whisperseg(monkeypatch):
    calls = []
    expected = [ChunkJob(1.0, 2.0, 1.0, 2.0)]

    def fake_build_whisperseg_jobs(audio, samplerate, duration, args):
        calls.append((audio, samplerate, duration, args))
        return expected

    monkeypatch.setattr("transcribe_ja_srt_qwen.build_whisperseg_jobs", fake_build_whisperseg_jobs)
    args = argparse.Namespace(vad_chunks=True, vad_backend="whisperseg")

    jobs, mode = build_qwen_jobs(np.zeros(16000, dtype=np.float32), 16000, 1.0, args)

    assert jobs is expected
    assert mode == "whisperseg"
    assert len(calls) == 1


def test_clip_relative_speech_intersects_and_shifts():
    intervals = [Interval(1.0, 2.0), Interval(5.0, 9.0)]
    regions = _clip_relative_speech(intervals, job_start=4.0, job_end=8.0)
    # 1-2s is outside [4,8]; 5-9s clips to 5-8s -> clip-relative 1-4s
    assert [(r.start, r.end) for r in regions] == [(1.0, 4.0)]


def test_time_anime_job_healthy_passthrough():
    job = ChunkJob(10.0, 20.0, 10.0, 20.0)
    items = [_RawItem(c, i * 0.7, i * 0.7 + 0.5) for i, c in enumerate("あいうえおかきくけこさし")]
    sentinel, recovery, out = _time_anime_job(job, items, _shaping_args())
    assert sentinel["status"] == "OK"
    assert recovery["applied"] is False
    assert out is not items and len(out) == len(items)  # copied, unchanged count


def test_time_anime_job_recovers_collapse_with_vad():
    job = ChunkJob(10.0, 20.0, 10.0, 20.0)  # widened clip duration = 10s
    job.speech = [Interval(1.0, 3.0), Interval(6.0, 9.0)]  # clip-relative speech
    items = [_RawItem(c, 0.0, 0.0) for c in "あいうえおかきくけこさし"]  # zero-position collapse
    sentinel, recovery, out = _time_anime_job(job, items, _shaping_args())
    assert sentinel["status"] == "COLLAPSED"
    assert recovery == {"applied": True, "strategy": "vad_guided"}
    starts = [it.start_time for it in out]
    assert starts == sorted(starts)
    for it in out:  # every item lands inside a clip-relative speech region
        assert (1.0 <= it.start_time <= 3.0) or (6.0 <= it.start_time <= 9.0), it.start_time


def test_time_aligned_job_recovers_qwen_collapse_with_vad():
    job = ChunkJob(100.0, 110.0, 100.0, 110.0)
    job.speech = [Interval(2.0, 6.0)]
    items = [_RawItem(c, 0.0, 0.0) for c in "ありがとうございますまたお願いします"]

    sentinel, recovery, out = _time_aligned_job(job, items, _shaping_args())

    assert sentinel["status"] == "COLLAPSED"
    assert recovery == {"applied": True, "strategy": "vad_guided"}
    assert all(2.0 <= it.start_time <= 6.0 for it in out)


def test_time_anime_job_aligner_only_skips_recovery():
    job = ChunkJob(10.0, 20.0, 10.0, 20.0)
    items = [_RawItem(c, 0.0, 0.0) for c in "あいうえおかきくけこさし"]
    sentinel, recovery, out = _time_anime_job(job, items, _shaping_args(timestamp_mode="aligner_only"))
    assert sentinel["status"] == "COLLAPSED"
    assert recovery["applied"] is False  # aligner_only never redistributes


def test_vad_only_items_distribute_across_speech_regions():
    items = vad_only_items_for_text("あいうえお", 10.0, [Interval(1.0, 3.0), Interval(7.0, 9.0)])
    assert [it.text for it in items] == list("あいうえお")
    assert items[0].start_time == pytest.approx(1.0)
    assert items[-1].end_time == pytest.approx(9.0)
    assert all(it.start_time <= it.end_time for it in items)
    # The silence gap between speech regions remains a real timing gap.
    assert any(items[i + 1].start_time - items[i].end_time > 2.0 for i in range(len(items) - 1))


def test_entries_from_raw_anime_schema():
    raw = {
        "text_backend": "anime", "timestamp_mode": "aligner_fallback",
        "chunk_seconds": 30.0, "chunk_overlap_seconds": 3.0, "duration": 20.0,
        "context": "",
        "chunks": [{
            "start": 10.0, "end": 18.0, "keep_lo": 10.0, "keep_hi": 18.0,
            "raw_text": "おはようございます", "clean_text": "おはようございます。",
            "speech_regions": [], "recovered_items": [], "sentinel": {}, "recovery": {"applied": False},
            "items": [{"text": c, "start": i * 0.5, "end": i * 0.5 + 0.4}
                      for i, c in enumerate("おはようございます")],
        }],
    }
    entries = entries_from_raw(raw, _shaping_args())
    assert entries and all(isinstance(e, SubtitleEntry) for e in entries)
    # clean_text drove the cue, offset by chunk start (10.0)
    assert entries[0].start >= 10.0
    assert "おはよう" in "".join(e.text for e in entries)


def test_entries_from_raw_anime_vad_only_rebuilds_from_speech_regions():
    raw = {
        "text_backend": "anime", "timestamp_mode": "aligner_fallback",
        "chunk_seconds": 30.0, "chunk_overlap_seconds": 3.0, "duration": 20.0,
        "context": "",
        "chunks": [{
            "start": 10.0, "end": 20.0, "keep_lo": 10.0, "keep_hi": 20.0,
            "raw_text": "おはようございます", "clean_text": "おはようございます。",
            "speech_regions": [[1.0, 4.0]], "raw_items": [], "items": [],
            "recovered_items": [], "sentinel": {}, "recovery": {"applied": False},
        }],
    }
    entries = entries_from_raw(raw, _shaping_args(timestamp_mode="vad_only"))
    assert entries
    assert entries[0].start == pytest.approx(11.0)
    assert entries[-1].end <= 14.0 + 1e-6
    assert "おはよう" in "".join(e.text for e in entries)


def test_entries_from_raw_qwen_schema_uses_final_items():
    raw = {
        "text_backend": "qwen", "timestamp_mode": "aligner_fallback",
        "chunk_seconds": 30.0, "chunk_overlap_seconds": 3.0, "duration": 20.0,
        "context": "",
        "chunks": [{
            "start": 10.0, "end": 20.0, "keep_lo": 10.0, "keep_hi": 20.0,
            "language": "Japanese", "text": "おはようございます。",
            "speech_regions": [[2.0, 5.0]],
            "raw_items": [{"text": c, "start": 0.0, "end": 0.0} for c in "おはようございます"],
            "recovered_items": [{"text": c, "start": 2.0 + i * 0.2, "end": 2.1 + i * 0.2}
                                for i, c in enumerate("おはようございます")],
            "sentinel": {"status": "COLLAPSED"}, "recovery": {"applied": True, "strategy": "vad_guided"},
            "items": [{"text": c, "start": 2.0 + i * 0.2, "end": 2.1 + i * 0.2}
                      for i, c in enumerate("おはようございます")],
        }],
    }

    entries = entries_from_raw(raw, _shaping_args())

    assert entries
    assert entries[0].start == pytest.approx(12.0)
    assert "おはよう" in "".join(e.text for e in entries)


def test_reframe_collapsed_jobs_preserves_outer_keep_window(monkeypatch):
    """Step-down re-frame: sub-jobs use absolute coords and inherit the collapsed job's
    outer keep window at the first/last edge, with interior boundaries their own frames."""
    class _Seg:
        def __init__(self, start, end):
            self.start, self.end = start, end

    class _FakeVAD:
        def __init__(self, **kwargs):
            pass

        def segment(self, clip, sample_rate):
            # two sub-frames inside the collapsed 10s clip: [0.5,3.0] and [4.0,6.0]
            return [[_Seg(0.5, 3.0)], [_Seg(4.0, 6.0)]]

        def cleanup(self):
            pass

    monkeypatch.setattr(whisperseg_vad, "WhisperSegVAD", lambda **kw: _FakeVAD())
    monkeypatch.setattr(whisperseg_vad, "resolve_model_path", lambda p: p)

    job = ChunkJob(10.0, 20.0, 10.0, float("inf"))  # last frame → keep_hi open
    args = _shaping_args(
        whisperseg_model="x.onnx", whisperseg_threshold=0.35, whisperseg_max_speech=5.0,
        whisperseg_max_group=6.0, whisperseg_chunk_threshold=1.0,
        whisperseg_min_frame_seconds=0.1, stepdown_fallback_group=3.0,
    )
    subs = reframe_collapsed_jobs(np.zeros(16000 * 20, dtype=np.float32), 16000, [job], args)

    assert len(subs) == 2
    assert subs[0].start == pytest.approx(10.5)   # 10.0 + 0.5, absolute
    assert subs[1].end == pytest.approx(16.0)     # 10.0 + 6.0
    assert subs[0].keep_lo == 10.0                # first sub inherits job.keep_lo
    assert subs[1].keep_hi == float("inf")        # last sub inherits job.keep_hi (open)
    assert subs[0].keep_hi == pytest.approx(13.0)  # interior boundary = own frame end
    assert subs[1].keep_lo == pytest.approx(14.0)  # interior boundary = own frame start
    # speech stored clip-relative to each sub-frame
    assert subs[0].speech[0].start == pytest.approx(0.0)


def test_entries_from_raw_skips_superseded_stepdown_chunk():
    """--from-raw must drop a collapsed chunk that step-down replaced, so replay matches
    the live pipeline (which removed the collapsed cues). The superseded chunk carries
    well-timed items on purpose: without the skip it would emit cues, proving the skip."""
    raw = {
        "text_backend": "qwen", "timestamp_mode": "aligner_fallback",
        "chunk_seconds": 30.0, "chunk_overlap_seconds": 3.0, "duration": 20.0,
        "context": "",
        "chunks": [
            {  # original collapsed frame, replaced by step-down
                "start": 10.0, "end": 20.0, "keep_lo": 10.0, "keep_hi": 20.0,
                "language": "Japanese", "text": "だめだめまた", "pass": "main",
                "superseded_by_stepdown": True,
                "items": [{"text": c, "start": 1.0 + i * 0.2, "end": 1.1 + i * 0.2}
                          for i, c in enumerate("だめだめまた")],
            },
            {  # tighter step-down re-frame
                "start": 12.0, "end": 15.0, "keep_lo": 12.0, "keep_hi": 15.0,
                "language": "Japanese", "text": "ただいま", "pass": "stepdown",
                "items": [{"text": c, "start": 0.5 + i * 0.2, "end": 0.6 + i * 0.2}
                          for i, c in enumerate("ただいま")],
            },
        ],
    }

    entries = entries_from_raw(raw, _shaping_args())
    joined = "".join(e.text for e in entries)

    assert "だめ" not in joined  # superseded chunk skipped despite well-timed items
    assert "ただいま" in joined  # step-down cues kept


def test_entries_from_raw_qwen_aligner_only_uses_raw_items():
    raw = {
        "text_backend": "qwen", "timestamp_mode": "aligner_fallback",
        "chunk_seconds": 30.0, "chunk_overlap_seconds": 3.0, "duration": 20.0,
        "context": "",
        "chunks": [{
            "start": 10.0, "end": 20.0, "keep_lo": 10.0, "keep_hi": 20.0,
            "language": "Japanese", "text": "おはようございます。",
            "raw_items": [{"text": c, "start": 1.0 + i * 0.1, "end": 1.05 + i * 0.1}
                          for i, c in enumerate("おはようございます")],
            "items": [{"text": c, "start": 2.0 + i * 0.2, "end": 2.1 + i * 0.2}
                      for i, c in enumerate("おはようございます")],
        }],
    }

    entries = entries_from_raw(raw, _shaping_args(timestamp_mode="aligner_only"))

    assert entries
    assert entries[0].start == pytest.approx(11.0)


# ---- anime ellipsis-soft sentence splitting ----

def test_split_units_ellipsis_hard_default_splits_on_ellipsis():
    # Qwen backend unchanged: … is a hard sentence end.
    assert split_into_units("会長、やめて…て…", 26) == ["会長、やめて…", "て…"]


def test_split_units_ellipsis_soft_keeps_line_whole():
    # anime backend: … is not a hard end; a short line stays one cue.
    assert split_into_units("会長、やめて…て…", 26, ellipsis_hard=False) == ["会長、やめて…て…"]


def test_split_units_ellipsis_soft_still_hard_breaks_on_period():
    assert split_into_units("はい。うん。", 26, ellipsis_hard=False) == ["はい。", "うん。"]


def test_split_units_ellipsis_soft_breaks_overlong_at_ellipsis():
    long = "あ" * 20 + "…" + "い" * 20  # 41 content chars, over max_chars=26
    out = split_into_units(long, 26, ellipsis_hard=False)
    assert len(out) >= 2
    assert out[0].endswith("…")  # soft-cut landed on the …
