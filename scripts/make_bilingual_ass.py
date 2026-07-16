from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path

from cli_config import add_dataclass_arguments
from pipeline_configs import BilingualAssConfig
from portable_runtime import project_root
from srt_utils import parse_time


# ASS colours are &HAABBGGRR (alpha, blue, green, red); alpha 00 is fully opaque.
# Microsoft YaHei ships with every Windows install and covers both the Chinese line
# and the Japanese kana/kanji line; Arial has no CJK glyphs, which left the actual
# typeface to the player's fallback. Non-Windows renderers fall back via fontconfig.
BILINGUAL_DEFAULTS = BilingualAssConfig()
DEFAULT_FONT = BILINGUAL_DEFAULTS.font
DEFAULT_ZH_FONT_SIZE = BILINGUAL_DEFAULTS.zh_font_size
DEFAULT_JA_FONT_SIZE = BILINGUAL_DEFAULTS.ja_font_size
DEFAULT_ZH_COLOUR = BILINGUAL_DEFAULTS.zh_colour  # yellow, larger top line
DEFAULT_JA_COLOUR = BILINGUAL_DEFAULTS.ja_colour  # light gray, smaller bottom line
# Speaker colours recolour only the Chinese (top) line; the JA line stays gray via
# {\rJA}. ASS is &HAABBGGRR, so these are blue-ish and pink in RGB terms.
DEFAULT_MALE_COLOUR = BILINGUAL_DEFAULTS.male_colour  # deep sky blue, RGB(0,191,255)
DEFAULT_FEMALE_COLOUR = BILINGUAL_DEFAULTS.female_colour  # pink, RGB(255,120,180)
DEFAULT_PLAY_RES_X = BILINGUAL_DEFAULTS.play_res_x
DEFAULT_PLAY_RES_Y = BILINGUAL_DEFAULTS.play_res_y

# Speaker gender per cue comes from an ECAPA-TDNN classifier (VoxCeleb-trained), which
# is more stable than raw pitch on noisy or music-laden audio. We colour only cues
# classified confidently; the rest keep the default colour rather than risk a wrong guess.
DEFAULT_GENDER_MODEL = project_root(Path(__file__)) / "models" / "voice-gender-classifier"
DEFAULT_GENDER_CONFIDENCE = BILINGUAL_DEFAULTS.gender_confidence
MIN_GENDER_SECONDS = 0.30  # cues shorter than this carry too little signal to trust


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
        # Preserve display wrapping from the final Chinese SRT; escape_ass_text
        # converts these real newlines to ASS \N later.
        text = "\n".join(line.strip() for line in lines[2:] if line.strip())
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
    male_colour = getattr(options, "male_colour", DEFAULT_MALE_COLOUR)
    female_colour = getattr(options, "female_colour", DEFAULT_FEMALE_COLOUR)
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
            # ZH_M / ZH_F clone ZH but recolour the top line per speaker gender.
            f"Style: ZH_M,{options.font},{options.zh_font_size},{male_colour},{style_tail}",
            f"Style: ZH_F,{options.font},{options.zh_font_size},{female_colour},{style_tail}",
            f"Style: JA,{options.font},{options.ja_font_size},{options.ja_colour},{style_tail}",
            "",
            "[Events]",
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
        ]
    )


def style_for_gender(gender: str | None) -> str:
    return {"M": "ZH_M", "F": "ZH_F"}.get(gender or "", "ZH")


def build_dialogue(entry: AssEntry, ja_text: str, style: str = "ZH") -> str:
    zh = escape_ass_text(entry.text)
    if ja_text:
        # \N starts a new line; {\rJA} resets the rest of the cue to the JA style.
        body = f"{zh}\\N{{\\rJA}}{escape_ass_text(ja_text)}"
    else:
        body = zh
    return f"Dialogue: 0,{ass_time(entry.start)},{ass_time(entry.end)},{style},,0,0,0,,{body}"


def build_bilingual_ass(
    zh_entries: list[AssEntry],
    ja_by_index: dict[str, str],
    options: argparse.Namespace,
    genders: dict[str, str | None] | None = None,
) -> str:
    genders = genders or {}
    lines = [build_header(options)]
    for entry in zh_entries:
        style = style_for_gender(genders.get(entry.index))
        lines.append(build_dialogue(entry, ja_by_index.get(entry.index, ""), style))
    return "\n".join(lines) + "\n"


def classify_gender(male_prob: float, female_prob: float, confidence: float) -> str | None:
    """Map a male/female posterior pair to 'M'/'F', or None when below the confidence floor."""
    top = max(male_prob, female_prob)
    if top < confidence:
        return None
    return "M" if male_prob >= female_prob else "F"


def gender_probabilities(
    entries: list[AssEntry], audio_path: Path, model_dir: Path, min_seconds: float = MIN_GENDER_SECONDS
) -> dict[str, tuple[float, float]]:
    """(male_prob, female_prob) per cue from the ECAPA classifier; missing = too-short cue."""
    import numpy as np
    import soundfile as sf
    import torch
    import torch.nn.functional as F

    from ecapa_gender import ECAPA_gender

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = ECAPA_gender.from_local(model_dir).to(device).eval()

    audio, sr = sf.read(str(audio_path))
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    audio = np.asarray(audio, dtype="float32")
    total = audio.shape[0]
    min_samples = int(min_seconds * sr)

    out: dict[str, tuple[float, float]] = {}
    with torch.no_grad():
        for entry in entries:
            lo = max(0, int(entry.start * sr))
            hi = min(total, int(entry.end * sr))
            if hi - lo < min_samples:
                continue
            seg = torch.from_numpy(audio[lo:hi]).unsqueeze(0).to(device)
            prob = F.softmax(model(seg), dim=1)[0]
            out[entry.index] = (float(prob[0]), float(prob[1]))
    return out


def detect_genders(
    entries: list[AssEntry], audio_path: Path, model_dir: Path, confidence: float
) -> dict[str, str | None]:
    probs = gender_probabilities(entries, audio_path, model_dir)
    return {idx: classify_gender(m, f, confidence) for idx, (m, f) in probs.items()}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build a bilingual ASS subtitle (Chinese on top, Japanese below) from aligned SRTs."
    )
    parser.add_argument("--zh-srt", type=Path, required=True, help="Chinese SRT (top line)")
    parser.add_argument("--ja-srt", type=Path, required=True, help="Japanese SRT aligned by index (bottom line)")
    parser.add_argument("--output", type=Path, required=True, help="Output ASS path")
    parser.add_argument(
        "--audio", type=Path, default=None,
        help="16kHz mono WAV; when given, recolour each cue's top line by speaker gender",
    )
    parser.add_argument(
        "--gender-model", type=Path, default=DEFAULT_GENDER_MODEL,
        help="Directory of the ECAPA gender classifier (model.safetensors + config.json)",
    )
    add_dataclass_arguments(parser, BilingualAssConfig)
    return parser


def main() -> None:
    args = build_parser().parse_args()

    zh_entries = parse_srt(args.zh_srt)
    ja_by_index = {entry.index: entry.text for entry in parse_srt(args.ja_srt)}

    genders: dict[str, str | None] | None = None
    if args.audio and args.colour_by_speaker:
        if not args.gender_model.exists():
            # Don't fail the build (or the batch pipeline) just because the optional
            # gender model is absent; emit a plain (uncoloured) ASS instead.
            print(f"Speaker colouring skipped: gender model not found at {args.gender_model}")
        else:
            genders = detect_genders(zh_entries, args.audio, args.gender_model, args.gender_confidence)
            coloured = sum(1 for g in genders.values() if g)
            male = sum(1 for g in genders.values() if g == "M")
            print(
                f"Speaker colouring: coloured={coloured}/{len(zh_entries)} "
                f"male={male} female={coloured - male} (conf>={args.gender_confidence})"
            )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(build_bilingual_ass(zh_entries, ja_by_index, args, genders), encoding="utf-8")
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
