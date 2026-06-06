from __future__ import annotations

import argparse
import difflib
from dataclasses import dataclass
from pathlib import Path

from faster_whisper.audio import decode_audio
from faster_whisper import BatchedInferencePipeline, WhisperModel

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


PROJECT_ROOT = Path(__file__).resolve().parents[1] if Path(__file__).resolve().parent.name == "scripts" else Path(__file__).resolve().parent
DEFAULT_MODEL = PROJECT_ROOT / "models" / "faster-whisper-large-v3"


@dataclass
class SubtitleEntry:
    start: float
    end: float
    text: str
    avg_logprob: float | None = None
    no_speech_prob: float | None = None
    compression_ratio: float | None = None


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(value, maximum))


def estimate_display_duration(text: str, min_duration: float, max_duration: float) -> float:
    compact = compact_text(text)
    if not compact:
        return min_duration
    return clamp(len(compact) * 0.28, min_duration, max_duration)


def repaired_segment_times(segment, text: str, min_duration: float, max_duration: float) -> tuple[float, float]:
    start = float(segment.start)
    end = float(segment.end)
    words = getattr(segment, "words", None) or []
    word_starts = [float(word.start) for word in words if getattr(word, "start", None) is not None]
    word_ends = [float(word.end) for word in words if getattr(word, "end", None) is not None]
    if word_starts and word_ends:
        start = min(word_starts)
        end = max(word_ends)

    duration = max(0.0, end - start)
    if duration > max_duration:
        end = start + estimate_display_duration(text, min_duration, max_duration)
    elif duration < min_duration:
        end = start + min_duration
    return start, end


def word_text(word) -> str:
    return str(getattr(word, "word", "")).strip()


def word_timestamps_are_reliable(segment, words: list) -> bool:
    if not words:
        return False

    previous_end: float | None = None
    for word in words:
        start = float(word.start)
        end = float(word.end)
        if end < start:
            return False
        if previous_end is not None:
            if start < previous_end - 0.25:
                return False
        previous_end = end

    segment_start = float(segment.start)
    segment_end = float(segment.end)
    word_start = float(words[0].start)
    word_end = float(words[-1].end)
    if word_start < segment_start - 5.0 or word_end > segment_end + 5.0:
        return False
    return True


def segment_entries(
    segment,
    min_duration: float,
    max_duration: float,
    max_chars: int,
    max_word_gap: float,
) -> list[SubtitleEntry]:
    text = segment.text.strip()
    if not text:
        return []
    avg_logprob = getattr(segment, "avg_logprob", None)
    no_speech_prob = getattr(segment, "no_speech_prob", None)
    compression_ratio = getattr(segment, "compression_ratio", None)

    words = [
        word
        for word in (getattr(segment, "words", None) or [])
        if word_text(word)
        and getattr(word, "start", None) is not None
        and getattr(word, "end", None) is not None
    ]
    if not word_timestamps_are_reliable(segment, words):
        start, end = repaired_segment_times(segment, text, min_duration, max_duration)
        return [SubtitleEntry(start, end, text, avg_logprob, no_speech_prob, compression_ratio)]

    entries: list[SubtitleEntry] = []
    chunk_words: list = []
    chunk_start = float(words[0].start)
    chunk_end = chunk_start

    def flush() -> None:
        nonlocal chunk_words, chunk_start, chunk_end
        if not chunk_words:
            return
        chunk_text = "".join(word_text(word) for word in chunk_words).strip()
        if not chunk_text:
            chunk_words = []
            return
        end = max(chunk_end, chunk_start + min_duration)
        entries.append(SubtitleEntry(chunk_start, end, chunk_text, avg_logprob, no_speech_prob, compression_ratio))
        chunk_words = []

    for word in words:
        current_text = word_text(word)
        word_start = float(word.start)
        word_end = float(word.end)
        next_text = "".join(word_text(item) for item in chunk_words) + current_text
        next_duration = word_end - chunk_start
        gap = word_start - chunk_end
        if chunk_words and (gap > max_word_gap or next_duration > max_duration or len(next_text) > max_chars):
            flush()
            chunk_start = word_start
        chunk_words.append(word)
        chunk_end = word_end

    flush()
    return entries


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
        # Copy (carrying confidence) so merging never mutates the caller's entries.
        merged.append(
            SubtitleEntry(
                entry.start,
                entry.end,
                entry.text,
                entry.avg_logprob,
                entry.no_speech_prob,
                entry.compression_ratio,
            )
        )
    return merged


def is_sentence_ending(text: str) -> bool:
    return compact_text(text).endswith(("。", "！", "？", "!", "?", "…"))


def is_cjk_or_katakana(char: str) -> bool:
    return bool(
        "\u3400" <= char <= "\u9fff"
        or "\u30a0" <= char <= "\u30ff"
        or "\uff66" <= char <= "\uff9f"
    )


def starts_with_small_kana(text: str) -> bool:
    compact = compact_text(text)
    return bool(compact) and compact[0] in "ぁぃぅぇぉっゃゅょゎァィゥェォッャュョヮ"


def looks_like_orphan_prefix(text: str, next_text: str) -> bool:
    compact = compact_text(text)
    if len(compact) != 1 or is_sentence_ending(compact):
        return False
    return is_cjk_or_katakana(compact) or starts_with_small_kana(next_text)


def merge_orphan_prefix_entries(
    entries: list[SubtitleEntry],
    max_gap: float,
    max_duration: float,
    max_chars: int,
) -> list[SubtitleEntry]:
    if not entries:
        return []
    merged: list[SubtitleEntry] = []
    index = 0
    while index < len(entries):
        current = entries[index]
        if index + 1 >= len(entries):
            merged.append(current)
            break
        following = entries[index + 1]
        combined_text = current.text + following.text
        if (
            looks_like_orphan_prefix(current.text, following.text)
            and following.start - current.end <= max_gap
            and following.end - current.start <= max_duration
            and len(compact_text(combined_text)) <= max_chars
        ):
            merged_entry = SubtitleEntry(
                current.start,
                following.end,
                combined_text,
                current.avg_logprob,
                current.no_speech_prob,
                current.compression_ratio,
            )
            if following.avg_logprob is not None:
                merged_entry.avg_logprob = (
                    following.avg_logprob
                    if merged_entry.avg_logprob is None
                    else min(merged_entry.avg_logprob, following.avg_logprob)
                )
            if following.no_speech_prob is not None:
                merged_entry.no_speech_prob = (
                    following.no_speech_prob
                    if merged_entry.no_speech_prob is None
                    else max(merged_entry.no_speech_prob, following.no_speech_prob)
                )
            if following.compression_ratio is not None:
                merged_entry.compression_ratio = (
                    following.compression_ratio
                    if merged_entry.compression_ratio is None
                    else max(merged_entry.compression_ratio, following.compression_ratio)
                )
            merged.append(merged_entry)
            index += 2
            continue
        merged.append(current)
        index += 1
    return merged


def collect_entries(
    segments,
    min_duration: float,
    max_duration: float,
    max_chars: int,
    max_word_gap: float,
    max_merge_gap: float,
) -> list[SubtitleEntry]:
    entries: list[SubtitleEntry] = []
    for segment in segments:
        entries.extend(segment_entries(segment, min_duration, max_duration, max_chars, max_word_gap))
    entries = merge_short_entries(entries, max_merge_gap, max_chars)
    return merge_orphan_prefix_entries(entries, max_gap=10.0, max_duration=12.0, max_chars=max_chars)


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
    """Shared ASR text cleanup for raw Whisper outputs.

    This is intentionally independent of whether the entry came from the main pass
    or gap fill. Stage-specific checks such as overlap with existing subtitles are
    layered on by the caller.
    """
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


def filter_repeated_hallucination_entries(
    entries: list[SubtitleEntry],
    *,
    hallucination_min_repeats: int,
    hallucination_repeat_no_speech_prob: float,
    hallucination_repeat_avg_logprob: float,
    hallucination_high_risk_max_repeats: int,
) -> tuple[list[SubtitleEntry], list[SubtitleEntry]]:
    """Drop repeated ASR phrases that are statistically likely hallucinations."""
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


def filter_main_local_entries(
    entries: list[SubtitleEntry],
    args: argparse.Namespace,
) -> tuple[list[SubtitleEntry], list[SubtitleEntry]]:
    """Consolidated text filter for the sliding main pass."""
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
    """Drop the squeezed twin of a near-duplicate cue pair that overlapping clips produce.

    The exact-match dedup misses pairs that differ by only a comma or particle
    ("いやいや今選んでください" vs "いやいや、今選んでください"); resolve_overlaps then squeezes
    one of them to a flash. Only drop when the shorter twin is squeezed below
    squeeze_seconds, so genuinely repeated dialogue (気持ちいい / 気持ちいい? at normal
    durations) is left alone — only the flash artifact is removed."""
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
                    # Drop whichever twin is the squeezed flash; keep the fuller one.
                    if cur_dur < prev_dur:
                        continue
                    kept[-1] = entry
                    continue
        kept.append(entry)
    return kept


def resolve_overlaps(entries: list[SubtitleEntry]) -> list[SubtitleEntry]:
    """Sort entries and trim any overlap so each subtitle ends no later than the next starts.

    Trimming is skipped when two entries share a start time, to avoid creating a
    zero-duration cue."""
    ordered = sorted(entries, key=lambda item: (item.start, item.end))
    for previous, current in zip(ordered, ordered[1:]):
        if previous.end > current.start and current.start > previous.start:
            previous.end = current.start
    return ordered


def finalize_main_entries(entries: list[SubtitleEntry], args: argparse.Namespace) -> list[SubtitleEntry]:
    """Apply main-pass time-axis cleanup consistently across entry points."""
    entries = resolve_overlaps(entries)
    if args.near_dup_similarity > 0:
        before = len(entries)
        entries = drop_adjacent_near_duplicates(
            entries,
            args.near_dup_max_gap,
            args.near_dup_similarity,
            args.near_dup_squeeze_seconds,
        )
        if before != len(entries):
            print(f"Dropped {before - len(entries)} adjacent near-duplicate cues", flush=True)
    if args.min_cue_seconds > 0:
        # Overlapping clip-boundary cues get trimmed to near-zero by resolve_overlaps
        # and then flash by (long text, ~0.02s on screen) because the next cue leaves
        # no room for min-display to lengthen them. Drop those squeezed-out artifacts.
        before = len(entries)
        entries = [entry for entry in entries if entry.end - entry.start >= args.min_cue_seconds]
        if before != len(entries):
            print(f"Dropped {before - len(entries)} sub-{args.min_cue_seconds}s cues", flush=True)
    return entries


def write_entries(entries: list[SubtitleEntry], output_path: Path) -> None:
    with output_path.open("w", encoding="utf-8") as f:
        for index, entry in enumerate(entries, start=1):
            f.write(f"{index}\n")
            f.write(f"{srt_time(entry.start)} --> {srt_time(entry.end)}\n")
            f.write(f"{entry.text}\n\n")
            print(f"{index}: {srt_time(entry.end)} {entry.text[:40]}", flush=True)


def load_model(model_name_or_path: str) -> WhisperModel:
    try:
        return WhisperModel(model_name_or_path, device="cuda", compute_type="float16")
    except Exception as exc:
        network_markers = ("ConnectError", "Hub", "RemoteProtocolError", "Server disconnected")
        if any(marker in str(exc) for marker in network_markers):
            raise
        print(f"CUDA float16 unavailable, falling back to CPU int8: {exc}")
        return WhisperModel(model_name_or_path, device="cpu", compute_type="int8")


def speech_intervals_from_audio_window(
    audio,
    window: Interval,
    threshold: float,
    min_silence_ms: int,
    speech_pad_ms: int,
    sampling_rate: int = 16000,
) -> list[Interval]:
    from faster_whisper.vad import VadOptions, get_speech_timestamps

    start_sample = max(0, int(window.start * sampling_rate))
    end_sample = min(len(audio), int(window.end * sampling_rate))
    if end_sample <= start_sample:
        return []
    options = VadOptions(
        threshold=threshold,
        min_silence_duration_ms=min_silence_ms,
        speech_pad_ms=speech_pad_ms,
    )
    timestamps = get_speech_timestamps(audio[start_sample:end_sample], options, sampling_rate=sampling_rate)
    return [
        Interval(window.start + item["start"] / sampling_rate, window.start + item["end"] / sampling_rate)
        for item in timestamps
    ]


def sliding_windows(duration: float, window_seconds: float, overlap_seconds: float) -> list[Interval]:
    if window_seconds <= 0:
        raise ValueError("window_seconds must be positive")
    if overlap_seconds < 0:
        raise ValueError("overlap_seconds must be non-negative")
    if overlap_seconds >= window_seconds:
        raise ValueError("overlap_seconds must be smaller than window_seconds")
    if duration <= 0:
        return []

    windows: list[Interval] = []
    step = window_seconds - overlap_seconds
    start = 0.0
    while start < duration:
        end = min(duration, start + window_seconds)
        windows.append(Interval(start, end))
        if end >= duration:
            break
        start += step
    return windows


def speech_intervals_from_sliding_audio(
    audio,
    duration: float,
    threshold: float,
    min_silence_ms: int,
    speech_pad_ms: int,
    window_seconds: float,
    overlap_seconds: float,
) -> list[Interval]:
    speech_intervals: list[Interval] = []
    for window in sliding_windows(duration, window_seconds, overlap_seconds):
        speech_intervals.extend(
            speech_intervals_from_audio_window(
                audio,
                window,
                threshold,
                min_silence_ms,
                speech_pad_ms,
            )
        )
    return merge_intervals(speech_intervals)


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
    # Padding can push adjacent clusters into each other; re-merge so the same
    # audio is not transcribed twice.
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


def build_main_local_clips(
    audio,
    audio_duration: float,
    args: argparse.Namespace,
) -> tuple[list[Interval], list[Interval], list[Interval]]:
    """Run sliding VAD -> cluster -> pad -> split and return the selection stages."""
    speech_intervals = speech_intervals_from_sliding_audio(
        audio,
        audio_duration,
        args.main_local_vad_threshold,
        args.vad_min_silence_ms,
        args.vad_speech_pad_ms,
        args.main_local_vad_window_seconds,
        args.main_local_vad_window_overlap_seconds,
    )
    clusters = speech_clusters(
        speech_intervals,
        args.main_local_vad_max_cluster_gap,
        args.main_local_asr_pad_seconds,
        audio_duration,
    )
    # BatchedInferencePipeline transcribes each clip in one 30s Whisper window and
    # silently drops anything past 30s ("Segment N is longer than 30 seconds..."),
    # so never hand it a clip longer than that window.
    max_clip_seconds = min(args.main_local_asr_max_clip_seconds, 30.0)
    clips: list[Interval] = []
    for cluster in clusters:
        if cluster.end - cluster.start < args.main_local_min_clip_seconds:
            continue
        clips.extend(
            split_clip_with_overlap(
                cluster,
                max_clip_seconds,
                args.main_local_asr_overlap_seconds,
            )
        )
    return speech_intervals, clusters, clips


def _total_seconds(intervals: list[Interval]) -> float:
    return sum(item.end - item.start for item in intervals)


def report_main_local_vad_stats(
    audio_duration: float,
    speech_intervals: list[Interval],
    clusters: list[Interval],
    clips: list[Interval],
) -> None:
    speech_min = _total_seconds(speech_intervals) / 60.0
    cluster_min = _total_seconds(clusters) / 60.0
    clip_min = _total_seconds(clips) / 60.0
    covered_min = _total_seconds(merge_intervals(clips)) / 60.0
    coverage = (covered_min * 60.0 / audio_duration * 100.0) if audio_duration > 0 else 0.0
    overlap_factor = (clip_min / covered_min) if covered_min > 0 else 1.0
    print(
        "Main local VAD: "
        f"audio={audio_duration / 60.0:.1f}min "
        f"speech_intervals={len(speech_intervals)} ({speech_min:.1f}min) "
        f"clusters={len(clusters)} ({cluster_min:.1f}min) "
        f"clips={len(clips)} ({clip_min:.1f}min) "
        f"covered={covered_min:.1f}min coverage={coverage:.1f}% "
        f"overlap_factor={overlap_factor:.2f}",
        flush=True,
    )


def main_local_vad_dry_run(audio_path: Path, args: argparse.Namespace) -> None:
    audio = decode_audio(str(audio_path), sampling_rate=16000)
    audio_duration = len(audio) / 16000
    speech_intervals, clusters, clips = build_main_local_clips(audio, audio_duration, args)
    report_main_local_vad_stats(audio_duration, speech_intervals, clusters, clips)


def transcribe_clips_batched(model, audio, clips: list[Interval], args: argparse.Namespace) -> list[SubtitleEntry]:
    """Transcribe a list of speech clips in one batched pass.

    Shared by the sliding main pass and gap fill. clip_timestamps makes
    BatchedInferencePipeline transcribe only those regions (vad_filter is ignored)
    and return segment timestamps already in full-audio coordinates, so no per-clip
    loop or manual offset is needed. without_timestamps=False keeps Whisper's natural
    per-sentence segmentation (the batched default collapses each clip into one line)."""
    if not clips:
        return []
    batched = BatchedInferencePipeline(model)
    clip_timestamps = [{"start": clip.start, "end": clip.end} for clip in clips]
    segments, _ = batched.transcribe(
        audio,
        language=args.language,
        beam_size=5,
        vad_filter=False,
        clip_timestamps=clip_timestamps,
        word_timestamps=True,
        condition_on_previous_text=False,
        batch_size=args.main_local_batch_size,
        without_timestamps=False,
    )
    return collect_entries(
        segments,
        args.min_duration,
        args.max_duration,
        args.max_chars,
        args.max_word_gap,
        args.max_merge_gap,
    )


def transcribe_audio_with_sliding_vad(model, audio_path: Path, args: argparse.Namespace) -> list[SubtitleEntry]:
    audio = decode_audio(str(audio_path), sampling_rate=16000)
    audio_duration = len(audio) / 16000
    speech_intervals, clusters, clips = build_main_local_clips(audio, audio_duration, args)
    report_main_local_vad_stats(audio_duration, speech_intervals, clusters, clips)
    print(
        f"Main local VAD: transcribing {len(clips)} clips "
        f"(batched, batch_size={args.main_local_batch_size})",
        flush=True,
    )
    return transcribe_clips_batched(model, audio, clips, args)


def transcribe_audio(model, audio_path: Path, args: argparse.Namespace) -> list[SubtitleEntry]:
    entries = transcribe_audio_with_sliding_vad(model, audio_path, args)
    if getattr(args, "filter_hallucinations", True):
        entries, filtered = filter_main_local_entries(entries, args)
        if filtered:
            samples = ", ".join(entry.text[:24] for entry in filtered[:5])
            print(f"Filtered main-ASR hallucinations/noise: {len(filtered)} ({samples})", flush=True)
    return entries


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("audio", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", default=str(DEFAULT_MODEL))
    parser.add_argument("--language", default="ja")
    parser.add_argument("--min-duration", type=float, default=1.0)
    parser.add_argument("--max-duration", type=float, default=10.0)
    parser.add_argument("--max-chars", type=int, default=42)
    parser.add_argument("--vad-min-silence-ms", type=int, default=500)
    parser.add_argument("--vad-speech-pad-ms", type=int, default=400)
    parser.add_argument(
        "--main-local-vad-dry-run",
        action="store_true",
        help="Run sliding VAD selection only, print coverage stats, and exit (no Whisper)",
    )
    parser.add_argument("--main-local-vad-threshold", type=float, default=0.5)
    parser.add_argument("--main-local-vad-window-seconds", type=float, default=8.0)
    parser.add_argument("--main-local-vad-window-overlap-seconds", type=float, default=4.0)
    parser.add_argument("--main-local-vad-max-cluster-gap", type=float, default=2.0)
    parser.add_argument("--main-local-asr-pad-seconds", type=float, default=0.3)
    parser.add_argument("--main-local-asr-max-clip-seconds", type=float, default=30.0)
    parser.add_argument("--main-local-asr-overlap-seconds", type=float, default=5.0)
    parser.add_argument("--main-local-min-clip-seconds", type=float, default=0.6)
    parser.add_argument("--main-local-batch-size", type=int, default=24)
    # Consolidated main-pass cleaning (so the sliding pass can replace main+gap-fill).
    parser.add_argument("--main-min-chars", type=int, default=1)
    parser.add_argument("--main-max-compression-ratio", type=float, default=25.0)
    parser.add_argument("--main-duplicate-window-seconds", type=float, default=2.0)
    parser.add_argument("--hallucination-min-repeats", type=int, default=10)
    parser.add_argument("--hallucination-repeat-no-speech-prob", type=float, default=0.75)
    parser.add_argument("--hallucination-repeat-avg-logprob", type=float, default=-0.80)
    parser.add_argument("--hallucination-high-risk-max-repeats", type=int, default=3)
    parser.add_argument("--min-cue-seconds", type=float, default=0.3)
    parser.add_argument("--near-dup-max-gap", type=float, default=0.5)
    parser.add_argument("--near-dup-similarity", type=float, default=0.6)
    parser.add_argument("--near-dup-squeeze-seconds", type=float, default=0.8)
    parser.add_argument("--max-word-gap", type=float, default=6.0)
    parser.add_argument("--max-merge-gap", type=float, default=1.0)
    parser.add_argument(
        "--no-hallucination-filter",
        dest="filter_hallucinations",
        action="store_false",
        help="Disable first-pass ASR filtering for clear platform/symbol hallucinations.",
    )
    parser.set_defaults(filter_hallucinations=True)
    args = parser.parse_args()
    if args.main_local_vad_window_overlap_seconds >= args.main_local_vad_window_seconds:
        raise SystemExit("--main-local-vad-window-overlap-seconds must be smaller than --main-local-vad-window-seconds")
    if args.main_local_asr_overlap_seconds >= min(args.main_local_asr_max_clip_seconds, 30.0):
        raise SystemExit("--main-local-asr-overlap-seconds must be smaller than the effective main ASR clip length")

    if args.main_local_vad_dry_run:
        main_local_vad_dry_run(args.audio, args)
        return

    model = load_model(args.model)
    entries = transcribe_audio(model, args.audio, args)
    entries = finalize_main_entries(entries, args)
    write_entries(entries, args.output)
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
