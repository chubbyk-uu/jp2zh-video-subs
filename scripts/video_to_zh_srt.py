from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1] if Path(__file__).resolve().parent.name == "scripts" else Path(__file__).resolve().parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
TRANSCRIBE_SCRIPT = SCRIPTS_DIR / "transcribe_ja_srt.py"
TRANSLATE_SCRIPT = SCRIPTS_DIR / "translate_srt_hymt.py"
WHISPER_MODEL = PROJECT_ROOT / "models" / "faster-whisper-large-v3"
TRANSLATE_MODEL = PROJECT_ROOT / "models" / "HY-MT1.5-7B-GGUF" / "HY-MT1.5-7B-Q4_K_M.gguf"


def run(command: list[str]) -> None:
    print("+ " + " ".join(command), flush=True)
    subprocess.run(command, check=True)


def require_file(path: Path, label: str) -> None:
    if not path.exists():
        raise SystemExit(f"Missing {label}: {path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate Chinese SRT subtitles from a Japanese video.")
    parser.add_argument("video", type=Path, help="Input video path")
    parser.add_argument("--output", type=Path, help="Output Chinese SRT path")
    parser.add_argument("--work-dir", type=Path, default=PROJECT_ROOT / "work")
    parser.add_argument("--keep-audio", action="store_true", help="Keep extracted WAV audio")
    parser.add_argument("--context-size", type=int, default=2)
    parser.add_argument("--language", default="ja")
    parser.add_argument("--condition-on-previous-text", action="store_true")
    parser.add_argument("--min-duration", type=float, default=1.0)
    parser.add_argument("--max-duration", type=float, default=10.0)
    parser.add_argument("--max-chars", type=int, default=42)
    parser.add_argument("--no-vad", action="store_true")
    parser.add_argument("--vad-threshold", type=float, default=0.35)
    parser.add_argument("--vad-min-silence-ms", type=int, default=500)
    parser.add_argument("--vad-speech-pad-ms", type=int, default=400)
    parser.add_argument(
        "--no-copy-to-video-dir",
        action="store_true",
        help="Do not copy the final Chinese SRT next to the input video",
    )
    args = parser.parse_args()

    video = args.video.resolve()
    require_file(video, "input video")
    require_file(WHISPER_MODEL / "model.bin", "Whisper model")
    require_file(TRANSLATE_MODEL, "HY-MT model")
    require_file(TRANSCRIBE_SCRIPT, "transcription script")
    require_file(TRANSLATE_SCRIPT, "translation script")

    output = args.output or (PROJECT_ROOT / "outputs" / f"{video.stem}.zh.srt")
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    job_dir = (args.work_dir / video.stem).resolve()
    job_dir.mkdir(parents=True, exist_ok=True)
    audio = job_dir / f"{video.stem}.wav"
    ja_srt = job_dir / f"{video.stem}.ja.srt"

    run([
        "ffmpeg",
        "-y",
        "-i",
        str(video),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        str(audio),
    ])
    transcribe_command = [
        sys.executable,
        str(TRANSCRIBE_SCRIPT),
        str(audio),
        "--output",
        str(ja_srt),
        "--model",
        str(WHISPER_MODEL),
        "--language",
        args.language,
        "--min-duration",
        str(args.min_duration),
        "--max-duration",
        str(args.max_duration),
        "--max-chars",
        str(args.max_chars),
        "--vad-threshold",
        str(args.vad_threshold),
        "--vad-min-silence-ms",
        str(args.vad_min_silence_ms),
        "--vad-speech-pad-ms",
        str(args.vad_speech_pad_ms),
    ]
    if args.condition_on_previous_text:
        transcribe_command.append("--condition-on-previous-text")
    if args.no_vad:
        transcribe_command.append("--no-vad")
    run(transcribe_command)
    run([
        sys.executable,
        str(TRANSLATE_SCRIPT),
        str(ja_srt),
        "--output",
        str(output),
        "--model-path",
        str(TRANSLATE_MODEL),
        "--context-size",
        str(args.context_size),
    ])

    if not args.keep_audio:
        audio.unlink(missing_ok=True)

    copied_output = video.parent / output.name
    if not args.no_copy_to_video_dir and copied_output != output:
        shutil.copy2(output, copied_output)

    print(f"Wrote {output}")
    if not args.no_copy_to_video_dir:
        print(f"Chinese SRT next to video: {copied_output}")
    print(f"Intermediate Japanese SRT: {ja_srt}")


if __name__ == "__main__":
    main()
