"""Plan private expansion candidates with locked temporal groups, before model runs."""
from __future__ import annotations

import argparse
import json
import math
import random
import re
from collections import Counter
from pathlib import Path

from evaluation_core import cache_fingerprint, normalize_text
from prepare_evaluation_samples import file_digest, read_ass


def overlaps(start: float, end: float, intervals: list[tuple[float, float]]) -> bool:
    return any(end > lo and start < hi for lo, hi in intervals)


DIFFICULTY_HINTS = {
    "negation_condition_hint": r"ない|なきゃ|なく|なけれ|ちゃだめ|ちゃダメ|たら|なら|ても|まで",
    "role_reference_hint": r"私|僕|俺|あなた|君|お前|先生|先輩|お客|彼女|一人|どっち|誰",
    "agency_request_hint": r"させ|してくれ|してほし|して欲し|してあげ|してもら|しよう|してみ|してください",
    "ellipsis_register_hint": r"って|じゃん|やん|やろ|だけ|ほう|方が|こっち|それ|そういう",
}


def locked_assignments(lock: dict) -> dict[str, dict[int, str]]:
    """Reuse only groups already assigned; never manufacture fresh held-out groups."""
    result = {}
    for sample in lock["samples"]:
        groups = result.setdefault(sample["video_id"], {})
        block, split = sample["temporal_group"], sample["split"]
        if split not in {"development", "heldout"} or groups.setdefault(block, split) != split:
            raise ValueError("parent lock contains conflicting or invalid group splits")
    return result


def verify_prior_chain(parent: dict, supplied: dict[str, str]):
    for path, digest in parent["previous_manifests"].items():
        if supplied.get(path) != digest:
            raise ValueError("all previously viewed ancestor manifests must be supplied unchanged")


def merge_source_metadata(manifests: list[dict]) -> dict:
    result = {}
    for manifest in manifests:
        for source in manifest["sources"]:
            if source["id"] in result:
                prior = result[source["id"]]
                identities = [(s["sha256"], s.get("duration_s"),
                               {name: item["sha256"] for name, item in s["subtitles"].items()})
                              for s in (source, prior)]
                if identities[0] != identities[1]:
                    raise ValueError("previous manifests disagree about source or subtitle identity")
            result[source["id"]] = source
    return result


def plan_long_windows(cues, duration: float, previous: list[tuple[float, float]],
                      assignments: dict[int, str], rng: random.Random, candidates: int = 8,
                      context: float = 35, group_seconds: float = 1200) -> tuple[list[dict], dict]:
    """Target longer difficult dialogue hints, independently of candidate predictions."""
    guard, focus_seconds, prior_guard = 120.0, 40.0, 120.0
    protected = [(max(0, lo - prior_guard), min(duration, hi + prior_guard)) for lo, hi in previous]
    pools = {"development": [], "heldout": []}
    for cue in cues:
        start = cue.start - 0.5
        end = start + focus_seconds
        block = int(start // group_seconds)
        if block not in assignments:
            continue
        lo, hi = block * group_seconds + guard, min(duration, (block + 1) * group_seconds) - guard
        if start - context < lo or end + context > hi or overlaps(start - context, end + context, protected):
            continue
        active = [item for item in cues if item.end > start - context and item.start < end + context]
        focal = [item for item in active if item.end > start and item.start < end]
        if sum(len(normalize_text(item.text)) >= 5 for item in active) < 8:
            continue
        if sum(len(normalize_text(item.text)) >= 5 for item in focal) < 3:
            continue
        text = " ".join(item.text for item in focal)
        hints = [label for label, pattern in DIFFICULTY_HINTS.items() if re.search(pattern, text)]
        if len(hints) < 2:
            continue
        pools[assignments[block]].append({
            "start_s": start, "end_s": end, "split": assignments[block], "temporal_group": block,
            "hint_score": len(hints), "hint_context_cues": len(active),
            "reason": "沿用既有分组；按旧字幕定位较长连续问答及易错语义线索，不把旧字幕或声学标签当真值。",
            "labels": ["long_dialogue_hint", "acoustic_difficulty_unverified", *hints],
        })
    selected, available = [], {split: len(pool) for split, pool in pools.items()}
    for split, count in (("heldout", candidates // 2), ("development", candidates - candidates // 2)):
        pool = pools[split]
        rng.shuffle(pool)  # Deterministic tie-breaking, without inspecting new model results.
        pool.sort(key=lambda row: row["hint_score"], reverse=True)
        group_ids = sorted({row["temporal_group"] for row in pool})
        rng.shuffle(group_ids)
        for index in range(count):
            remaining = [row for row in pool if not overlaps(
                row["start_s"] - context - 60, row["end_s"] + context + 60,
                [(s["start_s"] - context, s["end_s"] + context) for s in selected])]
            if not remaining:
                break  # Report the deficit; do not relax criteria or change splits.
            preferred = group_ids[index % len(group_ids)]
            selected.append(next((row for row in remaining if row["temporal_group"] == preferred), remaining[0]))
    audit = {"eligible_anchors": available, "requested_per_split": {
        "heldout": candidates // 2, "development": candidates - candidates // 2},
        "selected_per_split": dict(Counter(row["split"] for row in selected))}
    return sorted(selected, key=lambda row: row["start_s"]), audit


def plan_windows(cues, duration: float, previous: list[tuple[float, float]], rng: random.Random,
                 group_seconds: float = 1200, candidates: int = 15) -> list[dict]:
    """Temporal proxy groups require later context review; never assert acoustic labels."""
    guard, context, prior_guard = 120.0, 15.0, 120.0
    protected = [(max(0, lo - prior_guard), min(duration, hi + prior_guard)) for lo, hi in previous]
    blocks = {}
    for block in range(math.ceil(duration / group_seconds)):
        lo, hi = block * group_seconds, min(duration, (block + 1) * group_seconds)
        windows = []
        for cue in cues:
            start = cue.start - 0.5
            if not lo + guard <= start < hi - guard - 20:
                continue
            active = [item for item in cues if item.end > start and item.start < start + 20]
            if sum(len(normalize_text(item.text)) >= 5 for item in active) < 2:
                continue
            end = max(start + 15, *(item.end + 0.5 for item in active))
            if end - start > 35 or end + context > hi - guard:
                continue
            if overlaps(start - context, end + context, protected):
                continue
            windows.append((start, end))
        if windows:
            blocks[block] = windows
    unseen = [block for block in blocks
              if not overlaps(block * group_seconds, min(duration, (block + 1) * group_seconds), protected)]
    if len(unseen) < 2:
        raise ValueError("insufficient unseen groups for held-out samples")
    # Split is frozen before reading new model outputs. Entire groups share a split.
    heldout = set(rng.sample(unseen, 2))
    assignments = {block: "heldout" if block in heldout else "development" for block in blocks}
    selected = []
    for split, count in (("heldout", 6), ("development", candidates - 6)):
        group_ids = [block for block in blocks if assignments[block] == split]
        rng.shuffle(group_ids)
        for index in range(count):
            candidates_left = []
            for block in group_ids:
                candidates_left.extend((block, lo, hi) for lo, hi in blocks[block]
                                       if not overlaps(lo - context - 90, hi + context + 90,
                                                       [(s["start_s"], s["end_s"]) for s in selected]))
            if not candidates_left:
                raise ValueError(f"insufficient separated dialogue windows for {split}")
            preferred = group_ids[index % len(group_ids)]
            pool = [row for row in candidates_left if row[0] == preferred] or candidates_left
            block = pool[0][0]
            anchor = rng.uniform(block * group_seconds + guard, min(duration, (block + 1) * group_seconds) - guard - 35)
            block, start, end = min(pool, key=lambda row: abs(row[1] - anchor))
            selected.append({"start_s": start, "end_s": end, "split": split,
                             "temporal_group": block, "random_anchor_s": anchor,
                             "anchor_snap_s": start - anchor,
                             "reason": "预先锁定时段分组；在时间锚点附近寻找完整对白线索，旧字幕仅供定位。",
                             "labels": ["dialogue_density_hint", "acoustic_difficulty_unverified"]})
    return sorted(selected, key=lambda row: row["start_s"])


def verify_corpus(lock: dict, manifest: dict, prior: dict) -> int:
    """Compare prepared metadata to the immutable lock and prior source digests."""
    expected = {sample["id"]: sample for sample in lock["samples"]}
    actual = {sample["id"]: sample for sample in manifest["samples"]}
    if (len(expected) != len(lock["samples"]) or len(actual) != len(manifest["samples"])
            or set(expected) != set(actual)):
        raise ValueError("corpus sample IDs differ from split lock or contain duplicates")
    for sample_id, sample in actual.items():
        if any(sample.get(key) != expected[sample_id][key]
               for key in ("video_id", "split", "scene_group", "scene_grouping_evidence", "start_s", "end_s")):
            raise ValueError(f"{sample_id}: corpus differs from split lock")
        if "context_seconds" in lock:
            context = lock["context_seconds"]
            duration = next(s["duration_s"] for s in manifest["sources"] if s["id"] == sample["video_id"])
            if (sample["context_start_s"] != max(0, sample["start_s"] - context)
                    or sample["context_end_s"] != min(duration, sample["end_s"] + context)):
                raise ValueError(f"{sample_id}: context window differs from split lock")
    sources = {source["id"]: source for source in manifest["sources"]}
    if len(sources) != len(manifest["sources"]) or set(sources) != set(prior):
        raise ValueError("corpus source IDs differ from pilot")
    for source_id, source in sources.items():
        if source["sha256"] != prior[source_id]["sha256"]:
            raise ValueError(f"{source_id}: source video differs from pilot")
        if set(source["subtitles"]) != set(prior[source_id]["subtitles"]):
            raise ValueError(f"{source_id}: subtitle sources differ from pilot")
        for name, subtitle in source["subtitles"].items():
            if subtitle["sha256"] != prior[source_id]["subtitles"][name]["sha256"]:
                raise ValueError(f"{source_id}/{name}: subtitle hints changed")
    return len(expected)


def plan(args):
    parent, assignments = None, None
    if args.reuse_split_lock:
        parent = json.loads(args.reuse_split_lock.read_text(encoding="utf-8"))
        if parent["fingerprint"] != cache_fingerprint({k: v for k, v in parent.items() if k != "fingerprint"}):
            raise ValueError("parent split lock fingerprint changed")
        if file_digest(args.source_config) != parent["source_config_sha256"]:
            raise ValueError("source config differs from parent split lock")
        assignments = locked_assignments(parent)
        verify_prior_chain(parent, {str(path): file_digest(path) for path in args.previous_manifest})
    if args.verify_corpus:
        lock = json.loads((args.output / "split-lock.json").read_text(encoding="utf-8"))
        if lock["fingerprint"] != cache_fingerprint({k: v for k, v in lock.items() if k != "fingerprint"}):
            raise ValueError("split lock fingerprint changed")
        if file_digest(args.source_config) != lock["source_config_sha256"]:
            raise ValueError("original source config changed")
        if "parent_split_lock_sha256" in lock and parent is None:
            raise ValueError("long-window verification requires --reuse-split-lock")
        for path in args.previous_manifest:
            if lock["previous_manifests"].get(str(path)) != file_digest(path):
                raise ValueError("previous manifest changed or was not part of split lock")
        if parent and lock.get("parent_split_lock_sha256") != file_digest(args.reuse_split_lock):
            raise ValueError("parent split lock differs from long-window lock")
        manifest = json.loads((args.verify_corpus / "manifest.json").read_text(encoding="utf-8"))
        prior = merge_source_metadata([json.loads(path.read_text(encoding="utf-8")) for path in args.previous_manifest])
        count = verify_corpus(lock, manifest, prior)
        print(f"Verified locked splits and unchanged sources for {count} candidates")
        return
    if args.output.exists():
        raise ValueError("output exists; choose a new expansion directory")
    original = json.loads(args.source_config.read_text(encoding="utf-8"))
    manifests = [json.loads(path.read_text(encoding="utf-8")) for path in args.previous_manifest]
    metadata = merge_source_metadata(manifests)
    if parent:
        # A caller must supply the entire viewed parent corpus, not just its accepted clips.
        parent_corpora = [m for m in manifests if {s["id"] for s in m["samples"]} == {s["id"] for s in parent["samples"]}]
        if len(parent_corpora) != 1:
            raise ValueError("exactly one complete parent corpus manifest required")
        verify_corpus(parent, parent_corpora[0], metadata)
        if args.context_seconds < 25:
            raise ValueError("long-window sampling requires at least 25 seconds of context on each side")
    rng, sources, scenes, selection_audits = random.Random(args.seed), [], [], {}
    for source in original["sources"]:
        video_id = source["id"]
        previous = [(s["context_start_s"], s["context_end_s"]) for manifest in manifests
                    for s in manifest["samples"] if s["video_id"] == video_id]
        cues, _ = read_ass(Path(next(iter(source["subtitles"].values()))))
        if parent:
            selections, audit = plan_long_windows(cues, metadata[video_id]["duration_s"], previous,
                                                  assignments.get(video_id, {}), rng,
                                                  candidates=args.candidates_per_video,
                                                  context=args.context_seconds,
                                                  group_seconds=parent["temporal_group_seconds"])
            selection_audits[video_id] = audit
        else:
            selections = plan_windows(cues, metadata[video_id]["duration_s"], previous, rng,
                                      candidates=args.candidates_per_video)
        for number, sample in enumerate(selections, 1):
            sample["id"] = f"{video_id}-{'L' if parent else 'E'}{number:02d}"
            sample["scene_group"] = f"{video_id}-T{sample['temporal_group']:02d}"
            sample["scene_grouping_evidence"] = "temporal_proxy_pending_context_review"
        sources.append({**source, "selections": selections})
        scenes.extend({"video_id": video_id, **sample} for sample in selections)
    record = {"schema_version": 1, "status": "locked_split_before_baseline",
              "seed": args.seed, "source_config_sha256": file_digest(args.source_config),
              "previous_manifests": {str(path): file_digest(path) for path in args.previous_manifest},
              "temporal_group_seconds": 1200, "group_boundary_guard_seconds": 120,
              "prior_context_guard_seconds": 120, "samples": scenes,
              "counts": dict(Counter(s["split"] for s in scenes)),
              "limitations": ["temporal groups are proxies; context must check scene continuity",
                              "dialogue-density selection depends on old subtitles, not population random sampling",
                              "no candidate-model output used for selection; no verified acoustic truth",
                              "uncertain or empty focal dialogue must be discarded and recorded"]}
    if parent:
        record.update({"parent_split_lock_sha256": file_digest(args.reuse_split_lock),
                       "parent_split_lock": str(args.reuse_split_lock),
                       "context_seconds": args.context_seconds, "focus_seconds": 40,
                       "minimum_substantive_context_cues": 8, "minimum_substantive_focus_cues": 3,
                       "minimum_difficulty_hint_categories": 2, "new_context_separation_seconds": 60,
                       "selection_audits": selection_audits,
                       "group_assignments": assignments})
        record["limitations"].append("existing held-out groups reused; deficits not filled from development groups")
    if not scenes:
        raise ValueError("no eligible dialogue windows; no corpus was created")
    record["fingerprint"] = cache_fingerprint(record)
    args.output.mkdir(parents=True)
    (args.output / "source-config.json").write_text(json.dumps({"sources": sources}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (args.output / "split-lock.json").write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Locked {len(scenes)} candidates: {record['counts']}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-config", type=Path, required=True)
    parser.add_argument("--previous-manifest", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=20260929)
    parser.add_argument("--candidates-per-video", type=int, default=15)
    parser.add_argument("--verify-corpus", type=Path, help="Verify prepared manifest against existing split lock and pilot hashes")
    parser.add_argument("--reuse-split-lock", type=Path, help="Reuse assigned groups for longer, disjoint replacement windows")
    parser.add_argument("--context-seconds", type=float, default=35, help="Long-window context on each side, also pass to preparation")
    args = parser.parse_args()
    if args.candidates_per_video < 8:
        parser.error("at least 8 candidates per video required")
    plan(args)


if __name__ == "__main__":
    main()
