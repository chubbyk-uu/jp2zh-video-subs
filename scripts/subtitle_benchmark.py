"""Cross-model consensus benchmark for Japanese ASR subtitles (no ground truth).

Why: with no human-verified transcript, comparing a candidate SRT against a single
reference (e.g. WhisperJAV anime) is biased — that reference is itself wrong on hard
audio, and raw text similarity underrates same-reading wording (乾杯 vs かんぱい) and
different cue lengths.

Approach:
  1. Build a pseudo-ground-truth from *cross-model consensus*: a segment where an anime
     source AND at least one qwen source agree (reading-normalized) is high-confidence
     real dialogue. Reference sources disagreeing on a segment are isolated as
     "needs human" and excluded from scoring — this is where wrong conclusions came from.
  2. Score each candidate on: consensus recall (recognition quality on confirmed
     dialogue), weak-speech recall (anime-only segments the qwen models missed), and
     timing health (short flashes / overlaps / long cues).
  3. Reading normalization (pykakasi 漢字→かな) removes homophone / kana-variant bias.

Usage:
  python subtitle_benchmark.py \
    --anime-ref WJ-anime=/path/wj_anime.srt \
    --qwen-ref  WJ-qwen=/path/wj_qwen.srt --qwen-ref ours-qwen=/path/ours_qwen.srt \
    --cand vad_only=/path/mg5.srt --cand aligner=/path/aligner.srt
"""
from __future__ import annotations

import argparse
import json
import re
from functools import lru_cache
from pathlib import Path

import pykakasi

_KKS = pykakasi.kakasi()
_STRIP = re.compile(r"[。、，,！？!?…♪〜~ー・「」『』（）()\[\]【】\s]")


@lru_cache(maxsize=200000)
def reading(text: str) -> str:
    """Hiragana reading string with punctuation/interjection marks removed."""
    return "".join(x["hira"] for x in _KKS.convert(_STRIP.sub("", text)))


def bigrams(text: str) -> set[str]:
    r = reading(text)
    return {r[i : i + 2] for i in range(len(r) - 1)}


def overlap(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a) if a else 0.0


def parse_srt(path: str) -> list[tuple[float, float, str]]:
    s = open(path, encoding="utf-8").read()
    out = []
    for block in re.split(r"\n\n+", s.strip()):
        lines = block.strip().split("\n")
        if len(lines) < 3:
            continue
        m = re.search(r"(\d\d):(\d\d):(\d\d),(\d\d\d) --> (\d\d):(\d\d):(\d\d),(\d\d\d)", lines[1])
        if not m:
            continue
        v = list(map(int, m.groups()))
        a = v[0] * 3600 + v[1] * 60 + v[2] + v[3] / 1000
        e = v[4] * 3600 + v[5] * 60 + v[6] + v[7] / 1000
        out.append((a, e, " ".join(lines[2:])))
    return out


def window_bigrams(cues, t0: float, t1: float, pad: float = 4.0) -> set[str]:
    txt = " ".join(c[2] for c in cues if c[1] >= t0 - pad and c[0] <= t1 + pad)
    return bigrams(txt)


DIALOGUE_MIN_READING = 3          # skip pure interjections/moans
MATCH_THRESHOLD = 0.34            # reading-bigram overlap to count as "same content"


def build_benchmark(anime_ref, qwen_refs):
    """Return (consensus, anime_only). consensus = anime cues confirmed by >=1 qwen
    source (cross-model). anime_only = anime cues no qwen source has (weak speech)."""
    consensus, anime_only = [], []
    for a, e, t in anime_ref:
        if len(reading(t)) < DIALOGUE_MIN_READING:
            continue
        wg = bigrams(t)
        if not wg:
            continue
        confirmed = any(overlap(wg, window_bigrams(q, a, e)) >= MATCH_THRESHOLD for q in qwen_refs)
        (consensus if confirmed else anime_only).append((a, e, wg))
    return consensus, anime_only


def recall(cand, segments) -> tuple[int, int]:
    hit = 0
    for a, e, wg in segments:
        if overlap(wg, window_bigrams(cand, a, e)) >= MATCH_THRESHOLD:
            hit += 1
    return hit, len(segments)


def fmt_recall(hit: int, total: int) -> str:
    if total == 0:
        return f"n/a ({hit}/{total})"
    return f"{100 * hit / total:.1f}% ({hit}/{total})"


def timing_health(cand) -> dict:
    n = len(cand)
    short = sum(1 for a, e, _ in cand if e - a < 0.4)
    long = sum(1 for a, e, _ in cand if e - a > 8)
    cs = sorted(cand)
    ov = sum(1 for i in range(1, len(cs)) if cs[i - 1][1] - cs[i][0] > 1e-6)
    return {"cues": n, "short<0.4": short, "long>8s": long, "overlaps": ov}


def score_candidates(anime_ref, qwen_refs, cands: dict[str, list[tuple[float, float, str]]]) -> dict:
    consensus, anime_only = build_benchmark(anime_ref, qwen_refs)
    rows = []
    for name, cand in cands.items():
        ch, ct = recall(cand, consensus)
        wh, wt = recall(cand, anime_only)
        th = timing_health(cand)
        rows.append({
            "candidate": name,
            "consensus_hit": ch,
            "consensus_total": ct,
            "consensus_recall": round(ch / ct, 4) if ct else None,
            "weak_speech_hit": wh,
            "weak_speech_total": wt,
            "weak_speech_recall": round(wh / wt, 4) if wt else None,
            "timing": th,
        })
    return {
        "consensus_segments": len(consensus),
        "anime_only_weak_speech_segments": len(anime_only),
        "candidates": rows,
    }


def render_report(result: dict, anime_name: str, qwen_ref_count: int) -> str:
    lines = [
        f"Benchmark from anime={anime_name} + {qwen_ref_count} qwen refs:",
        f"  cross-model consensus (scored) : {result['consensus_segments']} segments",
        f"  anime-only weak speech         : {result['anime_only_weak_speech_segments']} segments",
        "  (isolated as 'needs human': reference-disagreement segments not scored)",
        "",
        f"{'candidate':16} {'consensus-recall':>18} {'weak-speech-recall':>20} {'timing'}",
    ]
    for row in result["candidates"]:
        th = row["timing"]
        lines.append(
            f"{row['candidate']:16} "
            f"{fmt_recall(row['consensus_hit'], row['consensus_total']):>18} "
            f"{fmt_recall(row['weak_speech_hit'], row['weak_speech_total']):>20} "
            f"  cues={th['cues']} short={th['short<0.4']} long={th['long>8s']} ov={th['overlaps']}"
        )
    return "\n".join(lines)


def kv(pairs):
    d = {}
    for p in pairs:
        k, v = p.split("=", 1)
        d[k] = parse_srt(v)
    return d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--anime-ref", required=True, help="name=path (anime reference, e.g. WJ-anime)")
    ap.add_argument("--qwen-ref", action="append", required=True, help="name=path (qwen reference)")
    ap.add_argument("--cand", action="append", required=True, help="name=path (candidate to score)")
    ap.add_argument("--json-output", type=Path, help="Write structured benchmark metrics to JSON.")
    args = ap.parse_args()

    aname, apath = args.anime_ref.split("=", 1)
    anime_ref = parse_srt(apath)
    qwen_refs = list(kv(args.qwen_ref).values())
    cands = kv(args.cand)

    result = score_candidates(anime_ref, qwen_refs, cands)
    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(render_report(result, aname, len(args.qwen_ref)))


if __name__ == "__main__":
    main()
