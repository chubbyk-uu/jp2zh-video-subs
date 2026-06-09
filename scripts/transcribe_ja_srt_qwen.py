from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import torch
from qwen_asr import Qwen3ASRModel

from srt_utils import Interval
from transcribe_ja_srt import (
    SubtitleEntry,
    filter_main_local_entries,
    resolve_overlaps,
    speech_clusters,
    speech_intervals_from_sliding_audio,
    split_clip_with_overlap,
    write_entries,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1] if Path(__file__).resolve().parent.name == "scripts" else Path(__file__).resolve().parent
DEFAULT_MODEL = PROJECT_ROOT / "models" / "Qwen3-ASR-1.7B"
DEFAULT_ALIGNER = PROJECT_ROOT / "models" / "Qwen3-ForcedAligner-0.6B"

# Characters that end a sentence-level cue.
SENTENCE_END_CHARS = "。！？!?…．."
# Punctuation/whitespace that carries no timing and is ignored when matching the
# punctuated `result.text` against the forced-aligner character stream.
PUNCT_CHARS = set("。、，,！？!?…．・「」『』（）()【】〔〕〜~ー　 \t\r\n")


@dataclass
class ChunkResult:
    start: float
    end: float
    language: str
    text: str
    segments: int
    seconds: float


def chunk_ranges(duration: float, chunk_seconds: float, overlap_seconds: float) -> list[tuple[float, float]]:
    if chunk_seconds <= 0:
        raise ValueError("--chunk-seconds must be positive")
    if overlap_seconds < 0:
        raise ValueError("--chunk-overlap-seconds must be non-negative")
    if overlap_seconds >= chunk_seconds:
        raise ValueError("--chunk-overlap-seconds must be smaller than --chunk-seconds")
    ranges: list[tuple[float, float]] = []
    step = chunk_seconds - overlap_seconds
    start = 0.0
    while start < duration:
        end = min(duration, start + chunk_seconds)
        ranges.append((start, end))
        if end >= duration:
            break
        start += step
    return ranges


def load_full_audio(path: Path):
    import soundfile as sf

    data, samplerate = sf.read(str(path), dtype="float32", always_2d=False)
    return data, int(samplerate)


def item_text(item) -> str:
    return str(getattr(item, "text", "")).strip()


def item_start(item) -> float:
    return float(getattr(item, "start_time"))


def item_end(item) -> float:
    return float(getattr(item, "end_time"))


def content_chars(text: str) -> list[str]:
    """Characters that carry timing \u2014 punctuation/whitespace stripped."""
    return [c for c in text if c not in PUNCT_CHARS]


def flatten_item_chars(time_stamps, max_char_seconds: float) -> list[tuple[str, float, float]]:
    """Flatten aligner items into a per-character (char, start, end) stream.

    Each item's duration is spread over its content characters so a sentence can
    later be timed by consuming a known number of characters. Zero-duration items
    keep their text (so trailing okurigana is not lost) but collapse to a point.

    The forced aligner anchors a chunk's first token to the chunk start, giving it
    an implausibly long span that swallows leading non-speech (e.g. a 3-char token
    stamped over 20s). When an item's per-character duration exceeds
    max_char_seconds, its characters are packed at that nominal rate against the
    item END (the reliable speech-side boundary) instead of spread from the start,
    so a cue is not dragged to the chunk edge.
    """
    out: list[tuple[str, float, float]] = []
    for item in time_stamps or []:
        if getattr(item, "start_time", None) is None or getattr(item, "end_time", None) is None:
            continue
        chars = content_chars(item_text(item))
        if not chars:
            continue
        start = item_start(item)
        end = item_end(item)
        if end <= start:
            for c in chars:
                out.append((c, start, start))
        elif (end - start) / len(chars) > max_char_seconds:
            base = end - len(chars) * max_char_seconds
            for k, c in enumerate(chars):
                out.append((c, base + k * max_char_seconds, base + (k + 1) * max_char_seconds))
        else:
            span = (end - start) / len(chars)
            for k, c in enumerate(chars):
                out.append((c, start + k * span, start + (k + 1) * span))
    return out


def split_into_units(text: str, max_chars: int) -> list[str]:
    """Split the punctuated transcript into sentence-level cue units.

    Primary split on sentence-ending punctuation; overly long units are split
    further on the soft separator \u3001 so cues stay readable.
    """
    units: list[str] = []
    buf = ""
    for ch in text:
        buf += ch
        if ch in SENTENCE_END_CHARS:
            units.append(buf)
            buf = ""
    if buf.strip():
        units.append(buf)

    result: list[str] = []
    for unit in units:
        if len(content_chars(unit)) <= max_chars:
            result.append(unit)
            continue
        sub = ""
        for ch in unit:
            sub += ch
            if ch == "\u3001" and len(content_chars(sub)) >= max_chars * 0.6:
                result.append(sub)
                sub = ""
        if sub:
            result.append(sub)
    return result


def sentences_from_alignment(
    text: str,
    time_stamps,
    *,
    offset: float,
    max_chars: int,
    max_duration: float,
    min_duration: float,
    max_internal_gap: float,
    max_char_seconds: float,
) -> list[SubtitleEntry]:
    """Build cues from the raw transcript, timed via the aligner stream.

    The punctuated `result.text` is authoritative for content (no token
    concatenation artifacts); aligner characters are consumed in order only to
    assign start/end. A 30s ASR window can merge utterances that are seconds
    apart into one sentence; the aligner then stretches that sentence across the
    pause. To keep each cue anchored to its own audio, a sentence is broken
    wherever consecutive characters are separated by more than max_internal_gap.
    Cue length is floored at min_duration and clamped at max_duration.
    """
    char_times = flatten_item_chars(time_stamps, max_char_seconds)
    units = split_into_units(text, max_chars)
    entries: list[SubtitleEntry] = []
    pos = 0
    for unit in units:
        content = content_chars(unit)
        need = len(content)
        if need == 0:
            continue
        span = char_times[pos : pos + need]
        pos += need
        if not span:
            continue
        # Split the unit on large internal time gaps, keeping punctuation attached
        # to the preceding content character.
        seg_chars: list[str] = []
        seg_span: list[tuple[str, float, float]] = []
        ci = 0
        prev_end: float | None = None

        def flush() -> None:
            if not seg_span:
                return
            start = offset + seg_span[0][1]
            end = offset + seg_span[-1][2]
            end = max(end, start + min_duration)
            end = min(end, start + max_duration)
            display = "".join(seg_chars).strip()
            if display:
                entries.append(SubtitleEntry(start, end, display))

        for ch in unit:
            if ch in PUNCT_CHARS:
                seg_chars.append(ch)
                continue
            if ci >= len(span):
                seg_chars.append(ch)
                continue
            cstart = span[ci][1]
            if prev_end is not None and seg_span and (cstart - prev_end) > max_internal_gap:
                flush()
                seg_chars = []
                seg_span = []
            seg_chars.append(ch)
            seg_span.append(span[ci])
            prev_end = span[ci][2]
            ci += 1
        flush()
    return entries


def drop_same_start_piles(entries: list[SubtitleEntry], tol: float = 0.05) -> list[SubtitleEntry]:
    """Drop cues piled on a single start time, keeping the first.

    In near-silent/moaning regions the forced aligner collapses many characters
    onto one timestamp, producing several cues with the same start that the shared
    overlap resolver leaves alone (it skips equal starts to avoid zero-duration
    cues). Their timing is meaningless, so rather than fan them into a flashing
    staircase we keep the first and discard the rest. Genuinely distinct cues have
    different start times and are untouched.
    """
    ordered = sorted(entries, key=lambda e: (e.start, e.end))
    result: list[SubtitleEntry] = []
    for entry in ordered:
        if result and entry.start - result[-1].start <= tol:
            continue
        result.append(entry)
    return result


def finalize_qwen_entries(entries: list[SubtitleEntry], args: argparse.Namespace) -> list[SubtitleEntry]:
    """Minimal time/format hygiene for Qwen output.

    Qwen rarely fabricates content, so the Whisper hallucination/near-duplicate
    filters are not applied here (they are opt-in via --filter-hallucinations).
    This keeps the transcript faithful: only overlap trimming, a sub-second
    flash-cue floor, and de-overlap of collapsed-timestamp cues.
    """
    entries = drop_same_start_piles(entries)
    entries = resolve_overlaps(entries)
    if args.min_cue_seconds > 0:
        entries = [e for e in entries if e.end - e.start >= args.min_cue_seconds]
    return entries


class _RawItem:
    """Lightweight stand-in for a forced-aligner item when replaying a raw dump."""

    __slots__ = ("text", "start_time", "end_time")

    def __init__(self, text: str, start_time: float, end_time: float) -> None:
        self.text = text
        self.start_time = start_time
        self.end_time = end_time


@dataclass
class ChunkJob:
    """A clip to transcribe plus its cue-ownership window.

    `start`/`end` bound the audio slice (absolute seconds). `keep_lo`/`keep_hi`
    are the half-open window whose cue centers this clip owns, so overlap that
    protects boundary words does not duplicate cues across adjacent clips.
    """

    start: float
    end: float
    keep_lo: float
    keep_hi: float


def build_fixed_jobs(duration: float, args: argparse.Namespace) -> list[ChunkJob]:
    """Uniform tiling over the whole timeline (the default, VAD-free path)."""
    ranges = chunk_ranges(duration, args.chunk_seconds, args.chunk_overlap_seconds)
    step = args.chunk_seconds - args.chunk_overlap_seconds
    jobs: list[ChunkJob] = []
    for start, end in ranges:
        is_last = end >= duration - 1e-3
        keep_hi = float("inf") if is_last else start + step
        jobs.append(ChunkJob(start, end, start, keep_hi))
    return jobs


def build_vad_jobs(audio, samplerate: int, duration: float, args: argparse.Namespace) -> list[ChunkJob]:
    """Speech-aligned clips: one clip per speech cluster, anchored to real time.

    Fixed tiling stamps a chunk's first token to the chunk start, so a clip whose
    speech begins seconds in drags that cue early. Cutting clips on silence puts
    each clip's first token where speech actually starts, removing that anchor
    drift. VAD is used only for boundary placement with a loose threshold: a
    missed boundary still leaves the audio covered by a neighbouring clip, so
    recall is unaffected.
    """
    if samplerate != 16000:
        raise SystemExit("--vad-chunks requires 16 kHz audio")
    intervals = speech_intervals_from_sliding_audio(
        audio,
        duration,
        args.vad_threshold,
        args.vad_min_silence_ms,
        args.vad_speech_pad_ms,
        args.vad_window_seconds,
        args.vad_window_overlap_seconds,
    )
    clusters = speech_clusters(intervals, args.vad_max_cluster_gap, args.vad_pad_seconds, duration)
    max_clip = min(args.chunk_seconds, 30.0)
    step = max_clip - args.chunk_overlap_seconds
    jobs: list[ChunkJob] = []
    for cluster in clusters:
        if cluster.end - cluster.start < args.vad_min_clip_seconds:
            continue
        subs = split_clip_with_overlap(cluster, max_clip, args.chunk_overlap_seconds)
        for i, sub in enumerate(subs):
            is_last = i == len(subs) - 1
            keep_hi = float("inf") if is_last else sub.start + step
            jobs.append(ChunkJob(sub.start, sub.end, sub.start, keep_hi))
    return jobs


def chunk_entries(
    text: str,
    items,
    *,
    start: float,
    keep_lo: float,
    keep_hi: float,
    args: argparse.Namespace,
) -> list[SubtitleEntry]:
    """Build one chunk's kept cues: sentence timing + claim-window dedup.

    Shared by the live model path and the --from-raw replay so both produce
    identical output for the same post-processing knobs. A cue is kept by the one
    clip whose [keep_lo, keep_hi) window holds the cue center.
    """
    sentence_entries = sentences_from_alignment(
        text,
        items,
        offset=start,
        max_chars=args.phrase_max_chars,
        max_duration=args.phrase_max_duration,
        min_duration=args.min_duration,
        max_internal_gap=args.phrase_max_internal_gap,
        max_char_seconds=args.phrase_max_char_seconds,
    )
    return [e for e in sentence_entries if keep_lo <= (e.start + e.end) / 2.0 < keep_hi]


def entries_from_raw(raw: dict, args: argparse.Namespace) -> list[SubtitleEntry]:
    """Rebuild cues from a dumped raw chunk stream, skipping the model entirely."""
    duration = raw["duration"]
    step = raw["chunk_seconds"] - raw["chunk_overlap_seconds"]
    entries: list[SubtitleEntry] = []
    for ch in raw["chunks"]:
        items = [_RawItem(it["text"], it["start"], it["end"]) for it in ch["items"]]
        if "keep_lo" in ch:
            keep_lo = ch["keep_lo"]
            keep_hi = ch["keep_hi"] if ch.get("keep_hi") is not None else float("inf")
        else:
            # Fallback for pre-VAD dumps that only recorded fixed-tiling chunks.
            keep_lo = ch["start"]
            keep_hi = float("inf") if ch["end"] >= duration - 1e-3 else ch["start"] + step
        entries.extend(
            chunk_entries(
                ch["text"], items, start=ch["start"],
                keep_lo=keep_lo, keep_hi=keep_hi, args=args,
            )
        )
    entries.sort(key=lambda e: (e.start, e.end))
    return entries


def transcribe_qwen(args: argparse.Namespace) -> tuple[list[SubtitleEntry], list[ChunkResult], dict]:
    model = Qwen3ASRModel.from_pretrained(
        str(args.model),
        dtype=getattr(torch, args.dtype),
        device_map=args.device,
        max_inference_batch_size=args.batch_size,
        max_new_tokens=args.max_new_tokens,
        forced_aligner=str(args.forced_aligner),
        forced_aligner_kwargs=dict(
            dtype=getattr(torch, args.dtype),
            device_map=args.device,
        ),
    )

    audio, samplerate = load_full_audio(args.audio)
    duration = audio.shape[0] / float(samplerate)
    if args.vad_chunks:
        jobs = build_vad_jobs(audio, samplerate, duration, args)
        mode = "vad"
    else:
        jobs = build_fixed_jobs(duration, args)
        mode = "fixed"
    entries: list[SubtitleEntry] = []
    chunk_results: list[ChunkResult] = []
    raw_chunks: list[dict] = []
    print(
        f"Qwen ASR: audio={duration / 60.0:.1f}min mode={mode} chunks={len(jobs)} "
        f"batch={args.batch_size} chunk_seconds={args.chunk_seconds} overlap={args.chunk_overlap_seconds}",
        flush=True,
    )

    for group_start in range(0, len(jobs), args.batch_size):
        group = jobs[group_start : group_start + args.batch_size]
        clips = [(audio[int(j.start * samplerate) : int(j.end * samplerate)], samplerate) for j in group]
        t0 = time.time()
        results = model.transcribe(
            audio=clips,
            language=[args.language] * len(clips),
            return_time_stamps=True,
        )
        elapsed = time.time() - t0
        for job, result in zip(group, results):
            text = str(result.text or "").strip()
            items = getattr(result.time_stamps, "items", None) if result.time_stamps is not None else None
            kept = chunk_entries(
                text, items, start=job.start,
                keep_lo=job.keep_lo, keep_hi=job.keep_hi, args=args,
            )
            entries.extend(kept)
            raw_chunks.append(
                {
                    "start": job.start,
                    "end": job.end,
                    "keep_lo": job.keep_lo,
                    "keep_hi": None if job.keep_hi == float("inf") else job.keep_hi,
                    "language": str(result.language),
                    "text": text,
                    "items": [
                        {"text": it.text, "start": float(it.start_time), "end": float(it.end_time)}
                        for it in (items or [])
                        if getattr(it, "start_time", None) is not None
                        and getattr(it, "end_time", None) is not None
                    ],
                }
            )
            chunk_results.append(
                ChunkResult(
                    start=job.start,
                    end=job.end,
                    language=str(result.language),
                    text=text,
                    segments=len(kept),
                    seconds=elapsed / len(group),
                )
            )
        done = min(group_start + args.batch_size, len(jobs))
        last_text = str(results[-1].text or "").strip()
        print(
            f"{done}/{len(jobs)} batch_elapsed={elapsed:.2f}s text={last_text[:60]}",
            flush=True,
        )
    entries.sort(key=lambda e: (e.start, e.end))
    raw = {
        "chunk_seconds": args.chunk_seconds,
        "chunk_overlap_seconds": args.chunk_overlap_seconds,
        "duration": duration,
        "mode": mode,
        "chunks": raw_chunks,
    }
    return entries, chunk_results, raw


def main() -> None:
    parser = argparse.ArgumentParser(description="Experimental Qwen3-ASR Japanese SRT transcription.")
    parser.add_argument("audio", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--forced-aligner", type=Path, default=DEFAULT_ALIGNER)
    parser.add_argument("--language", default="Japanese")
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--dtype", choices=("bfloat16", "float16", "float32"), default="bfloat16")
    parser.add_argument("--batch-size", type=int, default=24)
    parser.add_argument("--max-new-tokens", type=int, default=256)
    parser.add_argument("--chunk-seconds", type=float, default=30.0)
    parser.add_argument("--chunk-overlap-seconds", type=float, default=3.0)
    # VAD chunking: cut clips on silence so each clip's first token sits where
    # speech starts (removes leading-anchor drift). Opt-in; default is fixed tiling.
    parser.add_argument("--vad-chunks", dest="vad_chunks", action="store_true")
    parser.set_defaults(vad_chunks=False)
    parser.add_argument("--vad-threshold", type=float, default=0.1)
    parser.add_argument("--vad-window-seconds", type=float, default=8.0)
    parser.add_argument("--vad-window-overlap-seconds", type=float, default=4.0)
    parser.add_argument("--vad-min-silence-ms", type=int, default=500)
    parser.add_argument("--vad-speech-pad-ms", type=int, default=200)
    parser.add_argument("--vad-max-cluster-gap", type=float, default=2.0)
    parser.add_argument("--vad-pad-seconds", type=float, default=0.2)
    parser.add_argument("--vad-min-clip-seconds", type=float, default=0.3)
    parser.add_argument("--phrase-max-chars", type=int, default=26)
    parser.add_argument("--phrase-max-duration", type=float, default=8.0)
    parser.add_argument("--phrase-max-internal-gap", type=float, default=2.0)
    parser.add_argument("--phrase-max-char-seconds", type=float, default=0.5)
    parser.add_argument("--min-duration", type=float, default=0.8)
    parser.add_argument("--min-cue-seconds", type=float, default=0.2)
    parser.add_argument("--near-dup-max-gap", type=float, default=0.25)
    parser.add_argument("--near-dup-similarity", type=float, default=0.90)
    parser.add_argument("--near-dup-squeeze-seconds", type=float, default=0.5)
    parser.add_argument("--main-min-chars", type=int, default=1)
    parser.add_argument("--main-max-compression-ratio", type=float, default=25.0)
    parser.add_argument("--main-duplicate-window-seconds", type=float, default=8.0)
    parser.add_argument("--hallucination-min-repeats", type=int, default=3)
    parser.add_argument("--hallucination-repeat-no-speech-prob", type=float, default=0.75)
    parser.add_argument("--hallucination-repeat-avg-logprob", type=float, default=-1.0)
    parser.add_argument("--hallucination-high-risk-max-repeats", type=int, default=2)
    # Whisper-style hallucination/near-duplicate filtering is opt-in: Qwen rarely
    # fabricates content, so the default keeps the transcript faithful.
    parser.add_argument("--filter-hallucinations", dest="filter_hallucinations", action="store_true")
    parser.set_defaults(filter_hallucinations=False)
    parser.add_argument("--meta-output", type=Path)
    parser.add_argument(
        "--raw-output",
        type=Path,
        help="Dump per-chunk ASR text + aligner items to JSON for offline --from-raw replay.",
    )
    parser.add_argument(
        "--from-raw",
        type=Path,
        help="Rebuild the SRT from a --raw-output dump, skipping the model (fast post-processing tuning).",
    )
    args = parser.parse_args()

    if args.from_raw is None:
        if not args.model.exists():
            raise SystemExit(f"Missing Qwen ASR model: {args.model}")
        if not args.forced_aligner.exists():
            raise SystemExit(f"Missing Qwen forced aligner: {args.forced_aligner}")
        if args.chunk_overlap_seconds >= args.chunk_seconds:
            raise SystemExit("--chunk-overlap-seconds must be smaller than --chunk-seconds")

    started = time.time()
    if args.from_raw is not None:
        raw = json.loads(args.from_raw.read_text(encoding="utf-8"))
        entries = entries_from_raw(raw, args)
        chunk_results = []
        print(f"Replayed {len(raw['chunks'])} chunks from {args.from_raw}", flush=True)
    else:
        entries, chunk_results, raw = transcribe_qwen(args)
        if args.raw_output:
            args.raw_output.parent.mkdir(parents=True, exist_ok=True)
            args.raw_output.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
            print(f"Raw dump: {args.raw_output}", flush=True)
    if args.filter_hallucinations:
        entries, filtered = filter_main_local_entries(entries, args)
        if filtered:
            samples = ", ".join(entry.text[:24] for entry in filtered[:5])
            print(f"Filtered Qwen ASR hallucinations/noise: {len(filtered)} ({samples})", flush=True)
    entries = finalize_qwen_entries(entries, args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_entries(entries, args.output)

    meta_output = args.meta_output or args.output.with_suffix(args.output.suffix + ".meta.json")
    meta_output.write_text(
        json.dumps(
            {
                "audio": str(args.audio),
                "output": str(args.output),
                "model": str(args.model),
                "forced_aligner": str(args.forced_aligner),
                "chunk_seconds": args.chunk_seconds,
                "chunk_overlap_seconds": args.chunk_overlap_seconds,
                "batch_size": args.batch_size,
                "phrase_max_chars": args.phrase_max_chars,
                "phrase_max_duration": args.phrase_max_duration,
                "phrase_max_internal_gap": args.phrase_max_internal_gap,
                "phrase_max_char_seconds": args.phrase_max_char_seconds,
                "entries": len(entries),
                "elapsed_seconds": time.time() - started,
                "chunks": [asdict(item) for item in chunk_results],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"Wrote: {args.output}", flush=True)
    print(f"Meta: {meta_output}", flush=True)


if __name__ == "__main__":
    main()
