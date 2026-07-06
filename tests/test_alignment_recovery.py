from alignment_recovery import (
    RecoveredItem,
    assess_alignment_quality,
    items_to_words,
    redistribute_collapsed_words,
    words_to_items,
)
from transcribe_ja_srt_qwen import _RawItem, item_end, item_start, item_text


def _words(pairs):
    """pairs: [(word, start, end), ...] -> word dicts."""
    return [{"word": w, "start": s, "end": e} for w, s, e in pairs]


# ---- 字段适配 ----

def test_items_to_words_and_back():
    items = [_RawItem("あ", 1.0, 1.2), _RawItem("い", 1.2, 1.5)]
    words = items_to_words(items)
    assert words == [
        {"word": "あ", "start": 1.0, "end": 1.2},
        {"word": "い", "start": 1.2, "end": 1.5},
    ]
    back = words_to_items(words)
    assert all(isinstance(i, RecoveredItem) for i in back)
    # duck-type 兼容 chunk_entries 的读取器
    assert item_text(back[0]) == "あ"
    assert item_start(back[0]) == 1.0
    assert item_end(back[1]) == 1.5


def test_items_to_words_skips_null_timestamps():
    class _Null:
        text, start_time, end_time = "x", None, None
    assert items_to_words([_Null()]) == []


# ---- 检测 ----

def test_healthy_not_collapsed():
    # 12 字均匀铺在 6s：正常
    words = _words([(c, i * 0.5, i * 0.5 + 0.4) for i, c in enumerate("あいうえおかきくけこさし")])
    a = assess_alignment_quality(words, scene_duration_sec=6.0)
    assert a["status"] == "OK"


def test_short_text_not_assessed():
    words = _words([("あ", 0.0, 0.05), ("い", 0.05, 0.05)])
    assert assess_alignment_quality(words, 6.0)["status"] == "OK"


def test_zero_position_collapse():
    words = _words([(c, 0.0, 0.0) for c in "あいうえおかきくけこさし"])
    a = assess_alignment_quality(words, 6.0)
    assert a["status"] == "COLLAPSED"
    assert "zero_position" in a["triggers"]


def test_degenerate_collapse():
    # 全部 start==end，非零位置：聚簇塌缩
    words = _words([(c, 2.0, 2.0) for c in "あいうえおかきくけこさし"])
    a = assess_alignment_quality(words, 6.0)
    assert a["status"] == "COLLAPSED"
    assert "degenerate" in a["triggers"]


def test_span_and_cps_collapse():
    # 12 字压在 0.1s：span<0.5 且 cps 极高
    words = _words([(c, 2.0 + i * 0.008, 2.0 + i * 0.008) for i, c in enumerate("あいうえおかきくけこさし")])
    a = assess_alignment_quality(words, 6.0)
    assert a["status"] == "COLLAPSED"
    assert "span" in a["triggers"]


# ---- 恢复 ----

def test_vad_guided_skips_silence():
    words = _words([(c, 0.0, 0.0) for c in "あいうえおかきくけこ"])  # 10 字塌缩
    regions = [(1.0, 2.0), (5.0, 6.0)]  # 中间 2-5s 静音
    out = redistribute_collapsed_words(words, 6.0, speech_regions=regions)
    starts = [w["start"] for w in out]
    # 单调不减，且落在语音区，绝不落到 2-5s 静音里
    assert starts == sorted(starts)
    for w in out:
        in_r1 = 1.0 <= w["start"] <= 2.0
        in_r2 = 5.0 <= w["start"] <= 6.0
        assert in_r1 or in_r2, w
    assert out[0]["start"] >= 1.0
    assert out[-1]["end"] <= 6.0


def test_proportional_fallback_from_anchor():
    words = _words([(c, 3.0, 3.0) for c in "あいうえお"])  # anchor=3.0
    out = redistribute_collapsed_words(words, 20.0, speech_regions=None)
    assert out[0]["start"] == 3.0
    assert out[-1]["end"] > out[0]["start"]
    starts = [w["start"] for w in out]
    assert starts == sorted(starts)


def test_recovery_does_not_mutate_input():
    words = _words([(c, 0.0, 0.0) for c in "あいうえお"])
    snapshot = [dict(w) for w in words]
    redistribute_collapsed_words(words, 6.0, speech_regions=[(0.0, 5.0)])
    assert words == snapshot
