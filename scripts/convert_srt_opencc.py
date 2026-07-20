"""Convert only subtitle text in an SRT with OpenCC, preserving cue structure."""
from __future__ import annotations

import argparse
import re
from pathlib import Path


def convert_srt_text(content: str, converter) -> str:
    """Convert cue payloads while leaving indices, timestamps, and blank lines intact."""
    trailing_newline = "\n" if content.endswith("\n") else ""
    blocks = re.split(r"\n\s*\n", content.strip()) if content.strip() else []
    converted: list[str] = []
    for block in blocks:
        lines = block.splitlines()
        if len(lines) >= 3 and "-->" in lines[1]:
            lines[2:] = [converter.convert(line) for line in lines[2:]]
        converted.append("\n".join(lines))
    return "\n\n".join(converted) + trailing_newline


def convert_srt(source: Path, output: Path, config: str = "s2t") -> None:
    from opencc import OpenCC

    result = convert_srt_text(source.read_text(encoding="utf-8"), OpenCC(config))
    output.parent.mkdir(parents=True, exist_ok=True)
    partial = output.with_name(output.name + ".part")
    partial.write_text(result, encoding="utf-8")
    partial.replace(output)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Convert SRT subtitle text with OpenCC.")
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--config", default="s2t", help="OpenCC conversion config (default: s2t)")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    convert_srt(args.input, args.output, args.config)
    print(f"OpenCC {args.config}: wrote {args.output}")


if __name__ == "__main__":
    main()
