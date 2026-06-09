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
QWEN_TRANSCRIBE_SCRIPT = SCRIPTS_DIR / "transcribe_ja_srt_qwen.py"
TRANSLATE_SCRIPT = SCRIPTS_DIR / "translate_srt_hymt.py"
QUALITY_REPORT_SCRIPT = SCRIPTS_DIR / "quality_report.py"
FILL_GAPS_SCRIPT = SCRIPTS_DIR / "fill_ja_srt_gaps.py"
BILINGUAL_SCRIPT = SCRIPTS_DIR / "make_bilingual_ass.py"
WHISPER_MODEL = PROJECT_ROOT / "models" / "faster-whisper-large-v3"
QWEN_ASR_MODEL = PROJECT_ROOT / "models" / "Qwen3-ASR-1.7B"
QWEN_ALIGNER_MODEL = PROJECT_ROOT / "models" / "Qwen3-ForcedAligner-0.6B"
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
    backpressure: the extractor runs at most one unprocessed video ahead (it blocks
    on put once the slot is full). It does not delete WAVs; whether they accumulate
    on disk depends on the caller's --delete-audio handling."""
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

    if args.asr == "qwen":
        # Qwen3-ASR full-coverage sliding pass: no VAD gate, no gap fill, minimal
        # post-processing (it rarely fabricates, so Whisper-style filters are off).
        transcribe_command = [
            sys.executable,
            str(QWEN_TRANSCRIBE_SCRIPT),
            str(audio),
            str(ja_srt),
            "--model",
            str(QWEN_ASR_MODEL),
            "--forced-aligner",
            str(QWEN_ALIGNER_MODEL),
            "--language",
            "Japanese" if args.language == "ja" else args.language,
            "--batch-size",
            str(args.qwen_batch_size),
            "--chunk-seconds",
            str(args.qwen_chunk_seconds),
            "--chunk-overlap-seconds",
            str(args.qwen_chunk_overlap_seconds),
            "--phrase-max-chars",
            str(args.qwen_phrase_max_chars),
            "--phrase-max-duration",
            str(args.qwen_phrase_max_duration),
            "--phrase-max-internal-gap",
            str(args.qwen_phrase_max_internal_gap),
            "--phrase-max-char-seconds",
            str(args.qwen_phrase_max_char_seconds),
            "--min-cue-seconds",
            str(args.min_cue_seconds),
        ]
        if args.qwen_filter_hallucinations:
            transcribe_command.append("--filter-hallucinations")
        if args.qwen_vad_chunks:
            transcribe_command += [
                "--vad-chunks",
                "--vad-threshold",
                str(args.qwen_vad_threshold),
                "--vad-max-cluster-gap",
                str(args.qwen_vad_max_cluster_gap),
            ]
        run(transcribe_command)
    elif not args.gap_fill:
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
            "--vad-min-silence-ms",
            str(args.vad_min_silence_ms),
            "--vad-speech-pad-ms",
            str(args.vad_speech_pad_ms),
            "--main-local-vad-threshold",
            str(args.main_local_vad_threshold),
            "--main-local-vad-window-seconds",
            str(args.main_local_vad_window_seconds),
            "--main-local-vad-window-overlap-seconds",
            str(args.main_local_vad_window_overlap_seconds),
            "--main-local-vad-max-cluster-gap",
            str(args.main_local_vad_max_cluster_gap),
            "--main-local-asr-pad-seconds",
            str(args.main_local_asr_pad_seconds),
            "--main-local-asr-max-clip-seconds",
            str(args.main_local_asr_max_clip_seconds),
            "--main-local-asr-overlap-seconds",
            str(args.main_local_asr_overlap_seconds),
            "--main-local-min-clip-seconds",
            str(args.main_local_min_clip_seconds),
            "--main-local-batch-size",
            str(args.main_local_batch_size),
            "--main-min-chars",
            str(args.main_min_chars),
            "--main-max-compression-ratio",
            str(args.max_fill_compression_ratio),
            "--main-duplicate-window-seconds",
            str(args.main_duplicate_window_seconds),
            "--min-cue-seconds",
            str(args.min_cue_seconds),
            "--near-dup-max-gap",
            str(args.near_dup_max_gap),
            "--near-dup-similarity",
            str(args.near_dup_similarity),
            "--near-dup-squeeze-seconds",
            str(args.near_dup_squeeze_seconds),
            "--hallucination-min-repeats",
            str(args.hallucination_min_repeats),
            "--hallucination-repeat-no-speech-prob",
            str(args.hallucination_repeat_no_speech_prob),
            "--hallucination-repeat-avg-logprob",
            str(args.hallucination_repeat_avg_logprob),
            "--hallucination-high-risk-max-repeats",
            str(args.hallucination_high_risk_max_repeats),
            "--max-word-gap",
            str(args.max_word_gap),
            "--max-merge-gap",
            str(args.max_merge_gap),
        ]
        run(transcribe_command)
    else:
        # Transcribe and gap-fill share one loaded Whisper model in a single process.
        filled_ja_srt = job_dir / f"{video.stem}.filled.ja.srt"
        fills_srt = job_dir / f"{video.stem}.fills.ja.srt"
        fills_metadata = job_dir / f"{video.stem}.fills.tsv"
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
            "--fills-metadata-output",
            str(fills_metadata),
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
            "--vad-min-silence-ms",
            str(args.vad_min_silence_ms),
            "--vad-speech-pad-ms",
            str(args.vad_speech_pad_ms),
            "--main-local-vad-threshold",
            str(args.main_local_vad_threshold),
            "--main-local-vad-window-seconds",
            str(args.main_local_vad_window_seconds),
            "--main-local-vad-window-overlap-seconds",
            str(args.main_local_vad_window_overlap_seconds),
            "--main-local-vad-max-cluster-gap",
            str(args.main_local_vad_max_cluster_gap),
            "--main-local-asr-pad-seconds",
            str(args.main_local_asr_pad_seconds),
            "--main-local-asr-max-clip-seconds",
            str(args.main_local_asr_max_clip_seconds),
            "--main-local-asr-overlap-seconds",
            str(args.main_local_asr_overlap_seconds),
            "--main-local-min-clip-seconds",
            str(args.main_local_min_clip_seconds),
            "--main-local-batch-size",
            str(args.main_local_batch_size),
            "--main-min-chars",
            str(args.main_min_chars),
            "--main-max-compression-ratio",
            str(args.max_fill_compression_ratio),
            "--main-duplicate-window-seconds",
            str(args.main_duplicate_window_seconds),
            "--min-cue-seconds",
            str(args.min_cue_seconds),
            "--near-dup-max-gap",
            str(args.near_dup_max_gap),
            "--near-dup-similarity",
            str(args.near_dup_similarity),
            "--near-dup-squeeze-seconds",
            str(args.near_dup_squeeze_seconds),
            "--min-gap-seconds",
            str(args.fill_min_gap_seconds),
            "--min-speech-seconds",
            str(args.fill_min_speech_seconds),
            "--min-clip-seconds",
            str(args.fill_min_clip_seconds),
            "--max-cluster-gap",
            str(args.fill_max_cluster_gap),
            "--existing-pad-seconds",
            str(args.fill_existing_pad_seconds),
            "--max-existing-overlap-seconds",
            str(args.fill_max_existing_overlap_seconds),
            "--duplicate-window-seconds",
            str(args.fill_duplicate_window_seconds),
            "--min-fill-chars",
            str(args.fill_min_chars),
            "--hallucination-min-repeats",
            str(args.hallucination_min_repeats),
            "--hallucination-repeat-no-speech-prob",
            str(args.hallucination_repeat_no_speech_prob),
            "--hallucination-repeat-avg-logprob",
            str(args.hallucination_repeat_avg_logprob),
            "--hallucination-high-risk-max-repeats",
            str(args.hallucination_high_risk_max_repeats),
            "--gap-local-vad-threshold",
            str(args.gap_local_vad_threshold),
            "--gap-local-vad-window-min-gap-seconds",
            str(args.gap_local_vad_window_min_gap_seconds),
            "--gap-local-vad-window-seconds",
            str(args.gap_local_vad_window_seconds),
            "--gap-local-vad-window-overlap-seconds",
            str(args.gap_local_vad_window_overlap_seconds),
            "--gap-local-asr-pad-seconds",
            str(args.gap_local_asr_pad_seconds),
            "--gap-local-asr-max-clip-seconds",
            str(args.gap_local_asr_max_clip_seconds),
            "--gap-local-asr-overlap-seconds",
            str(args.gap_local_asr_overlap_seconds),
            "--max-fill-compression-ratio",
            str(args.max_fill_compression_ratio),
            "--fill-support-min-chars",
            str(args.fill_support_min_chars),
            "--fill-support-avg-logprob",
            str(args.fill_support_avg_logprob),
            "--fill-support-no-speech-prob",
            str(args.fill_support_no_speech_prob),
            "--fill-support-vad-threshold",
            str(args.fill_support_vad_threshold),
            "--fill-support-pad-seconds",
            str(args.fill_support_pad_seconds),
            "--fill-support-max-ratio",
            str(args.fill_support_max_ratio),
        ]
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
        "--lead-out-seconds",
        str(args.lead_out_seconds),
        "--min-display-seconds",
        str(args.min_display_seconds),
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
            "--vad-min-silence-ms",
            str(args.vad_min_silence_ms),
            "--vad-speech-pad-ms",
            str(args.vad_speech_pad_ms),
        ]
        if args.gap_fill:
            quality_command.extend(["--fills-metadata", str(job_dir / f"{video.stem}.fills.tsv")])
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
    parser.add_argument(
        "--gap-fill",
        action="store_true",
        help="Run the audio-aware gap fill stage after transcription (off by default)",
    )
    parser.add_argument(
        "--bilingual",
        action="store_true",
        help="Also write a bilingual ASS (Chinese on top, Japanese below) next to the Chinese SRT",
    )
    parser.add_argument("--bilingual-zh-font-size", type=int, default=36)
    parser.add_argument("--bilingual-ja-font-size", type=int, default=24)
    parser.add_argument("--bilingual-zh-colour", default="&H0000FFFF", help="ASS colour &HAABBGGRR for the Chinese line")
    parser.add_argument("--bilingual-ja-colour", default="&H00B4B4B4", help="ASS colour &HAABBGGRR for the Japanese line")
    parser.add_argument(
        "--context-size",
        type=int,
        default=2,
        help="Prior dialogue turns supplied to the translator as chat history (previous "
        "source/translation pairs). 0 translates each line standalone.",
    )
    parser.add_argument("--lead-out-seconds", type=float, default=0.5)
    parser.add_argument("--min-display-seconds", type=float, default=1.5)
    parser.add_argument("--language", default="ja")
    parser.add_argument(
        "--asr",
        choices=("whisper", "qwen"),
        default="qwen",
        help="Transcription backend (default qwen). 'qwen' uses Qwen3-ASR with VAD-cut "
        "clips (no gap fill); 'whisper' is the legacy sliding+gap-fill pipeline. "
        "Downstream translate/bilingual/quality are shared.",
    )
    parser.add_argument("--qwen-batch-size", type=int, default=24)
    parser.add_argument("--qwen-chunk-seconds", type=float, default=30.0)
    parser.add_argument("--qwen-chunk-overlap-seconds", type=float, default=3.0)
    parser.add_argument("--qwen-phrase-max-chars", type=int, default=26)
    parser.add_argument("--qwen-phrase-max-duration", type=float, default=8.0)
    parser.add_argument("--qwen-phrase-max-internal-gap", type=float, default=2.0)
    parser.add_argument("--qwen-phrase-max-char-seconds", type=float, default=0.5)
    parser.add_argument("--qwen-vad-chunks", dest="qwen_vad_chunks",
                        action=argparse.BooleanOptionalAction, default=True,
                        help="Cut Qwen clips on silence (VAD) so each clip's first token "
                             "sits where speech starts, reducing leading-anchor drift "
                             "(default on; use --no-qwen-vad-chunks for fixed tiling).")
    parser.add_argument("--qwen-vad-threshold", type=float, default=0.1)
    parser.add_argument("--qwen-vad-max-cluster-gap", type=float, default=2.0)
    parser.add_argument(
        "--qwen-filter-hallucinations",
        action="store_true",
        help="Apply the Whisper-style hallucination/near-duplicate filters to Qwen output (off by default).",
    )
    parser.add_argument("--min-duration", type=float, default=1.0)
    parser.add_argument("--max-duration", type=float, default=10.0)
    parser.add_argument("--max-chars", type=int, default=42)
    parser.add_argument("--vad-min-silence-ms", type=int, default=500)
    parser.add_argument("--vad-speech-pad-ms", type=int, default=400)
    parser.add_argument("--main-local-vad-threshold", type=float, default=0.6)
    parser.add_argument("--main-local-vad-window-seconds", type=float, default=8.0)
    parser.add_argument("--main-local-vad-window-overlap-seconds", type=float, default=4.0)
    parser.add_argument("--main-local-vad-max-cluster-gap", type=float, default=2.0)
    parser.add_argument("--main-local-asr-pad-seconds", type=float, default=0.3)
    parser.add_argument("--main-local-asr-max-clip-seconds", type=float, default=30.0)
    parser.add_argument("--main-local-asr-overlap-seconds", type=float, default=5.0)
    parser.add_argument("--main-local-min-clip-seconds", type=float, default=0.6)
    parser.add_argument("--main-local-batch-size", type=int, default=24)
    parser.add_argument("--max-word-gap", type=float, default=6.0)
    parser.add_argument("--max-merge-gap", type=float, default=1.0)
    parser.add_argument("--fill-min-gap-seconds", type=float, default=2.0)
    parser.add_argument("--fill-min-speech-seconds", type=float, default=1.0)
    parser.add_argument("--fill-min-chars", type=int, default=1)
    parser.add_argument("--fill-min-clip-seconds", type=float, default=0.6)
    parser.add_argument("--fill-existing-pad-seconds", type=float, default=0.1)
    parser.add_argument("--fill-max-existing-overlap-seconds", type=float, default=1.0)
    parser.add_argument("--fill-max-cluster-gap", type=float, default=2.0)
    parser.add_argument("--fill-duplicate-window-seconds", type=float, default=8.0)
    parser.add_argument("--gap-local-vad-threshold", type=float, default=0.60)
    parser.add_argument("--gap-local-vad-window-min-gap-seconds", type=float, default=6.0)
    parser.add_argument("--gap-local-vad-window-seconds", type=float, default=5.0)
    parser.add_argument("--gap-local-vad-window-overlap-seconds", type=float, default=3.0)
    parser.add_argument("--gap-local-asr-pad-seconds", type=float, default=1.0)
    parser.add_argument("--gap-local-asr-max-clip-seconds", type=float, default=30.0)
    parser.add_argument("--gap-local-asr-overlap-seconds", type=float, default=5.0)
    parser.add_argument("--max-fill-compression-ratio", type=float, default=25.0)
    parser.add_argument("--fill-support-min-chars", type=int, default=8)
    parser.add_argument("--fill-support-avg-logprob", type=float, default=-0.95)
    parser.add_argument("--fill-support-no-speech-prob", type=float, default=0.45)
    parser.add_argument("--fill-support-vad-threshold", type=float, default=0.5)
    parser.add_argument("--fill-support-pad-seconds", type=float, default=0.2)
    parser.add_argument("--fill-support-max-ratio", type=float, default=0.45)
    parser.add_argument("--main-min-chars", type=int, default=1)
    parser.add_argument("--main-duplicate-window-seconds", type=float, default=2.0)
    parser.add_argument("--min-cue-seconds", type=float, default=0.3)
    parser.add_argument("--near-dup-max-gap", type=float, default=0.5)
    parser.add_argument("--near-dup-similarity", type=float, default=0.6)
    parser.add_argument("--near-dup-squeeze-seconds", type=float, default=0.8)
    parser.add_argument("--hallucination-min-repeats", type=int, default=10)
    parser.add_argument("--hallucination-repeat-no-speech-prob", type=float, default=0.75)
    parser.add_argument("--hallucination-repeat-avg-logprob", type=float, default=-0.80)
    parser.add_argument("--hallucination-high-risk-max-repeats", type=int, default=3)
    parser.add_argument(
        "--no-copy-to-video-dir",
        action="store_true",
        help="Do not copy the final subtitle file (SRT, or ASS with --bilingual) next to the input video",
    )
    args = parser.parse_args()

    if args.asr == "qwen":
        # Qwen is a full-coverage pass; gap fill is a Whisper-only stage.
        if args.gap_fill:
            print("Note: --gap-fill is ignored with --asr qwen (full-coverage pass).", flush=True)
        args.gap_fill = False

    if args.keep_audio:
        print("Warning: --keep-audio is deprecated and has no effect (audio is kept by default).", flush=True)
    if args.lead_out_seconds < 0:
        raise SystemExit("--lead-out-seconds must be >= 0")
    if args.min_display_seconds < 0:
        raise SystemExit("--min-display-seconds must be >= 0")
    if args.main_local_vad_window_overlap_seconds >= args.main_local_vad_window_seconds:
        raise SystemExit("--main-local-vad-window-overlap-seconds must be smaller than --main-local-vad-window-seconds")
    if args.main_local_asr_overlap_seconds >= min(args.main_local_asr_max_clip_seconds, 30.0):
        raise SystemExit("--main-local-asr-overlap-seconds must be smaller than the effective main ASR clip length")
    if args.gap_local_asr_overlap_seconds >= min(args.gap_local_asr_max_clip_seconds, 30.0):
        raise SystemExit("--gap-local-asr-overlap-seconds must be smaller than the effective gap-fill ASR clip length")

    if shutil.which("ffmpeg") is None:
        raise SystemExit("Missing ffmpeg on PATH; install it (e.g. sudo apt install ffmpeg).")

    if args.asr == "qwen":
        require_file(QWEN_ASR_MODEL, "Qwen3-ASR model")
        require_file(QWEN_ALIGNER_MODEL, "Qwen3 forced aligner")
        require_file(QWEN_TRANSCRIBE_SCRIPT, "Qwen transcription script")
    else:
        require_file(WHISPER_MODEL / "model.bin", "Whisper model")
        require_file(TRANSCRIBE_SCRIPT, "transcription script")
    require_file(TRANSLATE_MODEL, "HY-MT model")
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
