"""anime-whisper 文本清洗（对齐前，保守版）。

移植/改编自 WhisperJAV `whisperjav/modules/subtitle_pipeline/cleaners/anime_whisper.py`
(MIT License, WhisperJAV authors)。见 THIRD_PARTY_NOTICES.md。

职责（对齐前，只收敛 anime-whisper 的已知输出伪迹，不破坏原文语气）：
  1. 删除省略号-only 伪迹（"…"、"…?"、"…」" 等纯非语音片段）。
  2. 折叠 3 次以上连续短语重复（模型 loop 幻觉）。
  3. 连续省略号折叠为一个。
  4. 句尾缺句末标点时补 "。"。

与项目内 `collapse_filler_repetitions` 的分工：
  - 本模块是对齐【前】的文本级短语重复收敛，针对 anime hallucinated phrase loop。
  - `collapse_filler_repetitions` 是对齐【后】的 cue 内 filler token 折叠。
  两级都可能作用于 anime 输出；正常强调重复（真实台词）不应被过度折叠 —— 见测试。

保守边界（故意保留，不当作伪迹）：
  - "…あ" / "あ…" 这类带语气的省略号 —— 保留。
  - "…" 不在此处当作强句尾切句；切句是 sentences_from_alignment 的职责。
"""
from __future__ import annotations

import re

# 句末标点：结尾已是其一则不补 "。"
_SENTENCE_FINAL = frozenset("。、!?…！？♪～")

# 省略号-only 伪迹：整串由 省略号/点/闭合标点/引号/空白 组成，且至少含一个点。
# 命中丢弃："…" "‥" "..." "……" "…?" "…!" "…」" "…？" "…！" "…)" 等。
# 保留："?" "!" "」" 单独，"あ…"、"…あ"、任何含假名/汉字的文本。
_ELLIPSIS_NOISE = re.compile(r'^[…‥\.．?!？！」』\)）\]\s]+$')
_HAS_DOT = re.compile(r'[…‥\.．]')

# 连续省略号折叠为一个。
_ELLIPSIS_RUN = re.compile(r'[…‥]{2,}')

# 句首省略号(anime-whisper 的软起始伪迹):一句开头的 … 在字幕里读着别扭,删掉。
# 句中/句末的 … 保留(如 "あ…"、"待って…くる")。
_LEADING_ELLIPSIS = re.compile(r'^[\s…‥]+')


def strip_leading_ellipsis(text: str) -> str:
    """删除一条 cue/句子开头的省略号(及前导空白)。句中/句末 … 不动。"""
    return _LEADING_ELLIPSIS.sub('', text)


def is_ellipsis_only(text: str) -> bool:
    """True 表示纯省略号/非语音伪迹（无对白内容）。"""
    if not text:
        return False
    if not _HAS_DOT.search(text):
        return False
    return bool(_ELLIPSIS_NOISE.match(text))


def _remove_repetition(text: str) -> str:
    """折叠连续重复 3+ 次的 2-20 字短语（非贪婪取最短重复单元），塌回一次。"""
    return re.sub(r"(.{2,20}?)\1{2,}", r"\1", text)


def _fold_ellipsis_runs(text: str) -> str:
    """连续省略号折叠为一个。"""
    return _ELLIPSIS_RUN.sub('…', text)


def _ensure_sentence_ending(text: str) -> str:
    """句尾缺句末标点则补 "。"（anime-whisper 常省略句末句号）。"""
    if text and text[-1] not in _SENTENCE_FINAL:
        return text + "。"
    return text


def anime_clean_text(text: str) -> str:
    """清洗单条 anime-whisper 文本。省略号-only/空 返回空串。"""
    if not text or not text.strip():
        return ""
    text = text.strip()
    if is_ellipsis_only(text):
        return ""
    text = strip_leading_ellipsis(text)
    text = _remove_repetition(text)
    text = _fold_ellipsis_runs(text)
    text = _ensure_sentence_ending(text)
    return text


def anime_clean_batch(texts: list[str]) -> list[str]:
    """批量清洗。"""
    return [anime_clean_text(t) for t in texts]
