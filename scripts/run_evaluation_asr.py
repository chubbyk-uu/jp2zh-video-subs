"""Run Linux pilot ASR baselines, preserving raw outputs and exact provenance."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path

from cli_config import config_to_cli_args
from evaluation_core import Cue, cache_fingerprint, load_subtitles
from pipeline_configs import AnimeAsrConfig, QwenAsrConfig
from prepare_evaluation_samples import excerpt, write_srt

ROOT = Path(__file__).resolve().parents[1]


def artifact_hashes(directory: Path, sample_ids: list[str]) -> dict:
    artifacts = {}
    for name in ["combined.srt", "raw.json", *(f"{sample_id}.srt" for sample_id in sample_ids)]:
        with (directory / name).open("rb") as stream:
            artifacts[name] = hashlib.file_digest(stream, "sha256").hexdigest()
    return artifacts


def cache_matches(record: dict, fingerprint: str, directory: Path, sample_ids: list[str]) -> bool:
    try:
        return (record.get("status") == "complete" and record.get("fingerprint") == fingerprint
                and record.get("artifact_sha256") == artifact_hashes(directory, sample_ids))
    except OSError:
        return False


def model_identity(directory: Path) -> dict:
    files = {}
    for path in sorted(directory.iterdir()):
        if path.is_file() and path.suffix in (".json", ".safetensors", ".onnx", ".txt"):
            with path.open("rb") as stream:
                files[path.name] = {"bytes": path.stat().st_size,
                                    "sha256": hashlib.file_digest(stream, "sha256").hexdigest()}
    if not files:
        raise ValueError(f"no model files found in {directory}")
    return {"directory": str(directory), "files": files}


def run(args) -> int:
    manifest = json.loads((args.pilot / "manifest.json").read_text(encoding="utf-8"))
    audio = args.pilot / "pilot.wav"
    with audio.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != manifest["combined_audio_sha256"]:
            raise ValueError("pilot audio changed since manifest creation")
    runtime = {"python": sys.version, "platform": platform.platform(), "packages": {},
               "numba_cache_dir": os.environ.get("NUMBA_CACHE_DIR")}
    for name in ("torch", "transformers", "qwen-asr", "onnxruntime-gpu", "librosa"):
        try:
            runtime["packages"][name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            runtime["packages"][name] = None
    gpu = subprocess.run(["nvidia-smi", "--query-gpu=name,driver_version,memory.total", "--format=csv,noheader"],
                         capture_output=True, text=True, check=True)
    runtime["gpu"] = gpu.stdout.strip()
    print("Hashing shared VAD and aligner weights", flush=True)
    shared = {"vad": model_identity(args.model_root / "whisperseg"),
              "aligner": model_identity(args.model_root / "Qwen3-ForcedAligner-0.6B")}
    failed = False
    for backend in args.backends:
        model_path = args.model_root / ("anime-whisper" if backend == "anime" else "Qwen3-ASR-1.7B")
        if backend == "qwen" and args.qwen_model is not None:
            model_path = args.qwen_model
        print(f"Hashing {backend} model files", flush=True)
        weights = model_identity(model_path)
        config = AnimeAsrConfig() if backend == "anime" else QwenAsrConfig()
        config.text_model = str(model_path) if backend == "anime" else str(args.model_root / "anime-whisper")
        config.whisperseg_model = str(args.model_root / "whisperseg" / "model.onnx")
        # Top-level CLI overrides this shared cue floor too.
        config.min_cue_seconds = 0.3
        directory = args.pilot / "runs" / f"{args.run_name}-{backend}"
        directory.mkdir(parents=True, exist_ok=True)
        output, raw = directory / "combined.srt", directory / "raw.json"
        command = [sys.executable, str(ROOT / "scripts/transcribe_ja_srt_qwen.py"), str(audio), str(output),
                   "--model", str(model_path if backend == "qwen" else args.model_root / "Qwen3-ASR-1.7B"),
                   "--forced-aligner", str(args.model_root / "Qwen3-ForcedAligner-0.6B"),
                   "--raw-output", str(raw), *config_to_cli_args(config)]
        provenance = {"input_sha256": manifest["combined_audio_sha256"], "model": weights,
                      "shared_models": shared, "runtime": runtime, "command": command,
                      "script_sha256": hashlib.sha256((ROOT / "scripts/transcribe_ja_srt_qwen.py").read_bytes()).hexdigest(),
                      "config_module_sha256": hashlib.sha256((ROOT / "scripts/pipeline_configs.py").read_bytes()).hexdigest(),
                      "script_dependencies": {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                                              for path in sorted((ROOT / "scripts").glob("*.py"))}}
        fingerprint = cache_fingerprint(provenance)
        record_path = directory / "run.json"
        if record_path.exists():
            old = json.loads(record_path.read_text(encoding="utf-8"))
            if cache_matches(old, fingerprint, directory, [sample["id"] for sample in manifest["samples"]]):
                print(f"{backend}: exact cache match; reuse", flush=True)
                continue
            raise ValueError(f"existing run does not match; choose a new --run-name: {directory}")
        record = {"schema_version": 1, "fingerprint": fingerprint, "provenance": provenance, "status": "running"}
        record_path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        started = time.monotonic()
        print(f"Running {backend}; log: {directory / 'inference.log'}", flush=True)
        peak_gpu_used = 0
        with (directory / "inference.log").open("w", encoding="utf-8") as log:
            process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
            while process.poll() is None:
                try:
                    usage = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                                           capture_output=True, text=True, timeout=5, check=True)
                    peak_gpu_used = max(peak_gpu_used, int(usage.stdout.strip().splitlines()[0]))
                except (ValueError, OSError, subprocess.SubprocessError):
                    pass
                try:
                    process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    pass
        parsed = load_subtitles(output)
        record.update(returncode=process.returncode, elapsed_s=time.monotonic() - started,
                      input_audio_seconds=max(s["combined_end_s"] for s in manifest["samples"]),
                      output_status=parsed.status, output_sha256=parsed.sha256,
                      gpu_peak_total_used_mib=peak_gpu_used, gpu_memory_metric="total device use, sampled approximately every second",
                      status="processing_outputs" if process.returncode == 0 and parsed.status in ("valid", "empty") else "failed")
        record["audio_time_ratio"] = record["elapsed_s"] / record["input_audio_seconds"]
        record_path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if record["status"] == "failed":
            print(f"{backend}: failed; inspect inference.log", flush=True)
            failed = True
            continue
        for sample in manifest["samples"]:
            cues = excerpt(parsed.cues, sample["combined_start_s"], sample["combined_end_s"])
            cues = [Cue(str(i), cue.start, cue.end, cue.text) for i, cue in enumerate(cues, 1)]
            write_srt(directory / f"{sample['id']}.srt", cues)
        json.loads(raw.read_text(encoding="utf-8"))
        record["artifact_sha256"] = artifact_hashes(directory, [sample["id"] for sample in manifest["samples"]])
        record["status"] = "complete"
        record_path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"{backend}: {len(parsed.cues)} cues; {record['elapsed_s']:.1f}s elapsed", flush=True)
    return int(failed)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pilot", type=Path, required=True)
    parser.add_argument("--model-root", type=Path, required=True)
    parser.add_argument("--backends", nargs="+", choices=("anime", "qwen"), default=["anime", "qwen"])
    parser.add_argument("--qwen-model", type=Path)
    parser.add_argument("--run-name", default="baseline")
    args = parser.parse_args()
    if not re_safe_run_name(args.run_name):
        parser.error("run-name must contain only letters, digits, hyphens or underscores")
    raise SystemExit(run(args))


def re_safe_run_name(value: str) -> bool:
    return bool(value) and all(char.isascii() and (char.isalnum() or char in "-_") for char in value)


if __name__ == "__main__":
    main()
