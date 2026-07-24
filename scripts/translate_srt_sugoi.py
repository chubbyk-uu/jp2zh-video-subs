from __future__ import annotations

import argparse
import re
from pathlib import Path

from atomic_io import atomic_text_writer
from portable_runtime import prepare_llama_cuda_dependencies, project_root

prepare_llama_cuda_dependencies(Path(__file__))

from llama_cpp import Llama

from cli_config import add_dataclass_arguments, config_from_namespace
from pipeline_configs import (
    SugoiTranslateConfig,
    raise_for_config_issues,
    validate_translation_config,
)
from target_languages import TargetLanguage, resolve_translation_settings
from translation_common import HISTORY_RESET_SECONDS, Entry, parse_srt, write_entry


PROJECT_ROOT = project_root(Path(__file__))
DEFAULT_MODEL = PROJECT_ROOT / "models" / "Sugoi-14B-Ultra-GGUF" / "Sugoi-14B-Ultra-Q4_K_M.gguf"
SUGOI_SYSTEM = (
    "You are a professional localizer whose primary goal is to translate Japanese to English. "
    "You should use colloquial or slang or nsfw vocabulary if it makes the translation more accurate. "
    "Always respond in English."
)
NON_ENGLISH_SCRIPT_RE = re.compile(r"[\u3040-\u30ff\u3400-\u9fff]")
NUMBERED_LINE_RE = re.compile(r"^\[(\d+)\]\s*(.*)$")


def numbered_prompt(sources: list[str]) -> str:
    lines = [f"[{index:03d}] {source.replace(chr(10), ' ')}" for index, source in enumerate(sources, 1)]
    return (
        "Translate every numbered Japanese subtitle below into natural English. "
        "Return exactly one line for each input, preserve every [NNN] identifier, "
        "and do not add explanations.\n" + "\n".join(lines)
    )


def parse_numbered_output(raw: str, count: int) -> list[str] | None:
    found: dict[int, str] = {}
    for line in raw.strip().splitlines():
        if not line.strip():
            continue
        match = NUMBERED_LINE_RE.match(line.strip())
        if match is None:
            return None
        identifier = int(match.group(1))
        text = match.group(2).strip()
        if identifier in found or not 1 <= identifier <= count or not text:
            return None
        found[identifier] = text
    if set(found) != set(range(1, count + 1)):
        return None
    return [found[index] for index in range(1, count + 1)]


def completion(llm: Llama, user: str, max_tokens: int) -> str:
    result = llm.create_chat_completion(
        messages=[
            {"role": "system", "content": SUGOI_SYSTEM},
            {"role": "user", "content": user},
        ],
        max_tokens=max_tokens,
        temperature=0.1,
        top_k=40,
        top_p=0.95,
        min_p=0.05,
        repeat_penalty=1.1,
    )
    return result["choices"][0]["message"]["content"].strip()


def safe_translation(source: str, translated: str) -> bool:
    if not translated or NON_ENGLISH_SCRIPT_RE.search(translated):
        return False
    # English normally uses many more characters than Japanese; the Chinese
    # translator's 3x-length heuristic would reject valid sentences. Keep only a
    # very high runaway cap plus explicit repetition-loop detection here.
    if len(translated) > max(240, 10 * len(source) + 80):
        return False
    return not any(re.search(r"(.{%d})\1{5,}" % size, translated) for size in range(1, 13))


def translate_one(llm: Llama, source: str) -> str:
    prompts = (
        source.replace("\n", " "),
        "Translate only this Japanese subtitle into English:\n" + source,
    )
    for prompt in prompts:
        translated = completion(llm, prompt, 512)
        if safe_translation(source, translated):
            return translated.splitlines()[0].strip()
    numbered = completion(llm, numbered_prompt([source]), 512)
    lines = parse_numbered_output(numbered, 1)
    if lines and safe_translation(source, lines[0]):
        return lines[0]
    raise RuntimeError("Sugoi could not produce a safe English translation for one subtitle cue")


def translate_batch_checked(llm: Llama, sources: list[str]) -> list[str | None] | None:
    raw = completion(llm, numbered_prompt(sources), min(2048, 160 * len(sources) + 256))
    lines = parse_numbered_output(raw, len(sources))
    if lines is None:
        return None
    return [line if safe_translation(source, line) else None for source, line in zip(sources, lines)]


def translate_batch_adaptive(llm: Llama, sources: list[str]) -> list[str | None]:
    """Split structurally invalid batches; leave unsafe individual slots for fallback."""
    translated = translate_batch_checked(llm, sources)
    if translated is not None:
        return translated
    if len(sources) == 1:
        return [None]
    midpoint = len(sources) // 2
    return translate_batch_adaptive(llm, sources[:midpoint]) + translate_batch_adaptive(llm, sources[midpoint:])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Translate a Japanese SRT to English with Sugoi 14B Ultra.")
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model-path", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--n-gpu-layers", type=int, default=-1)
    add_dataclass_arguments(parser, SugoiTranslateConfig)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    raise_for_config_issues(
        validate_translation_config(config_from_namespace(args, SugoiTranslateConfig))
    )
    batch_size = resolve_translation_settings(
        "sugoi", TargetLanguage.ENGLISH, batch_size=args.batch_size
    ).batch_size
    if not args.model_path.exists():
        raise SystemExit(f"Missing Sugoi model: {args.model_path}")

    entries = parse_srt(args.input)
    if args.limit:
        entries = entries[: args.limit]
    llm = Llama(model_path=str(args.model_path), n_ctx=4096, n_gpu_layers=args.n_gpu_layers, seed=42, verbose=False)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    fallback_slots = 0
    with atomic_text_writer(args.output) as output:
        index = 0
        while index < len(entries):
            block = [entries[index]]
            cursor = index + 1
            while (
                len(block) < batch_size
                and cursor < len(entries)
                and entries[cursor].start - entries[cursor - 1].end <= HISTORY_RESET_SECONDS
            ):
                block.append(entries[cursor])
                cursor += 1
            translated = translate_batch_adaptive(llm, [entry.text for entry in block])
            for offset, (entry, text) in enumerate(zip(block, translated)):
                if text is None:
                    fallback_slots += 1
                    try:
                        text = translate_one(llm, entry.text)
                    except RuntimeError as exc:
                        raise RuntimeError(f"Cue {entry.index}: {exc}") from exc
                next_index = index + offset + 1
                next_entry = entries[next_index] if next_index < len(entries) else None
                write_entry(output, entry, text, next_entry, args.lead_out_seconds, args.min_display_seconds)
                print(f"{entry.index}: {text}", flush=True)
            index = cursor
    print(f"Batch fallback slots: {fallback_slots}")
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
