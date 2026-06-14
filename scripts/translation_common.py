from __future__ import annotations

import re
from typing import Protocol, TypeVar


KANA_RE = re.compile(r"[ぁ-ゟ゠-ヿ]")


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
