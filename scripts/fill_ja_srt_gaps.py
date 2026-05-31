from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path

from faster_whisper.audio import decode_audio

from quality_report import (
    Entry,
    Interval,
    compact_text,
    merge_intervals,
    overlap_seconds,
    parse_srt,
    speech_intervals_from_audio,
)
from transcribe_ja_srt import (
    DEFAULT_MODEL,
    SubtitleEntry,
    collect_entries,
    load_model,
    srt_time,
    transcribe_audio,
    write_entries,
)


@dataclass
class FillStats:
    candidate_gaps: int = 0
    candidate_clips: int = 0
    raw_entries: int = 0
    kept_entries: int = 0
    filtered_entries: int = 0


def existing_intervals(entries: list[Entry], padding: float) -> list[Interval]:
    return merge_intervals(
        [Interval(max(0.0, entry.start - padding), entry.end + padding) for entry in entries]
    )


def srt_gaps(entries: list[Entry]) -> list[Interval]:
    gaps: list[Interval] = []
    for previous, current in zip(entries, entries[1:]):
        if current.start > previous.end:
            gaps.append(Interval(previous.end, current.start))
    return gaps


def speech_clusters_for_gap(
    gap: Interval,
    speech_intervals: list[Interval],
    max_cluster_gap: float,
    pad: float,
) -> list[Interval]:
    overlapped = []
    for item in speech_intervals:
        if item.end <= gap.start:
            continue
        if item.start >= gap.end:
            break
        start = max(gap.start, item.start)
        end = min(gap.end, item.end)
        if end > start:
            overlapped.append(Interval(start, end))
    if not overlapped:
        return []

    clusters = [overlapped[0]]
    for item in overlapped[1:]:
        last = clusters[-1]
        if item.start - last.end <= max_cluster_gap:
            last.end = max(last.end, item.end)
        else:
            clusters.append(item)

    return [
        Interval(max(gap.start, item.start - pad), min(gap.end, item.end + pad))
        for item in clusters
    ]


def split_clip(clip: Interval, max_clip_seconds: float) -> list[Interval]:
    if clip.end - clip.start <= max_clip_seconds:
        return [clip]
    clips: list[Interval] = []
    start = clip.start
    while start < clip.end:
        end = min(clip.end, start + max_clip_seconds)
        clips.append(Interval(start, end))
        start = end
    return clips


def repeated_character_ratio(text: str) -> float:
    compact = compact_text(text)
    if not compact:
        return 1.0
    return max(compact.count(char) for char in set(compact)) / len(compact)


def looks_like_noise(text: str, min_text_chars: int) -> bool:
    compact = compact_text(text)
    if not compact:
        return True
    if len(compact) < min_text_chars:
        return True
    for size in (1, 2, 3):
        if len(compact) >= size * 3 and len(compact) % size == 0:
            token = compact[:size]
            if token * (len(compact) // size) == compact:
                return True
    if len(compact) >= 5 and repeated_character_ratio(compact) >= 0.8:
        return True
    if re.fullmatch(r"[あぁアァうぅウゥんンはハぁー〜…・。、,.!?！？]+", compact) and len(compact) >= 4:
        return True
    return False


def is_duplicate_of_nearby(entry: SubtitleEntry, existing: list[Entry], window_seconds: float) -> bool:
    text = compact_text(entry.text)
    if not text:
        return True
    for item in existing:
        if item.end < entry.start - window_seconds:
            continue
        if item.start > entry.end + window_seconds:
            break
        if compact_text(item.text) == text:
            return True
    return False


def transcribe_clip(
    model,
    audio,
    clip: Interval,
    args: argparse.Namespace,
) -> list[SubtitleEntry]:
    sample_rate = 16000
    start_sample = max(0, int(clip.start * sample_rate))
    end_sample = min(len(audio), int(clip.end * sample_rate))
    if end_sample <= start_sample:
        return []

    segments, _ = model.transcribe(
        audio[start_sample:end_sample],
        language=args.language,
        beam_size=args.beam_size,
        vad_filter=False,
        word_timestamps=True,
        condition_on_previous_text=False,
        temperature=args.temperature,
        no_speech_threshold=args.no_speech_threshold,
        log_prob_threshold=args.log_prob_threshold,
        compression_ratio_threshold=args.compression_ratio_threshold,
    )
    entries = collect_entries(
        segments,
        args.min_duration,
        args.max_duration,
        args.max_chars,
        args.max_word_gap,
        args.max_merge_gap,
    )
    for entry in entries:
        entry.start += clip.start
        entry.end += clip.start
    return entries


def write_srt(entries: list[SubtitleEntry], path: Path) -> None:
    with path.open("w", encoding="utf-8") as file:
        for index, entry in enumerate(entries, start=1):
            file.write(f"{index}\n")
            file.write(f"{srt_time(entry.start)} --> {srt_time(entry.end)}\n")
            file.write(f"{entry.text}\n\n")


def convert_existing(entries: list[Entry]) -> list[SubtitleEntry]:
    return [SubtitleEntry(item.start, item.end, item.text) for item in entries]


def fill_gaps(args: argparse.Namespace, model=None, existing_entries=None) -> FillStats:
    if existing_entries is None:
        existing_entries = parse_srt(args.input)
    if not existing_entries:
        raise SystemExit(f"No SRT entries found: {args.input}")

    speech_intervals = speech_intervals_from_audio(
        args.audio,
        args.vad_threshold,
        args.vad_min_silence_ms,
        args.vad_speech_pad_ms,
    )
    covered = existing_intervals(existing_entries, args.existing_pad_seconds)
    gaps = srt_gaps(existing_entries)

    candidate_clips: list[Interval] = []
    stats = FillStats()
    for gap in gaps:
        if gap.end - gap.start < args.min_gap_seconds:
            continue
        speech_seconds = overlap_seconds(gap, speech_intervals)
        if speech_seconds < args.min_speech_seconds:
            continue
        stats.candidate_gaps += 1
        for cluster in speech_clusters_for_gap(gap, speech_intervals, args.max_cluster_gap, args.clip_pad_seconds):
            if overlap_seconds(cluster, covered) > args.max_existing_overlap_seconds:
                continue
            if cluster.end - cluster.start < args.min_clip_seconds:
                continue
            candidate_clips.extend(split_clip(cluster, args.max_clip_seconds))

    stats.candidate_clips = len(candidate_clips)
    if model is None:
        model = load_model(str(args.model))
    audio = decode_audio(str(args.audio), sampling_rate=16000)

    filled_entries: list[SubtitleEntry] = []
    for index, clip in enumerate(candidate_clips, start=1):
        print(f"[{index}/{len(candidate_clips)}] fill {clip.start:.2f}-{clip.end:.2f}", flush=True)
        raw_entries = transcribe_clip(model, audio, clip, args)
        stats.raw_entries += len(raw_entries)
        for entry in raw_entries:
            if looks_like_noise(entry.text, args.min_fill_chars):
                stats.filtered_entries += 1
                continue
            if is_duplicate_of_nearby(entry, existing_entries, args.duplicate_window_seconds):
                stats.filtered_entries += 1
                continue
            if is_duplicate_of_nearby(entry, filled_entries, args.duplicate_window_seconds):
                stats.filtered_entries += 1
                continue
            if overlap_seconds(Interval(entry.start, entry.end), covered) > args.max_existing_overlap_seconds:
                stats.filtered_entries += 1
                continue
            filled_entries.append(entry)

    stats.kept_entries = len(filled_entries)
    merged = convert_existing(existing_entries) + filled_entries
    merged.sort(key=lambda item: (item.start, item.end, item.text))
    write_srt(merged, args.output)

    if args.fills_output:
        write_srt(sorted(filled_entries, key=lambda item: (item.start, item.end)), args.fills_output)

    print(f"Wrote {args.output}")
    if args.fills_output:
        print(f"Wrote fills {args.fills_output}")
    print(
        "Fill stats: "
        f"candidate_gaps={stats.candidate_gaps} "
        f"candidate_clips={stats.candidate_clips} "
        f"raw_entries={stats.raw_entries} "
        f"kept_entries={stats.kept_entries} "
        f"filtered_entries={stats.filtered_entries}",
        flush=True,
    )
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Fill likely missed Japanese SRT gaps using audio-aware VAD clips.")
    parser.add_argument("input", type=Path, nargs="?", help="Input Japanese SRT (omit when using --transcribe-output)")
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--fills-output", type=Path)
    parser.add_argument(
        "--transcribe-output",
        type=Path,
        help="Transcribe the audio first (sharing one loaded model), write the raw Japanese SRT here, then fill gaps.",
    )
    parser.add_argument("--condition-on-previous-text", action="store_true")
    parser.add_argument("--no-vad", action="store_true")
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--language", default="ja")
    parser.add_argument("--beam-size", type=int, default=5)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--no-speech-threshold", type=float, default=0.6)
    parser.add_argument("--log-prob-threshold", type=float, default=-1.0)
    parser.add_argument("--compression-ratio-threshold", type=float, default=2.4)
    parser.add_argument("--min-duration", type=float, default=1.0)
    parser.add_argument("--max-duration", type=float, default=10.0)
    parser.add_argument("--max-chars", type=int, default=42)
    parser.add_argument("--max-word-gap", type=float, default=6.0)
    parser.add_argument("--max-merge-gap", type=float, default=1.0)
    parser.add_argument("--vad-threshold", type=float, default=0.35)
    parser.add_argument("--vad-min-silence-ms", type=int, default=500)
    parser.add_argument("--vad-speech-pad-ms", type=int, default=400)
    parser.add_argument("--min-gap-seconds", type=float, default=10.0)
    parser.add_argument("--min-speech-seconds", type=float, default=4.0)
    parser.add_argument("--min-clip-seconds", type=float, default=1.2)
    parser.add_argument("--min-fill-chars", type=int, default=3)
    parser.add_argument("--max-clip-seconds", type=float, default=45.0)
    parser.add_argument("--max-cluster-gap", type=float, default=2.0)
    parser.add_argument("--clip-pad-seconds", type=float, default=0.8)
    parser.add_argument("--existing-pad-seconds", type=float, default=0.5)
    parser.add_argument("--max-existing-overlap-seconds", type=float, default=0.2)
    parser.add_argument("--duplicate-window-seconds", type=float, default=8.0)
    args = parser.parse_args()

    if args.transcribe_output:
        model = load_model(str(args.model))
        entries = transcribe_audio(model, args.audio, args)
        write_entries(entries, args.transcribe_output)
        print(f"Wrote {args.transcribe_output}")
        fill_gaps(args, model=model, existing_entries=entries)
    else:
        if args.input is None:
            raise SystemExit("input SRT is required unless --transcribe-output is set")
        fill_gaps(args)


if __name__ == "__main__":
    main()
