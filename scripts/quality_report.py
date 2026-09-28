from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import wave
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from cli_config import add_dataclass_arguments, config_from_namespace
from evaluation_core import compare_subtitles, full_span_gaps, load_subtitles
from pipeline_configs import (
    QualityReportConfig,
    raise_for_config_issues,
    validate_quality_config,
)
from srt_utils import (
    Interval,
    compact_text,
    format_time,
    merge_intervals,
    overlap_seconds,
    srt_gaps,
)

KANA_RE = re.compile(r"[ぁ-ゟ゠-ヿ]")
CJK_RE = re.compile(r"[\u3400-\u9fff]")
READING_STRIP_RE = re.compile(r"[。、，,！？!?…♪〜~ー・「」『』（）()\[\]【】\s]")
# Conservative candidates for Japanese/traditional CJK left in Simplified Chinese
# output. These are review hints only; they are never used to filter subtitles.
# Keep this intentionally small: prefer missing some kanji-only leftovers over
# flagging normal Simplified Chinese as suspicious.
NON_SIMPLIFIED_CJK_RE = re.compile(
    r"[亜悪圧為隠栄駅円応桜仮価壊壌楽気帰拠挙郷暁経軽県険権験厳"
    r"済児実釈収従処焼証乗嬢譲畳浄剰図跡摂戦銭選総増蔵続対滝聴"
    r"鉄転伝徳読廃売発払仏辺変歩訳薬様頼覧竜両緑涙霊齢歴労録関"
    r"與國會學聲體處廣電誰話聞買愛]"
)


@dataclass
class Entry:
    index: str
    start: float
    end: float
    text: str


@lru_cache(maxsize=200000)
def reading_text(text: str) -> str:
    """Hiragana reading used for reference-aware ASR comparison.

    This mirrors subtitle_benchmark.py: comparing readings instead of raw strings avoids
    treating kana/kanji variants as misses.
    """
    return "".join(item["hira"] for item in _kakasi().convert(READING_STRIP_RE.sub("", text)))


@lru_cache(maxsize=1)
def _kakasi():
    import pykakasi

    return pykakasi.kakasi()


def reading_bigrams(text: str) -> set[str]:
    reading = reading_text(text)
    return {reading[i : i + 2] for i in range(len(reading) - 1)}


def reading_overlap(needles: set[str], haystack: set[str]) -> float:
    return len(needles & haystack) / len(needles) if needles else 0.0


def window_reading_bigrams(entries: list[Entry], start: float, end: float, pad: float) -> set[str]:
    text = " ".join(item.text for item in entries if item.end >= start - pad and item.start <= end + pad)
    return reading_bigrams(text)


def parse_named_srt(value: str) -> tuple[str, Path]:
    if "=" in value:
        name, path = value.split("=", 1)
        return name.strip() or Path(path).stem, Path(path)
    path = Path(value)
    return path.stem, path


def reference_segments(
    entries: list[Entry],
    min_reading: int,
) -> list[tuple[Entry, set[str]]]:
    segments: list[tuple[Entry, set[str]]] = []
    for entry in entries:
        if len(reading_text(entry.text)) < min_reading:
            continue
        bigrams = reading_bigrams(entry.text)
        if bigrams:
            segments.append((entry, bigrams))
    return segments


def reference_recall(
    candidate: list[Entry],
    segments: list[tuple[Entry, set[str]]],
    pad: float,
    threshold: float,
) -> tuple[int, int, list[Entry]]:
    hits = 0
    missed: list[Entry] = []
    for entry, bigrams in segments:
        score = reading_overlap(bigrams, window_reading_bigrams(candidate, entry.start, entry.end, pad))
        if score >= threshold:
            hits += 1
        else:
            missed.append(entry)
    return hits, len(segments), missed


def fmt_fraction(hit: int, total: int) -> str:
    if total == 0:
        return f"n/a ({hit}/{total})"
    return f"{hit / total:.1%} ({hit}/{total})"


def parse_srt(path: Path | None) -> list[Entry]:
    # Compatibility helper: callers may still request the parsed valid subset.
    # build_report separately exposes invalid/missing status and refuses accuracy.
    return [Entry(c.index, c.start, c.end, c.text) for c in load_subtitles(path).cues]


def load_json(path: Path | None) -> dict:
    if path is None or not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


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


def speech_intervals_from_metadata(qwen_metadata: dict) -> list[Interval]:
    intervals: list[Interval] = []
    chunks = qwen_metadata.get("chunks", [])
    if not isinstance(chunks, list):
        return []
    for chunk in chunks:
        if not isinstance(chunk, dict):
            continue
        regions = chunk.get("speech_regions")
        if not isinstance(regions, list):
            continue
        try:
            base = float(chunk.get("start", 0.0) or 0.0)
        except (TypeError, ValueError):
            base = 0.0
        for region in regions:
            if not isinstance(region, (list, tuple)) or len(region) < 2:
                continue
            try:
                start = base + float(region[0])
                end = base + float(region[1])
            except (TypeError, ValueError):
                continue
            if end > start:
                intervals.append(Interval(max(0.0, start), end))
    return merge_intervals(intervals)


def speech_intervals_from_whisperseg_audio(
    audio_path: Path,
    model_path: str,
    threshold: float,
    max_speech: float,
    hard_max_speech: float,
    soft_split_lookback: float,
    max_group: float,
    chunk_threshold: float,
    min_frame_seconds: float,
    audio=None,
) -> list[Interval]:
    from whisperseg_vad import WhisperSegVAD, resolve_model_path

    if audio is None:
        import librosa

        audio, _ = librosa.load(str(audio_path), sr=16000, mono=True)
    vad = WhisperSegVAD(
        model_path=resolve_model_path(model_path),
        threshold=threshold,
        max_speech_duration_s=max_speech,
        hard_max_speech_duration_s=hard_max_speech,
        soft_split_lookback_s=soft_split_lookback,
        max_group_duration_s=max_group,
        chunk_threshold_s=chunk_threshold,
    )
    try:
        groups = vad.segment(audio, 16000)
    finally:
        cleanup = getattr(vad, "cleanup", None)
        if callable(cleanup):
            cleanup()
    intervals: list[Interval] = []
    for group in groups:
        if not group:
            continue
        frame_start = min(item.start for item in group)
        frame_end = max(item.end for item in group)
        if frame_end - frame_start < min_frame_seconds:
            continue
        for item in group:
            if item.end > item.start:
                intervals.append(Interval(max(0.0, item.start), item.end))
    return merge_intervals(intervals)


def speech_intervals_for_report(
    args: argparse.Namespace,
    qwen_metadata: dict,
) -> tuple[list[Interval], str]:
    backend = getattr(args, "vad_backend", "auto")
    metadata_intervals = speech_intervals_from_metadata(qwen_metadata)
    if backend in ("auto", "metadata") and metadata_intervals:
        return metadata_intervals, "metadata"
    if backend == "metadata":
        return [], "metadata(empty)"

    if backend == "auto":
        backend = "whisperseg"
    audio_path = getattr(args, "audio", None)
    if audio_path is None or not audio_path.exists():
        return [], f"{backend}(audio_missing)"
    if backend == "whisperseg":
        return (
            speech_intervals_from_whisperseg_audio(
                audio_path,
                getattr(args, "whisperseg_model", "models/whisperseg/model.onnx"),
                getattr(args, "whisperseg_threshold", 0.35),
                getattr(args, "whisperseg_max_speech", 5.0),
                getattr(args, "whisperseg_hard_max_speech", getattr(args, "whisperseg_max_speech", 5.0)),
                getattr(args, "whisperseg_soft_split_lookback", 1.0),
                getattr(args, "whisperseg_max_group", 5.0),
                getattr(args, "whisperseg_chunk_threshold", 0.5),
                getattr(args, "whisperseg_min_frame_seconds", 0.1),
            ),
            "whisperseg",
        )
    return [], f"{backend}(unsupported)"


def adjacent_duplicate_candidates(ja_entries: list[Entry], zh_entries: list[Entry]) -> list[str]:
    candidates: list[str] = []
    # Only assess confirmed 1:1 correspondence. IDs alone can be renumbered after
    # deletions, so their source start times must agree too; never positional zip.
    source_by_id = {item.index: item for item in ja_entries}
    duplicate_source_ids = {item.index for item in ja_entries if sum(c.index == item.index for c in ja_entries) > 1}
    for prev_zh, curr_zh in zip(zh_entries, zh_entries[1:]):
        prev_ja, curr_ja = source_by_id.get(prev_zh.index), source_by_id.get(curr_zh.index)
        if prev_ja is None or curr_ja is None:
            continue
        if prev_zh.index in duplicate_source_ids or curr_zh.index in duplicate_source_ids:
            continue
        if abs(prev_ja.start - prev_zh.start) > 0.25 or abs(curr_ja.start - curr_zh.start) > 0.25:
            continue
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


def audio_duration(path: Path | None) -> float | None:
    if path is None or not path.is_file():
        return None
    try:
        with wave.open(str(path), "rb") as audio:
            return audio.getnframes() / audio.getframerate()
    except (OSError, wave.Error, EOFError):
        try:
            result = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                     "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
                                    capture_output=True, text=True, timeout=30, check=True)
            value = float(result.stdout.strip())
            return value if math.isfinite(value) and value >= 0 else None
        except (OSError, ValueError, subprocess.SubprocessError):
            return None


def audio_gap_report(args, ja_entries, qwen_metadata, metrics, max_samples) -> list[str]:
    speech_intervals, backend = speech_intervals_for_report(args, qwen_metadata)
    duration = audio_duration(getattr(args, "audio", None))
    # Metadata bounds give a lower bound when full audio duration is unavailable.
    inferred_end = max([item.end for item in speech_intervals] + [item.end for item in ja_entries] + [0.0])
    span = duration if duration is not None else inferred_end
    gaps = full_span_gaps(ja_entries, span)
    covered = padded_intervals(ja_entries, args.subtitle_pad_seconds)
    total = sum(item.end - item.start for item in speech_intervals)
    covered_seconds = min(total, sum(overlap_seconds(item, covered) for item in speech_intervals))
    suspicious = [(gap, overlap_seconds(gap, speech_intervals)) for gap in gaps
                  if gap.end - gap.start >= args.min_gap_seconds
                  and overlap_seconds(gap, speech_intervals) >= args.min_speech_seconds]
    metrics.update(vad_backend=backend, vad_speech_total_s=round(total, 1),
                   vad_speech_uncovered_s=round(max(0.0, total - covered_seconds), 1),
                   vad_speech_coverage=round(covered_seconds / total, 3) if total else None,
                   gaps_with_vad_speech=len(suspicious), audio_duration_s=duration,
                   gap_span_evidence="full_audio" if duration is not None else "metadata_lower_bound")
    lines = ["[Audio-aware subtitle gaps]",
             "note: VAD coverage is a risk hint, not ASR accuracy; breath/music/fillers may be counted.",
             f"gap_span_evidence: {metrics['gap_span_evidence']}", f"vad_backend: {backend}",
             f"vad_speech_segments: {len(speech_intervals)}", f"vad_speech_total_s: {total:.1f}",
             f"vad_speech_covered_by_subtitles_s: {covered_seconds:.1f}",
             f"vad_speech_uncovered_s: {max(0.0, total - covered_seconds):.1f}",
             f"vad_speech_coverage: {covered_seconds / total:.1%}" if total else "vad_speech_coverage: n/a",
             f"subtitle_gaps_with_vad_speech: {len(suspicious)}"]
    for gap, seconds in sorted(suspicious, key=lambda item: item[1], reverse=True)[:max_samples]:
        lines.append(f"- {format_time(gap.start)} -> {format_time(gap.end)} gap={gap.end-gap.start:.1f}s vad_speech={seconds:.1f}s")
    return [*lines, ""]


def possible_japanese_text_left(entries: list[Entry], target_language: str = "zh-Hans") -> list[tuple[Entry, str]]:
    candidates: list[tuple[Entry, str]] = []
    for item in entries:
        if KANA_RE.search(item.text):
            candidates.append((item, "kana"))
        elif target_language == "zh-Hans" and NON_SIMPLIFIED_CJK_RE.search(item.text):
            candidates.append((item, "non_simplified_cjk"))
        elif target_language == "en" and CJK_RE.search(item.text):
            candidates.append((item, "cjk"))
    return candidates


def build_report(args: argparse.Namespace, metrics: dict | None = None) -> str:
    """Render the report text; when `metrics` is given, also fill it with the key
    numeric indicators so the caller can append them to a metrics history file."""
    if metrics is None:
        metrics = {}
    ja_input = load_subtitles(args.ja_srt)
    zh_input = load_subtitles(args.zh_srt)
    ja_entries = [Entry(c.index, c.start, c.end, c.text) for c in ja_input.cues]
    zh_entries = [Entry(c.index, c.start, c.end, c.text) for c in zh_input.cues]
    target_language = getattr(args, "target_language", "zh-Hans")
    qwen_metadata = load_json(getattr(args, "qwen_metadata", None))
    reference_args = getattr(args, "reference_srt", None) or []
    max_samples = getattr(args, "max_samples", 20)

    lines: list[str] = []
    lines.append("Subtitle quality report")
    lines.append("note: structural checks and model-reference agreement do not establish recognition or translation accuracy.")
    metrics.update(schema_version=2, evaluator_version="1.0", ja_entries=len(ja_entries), zh_entries=len(zh_entries),
                   ja_input=ja_input.summary(), target_input=zh_input.summary(), true_cer=None,
                   semantic_accuracy=None, legacy_reference_metrics="deprecated agreement hints; not accuracy")
    lines.append(f"ja_input_status: {ja_input.status}")
    lines.append(f"target_input_status: {zh_input.status}")
    for issue in ja_input.issues:
        lines.append(f"- ja input issue: {issue}")
    for issue in zh_input.issues:
        lines.append(f"- target input issue: {issue}")
    lines.append(f"ja_srt: {args.ja_srt}")
    if args.zh_srt:
        lines.append(f"target_srt: {args.zh_srt}")
    if args.audio:
        lines.append(f"audio: {args.audio}")
    lines.append("")

    if ja_entries:
        durations = [max(0.0, item.end - item.start) for item in ja_entries]
        chars = [len(compact_text(item.text)) for item in ja_entries]
        gaps = srt_gaps(ja_entries)
        display_total = sum(durations)
        display_union = sum(item.end - item.start for item in merge_intervals(
            [Interval(entry.start, entry.end) for entry in ja_entries]))
        span = max(item.end for item in ja_entries) - min(item.start for item in ja_entries)
        lines.append("[Japanese SRT]")
        lines.append(f"entries: {len(ja_entries)}")
        lines.append(f"display_total_min: {display_total / 60:.1f}")
        lines.append(f"display_union_s: {display_union:.2f}")
        lines.append(f"overlapping_display_s: {max(0.0, display_total - display_union):.2f}")
        lines.append(f"display_coverage_in_srt_span: {display_union / span:.1%}" if span > 0 else "display_coverage_in_srt_span: n/a")
        lines.append(f"duration_median_s: {percentile(durations, 0.5):.2f}")
        lines.append(f"duration_p95_s: {percentile(durations, 0.95):.2f}")
        lines.append(f"chars_median: {percentile(chars, 0.5):.1f}")
        lines.append(f"chars_p95: {percentile(chars, 0.95):.1f}")
        for length in (1, 2, 3, 5):
            count = sum(value <= length for value in chars)
            lines.append(f"chars_le_{length}: {count} ({count / len(chars):.1%})")
        metrics.update(
            ja_entries=len(ja_entries),
            display_total_min=round(display_total / 60, 1),
            display_union_s=display_union,
            overlapping_display_s=max(0.0, display_total - display_union),
            display_coverage_in_srt_span=display_union / span if span > 0 else None,
            duration_median_s=round(percentile(durations, 0.5), 2),
            chars_median=percentile(chars, 0.5),
            gaps_gt_10s=sum(item.end - item.start > 10 for item in gaps),
            gaps_gt_30s=sum(item.end - item.start > 30 for item in gaps),
        )
        lines.append(f"gaps_gt_10s: {sum(item.end - item.start > 10 for item in gaps)}")
        lines.append(f"gaps_gt_30s: {sum(item.end - item.start > 30 for item in gaps)}")
        lines.append(f"gaps_gt_60s_observational_only: {sum(item.end - item.start > 60 for item in gaps)}")
        if gaps:
            lines.append(f"gap_p95_s: {percentile([item.end - item.start for item in gaps], 0.95):.1f}")
            lines.append(f"gap_max_s: {max(item.end - item.start for item in gaps):.1f}")
        lines.append("")

    if ((args.audio and args.audio.exists()) or qwen_metadata) and ja_input.status in ("valid", "empty"):
        lines.extend(audio_gap_report(args, ja_entries, qwen_metadata, metrics, max_samples))

    if reference_args:
        reference_pad = getattr(args, "reference_pad_seconds", 4.0)
        reference_threshold = getattr(args, "reference_match_threshold", 0.34)
        reference_min_reading = getattr(args, "reference_min_reading_chars", 3)
        reference_data: list[tuple[str, list[Entry], list[tuple[Entry, set[str]]]]] = []
        for item in reference_args:
            name, path = parse_named_srt(item)
            entries = parse_srt(path)
            reference_data.append((name, entries, reference_segments(entries, reference_min_reading)))

        lines.append("[Reference-aware ASR comparison]")
        lines.append("note: legacy recall fields below are deprecated agreement hints, not accuracy or confirmed misses.")
        metrics["reference_comparisons"] = {}
        for named_path in reference_args:
            name, path = parse_named_srt(named_path)
            comparison = compare_subtitles(load_subtitles(path), ja_input,
                                           getattr(args, "reference_kind", "model_output"),
                                           boundaries_verified=getattr(args, "reference_boundaries_verified", False))
            metrics["reference_comparisons"][name] = comparison
            lines.append(f"{name}: evidence={comparison['reference_kind']} comparison_status={comparison['status']}")
            difference = comparison["text_difference"]
            if difference is not None:
                counts = difference["normalized"]
                lines.append(f"{name}: reference_text_difference S={counts['substitutions']} I={counts['insertions']} D={counts['deletions']} chars={counts['reference_chars']} rate={counts['rate']}")
            lines.append(f"{name}: true_cer={comparison['true_cer']}")
            for limitation in comparison["limitations"]:
                lines.append(f"- {name}: {limitation}")
        lines.append(
            f"reading_match_threshold: {reference_threshold} "
            f"pad_seconds: {reference_pad} min_reading_chars: {reference_min_reading}"
        )
        for name, entries, segments in reference_data:
            hit, total, missed = reference_recall(ja_entries, segments, reference_pad, reference_threshold)
            lines.append(f"{name}: recall={fmt_fraction(hit, total)} entries={len(entries)} scored_segments={total}")
            for entry in missed[:max_samples]:
                lines.append(f"- missed {name} {format_time(entry.start)} -> {format_time(entry.end)} {entry.text[:80]}")
            metrics[f"reference_{name}_recall"] = round(hit / total, 3) if total and ja_input.status in ("valid", "empty") else None
            metrics[f"reference_{name}_segments"] = total

        if len(reference_data) >= 2:
            base_name, _, base_segments = reference_data[0]
            other_refs = [entries for _, entries, _ in reference_data[1:]]
            consensus: list[tuple[Entry, set[str]]] = []
            for entry, bigrams in base_segments:
                confirmed = any(
                    reading_overlap(
                        bigrams,
                        window_reading_bigrams(ref_entries, entry.start, entry.end, reference_pad),
                    ) >= reference_threshold
                    for ref_entries in other_refs
                )
                if confirmed:
                    consensus.append((entry, bigrams))
            hit, total, missed = reference_recall(ja_entries, consensus, reference_pad, reference_threshold)
            lines.append(f"cross_reference_consensus_from_{base_name}: recall={fmt_fraction(hit, total)}")
            for entry in missed[:max_samples]:
                lines.append(f"- missed consensus {format_time(entry.start)} -> {format_time(entry.end)} {entry.text[:80]}")
            metrics["reference_consensus_recall"] = round(hit / total, 3) if total and ja_input.status in ("valid", "empty") else None
            metrics["reference_consensus_segments"] = total
        lines.append("")

    if zh_entries:
        lines.append(f"[Translated SRT: {target_language}]")
        lines.append(f"entries: {len(zh_entries)}")
        jp_left = [item for item in zh_entries if KANA_RE.search(item.text)]
        possible_jp_left = possible_japanese_text_left(zh_entries, target_language)
        lines.append(f"japanese_kana_left: {len(jp_left)}")
        lines.append(f"possible_japanese_or_traditional_left: {len(possible_jp_left)}")
        duplicate_candidates = adjacent_duplicate_candidates(ja_entries, zh_entries)
        confirmed_ids = {c.index for c in zh_entries for source in ja_entries
                         if c.index == source.index and abs(c.start - source.start) <= 0.25}
        metrics["translation_mapping"] = {"method": "ID plus source-start agreement (1:1 only)",
                                          "assessed_target_cues": len(confirmed_ids),
                                          "unresolved_target_cues": len(zh_entries) - len(confirmed_ids),
                                          "source_cues": len(ja_entries), "target_cues": len(zh_entries)}
        lines.append(f"translation_mapping_unresolved: {len(zh_entries) - len(confirmed_ids)}")
        lines.append("note: untranslated text and duplicate checks are hints; semantic accuracy requires contextual review.")
        metrics.update(
            zh_entries=len(zh_entries),
            kana_left=len(jp_left),
            possible_japanese_left=len(possible_jp_left),
            adjacent_duplicates=len(duplicate_candidates),
        )
        lines.append(f"suspicious_adjacent_duplicates: {len(duplicate_candidates)}")
        for item in duplicate_candidates[:max_samples]:
            lines.append(f"- {item}")
        for item in jp_left[:max_samples]:
            lines.append(f"- kana left at {item.index}: {item.text[:80]}")
        non_kana_candidates = [(item, reason) for item, reason in possible_jp_left if reason != "kana"]
        for item, reason in non_kana_candidates[:max_samples]:
            lines.append(f"- possible {reason} at {item.index}: {item.text[:80]}")
        lines.append("")

    if qwen_metadata:
        chunks = qwen_metadata.get("chunks", [])
        if not isinstance(chunks, list):
            chunks = []
        clip_seconds = 0.0
        model_seconds = 0.0
        empty_text_chunks = 0
        chunk_segments = 0
        for chunk in chunks:
            if not isinstance(chunk, dict):
                continue
            try:
                clip_seconds += max(0.0, float(chunk.get("end", 0.0)) - float(chunk.get("start", 0.0)))
            except (TypeError, ValueError):
                pass
            try:
                model_seconds += max(0.0, float(chunk.get("seconds", 0.0)))
            except (TypeError, ValueError):
                pass
            if not str(chunk.get("text", "") or "").strip():
                empty_text_chunks += 1
            try:
                chunk_segments += int(chunk.get("segments", 0) or 0)
            except (TypeError, ValueError):
                pass

        lines.append("[Qwen ASR Metadata]")
        lines.append(f"mode: {qwen_metadata.get('mode', 'n/a')}")
        lines.append(f"vad_chunks: {qwen_metadata.get('vad_chunks', 'n/a')}")
        if "vad_threshold" in qwen_metadata:
            lines.append(f"vad_threshold: {qwen_metadata.get('vad_threshold')}")
        lines.append(f"batch_size: {qwen_metadata.get('batch_size', 'n/a')}")
        lines.append(f"chunk_count: {len(chunks)}")
        if chunks:
            lines.append(f"empty_text_chunks: {empty_text_chunks}")
            lines.append(f"segments_from_chunks: {chunk_segments}")
            lines.append(f"clip_audio_total_min: {clip_seconds / 60.0:.1f}")
            if model_seconds > 0:
                lines.append(f"model_batch_time_total_min_approx: {model_seconds / 60.0:.1f}")
        if "elapsed_seconds" in qwen_metadata:
            lines.append(f"elapsed_min: {float(qwen_metadata['elapsed_seconds']) / 60.0:.1f}")
            metrics["asr_elapsed_min"] = round(float(qwen_metadata["elapsed_seconds"]) / 60.0, 1)
        lines.append(f"entries_after_postprocess: {qwen_metadata.get('entries', 'n/a')}")
        lines.append("")

    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    """Tuning knobs come from QualityReportConfig (single source of truth, shared with the
    orchestrator); only IO/per-run args are declared here."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--ja-srt", type=Path, required=True)
    parser.add_argument("--target-srt", "--zh-srt", dest="zh_srt", type=Path)
    parser.add_argument("--target-language", choices=("zh-Hans", "zh-Hant", "en"), default="zh-Hans")
    parser.add_argument("--audio", type=Path)
    parser.add_argument("--qwen-metadata", type=Path)
    parser.add_argument(
        "--reference-srt",
        action="append",
        help="Optional name=path reference SRT; model outputs default to provisional evidence; repeatable.",
    )
    parser.add_argument("--reference-kind", choices=("audio_verified", "context_reviewed", "model_output"), default="model_output")
    parser.add_argument("--reference-boundaries-verified", action="store_true", help="Only set for independently verified reference timing")
    parser.add_argument("--reference-pad-seconds", type=float, default=4.0)
    parser.add_argument("--reference-match-threshold", type=float, default=0.34)
    parser.add_argument("--reference-min-reading-chars", type=int, default=3)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--metrics-jsonl",
        type=Path,
        help="Append one JSON line of key metrics to this file (history across runs/videos)",
    )
    parser.add_argument(
        "--metrics-label",
        default="",
        help="Label for the metrics record; defaults to the ja SRT stem without .ja",
    )
    add_dataclass_arguments(parser, QualityReportConfig)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    raise_for_config_issues(
        validate_quality_config(config_from_namespace(args, QualityReportConfig))
    )

    metrics: dict = {}
    report = build_report(args, metrics)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report + "\n", encoding="utf-8")
    print(report)
    if args.metrics_jsonl:
        label = args.metrics_label or re.sub(r"\.ja$", "", args.ja_srt.stem)
        record = {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "label": label,
            **metrics,
        }
        args.metrics_jsonl.parent.mkdir(parents=True, exist_ok=True)
        with args.metrics_jsonl.open("a", encoding="utf-8") as file:
            file.write(json.dumps(record, ensure_ascii=False) + "\n")
        print(f"Metrics appended: {args.metrics_jsonl}")


if __name__ == "__main__":
    main()
