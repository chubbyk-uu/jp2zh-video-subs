from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path

from llama_cpp import Llama

from srt_utils import padded_end, parse_time, srt_time


PROJECT_ROOT = Path(__file__).resolve().parents[1] if Path(__file__).resolve().parent.name == "scripts" else Path(__file__).resolve().parent
DEFAULT_MODEL = PROJECT_ROOT / "models" / "HY-MT1.5-7B-GGUF" / "HY-MT1.5-7B-Q4_K_M.gguf"

# HY-MT is a translation-specialised model: it translates whatever source it is shown, so
# any "reference context" placed in the same request gets fused into the output (it bleeds
# the previous line and drops the current one). Context is therefore supplied as prior chat
# turns (previous source -> previous translation); the current turn carries only the line to
# translate, which the model has no reason to merge.
TRANSLATE_INSTRUCTION = "将以下日语字幕翻译为自然、口语化的简体中文。"
TRANSLATE_SUFFIX = "只输出译文，不要解释，不要保留日文："
# Drop carried history across a long silence: lines that far apart are usually different
# scenes, so the previous line is misleading rather than helpful context.
HISTORY_RESET_SECONDS = 10.0


@dataclass
class Entry:
    index: str
    time: str
    text: str
    start: float
    end: float
    settings: str = ""


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
    replacements: dict[str, str] = {}
    for source, target in replacements.items():
        text = text.replace(source, target)
    return text


def is_context_sensitive_short_text(text: str) -> bool:
    compact = re.sub(r"\s+", "", text)
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


def build_messages(text: str, history: list[tuple[str, str]], extra_instruction: str = "") -> list[dict]:
    """Chat turns for one translation: prior (source -> translation) pairs as history,
    then the current source as its own user turn so only it gets translated."""
    instruction = TRANSLATE_INSTRUCTION + extra_instruction + TRANSLATE_SUFFIX
    messages: list[dict] = []
    for position, (prev_source, prev_translation) in enumerate(history):
        # The instruction rides on the first user turn; later turns continue the pattern.
        content = f"{instruction}\n{prev_source}" if position == 0 else prev_source
        messages.append({"role": "user", "content": content})
        messages.append({"role": "assistant", "content": prev_translation})
    if history:
        messages.append({"role": "user", "content": text})
    else:
        messages.append({"role": "user", "content": f"{instruction}\n{text}"})
    return messages


def translate_one(
    llm: Llama,
    text: str,
    history: list[tuple[str, str]] | None = None,
    extra_instruction: str = "",
) -> str:
    text = normalize_source(text)
    # Short, context-sensitive fillers translate better standalone than swayed by a prior
    # turn, so carry no history for them.
    if history is None or is_context_sensitive_short_text(text):
        history = []
    result = llm.create_chat_completion(
        messages=build_messages(text, history, extra_instruction),
        max_tokens=160,
        temperature=0.2,
        top_k=20,
        top_p=0.6,
        repeat_penalty=1.05,
    )
    return clean_translation(result["choices"][0]["message"]["content"])


def translate_with_retry(llm: Llama, text: str, history: list[tuple[str, str]] | None = None) -> str:
    translated = translate_one(llm, text, history)
    # If Japanese kana leaked into the output, retry once standalone with a stronger note.
    if re.search(r"[ぁ-ゟ゠-ヿ]", translated):
        translated = translate_one(
            llm, text, [], "译文中不能出现任何日文假名或片假名；人名请音译成中文。"
        )
    return translated


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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model-path", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument(
        "--context-size",
        type=int,
        default=1,
        help="Number of prior dialogue turns (previous source/translation pairs) supplied "
        "as chat history for context. 0 disables context (translate each line standalone).",
    )
    parser.add_argument("--n-gpu-layers", type=int, default=-1)
    parser.add_argument("--lead-out-seconds", type=float, default=0.0)
    parser.add_argument("--min-display-seconds", type=float, default=0.0)
    args = parser.parse_args()
    if args.context_size < 0:
        raise SystemExit("--context-size must be >= 0")
    if args.lead_out_seconds < 0:
        raise SystemExit("--lead-out-seconds must be >= 0")
    if args.min_display_seconds < 0:
        raise SystemExit("--min-display-seconds must be >= 0")

    entries = parse_srt(args.input)
    if args.limit:
        entries = entries[: args.limit]

    llm = Llama(
        model_path=str(args.model_path),
        n_ctx=4096,
        n_gpu_layers=args.n_gpu_layers,
        verbose=False,
    )

    with args.output.open("w", encoding="utf-8") as f:
        history: list[tuple[str, str]] = []  # (source, translation) pairs, oldest -> newest
        previous_end: float | None = None
        for index, entry in enumerate(entries):
            next_entry = entries[index + 1] if index + 1 < len(entries) else None
            # A long silence usually means a scene change; drop the stale history.
            if previous_end is not None and entry.start - previous_end > HISTORY_RESET_SECONDS:
                history = []
            turns = history[-args.context_size :] if args.context_size > 0 else []
            translated = translate_with_retry(llm, entry.text, turns)
            if not translated:
                translated = entry.text
            write_entry(f, entry, translated, next_entry, args.lead_out_seconds, args.min_display_seconds)
            history.append((normalize_source(entry.text), translated))
            previous_end = entry.end
            print(f"{entry.index}: {translated}", flush=True)

    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
