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

from cli_config import (
    add_prefixed_dataclass_arguments,
    apply_config_file,
    config_from_prefixed,
    config_to_cli_args,
    format_config_toml,
)
from pipeline_configs import (
    AnimeAsrConfig,
    BilingualAssConfig,
    GalTranslTranslateConfig,
    QualityReportConfig,
    QwenAsrConfig,
    SakuraTranslateConfig,
)
from srt_utils import wrap_srt_display_file


PROJECT_ROOT = Path(__file__).resolve().parents[1] if Path(__file__).resolve().parent.name == "scripts" else Path(__file__).resolve().parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
QWEN_TRANSCRIBE_SCRIPT = SCRIPTS_DIR / "transcribe_ja_srt_qwen.py"
SAKURA_TRANSLATE_SCRIPT = SCRIPTS_DIR / "translate_srt_sakura.py"
GALTRANSL_TRANSLATE_SCRIPT = SCRIPTS_DIR / "translate_srt_galtransl.py"
QUALITY_REPORT_SCRIPT = SCRIPTS_DIR / "quality_report.py"
BILINGUAL_SCRIPT = SCRIPTS_DIR / "make_bilingual_ass.py"
QWEN_ASR_MODEL = PROJECT_ROOT / "models" / "Qwen3-ASR-1.7B"
QWEN_ALIGNER_MODEL = PROJECT_ROOT / "models" / "Qwen3-ForcedAligner-0.6B"
# anime backend reuses the Qwen sub-script (shared VAD/cue-shaping/finalize) with a
# different text source, so --asr anime runs QWEN_TRANSCRIBE_SCRIPT with text_backend=anime.
ANIME_ASR_MODEL = PROJECT_ROOT / "models" / "anime-whisper"
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

ANIME_PREFIX_SKIP = {"language", "min_cue_seconds", "text_backend"}


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
    # Extract to a temp name and rename atomically: an interrupted ffmpeg must not
    # leave a truncated WAV at the final path, where a later --resume /
    # --reuse-existing-audio run would reuse it and silently transcribe short.
    partial = audio.with_name(audio.name + ".part")
    run(["ffmpeg", "-y", "-i", str(video), "-vn", "-ac", "1", "-ar", "16000", "-f", "wav", str(partial)], log)
    partial.replace(audio)


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
        try:
            for job in jobs:
                try:
                    extract(job)
                    work_queue.put((job, None))
                except BaseException as exc:
                    work_queue.put((job, exc))
                    if not isinstance(exc, Exception):
                        break
        finally:
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
            if not isinstance(exc, Exception):
                raise exc
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
        try:
            relative_parent = video.parent.relative_to(input_path)
        except ValueError:
            relative_parent = Path()
        if relative_parent == Path():
            return (output_dir / f"{video.stem}.zh.srt").resolve()
        safe_parent = "__".join(relative_parent.parts)
        return (output_dir / f"{safe_parent}__{video.stem}.zh.srt").resolve()
    return (output_dir / f"{video.stem}.zh.srt").resolve()


def work_dir_for(video: Path, input_path: Path, work_dir: Path, recursive: bool) -> Path:
    if input_path.is_dir() and recursive:
        relative = video.relative_to(input_path).with_suffix("")
        return (work_dir / relative).resolve()
    return (work_dir / video.stem).resolve()


def _asr_language(args: argparse.Namespace) -> str:
    language = getattr(args, "language", "ja")
    return "Japanese" if language == "ja" else language


def _anime_compat_overrides(args: argparse.Namespace) -> dict:
    """Map old anime-tuning --qwen-* aliases only when the new --anime-* value is unset."""
    overrides: dict = {}
    if getattr(args, "anime_timestamp_mode", None) is None and getattr(args, "qwen_timestamp_mode", None) is not None:
        overrides["timestamp_mode"] = args.qwen_timestamp_mode
    if getattr(args, "anime_scene_backend", None) is None and getattr(args, "qwen_scene_backend", None) is not None:
        overrides["scene_backend"] = args.qwen_scene_backend
    return overrides


def asr_config_for_command(args: argparse.Namespace) -> QwenAsrConfig | AnimeAsrConfig:
    if args.asr == "anime":
        overrides = {
            "language": _asr_language(args),
            "min_cue_seconds": getattr(args, "min_cue_seconds", 0.3),
            "text_backend": "anime",
            **_anime_compat_overrides(args),
        }
        return config_from_prefixed(
            args,
            AnimeAsrConfig,
            prefix="anime_",
            overrides=overrides,
            none_means_default=True,
        )
    return config_from_prefixed(
        args,
        QwenAsrConfig,
        prefix="qwen_",
        overrides={
            "language": _asr_language(args),
            "min_cue_seconds": getattr(args, "min_cue_seconds", 0.3),
            "text_backend": "qwen",
        },
        none_means_default=True,
    )


def build_qwen_command(args: argparse.Namespace, audio: Path, ja_srt: Path) -> list[str]:
    """Assemble the Qwen transcription sub-command.

    The qwen and anime backends share the same sub-script but use separate top-level
    config surfaces, so backend defaults cannot leak across lines.
    """
    cfg = asr_config_for_command(args)
    return [
        sys.executable,
        str(QWEN_TRANSCRIBE_SCRIPT),
        str(audio),
        str(ja_srt),
        "--model",
        str(QWEN_ASR_MODEL),
        "--forced-aligner",
        str(QWEN_ALIGNER_MODEL),
        *config_to_cli_args(cfg),
    ]


def validate_runtime_args(args: argparse.Namespace) -> None:
    """Validate cross-field combinations that argparse choices cannot express."""
    if args.asr == "qwen":
        cfg = asr_config_for_command(args)
        if (
            cfg.timestamp_mode == "vad_only"
            and cfg.vad_backend == "whisperseg"
            and cfg.whisperseg_context_mode != "none"
        ):
            raise SystemExit(
                "Qwen vad_only cannot be combined with WhisperSeg context merge. "
                "Use --qwen-whisperseg-context-mode none, or use "
                "--qwen-timestamp-mode aligner_fallback for long-context Qwen recognition."
            )


def translate_backend(args: argparse.Namespace) -> tuple[Path, Path]:
    if args.translator == "sakura":
        return SAKURA_TRANSLATE_SCRIPT, SAKURA_MODEL
    return GALTRANSL_TRANSLATE_SCRIPT, GALTRANSL_MODEL


def build_translate_command(args: argparse.Namespace, input_srt: Path, output_srt: Path) -> list[str]:
    translate_script, translate_model = translate_backend(args)
    context_size = args.context_size
    if context_size is None:
        context_size = 6

    common = {
        "context_size": context_size,
        "lead_out_seconds": args.lead_out_seconds,
        "min_display_seconds": args.min_display_seconds,
    }
    if args.translator == "galtransl":
        cfg = GalTranslTranslateConfig(batch_size=args.translate_batch_size, **common)
    else:
        cfg = SakuraTranslateConfig(**common)

    return [
        sys.executable,
        str(translate_script),
        str(input_srt),
        "--output",
        str(output_srt),
        "--model-path",
        str(translate_model),
        *config_to_cli_args(cfg),
    ]


def build_bilingual_command(args: argparse.Namespace, zh_srt: Path, ja_srt: Path, output_ass: Path, audio: Path) -> list[str]:
    cfg = config_from_prefixed(
        args,
        BilingualAssConfig,
        prefix="bilingual_",
        overrides={
            "colour_by_speaker": args.colour_by_speaker,
            "gender_confidence": args.gender_confidence,
        },
    )
    command = [
        sys.executable,
        str(BILINGUAL_SCRIPT),
        "--zh-srt",
        str(zh_srt),
        "--ja-srt",
        str(ja_srt),
        "--output",
        str(output_ass),
        *config_to_cli_args(cfg),
    ]
    if args.colour_by_speaker:
        command.extend(["--audio", str(audio)])
    return command


def build_quality_command(
    args: argparse.Namespace,
    ja_srt: Path,
    zh_srt: Path,
    audio: Path,
    output: Path,
    metrics_jsonl: Path,
    metrics_label: str,
    qwen_metadata: Path | None,
) -> list[str]:
    cfg = QualityReportConfig()
    if getattr(args, "asr", None) in ("anime", "qwen"):
        asr_cfg = asr_config_for_command(args)
        cfg.vad_backend = "whisperseg" if args.asr == "anime" else cfg.vad_backend
        for name in (
            "whisperseg_model", "whisperseg_max_speech", "whisperseg_hard_max_speech",
            "whisperseg_soft_split_lookback", "whisperseg_max_group",
            "whisperseg_chunk_threshold", "whisperseg_threshold", "whisperseg_min_frame_seconds",
        ):
            setattr(cfg, name, getattr(asr_cfg, name))
    if getattr(args, "quality_vad_backend", None):
        cfg.vad_backend = args.quality_vad_backend
    command = [
        sys.executable,
        str(QUALITY_REPORT_SCRIPT),
        "--ja-srt",
        str(ja_srt),
        "--zh-srt",
        str(zh_srt),
        "--audio",
        str(audio),
        "--output",
        str(output),
        # Shared history file across videos and runs, for comparing tuning changes.
        "--metrics-jsonl",
        str(metrics_jsonl),
        "--metrics-label",
        metrics_label,
        *config_to_cli_args(cfg),
    ]
    if qwen_metadata is not None:
        command.extend(["--qwen-metadata", str(qwen_metadata)])
    return command


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

    transcribe_command = build_qwen_command(args, audio, ja_srt)
    if not resume_skip(args, ja_srt, log, "transcription"):
        run(transcribe_command, log)

    translate_command = build_translate_command(args, translate_input_srt, output)
    if args.resume and translation_is_complete(output, translate_input_srt):
        log.print(f"Resume: skipping translation, reusing {output}")
    else:
        run(translate_command, log)

    wrapped = wrap_srt_display_file(output, args.display_wrap_max_chars)
    if wrapped:
        log.print(
            f"Display wrapping: {wrapped} cues split at punctuation "
            f"(max_chars={args.display_wrap_max_chars})"
        )

    bilingual_output: Path | None = None
    if args.bilingual:
        bilingual_output = output.with_suffix(".ass")
        bilingual_command = build_bilingual_command(args, output, translate_input_srt, bilingual_output, audio)
        run(bilingual_command, log)

    if args.quality_report and not args.skip_quality_report:
        report_path = job_dir / f"{video.stem}.quality.txt"
        qwen_metadata = ja_srt.with_suffix(ja_srt.suffix + ".meta.json")
        quality_command = build_quality_command(
            args,
            translate_input_srt,
            output,
            audio,
            report_path,
            args.work_dir / "metrics.jsonl",
            video.stem,
            qwen_metadata,
        )
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


def _early_config_path(argv: list[str]) -> Path | None:
    """Find --config PATH / --config=PATH before argparse runs.

    Scanning argv directly (rather than a parse_known_args pre-pass) lets the file's
    defaults be applied before the single real parse, without tripping over the required
    `input` positional — which argparse still demands on the command line regardless of
    any default a config file might set."""
    for index, token in enumerate(argv):
        if token == "--config" and index + 1 < len(argv):
            return Path(argv[index + 1])
        if token.startswith("--config="):
            return Path(token.split("=", 1)[1])
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate Chinese SRT subtitles from Japanese videos.")
    parser.add_argument(
        "--config",
        type=Path,
        help="Flat TOML file of defaults for any option below (keys are flag names). A "
        "value flag given on the command line overrides the file; plain on/off switches "
        "(e.g. --quality-report, --resume) can only be turned on, so once set true in the file "
        "the command line cannot turn them back off. See --print-config.",
    )
    parser.add_argument(
        "--print-config",
        action="store_true",
        help="Print the effective configuration as TOML (after applying --config and CLI flags) and exit.",
    )
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
        "The ASS stage always reruns (cheap, no model); quality report reruns only when --quality-report is set.",
    )
    parser.add_argument("--quality-report", action="store_true", help="Write a quality report and append metrics (off by default)")
    parser.add_argument("--skip-quality-report", action="store_true", help="Deprecated compatibility flag; quality reports are off unless --quality-report is set")
    parser.add_argument(
        "--quality-vad-backend",
        choices=("auto", "metadata", "whisperseg"),
        help="VAD source used only by the quality report (default: anime uses whisperseg, others auto)",
    )
    parser.add_argument(
        "--bilingual",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Write a bilingual ASS (Chinese on top, Japanese below) next to the Chinese SRT (default on; --no-bilingual writes only the Chinese SRT)",
    )
    bilingual_defaults = BilingualAssConfig()
    parser.add_argument("--bilingual-font", default=bilingual_defaults.font)
    parser.add_argument("--bilingual-zh-font-size", type=int, default=bilingual_defaults.zh_font_size)
    parser.add_argument("--bilingual-ja-font-size", type=int, default=bilingual_defaults.ja_font_size)
    parser.add_argument("--bilingual-zh-colour", default=bilingual_defaults.zh_colour, help="ASS colour &HAABBGGRR for the Chinese line")
    parser.add_argument("--bilingual-ja-colour", default=bilingual_defaults.ja_colour, help="ASS colour &HAABBGGRR for the Japanese line")
    parser.add_argument("--bilingual-play-res-x", type=int, default=bilingual_defaults.play_res_x)
    parser.add_argument("--bilingual-play-res-y", type=int, default=bilingual_defaults.play_res_y)
    parser.add_argument(
        "--colour-by-speaker",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="In bilingual mode, recolour each cue's Chinese line by speaker gender (ECAPA, off by default)",
    )
    parser.add_argument("--bilingual-male-colour", default=bilingual_defaults.male_colour, help="ASS colour for male-speaker Chinese line")
    parser.add_argument("--bilingual-female-colour", default=bilingual_defaults.female_colour, help="ASS colour for female-speaker Chinese line")
    parser.add_argument("--gender-confidence", type=float, default=bilingual_defaults.gender_confidence, help="Min confidence to colour a cue by gender")
    parser.add_argument(
        "--context-size",
        type=int,
        default=None,
        help="Prior dialogue turns supplied to the translator as context (galtransl: a "
        "历史翻译 block of prior translations; sakura: source/translation chat pairs; "
        "default 6). 0 translates each line standalone.",
    )
    parser.add_argument(
        "--translate-batch-size",
        type=int,
        default=8,
        help="GalTransl only: translate up to N consecutive cues as one turn so whole "
        "sentences split across cues resolve correctly (e.g. omitted subjects/person). "
        "Line-count mismatches are retried as smaller strict batches; any remaining "
        "unsafe slots fall back per-line. 0 or 1 disables batching.",
    )
    parser.add_argument("--lead-out-seconds", type=float, default=0.5)
    parser.add_argument("--min-display-seconds", type=float, default=1.5)
    parser.add_argument(
        "--display-wrap-max-chars", type=int, default=20,
        help="Split long final Chinese cues into two display lines at punctuation nearest the midpoint (0 disables)",
    )
    parser.add_argument("--language", default="ja")
    parser.add_argument(
        "--translator",
        choices=("sakura", "galtransl"),
        default="galtransl",
        help="Translation backend (default galtransl). 'galtransl' uses "
        "Sakura-GalTransl-7B-v3.7 (visual-novel dialogue, smaller/faster, more "
        "colloquial); 'sakura' uses Sakura-14B-Qwen2.5-v1.0 (light-novel style).",
    )
    parser.add_argument(
        "--asr",
        choices=("qwen", "anime"),
        default="anime",
        help="Transcription backend (default anime). 'anime' uses litagin/anime-whisper "
        "text + WhisperSeg framing + semantic scenes + vad_only timing; 'qwen' uses "
        "Qwen3-ASR with WhisperSeg framing, aligner fallback recovery, and WJ-style "
        "generation knobs. anime shares the qwen sub-script implementation but uses "
        "its own --anime-* tuning surface. Downstream stages are shared.",
    )
    parser.add_argument("--qwen-batch-size", type=int, default=24)
    parser.add_argument("--qwen-device", default="cuda:0")
    parser.add_argument("--qwen-dtype", choices=("bfloat16", "float16", "float32"), default="bfloat16")
    parser.add_argument("--qwen-max-new-tokens", type=int, default=4096)
    parser.add_argument("--qwen-repetition-penalty", type=float, default=1.1)
    parser.add_argument("--qwen-max-tokens-per-second", type=float, default=20.0)
    parser.add_argument("--qwen-min-tokens-floor", type=int, default=256)
    parser.add_argument("--qwen-chunk-seconds", type=float, default=30.0)
    parser.add_argument("--qwen-chunk-overlap-seconds", type=float, default=3.0)
    parser.add_argument("--qwen-phrase-max-chars", type=int, default=None)
    parser.add_argument("--qwen-phrase-max-duration", type=float, default=8.0)
    parser.add_argument("--qwen-phrase-max-internal-gap", type=float, default=None)
    parser.add_argument("--qwen-phrase-max-char-seconds", type=float, default=0.5)
    parser.add_argument("--qwen-min-duration", type=float, default=0.8)
    parser.add_argument("--qwen-context", default="",
                        help="Extra Qwen ASR hotwords/context appended to the built-in list "
                             "(e.g. per-title character names) to fix homophone/name errors.")
    parser.add_argument("--qwen-no-default-context", action="store_true",
                        help="Disable Qwen's built-in ASR hotword/context prompt.")
    parser.add_argument("--qwen-vad-chunks", dest="qwen_vad_chunks",
                        action=argparse.BooleanOptionalAction, default=True,
                        help="Cut Qwen clips on silence (VAD) so each clip's first token "
                             "sits where speech starts, reducing leading-anchor drift "
                             "(Qwen comparison line; default on for --asr qwen, use "
                             "--no-qwen-vad-chunks for fixed tiling).")
    parser.add_argument("--qwen-vad-threshold", type=float, default=0.1)
    parser.add_argument("--qwen-vad-window-seconds", type=float, default=8.0)
    parser.add_argument("--qwen-vad-window-overlap-seconds", type=float, default=4.0)
    parser.add_argument("--qwen-vad-min-silence-ms", type=int, default=500)
    parser.add_argument("--qwen-vad-speech-pad-ms", type=int, default=200)
    parser.add_argument("--qwen-vad-max-cluster-gap", type=float, default=2.0)
    parser.add_argument("--qwen-vad-pad-seconds", type=float, default=0.2)
    parser.add_argument("--qwen-vad-min-clip-seconds", type=float, default=0.3)
    parser.add_argument("--qwen-vad-pre-context-seconds", type=float, default=0.0)
    parser.add_argument("--qwen-vad-post-context-seconds", type=float, default=0.5)
    parser.add_argument("--qwen-vad-max-leading-silence", type=float, default=0.5)
    parser.add_argument("--qwen-vad-context-merge-gap", type=float, default=0.0)
    parser.add_argument("--qwen-vad-target-context-seconds", type=float, default=24.0)
    parser.add_argument("--qwen-vad-backend", choices=("whisperseg",), default=None)
    parser.add_argument("--qwen-whisperseg-model", default=None)
    parser.add_argument("--qwen-whisperseg-max-speech", type=float, default=None)
    parser.add_argument("--qwen-whisperseg-hard-max-speech", type=float, default=None)
    parser.add_argument("--qwen-whisperseg-soft-split-lookback", type=float, default=None)
    parser.add_argument("--qwen-whisperseg-max-group", type=float, default=None)
    parser.add_argument("--qwen-whisperseg-chunk-threshold", type=float, default=None)
    parser.add_argument("--qwen-whisperseg-threshold", type=float, default=None)
    parser.add_argument("--qwen-whisperseg-min-frame-seconds", type=float, default=None)
    parser.add_argument(
        "--qwen-whisperseg-context-mode",
        choices=("none", "merge"),
        default=None,
        help="Qwen WhisperSeg context experiment: none, or merge adjacent frames into one exact-boundary recognition job.",
    )
    parser.add_argument("--qwen-whisperseg-context-merge-gap", type=float, default=None,
                        help="Max gap between frames to merge when --qwen-whisperseg-context-mode merge.")
    parser.add_argument("--qwen-whisperseg-context-target-seconds", type=float, default=None,
                        help="Soft target recognition span when --qwen-whisperseg-context-mode merge.")
    parser.add_argument("--qwen-whisperseg-context-after-target-gap", type=float, default=None,
                        help="Tighter merge-gap tolerance once a merged group passes the soft target, to break at a pause instead of a mid-speech hard cut.")
    parser.add_argument("--qwen-whisperseg-context-hard-max-seconds", type=float, default=None,
                        help="Hard max recognition span when --qwen-whisperseg-context-mode merge.")
    parser.add_argument("--qwen-isolated-interjection-silence", type=float, default=3.0)
    parser.add_argument("--qwen-isolated-interjection-run", type=int, default=3)
    parser.add_argument("--qwen-isolated-interjection-run-gap", type=float, default=5.0)
    parser.add_argument("--qwen-interjection-reply-anchor-lag", type=float, default=3.0)
    parser.add_argument(
        "--qwen-timestamp-mode",
        choices=("aligner_fallback", "aligner_only", "vad_only"),
        default=None,
        help="Qwen timing mode; also accepted as a deprecated anime alias when --asr anime and --anime-timestamp-mode is unset.",
    )
    parser.add_argument(
        "--qwen-scene-backend",
        choices=("none", "semantic"),
        default=None,
        help="Qwen scene pre-segmentation; also accepted as a deprecated anime alias when --asr anime and --anime-scene-backend is unset.",
    )
    parser.add_argument("--qwen-scene-min-seconds", type=float, default=None)
    parser.add_argument("--qwen-scene-max-seconds", type=float, default=None)
    parser.add_argument("--qwen-scene-clustering-threshold", type=float, default=None)
    parser.add_argument("--qwen-collapse-filler-repetition", dest="qwen_collapse_filler_repetition",
                        action=argparse.BooleanOptionalAction, default=True,
                        help="Collapse repeated filler runs inside one Qwen cue (default on).")
    parser.add_argument("--qwen-near-dup-max-gap", type=float, default=0.25)
    parser.add_argument("--qwen-near-dup-similarity", type=float, default=0.90)
    parser.add_argument("--qwen-near-dup-squeeze-seconds", type=float, default=0.5)
    parser.add_argument("--qwen-main-min-chars", type=int, default=1)
    parser.add_argument("--qwen-main-max-compression-ratio", type=float, default=25.0)
    parser.add_argument("--qwen-main-duplicate-window-seconds", type=float, default=8.0)
    parser.add_argument("--qwen-hallucination-min-repeats", type=int, default=3)
    parser.add_argument("--qwen-hallucination-repeat-no-speech-prob", type=float, default=0.75)
    parser.add_argument("--qwen-hallucination-repeat-avg-logprob", type=float, default=-1.0)
    parser.add_argument("--qwen-hallucination-high-risk-max-repeats", type=int, default=2)
    parser.add_argument(
        "--qwen-filter-hallucinations",
        action="store_true",
        help="Apply the Whisper-style hallucination/near-duplicate filters to Qwen output (off by default).",
    )
    anime_group = parser.add_argument_group("Anime ASR")
    add_prefixed_dataclass_arguments(
        anime_group,
        AnimeAsrConfig,
        "anime_",
        skip=ANIME_PREFIX_SKIP,
        default_none=True,
    )
    parser.add_argument("--min-cue-seconds", type=float, default=0.3)
    parser.add_argument(
        "--no-copy-to-video-dir",
        action="store_true",
        help="Do not copy the final subtitle file (SRT, or ASS with --bilingual) next to the input video",
    )
    # Apply --config before parse_args so the file sets defaults for every option while
    # explicit command-line flags still win (precedence: code default < file < CLI).
    config_path = _early_config_path(sys.argv[1:])
    if config_path is not None:
        if not config_path.exists():
            raise SystemExit(f"Missing --config file: {config_path}")
        apply_config_file(parser, config_path)
    args = parser.parse_args()

    validate_runtime_args(args)

    if args.print_config:
        # input/output are per-run IO arguments, not reusable configuration; a config
        # file cannot set the input positional anyway, so emitting them would mislead.
        values = {k: v for k, v in vars(args).items() if k not in ("config", "print_config", "input", "output")}
        sys.stdout.write(format_config_toml(values))
        return

    if args.resume:
        args.reuse_existing_audio = True

    if args.keep_audio:
        print("Warning: --keep-audio is deprecated and has no effect (audio is kept by default).", flush=True)
    if args.lead_out_seconds < 0:
        raise SystemExit("--lead-out-seconds must be >= 0")
    if args.min_display_seconds < 0:
        raise SystemExit("--min-display-seconds must be >= 0")
    if args.display_wrap_max_chars < 0:
        raise SystemExit("--display-wrap-max-chars must be >= 0")
    if args.context_size is not None and args.context_size < 0:
        raise SystemExit("--context-size must be >= 0")
    if shutil.which("ffmpeg") is None:
        raise SystemExit("Missing ffmpeg on PATH; install it (e.g. sudo apt install ffmpeg).")

    if args.asr == "anime":
        anime_cfg = asr_config_for_command(args)
        require_file(Path(anime_cfg.text_model), "anime-whisper model")
        if anime_cfg.timestamp_mode != "vad_only":
            require_file(QWEN_ALIGNER_MODEL, "Qwen3 forced aligner")
        require_file(QWEN_TRANSCRIBE_SCRIPT, "transcription script")
    elif args.asr == "qwen":
        require_file(QWEN_ASR_MODEL, "Qwen3-ASR model")
        require_file(QWEN_ALIGNER_MODEL, "Qwen3 forced aligner")
        require_file(QWEN_TRANSCRIBE_SCRIPT, "Qwen transcription script")
    if args.translator == "sakura":
        require_file(SAKURA_MODEL, "Sakura model")
        require_file(SAKURA_TRANSLATE_SCRIPT, "Sakura translation script")
    elif args.translator == "galtransl":
        require_file(GALTRANSL_MODEL, "GalTransl model")
        require_file(GALTRANSL_TRANSLATE_SCRIPT, "GalTransl translation script")
    require_file(QUALITY_REPORT_SCRIPT, "quality report script")
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

    # Paths derive from the stem only, so videos differing just by extension
    # (a.mp4 + a.mkv) would share one work dir/WAV and one output; the look-ahead
    # extractor would then overwrite the WAV while the previous job still reads it.
    claimed: dict[Path, Path] = {}
    for job in jobs:
        for path in (job.output, job.job_dir):
            other = claimed.setdefault(path, job.video)
            if other != job.video:
                raise SystemExit(
                    f"{other} and {job.video} map to the same path: {path}\n"
                    "Rename one of them (same stem with different extensions is not supported)."
                )

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
