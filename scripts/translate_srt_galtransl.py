from __future__ import annotations

import argparse
from pathlib import Path
from typing import NamedTuple

from llama_cpp import Llama

from cli_config import add_dataclass_arguments
from pipeline_configs import GalTranslTranslateConfig
from translation_common import KANA_RE, looks_degenerate, relevant_terms
from translate_srt_hymt import (
    DEFAULT_GLOSSARY,
    Entry,
    GlossaryTerm,
    HISTORY_RESET_SECONDS,
    clean_translation,
    glossary_issues,
    is_context_sensitive_short_text,
    normalize_source,
    parse_srt,
    write_entry,
    write_terms_report,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1] if Path(__file__).resolve().parent.name == "scripts" else Path(__file__).resolve().parent
DEFAULT_MODEL = PROJECT_ROOT / "models" / "Sakura-GalTransl-7B-v3.7-GGUF" / "Sakura-Galtransl-7B-v3.7.gguf"

# Sakura-GalTransl v3.7 (Qwen2.5 base, GRPO-tuned for visual-novel JA->ZH) was
# trained on this exact prompt; it must not be reused for other backends. Unlike
# Sakura v1.0's chat-pair history, GalTransl v3 takes context as one user message:
# a 历史翻译 block of prior *translations only* (Chinese), an inline 术语表 in the
# native src->dst #note format, then the instruction and the source line. System
# prompt and section wording are fixed by the model card.
GALTRANSL_SYSTEM = (
    "你是一个视觉小说翻译模型，可以通顺地使用给定的术语表以指定的风格将日文翻译成简体中文，"
    "并联系上下文正确使用人称代词，注意不要混淆使役态和被动态的主语和宾语，"
    "不要擅自添加原文中没有的特殊符号，也不要擅自增加或减少换行。"
)
GLOSSARY_HEADER = "参考以下术语表（可为空，格式为src->dst #备注）："
TRANSLATE_INSTRUCTION = "根据以上术语表的对应关系和备注，结合历史剧情和上下文，将下面的文本从日文翻译成简体中文："


class BlockTranslation(NamedTuple):
    lines: list[str | None] | None
    reason: str
    raw: str = ""


def glossary_block(text: str, glossary: tuple[GlossaryTerm, ...]) -> str:
    """The 术语表 entries for this line in GalTransl's native src->dst #note format."""
    terms = relevant_terms(text, glossary)
    return "\n".join(
        f"{t.source}->{t.target} #{t.note}" if t.note else f"{t.source}->{t.target}"
        for t in terms
    )


def build_user_prompt(
    text: str,
    history: list[str],
    glossary: tuple[GlossaryTerm, ...],
) -> str:
    """Assemble the single GalTransl v3 user turn: optional 历史翻译 block, the
    术语表 (header kept even when empty, per the model card's 可为空), then the
    instruction and the source line."""
    parts: list[str] = []
    if history:
        parts.append("历史翻译：" + "\n".join(history))
        parts.append("")
    parts.append(GLOSSARY_HEADER)
    entries = glossary_block(text, glossary)
    if entries:
        parts.append(entries)
    parts.append("")
    parts.append(TRANSLATE_INSTRUCTION)
    parts.append(text)
    return "\n".join(parts)


def build_messages(text: str, history: list[str], glossary: tuple[GlossaryTerm, ...]) -> list[dict]:
    return [
        {"role": "system", "content": GALTRANSL_SYSTEM},
        {"role": "user", "content": build_user_prompt(text, history, glossary)},
    ]


def translate_one(
    llm: Llama,
    text: str,
    history: list[str] | None = None,
    glossary: tuple[GlossaryTerm, ...] = DEFAULT_GLOSSARY,
    frequency_penalty: float = 0.0,
    temperature: float = 0.3,
) -> str:
    text = normalize_source(text)
    # Short fillers translate better standalone than swayed by prior translations.
    if history is None or is_context_sensitive_short_text(text):
        history = []
    # Official v3 sampling: temperature 0.3, top_p 0.8.
    result = llm.create_chat_completion(
        messages=build_messages(text, history, glossary),
        max_tokens=512,
        temperature=temperature,
        top_p=0.8,
        top_k=40,
        repeat_penalty=1.0,
        frequency_penalty=frequency_penalty,
    )
    return clean_translation(result["choices"][0]["message"]["content"])


def translate_with_retry(
    llm: Llama,
    text: str,
    history: list[str] | None = None,
    glossary: tuple[GlossaryTerm, ...] = DEFAULT_GLOSSARY,
) -> str:
    translated = translate_one(llm, text, history, glossary)
    # On degeneration (looping/runaway) raise frequency_penalty.
    if looks_degenerate(text, translated):
        translated = translate_one(llm, text, history, glossary, frequency_penalty=0.2)
    # Kana leak safety: retry standalone with a penalty; if kana still survives the
    # deterministic retry, nudge the sampling once to escape an echo.
    if KANA_RE.search(translated):
        translated = translate_one(llm, text, [], glossary, frequency_penalty=0.2)
    if KANA_RE.search(translated):
        retried = translate_one(llm, text, [], glossary, frequency_penalty=0.3, temperature=0.7)
        if retried and not KANA_RE.search(retried):
            translated = retried
    # Glossary violation: retry standalone with only the violated terms so a competing
    # longer/shorter rule cannot pull the model back to the wrong rendering. If the
    # model still violates a simple terminology replacement, apply the exact forbidden
    # rendering deterministically; this catches bare 主人 -> 丈夫 while preserving
    # ご主人様 -> 主人 through longest-match term selection.
    issues = glossary_issues(text, translated, glossary)
    if issues:
        retried = translate_one(llm, text, [], tuple(issues))
        if retried and not glossary_issues(text, retried, glossary):
            translated = retried
        else:
            translated = apply_glossary_replacements(translated, issues)
    return translated


def union_terms(src_lines: list[str], glossary: tuple[GlossaryTerm, ...]) -> tuple[GlossaryTerm, ...]:
    """Glossary terms relevant to any line in a block, deduplicated, order-preserved."""
    terms: list[GlossaryTerm] = []
    seen: set[str] = set()
    for line in src_lines:
        for term in relevant_terms(line, glossary):
            if term.source not in seen:
                seen.add(term.source)
                terms.append(term)
    return tuple(terms)


def merge_two_line_overflow(lines: list[str], src_lines: list[str]) -> list[str] | None:
    """Rescue the common 2->3 split by folding extra output into the second cue."""
    if len(src_lines) != 2 or len(lines) != 3:
        return None
    return [lines[0], "".join(lines[1:])]


def apply_glossary_replacements(text: str, issues: list[GlossaryTerm]) -> str:
    fixed = text
    for term in issues:
        for forbidden in term.forbidden:
            fixed = fixed.replace(forbidden, term.target)
    return fixed


def validate_block_lines(
    src_lines: list[str],
    lines: list[str],
    glossary: tuple[GlossaryTerm, ...] = (),
) -> BlockTranslation:
    if len(lines) != len(src_lines):
        merged = merge_two_line_overflow(lines, src_lines)
        if merged is None:
            return BlockTranslation(None, f"line-count:{len(src_lines)}->{len(lines)}")
        merged_result = validate_block_lines(src_lines, merged, glossary)
        if merged_result.lines is not None:
            return BlockTranslation(merged_result.lines, "accepted-2to3")
        return merged_result
    checked: list[str | None] = []
    rejected_reasons: list[str] = []
    for source, line in zip(src_lines, lines):
        if KANA_RE.search(line):
            checked.append(None)
            rejected_reasons.append("kana-leak")
        elif looks_degenerate(source, line):
            checked.append(None)
            rejected_reasons.append("degenerate")
        elif glossary_issues(source, line, glossary):
            checked.append(None)
            rejected_reasons.append("glossary")
        else:
            checked.append(line)
    if rejected_reasons:
        return BlockTranslation(checked, "partial-" + "+".join(sorted(set(rejected_reasons))))
    return BlockTranslation(checked, "accepted")


def translate_block_checked(
    llm: Llama,
    sources: list[str],
    history: list[str],
    glossary: tuple[GlossaryTerm, ...],
) -> BlockTranslation:
    """Translate several source lines as one newline-joined turn.

    Relies on the model card's "不要擅自增加或减少换行" contract to return the same
    line count, so each output line maps 1:1 back to its cue. Returns one cleaned
    translation per input line. Individual unsafe lines are returned as None so the
    caller can keep good batch slots while falling back per-line only for bad slots.
    """
    src_lines = [normalize_source(s).replace("\n", " ") for s in sources]
    result = llm.create_chat_completion(
        messages=build_messages("\n".join(src_lines), history, union_terms(src_lines, glossary)),
        max_tokens=min(1536, 160 * len(src_lines) + 256),
        temperature=0.3,
        top_p=0.8,
        top_k=40,
        repeat_penalty=1.0,
    )
    raw = result["choices"][0]["message"]["content"].strip()
    lines = [ln for ln in (clean_translation(x) for x in raw.split("\n")) if ln]
    checked = validate_block_lines(src_lines, lines, glossary)
    return BlockTranslation(checked.lines, checked.reason, raw)


def translate_block(
    llm: Llama,
    sources: list[str],
    history: list[str],
    glossary: tuple[GlossaryTerm, ...],
) -> list[str] | None:
    lines = translate_block_checked(llm, sources, history, glossary).lines
    if lines is None or any(line is None for line in lines):
        return None
    return [line for line in lines if line is not None]


def translate_block_adaptive(
    llm: Llama,
    sources: list[str],
    history: list[str],
    glossary: tuple[GlossaryTerm, ...],
    context_size: int,
) -> tuple[list[str | None] | None, bool]:
    """Strict batch translation with a conservative recursive retry.

    Only line-count mismatches are split and retried. Kana leaks and degenerate output
    stay unsafe and fall back to the existing per-line path.
    """
    checked = translate_block_checked(llm, sources, history, glossary)
    if checked.lines is not None:
        return checked.lines, checked.reason != "accepted"
    if not checked.reason.startswith("line-count"):
        return None, False
    if len(sources) <= 2:
        return [None] * len(sources), False

    mid = len(sources) // 2
    left, left_rescued = translate_block_adaptive(llm, sources[:mid], history, glossary, context_size)
    left_history = [line for line in left or [] if line]
    right_history = (history + left_history)[-context_size:] if context_size > 0 else []
    right, right_rescued = translate_block_adaptive(llm, sources[mid:], right_history, glossary, context_size)
    if left is None and right is None:
        return None, False
    left_slots = left if left is not None else [None] * mid
    right_slots = right if right is not None else [None] * (len(sources) - mid)
    return left_slots + right_slots, True


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Translate a Japanese SRT to Chinese with Sakura-GalTransl.")
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model-path", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--n-gpu-layers", type=int, default=-1)
    parser.add_argument("--terms-report", type=Path)
    parser.add_argument("--no-glossary", action="store_true")
    parser.add_argument("--no-terms-report", action="store_true")
    add_dataclass_arguments(parser, GalTranslTranslateConfig)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.context_size < 0:
        raise SystemExit("--context-size must be >= 0")
    if args.batch_size < 0:
        raise SystemExit("--batch-size must be >= 0")
    if args.lead_out_seconds < 0 or args.min_display_seconds < 0:
        raise SystemExit("--lead-out-seconds and --min-display-seconds must be >= 0")
    if not args.model_path.exists():
        raise SystemExit(f"Missing GalTransl model: {args.model_path}")

    entries = parse_srt(args.input)
    if args.limit:
        entries = entries[: args.limit]

    glossary = () if args.no_glossary else DEFAULT_GLOSSARY
    terms_report_path = args.terms_report if args.terms_report else args.output.with_suffix(".terms.txt")

    llm = Llama(
        model_path=str(args.model_path),
        n_ctx=4096,
        n_gpu_layers=args.n_gpu_layers,
        verbose=False,
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as f:
        history: list[str] = []  # prior translations (Chinese), oldest -> newest
        previous_end: float | None = None
        term_issue_rows: list[tuple[Entry, str, list[GlossaryTerm]]] = []
        # Standalone lines (no applicable history) are pure functions of their source,
        # so they are memoized; repeated lines dominate this material.
        translation_cache: dict[str, str] = {}
        cache_hits = 0
        prev_source: str | None = None
        prev_translated: str | None = None
        duplicate_retries = 0
        duplicate_resolved = 0
        batch_blocks = 0
        batch_full_blocks = 0
        batch_partial_blocks = 0
        batch_rescued = 0
        batch_fallback_slots = 0

        def emit(entry: Entry, translated: str, next_entry: Entry | None) -> None:
            """Write one cue, record glossary issues, and advance history/dedup state."""
            nonlocal prev_source, prev_translated
            issues = glossary_issues(entry.text, translated, glossary)
            if issues:
                term_issue_rows.append((entry, translated, issues))
            write_entry(f, entry, translated, next_entry, args.lead_out_seconds, args.min_display_seconds)
            history.append(translated)
            prev_source, prev_translated = normalize_source(entry.text), translated
            print(f"{entry.index}: {translated}", flush=True)

        def translate_line(entry: Entry) -> str:
            """Per-line translation with cache, empty retry, and adjacent-duplicate nudge."""
            nonlocal cache_hits, duplicate_retries, duplicate_resolved
            turns = history[-args.context_size :] if args.context_size > 0 else []
            source = normalize_source(entry.text)
            standalone = not turns or is_context_sensitive_short_text(source)
            cached = translation_cache.get(source) if standalone else None
            if cached is not None:
                cache_hits += 1
                return cached
            translated = translate_with_retry(llm, entry.text, turns, glossary)
            if standalone and translated:
                translation_cache[source] = translated
            if not translated:
                translated = translate_one(llm, entry.text, [], glossary, frequency_penalty=0.2, temperature=0.7)
            if not translated:
                translated = entry.text
            # Adjacent-duplicate nudge: ultra-short interjection lines tend to collapse
            # onto the previous line's translation even when the source differs. One
            # standalone retry; keep the duplicate if the model insists.
            if prev_translated is not None and translated == prev_translated and source != prev_source:
                duplicate_retries += 1
                retried = translate_one(llm, entry.text, [], glossary, frequency_penalty=0.2)
                if (
                    retried
                    and retried != prev_translated
                    and not KANA_RE.search(retried)
                    and not looks_degenerate(source, retried)
                ):
                    translated = retried
                    duplicate_resolved += 1
                    if standalone:
                        translation_cache[source] = retried
            return translated

        idx = 0
        while idx < len(entries):
            if previous_end is not None and entries[idx].start - previous_end > HISTORY_RESET_SECONDS:
                history = []
            # Group consecutive cues into a block, never crossing a >RESET gap (which is
            # a scene/turn boundary and also where history resets).
            block = [entries[idx]]
            k = idx + 1
            while (
                args.batch_size > 1
                and len(block) < args.batch_size
                and k < len(entries)
                and entries[k].start - entries[k - 1].end <= HISTORY_RESET_SECONDS
            ):
                block.append(entries[k])
                k += 1
            translated_block: list[str | None] | None = None
            if len(block) > 1:
                batch_blocks += 1
                turns = history[-args.context_size :] if args.context_size > 0 else []
                translated_block, rescued = translate_block_adaptive(
                    llm,
                    [e.text for e in block],
                    turns,
                    glossary,
                    args.context_size,
                )
                if translated_block is not None:
                    rejected_slots = sum(1 for line in translated_block if line is None)
                    if rejected_slots:
                        batch_partial_blocks += 1
                        batch_fallback_slots += rejected_slots
                    else:
                        batch_full_blocks += 1
                    if rescued:
                        batch_rescued += 1
            for bi, entry in enumerate(block):
                next_entry = entries[idx + bi + 1] if idx + bi + 1 < len(entries) else None
                # Batch-accepted slots use the aligned line; rejected slots fall back to per-line.
                translated = (
                    translated_block[bi]
                    if translated_block is not None and translated_block[bi] is not None
                    else translate_line(entry)
                )
                emit(entry, translated, next_entry)
            previous_end = block[-1].end
            idx = k

    print(f"Translation cache hits: {cache_hits}/{len(entries)}")
    print(f"Adjacent duplicate retries resolved: {duplicate_resolved}/{duplicate_retries}")
    if batch_blocks:
        print(f"Batch blocks fully accepted: {batch_full_blocks}/{batch_blocks}")
        print(f"Batch blocks partially accepted: {batch_partial_blocks}/{batch_blocks}")
        print(f"Batch blocks rescued by strict retry: {batch_rescued}")
        print(f"Batch fallback slots: {batch_fallback_slots}")
    print(f"Wrote {args.output}")
    if not args.no_terms_report and glossary:
        write_terms_report(terms_report_path, term_issue_rows)
        print(f"Terminology report: {terms_report_path}")


if __name__ == "__main__":
    main()
