from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from pipeline_configs import AnimeAsrConfig, QwenAsrConfig
from cli_config import config_to_cli_args
from evaluation_core import cache_fingerprint, load_subtitles


PROJECT_ROOT = Path(__file__).resolve().parents[1] if Path(__file__).resolve().parent.name == "scripts" else Path(__file__).resolve().parent
TRANSCRIBE_SCRIPT = PROJECT_ROOT / "scripts" / "transcribe_ja_srt_qwen.py"
BENCHMARK_SCRIPT = PROJECT_ROOT / "scripts" / "subtitle_benchmark.py"
DEFAULT_QWEN_MODEL = PROJECT_ROOT / "models" / "Qwen3-ASR-1.7B"
DEFAULT_ALIGNER = PROJECT_ROOT / "models" / "Qwen3-ForcedAligner-0.6B"


@dataclass(frozen=True)
class Variant:
    name: str
    config: QwenAsrConfig | AnimeAsrConfig


def default_variants() -> list[Variant]:
    """Stage 6.3 comparison matrix.

    qwen_fixed_tiling intentionally disables VAD chunking and Stage 6.1/6.2 additions
    so it remains a measured fixed-window baseline. qwen_wj_core enables only the WJ
    qwen choices already ported into this codebase; it is not a full WhisperJAV qwen
    pipeline clone.
    """
    return [
        Variant(
            "qwen_fixed_tiling",
            QwenAsrConfig(
                vad_chunks=False,
                timestamp_mode="aligner_only",
                collapse_recovery=False,
                vad_backend="whisperseg",
                scene_backend="none",
                max_new_tokens=256,
                repetition_penalty=1.0,
                max_tokens_per_second=0.0,
            ),
        ),
        Variant(
            "qwen_fixed_recovery",
            QwenAsrConfig(
                vad_chunks=False,
                timestamp_mode="aligner_fallback",
                collapse_recovery=True,
                vad_backend="whisperseg",
                scene_backend="none",
                max_new_tokens=256,
                repetition_penalty=1.0,
                max_tokens_per_second=0.0,
            ),
        ),
        Variant(
            "qwen_whisperseg",
            QwenAsrConfig(
                timestamp_mode="aligner_fallback",
                collapse_recovery=True,
                vad_backend="whisperseg",
                scene_backend="none",
                max_new_tokens=256,
                repetition_penalty=1.0,
                max_tokens_per_second=0.0,
            ),
        ),
        Variant(
            "qwen_whisperseg_gen",
            QwenAsrConfig(
                timestamp_mode="aligner_fallback",
                collapse_recovery=True,
                vad_backend="whisperseg",
                scene_backend="none",
                max_new_tokens=4096,
                repetition_penalty=1.1,
                max_tokens_per_second=20.0,
                min_tokens_floor=256,
            ),
        ),
        Variant(
            "qwen_wj_framing",
            QwenAsrConfig(
                timestamp_mode="aligner_fallback",
                collapse_recovery=True,
                vad_backend="whisperseg",
                scene_backend="semantic",
                max_new_tokens=256,
                repetition_penalty=1.0,
                max_tokens_per_second=0.0,
            ),
        ),
        Variant(
            "qwen_wj_core",
            QwenAsrConfig(
                timestamp_mode="aligner_fallback",
                collapse_recovery=True,
                vad_backend="whisperseg",
                scene_backend="semantic",
                max_new_tokens=4096,
                repetition_penalty=1.1,
                max_tokens_per_second=20.0,
                min_tokens_floor=256,
            ),
        ),
        # Stage 6.4 ablation: tighter step-down (fallback 3.0, actually tightens vs the
        # inert WJ-faithful 6.0) crossed with semantic on/off.
        Variant(
            "qwen_wj_sd3",  # aligned WJ-qwen (semantic ON) + real step-down 3.0
            QwenAsrConfig(
                timestamp_mode="aligner_fallback",
                collapse_recovery=True,
                vad_backend="whisperseg",
                scene_backend="semantic",
                max_new_tokens=4096,
                repetition_penalty=1.1,
                max_tokens_per_second=20.0,
                min_tokens_floor=256,
                stepdown=True,
                stepdown_fallback_group=3.0,
            ),
        ),
        Variant(
            "qwen_semoff_sd3",  # semantic OFF + real step-down 3.0
            QwenAsrConfig(
                timestamp_mode="aligner_fallback",
                collapse_recovery=True,
                vad_backend="whisperseg",
                scene_backend="none",
                max_new_tokens=4096,
                repetition_penalty=1.1,
                max_tokens_per_second=20.0,
                min_tokens_floor=256,
                stepdown=True,
                stepdown_fallback_group=3.0,
            ),
        ),
        Variant("anime", AnimeAsrConfig()),
    ]


def selected_variants(names: list[str] | None) -> list[Variant]:
    variants = {variant.name: variant for variant in default_variants()}
    if not names:
        return list(variants.values())
    missing = [name for name in names if name not in variants]
    if missing:
        raise SystemExit(f"Unknown variant(s): {', '.join(missing)}. Available: {', '.join(variants)}")
    return [variants[name] for name in names]


def run(command: list[str], dry_run: bool) -> None:
    print("+ " + " ".join(command), flush=True)
    if not dry_run:
        subprocess.run(command, check=True)


def file_sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def input_identity(path: Path) -> dict:
    if path.is_file():
        return {"path": str(path.resolve()), "sha256": file_sha256(path)}
    if not path.is_dir():
        raise ValueError(f"missing benchmark input/model: {path}")
    files = {str(item.relative_to(path)): file_sha256(item) for item in sorted(path.rglob("*"))
             if item.is_file() and ".cache" not in item.relative_to(path).parts}
    return {"path": str(path.resolve()), "files": files}


def cache_matches(record: Path, fingerprint: str, srt: Path, raw: Path) -> bool:
    try:
        data = json.loads(record.read_text(encoding="utf-8"))
        return (data.get("status") == "complete" and data.get("fingerprint") == fingerprint
                and load_subtitles(srt).status in ("valid", "empty")
                and data["outputs"] == {"srt": file_sha256(srt), "raw": file_sha256(raw)})
    except (OSError, KeyError, ValueError):
        return False


def transcribe_command(args: argparse.Namespace, variant: Variant, output: Path, raw_output: Path) -> list[str]:
    return [
        sys.executable,
        str(TRANSCRIBE_SCRIPT),
        str(args.audio),
        str(output),
        "--model",
        str(args.model),
        "--forced-aligner",
        str(args.forced_aligner),
        "--raw-output",
        str(raw_output),
        *config_to_cli_args(variant.config),
    ]


def benchmark_command(args: argparse.Namespace, candidates: dict[str, Path], output_json: Path) -> list[str] | None:
    if not args.anime_ref or not args.qwen_ref:
        return None
    command = [
        sys.executable,
        str(BENCHMARK_SCRIPT),
        "--anime-ref",
        args.anime_ref,
        "--json-output",
        str(output_json),
    ]
    for item in args.qwen_ref:
        command.extend(["--qwen-ref", item])
    for name, path in candidates.items():
        command.extend(["--cand", f"{name}={path}"])
    return command


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Stage 6.3 qwen/anime ASR benchmark matrix.")
    parser.add_argument("audio", type=Path, help="16 kHz mono WAV to transcribe.")
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "work" / "stage6_benchmark")
    parser.add_argument("--model", type=Path, default=DEFAULT_QWEN_MODEL)
    parser.add_argument("--forced-aligner", type=Path, default=DEFAULT_ALIGNER)
    parser.add_argument("--variant", action="append", help="Variant to run; repeatable. Defaults to all variants.")
    parser.add_argument("--skip-existing", action="store_true", help="Reuse only matching provenance and SRT/raw digests; older unversioned outputs are rejected.")
    parser.add_argument("--dry-run", action="store_true", help="Print commands without running them.")
    parser.add_argument("--anime-ref", help="name=path reference for subtitle_benchmark.py, e.g. WJ-anime=wj.srt")
    parser.add_argument("--qwen-ref", action="append", help="name=path qwen reference for subtitle_benchmark.py; repeatable.")
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    candidates: dict[str, Path] = {}
    manifest = {
        "audio": str(args.audio),
        "variants": [],
        "benchmark_json": str(args.output_dir / "benchmark.json"),
    }
    identities = {}
    runtime = {"python": sys.version, "platform": platform.platform(), "packages": {}}
    if not args.dry_run:
        for name in ("torch", "transformers", "qwen-asr", "onnxruntime-gpu", "librosa"):
            try:
                runtime["packages"][name] = importlib.metadata.version(name)
            except importlib.metadata.PackageNotFoundError:
                runtime["packages"][name] = None

    for variant in selected_variants(args.variant):
        srt = args.output_dir / f"{variant.name}.ja.srt"
        raw = args.output_dir / f"{variant.name}.raw.json"
        candidates[variant.name] = srt
        manifest["variants"].append({
            "name": variant.name,
            "srt": str(srt),
            "raw": str(raw),
            "config": variant.config.__class__.__name__,
        })
        command = transcribe_command(args, variant, srt, raw)
        if args.dry_run:
            run(command, True)
            continue
        inputs = [args.audio, args.forced_aligner, Path(variant.config.whisperseg_model)]
        inputs.append(Path(variant.config.text_model) if isinstance(variant.config, AnimeAsrConfig) else args.model)
        for path in inputs:
            if str(path) not in identities:
                identities[str(path)] = input_identity(path)
        provenance = {"command": command, "inputs": {str(path): identities[str(path)] for path in inputs},
                      "runtime": runtime,
                      "scripts": {path.name: file_sha256(path) for path in sorted((PROJECT_ROOT / "scripts").glob("*.py"))}}
        fingerprint = cache_fingerprint(provenance)
        record_path = args.output_dir / f"{variant.name}.run.json"
        if args.skip_existing and (srt.exists() or raw.exists() or record_path.exists()):
            if cache_matches(record_path, fingerprint, srt, raw):
                print(f"reuse verified cache: {srt}", flush=True)
                continue
            raise SystemExit(f"Unverified/mismatched cache: {srt}. Use a new --output-dir; old outputs are preserved.")
        record = {"status": "running", "fingerprint": fingerprint, "provenance": provenance}
        record_path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        run(command, False)
        if load_subtitles(srt).status not in ("valid", "empty"):
            raise SystemExit(f"Invalid benchmark output: {srt}")
        json.loads(raw.read_text(encoding="utf-8"))
        record.update(status="complete", outputs={"srt": file_sha256(srt), "raw": file_sha256(raw)})
        record_path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    bench = benchmark_command(args, candidates, args.output_dir / "benchmark.json")
    if bench is not None:
        run(bench, args.dry_run)
    else:
        print("No --anime-ref/--qwen-ref supplied; skipping subtitle_benchmark.py scoring.", flush=True)

    manifest_path = args.output_dir / "manifest.json"
    if not args.dry_run:
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Manifest: {manifest_path}", flush=True)


if __name__ == "__main__":
    main()
