from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

from faster_whisper import WhisperModel


PROJECT_ROOT = Path(__file__).resolve().parents[1] if Path(__file__).resolve().parent.name == "scripts" else Path(__file__).resolve().parent
DEFAULT_MODEL = PROJECT_ROOT / "models" / "faster-whisper-large-v3"


@dataclass
class SubtitleEntry:
    start: float
    end: float
    text: str


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(value, maximum))


def compact_text(text: str) -> str:
    return "".join(text.split())


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


def word_timestamps_are_reliable(segment, words: list, max_word_gap: float) -> bool:
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

    words = [
        word
        for word in (getattr(segment, "words", None) or [])
        if word_text(word)
        and getattr(word, "start", None) is not None
        and getattr(word, "end", None) is not None
    ]
    if not word_timestamps_are_reliable(segment, words, max_word_gap):
        start, end = repaired_segment_times(segment, text, min_duration, max_duration)
        return [SubtitleEntry(start, end, text)]

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
        entries.append(SubtitleEntry(chunk_start, end, chunk_text))
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
            continue
        if (
            merged
            and len(compact_text(merged[-1].text)) <= 2
            and entry.start - merged[-1].end <= max_merge_gap
            and len(compact_text(merged[-1].text) + text) <= max_chars
        ):
            merged[-1].end = max(merged[-1].end, entry.end)
            merged[-1].text = merged[-1].text + entry.text
            continue
        merged.append(SubtitleEntry(entry.start, entry.end, entry.text))
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
    return merge_short_entries(entries, max_merge_gap, max_chars)


def srt_time(seconds: float) -> str:
    milliseconds = int(round(seconds * 1000))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"


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
    parser.add_argument("--vad-threshold", type=float, default=0.35)
    parser.add_argument("--vad-min-silence-ms", type=int, default=500)
    parser.add_argument("--vad-speech-pad-ms", type=int, default=400)
    parser.add_argument("--max-word-gap", type=float, default=6.0)
    parser.add_argument("--max-merge-gap", type=float, default=1.0)
    args = parser.parse_args()

    model = load_model(args.model)
    vad_parameters = None
    if not args.no_vad:
        vad_parameters = {
            "threshold": args.vad_threshold,
            "min_silence_duration_ms": args.vad_min_silence_ms,
            "speech_pad_ms": args.vad_speech_pad_ms,
        }
    segments, info = model.transcribe(
        str(args.audio),
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
    write_entries(entries, args.output)
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
