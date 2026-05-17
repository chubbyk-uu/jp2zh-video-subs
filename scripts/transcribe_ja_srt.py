from __future__ import annotations

import argparse
from pathlib import Path

from faster_whisper import WhisperModel


PROJECT_ROOT = Path(__file__).resolve().parents[1] if Path(__file__).resolve().parent.name == "scripts" else Path(__file__).resolve().parent
DEFAULT_MODEL = PROJECT_ROOT / "models" / "faster-whisper-large-v3"


def srt_time(seconds: float) -> str:
    milliseconds = int(round(seconds * 1000))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"


def write_srt(segments, output_path: Path) -> None:
    with output_path.open("w", encoding="utf-8") as f:
        for index, segment in enumerate(segments, start=1):
            text = segment.text.strip()
            if not text:
                continue
            f.write(f"{index}\n")
            f.write(f"{srt_time(segment.start)} --> {srt_time(segment.end)}\n")
            f.write(f"{text}\n\n")


def write_srt_stream(segments, output_path: Path) -> None:
    with output_path.open("w", encoding="utf-8") as f:
        for index, segment in enumerate(segments, start=1):
            text = segment.text.strip()
            if not text:
                continue
            f.write(f"{index}\n")
            f.write(f"{srt_time(segment.start)} --> {srt_time(segment.end)}\n")
            f.write(f"{text}\n\n")
            f.flush()
            print(f"{index}: {srt_time(segment.end)} {text[:40]}", flush=True)


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
    args = parser.parse_args()

    model = load_model(args.model)
    segments, info = model.transcribe(
        str(args.audio),
        language="ja",
        beam_size=5,
        vad_filter=True,
        condition_on_previous_text=True,
    )
    print(f"Detected language: {info.language} ({info.language_probability:.2f})")
    write_srt_stream(segments, args.output)
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
