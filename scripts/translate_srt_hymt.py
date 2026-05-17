from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path

from llama_cpp import Llama


PROJECT_ROOT = Path(__file__).resolve().parents[1] if Path(__file__).resolve().parent.name == "scripts" else Path(__file__).resolve().parent
DEFAULT_MODEL = PROJECT_ROOT / "models" / "HY-MT1.5-7B-GGUF" / "HY-MT1.5-7B-Q4_K_M.gguf"


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
        if len(lines) < 3:
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
    replacements = {
        "禁欲チャット": "禁欲ちゃんと",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    return text


def translate_one(llm: Llama, text: str, context: str) -> str:
    text = normalize_source(text)
    if context:
        prompt = (
            "以下是前文字幕，仅用于理解语境，不要翻译前文，也不要输出前文：\n"
            f"<context>{context}</context>\n\n"
            "参考上面的信息，把 <current> 标签内的日文成人影片字幕翻译成自然、口语化的简体中文。"
            "只输出当前句的中文纯文本译文，不要解释，不要保留日文，不要输出任何 XML 标签：\n"
            f"<current>{text}</current>"
        )
    else:
        prompt = (
            "将以下日文成人影片字幕翻译为自然、口语化的简体中文。"
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
    parser.add_argument("--context-size", type=int, default=5)
    parser.add_argument("--n-gpu-layers", type=int, default=-1)
    args = parser.parse_args()

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
        for entry in entries:
            context = "\n".join(previous_source[-args.context_size :])
            translated = translate_one(llm, entry.text, context)
            if not translated:
                translated = entry.text
            write_entry(f, entry, translated)
            previous_source.append(normalize_source(entry.text))
            print(f"{entry.index}: {translated}", flush=True)

    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
