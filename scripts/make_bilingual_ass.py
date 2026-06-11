from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path

from srt_utils import parse_time


# ASS colours are &HAABBGGRR (alpha, blue, green, red); alpha 00 is fully opaque.
# Microsoft YaHei ships with every Windows install and covers both the Chinese line
# and the Japanese kana/kanji line; Arial has no CJK glyphs, which left the actual
# typeface to the player's fallback. Non-Windows renderers fall back via fontconfig.
DEFAULT_FONT = "Microsoft YaHei"
DEFAULT_ZH_FONT_SIZE = 36
DEFAULT_JA_FONT_SIZE = 24
DEFAULT_ZH_COLOUR = "&H0000FFFF"  # yellow, larger top line
DEFAULT_JA_COLOUR = "&H00B4B4B4"  # light gray, smaller bottom line
DEFAULT_PLAY_RES_X = 1280
DEFAULT_PLAY_RES_Y = 720


@dataclass
class AssEntry:
    index: str
    start: float
    end: float
    text: str


def parse_srt(path: Path) -> list[AssEntry]:
    blocks = re.split(r"\n\s*\n", path.read_text(encoding="utf-8").strip())
    entries: list[AssEntry] = []
    for block in blocks:
        lines = block.splitlines()
        if len(lines) < 3 or "-->" not in lines[1]:
            continue
        start_str, end_str = (part.strip() for part in lines[1].split("-->", 1))
        end_str = end_str.split(maxsplit=1)[0]
        text = " ".join(line.strip() for line in lines[2:] if line.strip())
        entries.append(AssEntry(lines[0].strip(), parse_time(start_str), parse_time(end_str), text))
    return entries


def ass_time(seconds: float) -> str:
    centiseconds = int(round(max(0.0, seconds) * 100))
    hours, remainder = divmod(centiseconds, 360000)
    minutes, remainder = divmod(remainder, 6000)
    secs, centis = divmod(remainder, 100)
    return f"{hours}:{minutes:02}:{secs:02}.{centis:02}"


def escape_ass_text(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "(").replace("}", ")").replace("\n", "\\N")


def build_header(options: argparse.Namespace) -> str:
    style_format = (
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding"
    )
    # Fields after PrimaryColour: SecondaryColour, OutlineColour, BackColour, Bold,
    # Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle,
    # Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding.
    # Black outline, no shadow, BorderStyle 1, Alignment 2 (bottom center).
    style_tail = "&H00000000,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,0,2,20,20,20,1"
    return "\n".join(
        [
            "[Script Info]",
            "ScriptType: v4.00+",
            f"PlayResX: {options.play_res_x}",
            f"PlayResY: {options.play_res_y}",
            "WrapStyle: 2",
            "ScaledBorderAndShadow: yes",
            "",
            "[V4+ Styles]",
            style_format,
            f"Style: ZH,{options.font},{options.zh_font_size},{options.zh_colour},{style_tail}",
            f"Style: JA,{options.font},{options.ja_font_size},{options.ja_colour},{style_tail}",
            "",
            "[Events]",
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
        ]
    )


def build_dialogue(entry: AssEntry, ja_text: str) -> str:
    zh = escape_ass_text(entry.text)
    if ja_text:
        # \N starts a new line; {\rJA} resets the rest of the cue to the JA style.
        body = f"{zh}\\N{{\\rJA}}{escape_ass_text(ja_text)}"
    else:
        body = zh
    return f"Dialogue: 0,{ass_time(entry.start)},{ass_time(entry.end)},ZH,,0,0,0,,{body}"


def build_bilingual_ass(
    zh_entries: list[AssEntry], ja_by_index: dict[str, str], options: argparse.Namespace
) -> str:
    lines = [build_header(options)]
    for entry in zh_entries:
        lines.append(build_dialogue(entry, ja_by_index.get(entry.index, "")))
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a bilingual ASS subtitle (Chinese on top, Japanese below) from aligned SRTs."
    )
    parser.add_argument("--zh-srt", type=Path, required=True, help="Chinese SRT (top line)")
    parser.add_argument("--ja-srt", type=Path, required=True, help="Japanese SRT aligned by index (bottom line)")
    parser.add_argument("--output", type=Path, required=True, help="Output ASS path")
    parser.add_argument("--font", default=DEFAULT_FONT)
    parser.add_argument("--zh-font-size", type=int, default=DEFAULT_ZH_FONT_SIZE)
    parser.add_argument("--ja-font-size", type=int, default=DEFAULT_JA_FONT_SIZE)
    parser.add_argument("--zh-colour", default=DEFAULT_ZH_COLOUR, help="ASS colour &HAABBGGRR")
    parser.add_argument("--ja-colour", default=DEFAULT_JA_COLOUR, help="ASS colour &HAABBGGRR")
    parser.add_argument("--play-res-x", type=int, default=DEFAULT_PLAY_RES_X)
    parser.add_argument("--play-res-y", type=int, default=DEFAULT_PLAY_RES_Y)
    args = parser.parse_args()

    zh_entries = parse_srt(args.zh_srt)
    ja_by_index = {entry.index: entry.text for entry in parse_srt(args.ja_srt)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(build_bilingual_ass(zh_entries, ja_by_index, args), encoding="utf-8")
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
