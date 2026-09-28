"""Apply the existing Qwen aligner and cue shaping to HF pilot outputs."""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path

from asr_common import write_entries
from evaluation_core import Cue, load_subtitles
from prepare_evaluation_samples import excerpt, write_srt
from srt_utils import Interval
from transcribe_ja_srt_qwen import (
    ChunkJob, _serialize_items, _time_aligned_job, build_parser as asr_parser,
    entries_from_raw, normalize_runtime_args,
)


def run(args):
    import soundfile as sf
    import torch
    from qwen_asr.inference.qwen3_forced_aligner import Qwen3ForcedAligner

    source = json.loads(args.frames.read_text(encoding="utf-8"))
    generated = json.loads(args.transcriptions.read_text(encoding="utf-8"))
    manifest = json.loads((args.pilot / "manifest.json").read_text(encoding="utf-8"))
    if generated.get("status") != "complete":
        raise ValueError("incomplete HF transcription")
    audio, rate = sf.read(str(args.pilot / "pilot.wav"), dtype="float32")
    config = asr_parser().parse_args(["unused.wav", "unused.srt"])
    normalize_runtime_args(config)
    config.min_cue_seconds = 0.3
    aligner = Qwen3ForcedAligner.from_pretrained(str(args.aligner), dtype=torch.bfloat16, device_map="cuda:0")
    raw = copy.deepcopy(source)
    raw["chunks"] = []
    raw["generation"] = generated["provenance"]["generation_config"]
    for frame in generated["chunks"]:
        chunk = source["chunks"][frame["frame_index"]]
        text = frame["text"]
        items = []
        if text:
            waveform = audio[int(frame["start"] * rate):int(frame["end"] * rate)]
            items = aligner.align(audio=(waveform, rate), text=text, language="Japanese")[0].items
        job = ChunkJob(start=chunk["start"], end=chunk["end"], keep_lo=chunk["keep_lo"], keep_hi=chunk["keep_hi"],
                       speech=[Interval(*region) for region in chunk.get("speech_regions", [])])
        sentinel, recovery, recovered = _time_aligned_job(job, items, config)
        output = {key: chunk[key] for key in ("start", "end", "keep_lo", "keep_hi", "speech_regions", "regroup_regions",
                                             "left_boundary_reason", "right_boundary_reason") if key in chunk}
        output.update(text=text, language="Japanese", raw_items=_serialize_items(items), items=_serialize_items(recovered),
                      sentinel=sentinel, recovery=recovery, **{"pass": "main"})
        raw["chunks"].append(output)
    directory = args.transcriptions.parent
    (directory / "aligned-raw.json").write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    entries = entries_from_raw(raw, config)
    output = directory / "combined.srt"
    write_entries(entries, output)
    parsed = load_subtitles(output)
    for sample in manifest["samples"]:
        cues = excerpt(parsed.cues, sample["combined_start_s"], sample["combined_end_s"])
        write_srt(directory / f"{sample['id']}.srt", [Cue(str(i), c.start, c.end, c.text) for i, c in enumerate(cues, 1)])
    print(f"Aligned {len(generated['chunks'])} frames into {len(entries)} cues")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pilot", type=Path, required=True)
    parser.add_argument("--frames", type=Path, required=True)
    parser.add_argument("--transcriptions", type=Path, required=True)
    parser.add_argument("--aligner", type=Path, required=True)
    run(parser.parse_args())


if __name__ == "__main__":
    main()
