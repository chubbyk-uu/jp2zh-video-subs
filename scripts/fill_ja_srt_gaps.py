from __future__ import annotations

import argparse
import csv
import re
from dataclasses import dataclass
from pathlib import Path

from faster_whisper.audio import decode_audio

from hallucination_filters import (
    exceeds_compression_ratio,
    is_duplicate_of_nearby,
    is_high_risk_repeat_phrase,
    looks_like_hallucination,
    looks_like_noise,
    normalize_phrase,
    repeated_character_ratio,
    repeated_hallucination_texts,
)
from quality_report import (
    Entry,
    parse_srt,
    speech_intervals_from_audio,
)
from srt_utils import (
    Interval,
    compact_text,
    merge_intervals,
    overlap_seconds,
    srt_gaps,
    srt_time,
)
from transcribe_ja_srt import (
    DEFAULT_MODEL,
    SubtitleEntry,
    collect_entries,
    load_model,
    resolve_overlaps,
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


@dataclass
class FillMetadata:
    entry: SubtitleEntry
    clip: Interval
    status: str
    reason: str


@dataclass
class CandidateClip:
    interval: Interval
    source: str


def existing_intervals(entries: list[Entry], padding: float) -> list[Interval]:
    return merge_intervals(
        [Interval(max(0.0, entry.start - padding), entry.end + padding) for entry in entries]
    )


def srt_gaps_with_boundaries(entries: list[Entry], audio_duration: float) -> list[Interval]:
    gaps = srt_gaps(entries)
    ordered = sorted(entries, key=lambda item: (item.start, item.end))
    if ordered and ordered[0].start > 0.0:
        gaps.insert(0, Interval(0.0, ordered[0].start))
    if ordered and ordered[-1].end < audio_duration:
        gaps.append(Interval(ordered[-1].end, audio_duration))
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


def split_clip_with_overlap(
    clip: Interval,
    max_clip_seconds: float,
    overlap_seconds: float,
) -> list[Interval]:
    if max_clip_seconds <= 0:
        raise ValueError("max_clip_seconds must be positive")
    if overlap_seconds < 0:
        raise ValueError("overlap_seconds must be non-negative")
    if overlap_seconds >= max_clip_seconds:
        raise ValueError("overlap_seconds must be smaller than max_clip_seconds")
    if clip.end - clip.start <= max_clip_seconds:
        return [clip]

    clips: list[Interval] = []
    start = clip.start
    step = max_clip_seconds - overlap_seconds
    while start < clip.end:
        end = min(clip.end, start + max_clip_seconds)
        clips.append(Interval(start, end))
        if end >= clip.end:
            break
        start += step
    return clips




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


def confidence_text(value: float | None) -> str:
    return "" if value is None else f"{value:.4f}"


def write_fills_metadata(items: list[FillMetadata], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.writer(file, delimiter="\t")
        writer.writerow([
            "status",
            "reason",
            "start",
            "end",
            "duration",
            "clip_start",
            "clip_end",
            "avg_logprob",
            "no_speech_prob",
            "compression_ratio",
            "text",
        ])
        for item in sorted(items, key=lambda value: (value.entry.start, value.entry.end, value.status)):
            entry = item.entry
            writer.writerow([
                item.status,
                item.reason,
                f"{entry.start:.3f}",
                f"{entry.end:.3f}",
                f"{max(0.0, entry.end - entry.start):.3f}",
                f"{item.clip.start:.3f}",
                f"{item.clip.end:.3f}",
                confidence_text(entry.avg_logprob),
                confidence_text(entry.no_speech_prob),
                confidence_text(entry.compression_ratio),
                entry.text,
            ])


def write_srt(entries: list[SubtitleEntry], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        for index, entry in enumerate(entries, start=1):
            file.write(f"{index}\n")
            file.write(f"{srt_time(entry.start)} --> {srt_time(entry.end)}\n")
            file.write(f"{entry.text}\n\n")


def convert_existing(entries: list[Entry]) -> list[SubtitleEntry]:
    return [SubtitleEntry(item.start, item.end, item.text) for item in entries]


def speech_intervals_from_gap_audio(
    audio,
    gap: Interval,
    threshold: float,
    min_silence_ms: int,
    speech_pad_ms: int,
    sampling_rate: int = 16000,
) -> list[Interval]:
    from faster_whisper.vad import VadOptions, get_speech_timestamps

    start_sample = max(0, int(gap.start * sampling_rate))
    end_sample = min(len(audio), int(gap.end * sampling_rate))
    if end_sample <= start_sample:
        return []
    options = VadOptions(
        threshold=threshold,
        min_silence_duration_ms=min_silence_ms,
        speech_pad_ms=speech_pad_ms,
    )
    timestamps = get_speech_timestamps(audio[start_sample:end_sample], options, sampling_rate=sampling_rate)
    return [
        Interval(gap.start + item["start"] / sampling_rate, gap.start + item["end"] / sampling_rate)
        for item in timestamps
    ]


def gap_windows(gap: Interval, window_seconds: float, overlap_seconds: float) -> list[Interval]:
    if window_seconds <= 0:
        raise ValueError("window_seconds must be positive")
    if overlap_seconds < 0:
        raise ValueError("overlap_seconds must be non-negative")
    if overlap_seconds >= window_seconds:
        raise ValueError("overlap_seconds must be smaller than window_seconds")
    if gap.end - gap.start <= window_seconds:
        return [gap]

    windows: list[Interval] = []
    step = window_seconds - overlap_seconds
    start = gap.start
    while start < gap.end:
        end = min(gap.end, start + window_seconds)
        windows.append(Interval(start, end))
        if end >= gap.end:
            break
        start += step
    return windows


def speech_intervals_from_sliding_gap_audio(
    audio,
    gap: Interval,
    threshold: float,
    min_silence_ms: int,
    speech_pad_ms: int,
    window_seconds: float,
    overlap_seconds: float,
) -> list[Interval]:
    speech_intervals: list[Interval] = []
    for window in gap_windows(gap, window_seconds, overlap_seconds):
        speech_intervals.extend(
            speech_intervals_from_gap_audio(
                audio,
                window,
                threshold,
                min_silence_ms,
                speech_pad_ms,
            )
        )
    return merge_intervals(speech_intervals)


def padded_clip_for_gap(
    cluster: Interval,
    gap: Interval,
    pad_seconds: float,
) -> Interval:
    return Interval(
        max(gap.start, cluster.start - pad_seconds),
        min(gap.end, cluster.end + pad_seconds),
    )


def fill_gaps(args: argparse.Namespace, model=None, existing_entries=None) -> FillStats:
    if existing_entries is None:
        existing_entries = parse_srt(args.input)
    if not existing_entries:
        # No transcribed speech (e.g. a silent or music-only sample clip). Gaps are
        # defined between existing entries, so there is nothing to fill; write an empty
        # output and return rather than crashing the pipeline.
        stats = FillStats()
        write_srt([], args.output)
        if args.fills_output:
            write_srt([], args.fills_output)
        if args.fills_metadata_output:
            write_fills_metadata([], args.fills_metadata_output)
        print(f"Wrote {args.output} (no source entries; nothing to fill)")
        return stats

    audio = decode_audio(str(args.audio), sampling_rate=16000)
    audio_duration = len(audio) / 16000
    speech_intervals = []
    if not args.gap_local_vad:
        speech_intervals = speech_intervals_from_audio(
            args.audio,
            args.vad_threshold,
            args.vad_min_silence_ms,
            args.vad_speech_pad_ms,
            audio=audio,
        )
    covered = existing_intervals(existing_entries, args.existing_pad_seconds)
    gaps = srt_gaps_with_boundaries(existing_entries, audio_duration)

    candidate_clips: list[CandidateClip] = []
    stats = FillStats()
    for gap in gaps:
        if gap.end - gap.start < args.min_gap_seconds:
            continue
        if args.gap_local_vad:
            gap_seconds = gap.end - gap.start
            if gap_seconds >= args.gap_local_vad_window_min_gap_seconds:
                gap_speech_intervals = speech_intervals_from_sliding_gap_audio(
                    audio,
                    gap,
                    args.gap_local_vad_threshold,
                    args.vad_min_silence_ms,
                    args.vad_speech_pad_ms,
                    args.gap_local_vad_window_seconds,
                    args.gap_local_vad_window_overlap_seconds,
                )
                clip_source = "gap_local_vad_window"
            else:
                gap_speech_intervals = speech_intervals_from_gap_audio(
                    audio,
                    gap,
                    args.gap_local_vad_threshold,
                    args.vad_min_silence_ms,
                    args.vad_speech_pad_ms,
                )
                clip_source = "gap_local_vad"
            speech_seconds = overlap_seconds(gap, gap_speech_intervals)
            clip_pad_seconds = args.gap_local_asr_pad_seconds
            max_clip_seconds = args.gap_local_asr_max_clip_seconds
            clip_overlap_seconds = args.gap_local_asr_overlap_seconds
        else:
            gap_speech_intervals = speech_intervals
            speech_seconds = overlap_seconds(gap, gap_speech_intervals)
            clip_pad_seconds = args.clip_pad_seconds
            max_clip_seconds = args.max_clip_seconds
            clip_overlap_seconds = 0.0
            clip_source = "full_vad"
        if speech_seconds < args.min_speech_seconds:
            continue
        stats.candidate_gaps += 1
        for cluster in speech_clusters_for_gap(gap, gap_speech_intervals, args.max_cluster_gap, 0.0):
            cluster = padded_clip_for_gap(cluster, gap, clip_pad_seconds)
            if overlap_seconds(cluster, covered) > args.max_existing_overlap_seconds:
                continue
            if cluster.end - cluster.start < args.min_clip_seconds:
                continue
            for clip in split_clip_with_overlap(cluster, max_clip_seconds, clip_overlap_seconds):
                candidate_clips.append(CandidateClip(clip, clip_source))

    stats.candidate_clips = len(candidate_clips)
    if model is None:
        model = load_model(str(args.model))

    filled_entries: list[SubtitleEntry] = []
    metadata: list[FillMetadata] = []
    for index, candidate in enumerate(candidate_clips, start=1):
        clip = candidate.interval
        print(
            f"[{index}/{len(candidate_clips)}] fill {clip.start:.2f}-{clip.end:.2f} "
            f"{candidate.source}",
            flush=True,
        )
        raw_entries = transcribe_clip(model, audio, clip, args)
        stats.raw_entries += len(raw_entries)
        for entry in raw_entries:
            if exceeds_compression_ratio(entry, args.max_fill_compression_ratio):
                stats.filtered_entries += 1
                metadata.append(FillMetadata(entry, clip, "filtered", "compression_ratio"))
                continue
            if looks_like_noise(entry.text, args.min_fill_chars):
                stats.filtered_entries += 1
                metadata.append(FillMetadata(entry, clip, "filtered", "noise"))
                continue
            if looks_like_hallucination(entry.text):
                stats.filtered_entries += 1
                metadata.append(FillMetadata(entry, clip, "filtered", "hallucination"))
                continue
            if is_duplicate_of_nearby(entry, existing_entries, args.duplicate_window_seconds):
                stats.filtered_entries += 1
                metadata.append(FillMetadata(entry, clip, "filtered", "duplicate_existing"))
                continue
            if is_duplicate_of_nearby(entry, filled_entries, args.duplicate_window_seconds):
                stats.filtered_entries += 1
                metadata.append(FillMetadata(entry, clip, "filtered", "duplicate_fill"))
                continue
            if overlap_seconds(Interval(entry.start, entry.end), covered) > args.max_existing_overlap_seconds:
                stats.filtered_entries += 1
                metadata.append(FillMetadata(entry, clip, "filtered", "overlap_existing"))
                continue
            filled_entries.append(entry)
            metadata.append(FillMetadata(entry, clip, "kept", ""))

    # Frequency backstop: repeated ordinary dialogue is only auto-dropped when the
    # repeated group is also low-confidence or likely near-silence hallucination.
    repeated = repeated_hallucination_texts(
        filled_entries,
        args.hallucination_min_repeats,
        args.hallucination_repeat_no_speech_prob,
        args.hallucination_repeat_avg_logprob,
        args.hallucination_high_risk_max_repeats,
    )
    if repeated:
        kept_after: list[SubtitleEntry] = []
        for entry in filled_entries:
            if normalize_phrase(entry.text) in repeated:
                stats.filtered_entries += 1
                for item in metadata:
                    if item.entry is entry and item.status == "kept":
                        item.status, item.reason = "filtered", "hallucination_repeat"
                        break
            else:
                kept_after.append(entry)
        filled_entries = kept_after

    stats.kept_entries = len(filled_entries)
    merged = resolve_overlaps(convert_existing(existing_entries) + filled_entries)
    write_srt(merged, args.output)

    if args.fills_output:
        write_srt(sorted(filled_entries, key=lambda item: (item.start, item.end)), args.fills_output)

    if args.fills_metadata_output:
        write_fills_metadata(metadata, args.fills_metadata_output)

    print(f"Wrote {args.output}")
    if args.fills_output:
        print(f"Wrote fills {args.fills_output}")
    if args.fills_metadata_output:
        print(f"Wrote fills metadata {args.fills_metadata_output}")
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
    parser.add_argument("--fills-metadata-output", type=Path)
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
    parser.add_argument("--vad-threshold", type=float, default=0.05)
    parser.add_argument("--vad-min-silence-ms", type=int, default=500)
    parser.add_argument("--vad-speech-pad-ms", type=int, default=400)
    parser.add_argument("--main-local-vad", action="store_true")
    parser.add_argument("--main-local-vad-threshold", type=float, default=0.5)
    parser.add_argument("--main-local-vad-window-seconds", type=float, default=8.0)
    parser.add_argument("--main-local-vad-window-overlap-seconds", type=float, default=4.0)
    parser.add_argument("--main-local-vad-max-cluster-gap", type=float, default=2.0)
    parser.add_argument("--main-local-asr-pad-seconds", type=float, default=0.3)
    parser.add_argument("--main-local-asr-max-clip-seconds", type=float, default=30.0)
    parser.add_argument("--main-local-asr-overlap-seconds", type=float, default=5.0)
    parser.add_argument("--main-local-min-clip-seconds", type=float, default=0.6)
    parser.add_argument("--main-local-batch-size", type=int, default=24)
    parser.add_argument(
        "--gap-local-vad",
        action="store_true",
        help="Use per-gap local VAD for gap-fill candidates instead of full-audio VAD.",
    )
    parser.add_argument("--gap-local-vad-threshold", type=float, default=0.60)
    parser.add_argument("--gap-local-vad-window-min-gap-seconds", type=float, default=10.0)
    parser.add_argument("--gap-local-vad-window-seconds", type=float, default=5.0)
    parser.add_argument("--gap-local-vad-window-overlap-seconds", type=float, default=3.0)
    parser.add_argument("--gap-local-asr-pad-seconds", type=float, default=3.0)
    parser.add_argument("--gap-local-asr-max-clip-seconds", type=float, default=45.0)
    parser.add_argument("--gap-local-asr-overlap-seconds", type=float, default=5.0)
    # Gap-fill gates default to an aggressive setting validated on local sample runs,
    # so the stage actually recovers the short, low-energy reactions VAD@0.05 still
    # misses; the hallucination filters below keep the extra reach clean.
    parser.add_argument("--min-gap-seconds", type=float, default=2.0)
    parser.add_argument("--min-speech-seconds", type=float, default=1.0)
    parser.add_argument("--min-clip-seconds", type=float, default=0.6)
    parser.add_argument("--min-fill-chars", type=int, default=3)
    parser.add_argument("--max-fill-compression-ratio", type=float, default=25.0)
    parser.add_argument("--max-clip-seconds", type=float, default=45.0)
    parser.add_argument("--max-cluster-gap", type=float, default=2.0)
    parser.add_argument("--clip-pad-seconds", type=float, default=0.4)
    parser.add_argument("--existing-pad-seconds", type=float, default=0.1)
    parser.add_argument("--max-existing-overlap-seconds", type=float, default=1.0)
    parser.add_argument("--duplicate-window-seconds", type=float, default=8.0)
    parser.add_argument(
        "--hallucination-min-repeats",
        type=int,
        default=10,
        help="Consider a fill phrase repeated at least this many times across all gap "
        "fills for one video as a repeat-hallucination candidate.",
    )
    parser.add_argument(
        "--hallucination-repeat-no-speech-prob",
        type=float,
        default=0.75,
        help="Drop a repeated fill phrase only when its median no_speech_prob is at "
        "least this value.",
    )
    parser.add_argument(
        "--hallucination-repeat-avg-logprob",
        type=float,
        default=-0.80,
        help="Drop a repeated fill phrase only when its median avg_logprob is at most "
        "this value.",
    )
    parser.add_argument(
        "--hallucination-high-risk-max-repeats",
        type=int,
        default=3,
        help="Always drop high-risk fixed greeting/thanks phrases repeated at least "
        "this many times across all gap fills for one video (a fixed greeting recurring "
        "in several near-silent gaps is almost always hallucination; a real one-off "
        "greeting appears once and survives). Set 0 to disable.",
    )
    args = parser.parse_args()
    if args.gap_local_vad_window_min_gap_seconds < 0:
        raise SystemExit("--gap-local-vad-window-min-gap-seconds must be >= 0")
    if args.gap_local_vad_window_seconds <= 0:
        raise SystemExit("--gap-local-vad-window-seconds must be > 0")
    if args.gap_local_vad_window_overlap_seconds < 0:
        raise SystemExit("--gap-local-vad-window-overlap-seconds must be >= 0")
    if args.gap_local_vad_window_overlap_seconds >= args.gap_local_vad_window_seconds:
        raise SystemExit("--gap-local-vad-window-overlap-seconds must be smaller than --gap-local-vad-window-seconds")
    if args.gap_local_asr_overlap_seconds >= args.gap_local_asr_max_clip_seconds:
        raise SystemExit("--gap-local-asr-overlap-seconds must be smaller than --gap-local-asr-max-clip-seconds")
    if args.main_local_vad_window_overlap_seconds >= args.main_local_vad_window_seconds:
        raise SystemExit("--main-local-vad-window-overlap-seconds must be smaller than --main-local-vad-window-seconds")
    if args.main_local_asr_overlap_seconds >= args.main_local_asr_max_clip_seconds:
        raise SystemExit("--main-local-asr-overlap-seconds must be smaller than --main-local-asr-max-clip-seconds")

    if args.transcribe_output:
        model = load_model(str(args.model))
        # Resolve overlaps so the intermediate SRT matches standalone transcribe
        # output, and feed the resolved entries into gap filling.
        entries = resolve_overlaps(transcribe_audio(model, args.audio, args))
        write_entries(entries, args.transcribe_output)
        print(f"Wrote {args.transcribe_output}")
        fill_gaps(args, model=model, existing_entries=entries)
    else:
        if args.input is None:
            raise SystemExit("input SRT is required unless --transcribe-output is set")
        fill_gaps(args)


if __name__ == "__main__":
    main()
