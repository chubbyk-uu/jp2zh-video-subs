from __future__ import annotations

import argparse
import csv
import re
from dataclasses import dataclass, field
from pathlib import Path

from faster_whisper.audio import decode_audio

from fill_ja_srt_gaps import gap_local_vad_threshold, speech_intervals_from_gap_audio, srt_gaps_with_boundaries
from hallucination_filters import looks_like_hallucination
from quality_report import Entry, parse_fills_metadata, parse_srt
from srt_utils import Interval, compact_text, merge_intervals, overlap_seconds


VIDEO_EXTENSIONS = {".mp4", ".mkv", ".mov", ".avi", ".wmv", ".flv", ".webm", ".m4v", ".ts"}


@dataclass
class RunPaths:
    work: Path
    outputs: Path


@dataclass
class RunMetrics:
    entries: int = 0
    display_total_s: float = 0.0
    gap_max_s: float = 0.0
    gaps_gt_10: int = 0
    gaps_gt_30: int = 0
    gaps_gt_60: int = 0
    fills_kept: int = 0
    fills_filtered: int = 0
    fills_low_conf: int = 0


@dataclass
class LocalGapRow:
    gap: Interval
    threshold: float
    speech_s: float
    raw_asr_s: float
    kept_fill_s: float
    final_subtitle_s: float
    uncovered_s: float
    filtered_reason_s: dict[str, float] = field(default_factory=dict)


@dataclass
class LocalGapVadMetrics:
    gap_count: int = 0
    gap_duration_total_s: float = 0.0
    speech_total_s: float = 0.0
    speech_covered_s: float = 0.0
    speech_uncovered_s: float = 0.0
    raw_asr_covered_s: float = 0.0
    kept_fill_covered_s: float = 0.0
    filtered_reason_covered_s: dict[str, float] = field(default_factory=dict)
    coverage: float = 0.0
    raw_asr_coverage: float = 0.0
    kept_fill_coverage: float = 0.0
    top_uncovered: list[LocalGapRow] | None = None


def discover_stems(video_dir: Path) -> list[str]:
    return sorted(
        path.stem
        for path in video_dir.iterdir()
        if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS
    )


def gaps_between(entries: list[Entry]) -> list[Interval]:
    ordered = sorted(entries, key=lambda item: (item.start, item.end))
    gaps: list[Interval] = []
    for prev, curr in zip(ordered, ordered[1:]):
        if curr.start > prev.end:
            gaps.append(Interval(prev.end, curr.start))
    return gaps


def padded_entry_intervals(entries: list[Entry], padding: float) -> list[Interval]:
    return merge_intervals(
        [Interval(max(0.0, entry.start - padding), entry.end + padding) for entry in entries]
    )


def row_intervals(rows, *, status: str | None = None, reason: str | None = None) -> list[Interval]:
    intervals: list[Interval] = []
    for row in rows:
        if status is not None and row.status != status:
            continue
        if reason is not None and (row.reason or "") != reason:
            continue
        intervals.append(Interval(row.start, row.end))
    return merge_intervals(intervals)


def overlap_many(intervals: list[Interval], covered: list[Interval]) -> float:
    return sum(overlap_seconds(item, covered) for item in intervals)


def fill_low_conf_count(rows) -> int:
    count = 0
    for row in rows:
        if row.status != "kept":
            continue
        if (
            (row.avg_logprob is not None and row.avg_logprob < -0.80)
            or (row.no_speech_prob is not None and row.no_speech_prob > 0.50)
            or (row.compression_ratio is not None and row.compression_ratio > 2.20)
        ):
            count += 1
    return count


def run_metrics(run: RunPaths, stem: str) -> RunMetrics:
    filled = parse_srt(run.work / stem / f"{stem}.filled.ja.srt")
    fills = parse_fills_metadata(run.work / stem / f"{stem}.fills.tsv")
    durations = [max(0.0, entry.end - entry.start) for entry in filled]
    gaps = gaps_between(filled)
    kept = [row for row in fills if row.status == "kept"]
    filtered = [row for row in fills if row.status == "filtered"]
    return RunMetrics(
        entries=len(filled),
        display_total_s=sum(durations),
        gap_max_s=max((gap.end - gap.start for gap in gaps), default=0.0),
        gaps_gt_10=sum(gap.end - gap.start > 10.0 for gap in gaps),
        gaps_gt_30=sum(gap.end - gap.start > 30.0 for gap in gaps),
        gaps_gt_60=sum(gap.end - gap.start > 60.0 for gap in gaps),
        fills_kept=len(kept),
        fills_filtered=len(filtered),
        fills_low_conf=fill_low_conf_count(fills),
    )


def local_gap_vad_metrics(
    run: RunPaths,
    stem: str,
    min_gap_seconds: float,
    min_speech_seconds: float,
    vad_min_silence_ms: int,
    vad_speech_pad_ms: int,
    vad_min_threshold: float,
    vad_max_threshold: float,
    subtitle_pad_seconds: float,
) -> LocalGapVadMetrics:
    main_entries = parse_srt(run.work / stem / f"{stem}.ja.srt")
    filled_entries = parse_srt(run.work / stem / f"{stem}.filled.ja.srt")
    fill_rows = parse_fills_metadata(run.work / stem / f"{stem}.fills.tsv")
    audio_path = run.work / stem / f"{stem}.wav"
    if not main_entries or not filled_entries or not audio_path.exists():
        return LocalGapVadMetrics(top_uncovered=[])

    audio = decode_audio(str(audio_path), sampling_rate=16000)
    audio_duration = len(audio) / 16000
    gaps = [
        gap for gap in srt_gaps_with_boundaries(main_entries, audio_duration)
        if gap.end - gap.start >= min_gap_seconds
    ]
    subtitle_intervals = padded_entry_intervals(filled_entries, subtitle_pad_seconds)
    raw_asr_intervals = row_intervals(fill_rows)
    kept_fill_intervals = row_intervals(fill_rows, status="kept")
    filtered_reasons = sorted({row.reason for row in fill_rows if row.status == "filtered" and row.reason})
    filtered_reason_intervals = {
        reason: row_intervals(fill_rows, status="filtered", reason=reason)
        for reason in filtered_reasons
    }

    speech_intervals: list[Interval] = []
    gap_rows: list[LocalGapRow] = []
    for gap in gaps:
        threshold = gap_local_vad_threshold(gap.end - gap.start, vad_min_threshold, vad_max_threshold)
        gap_speech = speech_intervals_from_gap_audio(
            audio,
            gap,
            threshold,
            vad_min_silence_ms,
            vad_speech_pad_ms,
        )
        speech_seconds = overlap_seconds(gap, gap_speech)
        if speech_seconds < min_speech_seconds:
            continue
        raw_asr_covered = overlap_many(gap_speech, raw_asr_intervals)
        kept_fill_covered = overlap_many(gap_speech, kept_fill_intervals)
        covered = overlap_many(gap_speech, subtitle_intervals)
        uncovered = max(0.0, speech_seconds - covered)
        reason_coverage = {}
        for reason, intervals in filtered_reason_intervals.items():
            covered_by_reason = overlap_many(gap_speech, intervals)
            if covered_by_reason > 0.0:
                reason_coverage[reason] = covered_by_reason
        gap_rows.append(
            LocalGapRow(
                gap=gap,
                threshold=threshold,
                speech_s=speech_seconds,
                raw_asr_s=raw_asr_covered,
                kept_fill_s=kept_fill_covered,
                final_subtitle_s=covered,
                uncovered_s=uncovered,
                filtered_reason_s=reason_coverage,
            )
        )
        speech_intervals.extend(gap_speech)

    merged_speech = merge_intervals(speech_intervals)
    speech_total = sum(item.end - item.start for item in merged_speech)
    speech_covered = overlap_many(merged_speech, subtitle_intervals)
    raw_asr_covered = overlap_many(merged_speech, raw_asr_intervals)
    kept_fill_covered = overlap_many(merged_speech, kept_fill_intervals)
    filtered_reason_covered = {
        reason: overlap_many(merged_speech, intervals)
        for reason, intervals in filtered_reason_intervals.items()
    }
    speech_uncovered = max(0.0, speech_total - speech_covered)
    return LocalGapVadMetrics(
        gap_count=len(gap_rows),
        gap_duration_total_s=sum(row.gap.end - row.gap.start for row in gap_rows),
        speech_total_s=speech_total,
        speech_covered_s=speech_covered,
        speech_uncovered_s=speech_uncovered,
        raw_asr_covered_s=raw_asr_covered,
        kept_fill_covered_s=kept_fill_covered,
        filtered_reason_covered_s=filtered_reason_covered,
        coverage=speech_covered / speech_total if speech_total > 0 else 0.0,
        raw_asr_coverage=raw_asr_covered / speech_total if speech_total > 0 else 0.0,
        kept_fill_coverage=kept_fill_covered / speech_total if speech_total > 0 else 0.0,
        top_uncovered=sorted(gap_rows, key=lambda item: item.uncovered_s, reverse=True)[:20],
    )


def compact(value: str) -> str:
    return compact_text(value)


def compare_entries(old_entries: list[Entry], new_entries: list[Entry]):
    added: list[Entry] = []
    removed: list[Entry] = []
    changed: list[tuple[Entry, Entry]] = []
    used_old: set[int] = set()
    for new in new_entries:
        best_index = -1
        best_score = 0.0
        for index, old in enumerate(old_entries):
            overlap = max(0.0, min(new.end, old.end) - max(new.start, old.start))
            score = overlap / max(0.001, min(new.end - new.start, old.end - old.start))
            if score > best_score:
                best_score = score
                best_index = index
        if best_index >= 0 and best_score >= 0.5:
            old = old_entries[best_index]
            used_old.add(best_index)
            if compact(old.text) != compact(new.text):
                changed.append((old, new))
        else:
            added.append(new)
    for index, old in enumerate(old_entries):
        if index not in used_old:
            removed.append(old)
    return added, removed, changed


def suspicious_kept_rows(run: RunPaths, stem: str):
    rows = parse_fills_metadata(run.work / stem / f"{stem}.fills.tsv")
    suspicious = []
    for row in rows:
        if row.status != "kept":
            continue
        if (
            looks_like_hallucination(row.text)
            or (row.avg_logprob is not None and row.avg_logprob < -0.95)
            or (row.no_speech_prob is not None and row.no_speech_prob > 0.80)
            or (row.compression_ratio is not None and row.compression_ratio > 2.20)
        ):
            suspicious.append(row)
    return sorted(suspicious, key=lambda item: (item.start, item.end))


def format_time(seconds: float) -> str:
    whole = int(seconds)
    return f"{whole // 3600:02d}:{whole % 3600 // 60:02d}:{whole % 60:02d}"


def write_detail_report(
    path: Path,
    stem: str,
    old_run: RunPaths,
    new_run: RunPaths,
    old_metrics: RunMetrics,
    new_metrics: RunMetrics,
    local_metrics: LocalGapVadMetrics,
    max_samples: int,
) -> None:
    old_ja = parse_srt(old_run.work / stem / f"{stem}.filled.ja.srt")
    new_ja = parse_srt(new_run.work / stem / f"{stem}.filled.ja.srt")
    added, removed, changed = compare_entries(old_ja, new_ja)
    suspicious = suspicious_kept_rows(new_run, stem)

    lines = [
        f"# {stem}",
        "",
        "## Summary",
        f"entries: {old_metrics.entries} -> {new_metrics.entries} ({new_metrics.entries - old_metrics.entries:+d})",
        f"display_total_min: {old_metrics.display_total_s / 60:.1f} -> {new_metrics.display_total_s / 60:.1f}",
        f"gap_max_s: {old_metrics.gap_max_s:.1f} -> {new_metrics.gap_max_s:.1f}",
        f"gaps_gt_30: {old_metrics.gaps_gt_30} -> {new_metrics.gaps_gt_30}",
        f"gaps_gt_60: {old_metrics.gaps_gt_60} -> {new_metrics.gaps_gt_60}",
        f"fills_kept: {old_metrics.fills_kept} -> {new_metrics.fills_kept}",
        f"fills_low_conf: {old_metrics.fills_low_conf} -> {new_metrics.fills_low_conf}",
        "",
        "## Local Gap VAD Coverage",
        f"candidate_gap_count: {local_metrics.gap_count}",
        f"candidate_gap_duration_total_s: {local_metrics.gap_duration_total_s:.1f}",
        f"local_gap_vad_speech_total_s: {local_metrics.speech_total_s:.1f}",
        f"local_gap_vad_raw_asr_s: {local_metrics.raw_asr_covered_s:.1f}",
        f"local_gap_vad_raw_asr_coverage: {local_metrics.raw_asr_coverage:.1%}",
        f"local_gap_vad_kept_fill_s: {local_metrics.kept_fill_covered_s:.1f}",
        f"local_gap_vad_kept_fill_coverage: {local_metrics.kept_fill_coverage:.1%}",
        f"local_gap_vad_speech_covered_s: {local_metrics.speech_covered_s:.1f}",
        f"local_gap_vad_speech_uncovered_s: {local_metrics.speech_uncovered_s:.1f}",
        f"local_gap_vad_final_subtitle_coverage: {local_metrics.coverage:.1%}",
        "",
        "## Local Gap Filter Coverage",
    ]
    for reason, seconds in sorted(
        local_metrics.filtered_reason_covered_s.items(),
        key=lambda item: item[1],
        reverse=True,
    ):
        if seconds > 0.0:
            lines.append(f"- {reason}: {seconds:.1f}s ({seconds / local_metrics.speech_total_s:.1%})")

    lines.extend([
        "",
        "## Added JA Samples",
    ])
    for item in added[:max_samples]:
        lines.append(f"+ {format_time(item.start)}-{format_time(item.end)} {item.text}")
    lines.append("")
    lines.append("## Removed JA Samples")
    for item in removed[:max_samples]:
        lines.append(f"- {format_time(item.start)}-{format_time(item.end)} {item.text}")
    lines.append("")
    lines.append("## Changed JA Samples")
    for old, new in changed[:max_samples]:
        lines.append(f"* {format_time(new.start)}-{format_time(new.end)} old={old.text} | new={new.text}")
    lines.append("")
    lines.append("## Suspicious Kept Fill Samples")
    for row in suspicious[:max_samples]:
        lines.append(
            f"! {format_time(row.start)}-{format_time(row.end)} "
            f"avg={row.avg_logprob} ns={row.no_speech_prob} cr={row.compression_ratio} {row.text}"
        )
    lines.append("")
    lines.append("## Top Local VAD Uncovered Gaps")
    for row in (local_metrics.top_uncovered or [])[:max_samples]:
        gap = row.gap
        reason_text = ", ".join(
            f"{reason}={seconds:.1f}s"
            for reason, seconds in sorted(row.filtered_reason_s.items(), key=lambda item: item[1], reverse=True)
        )
        lines.append(
            f"- {format_time(gap.start)} -> {format_time(gap.end)} "
            f"gap={gap.end - gap.start:.1f}s threshold={row.threshold:.2f} "
            f"speech={row.speech_s:.1f}s raw_asr={row.raw_asr_s:.1f}s "
            f"kept_fill={row.kept_fill_s:.1f}s final_subtitle={row.final_subtitle_s:.1f}s "
            f"uncovered={row.uncovered_s:.1f}s"
            + (f" filtered[{reason_text}]" if reason_text else "")
        )

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare two subtitle pipeline runs.")
    parser.add_argument("--old-work", type=Path, required=True)
    parser.add_argument("--old-outputs", type=Path, required=True)
    parser.add_argument("--new-work", type=Path, required=True)
    parser.add_argument("--new-outputs", type=Path, required=True)
    parser.add_argument("--video-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--stem", action="append", dest="stems")
    parser.add_argument("--min-gap-seconds", type=float, default=2.0)
    parser.add_argument("--min-speech-seconds", type=float, default=1.0)
    parser.add_argument("--vad-min-silence-ms", type=int, default=500)
    parser.add_argument("--vad-speech-pad-ms", type=int, default=400)
    parser.add_argument("--gap-local-vad-min-threshold", type=float, default=0.10)
    parser.add_argument("--gap-local-vad-max-threshold", type=float, default=0.40)
    parser.add_argument("--subtitle-pad-seconds", type=float, default=0.5)
    parser.add_argument("--max-samples", type=int, default=12)
    args = parser.parse_args()

    old_run = RunPaths(args.old_work, args.old_outputs)
    new_run = RunPaths(args.new_work, args.new_outputs)
    stems = args.stems or discover_stems(args.video_dir)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    summary_path = args.output_dir / "comparison.tsv"
    with summary_path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.writer(file, delimiter="\t")
        writer.writerow([
            "stem",
            "old_entries",
            "new_entries",
            "delta_entries",
            "old_display_min",
            "new_display_min",
            "old_gap_max_s",
            "new_gap_max_s",
            "old_gaps_gt_30",
            "new_gaps_gt_30",
            "old_gaps_gt_60",
            "new_gaps_gt_60",
            "old_fills_kept",
            "new_fills_kept",
            "old_fills_low_conf",
            "new_fills_low_conf",
            "local_gap_count",
            "local_gap_vad_speech_total_s",
            "local_gap_vad_raw_asr_s",
            "local_gap_vad_raw_asr_coverage",
            "local_gap_vad_kept_fill_s",
            "local_gap_vad_kept_fill_coverage",
            "local_gap_vad_speech_covered_s",
            "local_gap_vad_final_subtitle_coverage",
        ])
        for stem in stems:
            old_metrics = run_metrics(old_run, stem)
            new_metrics = run_metrics(new_run, stem)
            local_metrics = local_gap_vad_metrics(
                new_run,
                stem,
                args.min_gap_seconds,
                args.min_speech_seconds,
                args.vad_min_silence_ms,
                args.vad_speech_pad_ms,
                args.gap_local_vad_min_threshold,
                args.gap_local_vad_max_threshold,
                args.subtitle_pad_seconds,
            )
            writer.writerow([
                stem,
                old_metrics.entries,
                new_metrics.entries,
                new_metrics.entries - old_metrics.entries,
                f"{old_metrics.display_total_s / 60:.1f}",
                f"{new_metrics.display_total_s / 60:.1f}",
                f"{old_metrics.gap_max_s:.1f}",
                f"{new_metrics.gap_max_s:.1f}",
                old_metrics.gaps_gt_30,
                new_metrics.gaps_gt_30,
                old_metrics.gaps_gt_60,
                new_metrics.gaps_gt_60,
                old_metrics.fills_kept,
                new_metrics.fills_kept,
                old_metrics.fills_low_conf,
                new_metrics.fills_low_conf,
                local_metrics.gap_count,
                f"{local_metrics.speech_total_s:.1f}",
                f"{local_metrics.raw_asr_covered_s:.1f}",
                f"{local_metrics.raw_asr_coverage:.1%}",
                f"{local_metrics.kept_fill_covered_s:.1f}",
                f"{local_metrics.kept_fill_coverage:.1%}",
                f"{local_metrics.speech_covered_s:.1f}",
                f"{local_metrics.coverage:.1%}",
            ])
            write_detail_report(
                args.output_dir / f"{stem}.comparison.txt",
                stem,
                old_run,
                new_run,
                old_metrics,
                new_metrics,
                local_metrics,
                args.max_samples,
            )

    print(f"Wrote {summary_path}")


if __name__ == "__main__":
    main()
