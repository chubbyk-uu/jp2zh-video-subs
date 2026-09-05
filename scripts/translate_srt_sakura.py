from __future__ import annotations

import argparse
from pathlib import Path

from atomic_io import atomic_text_writer
from portable_runtime import prepare_llama_cuda_dependencies, project_root

prepare_llama_cuda_dependencies(Path(__file__))

from llama_cpp import Llama

from cli_config import add_dataclass_arguments, config_from_namespace
from pipeline_configs import (
    SakuraTranslateConfig,
    raise_for_config_issues,
    validate_translation_config,
)
from translation_common import (
    DEFAULT_GLOSSARY,
    Entry,
    GlossaryTerm,
    HISTORY_RESET_SECONDS,
    KANA_RE,
    clean_translation,
    glossary_issues,
    is_context_sensitive_short_text,
    looks_degenerate,
    normalize_source,
    parse_srt,
    relevant_terms,
    write_entry,
    write_terms_report,
)


PROJECT_ROOT = project_root(Path(__file__))
DEFAULT_MODEL = PROJECT_ROOT / "models" / "Sakura-14B-Qwen2.5-v1.0-GGUF" / "sakura-14b-qwen2.5-v1.0-iq4xs.gguf"

# Sakura v1.0 (Qwen2.5) was trained on this exact template. System prompt and the
# dictionary phrasing are fixed by the model card.
SAKURA_SYSTEM = (
    "你是一个轻小说翻译模型，可以流畅通顺地以日本轻小说的风格将日文翻译成简体中文，"
    "并联系上下文正确使用人称代词，不擅自添加原文中没有的代词。"
)
PLAIN_USER = "将下面的日文文本翻译成中文："


def sakura_user_prompt(text: str, glossary: tuple[GlossaryTerm, ...]) -> str:
    """Current-line user turn, with a Sakura GPT dictionary only when terms apply."""
    terms = relevant_terms(text, glossary)
    if not terms:
        return f"{PLAIN_USER}{text}"
    dict_lines = "\n".join(
        f"{t.source}->{t.target} #{t.note}" if t.note else f"{t.source}->{t.target}"
        for t in terms
    )
    return (
        "根据以下术语表（可以为空）：\n"
        f"{dict_lines}\n"
        f"将下面的日文文本根据对应关系和备注翻译成中文：{text}"
    )


def build_messages(text: str, history: list[tuple[str, str]], glossary: tuple[GlossaryTerm, ...]) -> list[dict]:
    messages: list[dict] = [{"role": "system", "content": SAKURA_SYSTEM}]
    for prev_source, prev_translation in history:
        messages.append({"role": "user", "content": f"{PLAIN_USER}{prev_source}"})
        messages.append({"role": "assistant", "content": prev_translation})
    messages.append({"role": "user", "content": sakura_user_prompt(text, glossary)})
    return messages


def translate_one(
    llm: Llama,
    text: str,
    history: list[tuple[str, str]] | None = None,
    glossary: tuple[GlossaryTerm, ...] = DEFAULT_GLOSSARY,
    frequency_penalty: float = 0.0,
    temperature: float = 0.1,
) -> str:
    text = normalize_source(text)
    # Short fillers translate better standalone than swayed by a prior turn.
    if history is None or is_context_sensitive_short_text(text):
        history = []
    result = llm.create_chat_completion(
        messages=build_messages(text, history, glossary),
        max_tokens=512,
        temperature=temperature,
        top_p=0.3,
        top_k=40,
        repeat_penalty=1.0,
        frequency_penalty=frequency_penalty,
    )
    return clean_translation(result["choices"][0]["message"]["content"])


def translate_with_retry(
    llm: Llama,
    text: str,
    history: list[tuple[str, str]] | None = None,
    glossary: tuple[GlossaryTerm, ...] = DEFAULT_GLOSSARY,
) -> str:
    translated = translate_one(llm, text, history, glossary)
    # Official guidance: on degeneration (looping/runaway) raise frequency_penalty.
    if looks_degenerate(text, translated):
        translated = translate_one(llm, text, history, glossary, frequency_penalty=0.2)
    # Kana leak safety: retry standalone with a penalty; if kana still survives the
    # deterministic retry, nudge the sampling once (temperature) to escape an echo.
    if KANA_RE.search(translated):
        translated = translate_one(llm, text, [], glossary, frequency_penalty=0.2)
    if KANA_RE.search(translated):
        retried = translate_one(llm, text, [], glossary, frequency_penalty=0.3, temperature=0.7)
        if retried and not KANA_RE.search(retried):
            translated = retried
    # Glossary violation: retry standalone. The per-line dictionary already narrows to
    # the matched term; dropping history removes competing context.
    if glossary_issues(text, translated, glossary):
        retried = translate_one(llm, text, [], glossary)
        if (
            retried
            and not KANA_RE.search(retried)
            and not looks_degenerate(text, retried)
            and not glossary_issues(text, retried, glossary)
        ):
            translated = retried
    return translated


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Translate a Japanese SRT to Chinese with SakuraLLM.")
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model-path", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--n-gpu-layers", type=int, default=-1)
    parser.add_argument("--terms-report", type=Path)
    parser.add_argument("--no-glossary", action="store_true")
    parser.add_argument("--no-terms-report", action="store_true")
    add_dataclass_arguments(parser, SakuraTranslateConfig)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    raise_for_config_issues(
        validate_translation_config(config_from_namespace(args, SakuraTranslateConfig))
    )
    if not args.model_path.exists():
        raise SystemExit(f"Missing Sakura model: {args.model_path}")

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
    with atomic_text_writer(args.output) as f:
        history: list[tuple[str, str]] = []
        previous_end: float | None = None
        term_issue_rows: list[tuple[Entry, str, list[GlossaryTerm]]] = []
        # Repeated lines dominate this material, so standalone translations are
        # memoized. A line is standalone when no history turns apply — either none
        # are available or translate_one drops them (context-sensitive short text) —
        # which makes its translation a pure function of the source text.
        translation_cache: dict[str, str] = {}
        cache_hits = 0
        prev_source: str | None = None
        prev_translated: str | None = None
        duplicate_retries = 0
        duplicate_resolved = 0
        for index, entry in enumerate(entries):
            next_entry = entries[index + 1] if index + 1 < len(entries) else None
            if previous_end is not None and entry.start - previous_end > HISTORY_RESET_SECONDS:
                history = []
            turns = history[-args.context_size :] if args.context_size > 0 else []
            source = normalize_source(entry.text)
            standalone = not turns or is_context_sensitive_short_text(source)
            cached = translation_cache.get(source) if standalone else None
            if cached is not None:
                translated = cached
                cache_hits += 1
            else:
                translated = translate_with_retry(llm, entry.text, turns, glossary)
                if standalone and translated:
                    translation_cache[source] = translated
            if not translated:
                # An empty completion is a failure mode of its own: one nudged
                # standalone retry before falling back to the source text (which
                # the quality report would flag as kana residue).
                translated = translate_one(llm, entry.text, [], glossary, frequency_penalty=0.2, temperature=0.7)
            if not translated:
                translated = entry.text
            # Adjacent-duplicate nudge: ultra-short interjection lines tend to
            # collapse onto the previous line's translation even when the source
            # differs. One standalone retry with a penalty; keep the duplicate if
            # the model insists (different sources can genuinely share a rendering).
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
            issues = glossary_issues(entry.text, translated, glossary)
            if issues:
                term_issue_rows.append((entry, translated, issues))
            write_entry(f, entry, translated, next_entry, args.lead_out_seconds, args.min_display_seconds)
            history.append((source, translated))
            prev_source, prev_translated = source, translated
            previous_end = entry.end
            print(f"{entry.index}: {translated}", flush=True)

    print(f"Translation cache hits: {cache_hits}/{len(entries)}")
    print(f"Adjacent duplicate retries resolved: {duplicate_resolved}/{duplicate_retries}")
    print(f"Wrote {args.output}")
    if not args.no_terms_report and glossary:
        write_terms_report(terms_report_path, term_issue_rows)
        print(f"Terminology report: {terms_report_path}")


if __name__ == "__main__":
    main()
