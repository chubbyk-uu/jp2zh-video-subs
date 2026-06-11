from __future__ import annotations

import argparse
import difflib
import json
import time
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path

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

# Qwen3-ASR `context` is injected as the recognition system prompt to bias decoding.
# No built-in context by default. Listing a homophone term by its correct spelling
# can fix that one word, but a standing prompt also pushes the model to emit listed
# words that were not spoken and can degrade unrelated lines, so it is not worth it
# for a single homophone. Pass per-title names/terms explicitly with --context.
DEFAULT_ASR_CONTEXT = ""

# Characters that end a sentence-level cue.
SENTENCE_END_CHARS = "。！？!?…．."
# Punctuation/whitespace that carries no timing and is ignored when matching the
# punctuated `result.text` against the forced-aligner character stream.
PUNCT_CHARS = set("。、，,！？!?…．・「」『』（）()【】〔〕〜~ー　 \t\r\n")
# Clause/sentence punctuation preferred as cut points when a cue must be split.
BREAK_PUNCT = set("。、，,！？!?…．")
# A cue whose raw (pre-floor) aligned span is at or below this is treated as a
# collapsed point — the aligner stamped all its characters on one instant rather
# than localising them. See sentences_from_alignment / drop_same_start_piles.
COLLAPSED_SPAN_SECONDS = 1e-3

# Punctuation / elongation / small kana stripped (everywhere, not just the ends)
# before testing whether a cue is a bare interjection mora.
INTERJECTION_DROP_CHARS = set("。、，．・！？!?…．.,「」『』（）()【】〔〕〜~ーｰっッぁぃぅぇぉ　 \t\r\n\"'")
# Bare filler morae. A cue that reduces to one of these *and* is walled by long
# silence on both sides carries no dialogue — it is almost always VAD catching a
# breath/moan or a music blip that Qwen labels with a default うん. The silence
# gate (drop_isolated_interjections) is what keeps genuine one-word replies, which
# sit next to other speech, safe. Elongation marks are removed before matching, so
# あー→あ, うーん→うん, ねー→ね all fold into the cores below.
ISOLATED_INTERJECTION_CORES = {
    "うん", "ううん", "ん", "んん",
    "ねえ", "ね",
    "あ", "ああ", "あん",
    "は", "はあ", "はん",
    "ふ", "ふう", "ふん",
    "え", "ええ",
    "お", "おお", "おう",
    "う", "うう",
    "ひ", "ひん",
    "へ", "ほ",
}


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


def _split_segment(
    tokens: list[tuple[str, float, float, bool]],
    max_chars: int,
    max_duration: float,
    min_pause: float = 0.12,
) -> list[list[tuple[str, float, float, bool]]]:
    """Split one timed token run so each piece fits max_chars/max_duration.

    Each token is one content character (with any trailing punctuation) plus its
    aligner start/end and an is-break flag (ends in clause punctuation). A piece is
    grown greedily until the budget is hit, then cut at, in priority: the last
    clause-punctuation token, else the largest pause >= min_pause, else the budget
    edge. This turns punctuation-free run-ons (Qwen sometimes emits no punctuation
    for long continuous speech) into several correctly-timed cues instead of one
    cue clamped to max_duration that hides its own tail.
    """
    pieces: list[list[tuple[str, float, float, bool]]] = []
    i, n = 0, len(tokens)
    while i < n:
        j = i + 1
        while j < n and (j - i) < max_chars and (tokens[j - 1][2] - tokens[i][1]) <= max_duration:
            j += 1
        if j >= n:
            pieces.append(tokens[i:n])
            break
        cut = None
        for k in range(j, i, -1):  # last clause-punctuation token in the window
            if tokens[k - 1][3]:
                cut = k
                break
        if cut is None:  # largest pause within the window
            best_gap = min_pause
            for k in range(i + 1, j + 1):
                gap = tokens[k][1] - tokens[k - 1][2]
                if gap >= best_gap:
                    best_gap = gap
                    cut = k
        if cut is None:  # no punctuation, no pause: cut at the budget edge
            cut = j
        pieces.append(tokens[i:cut])
        i = cut
    return pieces


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
    assign start/end. A 30s ASR window can merge utterances that are seconds apart
    into one sentence; the aligner then stretches that sentence across the pause, so
    a segment is first broken wherever consecutive characters are separated by more
    than max_internal_gap. Each segment is then split (see _split_segment) so no cue
    exceeds max_chars/max_duration even when Qwen emitted no punctuation.
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
        # One token per content character: (display, start, end, ends_in_break_punct).
        # Punctuation has no aligner time, so it rides on the preceding character.
        tokens: list[tuple[str, float, float, bool]] = []
        ci = 0
        for ch in unit:
            if ch in PUNCT_CHARS:
                if tokens:
                    disp, s, e, br = tokens[-1]
                    tokens[-1] = (disp + ch, s, e, br or ch in BREAK_PUNCT)
                continue
            if ci >= len(span):
                if tokens:
                    disp, s, e, br = tokens[-1]
                    tokens[-1] = (disp + ch, s, e, br)
                continue
            tokens.append((ch, span[ci][1], span[ci][2], False))
            ci += 1
        if not tokens:
            continue
        # Break on large internal time gaps (pauses between merged utterances).
        segments: list[list[tuple[str, float, float, bool]]] = [[tokens[0]]]
        for tok in tokens[1:]:
            if tok[1] - segments[-1][-1][2] > max_internal_gap:
                segments.append([tok])
            else:
                segments[-1].append(tok)
        for segment in segments:
            for piece in _split_segment(segment, max_chars, max_duration):
                start = offset + piece[0][1]
                end = offset + piece[-1][2]
                # A zero-width raw span means the aligner could not localise this
                # piece and collapsed all its characters onto one instant (typically a
                # short trailing word snapped to the next utterance's onset). Flag it
                # so a same-start pile-up keeps the genuinely-timed cue, not this point.
                collapsed = (end - start) <= COLLAPSED_SPAN_SECONDS
                end = max(end, start + min_duration)
                end = min(end, start + max_duration)
                display = "".join(t[0] for t in piece).strip()
                if display:
                    entries.append(SubtitleEntry(start, end, display, collapsed=collapsed))
    return entries


def drop_same_start_piles(entries: list[SubtitleEntry], tol: float = 0.05) -> list[SubtitleEntry]:
    """Drop cues piled on a single start time, keeping the first.

    In near-silent/moaning regions the forced aligner collapses many characters
    onto one timestamp, producing several cues with the same start that the shared
    overlap resolver leaves alone (it skips equal starts to avoid zero-duration
    cues). Their timing is meaningless, so rather than fan them into a flashing
    staircase we collapse each same-start pile to a single cue.

    Which member to keep depends on *why* they share a start. Two cases:
      - Moaning staircase: every member is a collapsed point (zero raw span). Their
        order is arbitrary, so we keep the first.
      - Snapped trailing word: a short word the aligner could not localise (e.g. a
        trailing 「です。」) is stamped on the *next* utterance's onset, so a collapsed
        point lands on the same start as a genuinely-timed full sentence. Keeping the
        first would drop the real line, so a real-span cue always wins over a
        collapsed point.
    Genuinely distinct cues have different start times and are untouched.
    """
    ordered = sorted(entries, key=lambda e: (e.start, e.end))
    result: list[SubtitleEntry] = []
    for entry in ordered:
        if result and entry.start - result[-1].start <= tol:
            # Replace the kept cue only when it is a collapsed point and the new one
            # is genuinely timed; otherwise keep the first (both real, or both
            # collapsed, or kept-real vs new-collapsed).
            if result[-1].collapsed and not entry.collapsed:
                result[-1] = entry
            continue
        result.append(entry)
    return result


def _interjection_core(text: str) -> str:
    """Reduce a cue's text to its bare mora for interjection matching.

    Drops punctuation, elongation marks and small kana everywhere (not just the
    ends) so that あー, あっ, 「あ…」 all collapse to あ.
    """
    s = unicodedata.normalize("NFKC", text)
    return "".join(ch for ch in s if ch not in INTERJECTION_DROP_CHARS)


def drop_isolated_interjections(
    entries: list[SubtitleEntry],
    min_silence: float,
    run_min: int = 3,
    run_gap: float = 5.0,
) -> tuple[list[SubtitleEntry], list[SubtitleEntry]]:
    """Drop filler morae (うん/ん/ねえ/あ …) that carry no dialogue.

    Two complementary cases, both keyed on a cue reducing to a single interjection
    mora (see ISOLATED_INTERJECTION_CORES):

      - Isolated blip: one filler walled by ``min_silence`` seconds of silence on
        both sides — a stray VAD breath/moan in an otherwise quiet stretch.
      - Interjection chain: a run of ``run_min``+ consecutive fillers whose adjacent
        gaps stay within ``run_gap``. Real dialogue never strings 3+ bare うん in a
        row, so this is the signature of VAD slicing a music bed into blips that Qwen
        labels with a default うん. A chain is dropped even when it abuts real speech
        (its bracketing silence may be short), because the chain itself is the tell.

    The silence gate keeps genuine one-word replies — which sit next to other speech
    and never chain — safe. A missing neighbour (list edge) counts as infinite
    silence. ``min_silence``<=0 disables the isolated rule; ``run_min``<=0 the chain.
    """
    if not entries or (min_silence <= 0 and run_min <= 0):
        return entries, []
    ordered = sorted(entries, key=lambda e: (e.start, e.end))
    n = len(ordered)
    is_filler = [_interjection_core(e.text) in ISOLATED_INTERJECTION_CORES for e in ordered]
    drop = [False] * n
    i = 0
    while i < n:
        if not is_filler[i]:
            i += 1
            continue
        # Extend a chain of consecutive fillers separated by <= run_gap.
        j = i
        while j + 1 < n and is_filler[j + 1] and (ordered[j + 1].start - ordered[j].end) <= run_gap:
            j += 1
        lead = ordered[i].start - ordered[i - 1].end if i > 0 else float("inf")
        trail = ordered[j + 1].start - ordered[j].end if j + 1 < n else float("inf")
        bracketed = min_silence > 0 and lead >= min_silence and trail >= min_silence
        chained = run_min > 0 and (j - i + 1) >= run_min
        if bracketed or chained:
            for k in range(i, j + 1):
                drop[k] = True
        i = j + 1
    kept = [e for e, d in zip(ordered, drop) if not d]
    dropped = [e for e, d in zip(ordered, drop) if d]
    return kept, dropped


def finalize_qwen_entries(entries: list[SubtitleEntry], args: argparse.Namespace) -> list[SubtitleEntry]:
    """Minimal time/format hygiene for Qwen output.

    In current project tests Qwen has been less prone to Whisper-style
    looping/hallucination, so those filters are opt-in via --filter-hallucinations.
    This keeps the transcript faithful: only overlap trimming, a sub-second
    flash-cue floor, and de-overlap of collapsed-timestamp cues.
    """
    entries = drop_same_start_piles(entries)
    entries = resolve_overlaps(entries)
    entries, dropped = drop_isolated_interjections(
        entries,
        args.isolated_interjection_silence,
        args.isolated_interjection_run,
        args.isolated_interjection_run_gap,
    )
    if dropped:
        samples = "、".join(e.text.strip() for e in dropped[:6])
        print(f"Dropped isolated interjections: {len(dropped)} ({samples})", flush=True)
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


def merge_clusters_into_groups(clusters: list[Interval], merge_gap: float, target_seconds: float) -> list[Interval]:
    """Optional second-level merge: pack consecutive speech clusters separated by
    <= merge_gap into a context group, capped at target_seconds. Off when
    merge_gap <= 0 (each cluster is its own group), so the default keeps the
    single-cluster behaviour that was measured to have low drift.
    """
    if merge_gap <= 0:
        return [Interval(c.start, c.end) for c in clusters]
    groups: list[Interval] = []
    cur: Interval | None = None
    for c in clusters:
        if cur is None:
            cur = Interval(c.start, c.end)
        elif (c.start - cur.end) <= merge_gap and (c.end - cur.start) <= target_seconds:
            cur.end = c.end
        else:
            groups.append(cur)
            cur = Interval(c.start, c.end)
    if cur is not None:
        groups.append(cur)
    return groups


def build_vad_jobs(audio, samplerate: int, duration: float, args: argparse.Namespace) -> list[ChunkJob]:
    """Speech-aligned clips: VAD is a speech anchor, not a sentence splitter.

    intervals -> speech clusters (vad_max_cluster_gap) -> optional context groups
    (vad_context_merge_gap, off by default). Each group is split into <=30s subs
    with overlap; cue ownership uses overlap-midpoint handoff so an internal sub's
    leading token (anchored to the clip edge) is owned by the previous sub where it
    sits mid-clip and is well timed. The audio fed to Qwen may be widened a little
    for recognition context (pre/post), but cue ownership stays tight; the total
    leading expansion (including the pad speech_clusters already added) is capped at
    vad_max_leading_silence so widening never re-introduces leading-silence drift.
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
    groups = merge_clusters_into_groups(clusters, args.vad_context_merge_gap, args.vad_target_context_seconds)
    if args.vad_context_merge_gap > 0:
        print(f"VAD context merge: clusters={len(clusters)} -> groups={len(groups)}", flush=True)

    max_clip = min(args.chunk_seconds, 30.0)
    overlap = args.chunk_overlap_seconds
    half = overlap / 2.0
    # Cap the new pre-context so pad (already in cluster.start) + pre <= max leading silence.
    effective_pre = min(args.vad_pre_context_seconds, max(0.0, args.vad_max_leading_silence - args.vad_pad_seconds))

    jobs: list[ChunkJob] = []
    for group in groups:
        if group.end - group.start < args.vad_min_clip_seconds:
            continue
        subs = split_clip_with_overlap(group, max_clip, overlap)
        last = len(subs) - 1
        for i, sub in enumerate(subs):
            keep_lo = group.start if i == 0 else sub.start + half
            keep_hi = group.end if i == last else sub.end - half
            audio_start = max(0.0, sub.start - effective_pre)
            audio_end = min(duration, sub.end + args.vad_post_context_seconds)
            jobs.append(ChunkJob(audio_start, audio_end, keep_lo, keep_hi))
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
    context = raw.get("context", "")
    entries: list[SubtitleEntry] = []
    for ch in raw["chunks"]:
        items = [_RawItem(it["text"], it["start"], it["end"]) for it in ch["items"]]
        text = "" if is_context_echo(ch["text"], context) else ch["text"]
        if "keep_lo" in ch:
            keep_lo = ch["keep_lo"]
            keep_hi = ch["keep_hi"] if ch.get("keep_hi") is not None else float("inf")
        else:
            # Fallback for pre-VAD dumps that only recorded fixed-tiling chunks.
            keep_lo = ch["start"]
            keep_hi = float("inf") if ch["end"] >= duration - 1e-3 else ch["start"] + step
        entries.extend(
            chunk_entries(
                text, items, start=ch["start"],
                keep_lo=keep_lo, keep_hi=keep_hi, args=args,
            )
        )
    entries.sort(key=lambda e: (e.start, e.end))
    return entries


def is_context_echo(text: str, context: str) -> bool:
    """True if `text` is the ASR regurgitating its biasing context.

    Qwen3-ASR injects the context as a system prompt; on near-silent/indistinct
    clips it falls back to emitting the context text itself. Such echoes are a long
    contiguous slice of the context, so we flag a clip whose text is mostly a
    substring of the context. Genuine dialogue that merely reuses a context hotword
    (e.g. a real line "間接キスになるや") shares only that short word and is kept.
    """
    if not context or not text:
        return False
    t = text.strip().strip("。．.！!？?、,…　 ")
    if len(t) < 6:
        return False
    match = difflib.SequenceMatcher(None, t, context).find_longest_match(0, len(t), 0, len(context))
    return match.size >= 6 and match.size >= 0.7 * len(t)


def asr_context(args: argparse.Namespace) -> str:
    """Effective Qwen3-ASR context: the built-in hotword list plus any --context the
    caller appends (e.g. per-title character names). --no-default-context drops the
    built-in list."""
    parts: list[str] = []
    if not getattr(args, "no_default_context", False) and DEFAULT_ASR_CONTEXT.strip():
        parts.append(DEFAULT_ASR_CONTEXT)
    extra = getattr(args, "context", "") or ""
    if extra.strip():
        parts.append(extra.strip())
    return " ".join(parts)


def transcribe_qwen(args: argparse.Namespace) -> tuple[list[SubtitleEntry], list[ChunkResult], dict]:
    # Imported here so the pure helpers (filters, chunking) stay importable in
    # environments without the GPU stack, e.g. the pytest suite.
    import torch
    from qwen_asr import Qwen3ASRModel

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
    context = asr_context(args)
    banner = (
        f"Qwen ASR: audio={duration / 60.0:.1f}min mode={mode} chunks={len(jobs)} "
        f"batch={args.batch_size} chunk_seconds={args.chunk_seconds} overlap={args.chunk_overlap_seconds}"
    )
    if mode == "vad":
        banner += (
            f" vad_pad={args.vad_pad_seconds} pre_context={args.vad_pre_context_seconds} "
            f"post_context={args.vad_post_context_seconds} max_leading={args.vad_max_leading_silence}"
        )
    print(banner, flush=True)
    if context:
        print(f"ASR context: {context}", flush=True)

    for group_start in range(0, len(jobs), args.batch_size):
        group = jobs[group_start : group_start + args.batch_size]
        clips = [(audio[int(j.start * samplerate) : int(j.end * samplerate)], samplerate) for j in group]
        t0 = time.time()
        results = model.transcribe(
            audio=clips,
            context=context,
            language=[args.language] * len(clips),
            return_time_stamps=True,
        )
        elapsed = time.time() - t0
        for job, result in zip(group, results):
            text = str(result.text or "").strip()
            items = getattr(result.time_stamps, "items", None) if result.time_stamps is not None else None
            # Drop context echoes (the model regurgitating the biasing prompt on
            # near-silent clips) before they become spurious cues.
            display_text = "" if is_context_echo(text, context) else text
            kept = chunk_entries(
                display_text, items, start=job.start,
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
        "context": context,
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
    # Qwen3-ASR biasing context (system prompt). --context appends to the built-in
    # hotword list; --no-default-context drops the built-in list entirely.
    parser.add_argument("--context", default="", help="Extra ASR context/hotwords appended to the built-in list (e.g. character names).")
    parser.add_argument("--no-default-context", dest="no_default_context", action="store_true")
    parser.set_defaults(no_default_context=False)
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
    # Small audio context fed to Qwen (does not change cue ownership). Total leading
    # expansion incl. vad_pad_seconds is capped at --vad-max-leading-silence.
    parser.add_argument("--vad-pre-context-seconds", type=float, default=0.0)
    parser.add_argument("--vad-post-context-seconds", type=float, default=0.5)
    parser.add_argument("--vad-max-leading-silence", type=float, default=0.5)
    # Optional second-level merge of speech clusters into context groups. Off by
    # default (0.0): the first-level speech_clusters(vad_max_cluster_gap) merge stands.
    parser.add_argument("--vad-context-merge-gap", type=float, default=0.0)
    parser.add_argument("--vad-target-context-seconds", type=float, default=24.0)
    parser.add_argument("--phrase-max-chars", type=int, default=26)
    parser.add_argument("--phrase-max-duration", type=float, default=8.0)
    parser.add_argument("--phrase-max-internal-gap", type=float, default=2.0)
    parser.add_argument("--phrase-max-char-seconds", type=float, default=0.5)
    parser.add_argument("--min-duration", type=float, default=0.8)
    parser.add_argument("--min-cue-seconds", type=float, default=0.2)
    # Drop bare filler morae (うん/ん/ねえ/あ …) that carry no dialogue. Two rules
    # (drop_isolated_interjections): an isolated blip needs this much silence on both
    # sides (0 disables); a chain of --isolated-interjection-run+ consecutive fillers
    # within --isolated-interjection-run-gap is dropped outright (run<=0 disables).
    parser.add_argument("--isolated-interjection-silence", type=float, default=3.0)
    parser.add_argument("--isolated-interjection-run", type=int, default=3)
    parser.add_argument("--isolated-interjection-run-gap", type=float, default=5.0)
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
        if 0 < args.vad_context_merge_gap < args.vad_max_cluster_gap:
            raise SystemExit("--vad-context-merge-gap must be >= --vad-max-cluster-gap (or 0 to disable)")

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
                "vad_chunks": args.vad_chunks,
                "vad_threshold": args.vad_threshold,
                "vad_window_seconds": args.vad_window_seconds,
                "vad_window_overlap_seconds": args.vad_window_overlap_seconds,
                "vad_max_cluster_gap": args.vad_max_cluster_gap,
                "vad_pre_context_seconds": args.vad_pre_context_seconds,
                "vad_post_context_seconds": args.vad_post_context_seconds,
                "vad_max_leading_silence": args.vad_max_leading_silence,
                "vad_context_merge_gap": args.vad_context_merge_gap,
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
