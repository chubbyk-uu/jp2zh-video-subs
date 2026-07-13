from __future__ import annotations

import argparse
import json
import math
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from alignment_recovery import assess_alignment_quality, items_to_words
from pipeline_configs import QwenAsrConfig
from transcribe_ja_srt_qwen import (
    DEFAULT_ALIGNER,
    DEFAULT_MODEL,
    build_whisperseg_jobs,
    load_full_audio,
)


@dataclass
class TokenBudgetDecision:
    clip_seconds: list[float]
    max_new_tokens: int
    max_tokens_per_second: float
    min_tokens_floor: int
    per_clip: list[int]
    batch_budget: int
    recommendation: str


def resolve_generation_config(model: Any) -> tuple[Any | None, str]:
    """Find the HF GenerationConfig used by qwen-asr's transformers backend."""
    candidates = [
        ("model.model.thinker.generation_config", ("model", "thinker", "generation_config")),
        ("model.model.generation_config", ("model", "generation_config")),
        ("model.generation_config", ("generation_config",)),
    ]
    for label, attrs in candidates:
        obj = model
        try:
            for attr in attrs:
                obj = getattr(obj, attr)
        except AttributeError:
            continue
        if obj is not None:
            return obj, label
    return None, "missing"


def apply_repetition_penalty_probe(model: Any, penalty: float) -> dict:
    config, path = resolve_generation_config(model)
    if config is None:
        return {"applied": False, "path": path, "value": None}
    setattr(config, "repetition_penalty", penalty)
    return {"applied": True, "path": path, "value": getattr(config, "repetition_penalty", None)}


def dynamic_token_budget(
    clip_seconds: float,
    max_new_tokens: int,
    max_tokens_per_second: float,
    min_tokens_floor: int = 256,
) -> int:
    if max_tokens_per_second <= 0 or clip_seconds <= 0:
        return int(max_new_tokens)
    return min(int(max_new_tokens), max(int(min_tokens_floor), math.ceil(clip_seconds * max_tokens_per_second)))


def decide_batch_token_budget(
    clip_seconds: list[float],
    max_new_tokens: int,
    max_tokens_per_second: float,
    min_tokens_floor: int = 256,
) -> TokenBudgetDecision:
    per_clip = [
        dynamic_token_budget(sec, max_new_tokens, max_tokens_per_second, min_tokens_floor)
        for sec in clip_seconds
    ]
    batch_budget = max(per_clip, default=int(max_new_tokens))
    recommendation = "disabled"
    if max_tokens_per_second > 0 and clip_seconds:
        recommendation = "per_batch_max" if len(set(per_clip)) == 1 else "group_by_budget_or_batch1"
    return TokenBudgetDecision(
        clip_seconds=clip_seconds,
        max_new_tokens=int(max_new_tokens),
        max_tokens_per_second=float(max_tokens_per_second),
        min_tokens_floor=int(min_tokens_floor),
        per_clip=per_clip,
        batch_budget=batch_budget,
        recommendation=recommendation,
    )


def item_time_range(items: Any) -> dict:
    words = items_to_words(items)
    if not words:
        return {"count": 0, "min_start": None, "max_end": None}
    return {
        "count": len(words),
        "min_start": min(w["start"] for w in words),
        "max_end": max(w["end"] for w in words),
    }


def items_are_clip_relative(items: Any, clip_duration: float, tolerance: float = 0.05) -> bool | None:
    times = item_time_range(items)
    if times["count"] == 0:
        return None
    return (
        times["min_start"] >= -tolerance
        and times["max_end"] <= clip_duration + tolerance
    )


def _probe_args(args: argparse.Namespace) -> SimpleNamespace:
    cfg = QwenAsrConfig(
        vad_backend="whisperseg",
        scene_backend=args.scene_backend,
        whisperseg_model=str(args.whisperseg_model),
        whisperseg_threshold=args.whisperseg_threshold,
        whisperseg_max_speech=args.whisperseg_max_speech,
        whisperseg_hard_max_speech=args.whisperseg_hard_max_speech,
        whisperseg_soft_split_lookback=args.whisperseg_soft_split_lookback,
        whisperseg_max_group=args.whisperseg_max_group,
        whisperseg_chunk_threshold=args.whisperseg_chunk_threshold,
        whisperseg_min_frame_seconds=args.whisperseg_min_frame_seconds,
        scene_min_seconds=args.scene_min_seconds,
        scene_max_seconds=args.scene_max_seconds,
        scene_clustering_threshold=args.scene_clustering_threshold,
        batch_size=args.batch_size,
        max_new_tokens=args.max_new_tokens,
        device=args.device,
        dtype=args.dtype,
    )
    return SimpleNamespace(**asdict(cfg))


def run_probe(args: argparse.Namespace) -> dict:
    import torch
    from qwen_asr import Qwen3ASRModel

    started = time.time()
    audio, samplerate = load_full_audio(args.audio)
    duration = audio.shape[0] / float(samplerate)
    probe_args = _probe_args(args)
    jobs = build_whisperseg_jobs(audio, samplerate, duration, probe_args)
    jobs = jobs[: args.max_probe_clips]
    if not jobs:
        raise SystemExit("No WhisperSeg jobs found for probe audio.")

    model = Qwen3ASRModel.from_pretrained(
        str(args.model),
        dtype=getattr(torch, args.dtype),
        device_map=args.device,
        max_inference_batch_size=args.batch_size,
        max_new_tokens=args.max_new_tokens,
        forced_aligner=str(args.forced_aligner),
        forced_aligner_kwargs=dict(dtype=getattr(torch, args.dtype), device_map=args.device),
    )
    repetition = apply_repetition_penalty_probe(model, args.repetition_penalty)

    clip_seconds = [job.end - job.start for job in jobs]
    token_budget = decide_batch_token_budget(
        clip_seconds,
        args.max_new_tokens,
        args.max_tokens_per_second,
        args.min_tokens_floor,
    )
    original_max_tokens = getattr(model, "max_new_tokens", None)
    if args.max_tokens_per_second > 0:
        model.max_new_tokens = token_budget.batch_budget

    clips = [
        (audio[int(job.start * samplerate) : int(job.end * samplerate)], samplerate)
        for job in jobs
    ]
    t0 = time.time()
    try:
        results = model.transcribe(
            audio=clips,
            context=args.context,
            language=[args.language] * len(clips),
            return_time_stamps=True,
        )
    finally:
        if original_max_tokens is not None:
            model.max_new_tokens = original_max_tokens
    transcribe_elapsed = time.time() - t0

    result_rows = []
    for idx, (job, result) in enumerate(zip(jobs, results)):
        items = getattr(result.time_stamps, "items", None) if result.time_stamps is not None else None
        words = items_to_words(items)
        result_rows.append({
            "index": idx,
            "job": {
                "start": job.start,
                "end": job.end,
                "duration": job.end - job.start,
                "speech_regions": [[iv.start, iv.end] for iv in job.speech],
            },
            "text": str(result.text or "").strip(),
            "language": str(result.language),
            "items": item_time_range(items),
            "clip_relative": items_are_clip_relative(items, job.end - job.start),
            "sentinel": assess_alignment_quality(words, job.end - job.start),
        })

    return {
        "audio": str(args.audio),
        "duration": duration,
        "jobs_found": len(jobs),
        "model": str(args.model),
        "forced_aligner": str(args.forced_aligner),
        "device": args.device,
        "dtype": args.dtype,
        "batch_size": args.batch_size,
        "generation_config": repetition,
        "token_budget": asdict(token_budget),
        "transcribe_elapsed_seconds": round(transcribe_elapsed, 3),
        "elapsed_seconds": round(time.time() - started, 3),
        "results": result_rows,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Stage 6.0 probe for WJ-style qwen ASR assumptions.")
    parser.add_argument("audio", type=Path)
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--forced-aligner", type=Path, default=DEFAULT_ALIGNER)
    parser.add_argument("--output", type=Path, help="Write JSON report to this path.")
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--dtype", choices=("bfloat16", "float16", "float32"), default="bfloat16")
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--max-new-tokens", type=int, default=4096)
    parser.add_argument("--language", default="Japanese")
    parser.add_argument("--context", default="")
    parser.add_argument("--max-probe-clips", type=int, default=1)
    parser.add_argument("--repetition-penalty", type=float, default=1.1)
    parser.add_argument("--max-tokens-per-second", type=float, default=20.0)
    parser.add_argument("--min-tokens-floor", type=int, default=256)
    parser.add_argument("--whisperseg-model", type=Path, default=Path("models/whisperseg/model.onnx"))
    parser.add_argument("--whisperseg-threshold", type=float, default=0.35)
    parser.add_argument("--whisperseg-max-speech", type=float, default=5.0)
    parser.add_argument("--whisperseg-hard-max-speech", type=float, default=8.0)
    parser.add_argument("--whisperseg-soft-split-lookback", type=float, default=1.0)
    parser.add_argument("--whisperseg-max-group", type=float, default=6.0)
    parser.add_argument("--whisperseg-chunk-threshold", type=float, default=1.0)
    parser.add_argument("--whisperseg-min-frame-seconds", type=float, default=0.1)
    parser.add_argument("--scene-backend", choices=("none", "semantic"), default="none")
    parser.add_argument("--scene-min-seconds", type=float, default=12.0)
    parser.add_argument("--scene-max-seconds", type=float, default=48.0)
    parser.add_argument("--scene-clustering-threshold", type=float, default=18.0)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    report = run_probe(args)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
