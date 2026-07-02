from __future__ import annotations

import argparse
import csv
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

from faster_whisper.audio import decode_audio

from cli_config import add_dataclass_arguments
from pipeline_configs import FillConfig
from hallucination_filters import (
    exceeds_compression_ratio,
    is_duplicate_of_nearby,
    is_high_risk_repeat_phrase,
    looks_like_hallucination,
    looks_like_noise,
    normalize_phrase,
    repeated_hallucination_texts,
)
from quality_report import (
    Entry,
    parse_srt,
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
    filter_asr_text_entries,
    filter_repeated_hallucination_entries,
    finalize_main_entries,
    load_model,
    resolve_overlaps,
    transcribe_audio,
    transcribe_clips_batched,
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


CONTEXT_DUPLICATE_MAX_GAP_SECONDS = 0.5
CONTEXT_DUPLICATE_SIMILARITY = 0.72
CONTEXT_FRAGMENT_MIN_CHARS = 2
CONTEXT_PUNCTUATION_RE = re.compile(r"[、。．，！？!?…・ー～~「」『』（）()\[\]\"'`\s　]+")


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


def context_key(text: str) -> str:
    return CONTEXT_PUNCTUATION_RE.sub("", compact_text(text))


def nearby_context_gap(left, right) -> float:
    if left.end <= right.start:
        return right.start - left.end
    if right.end <= left.start:
        return left.start - right.end
    return 0.0


def context_duplicate_or_fragment(left_text: str, right_text: str) -> bool:
    left = context_key(left_text)
    right = context_key(right_text)
    if not left or not right:
        return False
    if left == right:
        return True
    shorter, longer = sorted((left, right), key=len)
    if len(shorter) >= CONTEXT_FRAGMENT_MIN_CHARS and shorter in longer:
        return True
    return SequenceMatcher(None, left, right).ratio() >= CONTEXT_DUPLICATE_SIMILARITY


def fill_rank(entry: SubtitleEntry) -> tuple[int, float, float]:
    text_len = len(context_key(entry.text))
    avg_logprob = entry.avg_logprob if entry.avg_logprob is not None else -99.0
    no_speech_prob = entry.no_speech_prob if entry.no_speech_prob is not None else 1.0
    return (text_len, avg_logprob, -no_speech_prob)


def context_duplicate_fill_entries(
    filled_entries: list[SubtitleEntry],
    existing_entries: list[Entry],
    max_gap_seconds: float = CONTEXT_DUPLICATE_MAX_GAP_SECONDS,
) -> set[int]:
    fill_ids = {id(entry) for entry in filled_entries}
    ordered = sorted(
        list(existing_entries) + list(filled_entries),
        key=lambda item: (item.start, item.end),
    )
    dropped: set[int] = set()
    for left, right in zip(ordered, ordered[1:]):
        if nearby_context_gap(left, right) > max_gap_seconds:
            continue
        if not context_duplicate_or_fragment(left.text, right.text):
            continue
        left_is_fill = id(left) in fill_ids
        right_is_fill = id(right) in fill_ids
        if left_is_fill and right_is_fill:
            dropped.add(id(left if fill_rank(left) <= fill_rank(right) else right))
        elif left_is_fill:
            dropped.add(id(left))
        elif right_is_fill:
            dropped.add(id(right))
    return dropped


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


def fill_vad_support_seconds(
    audio,
    entry: SubtitleEntry,
    threshold: float,
    pad_seconds: float,
    min_silence_ms: int,
    speech_pad_ms: int,
    sampling_rate: int = 16000,
) -> float:
    window = Interval(
        max(0.0, entry.start - pad_seconds),
        min(len(audio) / sampling_rate, entry.end + pad_seconds),
    )
    intervals = speech_intervals_from_gap_audio(
        audio,
        window,
        threshold,
        min_silence_ms,
        speech_pad_ms,
        sampling_rate=sampling_rate,
    )
    return overlap_seconds(Interval(entry.start, entry.end), intervals)


def looks_like_low_confidence_low_vad_support(
    audio,
    entry: SubtitleEntry,
    args: argparse.Namespace,
) -> bool:
    if args.fill_support_min_chars <= 0:
        return False
    if len(compact_text(entry.text)) < args.fill_support_min_chars:
        return False
    if entry.avg_logprob is None or entry.avg_logprob > args.fill_support_avg_logprob:
        return False
    if entry.no_speech_prob is None or entry.no_speech_prob < args.fill_support_no_speech_prob:
        return False
    duration = max(0.0, entry.end - entry.start)
    if duration <= 0:
        return True
    support = fill_vad_support_seconds(
        audio,
        entry,
        args.fill_support_vad_threshold,
        args.fill_support_pad_seconds,
        args.vad_min_silence_ms,
        args.vad_speech_pad_ms,
    )
    return support / duration <= args.fill_support_max_ratio


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
    covered = existing_intervals(existing_entries, args.existing_pad_seconds)
    gaps = srt_gaps_with_boundaries(existing_entries, audio_duration)

    candidate_clips: list[CandidateClip] = []
    stats = FillStats()
    for gap in gaps:
        if gap.end - gap.start < args.min_gap_seconds:
            continue
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
        max_clip_seconds = min(args.gap_local_asr_max_clip_seconds, 30.0)
        clip_overlap_seconds = args.gap_local_asr_overlap_seconds
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

    clips = [candidate.interval for candidate in candidate_clips]
    print(
        f"Gap fill: transcribing {len(clips)} clips "
        f"(batched, batch_size={args.main_local_batch_size})",
        flush=True,
    )
    raw_entries = transcribe_clips_batched(model, audio, clips, args)
    stats.raw_entries = len(raw_entries)

    def source_clip(entry: SubtitleEntry) -> Interval:
        for candidate in candidate_clips:
            if candidate.interval.start <= entry.start < candidate.interval.end:
                return candidate.interval
        return Interval(entry.start, entry.end)

    text_kept, text_filtered = filter_asr_text_entries(
        raw_entries,
        min_chars=args.min_fill_chars,
        max_compression_ratio=args.max_fill_compression_ratio,
        duplicate_window_seconds=None,
        apply_repeated_filter=False,
        hallucination_min_repeats=args.hallucination_min_repeats,
        hallucination_repeat_no_speech_prob=args.hallucination_repeat_no_speech_prob,
        hallucination_repeat_avg_logprob=args.hallucination_repeat_avg_logprob,
        hallucination_high_risk_max_repeats=args.hallucination_high_risk_max_repeats,
    )
    for entry in text_filtered:
        clip = source_clip(entry)
        stats.filtered_entries += 1
        if exceeds_compression_ratio(entry, args.max_fill_compression_ratio):
            reason = "compression_ratio"
        elif looks_like_noise(entry.text, args.min_fill_chars):
            reason = "noise"
        elif looks_like_hallucination(entry.text):
            reason = "hallucination"
        else:
            reason = "hallucination_repeat"
        metadata.append(FillMetadata(entry, clip, "filtered", reason))

    for entry in text_kept:
        clip = source_clip(entry)
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
        if looks_like_low_confidence_low_vad_support(audio, entry, args):
            stats.filtered_entries += 1
            metadata.append(FillMetadata(entry, clip, "filtered", "low_confidence_low_vad_support"))
            continue
        filled_entries.append(entry)
        metadata.append(FillMetadata(entry, clip, "kept", ""))

    filled_entries, repeated_filtered = filter_repeated_hallucination_entries(
        filled_entries,
        hallucination_min_repeats=args.hallucination_min_repeats,
        hallucination_repeat_no_speech_prob=args.hallucination_repeat_no_speech_prob,
        hallucination_repeat_avg_logprob=args.hallucination_repeat_avg_logprob,
        hallucination_high_risk_max_repeats=args.hallucination_high_risk_max_repeats,
    )
    for entry in repeated_filtered:
        stats.filtered_entries += 1
        for item in metadata:
            if item.entry is entry and item.status == "kept":
                item.status, item.reason = "filtered", "hallucination_repeat"
                break

    context_filtered_ids = context_duplicate_fill_entries(filled_entries, existing_entries)
    if context_filtered_ids:
        filtered_entries = []
        kept_entries = []
        for entry in filled_entries:
            if id(entry) in context_filtered_ids:
                filtered_entries.append(entry)
            else:
                kept_entries.append(entry)
        filled_entries = kept_entries
        for entry in filtered_entries:
            stats.filtered_entries += 1
            for item in metadata:
                if item.entry is entry and item.status == "kept":
                    item.status, item.reason = "filtered", "context_duplicate"
                    break

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


def build_parser() -> argparse.ArgumentParser:
    """Tuning knobs come from FillConfig (single source of truth, shared with the
    orchestrator); only IO/structural args are declared here."""
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
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    add_dataclass_arguments(parser, FillConfig)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.gap_local_vad_window_min_gap_seconds < 0:
        raise SystemExit("--gap-local-vad-window-min-gap-seconds must be >= 0")
    if args.gap_local_vad_window_seconds <= 0:
        raise SystemExit("--gap-local-vad-window-seconds must be > 0")
    if args.gap_local_vad_window_overlap_seconds < 0:
        raise SystemExit("--gap-local-vad-window-overlap-seconds must be >= 0")
    if args.gap_local_vad_window_overlap_seconds >= args.gap_local_vad_window_seconds:
        raise SystemExit("--gap-local-vad-window-overlap-seconds must be smaller than --gap-local-vad-window-seconds")
    if args.gap_local_asr_overlap_seconds >= min(args.gap_local_asr_max_clip_seconds, 30.0):
        raise SystemExit("--gap-local-asr-overlap-seconds must be smaller than the effective gap-fill ASR clip length")
    if args.main_local_vad_window_overlap_seconds >= args.main_local_vad_window_seconds:
        raise SystemExit("--main-local-vad-window-overlap-seconds must be smaller than --main-local-vad-window-seconds")
    if args.main_local_asr_overlap_seconds >= min(args.main_local_asr_max_clip_seconds, 30.0):
        raise SystemExit("--main-local-asr-overlap-seconds must be smaller than the effective main ASR clip length")

    if args.transcribe_output:
        model = load_model(str(args.model))
        # Resolve overlaps so the intermediate SRT matches standalone transcribe
        # output, and feed the resolved entries into gap filling.
        entries = finalize_main_entries(transcribe_audio(model, args.audio, args), args)
        write_entries(entries, args.transcribe_output)
        print(f"Wrote {args.transcribe_output}")
        fill_gaps(args, model=model, existing_entries=entries)
    else:
        if args.input is None:
            raise SystemExit("input SRT is required unless --transcribe-output is set")
        fill_gaps(args)


if __name__ == "__main__":
    main()
