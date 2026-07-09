from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, TypeVar

from srt_utils import padded_end, parse_time, srt_time


KANA_RE = re.compile(r"[ぁ-ゟ゠-ヿ]")
HISTORY_RESET_SECONDS = 10.0


@dataclass
class Entry:
    index: str
    time: str
    text: str
    start: float
    end: float
    settings: str = ""


@dataclass(frozen=True)
class GlossaryTerm:
    source: str
    target: str
    note: str
    forbidden: tuple[str, ...] = ()


# 带 様/さん 尊称的「ご主人様」是主仆/角色称呼，译「主人」。不带尊称的
# 「主人」在现实系台词里通常是妻子称丈夫，译「丈夫」。Longest-match matching
# keeps ご主人様/主人様 from being caught by the bare 主人 rule.
DEFAULT_GLOSSARY = (
    GlossaryTerm(
        source="ご主人様",
        target="主人",
        note="主仆/角色尊称",
        forbidden=("老公", "丈夫"),
    ),
    GlossaryTerm(
        source="主人様",
        target="主人",
        note="主仆/角色尊称",
        forbidden=("老公", "丈夫"),
    ),
    GlossaryTerm(
        source="ご主人さん",
        target="主人",
        note="主仆/角色尊称",
        forbidden=("老公", "丈夫"),
    ),
    GlossaryTerm(
        source="主人",
        target="丈夫",
        note="妻子称丈夫；只有ご主人様/主人様等尊称译为主人",
        forbidden=("主人",),
    ),
    # 契約結ぶ／契約: realistic-drama "sign a contract". Steer away from Sakura's stiff
    # literary "缔结契约" toward the colloquial "签合同/合同" (phrase form first so the
    # verb 結ぶ=签 is kept). Wrong for fantasy/pact titles, fine for this content.
    GlossaryTerm(
        source="契約結ぶ",
        target="签合同",
        note="口语",
        forbidden=("缔结",),
    ),
    GlossaryTerm(
        source="契約",
        target="合同",
        note="口语",
        forbidden=("缔结",),
    ),
)


class GlossaryTermLike(Protocol):
    source: str


GlossaryT = TypeVar("GlossaryT", bound=GlossaryTermLike)


def relevant_terms(text: str, glossary: tuple[GlossaryT, ...]) -> list[GlossaryT]:
    """Return source-matched glossary terms, keeping only the longest overlapping term."""
    kept: list[GlossaryT] = []
    for term in sorted(glossary, key=lambda item: len(item.source), reverse=True):
        if term.source not in text:
            continue
        if any(term.source in kept_term.source or kept_term.source in term.source for kept_term in kept):
            continue
        kept.append(term)
    return kept


def matched_glossary_terms(source: str, glossary: tuple[GlossaryTerm, ...]) -> tuple[GlossaryTerm, ...]:
    return tuple(relevant_terms(source, glossary))


def glossary_issues(source: str, translated: str, glossary: tuple[GlossaryTerm, ...]) -> list[GlossaryTerm]:
    issues: list[GlossaryTerm] = []
    for term in matched_glossary_terms(source, glossary):
        if any(item in translated for item in term.forbidden):
            issues.append(term)
    return issues


def clean_translation(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^<target>|</target>$", "", text).strip()
    text = re.sub(r"^```(?:\w+)?|```$", "", text).strip()
    text = re.sub(r"^(翻译结果[:：]\s*)", "", text).strip()
    text = re.sub(r"^译文[:：]\s*", "", text).strip()
    target_match = re.search(r"<target>(.*?)</target>", text, flags=re.S)
    if target_match:
        text = target_match.group(1).strip()
    current_match = re.search(r"<current>(.*?)</current>", text, flags=re.S)
    if current_match:
        text = current_match.group(1).strip()
    text = re.sub(r"</?current>", "", text).strip()
    text = re.sub(r"</?context>", "", text).strip()
    return text.splitlines()[0].strip() if text else ""


def normalize_source(text: str) -> str:
    return text


def is_context_sensitive_short_text(text: str) -> bool:
    compact = re.sub(r"\s+", "", text)
    compact = compact.translate(str.maketrans({"？": "?", "！": "!"}))
    if len(compact) <= 2:
        return True
    if re.fullmatch(r"[、。！？!?…ー〜・\-.]+", compact):
        return True
    filler_words = {
        "あ",
        "え",
        "はい",
        "うん",
        "いや",
        "おー",
        "え?",
        "ああ",
        "ここ",
    }
    return compact in filler_words


def parse_srt(path: Path) -> list[Entry]:
    blocks = re.split(r"\n\s*\n", path.read_text(encoding="utf-8").strip())
    entries: list[Entry] = []
    for block in blocks:
        lines = block.splitlines()
        if len(lines) < 3 or "-->" not in lines[1]:
            continue
        start_text, end_text = [item.strip() for item in lines[1].split("-->", 1)]
        end_parts = end_text.split(maxsplit=1)
        end_time = end_parts[0]
        settings = f" {end_parts[1]}" if len(end_parts) > 1 else ""
        entries.append(
            Entry(
                lines[0].strip(),
                lines[1].strip(),
                "\n".join(lines[2:]).strip(),
                parse_time(start_text),
                parse_time(end_time),
                settings,
            )
        )
    return entries


def padded_time(entry: Entry, next_entry: Entry | None, lead_out: float, min_display: float) -> str:
    next_start = next_entry.start if next_entry is not None else None
    end = padded_end(entry.start, entry.end, next_start, lead_out, min_display)
    return f"{srt_time(entry.start)} --> {srt_time(end)}{entry.settings}"


def write_entry(
    f,
    entry: Entry,
    text: str,
    next_entry: Entry | None = None,
    lead_out: float = 0.0,
    min_display: float = 0.0,
) -> None:
    f.write(f"{entry.index}\n")
    f.write(f"{padded_time(entry, next_entry, lead_out, min_display)}\n")
    f.write(f"{text}\n\n")
    f.flush()


def write_terms_report(
    path: Path,
    rows: list[tuple[Entry, str, list[GlossaryTerm]]],
) -> None:
    lines = ["Terminology review report", ""]
    if not rows:
        lines.append("No terminology issues detected.")
    for entry, translated, issues in rows:
        expected = ", ".join(f"{term.source}->{term.target}" for term in issues)
        forbidden = ", ".join(sorted({item for term in issues for item in term.forbidden}))
        lines.extend(
            [
                f"[{entry.index}] {entry.time}",
                f"source: {entry.text}",
                f"translation: {translated}",
                f"expected: {expected}",
                f"forbidden_seen: {forbidden}",
                "",
            ]
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def looks_degenerate(source: str, text: str) -> bool:
    """Detect runaway/looping translation output."""
    if not text:
        return False
    if len(text) > max(40, 3 * len(source) + 10):
        return True
    for unit in range(1, 6):
        if re.search(r"(.{%d})\1{5,}" % unit, text):
            return True
    return False
