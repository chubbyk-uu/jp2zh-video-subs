from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from pipeline_configs import AnimeAsrConfig, QwenAsrConfig
from cli_config import config_to_cli_args


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

    qwen_current intentionally disables the Stage 6.1/6.2 additions so it remains a
    measured baseline. qwen_wj_core enables only the WJ qwen choices already ported
    into this codebase; it is not a full WhisperJAV qwen pipeline clone.
    """
    return [
        Variant(
            "qwen_current",
            QwenAsrConfig(
                timestamp_mode="aligner_only",
                collapse_recovery=False,
                vad_backend="current",
                scene_backend="none",
                max_new_tokens=256,
                repetition_penalty=1.0,
                max_tokens_per_second=0.0,
            ),
        ),
        Variant(
            "qwen_recovery",
            QwenAsrConfig(
                timestamp_mode="aligner_fallback",
                collapse_recovery=True,
                vad_backend="current",
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
    parser.add_argument("--skip-existing", action="store_true", help="Reuse existing variant SRT/raw outputs.")
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
        if args.skip_existing and srt.exists() and srt.stat().st_size > 0:
            print(f"skip existing: {srt}", flush=True)
            continue
        run(transcribe_command(args, variant, srt, raw), args.dry_run)

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
