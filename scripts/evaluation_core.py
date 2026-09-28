"""Evidence-aware, model-independent subtitle checks. No model is a ground truth."""
from __future__ import annotations

import difflib
import hashlib
import json
import math
import re
import unicodedata
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path

from srt_utils import Interval, merge_intervals, parse_time

SCHEMA_VERSION = 1
EVALUATOR_VERSION = "1.0"
REFERENCE_KINDS = ("audio_verified", "context_reviewed", "model_output")
TIME_RE = re.compile(r"^(\d{2,}:[0-5]\d:[0-5]\d,\d{3})\s*-->\s*(\d{2,}:[0-5]\d:[0-5]\d,\d{3})(?:\s+.*)?$")


@dataclass(frozen=True)
class Cue:
    index: str
    start: float
    end: float
    text: str


@dataclass
class SubtitleInput:
    status: str
    cues: list[Cue]
    issues: list[str]
    sha256: str | None = None

    def summary(self) -> dict:
        return {"status": self.status, "entries": len(self.cues), "issues": self.issues, "sha256": self.sha256}


def load_subtitles(path: Path | None) -> SubtitleInput:
    if path is None:
        return SubtitleInput("not_provided", [], [])
    if not path.is_file():
        return SubtitleInput("missing", [], ["subtitle file missing"])
    try:
        raw = path.read_bytes()
        text = raw.decode("utf-8-sig").strip()
    except (OSError, UnicodeDecodeError) as exc:
        return SubtitleInput("invalid", [], [f"cannot read subtitle: {type(exc).__name__}"])
    digest = hashlib.sha256(raw).hexdigest()
    if not text:
        return SubtitleInput("empty", [], [], digest)
    cues, issues, seen = [], [], set()
    for number, block in enumerate(re.split(r"\r?\n\s*\r?\n", text), 1):
        lines = block.splitlines()
        match = TIME_RE.fullmatch(lines[1].strip()) if len(lines) >= 3 else None
        if match is None:
            issues.append(f"block {number}: invalid SRT block")
            continue
        index = lines[0].strip()
        start, end = (parse_time(value) for value in match.groups())
        content = "\n".join(lines[2:]).strip()
        if not index.isdecimal() or index in seen or end <= start or not content:
            issues.append(f"block {number}: invalid/duplicate ID, duration or text")
            continue
        seen.add(index)
        cues.append(Cue(index, start, end, content))
    if any(a.start > b.start for a, b in zip(cues, cues[1:])):
        issues.append("cue order is not chronological")
    status = "partial_invalid" if issues and cues else "invalid" if issues else "valid"
    return SubtitleInput(status, cues, issues, digest)


def normalize_text(text: str) -> str:
    """NFC; omit whitespace/punctuation, retaining long vowels, negation and repeats."""
    return "".join(char for char in unicodedata.normalize("NFC", text)
                   if not char.isspace() and not unicodedata.category(char).startswith("P"))


def character_errors(reference: str, candidate: str) -> dict:
    """Levenshtein S/I/D counts with deterministic substitution-first ties."""
    # Cells hold (edits, substitutions, insertions, deletions); only two rows are kept.
    previous = [(j, 0, j, 0) for j in range(len(candidate) + 1)]
    for i, ref in enumerate(reference, 1):
        current = [(i, 0, 0, i)]
        for j, cand in enumerate(candidate, 1):
            if ref == cand:
                current.append(previous[j - 1])
                continue
            p, d, ins = previous[j - 1], previous[j], current[j - 1]
            choices = [(p[0] + 1, p[1] + 1, p[2], p[3]),
                       (d[0] + 1, d[1], d[2], d[3] + 1),
                       (ins[0] + 1, ins[1], ins[2] + 1, ins[3])]
            current.append(min(choices, key=lambda cell: (cell[0], cell[2] + cell[3], cell[3])))
        previous = current
    edits, substitutions, insertions, deletions = previous[-1]
    return {"reference_chars": len(reference), "candidate_chars": len(candidate),
            "substitutions": substitutions, "insertions": insertions, "deletions": deletions,
            "edits": edits, "rate": edits / len(reference) if reference else None}


def full_span_gaps(cues, duration: float) -> list[Interval]:
    """Include leading/trailing gaps and the entire span when output is empty."""
    intervals = merge_intervals([Interval(max(0.0, item.start), min(duration, item.end))
                                 for item in cues if min(duration, item.end) > max(0.0, item.start)])
    gaps, covered_until = [], 0.0
    for item in intervals:
        if item.start > covered_until:
            gaps.append(Interval(covered_until, item.start))
        covered_until = max(covered_until, item.end)
    if duration > covered_until:
        gaps.append(Interval(covered_until, duration))
    return gaps


def align_cue_groups(reference: list[Cue], candidate: list[Cue], max_group: int = 3) -> list[dict]:
    """Monotonic one-use matches; at most max_group cues on each side.

    Matching uses text only, never a padded time window. This heuristic is for
    locating examples and comparable boundaries; global character errors are exact.
    """
    if len(reference) > 150 or len(candidate) > 150:
        raise ValueError("group alignment is clip-level (maximum 150 cues per side)")
    if max_group < 1 or max_group > 3:
        raise ValueError("max_group must be in [1, 3]")
    n, m = len(reference), len(candidate)
    costs = [[math.inf] * (m + 1) for _ in range(n + 1)]
    parents: dict[tuple[int, int], tuple[int, int]] = {}
    costs[0][0] = 0.0

    @lru_cache(maxsize=None)
    def group_text(side: str, start: int, count: int) -> str:
        cues = reference if side == "r" else candidate
        return normalize_text("".join(c.text for c in cues[start:start + count]))

    def relax(i: int, j: int, ni: int, nj: int, extra: float):
        value = costs[i][j] + extra
        if value < costs[ni][nj] - 1e-9:
            costs[ni][nj] = value
            parents[ni, nj] = (i, j)

    for i in range(n + 1):
        for j in range(m + 1):
            if not math.isfinite(costs[i][j]):
                continue
            for a in range(1, min(max_group, n - i) + 1):
                left = group_text("r", i, a)
                for b in range(1, min(max_group, m - j) + 1):
                    right = group_text("c", j, b)
                    similarity = difflib.SequenceMatcher(None, left, right, autojunk=False).ratio()
                    if left and right and similarity >= 0.5:
                        relax(i, j, i + a, j + b,
                              (1 - similarity) * (len(left) + len(right)) + 0.05 * (a + b - 2))
            if i < n:
                relax(i, j, i + 1, j, max(1, len(group_text("r", i, 1))))
            if j < m:
                relax(i, j, i, j + 1, max(1, len(group_text("c", j, 1))))
    groups, i, j = [], n, m
    while i or j:
        pi, pj = parents[i, j]
        refs, cands = reference[pi:i], candidate[pj:j]
        groups.append({"reference_ids": [c.index for c in refs], "candidate_ids": [c.index for c in cands],
                       "status": "matched" if refs and cands else "missing_reference_text" if refs else "extra_candidate_text",
                       "reference_text": "".join(c.text for c in refs),
                       "candidate_text": "".join(c.text for c in cands),
                       "start_delta_s": cands[0].start - refs[0].start if refs and cands else None,
                       "end_delta_s": cands[-1].end - refs[-1].end if refs and cands else None})
        i, j = pi, pj
    return list(reversed(groups))


def distribution(values: list[float]) -> dict:
    if not values:
        return {"count": 0, "mae_s": None, "median_abs_s": None, "p95_abs_s": None}
    ordered = sorted(abs(value) for value in values)

    def quantile(q):
        position = (len(ordered) - 1) * q
        lo, hi = math.floor(position), math.ceil(position)
        return ordered[lo] + (ordered[hi] - ordered[lo]) * (position - lo)

    return {"count": len(values), "mae_s": sum(ordered) / len(ordered),
            "median_abs_s": quantile(0.5), "p95_abs_s": quantile(0.95)}


def compare_subtitles(reference: SubtitleInput, candidate: SubtitleInput, reference_kind: str,
                      *, boundaries_verified: bool = False) -> dict:
    if reference_kind not in REFERENCE_KINDS:
        raise ValueError(f"unknown reference kind: {reference_kind}")
    result = {"schema_version": SCHEMA_VERSION, "evaluator_version": EVALUATOR_VERSION,
              "reference_kind": reference_kind, "reference_input": reference.summary(),
              "candidate_input": candidate.summary(), "true_cer": None, "text_difference": None,
              "timing_accuracy": None, "boundary_difference": None, "groups": [], "limitations": []}
    if reference.status != "valid" or candidate.status not in ("valid", "empty"):
        result["status"] = "unavailable"
        result["limitations"].append("missing, empty-reference or invalid input; no accuracy score")
        return result
    ref = "".join(c.text for c in reference.cues)
    cand = "".join(c.text for c in candidate.cues)
    if max(len(ref), len(cand)) > 8000 or len(ref) * len(cand) > 4_000_000:
        result["status"] = "unavailable"
        result["limitations"].append("text comparison exceeds clip-level budget; split into predefined samples")
        return result
    differences = {"raw": character_errors(ref, cand),
                   "normalized": character_errors(normalize_text(ref), normalize_text(cand)),
                   "normalization": "NFC; remove Unicode punctuation/whitespace; retain long vowels and repetitions"}
    result["text_difference"] = differences
    if reference_kind == "audio_verified":
        result["true_cer"] = differences["normalized"]
    else:
        result["limitations"].append("text difference from a provisional reference is not ASR accuracy")
    try:
        groups = align_cue_groups(reference.cues, candidate.cues)
    except ValueError as exc:
        result["limitations"].append(str(exc))
        groups = []
    result["groups"] = groups
    matched = [group for group in groups if group["status"] == "matched"]
    # Boundaries are comparable only for equal normalized text, not an approximate match.
    exact = [group for group in matched if normalize_text(group["reference_text"]) == normalize_text(group["candidate_text"])]
    result["boundary_difference"] = {"start": distribution([g["start_delta_s"] for g in exact]),
                                     "end": distribution([g["end_delta_s"] for g in exact]),
                                     "exact_groups": len(exact), "matched_groups": len(matched),
                                     "reference_cues": len(reference.cues),
                                     "matched_reference_cues": sum(len(g["reference_ids"]) for g in matched),
                                     "exact_reference_cues": sum(len(g["reference_ids"]) for g in exact)}
    if reference_kind == "audio_verified" and boundaries_verified:
        result["timing_accuracy"] = result["boundary_difference"]
    else:
        result["limitations"].append("reference timing is not verified; boundary differences are descriptive")
    result["status"] = "evaluated"
    return result


def validate_translation_ids(source_ids: list[str], records: list[dict]) -> dict:
    """Validate explicit merge/delete mapping independently of semantic correctness."""
    expected, consumed, issues, deleted = set(source_ids), [], [], []
    if len(expected) != len(source_ids):
        issues.append("duplicate source IDs")
    source_positions = {value: index for index, value in enumerate(source_ids)}
    for number, record in enumerate(records, 1):
        if not isinstance(record, dict):
            issues.append(f"record {number}: expected object")
            continue
        ids = record.get("ids")
        text = record.get("text")
        if not isinstance(ids, list) or not ids or any(not isinstance(value, str) for value in ids):
            issues.append(f"record {number}: nonempty string IDs required")
            continue
        consumed.extend(ids)
        if text is None:
            deleted.extend(ids)
        elif not isinstance(text, str) or not text.strip():
            issues.append(f"record {number}: text must be nonempty string or explicit null")
        if all(value in source_positions for value in ids):
            positions = [source_positions[value] for value in ids]
            if positions != list(range(positions[0], positions[0] + len(positions))):
                issues.append(f"record {number}: merged IDs must be consecutive and ordered")
    missing, unknown = sorted(expected - set(consumed)), sorted(set(consumed) - expected)
    duplicates = sorted({value for value in consumed if consumed.count(value) > 1})
    if missing:
        issues.append("missing source IDs")
    if unknown:
        issues.append("unknown source IDs")
    if duplicates:
        issues.append("repeated source IDs")
    positions = [source_positions[value] for value in consumed if value in source_positions]
    if positions != sorted(positions):
        issues.append("output records reorder source IDs")
    return {"valid": not issues, "issues": issues, "missing_ids": missing, "unknown_ids": unknown,
            "duplicate_ids": duplicates, "deleted_ids_need_review": deleted, "semantic_correctness": "not_assessed"}


def cache_fingerprint(provenance: dict) -> str:
    """Input/model/config/runtime/evaluator revisions belong in the supplied provenance."""
    payload = json.dumps({"evaluator_version": EVALUATOR_VERSION, "provenance": provenance},
                         ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode()).hexdigest()


def cues_as_dicts(cues: list[Cue]) -> list[dict]:
    return [asdict(cue) for cue in cues]
