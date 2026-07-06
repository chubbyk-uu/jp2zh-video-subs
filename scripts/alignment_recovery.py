"""Forced-aligner 塌缩检测与时间轴恢复。

移植/改编自 WhisperJAV `whisperjav/modules/alignment_sentinel.py`
(MIT License, WhisperJAV authors)。见 THIRD_PARTY_NOTICES.md。

forced aligner 偶尔"塌缩"：把整段词都压到 ~100ms 窗口，文本对但时间戳全错。
本模块提供检测（assess_alignment_quality）与恢复（redistribute_collapsed_words）。

坐标约定（配合本项目两阶段 anime 线，见 docs/PLAN-anime-whisper.md 1.3/1.7）：
  - 全程在 clip-relative 坐标系运行。
  - scene_duration_sec 传【加宽后】的 clip 时长 job.end - job.start。
  - speech_regions 传 clip-relative 的 [(start, end), ...]。
  - 恢复后的 items 由调用方再加 job.start 转 full-audio absolute。

字段适配：
  - items_to_words(items): 有 .text/.start_time/.end_time 的对象 -> {"word","start","end"}。
  - words_to_items(words): -> RecoveredItem(text,start_time,end_time)，供 chunk_entries 消费。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

# --- 检测阈值（V2：span + 分布，照搬 WhisperJAV 原值）---
_MIN_CHAR_COUNT_FOR_ASSESSMENT = 10   # 低于此字符数不足以判断
_COVERAGE_RATIO_THRESHOLD = 0.05      # 词跨度 < 场景 5% = 塌缩
_AGGREGATE_CPS_THRESHOLD = 50.0       # 物理上不可能的语速
_WORD_SPAN_THRESHOLD = 0.5            # 有实质文本却 < 500ms
_ZERO_POSITION_RATIO_THRESHOLD = 0.10  # >10% 词在 (0,0) = 塌缩
_DEGENERATE_RATIO_THRESHOLD = 0.40    # >40% 词 start==end = 聚簇塌缩

# --- 恢复参数 ---
_TARGET_CPS = 10.0  # 日语会话速度 ~10 字/秒


@dataclass
class RecoveredItem:
    """恢复后的 aligner item，duck-type 兼容 chunk_entries（.text/.start_time/.end_time）。"""

    text: str
    start_time: float
    end_time: float


# ---------------------------------------------------------------------------
# 字段适配
# ---------------------------------------------------------------------------

def items_to_words(items) -> List[Dict[str, Any]]:
    """aligner items（.text/.start_time/.end_time）-> sentinel 所需 word dicts。

    start/end 为空的 item 跳过（与 flatten_item_chars 一致）。
    """
    words: List[Dict[str, Any]] = []
    for it in items or []:
        s = getattr(it, "start_time", None)
        e = getattr(it, "end_time", None)
        if s is None or e is None:
            continue
        words.append({"word": str(getattr(it, "text", "")), "start": float(s), "end": float(e)})
    return words


def words_to_items(words: List[Dict[str, Any]]) -> List[RecoveredItem]:
    """恢复后的 word dicts -> RecoveredItem 列表，供 chunk_entries 消费。"""
    return [RecoveredItem(text=w.get("word", ""), start_time=float(w["start"]), end_time=float(w["end"]))
            for w in words]


# ---------------------------------------------------------------------------
# 塌缩检测
# ---------------------------------------------------------------------------

def assess_alignment_quality(
    words: List[Dict[str, Any]],
    scene_duration_sec: float,
) -> Dict[str, Any]:
    """扫描 word 列表判断是否塌缩。返回含 status ("OK"/"COLLAPSED") 与指标的 dict。"""
    result: Dict[str, Any] = {
        "status": "OK",
        "word_count": 0,
        "char_count": 0,
        "word_span_sec": 0.0,
        "scene_duration_sec": scene_duration_sec,
        "coverage_ratio": 0.0,
        "aggregate_cps": 0.0,
        "anchor_sec": 0.0,
        "triggers": [],
    }

    if not words or scene_duration_sec <= 0:
        return result

    word_count = len(words)
    char_count = sum(len(w.get("word", "")) for w in words)
    result["word_count"] = word_count
    result["char_count"] = char_count

    if char_count <= _MIN_CHAR_COUNT_FOR_ASSESSMENT:
        return result

    first_start = words[0].get("start", 0.0)
    last_end = words[-1].get("end", 0.0)
    word_span_sec = max(0.0, last_end - first_start)
    coverage_ratio = word_span_sec / scene_duration_sec if scene_duration_sec > 0 else 0.0
    aggregate_cps = char_count / word_span_sec if word_span_sec > 0 else float("inf")

    zero_position_count = sum(
        1 for w in words if w.get("start", 0.0) == 0.0 and w.get("end", 0.0) == 0.0
    )
    zero_position_ratio = zero_position_count / word_count
    degenerate_count = sum(1 for w in words if w.get("start", 0.0) == w.get("end", 0.0))
    degenerate_ratio = degenerate_count / word_count

    result.update({
        "word_span_sec": word_span_sec,
        "coverage_ratio": coverage_ratio,
        "aggregate_cps": aggregate_cps,
        "anchor_sec": first_start,
        "zero_position_count": zero_position_count,
        "zero_position_ratio": zero_position_ratio,
        "degenerate_count": degenerate_count,
        "degenerate_ratio": degenerate_ratio,
    })

    collapsed = False
    triggers: List[str] = []
    if coverage_ratio < _COVERAGE_RATIO_THRESHOLD:
        collapsed = True; triggers.append("coverage")
    if aggregate_cps > _AGGREGATE_CPS_THRESHOLD:
        collapsed = True; triggers.append("cps")
    if word_span_sec < _WORD_SPAN_THRESHOLD:
        collapsed = True; triggers.append("span")
    if zero_position_ratio > _ZERO_POSITION_RATIO_THRESHOLD:
        collapsed = True; triggers.append("zero_position")
    if degenerate_ratio > _DEGENERATE_RATIO_THRESHOLD:
        collapsed = True; triggers.append("degenerate")

    result["triggers"] = triggers
    if collapsed:
        result["status"] = "COLLAPSED"
    return result


# ---------------------------------------------------------------------------
# 恢复调度
# ---------------------------------------------------------------------------

def redistribute_collapsed_words(
    words: List[Dict[str, Any]],
    scene_duration_sec: float,
    speech_regions: Optional[List[Tuple[float, float]]] = None,
) -> List[Dict[str, Any]]:
    """按字符数比例重铺时间戳，返回新 word 列表（不改输入）。

    有 speech_regions 走 VAD-guided（跳静音），否则从 anchor 按会话速率摊分。
    """
    if not words:
        return []
    total_chars = sum(len(w.get("word", "")) for w in words)
    if total_chars == 0:
        total_chars = len(words)
    if speech_regions:
        return _distribute_words_across_regions(words, speech_regions, total_chars)
    return _distribute_words_from_anchor(words, scene_duration_sec, total_chars)


def _distribute_words_across_regions(
    words: List[Dict[str, Any]],
    speech_regions: List[Tuple[float, float]],
    total_chars: int,
) -> List[Dict[str, Any]]:
    """Strategy C：按字符数比例摊到 VAD 语音时间轴，跳过静音间隙。"""
    regions = sorted([(s, e) for s, e in speech_regions if e > s], key=lambda r: r[0])
    if not regions:
        scene_end = max(w.get("end", 0.0) for w in words) if words else 0.0
        return _distribute_words_from_anchor(words, scene_end, total_chars)
    total_speech = sum(e - s for s, e in regions)
    if total_speech <= 0:
        return _distribute_words_from_anchor(words, regions[-1][1], total_chars)

    out: List[Dict[str, Any]] = []
    cum = 0
    for w in words:
        wc = len(w.get("word", "")) or 1
        ts = (cum / total_chars) * total_speech
        te = ((cum + wc) / total_chars) * total_speech
        rs = _timeline_to_real(ts, regions)
        re_ = _timeline_to_real(te, regions)
        if re_ <= rs:
            re_ = rs + 0.02
        out.append({"word": w.get("word", ""), "start": round(rs, 3), "end": round(re_, 3)})
        cum += wc
    return out


def _distribute_words_from_anchor(
    words: List[Dict[str, Any]],
    scene_duration_sec: float,
    total_chars: int,
) -> List[Dict[str, Any]]:
    """Strategy B：无 VAD 数据时，从 anchor（首词 start）按会话速率摊分。"""
    if not words:
        return []
    anchor = words[0].get("start", 0.0)
    estimated = total_chars / _TARGET_CPS
    start = anchor
    end = start + estimated
    if end > scene_duration_sec:
        end = scene_duration_sec
        if end - start < estimated * 0.5:
            start = max(0.0, scene_duration_sec - estimated)
    if end <= start:
        start = 0.0
        end = scene_duration_sec
    span = end - start

    out: List[Dict[str, Any]] = []
    cum = 0
    for w in words:
        wc = len(w.get("word", "")) or 1
        ws = start + (cum / total_chars) * span
        we = start + ((cum + wc) / total_chars) * span
        if we <= ws:
            we = ws + 0.02
        out.append({"word": w.get("word", ""), "start": round(ws, 3), "end": round(we, 3)})
        cum += wc
    return out


def _timeline_to_real(timeline_pos: float, regions: List[Tuple[float, float]]) -> float:
    """把压缩语音时间轴上的位置映射回真实时间（跳过 region 间静音）。"""
    cum = 0.0
    for rs, re_ in regions:
        dur = re_ - rs
        if dur <= 0:
            continue
        if cum + dur >= timeline_pos:
            return rs + (timeline_pos - cum)
        cum += dur
    return regions[-1][1] if regions else 0.0
