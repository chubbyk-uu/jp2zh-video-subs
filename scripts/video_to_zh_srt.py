from __future__ import annotations

import argparse
import os
import queue
import shutil
import subprocess
import sys
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[1] if Path(__file__).resolve().parent.name == "scripts" else Path(__file__).resolve().parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
TRANSCRIBE_SCRIPT = SCRIPTS_DIR / "transcribe_ja_srt.py"
QWEN_TRANSCRIBE_SCRIPT = SCRIPTS_DIR / "transcribe_ja_srt_qwen.py"
TRANSLATE_SCRIPT = SCRIPTS_DIR / "translate_srt_hymt.py"
SAKURA_TRANSLATE_SCRIPT = SCRIPTS_DIR / "translate_srt_sakura.py"
GALTRANSL_TRANSLATE_SCRIPT = SCRIPTS_DIR / "translate_srt_galtransl.py"
QUALITY_REPORT_SCRIPT = SCRIPTS_DIR / "quality_report.py"
FILL_GAPS_SCRIPT = SCRIPTS_DIR / "fill_ja_srt_gaps.py"
BILINGUAL_SCRIPT = SCRIPTS_DIR / "make_bilingual_ass.py"
WHISPER_MODEL = PROJECT_ROOT / "models" / "faster-whisper-large-v3"
QWEN_ASR_MODEL = PROJECT_ROOT / "models" / "Qwen3-ASR-1.7B"
QWEN_ALIGNER_MODEL = PROJECT_ROOT / "models" / "Qwen3-ForcedAligner-0.6B"
TRANSLATE_MODEL = PROJECT_ROOT / "models" / "Hy-MT2-7B-GGUF" / "HY-MT2-7B-Q6_K.gguf"
SAKURA_MODEL = PROJECT_ROOT / "models" / "Sakura-14B-Qwen2.5-v1.0-GGUF" / "sakura-14b-qwen2.5-v1.0-iq4xs.gguf"
GALTRANSL_MODEL = PROJECT_ROOT / "models" / "Sakura-GalTransl-7B-v3.7-GGUF" / "Sakura-Galtransl-7B-v3.7.gguf"
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


class JobLog:
    """Tees pipeline output into the job's work dir so it survives terminal loss
    and /tmp cleanup; appended across runs, one file per video."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.file = path.open("a", encoding="utf-8")

    def print(self, message: str) -> None:
        print(message, flush=True)
        self.file.write(message + "\n")
        self.file.flush()

    def write_raw(self, text: str) -> None:
        sys.stdout.write(text)
        sys.stdout.flush()
        self.file.write(text)
        self.file.flush()

    def close(self) -> None:
        self.file.close()


def run(command: list[str], log: JobLog | None = None) -> None:
    if log is None:
        print("+ " + " ".join(command), flush=True)
        subprocess.run(command, check=True)
        return
    log.print("+ " + " ".join(command))
    # Child Python processes block-buffer stdout once it is a pipe; force line
    # buffering so the console and log stay live. stderr is merged so tracebacks
    # land in the log too.
    env = dict(os.environ, PYTHONUNBUFFERED="1")
    with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env) as proc:
        assert proc.stdout is not None
        # Chunked rather than line-based so \r progress (ffmpeg) still streams live.
        while chunk := proc.stdout.read1(8192):
            log.write_raw(chunk.decode("utf-8", errors="replace"))
    if proc.returncode:
        raise subprocess.CalledProcessError(proc.returncode, command)


def require_file(path: Path, label: str) -> None:
    if not path.exists():
        raise SystemExit(f"Missing {label}: {path}")


def srt_cue_count(path: Path) -> int:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return -1
    return sum(1 for line in text.splitlines() if "-->" in line)


def translation_is_complete(zh_srt: Path, ja_srt: Path) -> bool:
    """A finished translation has exactly one cue per source cue. The translator
    writes incrementally, so a crash leaves a shorter (but valid-looking) SRT —
    bare existence is not enough to resume past it."""
    count = srt_cue_count(zh_srt)
    return count > 0 and count == srt_cue_count(ja_srt)


def resume_skip(args: argparse.Namespace, path: Path, log: JobLog, label: str) -> bool:
    """Whether --resume can skip a stage whose output is written in one shot at the
    end of the stage (transcription), making existence proof of completeness."""
    if args.resume and path.exists() and path.stat().st_size > 0:
        log.print(f"Resume: skipping {label}, reusing {path}")
        return True
    return False


@dataclass
class VideoJob:
    index: int
    video: Path
    output: Path
    job_dir: Path
    audio: Path


def extract_audio(video: Path, audio: Path, reuse_existing: bool = False, log: JobLog | None = None) -> None:
    audio.parent.mkdir(parents=True, exist_ok=True)
    if reuse_existing and audio.exists() and audio.stat().st_size > 0:
        message = f"Reusing existing audio: {audio}"
        if log is not None:
            log.print(message)
        else:
            print(message, flush=True)
        return
    run(["ffmpeg", "-y", "-i", str(video), "-vn", "-ac", "1", "-ar", "16000", str(audio)], log)


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
    job_dir.mkdir(parents=True, exist_ok=True)
    log = JobLog(job_dir / "pipeline.log")
    try:
        log.print(f"=== {datetime.now():%Y-%m-%d %H:%M:%S} start {video.name} ===")
        process_video_stages(args, video, output, job_dir, audio, log)
        log.print(f"=== {datetime.now():%Y-%m-%d %H:%M:%S} done {video.name} ===")
    except BaseException as exc:
        log.print(f"=== {datetime.now():%Y-%m-%d %H:%M:%S} FAILED {video.name}: {exc!r} ===")
        raise
    finally:
        log.close()


def process_video_stages(
    args: argparse.Namespace, video: Path, output: Path, job_dir: Path, audio: Path, log: JobLog
) -> None:
    log.print(f"\n==> Processing {video}")
    output.parent.mkdir(parents=True, exist_ok=True)
    ja_srt = job_dir / f"{video.stem}.ja.srt"
    translate_input_srt = ja_srt

    if args.asr == "qwen":
        # Qwen3-ASR uses VAD-cut clips by default to reduce leading-anchor drift.
        # Use --no-qwen-vad-chunks for fixed uniform tiling when VAD boundaries are suspect.
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
            "--isolated-interjection-silence",
            str(args.qwen_isolated_interjection_silence),
            "--recapture-min-gap",
            str(args.qwen_recapture_min_gap),
            "--recapture-min-speech",
            str(args.qwen_recapture_min_speech),
            "--recapture-vad-threshold",
            str(args.qwen_recapture_vad_threshold),
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
        if args.qwen_context:
            transcribe_command += ["--context", args.qwen_context]
        if not resume_skip(args, ja_srt, log, "transcription"):
            run(transcribe_command, log)
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
        if not resume_skip(args, ja_srt, log, "transcription"):
            run(transcribe_command, log)
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
        # The fill stage writes the filled SRT and the fills metadata together at
        # the end, so resuming needs both present.
        if not (fills_metadata.exists() and resume_skip(args, filled_ja_srt, log, "transcription + gap fill")):
            run(fill_command, log)
        translate_input_srt = filled_ja_srt

    # Sakura, GalTransl, and HY-MT share the same core CLI (input, --output,
    # --model-path, --context-size, --lead-out/--min-display), so only the script and
    # model differ. Each translator decides how to render context in its own prompt.
    if args.translator == "sakura":
        translate_script, translate_model = SAKURA_TRANSLATE_SCRIPT, SAKURA_MODEL
    elif args.translator == "galtransl":
        translate_script, translate_model = GALTRANSL_TRANSLATE_SCRIPT, GALTRANSL_MODEL
    else:
        translate_script, translate_model = TRANSLATE_SCRIPT, TRANSLATE_MODEL
    translate_context_size = args.context_size
    if translate_context_size is None:
        translate_context_size = 2 if args.translator == "hymt" else 6
    translate_command = [
        sys.executable,
        str(translate_script),
        str(translate_input_srt),
        "--output",
        str(output),
        "--model-path",
        str(translate_model),
        "--context-size",
        str(translate_context_size),
        "--lead-out-seconds",
        str(args.lead_out_seconds),
        "--min-display-seconds",
        str(args.min_display_seconds),
    ]
    # Batch translation is GalTransl-only (relies on its line-break-preservation
    # contract); Sakura/HY-MT do not take --batch-size.
    if args.translator == "galtransl":
        translate_command.extend(["--batch-size", str(args.translate_batch_size)])
    if args.resume and translation_is_complete(output, translate_input_srt):
        log.print(f"Resume: skipping translation, reusing {output}")
    else:
        run(translate_command, log)

    bilingual_output: Path | None = None
    if args.bilingual:
        bilingual_output = output.with_suffix(".ass")
        bilingual_command = [
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
            "--male-colour",
            args.bilingual_male_colour,
            "--female-colour",
            args.bilingual_female_colour,
            "--gender-confidence",
            str(args.gender_confidence),
        ]
        if args.colour_by_speaker:
            bilingual_command.extend(["--audio", str(audio), "--colour-by-speaker"])
        else:
            bilingual_command.append("--no-colour-by-speaker")
        run(bilingual_command, log)

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
            # Shared history file across videos and runs, for comparing tuning changes.
            "--metrics-jsonl",
            str(args.work_dir / "metrics.jsonl"),
            "--metrics-label",
            video.stem,
        ]
        if args.gap_fill:
            quality_command.extend(["--fills-metadata", str(job_dir / f"{video.stem}.fills.tsv")])
        if args.asr == "qwen":
            quality_command.extend(["--qwen-metadata", str(ja_srt.with_suffix(ja_srt.suffix + ".meta.json"))])
        run(quality_command, log)
        log.print(f"Quality report: {report_path}")

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

    log.print(f"Wrote {output}")
    if bilingual_output is not None:
        log.print(f"Bilingual ASS: {bilingual_output}")
    if copied_to_video is not None:
        label = "Bilingual ASS" if bilingual_output is not None else "Chinese SRT"
        log.print(f"{label} next to video: {copied_to_video}")
    log.print(f"Intermediate Japanese SRT: {ja_srt}")
    if translate_input_srt != ja_srt:
        log.print(f"Gap-filled Japanese SRT: {translate_input_srt}")


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
    parser.add_argument("--reuse-existing-audio", action="store_true", help="Skip ffmpeg extraction when the WAV already exists (reuse it)")
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Skip finished stages: reuse existing audio, transcription, and complete translations. "
        "The ASS/quality-report stages always rerun (cheap, no model).",
    )
    parser.add_argument("--skip-quality-report", action="store_true", help="Do not write a quality report")
    parser.add_argument(
        "--gap-fill",
        action="store_true",
        help="Run the audio-aware gap fill stage after transcription (off by default)",
    )
    parser.add_argument(
        "--bilingual",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Write a bilingual ASS (Chinese on top, Japanese below) next to the Chinese SRT (default on; --no-bilingual writes only the Chinese SRT)",
    )
    parser.add_argument("--bilingual-zh-font-size", type=int, default=36)
    parser.add_argument("--bilingual-ja-font-size", type=int, default=24)
    parser.add_argument("--bilingual-zh-colour", default="&H0000FFFF", help="ASS colour &HAABBGGRR for the Chinese line")
    parser.add_argument("--bilingual-ja-colour", default="&H00B4B4B4", help="ASS colour &HAABBGGRR for the Japanese line")
    parser.add_argument(
        "--colour-by-speaker",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="In bilingual mode, recolour each cue's Chinese line by speaker gender (ECAPA, off by default)",
    )
    parser.add_argument("--bilingual-male-colour", default="&H00FFBF00", help="ASS colour for male-speaker Chinese line")
    parser.add_argument("--bilingual-female-colour", default="&H00B478FF", help="ASS colour for female-speaker Chinese line")
    parser.add_argument("--gender-confidence", type=float, default=0.6, help="Min confidence to colour a cue by gender")
    parser.add_argument(
        "--context-size",
        type=int,
        default=None,
        help="Prior dialogue turns supplied to the translator as context (galtransl: a "
        "历史翻译 block of prior translations; sakura: source/translation chat pairs; "
        "hymt: previous Chinese translations as Hy-MT2 background information). Defaults: "
        "6 for galtransl/sakura, 2 for hymt. "
        "0 translates each line standalone.",
    )
    parser.add_argument(
        "--translate-batch-size",
        type=int,
        default=8,
        help="GalTransl only: translate up to N consecutive cues as one turn so whole "
        "sentences split across cues resolve correctly (e.g. omitted subjects/person). "
        "Line-count mismatch falls back to per-line. 0 or 1 disables batching.",
    )
    parser.add_argument("--lead-out-seconds", type=float, default=0.5)
    parser.add_argument("--min-display-seconds", type=float, default=1.5)
    parser.add_argument("--language", default="ja")
    parser.add_argument(
        "--translator",
        choices=("sakura", "galtransl", "hymt"),
        default="galtransl",
        help="Translation backend (default galtransl). 'galtransl' uses "
        "Sakura-GalTransl-7B-v3.7 (visual-novel dialogue, smaller/faster, more "
        "colloquial); 'sakura' uses Sakura-14B-Qwen2.5-v1.0 (light-novel style); "
        "'hymt' uses Hy-MT2-7B.",
    )
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
    parser.add_argument("--qwen-context", default="",
                        help="Extra Qwen ASR hotwords/context appended to the built-in list "
                             "(e.g. per-title character names) to fix homophone/name errors.")
    parser.add_argument("--qwen-vad-chunks", dest="qwen_vad_chunks",
                        action=argparse.BooleanOptionalAction, default=True,
                        help="Cut Qwen clips on silence (VAD) so each clip's first token "
                             "sits where speech starts, reducing leading-anchor drift "
                             "(default on; use --no-qwen-vad-chunks for fixed tiling).")
    parser.add_argument("--qwen-vad-threshold", type=float, default=0.1)
    parser.add_argument("--qwen-vad-max-cluster-gap", type=float, default=2.0)
    parser.add_argument("--qwen-isolated-interjection-silence", type=float, default=3.0)
    # Recapture: a second, more sensitive VAD+ASR look inside subtitle gaps at least
    # this long, run while the ASR model is still loaded (0 disables).
    parser.add_argument("--qwen-recapture-min-gap", type=float, default=10.0)
    parser.add_argument("--qwen-recapture-min-speech", type=float, default=2.0)
    parser.add_argument("--qwen-recapture-vad-threshold", type=float, default=0.05)
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

    if args.resume:
        args.reuse_existing_audio = True

    if args.asr == "qwen":
        # Qwen gap-fill is intentionally disabled; use Whisper when a second recall pass is required.
        if args.gap_fill:
            print("Note: --gap-fill is ignored with --asr qwen; gap fill belongs to the Whisper backend.", flush=True)
        args.gap_fill = False

    if args.keep_audio:
        print("Warning: --keep-audio is deprecated and has no effect (audio is kept by default).", flush=True)
    if args.lead_out_seconds < 0:
        raise SystemExit("--lead-out-seconds must be >= 0")
    if args.min_display_seconds < 0:
        raise SystemExit("--min-display-seconds must be >= 0")
    if args.context_size is not None and args.context_size < 0:
        raise SystemExit("--context-size must be >= 0")
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
    if args.translator == "sakura":
        require_file(SAKURA_MODEL, "Sakura model")
        require_file(SAKURA_TRANSLATE_SCRIPT, "Sakura translation script")
    elif args.translator == "galtransl":
        require_file(GALTRANSL_MODEL, "GalTransl model")
        require_file(GALTRANSL_TRANSLATE_SCRIPT, "GalTransl translation script")
    else:
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
        log = JobLog(job.job_dir / "pipeline.log")
        try:
            extract_audio(job.video, job.audio, reuse_existing=args.reuse_existing_audio, log=log)
        except BaseException as exc:
            log.print(f"=== {datetime.now():%Y-%m-%d %H:%M:%S} FAILED extracting {job.video.name}: {exc!r} ===")
            raise
        finally:
            log.close()

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
