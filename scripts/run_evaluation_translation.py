"""Paired GalTransl/ASMR translation pilot on fixed, eligible Japanese dialogue."""
from __future__ import annotations

import argparse
import contextlib
import copy
import hashlib
import importlib.metadata
import io
import json
import sys
import time
from pathlib import Path
from unittest.mock import patch

from evaluation_core import cache_fingerprint
from evaluation_translation import asmr_prompt, check_asmr_output, qwen_no_thinking_prompt, select_translation_input, translation_schema


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


def model_input_entries(entries: list[dict], source_mode: str) -> list[dict]:
    if source_mode == "reviewed":
        return entries
    if source_mode != "raw-asr":
        raise ValueError("unknown translation source mode")
    if any(not isinstance(e.get("raw_ja"), str) or not e["raw_ja"].strip() for e in entries):
        raise ValueError("raw-asr mode requires preserved nonempty raw Japanese for every context cue")
    return [{**entry, "ja": entry["raw_ja"], "reviewed_ja": entry["ja"],
             "reference_status": entry["status"], "status": "model_output",
             "input_evidence": "model_output", "translation_eligible": False} for entry in entries]


def production_galtransl(llm, entries: list[dict], directory: Path, model: Path, batch_size: int = 8,
                        whole_window: bool = False) -> dict:
    """Exercise the production CLI, including its batch, cache and retry paths."""
    import translate_srt_galtransl as production
    from evaluation_core import Cue, load_subtitles
    from prepare_evaluation_samples import write_srt

    directory.mkdir(parents=True, exist_ok=True)
    source, output = directory / "fixed-source.srt", directory / "output.srt"
    write_srt(source, [Cue(e["id"], e["start_s"], e["end_s"], e["ja"]) for e in entries])
    calls = []
    full_context = "\n".join(e["ja"] for e in entries)

    class Recorder:
        def create_chat_completion(self, **kwargs):
            if whole_window and full_context not in kwargs["messages"][-1]["content"]:
                # Native retries may split the target. Retain the same reviewed
                # Japanese context even for those smaller fallback requests.
                kwargs = copy.deepcopy(kwargs)
                kwargs["messages"][-1]["content"] = (
                    "完整日文上下文（仅供参考，不额外输出译文）：\n" + full_context + "\n\n"
                    + kwargs["messages"][-1]["content"])
            response = llm.create_chat_completion(**kwargs)
            calls.append({"request": kwargs, "response": response,
                          "full_window_context_supplied": full_context in kwargs["messages"][-1]["content"]})
            return response

    argv = ["translate_srt_galtransl.py", str(source), "--output", str(output),
            "--model-path", str(model), "--context-size", "6", "--batch-size", str(batch_size),
            "--lead-out-seconds", "0", "--min-display-seconds", "0"]
    log = io.StringIO()
    with patch.object(production, "Llama", return_value=Recorder()), patch.object(sys, "argv", argv), contextlib.redirect_stdout(log), \
            patch.object(production, "HISTORY_RESET_SECONDS", float("inf") if whole_window else production.HISTORY_RESET_SECONDS):
        production.main()
    (directory / "production.log").write_text(log.getvalue(), encoding="utf-8")
    parsed = load_subtitles(output)
    by_id = {cue.index: cue for cue in parsed.cues}
    valid = parsed.status == "valid" and set(by_id) == {e["id"] for e in entries}
    return {"status": "complete" if valid else "invalid_output", "calls": calls,
            "output_status": parsed.status,
            "records": [{"ids": [e["id"]], "text": by_id[e["id"]].text,
                         "start_s": e["start_s"], "end_s": e["end_s"]} for e in entries if e["id"] in by_id],
            "whole_window_context": whole_window,
            "policy": f"production CLI: context=6, batch={batch_size}; whole_window={whole_window}; native prompts/cache/retries; reviewed window prevents gap resets and retains Japanese context in retries; display padding disabled; source-owned times"}


def run(args):
    reference = load_reference(args.reference)
    source_mode = getattr(args, "source_mode", "reviewed")
    prepared = []
    for sample in reference["samples"]:
        context, focus = select_translation_input(sample, args.context_policy)
        prepared.append((sample, model_input_entries(context, source_mode), focus))
    if args.output.exists():
        raise ValueError("output exists; choose a new run output")
    if not prepared:
        raise ValueError("no translation samples")
    from llama_cpp import Llama, LlamaGrammar

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.model.open("rb") as stream:
        weights_hash = hashlib.file_digest(stream, "sha256").hexdigest()
    started = time.monotonic()
    llm = Llama(model_path=str(args.model), n_gpu_layers=args.gpu_layers, n_ctx=8192 if args.backend == "asmr" else 4096,
                seed=0, verbose=False)
    load_seconds = time.monotonic() - started
    provenance = {"reference_sha256": hashlib.sha256(args.reference.read_bytes()).hexdigest(),
                  "reference_parts": reference.get("reference_hashes", {}),
                  "model_sha256": weights_hash, "backend": args.backend, "seed": 0,
                  "gpu_layers_requested": args.gpu_layers,
                  "context_policy": args.context_policy,
                  "source_mode": source_mode,
                  "input_evidence": "model_output" if source_mode == "raw-asr" else reference["reference_kind"],
                  "llama_cpp_python": importlib.metadata.version("llama-cpp-python"),
                  "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  "protocol_sha256": hashlib.sha256(Path(__file__).with_name("evaluation_translation.py").read_bytes()).hexdigest(),
                  "production_dependencies": {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                                              for name in ("translate_srt_galtransl.py", "translation_common.py", "pipeline_configs.py", "target_languages.py")}}
    result = {"schema_version": 1, "reference_kind": reference["reference_kind"], "provenance": provenance,
              "fingerprint": cache_fingerprint(provenance), "load_seconds": load_seconds, "samples": [],
              "status": "running", "semantic_accuracy": None}
    for sample, entries, focus in prepared:
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
            # Whole-window batch supplies the same preceding/following Japanese
            # as the ASMR arm; native adaptive retries remain visible in calls.
            batch_size = len(entries) if args.context_policy == "reviewed-window" else 8
            record = {"id": sample["id"], **production_galtransl(llm, entries, args.output.parent / sample["id"], args.model,
                                                              batch_size=batch_size, whole_window=args.context_policy == "reviewed-window")}
        record["elapsed_s"] = time.monotonic() - t0
        record["fixed_source"] = focus
        record["translation_input"] = entries
        record["context_policy"] = args.context_policy
        record["source_mode"] = source_mode
        record["input_evidence"] = provenance["input_evidence"]
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
    parser.add_argument("--gpu-layers", type=int, default=-1, help="GPU offload layers; 0 requests CPU-only, default -1 offloads all possible layers")
    parser.add_argument("--context-policy", choices=("reviewed-window", "focus-only"), default="reviewed-window",
                        help="Default: translate reviewed continuous context, score only focus; focus-only is a local-input diagnostic")
    parser.add_argument("--source-mode", choices=("reviewed", "raw-asr"), default="reviewed",
                        help="Raw-ASR propagation probe uses preserved baseline text; frozen target and context membership stay unchanged")
    parser.add_argument("--output", type=Path, required=True)
    run(parser.parse_args())


if __name__ == "__main__":
    main()
