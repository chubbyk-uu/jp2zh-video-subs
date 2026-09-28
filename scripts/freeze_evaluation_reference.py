"""Freeze context review decisions with full cue coverage and immutable provenance."""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from evaluation_core import Cue, cache_fingerprint, load_subtitles
from prepare_evaluation_samples import write_srt

STATUSES = {"text_clear", "high_confidence_change", "possible", "unresolved"}
EVIDENCE_FIELDS = {"raw", "proposal", "source_trace", "original_failure", "context", "alternatives"}


def freeze(pilot: Path, decisions_path: Path, require_clear_focus: bool = False, selected_samples: list[str] | None = None):
    decisions = json.loads(decisions_path.read_text(encoding="utf-8"))
    manifest = json.loads((pilot / "manifest.json").read_text(encoding="utf-8"))
    available = {sample["id"] for sample in manifest["samples"]}
    if selected_samples is not None:
        if not selected_samples or len(selected_samples) != len(set(selected_samples)):
            raise ValueError("selected sample IDs must be nonempty and unique")
        if set(selected_samples) - available:
            raise ValueError(f"unknown sample IDs: {sorted(set(selected_samples) - available)}")
    directory = pilot / "reference-v1"
    if directory.exists():
        raise ValueError("reference-v1 already exists; do not overwrite a frozen reference")
    records, counts, hashes = [], Counter(), {}
    for sample in manifest["samples"]:
        sample_id = sample["id"]
        if selected_samples is not None and sample_id not in selected_samples:
            continue
        source = load_subtitles(pilot / "runs" / decisions["primary_run"] / f"{sample_id}.srt")
        alternate = load_subtitles(pilot / "runs" / decisions["alternate_run"] / f"{sample_id}.srt")
        review = dict(decisions["samples"][sample_id])
        if decisions.get("unlisted_context_policy") == "unresolved_not_scored":
            for cue in source.cues:
                review.setdefault(cue.index, {"status": "unresolved", "zh": "[背景初稿，不参与标准答案评分]",
                                              "reason": "保留作前后文线索，未设为标准语句。"})
        if source.status != "valid" or alternate.status not in ("valid", "empty"):
            raise ValueError(f"{sample_id}: invalid baseline inputs")
        if set(review) != {cue.index for cue in source.cues}:
            raise ValueError(f"{sample_id}: review must account for every primary cue exactly once")
        entries = []
        for cue in source.cues:
            decision = review[cue.index]
            status = decision["status"]
            if status not in STATUSES or not isinstance(decision.get("zh"), str) or not decision["zh"].strip():
                raise ValueError(f"{sample_id}/{cue.index}: status and translation required")
            if status == "high_confidence_change":
                evidence = decision.get("evidence", {})
                if (not isinstance(evidence, dict) or not EVIDENCE_FIELDS <= set(evidence)
                        or any(not isinstance(evidence[key], str) or not evidence[key].strip() for key in EVIDENCE_FIELDS)):
                    raise ValueError(f"{sample_id}/{cue.index}: full correction evidence required")
                if evidence["raw"] != cue.text or evidence["proposal"] != decision.get("ja"):
                    raise ValueError(f"{sample_id}/{cue.index}: correction evidence does not match raw/proposed text")
            if "ja" in decision and status != "high_confidence_change":
                raise ValueError("only evidence-backed confirmed text revisions may alter the reference")
            focus_start = sample["start_s"] - sample["context_start_s"]
            focus_end = sample["end_s"] - sample["context_start_s"]
            entries.append({"id": cue.index, "start_s": cue.start, "end_s": cue.end,
                            "raw_ja": cue.text, "ja": decision.get("ja", cue.text), **decision,
                            "in_focus": cue.end > focus_start and cue.start < focus_end,
                            "translation_eligible": status in ("text_clear", "high_confidence_change")})
            counts[status] += 1
        focus = [entry for entry in entries if entry["in_focus"]]
        accepted = bool(focus) and all(entry["translation_eligible"] for entry in focus)
        if require_clear_focus and not accepted:
            raise ValueError(f"{sample_id}: uncertain/empty focus; discard and select a replacement before freezing")
        records.append({"id": sample_id, "reference_kind": "context_reviewed", "audio_verified": False,
                        "standard_sample_accepted": accepted, "focus_cue_ids": [e["id"] for e in focus],
                        "boundaries_verified": False, "primary_sha256": source.sha256,
                        "alternate_sha256": alternate.sha256, "entries": entries,
                        "alternate_only_items": [g for g in json.loads((pilot / "review" / f"{sample_id}.json").read_text(encoding="utf-8"))["groups"]
                                                 if g["status"] == "extra_candidate_text"]})
        hashes[sample_id] = {"primary": source.sha256, "alternate": alternate.sha256}
    if not records:
        raise ValueError("no reference samples selected")
    fingerprint = cache_fingerprint({"decisions_sha256": hashlib.sha256(decisions_path.read_bytes()).hexdigest(),
                                     "input_hashes": hashes, "manifest_fingerprint": manifest["fingerprint"]})
    directory.mkdir(parents=True)
    reference = {"schema_version": 1, "version": "reference-v1", "fingerprint": fingerprint,
                 "reference_kind": "context_reviewed", "audio_verified": False,
                 "review_scope": decisions["review_scope"], "counts": dict(counts),
                 "limitations": ["text_clear is linguistic clarity, not acoustic correctness",
                                  "baseline-derived reference may favor its source",
                                  "possible/unresolved text excluded from translation semantic judgments",
                                  "alternate-only output is preserved for review; not established missing dialogue"],
                 "samples": records}
    report = [f"# {len(records)} 段试样参考稿 v1", "", "证据：文本上下文校对；未听音确认；时间边界未验证。", "",
              f"共 {sum(counts.values())} 条主稿事件；分类：{dict(counts)}。", ""]
    for sample in records:
        cues = [Cue(e["id"], e["start_s"], e["end_s"], e["ja"]) for e in sample["entries"]]
        write_srt(directory / f"{sample['id']}.ja.srt", cues)
        report.extend([f"## {sample['id']}", ""])
        for entry in sample["entries"]:
            report.append(f"- {entry['id']} [{entry['start_s']:.2f}–{entry['end_s']:.2f}] {entry['status']} / 日文：{entry['ja']} / 中文：{entry['zh']}")
            if entry.get("reason"):
                report.append(f"  依据或限制：{entry['reason']}")
            if entry.get("evidence"):
                report.append(f"  修订证据：{json.dumps(entry['evidence'], ensure_ascii=False)}")
        report.append("")
    (directory / "reference.json").write_text(json.dumps(reference, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (directory / "review-report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    print(f"Frozen {len(records)} samples, {sum(counts.values())} events: {dict(counts)}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pilot", type=Path, required=True)
    parser.add_argument("--decisions", type=Path, required=True)
    parser.add_argument("--require-clear-focus", action="store_true", help="Reject any unresolved/possible or empty focus")
    parser.add_argument("--samples", nargs="+", help="Explicit selected sample IDs; others remain development records")
    args = parser.parse_args()
    freeze(args.pilot, args.decisions, args.require_clear_focus, args.samples)


if __name__ == "__main__":
    main()
