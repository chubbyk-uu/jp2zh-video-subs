from __future__ import annotations

import argparse
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

import make_bilingual_ass
from make_bilingual_ass import (
    DEFAULT_FONT,
    DEFAULT_JA_COLOUR,
    DEFAULT_JA_FONT_SIZE,
    DEFAULT_PLAY_RES_X,
    DEFAULT_PLAY_RES_Y,
    DEFAULT_ZH_COLOUR,
    DEFAULT_ZH_FONT_SIZE,
)
from srt_utils import padded_end, parse_time, srt_time
from target_languages import TargetLanguage, output_language_suffix


VIDEO_EXTENSIONS = {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".m4v", ".webm"}


@dataclass
class SubtitlePaths:
    video: Path
    source_zh_srt: Path
    source_ja_srt: Path
    retimed_zh_srt: Path
    retimed_ass: Path
    video_ass: Path


@dataclass
class SrtBlock:
    index: str
    text: str
    start: float
    end: float
    settings: str = ""


def wsl_path(path: str) -> Path:
    match = re.match(r"^([A-Za-z]):[\\/](.*)$", path)
    if not match:
        return Path(path)
    drive, rest = match.groups()
    return Path("/mnt") / drive.lower() / rest.replace("\\", "/")


def iter_videos(path: Path, recursive: bool) -> list[Path]:
    if path.is_file():
        return [path] if path.suffix.lower() in VIDEO_EXTENSIONS else []
    pattern = "**/*" if recursive else "*"
    return sorted(p for p in path.glob(pattern) if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS)


def find_ja_srt(work_dir: Path, stem: str) -> Path | None:
    candidate = work_dir / stem / f"{stem}.ja.srt"
    return candidate if candidate.exists() else None


def parse_srt(path: Path) -> list[SrtBlock]:
    content = path.read_text(encoding="utf-8").strip()
    if not content:
        return []

    blocks: list[SrtBlock] = []
    for block in re.split(r"\n\s*\n", content):
        lines = block.splitlines()
        if len(lines) < 3 or "-->" not in lines[1]:
            continue
        start_text, end_text = [item.strip() for item in lines[1].split("-->", 1)]
        end_parts = end_text.split(maxsplit=1)
        end_time = end_parts[0]
        settings = f" {end_parts[1]}" if len(end_parts) > 1 else ""
        blocks.append(
            SrtBlock(
                index=lines[0].strip(),
                text="\n".join(lines[2:]).strip(),
                start=parse_time(start_text),
                end=parse_time(end_time),
                settings=settings,
            )
        )
    return blocks


def retime_blocks(
    blocks: list[SrtBlock],
    lead_out: float,
    min_display: float,
    min_gap: float,
) -> list[str]:
    output: list[str] = []
    for index, block in enumerate(blocks):
        next_start = blocks[index + 1].start if index + 1 < len(blocks) else None
        end = padded_end(block.start, block.end, next_start, lead_out, min_display, min_gap)
        output.append(
            f"{block.index}\n"
            f"{srt_time(block.start)} --> {srt_time(end)}{block.settings}\n"
            f"{block.text}\n"
        )
    return output


def subtitle_paths(
    video: Path,
    output_dir: Path,
    work_dir: Path,
    target_language: str | TargetLanguage = TargetLanguage.SIMPLIFIED_CHINESE,
) -> SubtitlePaths | None:
    stem = video.stem
    suffix = output_language_suffix(target_language)
    source_zh_srt = output_dir / f"{stem}{suffix}.srt"
    # Read legacy Simplified-Chinese outputs created before standard language tags.
    if not source_zh_srt.exists() and target_language == TargetLanguage.SIMPLIFIED_CHINESE:
        source_zh_srt = output_dir / f"{stem}.zh.srt"
    source_ja_srt = find_ja_srt(work_dir, stem)
    if not source_zh_srt.exists() or source_ja_srt is None:
        return None
    return SubtitlePaths(
        video=video,
        source_zh_srt=source_zh_srt,
        source_ja_srt=source_ja_srt,
        retimed_zh_srt=output_dir / f"{stem}.retimed{suffix}.srt",
        retimed_ass=output_dir / f"{stem}.retimed{suffix}.ass",
        video_ass=video.parent / f"{stem}{suffix}.ass",
    )


def retime_srt_file(paths: SubtitlePaths, lead_out: float, min_display: float, min_gap: float) -> None:
    blocks = parse_srt(paths.source_zh_srt)
    paths.retimed_zh_srt.parent.mkdir(parents=True, exist_ok=True)
    content = "\n".join(retime_blocks(blocks, lead_out, min_display, min_gap))
    paths.retimed_zh_srt.write_text(content + ("\n" if blocks else ""), encoding="utf-8")


def build_ass(paths: SubtitlePaths, options: argparse.Namespace) -> None:
    zh_entries = make_bilingual_ass.parse_srt(paths.retimed_zh_srt)
    ja_by_index = {entry.index: entry.text for entry in make_bilingual_ass.parse_srt(paths.source_ja_srt)}
    paths.retimed_ass.parent.mkdir(parents=True, exist_ok=True)
    paths.retimed_ass.write_text(
        make_bilingual_ass.build_bilingual_ass(zh_entries, ja_by_index, options),
        encoding="utf-8",
    )


def process_video(
    paths: SubtitlePaths,
    options: argparse.Namespace,
    dry_run: bool,
    copy_to_video_dir: bool,
) -> None:
    if dry_run:
        print(f"[DRY] {paths.video.name}")
        print(f"  zh: {paths.source_zh_srt}")
        print(f"  ja: {paths.source_ja_srt}")
        print(f"  write: {paths.retimed_zh_srt}")
        print(f"  write: {paths.retimed_ass}")
        if copy_to_video_dir:
            print(f"  copy: {paths.retimed_ass} -> {paths.video_ass}")
        return

    retime_srt_file(
        paths,
        options.lead_out_seconds,
        options.min_display_seconds,
        options.min_gap_seconds,
    )
    build_ass(paths, options)
    if copy_to_video_dir:
        shutil.copy2(paths.retimed_ass, paths.video_ass)
    print(f"[OK] {paths.video.name}")
    print(f"  wrote {paths.retimed_zh_srt}")
    print(f"  wrote {paths.retimed_ass}")
    if copy_to_video_dir:
        print(f"  copied {paths.video_ass}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Retiming-only refresh for existing translated SRT + bilingual ASS outputs."
    )
    parser.add_argument("input", help="Video file or video directory. Windows drive paths are accepted in WSL.")
    parser.add_argument("--output-dir", type=Path, default=Path("outputs"))
    parser.add_argument("--work-dir", type=Path, default=Path("work"))
    parser.add_argument(
        "--target-language",
        choices=tuple(item.value for item in TargetLanguage),
        default=TargetLanguage.SIMPLIFIED_CHINESE.value,
    )
    parser.add_argument("--recursive", action="store_true")
    parser.add_argument("--no-copy-to-video-dir", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--lead-out-seconds", type=float, default=0.5)
    parser.add_argument("--min-display-seconds", type=float, default=1.5)
    parser.add_argument("--min-gap-seconds", type=float, default=0.04)
    parser.add_argument("--font", default=DEFAULT_FONT)
    parser.add_argument("--ja-font", default=DEFAULT_FONT)
    parser.add_argument("--zh-font-size", type=int, default=DEFAULT_ZH_FONT_SIZE)
    parser.add_argument("--ja-font-size", type=int, default=DEFAULT_JA_FONT_SIZE)
    parser.add_argument("--zh-colour", default=DEFAULT_ZH_COLOUR, help="ASS colour &HAABBGGRR")
    parser.add_argument("--ja-colour", default=DEFAULT_JA_COLOUR, help="ASS colour &HAABBGGRR")
    parser.add_argument("--play-res-x", type=int, default=DEFAULT_PLAY_RES_X)
    parser.add_argument("--play-res-y", type=int, default=DEFAULT_PLAY_RES_Y)
    args = parser.parse_args()

    if args.lead_out_seconds < 0:
        raise SystemExit("--lead-out-seconds must be >= 0")
    if args.min_display_seconds < 0:
        raise SystemExit("--min-display-seconds must be >= 0")
    if args.min_gap_seconds < 0:
        raise SystemExit("--min-gap-seconds must be >= 0")

    input_path = wsl_path(args.input)
    videos = iter_videos(input_path, args.recursive)
    if not videos:
        raise SystemExit(f"No video files found: {input_path}")

    processed = 0
    skipped = 0
    for video in videos:
        paths = subtitle_paths(video, args.output_dir, args.work_dir, args.target_language)
        if paths is None:
            skipped += 1
            suffix = output_language_suffix(args.target_language)
            print(f"[SKIP] {video.name}: missing outputs/{video.stem}{suffix}.srt or work/{video.stem}/*.ja.srt")
            continue
        process_video(paths, args, args.dry_run, not args.no_copy_to_video_dir)
        processed += 1

    print(f"Done. processed={processed}, skipped={skipped}")


if __name__ == "__main__":
    main()
