"""Single source of truth for downloadable model locations and requirements."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Iterable


class ModelInstallState(StrEnum):
    INSTALLED = "installed"
    PARTIAL = "partial"
    MISSING = "missing"


@dataclass(frozen=True)
class ModelDownloadSpec:
    key: str
    name: str
    repo_id: str
    local_dir: str
    required_files: tuple[str, ...]
    filenames: tuple[str, ...] = ()
    revision: str | None = None
    optional: bool = False
    experimental: bool = False

    def destination(self, root: Path) -> Path:
        return root / self.local_dir

    def required_paths(self, root: Path) -> tuple[Path, ...]:
        destination = self.destination(root)
        return tuple(destination / relative for relative in self.required_files)


MODEL_DOWNLOAD_SPECS = (
    ModelDownloadSpec(
        key="anime-whisper",
        name="Anime Whisper",
        repo_id="litagin/anime-whisper",
        local_dir="models/anime-whisper",
        filenames=(
            "added_tokens.json",
            "config.json",
            "generation_config.json",
            "merges.txt",
            "model.safetensors",
            "normalizer.json",
            "preprocessor_config.json",
            "special_tokens_map.json",
            "tokenizer_config.json",
            "vocab.json",
        ),
        revision="22e2008a8182b357da3922a6308d095008f72973",
        required_files=(
            "config.json",
            "model.safetensors",
            "preprocessor_config.json",
            "tokenizer_config.json",
            "merges.txt",
            "vocab.json",
        ),
    ),
    ModelDownloadSpec(
        key="whisperseg",
        name="WhisperSeg",
        repo_id="TransWithAI/Whisper-Vad-EncDec-ASMR-onnx",
        local_dir="models/whisperseg",
        filenames=("model.onnx",),
        revision="6ac29e2cbf2f4f8e9b639861766a8639dd666e9c",
        required_files=("model.onnx",),
    ),
    ModelDownloadSpec(
        key="qwen-forced-aligner",
        name="Qwen3 Forced Aligner 0.6B",
        repo_id="Qwen/Qwen3-ForcedAligner-0.6B",
        local_dir="models/Qwen3-ForcedAligner-0.6B",
        filenames=(
            "chat_template.json",
            "config.json",
            "generation_config.json",
            "merges.txt",
            "model.safetensors",
            "preprocessor_config.json",
            "tokenizer_config.json",
            "vocab.json",
        ),
        revision="c7cbfc2048c462b0d63a45797104fc9db3ad62b7",
        required_files=(
            "config.json",
            "model.safetensors",
            "preprocessor_config.json",
            "tokenizer_config.json",
            "merges.txt",
            "vocab.json",
        ),
    ),
    ModelDownloadSpec(
        key="galtransl-7b",
        name="GalTransl 7B",
        repo_id="SakuraLLM/Sakura-GalTransl-7B-v3.7",
        local_dir="models/Sakura-GalTransl-7B-v3.7-GGUF",
        filenames=("Sakura-Galtransl-7B-v3.7.gguf",),
        revision="759d76b1745f4428308de6564c5ab710d4358b2e",
        required_files=("Sakura-Galtransl-7B-v3.7.gguf",),
    ),
    ModelDownloadSpec(
        key="qwen-asr-1.7b",
        name="Qwen3 ASR 1.7B",
        repo_id="Qwen/Qwen3-ASR-1.7B",
        local_dir="models/Qwen3-ASR-1.7B",
        filenames=(
            "chat_template.json",
            "config.json",
            "generation_config.json",
            "merges.txt",
            "model-00001-of-00002.safetensors",
            "model-00002-of-00002.safetensors",
            "model.safetensors.index.json",
            "preprocessor_config.json",
            "tokenizer_config.json",
            "vocab.json",
        ),
        revision="7278e1e70fe206f11671096ffdd38061171dd6e5",
        required_files=(
            "config.json",
            "model.safetensors.index.json",
            "model-00001-of-00002.safetensors",
            "model-00002-of-00002.safetensors",
            "preprocessor_config.json",
            "tokenizer_config.json",
            "merges.txt",
            "vocab.json",
        ),
        optional=True,
    ),
    ModelDownloadSpec(
        key="sakura-14b",
        name="Sakura 14B",
        repo_id="SakuraLLM/Sakura-14B-Qwen2.5-v1.0-GGUF",
        local_dir="models/Sakura-14B-Qwen2.5-v1.0-GGUF",
        filenames=("sakura-14b-qwen2.5-v1.0-iq4xs.gguf",),
        revision="f370f85114971e556ba9ab7cdfd00fe9fe88dd53",
        required_files=("sakura-14b-qwen2.5-v1.0-iq4xs.gguf",),
        optional=True,
    ),
    ModelDownloadSpec(
        key="sugoi-14b",
        name="Sugoi 14B Ultra",
        repo_id="sugoitoolkit/Sugoi-14B-Ultra-GGUF",
        local_dir="models/Sugoi-14B-Ultra-GGUF",
        filenames=("Sugoi-14B-Ultra-Q4_K_M.gguf",),
        revision="d8dd836bf519a604530779cbf5ce13ffb35c3eeb",
        required_files=("Sugoi-14B-Ultra-Q4_K_M.gguf",),
        optional=True,
        experimental=True,
    ),
    ModelDownloadSpec(
        key="speaker-gender",
        name="Speaker Gender Classifier",
        repo_id="JaesungHuh/voice-gender-classifier",
        local_dir="models/voice-gender-classifier",
        filenames=("config.json", "model.safetensors"),
        revision="db1222153bd60337e900be22add7af180452adc0",
        required_files=("config.json", "model.safetensors"),
        optional=True,
    ),
)

MODEL_SPEC_BY_KEY = {spec.key: spec for spec in MODEL_DOWNLOAD_SPECS}
MODEL_DOWNLOAD_ENDPOINTS = {
    "official": "https://huggingface.co",
    "mirror": "https://hf-mirror.com",
}
MODEL_KEYS_BY_ASR = {
    "anime": ("anime-whisper", "whisperseg", "qwen-forced-aligner"),
    "qwen": ("qwen-asr-1.7b", "whisperseg", "qwen-forced-aligner"),
}
MODEL_KEYS_BY_TRANSLATOR = {
    "galtransl": ("galtransl-7b",),
    "sakura": ("sakura-14b",),
    "sugoi": ("sugoi-14b",),
}


def model_specs(keys: Iterable[str]) -> tuple[ModelDownloadSpec, ...]:
    requested = set(keys)
    unknown = requested.difference(MODEL_SPEC_BY_KEY)
    if unknown:
        raise ValueError(f"Unknown model keys: {', '.join(sorted(unknown))}")
    return tuple(spec for spec in MODEL_DOWNLOAD_SPECS if spec.key in requested)


def required_model_keys(
    asr: str,
    translator: str,
    *,
    colour_by_speaker: bool = False,
) -> tuple[str, ...]:
    try:
        keys = [*MODEL_KEYS_BY_ASR[asr], *MODEL_KEYS_BY_TRANSLATOR[translator]]
    except KeyError as exc:
        raise ValueError(f"Unknown model preset: {exc.args[0]}") from exc
    if colour_by_speaker:
        keys.append("speaker-gender")
    return tuple(dict.fromkeys(keys))


def required_model_paths(
    root: Path,
    asr: str,
    translator: str,
    *,
    colour_by_speaker: bool = False,
) -> tuple[Path, ...]:
    keys = required_model_keys(
        asr,
        translator,
        colour_by_speaker=colour_by_speaker,
    )
    return tuple(path for spec in model_specs(keys) for path in spec.required_paths(root))


def model_install_state(spec: ModelDownloadSpec, root: Path) -> ModelInstallState:
    destination = spec.destination(root)
    if destination.is_dir() and any(
        path.is_file() for path in destination.rglob("*.incomplete")
    ):
        return ModelInstallState.PARTIAL

    required = spec.required_paths(root)
    if required and all(path.is_file() and path.stat().st_size > 0 for path in required):
        return ModelInstallState.INSTALLED

    if not destination.is_dir():
        return ModelInstallState.MISSING
    for path in destination.rglob("*"):
        if not path.is_file() or path.stat().st_size <= 0:
            continue
        if path.suffix == ".incomplete" or ".cache" not in path.relative_to(destination).parts:
            return ModelInstallState.PARTIAL
    return ModelInstallState.MISSING
