"""HF base/LoRA comparison on identical preserved VAD frames and decode settings."""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.metadata
import json
import time
from pathlib import Path

from evaluation_core import cache_fingerprint


def run(args):
    import soundfile as sf
    import torch
    from transformers import AutoModelForMultimodalLM, AutoProcessor

    source = json.loads(args.frames.read_text(encoding="utf-8"))
    audio, rate = sf.read(str(args.audio), dtype="float32")
    if rate != 16000 or audio.ndim != 1:
        raise ValueError("expected mono 16 kHz audio")
    if args.output.exists():
        raise ValueError("output exists; choose a new output path")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    frame_directory = args.output.parent / "frames"
    frame_directory.mkdir(parents=True, exist_ok=True)
    # Keep tokenization and prompt formatting identical in the base and LoRA arms.
    processor = AutoProcessor.from_pretrained(str(args.base), local_files_only=True)
    started = time.monotonic()
    model = AutoModelForMultimodalLM.from_pretrained(str(args.base), dtype=torch.bfloat16,
                                                    device_map={"": 0}, local_files_only=True)
    if args.adapter:
        from peft import PeftModel

        model = PeftModel.from_pretrained(model, str(args.adapter), local_files_only=True)
    model.eval()
    config = copy.deepcopy(model.generation_config)
    config.do_sample = False
    config.num_beams = args.beams
    config.early_stopping = False
    config.repetition_penalty = 1.0
    config.no_repeat_ngram_size = 0
    config.max_new_tokens = 256
    torch.manual_seed(0)
    torch.cuda.reset_peak_memory_stats()
    provenance = {"audio_sha256": hashlib.sha256(args.audio.read_bytes()).hexdigest(),
                  "frames_sha256": hashlib.sha256(args.frames.read_bytes()).hexdigest(),
                  "base": json.loads((args.base / "evaluation-download.json").read_text(encoding="utf-8")),
                  "adapter": json.loads((args.adapter / "evaluation-download.json").read_text(encoding="utf-8")) if args.adapter else None,
                  "generation_config": config.to_dict(),
                  "runtime": {name: importlib.metadata.version(name) for name in ("torch", "transformers", "peft")},
                  "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    result = {"schema_version": 1, "status": "running", "provenance": provenance,
              "fingerprint": cache_fingerprint(provenance), "chunks": []}
    for number, chunk in enumerate(source["chunks"]):
        if chunk.get("superseded_by_stepdown"):
            continue
        waveform = audio[int(chunk["start"] * rate):int(chunk["end"] * rate)]
        path = frame_directory / f"{number:04d}.wav"
        # FLOAT avoids introducing an extra int16 quantization in only the HF arm.
        sf.write(str(path), waveform, rate, subtype="FLOAT")
        inputs = processor.apply_transcription_request(audio=str(path), language="Japanese")
        inputs = {key: value.to(model.device) for key, value in inputs.items()}
        prompt_len = inputs["input_ids"].shape[1]
        prompt_hash = hashlib.sha256(inputs["input_ids"].cpu().numpy().tobytes()).hexdigest()
        t0 = time.monotonic()
        with torch.inference_mode(), torch.autocast(device_type="cuda", dtype=torch.bfloat16):
            generated = model.generate(**inputs, generation_config=config)
        ids = generated[0, prompt_len:]
        decoded = processor.tokenizer.decode(ids, skip_special_tokens=True)
        text = decoded.split("<asr_text>", 1)[-1].strip()
        result["chunks"].append({"frame_index": number, "start": chunk["start"], "end": chunk["end"],
                                 "text": text, "raw_decoded": decoded, "prompt_sha256": prompt_hash,
                                 "generated_tokens": len(ids), "hit_token_limit": len(ids) >= config.max_new_tokens,
                                 "elapsed_s": time.monotonic() - t0})
        print(f"{number + 1}/{len(source['chunks'])}: {text[:100]}", flush=True)
        args.output.with_suffix(".partial.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    result.update(status="complete", elapsed_s=time.monotonic() - started,
                  peak_allocated_mib=torch.cuda.max_memory_allocated() / 1024 ** 2,
                  peak_reserved_mib=torch.cuda.max_memory_reserved() / 1024 ** 2)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--frames", type=Path, required=True, help="Qwen baseline raw.json supplies fixed VAD frames")
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--adapter", type=Path)
    parser.add_argument("--beams", type=int, choices=(1, 4), default=4)
    parser.add_argument("--output", type=Path, required=True)
    run(parser.parse_args())


if __name__ == "__main__":
    main()
