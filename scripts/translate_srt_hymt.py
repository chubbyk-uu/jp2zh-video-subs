from __future__ import annotations

import argparse
import difflib
import re
from dataclasses import dataclass
from pathlib import Path

from llama_cpp import Llama

from srt_utils import compact_text


PROJECT_ROOT = Path(__file__).resolve().parents[1] if Path(__file__).resolve().parent.name == "scripts" else Path(__file__).resolve().parent
DEFAULT_MODEL = PROJECT_ROOT / "models" / "HY-MT1.5-7B-GGUF" / "HY-MT1.5-7B-Q4_K_M.gguf"

# Context-bleed detection: the current translation echoes the previous one even
# though the two source lines are clearly different. Retranslate without context.
DUP_TRANSLATION_RATIO = 0.8  # current vs previous translation must be at least this similar
DIFF_SOURCE_RATIO = 0.5  # current vs previous source must be at most this similar


@dataclass
class Entry:
    index: str
    time: str
    text: str


def parse_srt(path: Path) -> list[Entry]:
    blocks = re.split(r"\n\s*\n", path.read_text(encoding="utf-8").strip())
    entries: list[Entry] = []
    for block in blocks:
        lines = block.splitlines()
        if len(lines) < 3 or "-->" not in lines[1]:
            continue
        entries.append(Entry(lines[0].strip(), lines[1].strip(), "\n".join(lines[2:]).strip()))
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


def text_ratio(a: str, b: str) -> float:
    """Order- and length-aware similarity in [0, 1] on whitespace-stripped text.

    Uses difflib (Ratcliff/Obershelp), not a character-set overlap, so frequent
    shared CJK characters do not inflate the score for unrelated lines."""
    a, b = compact_text(a), compact_text(b)
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def is_context_bleed(
    source: str,
    translated: str,
    previous_source: str,
    previous_translation: str,
    translation_ratio: float = DUP_TRANSLATION_RATIO,
    source_ratio: float = DIFF_SOURCE_RATIO,
) -> bool:
    """True when the translation echoes the previous one while the sources differ.

    The asymmetry is the signal: a genuinely repeated line keeps a similar source,
    so it is left alone; only a translation that copies the previous line despite a
    different source is treated as context leaking in."""
    if not previous_translation:
        return False
    return (
        text_ratio(translated, previous_translation) >= translation_ratio
        and text_ratio(source, previous_source) <= source_ratio
    )


def looks_context_leaked(source: str, translated: str) -> bool:
    source_compact = re.sub(r"\s+", "", source)
    translated_compact = re.sub(r"\s+", "", translated)
    if not translated_compact:
        return False
    if re.search(r"[ぁ-ゟ゠-ヿ]", translated_compact):
        return True
    if any(token in translated_compact for token in ("さん", "ちゃん", "くん", "<context>", "<current>")):
        return True
    if len(source_compact) <= 2 and len(translated_compact) > 10:
        return True
    return len(translated_compact) > max(36, len(source_compact) * 3 + 18)


def translate_one(llm: Llama, text: str, context: str, extra_instruction: str = "") -> str:
    text = normalize_source(text)
    if is_context_sensitive_short_text(text):
        context = ""
    instruction = f"{extra_instruction}" if extra_instruction else ""
    if context:
        prompt = (
            "以下是前文字幕，仅用于理解语境，不要翻译前文，也不要输出前文：\n"
            f"<context>{context}</context>\n\n"
            "参考上面的信息，把 <current> 标签内的日语字幕翻译成自然、口语化的简体中文。"
            f"{instruction}"
            "只输出当前句的中文纯文本译文，不要解释，不要保留日文，不要输出任何 XML 标签：\n"
            f"<current>{text}</current>"
        )
    else:
        prompt = (
            "将以下日语字幕翻译为自然、口语化的简体中文。"
            f"{instruction}"
            "只输出译文，不要解释，不要保留日文：\n"
            f"{text}"
        )
    result = llm.create_chat_completion(
        messages=[{"role": "user", "content": prompt}],
        max_tokens=160,
        temperature=0.2,
        top_k=20,
        top_p=0.6,
        repeat_penalty=1.05,
    )
    return clean_translation(result["choices"][0]["message"]["content"])


def translate_with_retry(
    llm: Llama,
    text: str,
    context: str,
    previous_source: str = "",
    previous_translation: str = "",
) -> str:
    translated = translate_one(llm, text, context)
    if context and looks_context_leaked(text, translated):
        translated = translate_one(llm, text, "")
    if context and is_context_bleed(text, translated, previous_source, previous_translation):
        translated = translate_one(
            llm,
            text,
            "",
            "这句和上一句原文不同，必须只翻译当前句，不能照抄上一句译文。",
        )
    if re.search(r"[ぁ-ゟ゠-ヿ]", translated):
        translated = translate_one(
            llm,
            text,
            "",
            "译文中不能出现任何日文假名或片假名；人名请音译成中文。",
        )
    return translated


def write_entry(f, entry: Entry, text: str) -> None:
    f.write(f"{entry.index}\n")
    f.write(f"{entry.time}\n")
    f.write(f"{text}\n\n")
    f.flush()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model-path", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--context-size", type=int, default=2)
    parser.add_argument("--n-gpu-layers", type=int, default=-1)
    args = parser.parse_args()
    if args.context_size < 0:
        raise SystemExit("--context-size must be >= 0")

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
        previous_source: list[str] = []
        previous_translation = ""
        for entry in entries:
            context = ""
            if args.context_size > 0:
                context = "\n".join(previous_source[-args.context_size :])
            translated = translate_with_retry(
                llm,
                entry.text,
                context,
                previous_source[-1] if previous_source else "",
                previous_translation,
            )
            if not translated:
                translated = entry.text
            write_entry(f, entry, translated)
            previous_source.append(normalize_source(entry.text))
            previous_translation = translated
            print(f"{entry.index}: {translated}", flush=True)

    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
