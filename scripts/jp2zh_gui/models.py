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


PROJECT_ROOT = project_root(Path(__file__))
PIPELINE_SCRIPT = scripts_dir(Path(__file__)) / "video_to_zh_srt.py"


class AsrPreset(StrEnum):
    ANIME = "anime"
    QWEN = "qwen"


class TranslatorPreset(StrEnum):
    GALTRANSL = "galtransl"
    SAKURA = "sakura"


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


ASR_LABELS = {
    AsrPreset.ANIME: "Anime（推荐）",
    AsrPreset.QWEN: "Qwen",
}
TRANSLATOR_LABELS = {
    TranslatorPreset.GALTRANSL: "GalTransl 7B（推荐）",
    TranslatorPreset.SAKURA: "Sakura 14B",
}
CLEANUP_LABELS = {
    CleanupPolicy.KEEP_ALL: "保留全部中间产物",
    CleanupPolicy.DELETE_AUDIO: "成功后删除 WAV",
    CleanupPolicy.FINAL_ONLY: "成功后仅保留最终字幕、质检和日志",
}
STATUS_LABELS = {
    TaskStatus.WAITING: "等待中",
    TaskStatus.RUNNING: "处理中",
    TaskStatus.COMPLETED: "已完成",
    TaskStatus.FAILED: "失败",
    TaskStatus.CANCELLED: "已取消",
}
STAGE_LABELS = {
    "extract": "提取音频",
    "asr": "日语识别",
    "translate": "中文翻译",
    "ass": "生成 ASS",
    "quality": "质量检查",
    "cleanup": "清理中间产物",
}
STAGE_PROGRESS_RANGES = {
    "extract": (0.00, 0.05),
    "asr": (0.05, 0.60),
    "translate": (0.60, 0.92),
    "ass": (0.92, 0.96),
    "quality": (0.96, 0.99),
    "cleanup": (0.99, 1.00),
}


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
    bilingual: bool = True
    quality_report: bool = False
    resume: bool = False
    copy_to_video_dir: bool = True
    cleanup_policy: CleanupPolicy = CleanupPolicy.KEEP_ALL
    asr_batch_size: int = 24
    context_size: int = 6
    translate_batch_size: int = 8
    display_wrap_max_chars: int = 20
    bilingual_font: str = "Microsoft YaHei"
    bilingual_zh_font_size: int = 36
    bilingual_ja_font_size: int = 24
    bilingual_zh_colour: str = "&H0000FFFF"
    bilingual_ja_colour: str = "&H00B4B4B4"
    bilingual_male_colour: str = "&H00FFBF00"
    bilingual_female_colour: str = "&H00B478FF"
    colour_by_speaker: bool = False

    def validate(self) -> list[str]:
        errors: list[str] = []
        if self.asr_batch_size <= 0:
            errors.append("ASR 批大小必须大于 0")
        if self.context_size < 0:
            errors.append("翻译上下文不能小于 0")
        if self.translate_batch_size < 0:
            errors.append("翻译批大小不能小于 0")
        if self.display_wrap_max_chars < 0:
            errors.append("每行最大字符数不能小于 0")
        if self.bilingual_zh_font_size <= 0 or self.bilingual_ja_font_size <= 0:
            errors.append("字幕字号必须大于 0")
        if not self.bilingual_font.strip():
            errors.append("字幕字体不能为空")
        for label, value in (
            ("中文颜色", self.bilingual_zh_colour),
            ("日文颜色", self.bilingual_ja_colour),
            ("男性颜色", self.bilingual_male_colour),
            ("女性颜色", self.bilingual_female_colour),
        ):
            if not re.fullmatch(r"&H[0-9A-Fa-f]{8}", value):
                errors.append(f"{label}必须使用 ASS &HAABBGGRR 格式")
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
            raise ValueError("；".join(errors))
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
            "--cleanup-policy", self.cleanup_policy.value,
            f"--{self.asr.value}-batch-size", str(self.asr_batch_size),
            "--context-size", str(self.context_size),
            "--translate-batch-size", str(self.translate_batch_size),
            "--display-wrap-max-chars", str(self.display_wrap_max_chars),
            "--bilingual-font", self.bilingual_font,
            "--bilingual-zh-font-size", str(self.bilingual_zh_font_size),
            "--bilingual-ja-font-size", str(self.bilingual_ja_font_size),
            "--bilingual-zh-colour", self.bilingual_zh_colour,
            "--bilingual-ja-colour", self.bilingual_ja_colour,
            "--bilingual-male-colour", self.bilingual_male_colour,
            "--bilingual-female-colour", self.bilingual_female_colour,
        ]
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
    detail: str = ""
    error: str = ""
    outputs: dict[str, Path] = field(default_factory=dict)

    @property
    def status_text(self) -> str:
        if self.status == TaskStatus.RUNNING and self.stage:
            return self.detail or STAGE_LABELS.get(self.stage, self.stage)
        return STATUS_LABELS[self.status]

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
        self.detail = ""
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
