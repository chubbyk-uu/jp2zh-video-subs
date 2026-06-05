from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

from faster_whisper import WhisperModel

from hallucination_filters import is_high_risk_repeat_phrase, looks_like_hallucination
from srt_utils import compact_text, srt_time


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


def resolve_overlaps(entries: list[SubtitleEntry]) -> list[SubtitleEntry]:
    """Sort entries and trim any overlap so each subtitle ends no later than the next starts.

    Trimming is skipped when two entries share a start time, to avoid creating a
    zero-duration cue."""
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


def load_model(model_name_or_path: str) -> WhisperModel:
    try:
        return WhisperModel(model_name_or_path, device="cuda", compute_type="float16")
    except Exception as exc:
        network_markers = ("ConnectError", "Hub", "RemoteProtocolError", "Server disconnected")
        if any(marker in str(exc) for marker in network_markers):
            raise
        print(f"CUDA float16 unavailable, falling back to CPU int8: {exc}")
        return WhisperModel(model_name_or_path, device="cpu", compute_type="int8")


def transcribe_audio(model, audio_path: Path, args: argparse.Namespace) -> list[SubtitleEntry]:
    vad_parameters = None
    if not args.no_vad:
        vad_parameters = {
            "threshold": args.vad_threshold,
            "min_silence_duration_ms": args.vad_min_silence_ms,
            "speech_pad_ms": args.vad_speech_pad_ms,
        }
    segments, info = model.transcribe(
        str(audio_path),
        language=args.language,
        beam_size=5,
        vad_filter=not args.no_vad,
        vad_parameters=vad_parameters,
        word_timestamps=True,
        condition_on_previous_text=args.condition_on_previous_text,
    )
    print(f"Detected language: {info.language} ({info.language_probability:.2f})")
    entries = collect_entries(
        segments,
        args.min_duration,
        args.max_duration,
        args.max_chars,
        args.max_word_gap,
        args.max_merge_gap,
    )
    if getattr(args, "filter_hallucinations", True):
        entries, filtered = filter_hallucination_entries(entries)
        if filtered:
            samples = ", ".join(entry.text[:24] for entry in filtered[:5])
            print(f"Filtered main-ASR hallucinations: {len(filtered)} ({samples})", flush=True)
    return entries


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("audio", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", default=str(DEFAULT_MODEL))
    parser.add_argument("--language", default="ja")
    parser.add_argument("--condition-on-previous-text", action="store_true")
    parser.add_argument("--min-duration", type=float, default=1.0)
    parser.add_argument("--max-duration", type=float, default=10.0)
    parser.add_argument("--max-chars", type=int, default=42)
    parser.add_argument("--no-vad", action="store_true")
    parser.add_argument("--vad-threshold", type=float, default=0.05)
    parser.add_argument("--vad-min-silence-ms", type=int, default=500)
    parser.add_argument("--vad-speech-pad-ms", type=int, default=400)
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

    model = load_model(args.model)
    entries = transcribe_audio(model, args.audio, args)
    write_entries(resolve_overlaps(entries), args.output)
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
