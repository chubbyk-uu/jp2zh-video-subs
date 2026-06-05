from __future__ import annotations

import unicodedata
from statistics import median

from srt_utils import compact_text


# Canonical Japanese Whisper hallucinations: video sign-off / subscribe / credits
# boilerplate the model learned from video-platform training data. They surface when
# it decodes near-silent audio, and are unrelated to the source audio in this corpus.
# Keep this list focused on clearly context-mismatched boilerplate or non-dialogue
# artifacts; ordinary dialogue phrases are handled by repeat/confidence rules.
HALLUCINATION_PHRASES = (
    # Video-platform boilerplate (subscribe / sign-off / credits).
    "ご視聴",
    "ご清聴",
    "ご覧いただき",
    "チャンネル登録",
    "高評価",
    "グッドボタン",
    "登録お願いします",
    "購読",
    "サブスクリプション",
    "コメント",
    "コメント欄",
    "概要欄",
    "ベルマーク",
    "通知オン",
    "フォロー",
    "シェア",
    "ライブ配信",
    "メンバーシップ",
    "次の動画",
    "次回の動画",
    "また次回",
    "また次の動画",
    "お会いしましょう",
    "また会いましょう",
    "それではまた",
    "それでは",
    "最後までご視聴",
    "最後まで見てくれてありがとう",
    "最後まで見てくれてありがとうございます",
    "また見てね",
    # Subtitle labels or context-mismatched set phrases that repeatedly appear as
    # gap-fill hallucinations in this corpus.
    "笑い声",
    "拍手",
    "アーメン",
    # Context-mismatched math snippets observed in ASR/gap-fill hallucinations.
    "タンジェント",
    "コサイン",
    # Context-mismatched AI/tool/English snippets observed in main ASR hallucinations.
    "エルミック",
    "アルファミリー",
    "AlphaFamily",
)


HIGH_RISK_REPEAT_PHRASES = (
    "おやすみなさい",
    "おやすみ",
    "ありがとうございました",
    "ありがとうございます",
    "どうもありがとう",
    "お疲れ様でした",
    "おつかれさまでした",
    "バイバイ",
    "またね",
    "さよなら",
    "さようなら",
    "おはようございます",
    "おはよう",
    "ごちそうさまでした",
    "ごちそうさま",
)


def symbol_count(text: str) -> int:
    return sum(1 for char in text if unicodedata.category(char).startswith(("S", "C")))


def looks_like_symbol_hallucination(text: str) -> bool:
    compact = compact_text(text)
    if not compact:
        return False
    symbols = symbol_count(compact)
    if symbols >= 2 and symbols / len(compact) >= 0.5:
        return True
    return symbols >= 1 and len(compact) <= 2


def looks_like_hallucination(text: str) -> bool:
    compact = compact_text(text)
    return any(phrase in compact for phrase in HALLUCINATION_PHRASES) or looks_like_symbol_hallucination(compact)


def normalize_phrase(text: str) -> str:
    # Frequency key: drop trailing punctuation/spacing so "ありがとうございました。" and
    # "ありがとうございました" collapse to one phrase instead of evading the count.
    return compact_text(text).strip("。、．，！？!?…・ー～~ 　")


def is_high_risk_repeat_phrase(text: str) -> bool:
    return any(phrase in text for phrase in HIGH_RISK_REPEAT_PHRASES)


def repeated_hallucination_texts(
    entries,
    min_repeats: int,
    no_speech_prob_at_least: float,
    avg_logprob_at_most: float,
    high_risk_max_repeats: int,
) -> set[str]:
    # Frequency is counted across all gap fills for one video. Repeated ordinary
    # dialogue is auto-dropped when the repeated group is also low-confidence; high-risk
    # fixed greetings/thanks also have an absolute repeat cap because extreme counts
    # are implausible even when the clip contains some VAD speech.
    groups: dict[str, list] = {}
    for entry in entries:
        key = normalize_phrase(entry.text)
        if key:
            groups.setdefault(key, []).append(entry)

    repeated: set[str] = set()
    for key, group in groups.items():
        if (
            high_risk_max_repeats > 0
            and is_high_risk_repeat_phrase(key)
            and len(group) >= high_risk_max_repeats
        ):
            repeated.add(key)
            continue
        if len(group) < min_repeats:
            continue
        no_speech_probs = [
            entry.no_speech_prob for entry in group if entry.no_speech_prob is not None
        ]
        avg_logprobs = [
            entry.avg_logprob for entry in group if entry.avg_logprob is not None
        ]
        if no_speech_probs and median(no_speech_probs) >= no_speech_prob_at_least:
            repeated.add(key)
            continue
        if avg_logprobs and median(avg_logprobs) <= avg_logprob_at_most:
            repeated.add(key)
    return repeated
