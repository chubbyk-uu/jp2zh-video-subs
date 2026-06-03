from __future__ import annotations

import argparse
import queue
import shutil
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[1] if Path(__file__).resolve().parent.name == "scripts" else Path(__file__).resolve().parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
TRANSCRIBE_SCRIPT = SCRIPTS_DIR / "transcribe_ja_srt.py"
TRANSLATE_SCRIPT = SCRIPTS_DIR / "translate_srt_hymt.py"
QUALITY_REPORT_SCRIPT = SCRIPTS_DIR / "quality_report.py"
FILL_GAPS_SCRIPT = SCRIPTS_DIR / "fill_ja_srt_gaps.py"
BILINGUAL_SCRIPT = SCRIPTS_DIR / "make_bilingual_ass.py"
WHISPER_MODEL = PROJECT_ROOT / "models" / "faster-whisper-large-v3"
TRANSLATE_MODEL = PROJECT_ROOT / "models" / "HY-MT1.5-7B-GGUF" / "HY-MT1.5-7B-Q4_K_M.gguf"
VIDEO_EXTENSIONS = {
    ".mp4",
    ".mkv",
    ".mov",
    ".avi",
    ".wmv",
    ".flv",
    ".webm",
    ".m4v",
    ".ts",
}


def run(command: list[str]) -> None:
    print("+ " + " ".join(command), flush=True)
    subprocess.run(command, check=True)


def require_file(path: Path, label: str) -> None:
    if not path.exists():
        raise SystemExit(f"Missing {label}: {path}")


@dataclass
class VideoJob:
    index: int
    video: Path
    output: Path
    job_dir: Path
    audio: Path


def extract_audio(video: Path, audio: Path) -> None:
    audio.parent.mkdir(parents=True, exist_ok=True)
    run(["ffmpeg", "-y", "-i", str(video), "-vn", "-ac", "1", "-ar", "16000", str(audio)])


def run_pipeline(
    jobs: Iterable[VideoJob],
    extract: Callable[[VideoJob], None],
    process: Callable[[VideoJob], None],
    continue_on_error: bool,
) -> list[tuple[VideoJob, Exception]]:
    """Extract audio one video ahead in a background thread while the GPU stages run.

    Audio extraction is CPU/IO bound and the GPU stages are GPU bound, so a single
    serial extractor running one step ahead hides extraction behind the recognition
    and translation of the previous video. The bounded queue (maxsize=1) provides
    backpressure so at most a couple of WAVs exist at once."""
    work_queue: queue.Queue = queue.Queue(maxsize=1)
    done = object()

    def producer() -> None:
        for job in jobs:
            try:
                extract(job)
                work_queue.put((job, None))
            except Exception as exc:  # noqa: BLE001 - reported to the consumer
                work_queue.put((job, exc))
        work_queue.put(done)

    thread = threading.Thread(target=producer, daemon=True)
    thread.start()

    failures: list[tuple[VideoJob, Exception]] = []
    while True:
        item = work_queue.get()
        if item is done:
            break
        job, exc = item
        if exc is not None:
            if not continue_on_error:
                raise exc
            failures.append((job, exc))
            continue
        try:
            process(job)
        except Exception as exc:  # noqa: BLE001
            if not continue_on_error:
                raise
            failures.append((job, exc))
    thread.join()
    return failures


def is_video_file(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS


def discover_videos(input_path: Path, recursive: bool) -> list[Path]:
    if input_path.is_file():
        if not is_video_file(input_path):
            raise SystemExit(f"Input file is not a supported video: {input_path}")
        return [input_path]
    if not input_path.is_dir():
        raise SystemExit(f"Missing input video or directory: {input_path}")

    iterator = input_path.rglob("*") if recursive else input_path.iterdir()
    return sorted((path.resolve() for path in iterator if is_video_file(path)), key=lambda item: str(item).lower())


def output_path_for(video: Path, input_path: Path, output_dir: Path, recursive: bool) -> Path:
    if input_path.is_dir():
        if recursive:
            relative = video.relative_to(input_path).with_suffix(".zh.srt")
            return (output_dir / relative).resolve()
        return (output_dir / f"{video.stem}.zh.srt").resolve()
    return (output_dir / f"{video.stem}.zh.srt").resolve()


def work_dir_for(video: Path, input_path: Path, work_dir: Path, recursive: bool) -> Path:
    if input_path.is_dir() and recursive:
        relative = video.relative_to(input_path).with_suffix("")
        return (work_dir / relative).resolve()
    return (work_dir / video.stem).resolve()


def process_video(args: argparse.Namespace, video: Path, output: Path, job_dir: Path, audio: Path) -> None:
    print(f"\n==> Processing {video}", flush=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    job_dir.mkdir(parents=True, exist_ok=True)
    ja_srt = job_dir / f"{video.stem}.ja.srt"
    translate_input_srt = ja_srt

    if args.skip_gap_fill:
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
            "--max-word-gap",
            str(args.max_word_gap),
            "--max-merge-gap",
            str(args.max_merge_gap),
        ]
        if args.condition_on_previous_text:
            transcribe_command.append("--condition-on-previous-text")
        if args.no_vad:
            transcribe_command.append("--no-vad")
        run(transcribe_command)
    else:
        # Transcribe and gap-fill share one loaded Whisper model in a single process.
        filled_ja_srt = job_dir / f"{video.stem}.filled.ja.srt"
        fills_srt = job_dir / f"{video.stem}.fills.ja.srt"
        fill_command = [
            sys.executable,
            str(FILL_GAPS_SCRIPT),
            "--audio",
            str(audio),
            "--transcribe-output",
            str(ja_srt),
            "--output",
            str(filled_ja_srt),
            "--fills-output",
            str(fills_srt),
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
            "--max-word-gap",
            str(args.max_word_gap),
            "--max-merge-gap",
            str(args.max_merge_gap),
            "--vad-threshold",
            str(args.vad_threshold),
            "--vad-min-silence-ms",
            str(args.vad_min_silence_ms),
            "--vad-speech-pad-ms",
            str(args.vad_speech_pad_ms),
            "--min-gap-seconds",
            str(args.fill_min_gap_seconds),
            "--min-speech-seconds",
            str(args.fill_min_speech_seconds),
            "--max-clip-seconds",
            str(args.fill_max_clip_seconds),
            "--min-fill-chars",
            str(args.fill_min_chars),
        ]
        if args.condition_on_previous_text:
            fill_command.append("--condition-on-previous-text")
        if args.no_vad:
            fill_command.append("--no-vad")
        run(fill_command)
        translate_input_srt = filled_ja_srt

    translate_command = [
        sys.executable,
        str(TRANSLATE_SCRIPT),
        str(translate_input_srt),
        "--output",
        str(output),
        "--model-path",
        str(TRANSLATE_MODEL),
        "--context-size",
        str(args.context_size),
    ]
    run(translate_command)

    bilingual_output: Path | None = None
    if args.bilingual:
        bilingual_output = output.with_suffix(".ass")
        run([
            sys.executable,
            str(BILINGUAL_SCRIPT),
            "--zh-srt",
            str(output),
            "--ja-srt",
            str(translate_input_srt),
            "--output",
            str(bilingual_output),
            "--zh-font-size",
            str(args.bilingual_zh_font_size),
            "--ja-font-size",
            str(args.bilingual_ja_font_size),
            "--zh-colour",
            args.bilingual_zh_colour,
            "--ja-colour",
            args.bilingual_ja_colour,
        ])

    if not args.skip_quality_report:
        report_path = job_dir / f"{video.stem}.quality.txt"
        quality_command = [
            sys.executable,
            str(QUALITY_REPORT_SCRIPT),
            "--ja-srt",
            str(translate_input_srt),
            "--zh-srt",
            str(output),
            "--audio",
            str(audio),
            "--output",
            str(report_path),
            "--vad-threshold",
            str(args.vad_threshold),
            "--vad-min-silence-ms",
            str(args.vad_min_silence_ms),
            "--vad-speech-pad-ms",
            str(args.vad_speech_pad_ms),
        ]
        run(quality_command)
        print(f"Quality report: {report_path}")

    if args.delete_audio:
        audio.unlink(missing_ok=True)

    # In bilingual mode only the ASS is placed next to the video; otherwise the SRT is.
    copied_to_video: Path | None = None
    if not args.no_copy_to_video_dir:
        source = bilingual_output if bilingual_output is not None else output
        destination = video.parent / source.name
        if destination != source:
            shutil.copy2(source, destination)
        copied_to_video = destination

    print(f"Wrote {output}")
    if bilingual_output is not None:
        print(f"Bilingual ASS: {bilingual_output}")
    if copied_to_video is not None:
        label = "Bilingual ASS" if bilingual_output is not None else "Chinese SRT"
        print(f"{label} next to video: {copied_to_video}")
    print(f"Intermediate Japanese SRT: {ja_srt}")
    if translate_input_srt != ja_srt:
        print(f"Gap-filled Japanese SRT: {translate_input_srt}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate Chinese SRT subtitles from Japanese videos.")
    parser.add_argument("input", type=Path, help="Input video path or directory")
    parser.add_argument("--output", type=Path, help="Output Chinese SRT path for a single input video")
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "outputs", help="Output directory")
    parser.add_argument("--work-dir", type=Path, default=PROJECT_ROOT / "work")
    parser.add_argument("--recursive", action="store_true", help="Process videos in subdirectories")
    parser.add_argument("--continue-on-error", action="store_true", help="Continue batch processing after a video fails")
    parser.add_argument("--keep-audio", action="store_true", help="Deprecated: audio is kept by default")
    parser.add_argument("--delete-audio", action="store_true", help="Delete extracted WAV audio after processing")
    parser.add_argument("--skip-quality-report", action="store_true", help="Do not write a quality report")
    parser.add_argument("--skip-gap-fill", action="store_true", help="Do not run the audio-aware gap fill stage")
    parser.add_argument(
        "--bilingual",
        action="store_true",
        help="Also write a bilingual ASS (Chinese on top, Japanese below) next to the Chinese SRT",
    )
    parser.add_argument("--bilingual-zh-font-size", type=int, default=36)
    parser.add_argument("--bilingual-ja-font-size", type=int, default=24)
    parser.add_argument("--bilingual-zh-colour", default="&H0000FFFF", help="ASS colour &HAABBGGRR for the Chinese line")
    parser.add_argument("--bilingual-ja-colour", default="&H00B4B4B4", help="ASS colour &HAABBGGRR for the Japanese line")
    parser.add_argument("--context-size", type=int, default=1)
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
    parser.add_argument("--fill-min-gap-seconds", type=float, default=10.0)
    parser.add_argument("--fill-min-speech-seconds", type=float, default=4.0)
    parser.add_argument("--fill-max-clip-seconds", type=float, default=45.0)
    parser.add_argument("--fill-min-chars", type=int, default=3)
    parser.add_argument(
        "--no-copy-to-video-dir",
        action="store_true",
        help="Do not copy the final Chinese SRT next to the input video",
    )
    args = parser.parse_args()

    if args.keep_audio:
        print("Warning: --keep-audio is deprecated and has no effect (audio is kept by default).", flush=True)

    if shutil.which("ffmpeg") is None:
        raise SystemExit("Missing ffmpeg on PATH; install it (e.g. sudo apt install ffmpeg).")

    require_file(WHISPER_MODEL / "model.bin", "Whisper model")
    require_file(TRANSLATE_MODEL, "HY-MT model")
    require_file(TRANSCRIBE_SCRIPT, "transcription script")
    require_file(TRANSLATE_SCRIPT, "translation script")
    require_file(QUALITY_REPORT_SCRIPT, "quality report script")
    require_file(FILL_GAPS_SCRIPT, "gap fill script")
    if args.bilingual:
        require_file(BILINGUAL_SCRIPT, "bilingual ASS script")

    input_path = args.input.resolve()
    videos = discover_videos(input_path, args.recursive)
    if not videos:
        raise SystemExit(f"No supported videos found in: {input_path}")
    if input_path.is_dir() and args.output:
        raise SystemExit("Use --output-dir for directory input; --output is only for a single video.")

    # Smallest first: extraction time scales with file size, so the smallest video
    # minimizes the unavoidable wait before the GPU can start on the first one.
    videos.sort(key=lambda item: item.stat().st_size)

    jobs: list[VideoJob] = []
    for index, video in enumerate(videos, start=1):
        output = args.output.resolve() if args.output else output_path_for(video, input_path, args.output_dir, args.recursive)
        job_dir = work_dir_for(video, input_path, args.work_dir, args.recursive)
        jobs.append(VideoJob(index, video, output, job_dir, job_dir / f"{video.stem}.wav"))

    total = len(jobs)

    def extract(job: VideoJob) -> None:
        extract_audio(job.video, job.audio)

    def process(job: VideoJob) -> None:
        print(f"\n[{job.index}/{total}]", flush=True)
        process_video(args, job.video, job.output, job.job_dir, job.audio)

    failures = run_pipeline(jobs, extract, process, args.continue_on_error)
    failed = [(job.video, str(exc)) for job, exc in failures]
    for video, error in failed:
        print(f"Failed {video}: {error}", flush=True)

    if failed:
        print("\nFailed videos:")
        for video, error in failed:
            print(f"- {video}: {error}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
