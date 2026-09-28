"""Prepare private, reproducible video samples; existing subtitles are hints only."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import random
import re
import subprocess
import sys
import wave
from pathlib import Path

from evaluation_core import Cue, cache_fingerprint, cues_as_dicts
from srt_utils import srt_time

ROOT = Path(__file__).resolve().parents[1]


def ass_helper():
    path = ROOT / ".agents/skills/review-bilingual-ass/scripts/ass_review.py"
    spec = importlib.util.spec_from_file_location("evaluation_ass_review", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def ass_seconds(value: str) -> float:
    hours, minutes, seconds = value.split(":")
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def read_ass(path: Path) -> tuple[list[Cue], dict]:
    helper = ass_helper()
    ass = helper.load_ass(path)
    info = helper.inspect_payload(ass)
    if ass.parse_errors:
        raise ValueError(f"invalid ASS: {path}")
    cues = []
    for event in ass.dialogues:
        _, ja = helper.bilingual_parts(event)
        if not ja:
            continue
        ja = re.sub(r"\{[^}]*\}", "", ja).replace(r"\N", " ").replace(r"\n", " ")
        cues.append(Cue(str(event.event_index), ass_seconds(event.start), ass_seconds(event.end), ja))
    return cues, info


def write_srt(path: Path, cues: list[Cue]):
    path.write_text("\n\n".join(f"{c.index}\n{srt_time(c.start)} --> {srt_time(c.end)}\n{c.text}"
                                 for c in cues) + ("\n" if cues else ""), encoding="utf-8")


def excerpt(cues: list[Cue], start: float, end: float) -> list[Cue]:
    return [Cue(c.index, max(start, c.start) - start, min(end, c.end) - start, c.text)
            for c in cues if c.end > start and c.start < end]


def probe(path: Path) -> dict:
    result = subprocess.run(["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)],
                            check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


def file_digest(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def prepare(config_path: Path, output: Path, seed: int, clip_seconds: float, context_seconds: float):
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if (output / "manifest.json").exists():
        raise ValueError("manifest already exists; use a new run directory")
    output.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    manifest = {"schema_version": 1, "status": "pilot_development", "seed": seed,
                "reference_kind": "model_output", "clip_seconds": clip_seconds,
                "context_seconds": context_seconds, "sources": [], "samples": [],
                "sampling_limitations": ["three stratified time anchors per video; subtitle hints may snap an anchor",
                                         "pilot only; no full-video accuracy inference; no verified acoustic labels"]}
    for source in config["sources"]:
        video_id, video = source["id"], Path(source["video"])
        media = probe(video)
        duration = float(media["format"]["duration"])
        print(f"{video_id}: duration={duration:.1f}s; hashing source", flush=True)
        subtitles = {}
        for name, path in source.get("subtitles", {}).items():
            cues, info = read_ass(Path(path))
            subtitles[name] = (cues, info)
        entry = {"id": video_id, "path": str(video), "sha256": file_digest(video),
                 "bytes": video.stat().st_size, "duration_s": duration,
                 "audio_streams": [stream for stream in media["streams"] if stream["codec_type"] == "audio"],
                 "subtitles": {name: info for name, (_, info) in subtitles.items()}}
        manifest["sources"].append(entry)
        primary = next(iter(subtitles.values()))[0] if subtitles else []
        explicit = source.get("selections")
        fractions = (0.06, 0.38, 0.72) if explicit is None else range(len(explicit))
        for number, fraction in enumerate(fractions, 1):
            anchor = max(0.0, min(duration - clip_seconds, duration * (fraction + rng.uniform(-0.015, 0.015))))
            nearby = [cue for cue in primary if abs(cue.start - anchor) <= 90 and len(cue.text) >= 4]
            selected = min(nearby, key=lambda cue: abs(cue.start - anchor)) if nearby else None
            start = max(0.0, min(duration - clip_seconds, selected.start - 2 if selected else anchor))
            end = min(duration, start + clip_seconds)
            if explicit is not None:
                selection = explicit[number - 1]
                start, end = float(selection["start_s"]), float(selection["end_s"])
                if not 0 <= start < end <= duration:
                    raise ValueError(f"{video_id}: explicit selection outside video")
                anchor, selected = start, None
            sample_id = selection.get("id", f"{video_id}-P{number:02d}") if explicit is not None else f"{video_id}-P{number:02d}"
            if not sample_id or any(not char.isascii() or not (char.isalnum() or char in "-_") for char in sample_id):
                raise ValueError("sample ID must be a safe ASCII name")
            directory = output / "samples" / sample_id
            directory.mkdir(parents=True, exist_ok=True)
            context_start, context_end = max(0, start - context_seconds), min(duration, end + context_seconds)
            audio = directory / "context.wav"
            subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-n", "-ss", str(context_start),
                            "-i", str(video), "-t", str(context_end - context_start), "-map", "0:a:0",
                            "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(audio)], check=True)
            sample = {"id": sample_id, "video_id": video_id, "split": selection.get("split", "development") if explicit is not None else "development",
                      "random_anchor_s": anchor, "subtitle_snap_s": start + 2 - anchor if selected else None,
                      "start_s": start, "end_s": end, "context_start_s": context_start, "context_end_s": context_end,
                      "audio": str(audio.relative_to(output)), "audio_sha256": file_digest(audio),
                      "labels": ["time_stratified", "acoustic_difficulty_unverified"], "existing_outputs": {}}
            if explicit is not None:
                sample["labels"] = selection.get("labels", ["curated_replacement", "acoustic_difficulty_unverified"])
                sample["selection_reason"] = selection["reason"]
                for key in ("scene_group", "scene_grouping_evidence", "temporal_group", "random_anchor_s", "anchor_snap_s"):
                    if key in selection:
                        sample[key] = selection[key]
            for name, (cues, _) in subtitles.items():
                context = excerpt(cues, context_start, context_end)
                path = directory / f"existing-{name}.srt"
                write_srt(path, context)
                sample["existing_outputs"][name] = {"path": str(path.relative_to(output)),
                                                    "cues": cues_as_dicts(context), "evidence": "model_output"}
            manifest["samples"].append(sample)
            print(f"{sample_id}: {start:.2f}–{end:.2f}s; context WAV ready", flush=True)
    if all(source.get("selections") is not None for source in config["sources"]):
        manifest["status"] = "explicit_selection_candidates"
        manifest["sampling_limitations"][0] = "explicit windows from supplied config; inspect selection reasons and split evidence"
        manifest["sampling_limitations"].append("dialogue selection may favor interpretable text; no population accuracy inference")
    manifest["fingerprint"] = cache_fingerprint({"sources": manifest["sources"], "seed": seed,
                                                  "sample_windows": [(s["id"], s["start_s"], s["end_s"]) for s in manifest["samples"]],
                                                  "sample_splits": [(s["id"], s["split"], s.get("scene_group")) for s in manifest["samples"]],
                                                  "source_config_sha256": file_digest(config_path),
                                                  "clip_seconds": clip_seconds, "context_seconds": context_seconds})
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with wave.open(str(output / "pilot.wav"), "wb") as combined:
        combined.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        offset = 0.0
        for sample in manifest["samples"]:
            with wave.open(str(output / sample["audio"]), "rb") as audio:
                assert audio.getparams()[:3] == (1, 2, 16000)
                combined.writeframes(audio.readframes(audio.getnframes()))
                seconds = audio.getnframes() / 16000
            sample["combined_start_s"], sample["combined_end_s"] = offset, offset + seconds
            combined.writeframes(b"\0" * (16000 * 2 * 4))
            offset += seconds + 4
    manifest["combined_audio_sha256"] = file_digest(output / "pilot.wav")
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Prepared {len(manifest['samples'])} pilot samples; combined audio {offset:.1f}s", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True, help="Private JSON listing video IDs, paths and ASS sources")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=20260928)
    parser.add_argument("--clip-seconds", type=float, default=30.0)
    parser.add_argument("--context-seconds", type=float, default=20.0)
    args = parser.parse_args()
    if args.clip_seconds <= 0 or args.context_seconds < 0:
        parser.error("clip-seconds must be positive; context-seconds must be nonnegative")
    prepare(args.config, args.output, args.seed, args.clip_seconds, args.context_seconds)


if __name__ == "__main__":
    main()
