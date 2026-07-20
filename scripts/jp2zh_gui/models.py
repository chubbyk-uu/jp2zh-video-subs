"""Qt-independent GUI configuration, task state, and model discovery."""
from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Iterable
from uuid import uuid4

from pipeline_runtime import PIPELINE_STAGES, VIDEO_EXTENSIONS
from portable_runtime import project_root, scripts_dir
from target_languages import (
    DEFAULT_BATCH_SIZE_BY_TRANSLATOR,
    DEFAULT_CONTEXT_SIZE,
    DEFAULT_WRAP_CHARS_BY_TARGET,
    TargetLanguage,
    translator_supports_target,
)


PROJECT_ROOT = project_root(Path(__file__))
PIPELINE_SCRIPT = scripts_dir(Path(__file__)) / "video_to_zh_srt.py"


class AsrPreset(StrEnum):
    ANIME = "anime"
    QWEN = "qwen"


class TranslatorPreset(StrEnum):
    GALTRANSL = "galtransl"
    SAKURA = "sakura"
    SUGOI = "sugoi"


class CleanupPolicy(StrEnum):
    KEEP_ALL = "keep_all"
    DELETE_AUDIO = "delete_audio"
    FINAL_ONLY = "final_only"


class TaskStatus(StrEnum):
    WAITING = "waiting"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


STAGE_PROGRESS_RANGES = {
    "extract": (0.00, 0.05),
    "asr": (0.05, 0.60),
    "translate": (0.60, 0.92),
    "ass": (0.92, 0.96),
    "quality": (0.96, 0.99),
    "cleanup": (0.99, 1.00),
}


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    params: dict[str, object] = field(default_factory=dict)


MODEL_REQUIREMENTS = {
    AsrPreset.ANIME: (
        "models/anime-whisper/config.json",
        "models/anime-whisper/model.safetensors",
        "models/whisperseg/model.onnx",
        "models/Qwen3-ForcedAligner-0.6B/config.json",
        "models/Qwen3-ForcedAligner-0.6B/model.safetensors",
    ),
    AsrPreset.QWEN: (
        "models/Qwen3-ASR-1.7B/config.json",
        "models/Qwen3-ASR-1.7B/model.safetensors.index.json",
        "models/Qwen3-ASR-1.7B/model-00001-of-00002.safetensors",
        "models/Qwen3-ASR-1.7B/model-00002-of-00002.safetensors",
        "models/Qwen3-ForcedAligner-0.6B/config.json",
        "models/Qwen3-ForcedAligner-0.6B/model.safetensors",
        "models/whisperseg/model.onnx",
    ),
    TranslatorPreset.GALTRANSL: (
        "models/Sakura-GalTransl-7B-v3.7-GGUF/Sakura-Galtransl-7B-v3.7.gguf",
    ),
    TranslatorPreset.SAKURA: (
        "models/Sakura-14B-Qwen2.5-v1.0-GGUF/sakura-14b-qwen2.5-v1.0-iq4xs.gguf",
    ),
    TranslatorPreset.SUGOI: (
        "models/Sugoi-14B-Ultra-GGUF/Sugoi-14B-Ultra-Q4_K_M.gguf",
    ),
}
GENDER_MODEL_REQUIREMENTS = (
    "models/voice-gender-classifier/config.json",
    "models/voice-gender-classifier/model.safetensors",
)


@dataclass
class GuiConfig:
    output_dir: Path = PROJECT_ROOT / "outputs"
    work_dir: Path = PROJECT_ROOT / "work"
    recursive: bool = False
    asr: AsrPreset = AsrPreset.ANIME
    translator: TranslatorPreset = TranslatorPreset.GALTRANSL
    target_language: TargetLanguage = TargetLanguage.SIMPLIFIED_CHINESE
    bilingual: bool = True
    quality_report: bool = False
    resume: bool = False
    copy_to_video_dir: bool = True
    cleanup_policy: CleanupPolicy = CleanupPolicy.KEEP_ALL
    asr_batch_size: int = 24
    context_size: int = DEFAULT_CONTEXT_SIZE
    translate_batch_size: int = DEFAULT_BATCH_SIZE_BY_TRANSLATOR["galtransl"]
    display_wrap_max_chars: int = DEFAULT_WRAP_CHARS_BY_TARGET[TargetLanguage.SIMPLIFIED_CHINESE]
    bilingual_font: str = "Microsoft YaHei"
    bilingual_ja_font: str = "Microsoft YaHei"
    bilingual_zh_font_size: int = 36
    bilingual_ja_font_size: int = 24
    bilingual_zh_colour: str = "&H0000FFFF"
    bilingual_ja_colour: str = "&H00B4B4B4"
    bilingual_male_colour: str = "&H00FFBF00"
    bilingual_female_colour: str = "&H00B478FF"
    colour_by_speaker: bool = False

    def validate(self) -> list[ValidationIssue]:
        errors: list[ValidationIssue] = []
        if not translator_supports_target(self.translator.value, self.target_language):
            errors.append(ValidationIssue("translator_target_incompatible"))
        if self.asr_batch_size <= 0:
            errors.append(ValidationIssue("asr_batch_positive"))
        if self.context_size < 0:
            errors.append(ValidationIssue("context_nonnegative"))
        if self.translate_batch_size < 0:
            errors.append(ValidationIssue("translate_batch_nonnegative"))
        if self.display_wrap_max_chars < 0:
            errors.append(ValidationIssue("wrap_nonnegative"))
        if self.bilingual_zh_font_size <= 0 or self.bilingual_ja_font_size <= 0:
            errors.append(ValidationIssue("subtitle_size_positive"))
        if not self.bilingual_font.strip() or not self.bilingual_ja_font.strip():
            errors.append(ValidationIssue("subtitle_font_required"))
        for field_name, value in (
            ("zh", self.bilingual_zh_colour),
            ("ja", self.bilingual_ja_colour),
            ("male", self.bilingual_male_colour),
            ("female", self.bilingual_female_colour),
        ):
            if not re.fullmatch(r"&H[0-9A-Fa-f]{8}", value):
                errors.append(ValidationIssue("ass_colour_format", {"field": field_name}))
        return errors

    def build_command(
        self,
        input_path: Path,
        event_log: Path,
        cancel_file: Path,
        *,
        python_executable: Path | str = sys.executable,
        pipeline_script: Path = PIPELINE_SCRIPT,
    ) -> list[str]:
        errors = self.validate()
        if errors:
            raise ValueError("; ".join(issue.code for issue in errors))
        command = [
            str(python_executable),
            str(pipeline_script),
            str(input_path),
            "--output-dir", str(self.output_dir),
            "--work-dir", str(self.work_dir),
            "--event-log", str(event_log),
            "--cancel-file", str(cancel_file),
            "--asr", self.asr.value,
            "--translator", self.translator.value,
            "--target-language", self.target_language.value,
            "--cleanup-policy", self.cleanup_policy.value,
            f"--{self.asr.value}-batch-size", str(self.asr_batch_size),
            "--translate-batch-size", str(self.translate_batch_size),
            "--display-wrap-max-chars", str(self.display_wrap_max_chars),
            "--bilingual-font", self.bilingual_font,
            "--bilingual-ja-font", self.bilingual_ja_font,
            "--bilingual-zh-font-size", str(self.bilingual_zh_font_size),
            "--bilingual-ja-font-size", str(self.bilingual_ja_font_size),
            "--bilingual-zh-colour", self.bilingual_zh_colour,
            "--bilingual-ja-colour", self.bilingual_ja_colour,
            "--bilingual-male-colour", self.bilingual_male_colour,
            "--bilingual-female-colour", self.bilingual_female_colour,
        ]
        if self.translator != TranslatorPreset.SUGOI:
            command.extend(("--context-size", str(self.context_size)))
        if self.recursive:
            command.append("--recursive")
        if not self.bilingual:
            command.append("--no-bilingual")
        if self.quality_report:
            command.append("--quality-report")
        if self.resume:
            command.append("--resume")
        if not self.copy_to_video_dir:
            command.append("--no-copy-to-video-dir")
        if self.colour_by_speaker:
            command.append("--colour-by-speaker")
        return command


@dataclass
class GuiTask:
    video: Path
    task_id: str = field(default_factory=lambda: uuid4().hex)
    status: TaskStatus = TaskStatus.WAITING
    stage: str | None = None
    stage_index: int = 0
    stage_total: int = len(PIPELINE_STAGES)
    completed_stages: int = 0
    stage_progress: float = 0.0
    detail_key: str = ""
    detail_args: dict[str, object] = field(default_factory=dict)
    detail: str = ""
    error_key: str = ""
    error_args: dict[str, object] = field(default_factory=dict)
    error: str = ""
    outputs: dict[str, Path] = field(default_factory=dict)

    @property
    def progress_percent(self) -> int:
        if self.status == TaskStatus.COMPLETED:
            return 100
        if self.stage in STAGE_PROGRESS_RANGES:
            start, end = STAGE_PROGRESS_RANGES[self.stage]
            value = start + (end - start) * self.stage_progress
            return max(0, min(99, round(100 * value)))
        if self.status in (TaskStatus.FAILED, TaskStatus.CANCELLED):
            return max(0, min(99, round(100 * self.completed_stages / self.stage_total)))
        return 0

    def reset_for_retry(self) -> None:
        self.status = TaskStatus.WAITING
        self.stage = None
        self.stage_index = 0
        self.completed_stages = 0
        self.stage_progress = 0.0
        self.detail_key = ""
        self.detail_args.clear()
        self.detail = ""
        self.error_key = ""
        self.error_args.clear()
        self.error = ""
        self.outputs.clear()


def discover_dropped_videos(paths: Iterable[Path], recursive: bool) -> list[Path]:
    """Expand dropped files/directories into a stable, de-duplicated video list."""
    videos: list[Path] = []
    seen: set[str] = set()
    for raw_path in paths:
        path = raw_path.expanduser().resolve()
        if path.is_file():
            candidates = [path] if path.suffix.lower() in VIDEO_EXTENSIONS else []
        elif path.is_dir():
            iterator = path.rglob("*") if recursive else path.iterdir()
            candidates = sorted(
                (item.resolve() for item in iterator if item.is_file() and item.suffix.lower() in VIDEO_EXTENSIONS),
                key=lambda item: str(item).lower(),
            )
        else:
            candidates = []
        for candidate in candidates:
            key = os.path.normcase(str(candidate))
            if key not in seen:
                seen.add(key)
                videos.append(candidate)
    return videos


def missing_model_files(config: GuiConfig, project_root: Path = PROJECT_ROOT) -> list[Path]:
    required = [*MODEL_REQUIREMENTS[config.asr], *MODEL_REQUIREMENTS[config.translator]]
    if config.colour_by_speaker:
        required.extend(GENDER_MODEL_REQUIREMENTS)
    return [project_root / relative for relative in required if not (project_root / relative).is_file()]
