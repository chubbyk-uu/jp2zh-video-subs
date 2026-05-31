from __future__ import annotations

import argparse
import math
import re
from dataclasses import dataclass
from pathlib import Path

from srt_utils import (
    Interval,
    compact_text,
    format_time,
    merge_intervals,
    overlap_seconds,
    parse_time,
    srt_gaps,
)


@dataclass
class Entry:
    index: str
    start: float
    end: float
    text: str


def parse_srt(path: Path | None) -> list[Entry]:
    if path is None or not path.exists():
        return []
    content = path.read_text(encoding="utf-8").strip()
    if not content:
        return []
    entries: list[Entry] = []
    for block in re.split(r"\n\s*\n", content):
        lines = block.splitlines()
        if len(lines) < 3 or "-->" not in lines[1]:
            continue
        start_text, end_text = [item.strip() for item in lines[1].split("-->")]
        entries.append(
            Entry(
                index=lines[0].strip(),
                start=parse_time(start_text),
                end=parse_time(end_text),
                text="\n".join(line.strip() for line in lines[2:]).strip(),
            )
        )
    return entries


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    sorted_values = sorted(values)
    position = (len(sorted_values) - 1) * q
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return sorted_values[int(position)]
    return sorted_values[lower] * (upper - position) + sorted_values[upper] * (position - lower)


def padded_intervals(entries: list[Entry], padding: float) -> list[Interval]:
    return merge_intervals(
        [Interval(max(0.0, entry.start - padding), entry.end + padding) for entry in entries]
    )


def speech_intervals_from_audio(
    audio_path: Path,
    threshold: float,
    min_silence_ms: int,
    speech_pad_ms: int,
    audio=None,
) -> list[Interval]:
    from faster_whisper.audio import decode_audio
    from faster_whisper.vad import VadOptions, get_speech_timestamps

    if audio is None:
        audio = decode_audio(str(audio_path), sampling_rate=16000)
    options = VadOptions(
        threshold=threshold,
        min_silence_duration_ms=min_silence_ms,
        speech_pad_ms=speech_pad_ms,
    )
    timestamps = get_speech_timestamps(audio, options, sampling_rate=16000)
    return [Interval(item["start"] / 16000, item["end"] / 16000) for item in timestamps]


def adjacent_duplicate_candidates(ja_entries: list[Entry], zh_entries: list[Entry]) -> list[str]:
    candidates: list[str] = []
    for (prev_ja, curr_ja), (prev_zh, curr_zh) in zip(
        zip(ja_entries, ja_entries[1:]),
        zip(zh_entries, zh_entries[1:]),
    ):
        if not compact_text(prev_zh.text):
            continue
        if compact_text(prev_zh.text) != compact_text(curr_zh.text):
            continue
        if compact_text(prev_ja.text) == compact_text(curr_ja.text):
            continue
        candidates.append(
            f"{prev_zh.index}->{curr_zh.index}: zh duplicate while ja differs"
        )
    return candidates


def build_report(args: argparse.Namespace) -> str:
    ja_entries = parse_srt(args.ja_srt)
    zh_entries = parse_srt(args.zh_srt)

    lines: list[str] = []
    lines.append("Subtitle quality report")
    lines.append(f"ja_srt: {args.ja_srt}")
    if args.zh_srt:
        lines.append(f"zh_srt: {args.zh_srt}")
    if args.audio:
        lines.append(f"audio: {args.audio}")
    lines.append("")

    if ja_entries:
        durations = [max(0.0, item.end - item.start) for item in ja_entries]
        chars = [len(compact_text(item.text)) for item in ja_entries]
        gaps = srt_gaps(ja_entries)
        display_total = sum(durations)
        span = max(item.end for item in ja_entries) - min(item.start for item in ja_entries)
        lines.append("[Japanese SRT]")
        lines.append(f"entries: {len(ja_entries)}")
        lines.append(f"display_total_min: {display_total / 60:.1f}")
        lines.append(f"display_coverage_in_srt_span: {display_total / span:.1%}" if span > 0 else "display_coverage_in_srt_span: n/a")
        lines.append(f"duration_median_s: {percentile(durations, 0.5):.2f}")
        lines.append(f"duration_p95_s: {percentile(durations, 0.95):.2f}")
        lines.append(f"chars_median: {percentile(chars, 0.5):.1f}")
        lines.append(f"chars_p95: {percentile(chars, 0.95):.1f}")
        for length in (1, 2, 3, 5):
            count = sum(value <= length for value in chars)
            lines.append(f"chars_le_{length}: {count} ({count / len(chars):.1%})")
        lines.append(f"gaps_gt_10s: {sum(item.end - item.start > 10 for item in gaps)}")
        lines.append(f"gaps_gt_30s: {sum(item.end - item.start > 30 for item in gaps)}")
        lines.append(f"gaps_gt_60s_observational_only: {sum(item.end - item.start > 60 for item in gaps)}")
        if gaps:
            lines.append(f"gap_p95_s: {percentile([item.end - item.start for item in gaps], 0.95):.1f}")
            lines.append(f"gap_max_s: {max(item.end - item.start for item in gaps):.1f}")
        lines.append("")

        if args.audio and args.audio.exists():
            speech_intervals = speech_intervals_from_audio(
                args.audio,
                args.vad_threshold,
                args.vad_min_silence_ms,
                args.vad_speech_pad_ms,
            )
            subtitle_intervals = padded_intervals(ja_entries, args.subtitle_pad_seconds)
            speech_total = sum(item.end - item.start for item in speech_intervals)
            speech_covered = sum(overlap_seconds(item, subtitle_intervals) for item in speech_intervals)
            speech_uncovered = max(0.0, speech_total - speech_covered)
            suspicious = []
            for gap in gaps:
                gap_duration = gap.end - gap.start
                if gap_duration < args.min_gap_seconds:
                    continue
                speech_seconds = overlap_seconds(gap, speech_intervals)
                if speech_seconds >= args.min_speech_seconds:
                    suspicious.append((gap, speech_seconds))
            lines.append("[Audio-aware subtitle gaps]")
            lines.append(f"vad_speech_segments: {len(speech_intervals)}")
            lines.append(f"vad_speech_total_s: {speech_total:.1f}")
            lines.append(f"vad_speech_covered_by_subtitles_s: {speech_covered:.1f}")
            lines.append(f"vad_speech_uncovered_s: {speech_uncovered:.1f}")
            lines.append(f"vad_speech_coverage: {speech_covered / speech_total:.1%}" if speech_total > 0 else "vad_speech_coverage: n/a")
            lines.append(f"subtitle_gaps_with_vad_speech: {len(suspicious)}")
            for gap, speech_seconds in sorted(suspicious, key=lambda item: item[1], reverse=True)[: args.max_samples]:
                lines.append(
                    f"- {format_time(gap.start)} -> {format_time(gap.end)} "
                    f"gap={gap.end - gap.start:.1f}s vad_speech={speech_seconds:.1f}s"
                )
            lines.append("")

    if zh_entries:
        lines.append("[Chinese SRT]")
        lines.append(f"entries: {len(zh_entries)}")
        jp_left = [item for item in zh_entries if re.search(r"[ぁ-ゟ゠-ヿ]", item.text)]
        lines.append(f"japanese_kana_left: {len(jp_left)}")
        duplicate_candidates = adjacent_duplicate_candidates(ja_entries, zh_entries)
        lines.append(f"suspicious_adjacent_duplicates: {len(duplicate_candidates)}")
        for item in duplicate_candidates[: args.max_samples]:
            lines.append(f"- {item}")
        for item in jp_left[: args.max_samples]:
            lines.append(f"- kana left at {item.index}: {item.text[:80]}")
        lines.append("")

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ja-srt", type=Path, required=True)
    parser.add_argument("--zh-srt", type=Path)
    parser.add_argument("--audio", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--vad-threshold", type=float, default=0.35)
    parser.add_argument("--vad-min-silence-ms", type=int, default=500)
    parser.add_argument("--vad-speech-pad-ms", type=int, default=400)
    parser.add_argument("--min-gap-seconds", type=float, default=10.0)
    parser.add_argument("--min-speech-seconds", type=float, default=2.0)
    parser.add_argument("--subtitle-pad-seconds", type=float, default=0.5)
    parser.add_argument("--max-samples", type=int, default=20)
    args = parser.parse_args()

    report = build_report(args)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report + "\n", encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
