"""End-to-end A/B blind test for candidate models, judged by a Chinese-only viewer.

Subcommands:
  pipeline  run the production pipeline on whole videos (default, or Qwen ASR with swapped weights)
  asmr      translate the default run's Japanese SRT with the experimental ASMR GGUF model
  build     pick differing windows, cut clips and write a local blind comparison page
  score     unblind exported votes and report wins/ties with a two-sided sign test

The viewer never sees Japanese or model names; the A/B mapping is stored outside the page.
Everything stays under a local, Git-ignored output directory.
"""
from __future__ import annotations

import argparse
import difflib
import json
import math
import os
import random
import subprocess
import sys
import time
from pathlib import Path

from translation_common import Entry, parse_srt, write_entry

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
LEAD_OUT_SECONDS = 0.5  # orchestrator defaults, so ASMR cues are displayed like GalTransl cues
MIN_DISPLAY_SECONDS = 1.5


def load_videos(path: Path) -> list[dict]:
    videos = json.loads(path.read_text(encoding="utf-8"))["videos"]
    ids = [video["id"] for video in videos]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate video IDs")
    return videos


def run_dir(out: Path, variant: str) -> Path:
    return out / "runs" / variant


def zh_srt_path(out: Path, variant: str, video_id: str) -> Path:
    return run_dir(out, variant) / f"{video_id}.zh.srt"


def ja_srt_path(out: Path, variant: str, video: dict) -> Path:
    return run_dir(out, variant) / "work" / Path(video["video"]).stem / f"{Path(video['video']).stem}.ja.srt"


# ---------------------------------------------------------------- pipeline

def pipeline_command(video: dict, out: Path, variant: str, qwen_model: Path | None) -> list[str]:
    if not out.is_absolute() or (qwen_model is not None and not qwen_model.is_absolute()):
        raise ValueError("pipeline paths must be absolute; the subprocess runs from the repository root")
    argv =["video_to_zh_srt.py", video["video"],
            "--output", str(zh_srt_path(out, variant, video["id"])),
            "--work-dir", str(run_dir(out, variant) / "work"),
            "--no-bilingual", "--no-copy-to-video-dir", "--resume",
            "--asr", "qwen" if qwen_model else "anime"]
    # The orchestrator hardcodes the Qwen weights path; swap only that module constant so
    # every other stage, default and provenance record is the production code path.
    patch = f"m.QWEN_ASR_MODEL = Path({str(qwen_model)!r}); " if qwen_model else ""
    code = (f"import sys; from pathlib import Path; sys.path.insert(0, {str(SCRIPTS)!r}); "
            f"import video_to_zh_srt as m; {patch}sys.argv = {argv!r}; m.main()")
    return [sys.executable, "-c", code]


def cmd_pipeline(args) -> int:
    if args.variant != "default" and args.qwen_model is None:
        raise SystemExit("--qwen-model is required for a candidate ASR variant")
    qwen_model = args.qwen_model if args.variant != "default" else None
    record = {"variant": args.variant, "qwen_model": str(qwen_model) if qwen_model else None, "videos": {}}
    run_dir(args.out, args.variant).mkdir(parents=True, exist_ok=True)
    # A stale shared Numba cache has segfaulted audio preprocessing before; use a private one.
    env = {**os.environ, "NUMBA_CACHE_DIR": str(args.out / "numba-cache")}
    failed = False
    for video in load_videos(args.videos):
        started = time.monotonic()
        with (run_dir(args.out, args.variant) / f"{video['id']}.log").open("a", encoding="utf-8") as log:
            code = subprocess.run(pipeline_command(video, args.out, args.variant, qwen_model),
                                  stdout=log, stderr=subprocess.STDOUT, cwd=ROOT, env=env).returncode
        record["videos"][video["id"]] = {"returncode": code, "elapsed_s": round(time.monotonic() - started, 1)}
        print(f"{args.variant} {video['id']}: rc={code} {record['videos'][video['id']]['elapsed_s']}s", flush=True)
        failed |= code != 0
    (run_dir(args.out, args.variant) / "run.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return int(failed)


# ---------------------------------------------------------------- ASMR translation

def asmr_windows(entries: list[Entry], max_cues: int, reset_gap: float) -> list[list[Entry]]:
    """Consecutive cue windows that never cross a long pause (a scene/turn boundary)."""
    windows: list[list[Entry]] = []
    for entry in entries:
        if windows and len(windows[-1]) < max_cues and entry.start - windows[-1][-1].end <= reset_gap:
            windows[-1].append(entry)
        else:
            windows.append([entry])
    return windows


def asmr_rows(window: list[Entry]) -> list[dict]:
    return [{"id": str(number), "ja": entry.text, "start_s": entry.start, "end_s": entry.end}
            for number, entry in enumerate(window, 1)]


def records_to_cues(records: list[dict]) -> list[tuple[float, float, str]]:
    """Keep model merges, drop explicit null deletions; times come from source IDs only."""
    return [(record["start_s"], record["end_s"], record["text"].strip())
            for record in records if record["text"] is not None and record["text"].strip()]


def window_token_budget(cue_count: int) -> int:
    """~30 tokens per cue in practice; the cap stops runaway repetition from eating minutes."""
    return min(2048, 100 * cue_count + 100)


def translate_window(llm, window: list[Entry], label: str, stats: dict, log=None) -> list[tuple[float, float, str]]:
    from evaluation_translation import asmr_prompt, check_asmr_output, qwen_no_thinking_prompt, translation_schema
    from llama_cpp import LlamaGrammar

    rows = asmr_rows(window)
    prompt = qwen_no_thinking_prompt(asmr_prompt(rows, label))
    # Same prompt and greedy decoding as run_evaluation_translation.py. The JSON grammar is
    # only a fallback: on the 20 evaluation windows grammar-free output was byte-identical
    # and ~3.4x faster, because llama.cpp grammar sampling is CPU-bound.
    for grammar in (None, LlamaGrammar.from_json_schema(json.dumps(translation_schema()))):
        started = time.monotonic()
        response = llm.create_completion(prompt=prompt, grammar=grammar, temperature=0,
                                         max_tokens=window_token_budget(len(rows)),
                                         stop=["<|im_end|>"], repeat_penalty=1.0)
        tokens = (response.get("usage") or {}).get("completion_tokens", 0)
        finish = response["choices"][0].get("finish_reason")
        stats["completion_tokens"] += tokens
        stats["length_stops"] += finish == "length"
        checked = check_asmr_output(response["choices"][0]["text"], rows)
        if log is not None:
            log.write(json.dumps({"video": label, "start": window[0].start, "cues": len(rows),
                                  "grammar": grammar is not None, "tokens": tokens, "finish": finish,
                                  "valid": checked["valid"], "elapsed_s": round(time.monotonic() - started, 2)}) + "\n")
        if checked["valid"]:
            stats["deleted"] += len(checked["deleted_ids_need_review"])
            stats["merged"] += sum(len(record["ids"]) - 1 for record in checked["records"])
            stats["grammar_fallbacks"] += grammar is not None
            return records_to_cues(checked["records"])
        if finish == "length":
            # Greedy runaway repetition: the grammar only masks tokens, so a grammar retry
            # replays the same loop (much slower). Split the window instead.
            break
    stats["invalid_windows"] += 1
    if len(window) == 1:
        stats["failed_cues"] += 1
        return []
    middle = len(window) // 2
    return (translate_window(llm, window[:middle], label, stats, log)
            + translate_window(llm, window[middle:], label, stats, log))


def write_cues(path: Path, cues: list[tuple[float, float, str]]) -> None:
    from srt_utils import srt_time

    cues = sorted(cues)
    entries = [Entry(str(number), f"{srt_time(start)} --> {srt_time(end)}", text, start, end)
               for number, (start, end, text) in enumerate(cues, 1)]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        for index, entry in enumerate(entries):
            following = entries[index + 1] if index + 1 < len(entries) else None
            write_entry(stream, entry, entry.text, following, LEAD_OUT_SECONDS, MIN_DISPLAY_SECONDS)


def cmd_asmr(args) -> int:
    from llama_cpp import Llama

    from srt_utils import wrap_srt_display_file
    from target_languages import resolve_translation_settings

    wrap_chars = resolve_translation_settings("galtransl", "zh-Hans").wrap_chars
    llm = Llama(model_path=str(args.model), n_gpu_layers=-1, n_ctx=8192, seed=0, verbose=False)
    record = {"model": str(args.model), "source_variant": args.source_variant,
              "max_cues": args.max_cues, "videos": {}}
    for video in load_videos(args.videos):
        output = zh_srt_path(args.out, "asmr", video["id"])
        if output.exists():
            print(f"asmr {video['id']}: exists, skip", flush=True)
            continue
        entries = parse_srt(ja_srt_path(args.out, args.source_variant, video))
        stats = {"cues": len(entries), "completion_tokens": 0, "deleted": 0, "merged": 0, "length_stops": 0,
                 "grammar_fallbacks": 0, "invalid_windows": 0, "failed_cues": 0}
        started = time.monotonic()
        cues: list[tuple[float, float, str]] = []
        windows = asmr_windows(entries, args.max_cues, 10.0)
        run_dir(args.out, "asmr").mkdir(parents=True, exist_ok=True)
        with (run_dir(args.out, "asmr") / f"{video['id']}.windows.jsonl").open("w", encoding="utf-8") as log:
            for number, window in enumerate(windows, 1):
                cues.extend(translate_window(llm, window, video["id"], stats, log))
                log.flush()
                if number % 20 == 0:
                    print(f"asmr {video['id']}: {number}/{len(windows)} windows "
                          f"{time.monotonic() - started:.0f}s", flush=True)
        partial = output.with_suffix(".partial.srt")
        write_cues(partial, cues)
        wrap_srt_display_file(partial, wrap_chars, "zh-Hans")
        partial.replace(output)
        stats["elapsed_s"] = round(time.monotonic() - started, 1)
        record["videos"][video["id"]] = stats
        print(f"asmr {video['id']}: {stats}", flush=True)
        (run_dir(args.out, "asmr") / "run.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return 0


# ---------------------------------------------------------------- window selection

def cue_text(entry: Entry) -> str:
    return "".join(entry.text.split())


def window_text(entries: list[Entry], start: float, end: float) -> str:
    """Cues belong to the window containing their start, so no cue is counted twice."""
    return "".join(cue_text(entry) for entry in entries if start <= entry.start < end)


def differing_windows(a: list[Entry], b: list[Entry], duration: float, *, window: float,
                      threshold: float, min_chars: int) -> list[dict]:
    found = []
    for index in range(int(math.ceil(duration / window))):
        start, end = index * window, min(duration, (index + 1) * window)
        text_a, text_b = window_text(a, start, end), window_text(b, start, end)
        if max(len(text_a), len(text_b)) < min_chars:
            continue
        ratio = difflib.SequenceMatcher(None, text_a, text_b, autojunk=False).ratio()
        if ratio < threshold:
            found.append({"index": index, "start": start, "end": end, "similarity": round(ratio, 3)})
    return found


def sample_windows(candidates: dict[str, list[dict]], count: int, seed: int) -> list[tuple[str, dict]]:
    """Random, round-robin across videos, never two adjacent windows from one video."""
    rng = random.Random(seed)
    pools = {video_id: rng.sample(items, len(items)) for video_id, items in sorted(candidates.items())}
    chosen: list[tuple[str, dict]] = []
    taken: dict[str, set[int]] = {video_id: set() for video_id in pools}
    while len(chosen) < count and any(pools.values()):
        for video_id in sorted(pools):
            pool = pools[video_id]
            while pool:
                item = pool.pop()
                if not {item["index"] - 1, item["index"], item["index"] + 1} & taken[video_id]:
                    taken[video_id].add(item["index"])
                    chosen.append((video_id, item))
                    break
            if len(chosen) >= count:
                break
    rng.shuffle(chosen)
    return chosen


def clip_cues(entries: list[Entry], start: float, end: float) -> list[dict]:
    return [{"s": round(max(0.0, entry.start - start), 2), "e": round(min(end, entry.end) - start, 2),
             "t": entry.text.replace("\n", " ")}
            for entry in entries if entry.end > start and entry.start < end]


def media_duration(path: str) -> float:
    result = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                            capture_output=True, text=True, check=True)
    return float(result.stdout.strip())


def cut_clip(video: str, start: float, duration: float, output: Path) -> None:
    if output.exists() and output.stat().st_size > 0:
        return
    partial = output.with_suffix(".partial.mp4")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{start:.3f}", "-i", video, "-t", f"{duration:.3f}",
                    "-vf", "scale=-2:540", "-c:v", "libx264", "-preset", "veryfast", "-crf", "26",
                    "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(partial)], check=True)
    partial.replace(output)


def cmd_build(args) -> int:
    test_dir = args.out / "tests" / args.name
    page_dir, private_dir = test_dir / "page", test_dir / "private"
    if (private_dir / "mapping.json").exists():
        raise SystemExit(f"test already built: {test_dir}; choose a new --name")
    videos = {video["id"]: video for video in load_videos(args.videos)}
    subtitles, candidates, durations = {}, {}, {}
    for video_id, video in videos.items():
        a = parse_srt(zh_srt_path(args.out, args.baseline, video_id))
        b = parse_srt(zh_srt_path(args.out, args.candidate, video_id))
        durations[video_id] = media_duration(video["video"])
        subtitles[video_id] = {args.baseline: a, args.candidate: b}
        candidates[video_id] = differing_windows(a, b, durations[video_id], window=args.window,
                                                 threshold=args.threshold, min_chars=args.min_chars)
        print(f"{video_id}: {len(candidates[video_id])} differing windows", flush=True)
    chosen = sample_windows(candidates, args.count, args.seed)
    rng = random.Random(args.seed + 1)
    items, mapping = [], {}
    (page_dir / "clips").mkdir(parents=True, exist_ok=True)
    private_dir.mkdir(parents=True, exist_ok=True)
    for number, (video_id, window) in enumerate(chosen, 1):
        start = max(0.0, window["start"] - args.lead_in)
        end = min(durations[video_id], window["end"] + args.tail)
        clip = page_dir / "clips" / f"{number:03d}.mp4"
        cut_clip(videos[video_id]["video"], start, end - start, clip)
        order = [args.baseline, args.candidate]
        rng.shuffle(order)
        items.append({"n": number, "clip": f"clips/{clip.name}",
                      "a": clip_cues(subtitles[video_id][order[0]], start, end),
                      "b": clip_cues(subtitles[video_id][order[1]], start, end)})
        mapping[str(number)] = {"A": order[0], "B": order[1], "video": video_id,
                                "start": round(start, 2), "end": round(end, 2), "similarity": window["similarity"]}
        print(f"clip {number}/{len(chosen)}", flush=True)
    (private_dir / "mapping.json").write_text(json.dumps(
        {"name": args.name, "baseline": args.baseline, "candidate": args.candidate, "seed": args.seed,
         "window": args.window, "threshold": args.threshold, "min_chars": args.min_chars,
         "candidate_windows": {video_id: len(items_) for video_id, items_ in candidates.items()},
         "items": mapping}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    template = (SCRIPTS / "ab_blind_test_page.html").read_text(encoding="utf-8")
    page = template.replace("__TEST_NAME__", json.dumps(args.name)).replace(
        "__ITEMS__", json.dumps(items, ensure_ascii=False).replace("</", "<\\/"))
    (page_dir / "index.html").write_text(page, encoding="utf-8")
    print(f"page: {page_dir / 'index.html'}", flush=True)
    return 0


# ---------------------------------------------------------------- scoring

def sign_test_p(wins: int, losses: int) -> float:
    """Two-sided exact binomial sign test; ties are excluded by the caller."""
    total = wins + losses
    if total == 0:
        return 1.0
    tail = sum(math.comb(total, k) for k in range(min(wins, losses) + 1)) / 2 ** total
    return min(1.0, 2 * tail)


def tally(mapping: dict, votes: dict[str, str]) -> dict:
    baseline, candidate = mapping["baseline"], mapping["candidate"]
    result = {"candidate_wins": 0, "baseline_wins": 0, "ties": 0, "unvoted": 0, "by_video": {}}
    for number, item in mapping["items"].items():
        vote = votes.get(number)
        per_video = result["by_video"].setdefault(item["video"], {"candidate_wins": 0, "baseline_wins": 0, "ties": 0})
        if vote in ("A", "B"):
            key = "candidate_wins" if item[vote] == candidate else "baseline_wins"
        elif vote == "tie":
            key = "ties"
        else:
            result["unvoted"] += 1
            continue
        result[key] += 1
        per_video[key] += 1
    result["p_value"] = round(sign_test_p(result["candidate_wins"], result["baseline_wins"]), 4)
    result["baseline"], result["candidate"] = baseline, candidate
    return result


def cmd_score(args) -> int:
    mapping = json.loads((args.test / "private" / "mapping.json").read_text(encoding="utf-8"))
    exported = json.loads(args.votes.read_text(encoding="utf-8"))
    if exported.get("test") != mapping["name"]:
        raise SystemExit(f"votes are for {exported.get('test')!r}, not {mapping['name']!r}")
    result = tally(mapping, exported["votes"])
    (args.test / "private" / "score.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                                                      encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--videos", type=Path, required=True, help='JSON: {"videos": [{"id", "video"}]}')
    common.add_argument("--out", type=Path, required=True, help="Git-ignored experiment directory")

    p = sub.add_parser("pipeline", parents=[common])
    p.add_argument("--variant", required=True, help="'default' (production) or a candidate name")
    p.add_argument("--qwen-model", type=Path, help="Qwen3-ASR weights for a candidate variant (runs --asr qwen)")
    p.set_defaults(func=cmd_pipeline)

    p = sub.add_parser("asmr", parents=[common])
    p.add_argument("--model", type=Path, required=True)
    p.add_argument("--source-variant", default="default", help="Variant whose Japanese SRT is translated")
    p.add_argument("--max-cues", type=int, default=20)
    p.set_defaults(func=cmd_asmr)

    p = sub.add_parser("build", parents=[common])
    p.add_argument("--name", required=True)
    p.add_argument("--baseline", default="default")
    p.add_argument("--candidate", required=True)
    p.add_argument("--count", type=int, default=30)
    p.add_argument("--seed", type=int, default=20260928)
    p.add_argument("--window", type=float, default=20.0)
    p.add_argument("--threshold", type=float, default=0.6, help="Differing when text similarity is below this")
    p.add_argument("--min-chars", type=int, default=8, help="Skip windows with less text than this in both arms")
    p.add_argument("--lead-in", type=float, default=5.0)
    p.add_argument("--tail", type=float, default=3.0)
    p.set_defaults(func=cmd_build)

    p = sub.add_parser("score")
    p.add_argument("--test", type=Path, required=True)
    p.add_argument("--votes", type=Path, required=True)
    p.set_defaults(func=cmd_score)

    args = parser.parse_args()
    # Pipeline subprocesses run from the repository root; never let a relative path
    # resolve against a different directory there.
    for name in ("videos", "out", "qwen_model", "model", "test", "votes"):
        if getattr(args, name, None) is not None:
            setattr(args, name, getattr(args, name).resolve())
    raise SystemExit(args.func(args))


if __name__ == "__main__":
    main()
