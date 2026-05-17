from __future__ import annotations

import argparse
from pathlib import Path

from faster_whisper import WhisperModel


PROJECT_ROOT = Path(__file__).resolve().parents[1] if Path(__file__).resolve().parent.name == "scripts" else Path(__file__).resolve().parent
DEFAULT_MODEL = PROJECT_ROOT / "models" / "faster-whisper-large-v3"


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(value, maximum))


def estimate_display_duration(text: str, min_duration: float, max_duration: float) -> float:
    compact = "".join(text.split())
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


def segment_entries(segment, min_duration: float, max_duration: float, max_chars: int) -> list[tuple[float, float, str]]:
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
    if not words:
        start, end = repaired_segment_times(segment, text, min_duration, max_duration)
        return [(start, end, text)]

    entries: list[tuple[float, float, str]] = []
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
        entries.append((chunk_start, end, chunk_text))
        chunk_words = []

    for word in words:
        current_text = word_text(word)
        word_start = float(word.start)
        word_end = float(word.end)
        next_text = "".join(word_text(item) for item in chunk_words) + current_text
        next_duration = word_end - chunk_start
        if chunk_words and (next_duration > max_duration or len(next_text) > max_chars):
            flush()
            chunk_start = word_start
        chunk_words.append(word)
        chunk_end = word_end

    flush()
    return entries


def srt_time(seconds: float) -> str:
    milliseconds = int(round(seconds * 1000))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"


def write_srt(segments, output_path: Path, min_duration: float, max_duration: float, max_chars: int) -> None:
    with output_path.open("w", encoding="utf-8") as f:
        index = 1
        for segment in segments:
            for start, end, text in segment_entries(segment, min_duration, max_duration, max_chars):
                f.write(f"{index}\n")
                f.write(f"{srt_time(start)} --> {srt_time(end)}\n")
                f.write(f"{text}\n\n")
                index += 1


def write_srt_stream(segments, output_path: Path, min_duration: float, max_duration: float, max_chars: int) -> None:
    with output_path.open("w", encoding="utf-8") as f:
        index = 1
        for segment in segments:
            for start, end, text in segment_entries(segment, min_duration, max_duration, max_chars):
                f.write(f"{index}\n")
                f.write(f"{srt_time(start)} --> {srt_time(end)}\n")
                f.write(f"{text}\n\n")
                f.flush()
                print(f"{index}: {srt_time(end)} {text[:40]}", flush=True)
                index += 1


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
    write_srt_stream(segments, args.output, args.min_duration, args.max_duration, args.max_chars)
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
