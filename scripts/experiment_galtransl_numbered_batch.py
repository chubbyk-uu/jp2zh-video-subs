from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path

from llama_cpp import Llama

from translate_srt_galtransl import (
    DEFAULT_MODEL,
    GALTRANSL_SYSTEM,
    GLOSSARY_HEADER,
    KANA_RE,
    TRANSLATE_INSTRUCTION,
    build_messages,
    glossary_block,
    looks_degenerate,
    translate_block,
    translate_with_retry,
    union_terms,
)
from translate_srt_hymt import (
    DEFAULT_GLOSSARY,
    HISTORY_RESET_SECONDS,
    Entry,
    GlossaryTerm,
    clean_translation,
    normalize_source,
    parse_srt,
    write_entry,
)


NUMBERED_LINE_RE = re.compile(
    r"^\s*[\[【(（]?\s*(\d{1,3})\s*[\]】)）]?\s*[\.．、:：]?\s*(.*)$"
)
PREVIEW_WIDTH = 160


@dataclass(frozen=True)
class NumberedParseResult:
    lines: list[str] | None
    reason: str
    missing: tuple[int, ...] = ()
    extra: tuple[int, ...] = ()
    duplicate: tuple[int, ...] = ()
    unnumbered: tuple[str, ...] = ()


def build_numbered_user_prompt(
    text: str,
    history: list[str],
    glossary: tuple[GlossaryTerm, ...],
) -> str:
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
    parts.append(
        "下面每行都以 [编号] 开头。请逐行翻译，并且每行输出必须保留相同编号；"
        "不要合并编号，不要拆分编号，不要新增编号，也不要省略编号。"
    )
    parts.append(text)
    return "\n".join(parts)


def build_numbered_messages(
    text: str,
    history: list[str],
    glossary: tuple[GlossaryTerm, ...],
) -> list[dict]:
    return [
        {"role": "system", "content": GALTRANSL_SYSTEM},
        {"role": "user", "content": build_numbered_user_prompt(text, history, glossary)},
    ]


def parse_numbered_output(raw: str, expected_count: int) -> NumberedParseResult:
    numbered: dict[int, str] = {}
    duplicate: list[int] = []
    extra: list[int] = []
    unnumbered: list[str] = []
    for raw_line in raw.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = NUMBERED_LINE_RE.match(line)
        if not match:
            unnumbered.append(line)
            continue
        index = int(match.group(1))
        text = clean_translation(match.group(2))
        if index < 1 or index > expected_count:
            extra.append(index)
            continue
        if index in numbered:
            duplicate.append(index)
            continue
        numbered[index] = text

    missing = [idx for idx in range(1, expected_count + 1) if idx not in numbered]
    if unnumbered:
        return NumberedParseResult(None, "unnumbered", tuple(missing), tuple(extra), tuple(duplicate), tuple(unnumbered))
    if extra:
        return NumberedParseResult(None, "extra-number", tuple(missing), tuple(extra), tuple(duplicate))
    if duplicate:
        return NumberedParseResult(None, "duplicate-number", tuple(missing), tuple(extra), tuple(duplicate))
    if missing:
        return NumberedParseResult(None, "missing-number", tuple(missing), tuple(extra), tuple(duplicate))
    lines = [numbered[idx] for idx in range(1, expected_count + 1)]
    if any(not line for line in lines):
        return NumberedParseResult(None, "empty-line")
    return NumberedParseResult(lines, "accepted")


def translate_numbered_block(
    llm: Llama,
    sources: list[str],
    history: list[str],
    glossary: tuple[GlossaryTerm, ...],
) -> tuple[list[str] | None, str, str]:
    src_lines = [normalize_source(s).replace("\n", " ") for s in sources]
    numbered_text = "\n".join(f"[{idx}] {line}" for idx, line in enumerate(src_lines, start=1))
    result = llm.create_chat_completion(
        messages=build_numbered_messages(numbered_text, history, union_terms(src_lines, glossary)),
        max_tokens=min(2048, 180 * len(src_lines) + 320),
        temperature=0.3,
        top_p=0.8,
        top_k=40,
        repeat_penalty=1.0,
    )
    raw = result["choices"][0]["message"]["content"].strip()
    parsed = parse_numbered_output(raw, len(src_lines))
    if parsed.lines is None:
        return None, parsed.reason, raw
    if any(KANA_RE.search(line) for line in parsed.lines):
        return None, "kana-leak", raw
    if any(looks_degenerate(source, line) for source, line in zip(src_lines, parsed.lines)):
        return None, "degenerate", raw
    return parsed.lines, "accepted", raw


def write_report_header(file) -> None:
    file.write(
        "\t".join(
            [
                "block_start",
                "block_end",
                "cue_count",
                "strict",
                "numbered",
                "numbered_reason",
                "sources",
                "numbered_raw_preview",
            ]
        )
        + "\n"
    )


def preview(text: str) -> str:
    one_line = " ".join(text.split())
    if len(one_line) > PREVIEW_WIDTH:
        return one_line[: PREVIEW_WIDTH - 1] + "..."
    return one_line


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Experiment with numbered GalTransl batch translation without changing the main pipeline."
    )
    parser.add_argument("input", type=Path, help="Japanese SRT")
    parser.add_argument("--output", type=Path, required=True, help="Chinese SRT produced by numbered batch + fallback")
    parser.add_argument("--report", type=Path, help="TSV report of strict vs numbered batch acceptance")
    parser.add_argument("--model-path", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--context-size", type=int, default=2)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--n-gpu-layers", type=int, default=-1)
    parser.add_argument("--no-glossary", action="store_true")
    args = parser.parse_args()

    if args.batch_size < 2:
        raise SystemExit("--batch-size must be >= 2 for this experiment")
    if args.context_size < 0:
        raise SystemExit("--context-size must be >= 0")
    if not args.model_path.exists():
        raise SystemExit(f"Missing GalTransl model: {args.model_path}")

    entries = parse_srt(args.input)
    if args.limit:
        entries = entries[: args.limit]
    glossary = () if args.no_glossary else DEFAULT_GLOSSARY
    report_path = args.report or args.output.with_suffix(".numbered-batch.tsv")

    llm = Llama(model_path=str(args.model_path), n_ctx=4096, n_gpu_layers=args.n_gpu_layers, verbose=False)

    strict_accepted = 0
    numbered_accepted = 0
    strict_rejected_numbered_accepted = 0
    numbered_rejected_strict_accepted = 0
    block_count = 0

    history: list[str] = []
    previous_end: float | None = None
    with args.output.open("w", encoding="utf-8", newline="") as out, report_path.open(
        "w", encoding="utf-8", newline=""
    ) as report:
        write_report_header(report)
        idx = 0
        while idx < len(entries):
            if previous_end is not None and entries[idx].start - previous_end > HISTORY_RESET_SECONDS:
                history = []
            block = [entries[idx]]
            k = idx + 1
            while (
                len(block) < args.batch_size
                and k < len(entries)
                and entries[k].start - entries[k - 1].end <= HISTORY_RESET_SECONDS
            ):
                block.append(entries[k])
                k += 1

            translations: list[str]
            if len(block) > 1:
                block_count += 1
                turns = history[-args.context_size :] if args.context_size > 0 else []
                sources = [entry.text for entry in block]
                strict = translate_block(llm, sources, turns, glossary)
                numbered, numbered_reason, numbered_raw = translate_numbered_block(llm, sources, turns, glossary)
                strict_ok = strict is not None
                numbered_ok = numbered is not None
                strict_accepted += int(strict_ok)
                numbered_accepted += int(numbered_ok)
                strict_rejected_numbered_accepted += int((not strict_ok) and numbered_ok)
                numbered_rejected_strict_accepted += int(strict_ok and (not numbered_ok))

                report.write(
                    "\t".join(
                        [
                            str(block[0].index),
                            str(block[-1].index),
                            str(len(block)),
                            "accepted" if strict_ok else "fallback",
                            "accepted" if numbered_ok else "fallback",
                            numbered_reason,
                            preview(" / ".join(sources)),
                            preview(numbered_raw),
                        ]
                    )
                    + "\n"
                )
                translations = numbered if numbered is not None else (strict if strict is not None else [])
            else:
                translations = []
            if not translations:
                fallback_history = list(history)
                for entry in block:
                    turns = fallback_history[-args.context_size :] if args.context_size > 0 else []
                    translated = translate_with_retry(llm, entry.text, turns, glossary)
                    translations.append(translated)
                    if args.context_size > 0:
                        fallback_history.append(translated)
            for bi, entry in enumerate(block):
                next_entry = entries[idx + bi + 1] if idx + bi + 1 < len(entries) else None
                write_entry(out, entry, translations[bi], next_entry=next_entry)
                if args.context_size > 0:
                    history.append(translations[bi])
            previous_end = block[-1].end
            idx = k

    print(f"Blocks: {block_count}")
    print(f"Strict accepted: {strict_accepted}/{block_count}")
    print(f"Numbered accepted: {numbered_accepted}/{block_count}")
    print(f"Strict rejected but numbered accepted: {strict_rejected_numbered_accepted}")
    print(f"Numbered rejected but strict accepted: {numbered_rejected_strict_accepted}")
    print(f"Wrote {args.output}")
    print(f"Report {report_path}")


if __name__ == "__main__":
    main()
