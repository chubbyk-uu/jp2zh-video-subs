from __future__ import annotations

import argparse
import difflib
from dataclasses import dataclass
from pathlib import Path

from hallucination_filters import (
    exceeds_compression_ratio,
    is_duplicate_of_nearby,
    is_high_risk_repeat_phrase,
    looks_like_hallucination,
    looks_like_noise,
    normalize_phrase,
    repeated_hallucination_texts,
)
from srt_utils import Interval, compact_text, merge_intervals, srt_time


@dataclass
class SubtitleEntry:
    start: float
    end: float
    text: str
    avg_logprob: float | None = None
    no_speech_prob: float | None = None
    compression_ratio: float | None = None
    # True when a forced aligner gave this cue a zero-width span, so start/end
    # are an artefact rather than a real localisation.
    collapsed: bool = False


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(value, maximum))


def estimate_display_duration(text: str, min_duration: float, max_duration: float) -> float:
    compact = compact_text(text)
    if not compact:
        return min_duration
    return clamp(len(compact) * 0.28, min_duration, max_duration)


def merge_short_entries(entries: list[SubtitleEntry], max_merge_gap: float, max_chars: int) -> list[SubtitleEntry]:
    merged: list[SubtitleEntry] = []

    def merge_confidence(target: SubtitleEntry, source: SubtitleEntry) -> None:
        if source.avg_logprob is not None:
            target.avg_logprob = (
                source.avg_logprob if target.avg_logprob is None else min(target.avg_logprob, source.avg_logprob)
            )
        if source.no_speech_prob is not None:
            target.no_speech_prob = (
                source.no_speech_prob if target.no_speech_prob is None else max(target.no_speech_prob, source.no_speech_prob)
            )
        if source.compression_ratio is not None:
            target.compression_ratio = (
                source.compression_ratio if target.compression_ratio is None else max(target.compression_ratio, source.compression_ratio)
            )

    for entry in entries:
        text = compact_text(entry.text)
        if (
            merged
            and len(text) <= 2
            and entry.start - merged[-1].end <= max_merge_gap
            and len(compact_text(merged[-1].text) + text) <= max_chars
        ):
            merged[-1].end = max(merged[-1].end, entry.end)
            merged[-1].text = merged[-1].text + entry.text
            merge_confidence(merged[-1], entry)
            continue
        if (
            merged
            and len(compact_text(merged[-1].text)) <= 2
            and entry.start - merged[-1].end <= max_merge_gap
            and len(compact_text(merged[-1].text) + text) <= max_chars
        ):
            merged[-1].end = max(merged[-1].end, entry.end)
            merged[-1].text = merged[-1].text + entry.text
            merge_confidence(merged[-1], entry)
            continue
        merged.append(
            SubtitleEntry(
                entry.start,
                entry.end,
                entry.text,
                entry.avg_logprob,
                entry.no_speech_prob,
                entry.compression_ratio,
                entry.collapsed,
            )
        )
    return merged


def filter_hallucination_entries(entries: list[SubtitleEntry]) -> tuple[list[SubtitleEntry], list[SubtitleEntry]]:
    kept: list[SubtitleEntry] = []
    filtered: list[SubtitleEntry] = []
    hard_hallucination_indexes = {
        index for index, entry in enumerate(entries) if looks_like_hallucination(entry.text)
    }
    for index, entry in enumerate(entries):
        adjacent_to_hallucination = False
        for neighbor in (index - 1, index + 1):
            if neighbor not in hard_hallucination_indexes:
                continue
            nearby = (
                abs(entries[neighbor].start - entry.end) <= 5.0
                or abs(entry.start - entries[neighbor].end) <= 5.0
            )
            if nearby:
                adjacent_to_hallucination = True
                break
        if looks_like_hallucination(entry.text) or (
            adjacent_to_hallucination and is_high_risk_repeat_phrase(entry.text)
        ):
            filtered.append(entry)
        else:
            kept.append(entry)
    return kept, filtered


def filter_repeated_hallucination_entries(
    entries: list[SubtitleEntry],
    *,
    hallucination_min_repeats: int,
    hallucination_repeat_no_speech_prob: float,
    hallucination_repeat_avg_logprob: float,
    hallucination_high_risk_max_repeats: int,
) -> tuple[list[SubtitleEntry], list[SubtitleEntry]]:
    repeated = repeated_hallucination_texts(
        entries,
        hallucination_min_repeats,
        hallucination_repeat_no_speech_prob,
        hallucination_repeat_avg_logprob,
        hallucination_high_risk_max_repeats,
    )
    filtered: list[SubtitleEntry] = []
    if repeated:
        kept: list[SubtitleEntry] = []
        for entry in entries:
            if normalize_phrase(entry.text) in repeated:
                filtered.append(entry)
            else:
                kept.append(entry)
        return kept, filtered
    return entries, filtered


def filter_asr_text_entries(
    entries: list[SubtitleEntry],
    *,
    min_chars: int,
    max_compression_ratio: float,
    duplicate_window_seconds: float | None,
    hallucination_min_repeats: int,
    hallucination_repeat_no_speech_prob: float,
    hallucination_repeat_avg_logprob: float,
    hallucination_high_risk_max_repeats: int,
    apply_repeated_filter: bool = True,
) -> tuple[list[SubtitleEntry], list[SubtitleEntry]]:
    kept, filtered = filter_hallucination_entries(entries)
    survivors: list[SubtitleEntry] = []
    for entry in sorted(kept, key=lambda item: (item.start, item.end)):
        if exceeds_compression_ratio(entry, max_compression_ratio):
            filtered.append(entry)
            continue
        if looks_like_noise(entry.text, min_chars):
            filtered.append(entry)
            continue
        if duplicate_window_seconds is not None and duplicate_window_seconds >= 0 and is_duplicate_of_nearby(
            entry,
            survivors,
            duplicate_window_seconds,
        ):
            filtered.append(entry)
            continue
        survivors.append(entry)

    if apply_repeated_filter:
        survivors, repeated_filtered = filter_repeated_hallucination_entries(
            survivors,
            hallucination_min_repeats=hallucination_min_repeats,
            hallucination_repeat_no_speech_prob=hallucination_repeat_no_speech_prob,
            hallucination_repeat_avg_logprob=hallucination_repeat_avg_logprob,
            hallucination_high_risk_max_repeats=hallucination_high_risk_max_repeats,
        )
        filtered.extend(repeated_filtered)
    return survivors, filtered


def filter_main_local_entries(
    entries: list[SubtitleEntry],
    args: argparse.Namespace,
) -> tuple[list[SubtitleEntry], list[SubtitleEntry]]:
    return filter_asr_text_entries(
        entries,
        min_chars=args.main_min_chars,
        max_compression_ratio=args.main_max_compression_ratio,
        duplicate_window_seconds=args.main_duplicate_window_seconds,
        hallucination_min_repeats=args.hallucination_min_repeats,
        hallucination_repeat_no_speech_prob=args.hallucination_repeat_no_speech_prob,
        hallucination_repeat_avg_logprob=args.hallucination_repeat_avg_logprob,
        hallucination_high_risk_max_repeats=args.hallucination_high_risk_max_repeats,
        apply_repeated_filter=True,
    )


def drop_adjacent_near_duplicates(
    entries: list[SubtitleEntry],
    max_gap: float,
    similarity: float,
    squeeze_seconds: float,
) -> list[SubtitleEntry]:
    ordered = sorted(entries, key=lambda item: (item.start, item.end))
    kept: list[SubtitleEntry] = []
    for entry in ordered:
        if kept:
            previous = kept[-1]
            if entry.start - previous.end <= max_gap:
                ratio = difflib.SequenceMatcher(
                    None, compact_text(previous.text), compact_text(entry.text)
                ).ratio()
                prev_dur = previous.end - previous.start
                cur_dur = entry.end - entry.start
                if ratio >= similarity and min(prev_dur, cur_dur) < squeeze_seconds:
                    if cur_dur < prev_dur:
                        continue
                    kept[-1] = entry
                    continue
        kept.append(entry)
    return kept


def resolve_overlaps(entries: list[SubtitleEntry]) -> list[SubtitleEntry]:
    ordered = sorted(entries, key=lambda item: (item.start, item.end))
    for previous, current in zip(ordered, ordered[1:]):
        if previous.end > current.start and current.start > previous.start:
            previous.end = current.start
    return ordered


def write_entries(entries: list[SubtitleEntry], output_path: Path) -> None:
    with output_path.open("w", encoding="utf-8") as f:
        for index, entry in enumerate(entries, start=1):
            f.write(f"{index}\n")
            f.write(f"{srt_time(entry.start)} --> {srt_time(entry.end)}\n")
            f.write(f"{entry.text}\n\n")
            print(f"{index}: {srt_time(entry.end)} {entry.text[:40]}", flush=True)


def speech_clusters(
    speech_intervals: list[Interval],
    max_cluster_gap: float,
    pad_seconds: float,
    audio_duration: float,
) -> list[Interval]:
    if not speech_intervals:
        return []
    clusters = [Interval(speech_intervals[0].start, speech_intervals[0].end)]
    for item in speech_intervals[1:]:
        last = clusters[-1]
        if item.start - last.end <= max_cluster_gap:
            last.end = max(last.end, item.end)
        else:
            clusters.append(Interval(item.start, item.end))
    padded = [
        Interval(max(0.0, item.start - pad_seconds), min(audio_duration, item.end + pad_seconds))
        for item in clusters
    ]
    return merge_intervals(padded)


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
