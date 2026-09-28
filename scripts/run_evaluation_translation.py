"""Paired GalTransl/ASMR translation pilot on fixed, eligible Japanese dialogue."""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib.metadata
import io
import json
import sys
import time
from pathlib import Path
from unittest.mock import patch

from evaluation_core import cache_fingerprint
from evaluation_translation import asmr_prompt, check_asmr_output, qwen_no_thinking_prompt, translation_schema


def load_reference(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if "parts" not in data:
        return data
    samples, hashes = [], {}
    for part in data["parts"]:
        reference_path = Path(part["reference"])
        reference = json.loads(reference_path.read_text(encoding="utf-8"))
        if reference["reference_kind"] != data["reference_kind"]:
            raise ValueError("mixed reference evidence kinds")
        selected = part["samples"]
        by_id = {sample["id"]: sample for sample in reference["samples"]}
        if len(selected) != len(set(selected)) or set(selected) - set(by_id):
            raise ValueError("invalid selected sample IDs")
        samples.extend(by_id[id_] for id_ in selected)
        hashes[str(reference_path)] = hashlib.sha256(reference_path.read_bytes()).hexdigest()
    if len(samples) != len({sample["id"] for sample in samples}):
        raise ValueError("duplicate sample IDs across references")
    return {"reference_kind": data["reference_kind"], "samples": samples, "reference_hashes": hashes}


def production_galtransl(llm, entries: list[dict], directory: Path, model: Path) -> dict:
    """Exercise the production CLI, including its batch, cache and retry paths."""
    import translate_srt_galtransl as production
    from evaluation_core import Cue, load_subtitles
    from prepare_evaluation_samples import write_srt

    directory.mkdir(parents=True, exist_ok=True)
    source, output = directory / "fixed-source.srt", directory / "output.srt"
    write_srt(source, [Cue(e["id"], e["start_s"], e["end_s"], e["ja"]) for e in entries])
    calls = []

    class Recorder:
        def create_chat_completion(self, **kwargs):
            response = llm.create_chat_completion(**kwargs)
            calls.append({"request": kwargs, "response": response})
            return response

    argv = ["translate_srt_galtransl.py", str(source), "--output", str(output),
            "--model-path", str(model), "--context-size", "6", "--batch-size", "8",
            "--lead-out-seconds", "0", "--min-display-seconds", "0"]
    log = io.StringIO()
    with patch.object(production, "Llama", return_value=Recorder()), patch.object(sys, "argv", argv), contextlib.redirect_stdout(log):
        production.main()
    (directory / "production.log").write_text(log.getvalue(), encoding="utf-8")
    parsed = load_subtitles(output)
    by_id = {cue.index: cue for cue in parsed.cues}
    valid = parsed.status == "valid" and set(by_id) == {e["id"] for e in entries}
    return {"status": "complete" if valid else "invalid_output", "calls": calls,
            "output_status": parsed.status,
            "records": [{"ids": [e["id"]], "text": by_id[e["id"]].text,
                         "start_s": e["start_s"], "end_s": e["end_s"]} for e in entries if e["id"] in by_id],
            "policy": "production CLI: context=6, batch=8, native prompts/cache/retries; display padding disabled; source-owned times"}


def run(args):
    from llama_cpp import Llama, LlamaGrammar

    reference = load_reference(args.reference)
    if args.output.exists():
        raise ValueError("output exists; choose a new run output")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.model.open("rb") as stream:
        weights_hash = hashlib.file_digest(stream, "sha256").hexdigest()
    started = time.monotonic()
    llm = Llama(model_path=str(args.model), n_gpu_layers=-1, n_ctx=8192 if args.backend == "asmr" else 4096,
                seed=0, verbose=False)
    load_seconds = time.monotonic() - started
    provenance = {"reference_sha256": hashlib.sha256(args.reference.read_bytes()).hexdigest(),
                  "reference_parts": reference.get("reference_hashes", {}),
                  "model_sha256": weights_hash, "backend": args.backend, "seed": 0,
                  "llama_cpp_python": importlib.metadata.version("llama-cpp-python"),
                  "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  "protocol_sha256": hashlib.sha256(Path(__file__).with_name("evaluation_translation.py").read_bytes()).hexdigest(),
                  "production_dependencies": {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                                              for name in ("translate_srt_galtransl.py", "translation_common.py", "pipeline_configs.py", "target_languages.py")}}
    result = {"schema_version": 1, "reference_kind": reference["reference_kind"], "provenance": provenance,
              "fingerprint": cache_fingerprint(provenance), "load_seconds": load_seconds, "samples": [],
              "status": "running", "semantic_accuracy": None}
    for sample in reference["samples"]:
        entries = [e for e in sample["entries"] if e["in_focus"] and e["translation_eligible"]]
        if not entries or not sample["standard_sample_accepted"]:
            result["samples"].append({"id": sample["id"], "status": "skipped_uncertain_focus"})
            continue
        t0 = time.monotonic()
        if args.backend == "asmr":
            prompt = qwen_no_thinking_prompt(asmr_prompt(entries, sample["id"]))
            response = llm.create_completion(prompt=prompt, grammar=LlamaGrammar.from_json_schema(json.dumps(translation_schema())),
                                             temperature=0, max_tokens=2048, stop=["<|im_end|>"], repeat_penalty=1.0)
            raw = response["choices"][0]["text"]
            parsed = check_asmr_output(raw, entries)
            record = {"id": sample["id"], "raw": raw, "checked": parsed,
                      "status": "complete" if parsed["valid"] else "invalid_output",
                      "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(), "usage": response.get("usage"),
                      "finish_reason": response["choices"][0].get("finish_reason")}
        else:
            record = {"id": sample["id"], **production_galtransl(llm, entries, args.output.parent / sample["id"], args.model)}
        record["elapsed_s"] = time.monotonic() - t0
        record["fixed_source"] = entries
        result["samples"].append(record)
        args.output.with_suffix(".partial.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"{sample['id']}: {record['status']}; {record['elapsed_s']:.1f}s", flush=True)
    result.update(status="complete" if all(row["status"] == "complete" for row in result["samples"]) else "completed_with_errors",
                  elapsed_s=time.monotonic() - started)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--backend", choices=("galtransl", "asmr"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    run(parser.parse_args())


if __name__ == "__main__":
    main()
