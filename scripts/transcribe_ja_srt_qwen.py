from __future__ import annotations

import argparse
import difflib
import json
import math
import time
import unicodedata
from dataclasses import asdict, dataclass, field
from pathlib import Path

from alignment_recovery import (
    assess_alignment_quality,
    items_to_words,
    redistribute_collapsed_words,
    words_to_items,
)
from anime_text_clean import anime_clean_text
from cli_config import add_dataclass_arguments
from pipeline_configs import QwenAsrConfig
from srt_utils import Interval
from transcribe_ja_srt import (
    SubtitleEntry,
    drop_adjacent_near_duplicates,
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
# anime-whisper punctuates soft pauses with … liberally, so treating every … as a
# hard sentence end shatters one spoken line into many tiny cues. In ellipsis-soft
# mode (anime backend) … is NOT a hard ender — only 。！？ etc. are — and … instead
# becomes a soft split point used only when a unit is over-long. See split_into_units
# / sentences_from_alignment(ellipsis_hard_split=...). BREAK_PUNCT still keeps … as a
# soft cut point inside _split_segment, which only fires past the length budget.
SENTENCE_END_CHARS_NO_ELLIPSIS = SENTENCE_END_CHARS.replace("…", "")
# Punctuation/whitespace that carries no timing and is ignored when matching the
# punctuated `result.text` against the forced-aligner character stream.
PUNCT_CHARS = set("。、，,！？!?…．・「」『』（）()【】〔〕〜~ー　 \t\r\n")
# Clause/sentence punctuation preferred as cut points when a cue must be split.
BREAK_PUNCT = set("。、，,！？!?…．")
# A cue whose raw (pre-floor) aligned span is at or below this is treated as a
# collapsed point — the aligner stamped all its characters on one instant rather
# than localising them. See sentences_from_alignment / drop_same_start_piles.
COLLAPSED_SPAN_SECONDS = 1e-3
# anime ellipsis-soft splitting: a … followed by a real pause of at least this many
# seconds is a sentence boundary; a … with a smaller gap is trailing intonation (やだ…)
# and stays joined. Only consulted when ellipsis_hard_split is False (anime backend).
ELLIPSIS_SPLIT_GAP_SECONDS = 0.4
# The aligner can push a short sentence ending several seconds after the preceding
# text ("何欲しいん" ... "だ。"). Keep only strongly fragmentary joins across this
# wider window; normal utterance pauses still split at phrase_max_internal_gap.
FRAGMENT_INTERNAL_GAP_MAX_SECONDS = 6.5

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
# Reply words (はい "yes") are genuine dialogue exactly when they answer
# something: in real recordings an answering はい starts within a couple of
# seconds of the line it replies to. ASR also labels quiet rhythmic
# breathing/kissing as metronomic はい runs (observed at 6-8s spacing, far from
# any real line, making up ~half the cues of a quiet title), which the plain
# chain rule misses. So a はい anchored to recent real speech
# (reply_anchor_lag) is kept unconditionally; an unanchored はい is treated as
# an ordinary filler, subject to the same silence/chain gates as うん.
REPLY_INTERJECTION_CORES = {"はい"}
ALL_FILLER_CORES = ISOLATED_INTERJECTION_CORES | REPLY_INTERJECTION_CORES

FRAGMENT_JOIN_SUFFIX_STARTS = (
    "ん", "だ", "です", "でし", "ます", "ませ", "ました", "ない", "な",
    "て", "た", "ちゃ", "じゃ", "の", "か", "から", "けど",
    "という", "って", "に", "よ", "ね",
)
FRAGMENT_JOIN_PREFIX_ENDS = (
    "の", "が", "を", "に", "へ", "と", "で", "から", "まで", "より", "も",
)
FRAGMENT_JOIN_UNFINISHED_ENDS = (
    "し", "っ", "い", "ん", "く", "ぐ", "す", "つ", "ぬ", "ぶ", "む", "る",
)


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


_QWEN_ALIGNER_LANGUAGE_ALIASES = {
    "ja": "Japanese",
    "jp": "Japanese",
    "jpn": "Japanese",
    "japanese": "Japanese",
    "en": "English",
    "eng": "English",
    "english": "English",
    "zh": "Chinese",
    "zho": "Chinese",
    "chi": "Chinese",
    "chinese": "Chinese",
}


def qwen_aligner_language(language: str | None) -> str:
    """Normalize CLI language codes to qwen-asr ForcedAligner language names."""
    if not language or not str(language).strip():
        return "Japanese"
    key = str(language).strip().lower()
    return _QWEN_ALIGNER_LANGUAGE_ALIASES.get(key, str(language).strip())


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


def split_into_units(text: str, max_chars: int, ellipsis_hard: bool = True) -> list[str]:
    """Split the punctuated transcript into sentence-level cue units.

    Primary split on sentence-ending punctuation; overly long units are split
    further on the soft separator \u3001 so cues stay readable.
    """
    enders = SENTENCE_END_CHARS if ellipsis_hard else SENTENCE_END_CHARS_NO_ELLIPSIS
    # Soft separators used only to break an over-long unit. In ellipsis-soft mode \u2026
    # joins \u3001 as a soft break so a long anime run still splits at a natural pause.
    soft_seps = "\u3001" if ellipsis_hard else "\u3001\u2026"
    units: list[str] = []
    buf = ""
    for ch in text:
        buf += ch
        if ch in enders:
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
            if ch in soft_seps and len(content_chars(sub)) >= max_chars * 0.6:
                result.append(sub)
                sub = ""
        if sub:
            result.append(sub)
    return result


def _fragment_text(text: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKC", text).strip() if ch not in PUNCT_CHARS)


def should_keep_across_internal_gap(left_text: str, right_text: str, gap: float, base_gap: float) -> bool:
    """True when a large aligner gap most likely split one grammatical fragment.

    This is deliberately narrower than raising phrase_max_internal_gap globally:
    ordinary long pauses still split, but short sentence tails / particles that
    the forced aligner stamped late stay attached to their host phrase.
    """
    if gap <= base_gap:
        return True
    if gap > FRAGMENT_INTERNAL_GAP_MAX_SECONDS:
        return False
    left = _fragment_text(left_text)
    right = _fragment_text(right_text)
    if not left or not right:
        return False
    if left in ALL_FILLER_CORES or right in ALL_FILLER_CORES:
        return False

    left_short = len(left) <= 4
    right_short = len(right) <= 5
    right_is_suffix = right_short and right.startswith(FRAGMENT_JOIN_SUFFIX_STARTS)
    left_is_prefix = left_short and left.endswith(FRAGMENT_JOIN_PREFIX_ENDS)
    left_is_unfinished = not left_text.rstrip().endswith(tuple(SENTENCE_END_CHARS)) and (
        left.endswith(FRAGMENT_JOIN_UNFINISHED_ENDS) or left_is_prefix
    )

    if right_is_suffix and (left_is_unfinished or right.startswith(("ん", "ませ"))):
        return True
    if left_is_prefix and not right_text.lstrip().startswith(tuple(SENTENCE_END_CHARS)):
        return True
    # Half-words split around a conjugation boundary: 使っ + て, 働い + てる.
    if len(left) <= 8 and right.startswith(("て", "た", "ちゃ", "という")) and not left_text.rstrip().endswith(tuple(SENTENCE_END_CHARS)):
        return True
    return False


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


# Punctuation accepted as a filler-run boundary (rides on the preceding token's
# display). A repetition run only collapses when both edges sit on such punctuation
# or the segment boundary, so word-initial repetition inside real words (ああいう)
# is never touched.
RUN_BOUNDARY_PUNCT = set("。、，．,.！？!?…・")
# Longest-first so うんうん matches core うん rather than two ん with stray う.
# Includes reply words so はい、はい。 collapses to a single はい before the
# anchored-reply gate judges it.
FILLER_COLLAPSE_CORES = sorted(ALL_FILLER_CORES, key=len, reverse=True)


def _token_core_char(display: str) -> str:
    """The matching character a token contributes to a filler core, or "" when the
    token is transparent (small kana / elongation that rides along a filler)."""
    base = unicodedata.normalize("NFKC", display[:1])
    return "" if base in INTERJECTION_DROP_CHARS else base


def collapse_filler_repetitions(
    tokens: list[tuple[str, float, float, bool]],
) -> list[tuple[str, float, float, bool]]:
    """Collapse a consecutive same-core filler run (うん、うん、うん…) to one instance.

    Qwen sometimes transcribes a stretch of low-value filler as one cue that
    repeats a filler mora, either alone (うんうんうん。) or padded around real
    speech (うん、うん、うん、一人。). The per-cue interjection filter only matches a
    cue that *is* a single filler, so these slip through. Collapsing at the token
    level keeps the aligner's per-character times, so the surviving cue's timing is
    exact rather than re-derived.

    The kept instance is the one adjacent to the surrounding real content — last
    instance of a leading run, first of a trailing run — so the cue keeps a natural
    lead-in (うん、一人。) and its start sits a beat early rather than late. A run
    that spans the whole segment collapses to its first instance, which the
    silence/chain gates in drop_isolated_interjections then judge as usual.
    """
    n = len(tokens)
    if n < 2:
        return tokens
    cores = [_token_core_char(t[0]) for t in tokens]

    def has_trailing_punct(idx: int) -> bool:
        return any(ch in RUN_BOUNDARY_PUNCT for ch in tokens[idx][0][1:])

    def match_core(core: str, start: int) -> int:
        """Consume tokens from `start` matching `core` (transparent tokens ride
        along); return the index past the match, or -1."""
        pos = 0
        j = start
        while j < n and pos < len(core):
            if cores[j] == "":
                j += 1
                continue
            if cores[j] != core[pos]:
                return -1
            pos += 1
            j += 1
        return j if pos == len(core) else -1

    keep = [True] * n
    i = 0
    while i < n:
        if cores[i] == "":
            i += 1
            continue
        run_core = None
        instances: list[tuple[int, int]] = []
        for core in FILLER_COLLAPSE_CORES:
            first_end = match_core(core, i)
            if first_end < 0:
                continue
            bounds = [(i, first_end)]
            while (next_end := match_core(core, bounds[-1][1])) >= 0:
                bounds.append((bounds[-1][1], next_end))
            if len(bounds) >= 2:
                # ああ/ええ/おお/んん … are lexical interjections in their own
                # right, not padding; a run that *is* one known core stays whole
                # (the whole-cue silence gate already knows how to judge it).
                if core * len(bounds) in ISOLATED_INTERJECTION_CORES:
                    continue
                run_core, instances = core, bounds
                break
        if run_core is None:
            i += 1
            continue
        run_end = instances[-1][1]
        while run_end < n and cores[run_end] == "":  # absorb trailing small kana
            run_end += 1
        left_ok = i == 0 or has_trailing_punct(i - 1)
        right_ok = run_end >= n or has_trailing_punct(run_end - 1)
        if not (left_ok and right_ok):
            i = run_end
            continue
        # Trailing run (real content before it) keeps its first instance; any run
        # followed by content keeps its last. Whole-segment runs keep the first.
        kept_lo, kept_hi = instances[-1] if run_end < n else instances[0]
        for k in range(i, run_end):
            if not (kept_lo <= k < kept_hi):
                keep[k] = False
        i = run_end
    if all(keep):
        return tokens
    return [tok for tok, kept in zip(tokens, keep) if kept]


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
    collapse_fillers: bool = True,
    ellipsis_hard_split: bool = True,
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
    units = split_into_units(text, max_chars, ellipsis_hard=ellipsis_hard_split)
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
        for idx, tok in enumerate(tokens[1:], start=1):
            prev = segments[-1][-1]
            gap = tok[1] - prev[2]
            # anime: a … sitting on a real pause is a sentence boundary; the same … with
            # no gap is just trailing intonation and stays joined. Fires below
            # max_internal_gap so tighter pauses still break, but only right after a ….
            if not ellipsis_hard_split and "…" in prev[0] and gap > ELLIPSIS_SPLIT_GAP_SECONDS:
                segments.append([tok])
                continue
            left_text = "".join(t[0] for t in segments[-1])
            right_text = "".join(t[0] for t in tokens[idx : min(len(tokens), idx + 8)])
            if gap > max_internal_gap and not should_keep_across_internal_gap(left_text, right_text, gap, max_internal_gap):
                segments.append([tok])
            else:
                segments[-1].append(tok)
        for segment in segments:
            if collapse_fillers:
                segment = collapse_filler_repetitions(segment)
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

    In near-silent low-value filler regions the forced aligner collapses many characters
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
    reply_anchor_lag: float = 3.0,
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

    Reply words (REPLY_INTERJECTION_CORES, e.g. はい) get one extra gate first: one
    anchored to real speech (a real-word cue ended within ``reply_anchor_lag``
    seconds before it) is a genuine answer and is exempt from both rules; an
    unanchored one is an ordinary filler. ``reply_anchor_lag``<=0 disables
    anchoring (every はい is then a plain filler).
    """
    if not entries or (min_silence <= 0 and run_min <= 0):
        return entries, []
    ordered = sorted(entries, key=lambda e: (e.start, e.end))
    n = len(ordered)
    cores = [_interjection_core(e.text) for e in ordered]
    # A reply word (はい) anchored to recent real speech is a genuine answer and
    # is exempt from every drop rule; an unanchored one is an ordinary filler.
    # Only real-word cues anchor — a はい cannot anchor the next はい, so a
    # metronomic run decays after the one genuinely answering the line.
    anchored = [False] * n
    last_word_end: float | None = None
    for k in range(n):
        if cores[k] in REPLY_INTERJECTION_CORES:
            if (
                reply_anchor_lag > 0
                and last_word_end is not None
                and ordered[k].start - last_word_end <= reply_anchor_lag
            ):
                anchored[k] = True
        elif cores[k] not in ALL_FILLER_CORES:
            last_word_end = ordered[k].end
    is_filler = [c in ALL_FILLER_CORES and not anchored[k] for k, c in enumerate(cores)]
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


def collapse_repeated_phrases(text: str, threshold: int = 4, keep: int = 2, max_len: int = 20) -> str:
    """Collapse a runaway consecutive repetition of any 1..max_len-char unit to `keep`
    copies. Targets the Qwen failure mode where a climax/moan line loops (行く×7, だめ×4,
    ああ×6) into an untranslatable flood.

    This is the narrow, text-quality half of WJ's AssemblyTextCleaner (phrase-repetition +
    char-flood), NOT ported verbatim: WJ's Stage-1a regex `([\\p{L}\\p{N}]{2,8})\\1{2,}` is
    greedy and on 行く×7 only reaches 行く×5 (verified with WJ's own `regex` lib), and its
    recursive stage only fires at ≥10. This minimal-unit scanner instead finds the true
    repeating unit and keeps exactly `keep`, so 行く×7 → 行く行く while genuine 2-3× emphasis
    (threshold 4) and normal text are untouched. Single-char floods fall out of the len-1 case.
    """
    if not text or threshold < 2:
        return text
    out: list[str] = []
    pos, n = 0, len(text)
    while pos < n:
        best_len = best_count = 0
        for plen in range(1, min(max_len, n - pos) + 1):
            unit = text[pos:pos + plen]
            count, cp = 1, pos + plen
            while cp + plen <= n and text[cp:cp + plen] == unit:
                count += 1
                cp += plen
            if count >= threshold and count > best_count:
                best_len, best_count = plen, count
        if best_count >= threshold:
            out.append(text[pos:pos + best_len] * min(keep, best_count))
            pos += best_len * best_count
        else:
            out.append(text[pos])
            pos += 1
    return "".join(out)


def finalize_qwen_entries(entries: list[SubtitleEntry], args: argparse.Namespace) -> list[SubtitleEntry]:
    """Minimal time/format hygiene for Qwen output.

    In current project tests Qwen has been less prone to Whisper-style
    looping/hallucination, so those filters are opt-in via --filter-hallucinations
    (which also enables the near-duplicate squeeze filter below).
    This keeps the transcript faithful: only overlap trimming, a sub-second
    flash-cue floor, and de-overlap of collapsed-timestamp cues.
    """
    if getattr(args, "collapse_repeats", True):
        thr = int(getattr(args, "collapse_repeats_threshold", 4))
        keep = int(getattr(args, "collapse_repeats_keep", 2))
        collapsed_n = 0
        for e in entries:
            new_text = collapse_repeated_phrases(e.text, thr, keep)
            if new_text != e.text:
                e.text = new_text
                collapsed_n += 1
        if collapsed_n:
            print(f"Collapsed runaway repetition in {collapsed_n} cues", flush=True)
    entries = drop_same_start_piles(entries)
    entries = resolve_overlaps(entries)
    if args.filter_hallucinations and args.near_dup_similarity > 0:
        before = len(entries)
        entries = drop_adjacent_near_duplicates(
            entries,
            args.near_dup_max_gap,
            args.near_dup_similarity,
            args.near_dup_squeeze_seconds,
        )
        if before != len(entries):
            print(f"Dropped {before - len(entries)} adjacent near-duplicate cues", flush=True)
    entries, dropped = drop_isolated_interjections(
        entries,
        args.isolated_interjection_silence,
        args.isolated_interjection_run,
        args.isolated_interjection_run_gap,
        args.interjection_reply_anchor_lag,
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
    # Clip-relative speech regions inside [start, end] (offset by -start), used by
    # collapse recovery for VAD-guided redistribution. Empty on the fixed-tiling path.
    speech: list[Interval] = field(default_factory=list)


def _clip_relative_speech(intervals: list[Interval], job_start: float, job_end: float) -> list[Interval]:
    """Intersect absolute speech intervals with [job_start, job_end] and shift to
    clip-relative coordinates (subtract job_start)."""
    regions: list[Interval] = []
    for iv in intervals:
        s = max(iv.start, job_start)
        e = min(iv.end, job_end)
        if e > s:
            regions.append(Interval(s - job_start, e - job_start))
    return regions


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
            job = ChunkJob(audio_start, audio_end, keep_lo, keep_hi)
            job.speech = _clip_relative_speech(intervals, audio_start, audio_end)
            jobs.append(job)
    return jobs


def build_whisperseg_jobs(audio, samplerate: int, duration: float, args: argparse.Namespace) -> list[ChunkJob]:
    """Short, speech-pure frames from WhisperSeg (Stage 3). Each grouped frame becomes
    one ChunkJob spanning its speech; the frame's speech segments are stored
    clip-relative for the collapse sentinel's VAD-guided recovery.

    Frames do not overlap, so cue ownership is simply the frame's own [start, end).
    """
    from whisperseg_vad import WhisperSegVAD, resolve_model_path

    if samplerate != 16000:
        raise SystemExit("--vad-backend whisperseg requires 16 kHz audio")
    vad = WhisperSegVAD(
        model_path=resolve_model_path(str(args.whisperseg_model)),
        threshold=args.whisperseg_threshold,
        max_speech_duration_s=args.whisperseg_max_speech,
        max_group_duration_s=args.whisperseg_max_group,
        chunk_threshold_s=args.whisperseg_chunk_threshold,
    )
    if getattr(args, "scene_backend", "none") == "semantic":
        # Cut acoustic-texture scenes first, then run WhisperSeg per scene so frames
        # never cross a scene boundary (frame times shifted back to absolute).
        from semantic_scene import detect_scenes

        scenes = detect_scenes(
            audio, samplerate,
            min_dur=args.scene_min_seconds, max_dur=args.scene_max_seconds,
            clustering_threshold=args.scene_clustering_threshold,
        )
        print(f"semantic scenes: {len(scenes)} (min={args.scene_min_seconds}s max={args.scene_max_seconds}s)", flush=True)
        groups = []
        for ss, se in scenes:
            seg_audio = audio[int(ss * samplerate) : int(se * samplerate)]
            if len(seg_audio) < int(0.1 * samplerate):
                continue
            for g in vad.segment(seg_audio, samplerate):
                for s in g:
                    s.start += ss
                    s.end += ss
                groups.append(g)
    else:
        groups = vad.segment(audio, samplerate)
    vad.cleanup()

    jobs: list[ChunkJob] = []
    n = len(groups)
    for gi, g in enumerate(groups):
        frame_start = g[0].start
        frame_end = g[-1].end
        if frame_end - frame_start < args.whisperseg_min_frame_seconds:
            continue
        keep_hi = float("inf") if gi == n - 1 else frame_end
        job = ChunkJob(frame_start, frame_end, frame_start, keep_hi)
        job.speech = [Interval(s.start - frame_start, s.end - frame_start) for s in g]
        jobs.append(job)
    return jobs


def reframe_collapsed_jobs(audio, samplerate: int, collapsed_jobs: list[ChunkJob], args: argparse.Namespace) -> list[ChunkJob]:
    """Step-down retry: re-frame each collapsed qwen job with a tighter WhisperSeg
    max_group and return absolute-coord sub-jobs (WJ re-frames the scene; our jobs are
    frame-level, so this is the per-job analog). Each sub-job preserves the collapsed
    job's outer keep window at its edges so cue ownership stays contiguous.

    WJ ships `stepdown_fallback_group == main max_group` (6.0), which produces the same
    frames and re-decodes identically on our deterministic path (inert but faithful);
    the ablation tests tighter fallback values.
    """
    from whisperseg_vad import WhisperSegVAD, resolve_model_path

    if samplerate != 16000:
        return []
    fallback = float(getattr(args, "stepdown_fallback_group", args.whisperseg_max_group))
    vad = WhisperSegVAD(
        model_path=resolve_model_path(str(args.whisperseg_model)),
        threshold=args.whisperseg_threshold,
        max_speech_duration_s=min(float(args.whisperseg_max_speech), fallback),
        max_group_duration_s=fallback,
        chunk_threshold_s=args.whisperseg_chunk_threshold,
    )
    min_frame = float(args.whisperseg_min_frame_seconds)
    sub_jobs: list[ChunkJob] = []
    for job in collapsed_jobs:
        clip = audio[int(job.start * samplerate) : int(job.end * samplerate)]
        if len(clip) < int(min_frame * samplerate):
            continue
        frames = [
            (g[0].start, g[-1].end, g)
            for g in vad.segment(clip, samplerate)
            if (g[-1].end - g[0].start) >= min_frame
        ]
        if not frames:
            continue
        last = len(frames) - 1
        for k, (fs, fe, g) in enumerate(frames):
            a, e = job.start + fs, job.start + fe
            keep_lo = job.keep_lo if k == 0 else a
            keep_hi = job.keep_hi if k == last else e
            sub = ChunkJob(a, e, keep_lo, keep_hi)
            sub.speech = [Interval(s.start - fs, s.end - fs) for s in g]
            sub_jobs.append(sub)
    vad.cleanup()
    return sub_jobs


def build_qwen_jobs(audio, samplerate: int, duration: float, args: argparse.Namespace) -> tuple[list[ChunkJob], str]:
    """Build qwen clips without changing its default framing.

    Qwen's measured baseline stays on the current Silero/VAD path. WhisperSeg and
    semantic scenes are opt-in qwen experiments via --vad-backend whisperseg and
    --scene-backend semantic.
    """
    if args.vad_chunks:
        if getattr(args, "vad_backend", "current") == "whisperseg":
            return build_whisperseg_jobs(audio, samplerate, duration, args), "whisperseg"
        return build_vad_jobs(audio, samplerate, duration, args), "vad"
    return build_fixed_jobs(duration, args), "fixed"


def uncovered_gap_spans(entries: list[SubtitleEntry], duration: float, min_gap: float) -> list[Interval]:
    """Timeline spans not covered by any cue, at least min_gap seconds long.

    List edges count: a silent lead-in or tail longer than min_gap is also a span.
    Feeds the recapture pass, which gives these regions a second, more sensitive
    VAD+ASR look while the model is still loaded."""
    spans: list[Interval] = []
    prev_end = 0.0
    for entry in sorted(entries, key=lambda e: (e.start, e.end)):
        if entry.start - prev_end >= min_gap:
            spans.append(Interval(prev_end, entry.start))
        prev_end = max(prev_end, entry.end)
    if duration - prev_end >= min_gap:
        spans.append(Interval(prev_end, duration))
    return spans


def build_recapture_jobs(
    audio,
    samplerate: int,
    duration: float,
    spans: list[Interval],
    args: argparse.Namespace,
) -> list[ChunkJob]:
    """Second-look clips inside uncovered gaps, cut with a more sensitive VAD.

    The main pass misses quiet speech that sits under --vad-threshold; re-running
    VAD only inside the gaps at --recapture-vad-threshold finds it without making
    the whole-file VAD noisier. A span whose detected speech totals less than
    --recapture-min-speech is skipped (background blips are not worth a clip).
    Clip construction mirrors build_vad_jobs: cluster, split at 30s with
    overlap-midpoint cue ownership."""
    max_clip = min(args.chunk_seconds, 30.0)
    overlap = args.chunk_overlap_seconds
    half = overlap / 2.0
    jobs: list[ChunkJob] = []
    for span in spans:
        lo = int(span.start * samplerate)
        hi = int(span.end * samplerate)
        span_duration = span.end - span.start
        intervals = speech_intervals_from_sliding_audio(
            audio[lo:hi],
            span_duration,
            args.recapture_vad_threshold,
            args.vad_min_silence_ms,
            args.vad_speech_pad_ms,
            args.vad_window_seconds,
            args.vad_window_overlap_seconds,
        )
        if sum(item.end - item.start for item in intervals) < args.recapture_min_speech:
            continue
        clusters = speech_clusters(intervals, args.vad_max_cluster_gap, args.vad_pad_seconds, span_duration)
        for cluster in clusters:
            if cluster.end - cluster.start < args.vad_min_clip_seconds:
                continue
            group = Interval(span.start + cluster.start, span.start + cluster.end)
            subs = split_clip_with_overlap(group, max_clip, overlap)
            last = len(subs) - 1
            for i, sub in enumerate(subs):
                keep_lo = group.start if i == 0 else sub.start + half
                keep_hi = group.end if i == last else sub.end - half
                audio_end = min(duration, sub.end + args.vad_post_context_seconds)
                jobs.append(ChunkJob(sub.start, audio_end, keep_lo, keep_hi))
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
        collapse_fillers=getattr(args, "collapse_filler_repetition", True),
        ellipsis_hard_split=getattr(args, "text_backend", "qwen") != "anime",
    )
    return [e for e in sentence_entries if keep_lo <= (e.start + e.end) / 2.0 < keep_hi]


def _speech_regions_for_vad_only(clip_duration: float, speech_regions: list[Interval]) -> list[Interval]:
    """Clip-relative speech regions used as the timestamp source in vad_only mode."""
    regions: list[Interval] = []
    for iv in speech_regions:
        start = max(0.0, min(float(iv.start), clip_duration))
        end = max(0.0, min(float(iv.end), clip_duration))
        if end > start:
            regions.append(Interval(start, end))
    if not regions and clip_duration > 0:
        regions.append(Interval(0.0, clip_duration))
    return regions


def _map_speech_offset(regions: list[Interval], position: float) -> float:
    """Map a position in concatenated-speech seconds back to clip-relative time."""
    remaining = max(0.0, position)
    for iv in regions:
        span = iv.end - iv.start
        if remaining <= span:
            return iv.start + remaining
        remaining -= span
    return regions[-1].end if regions else 0.0


def _region_at_speech_offset(regions: list[Interval], position: float) -> Interval:
    """Return the speech region owning a concatenated-speech position."""
    remaining = max(0.0, position)
    for iv in regions:
        span = iv.end - iv.start
        if remaining <= span:
            return iv
        remaining -= span
    return regions[-1]


def vad_only_items_for_text(text: str, clip_duration: float, speech_regions: list[Interval]) -> list[_RawItem]:
    """Build WJ-style aligner-free pseudo items for anime-whisper text.

    WhisperJAV's anime-whisper preset uses vad_only: no forced aligner is loaded;
    frame/VAD boundaries are the timing source. This adapter gives our existing
    cue shaping one timed pseudo item per content character, distributed across
    the detected speech regions and leaving inter-region gaps as real pauses.
    """
    chars = content_chars(text)
    if not chars:
        return []
    regions = _speech_regions_for_vad_only(clip_duration, speech_regions)
    if not regions:
        return []
    total = sum(iv.end - iv.start for iv in regions)
    if total <= 0:
        return []
    items: list[_RawItem] = []
    n = len(chars)
    for i, ch in enumerate(chars):
        speech_start = total * i / n
        speech_end = total * (i + 1) / n
        region = _region_at_speech_offset(regions, speech_start)
        start = _map_speech_offset(regions, speech_start)
        end = min(_map_speech_offset(regions, speech_end), region.end)
        if end < start:
            end = start
        items.append(_RawItem(ch, start, end))
    return items


def _serialize_items(items) -> list[dict]:
    return [
        {"text": item_text(it), "start": item_start(it), "end": item_end(it)}
        for it in (items or [])
        if getattr(it, "start_time", None) is not None and getattr(it, "end_time", None) is not None
    ]


def entries_from_raw(raw: dict, args: argparse.Namespace) -> list[SubtitleEntry]:
    """Rebuild cues from a dumped raw chunk stream, skipping the model entirely."""
    duration = raw["duration"]
    step = raw["chunk_seconds"] - raw["chunk_overlap_seconds"]
    context = raw.get("context", "")
    entries: list[SubtitleEntry] = []
    # anime aligner_only: replay from the pre-recovery raw_items so a single expensive
    # generate/align pass can be replayed as either mode (aligner_fallback uses the
    # recovered items stored in "items").
    anime_only = (
        getattr(args, "text_backend", "qwen") == "anime"
        and getattr(args, "timestamp_mode", "aligner_fallback") == "aligner_only"
    )
    for ch in raw["chunks"]:
        if ch.get("superseded_by_stepdown"):
            continue  # step-down re-framed this collapsed chunk; its cues live in later "stepdown" chunks
        if "clean_text" in ch:
            # anime schema: text is already cleaned; no context echo to strip.
            text = ch["clean_text"]
            if getattr(args, "timestamp_mode", "aligner_fallback") == "vad_only":
                regions = [Interval(float(s), float(e)) for s, e in ch.get("speech_regions", [])]
                items = vad_only_items_for_text(text, ch["end"] - ch["start"], regions)
            else:
                src = ch["raw_items"] if (anime_only and "raw_items" in ch) else ch["items"]
                items = [_RawItem(it["text"], it["start"], it["end"]) for it in src]
        else:
            text = "" if is_context_echo(ch["text"], context) else ch["text"]
            raw_mode = getattr(args, "timestamp_mode", raw.get("timestamp_mode", "aligner_fallback"))
            if raw.get("text_backend", "qwen") == "qwen" and raw_mode == "vad_only":
                regions = [Interval(float(s), float(e)) for s, e in ch.get("speech_regions", [])]
                items = vad_only_items_for_text(text, ch["end"] - ch["start"], regions)
            elif raw.get("text_backend", "qwen") == "qwen" and raw_mode == "aligner_only" and "raw_items" in ch:
                src = ch["raw_items"]
                items = [_RawItem(it["text"], it["start"], it["end"]) for it in src]
            else:
                src = ch.get("items") or ch.get("raw_items") or []
                items = [_RawItem(it["text"], it["start"], it["end"]) for it in src]
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


def _time_aligned_job(job: ChunkJob, items, args: argparse.Namespace) -> tuple[dict, dict, list]:
    """Run the collapse sentinel on a job's aligner items (clip-relative) and, in
    aligner_fallback mode, redistribute when collapsed. Returns (sentinel, recovery, items).

    scene_duration is the widened clip duration (job.end - job.start); speech regions
    are the job's clip-relative VAD regions. Output items stay clip-relative.
    """
    words = items_to_words(items)
    sentinel = assess_alignment_quality(words, job.end - job.start)
    recovery = {"applied": False, "strategy": "none"}
    out_items = list(items)
    if (
        args.timestamp_mode == "aligner_fallback"
        and getattr(args, "collapse_recovery", True)
        and sentinel["status"] == "COLLAPSED"
    ):
        regions = [(iv.start, iv.end) for iv in job.speech]
        recovered = redistribute_collapsed_words(words, job.end - job.start, speech_regions=regions or None)
        out_items = words_to_items(recovered)
        recovery = {"applied": True, "strategy": "vad_guided" if regions else "proportional"}
    return sentinel, recovery, out_items


def _time_anime_job(job: ChunkJob, items, args: argparse.Namespace) -> tuple[dict, dict, list]:
    return _time_aligned_job(job, items, args)


def resolve_qwen_generation_config(model) -> tuple[object | None, str]:
    """Find the HF GenerationConfig used by qwen-asr's transformers backend."""
    candidates = [
        ("model.model.thinker.generation_config", ("model", "thinker", "generation_config")),
        ("model.model.generation_config", ("model", "generation_config")),
        ("model.generation_config", ("generation_config",)),
    ]
    for label, attrs in candidates:
        obj = model
        try:
            for attr in attrs:
                obj = getattr(obj, attr)
        except AttributeError:
            continue
        if obj is not None:
            return obj, label
    return None, "missing"


def apply_qwen_generation_config(model, args: argparse.Namespace) -> dict:
    penalty = float(getattr(args, "repetition_penalty", 1.0))
    if penalty <= 0 or abs(penalty - 1.0) < 1e-9:
        return {"applied": False, "path": "disabled", "repetition_penalty": penalty}
    config, path = resolve_qwen_generation_config(model)
    if config is None:
        print("warning: qwen repetition_penalty requested, but generation_config path was not found", flush=True)
        return {"applied": False, "path": path, "repetition_penalty": penalty}
    setattr(config, "repetition_penalty", penalty)
    return {"applied": True, "path": path, "repetition_penalty": getattr(config, "repetition_penalty", None)}


def qwen_token_budget_for_seconds(clip_seconds: float, args: argparse.Namespace) -> int:
    max_new_tokens = int(getattr(args, "max_new_tokens", 256))
    max_tokens_per_second = float(getattr(args, "max_tokens_per_second", 0.0))
    if max_tokens_per_second <= 0 or clip_seconds <= 0:
        return max_new_tokens
    floor = int(getattr(args, "min_tokens_floor", 256))
    return min(max_new_tokens, max(floor, math.ceil(clip_seconds * max_tokens_per_second)))


def qwen_batch_token_budget(jobs: list[ChunkJob], args: argparse.Namespace) -> dict:
    per_clip = [qwen_token_budget_for_seconds(job.end - job.start, args) for job in jobs]
    return {
        "per_clip": per_clip,
        "batch_budget": max(per_clip, default=int(getattr(args, "max_new_tokens", 256))),
    }


def transcribe_anime(args: argparse.Namespace) -> tuple[list[SubtitleEntry], list[ChunkResult], dict]:
    """anime-whisper text + standalone Qwen forced aligner, two-phase (generate-all then
    align-all). Reuses the existing VAD clip construction; WhisperSeg/semantic are Stage 3/4.

    Phase 1 loads anime-whisper and transcribes each clip to text (cleaned). Phase 2
    either builds vad_only timestamps from VAD regions (WJ anime preset) or unloads it,
    loads the standalone aligner, aligns every non-empty clip, then runs the collapse
    sentinel / recovery before the shared chunk_entries shaping.
    """
    import gc
    import torch
    from transformers import WhisperForConditionalGeneration, WhisperProcessor

    audio, samplerate = load_full_audio(args.audio)
    duration = audio.shape[0] / float(samplerate)
    if getattr(args, "vad_backend", "current") == "whisperseg":
        jobs = build_whisperseg_jobs(audio, samplerate, duration, args)
        mode = "whisperseg"
    elif args.vad_chunks:
        jobs = build_vad_jobs(audio, samplerate, duration, args)
        mode = "vad"
    else:
        jobs = build_fixed_jobs(duration, args)
        mode = "fixed"

    if args.recapture_min_gap > 0:
        print("warning: recapture is not supported on the anime backend; ignoring --recapture-min-gap", flush=True)
    if (args.context or "").strip():
        print("warning: --context is ignored by anime-whisper (model constraint: no initial prompt)", flush=True)

    print(
        f"anime ASR: audio={duration / 60.0:.1f}min mode={mode} clips={len(jobs)} "
        f"batch={args.batch_size} timestamp_mode={args.timestamp_mode} model={args.text_model}",
        flush=True,
    )

    gen_dtype = torch.float16 if "cuda" in str(args.device) else torch.float32

    # ---- Phase 1: generate all clip texts ----
    proc = WhisperProcessor.from_pretrained(str(args.text_model))
    model = WhisperForConditionalGeneration.from_pretrained(str(args.text_model), dtype=gen_dtype).to(args.device)
    max_tokens = min(int(args.max_new_tokens), 444)
    raw_texts: list[str] = []
    clean_texts: list[str] = []
    t0 = time.time()
    for i, job in enumerate(jobs):
        clip = audio[int(job.start * samplerate) : int(job.end * samplerate)]
        feats = proc(clip, sampling_rate=samplerate, return_tensors="pt").input_features.to(args.device, gen_dtype)
        with torch.no_grad():
            ids = model.generate(
                input_features=feats, language="ja", task="transcribe",
                do_sample=False, num_beams=1,
                no_repeat_ngram_size=int(args.no_repeat_ngram_size), max_new_tokens=max_tokens,
            )
        raw = str(proc.batch_decode(ids, skip_special_tokens=True)[0]).strip()
        raw_texts.append(raw)
        clean_texts.append(anime_clean_text(raw))
        if (i + 1) % 50 == 0 or i + 1 == len(jobs):
            el = time.time() - t0
            eta = el / (i + 1) * (len(jobs) - i - 1)
            print(
                f"[anime-gen] {i + 1}/{len(jobs)} elapsed={el:.0f}s eta={eta:.0f}s last={clean_texts[-1][:40]!r}",
                flush=True,
            )
    del model, proc
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    job_items: dict[int, list] = {}
    job_sentinel: dict[int, dict] = {}
    job_recovery: dict[int, dict] = {}
    job_raw_items: dict[int, list] = {}
    idxs = [i for i, c in enumerate(clean_texts) if c]
    n_collapsed = 0
    if args.timestamp_mode == "vad_only":
        for i in idxs:
            job_items[i] = vad_only_items_for_text(clean_texts[i], jobs[i].end - jobs[i].start, jobs[i].speech)
            job_raw_items[i] = []
            job_sentinel[i] = {"status": "N/A", "reason": "vad_only"}
            job_recovery[i] = {"applied": False, "strategy": "vad_only"}
        print(f"[anime-vad-only] timed {len(idxs)} non-empty clips from VAD regions", flush=True)
    else:
        # ---- Phase 2: align all non-empty clips ----
        from qwen_asr.inference.qwen3_forced_aligner import Qwen3ForcedAligner

        aligner = Qwen3ForcedAligner.from_pretrained(
            str(args.forced_aligner), dtype=getattr(torch, args.dtype), device_map=args.device,
        )
        aligner_language = qwen_aligner_language(getattr(args, "language", None))
        t1 = time.time()
        for gstart in range(0, len(idxs), args.batch_size):
            gi = idxs[gstart : gstart + args.batch_size]
            clips = [(audio[int(jobs[i].start * samplerate) : int(jobs[i].end * samplerate)], samplerate) for i in gi]
            texts = [clean_texts[i] for i in gi]
            results = aligner.align(audio=clips, text=texts, language=[aligner_language] * len(clips))
            for i, res in zip(gi, results):
                items = getattr(res, "items", None)
                if items is None:
                    try:
                        items = list(res)
                    except TypeError:
                        items = []
                job_raw_items[i] = items
                sentinel, recovery, out_items = _time_aligned_job(jobs[i], items, args)
                job_sentinel[i] = sentinel
                job_recovery[i] = recovery
                job_items[i] = out_items
                if sentinel["status"] == "COLLAPSED":
                    n_collapsed += 1
            done = min(gstart + args.batch_size, len(idxs))
            print(f"[anime-align] {done}/{len(idxs)} elapsed={time.time() - t1:.0f}s collapsed={n_collapsed}", flush=True)
        del aligner
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    # ---- Build entries + raw dump ----
    entries: list[SubtitleEntry] = []
    chunk_results: list[ChunkResult] = []
    raw_chunks: list[dict] = []
    n_recovered = {"vad_guided": 0, "proportional": 0}
    for i, job in enumerate(jobs):
        clean = clean_texts[i]
        out_items = job_items.get(i, [])
        raw_items = job_raw_items.get(i, [])
        sentinel = job_sentinel.get(i, {})
        recovery = job_recovery.get(i, {"applied": False, "strategy": "none"})
        if recovery.get("applied"):
            n_recovered[recovery["strategy"]] = n_recovered.get(recovery["strategy"], 0) + 1
        kept = chunk_entries(
            clean, out_items, start=job.start, keep_lo=job.keep_lo, keep_hi=job.keep_hi, args=args,
        )
        entries.extend(kept)
        raw_chunks.append({
            "start": job.start,
            "end": job.end,
            "keep_lo": job.keep_lo,
            "keep_hi": None if job.keep_hi == float("inf") else job.keep_hi,
            "raw_text": raw_texts[i],
            "clean_text": clean,
            "speech_regions": [[iv.start, iv.end] for iv in job.speech],
            "raw_items": _serialize_items(raw_items),
            "recovered_items": _serialize_items(out_items) if recovery.get("applied") else [],
            "sentinel": sentinel,
            "recovery": recovery,
            "items": _serialize_items(out_items),
        })
        chunk_results.append(
            ChunkResult(start=job.start, end=job.end, language="ja", text=raw_texts[i], segments=len(kept), seconds=0.0)
        )

    entries.sort(key=lambda e: (e.start, e.end))
    print(
        f"anime done: clips={len(jobs)} non_empty={len(idxs)} collapsed={n_collapsed} "
        f"recovered(vad={n_recovered['vad_guided']}, prop={n_recovered['proportional']}) entries={len(entries)}",
        flush=True,
    )
    raw = {
        "text_backend": "anime",
        "scene_backend": getattr(args, "scene_backend", "none"),
        "vad_backend": getattr(args, "vad_backend", "current"),
        "timestamp_mode": args.timestamp_mode,
        "chunk_seconds": args.chunk_seconds,
        "chunk_overlap_seconds": args.chunk_overlap_seconds,
        "duration": duration,
        "mode": mode,
        "context": "",
        "recapture": {},
        "chunks": raw_chunks,
    }
    return entries, chunk_results, raw


def transcribe_qwen(args: argparse.Namespace) -> tuple[list[SubtitleEntry], list[ChunkResult], dict]:
    if getattr(args, "text_backend", "qwen") == "anime":
        return transcribe_anime(args)
    # Imported here so the pure helpers (filters, chunking) stay importable in
    # environments without the GPU stack, e.g. the pytest suite.
    import torch
    from qwen_asr import Qwen3ASRModel

    use_vad_only = getattr(args, "timestamp_mode", "aligner_fallback") == "vad_only"
    model = Qwen3ASRModel.from_pretrained(
        str(args.model),
        dtype=getattr(torch, args.dtype),
        device_map=args.device,
        max_inference_batch_size=args.batch_size,
        max_new_tokens=args.max_new_tokens,
        forced_aligner=None if use_vad_only else str(args.forced_aligner),
        forced_aligner_kwargs=None if use_vad_only else dict(
            dtype=getattr(torch, args.dtype),
            device_map=args.device,
        ),
    )
    generation_config = apply_qwen_generation_config(model, args)

    audio, samplerate = load_full_audio(args.audio)
    duration = audio.shape[0] / float(samplerate)
    jobs, mode = build_qwen_jobs(audio, samplerate, duration, args)
    entries: list[SubtitleEntry] = []
    chunk_results: list[ChunkResult] = []
    raw_chunks: list[dict] = []
    context = asr_context(args)
    banner = (
        f"Qwen ASR: audio={duration / 60.0:.1f}min mode={mode} chunks={len(jobs)} "
        f"batch={args.batch_size} chunk_seconds={args.chunk_seconds} overlap={args.chunk_overlap_seconds}"
    )
    if mode in {"vad", "whisperseg"}:
        banner += (
            f" vad_backend={getattr(args, 'vad_backend', 'current')} "
            f"scene_backend={getattr(args, 'scene_backend', 'none')}"
            f" vad_pad={args.vad_pad_seconds} pre_context={args.vad_pre_context_seconds} "
            f"post_context={args.vad_post_context_seconds} max_leading={args.vad_max_leading_silence}"
        )
    print(banner, flush=True)
    if context:
        print(f"ASR context: {context}", flush=True)
    print(
        "Qwen generation: "
        f"max_new_tokens={args.max_new_tokens} "
        f"max_tokens_per_second={getattr(args, 'max_tokens_per_second', 0.0)} "
        f"min_tokens_floor={getattr(args, 'min_tokens_floor', 256)} "
        f"repetition_penalty={generation_config.get('repetition_penalty')} "
        f"repetition_path={generation_config.get('path')}",
        flush=True,
    )

    def run_jobs(job_list: list[ChunkJob], label: str, records: list | None = None) -> int:
        added = 0
        for group_start in range(0, len(job_list), args.batch_size):
            group = job_list[group_start : group_start + args.batch_size]
            clips = [(audio[int(j.start * samplerate) : int(j.end * samplerate)], samplerate) for j in group]
            token_budget = qwen_batch_token_budget(group, args)
            original_max_tokens = getattr(model, "max_new_tokens", None)
            t0 = time.time()
            try:
                if float(getattr(args, "max_tokens_per_second", 0.0)) > 0 and original_max_tokens is not None:
                    model.max_new_tokens = token_budget["batch_budget"]
                results = model.transcribe(
                    audio=clips,
                    context=context,
                    language=[args.language] * len(clips),
                    return_time_stamps=not use_vad_only,
                )
            finally:
                if original_max_tokens is not None:
                    model.max_new_tokens = original_max_tokens
            elapsed = time.time() - t0
            for job, result in zip(group, results):
                text = str(result.text or "").strip()
                # Drop context echoes (the model regurgitating the biasing prompt on
                # near-silent clips) before they become spurious cues.
                display_text = "" if is_context_echo(text, context) else text
                if use_vad_only:
                    raw_items = []
                    out_items = vad_only_items_for_text(display_text, job.end - job.start, job.speech)
                    sentinel = {"status": "N/A", "reason": "vad_only"}
                    recovery = {"applied": False, "strategy": "vad_only"}
                else:
                    items = getattr(result.time_stamps, "items", None) if result.time_stamps is not None else None
                    raw_items = list(items or [])
                    sentinel, recovery, out_items = _time_aligned_job(job, raw_items, args)
                kept = chunk_entries(
                    display_text, out_items, start=job.start,
                    keep_lo=job.keep_lo, keep_hi=job.keep_hi, args=args,
                )
                entries.extend(kept)
                added += len(kept)
                chunk_record = {
                    "start": job.start,
                    "end": job.end,
                    "keep_lo": job.keep_lo,
                    "keep_hi": None if job.keep_hi == float("inf") else job.keep_hi,
                    "language": str(result.language),
                    "text": text,
                    "pass": label,
                    "recapture": label == "recapture",
                    "speech_regions": [[iv.start, iv.end] for iv in job.speech],
                    "raw_items": _serialize_items(raw_items),
                    "recovered_items": _serialize_items(out_items) if recovery.get("applied") else [],
                    "sentinel": sentinel,
                    "recovery": recovery,
                    "token_budget": {
                        "max_new_tokens": token_budget["batch_budget"],
                        "max_tokens_per_second": float(getattr(args, "max_tokens_per_second", 0.0)),
                    },
                    "items": _serialize_items(out_items),
                }
                raw_chunks.append(chunk_record)
                if records is not None:
                    records.append((job, kept, sentinel.get("status"), chunk_record))
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
            done = min(group_start + args.batch_size, len(job_list))
            last_text = str(results[-1].text or "").strip()
            print(
                f"[{label}] {done}/{len(job_list)} batch_elapsed={elapsed:.2f}s "
                f"max_new_tokens={token_budget['batch_budget']} text={last_text[:60]}",
                flush=True,
            )
        return added

    main_records: list = []
    run_jobs(jobs, "main", records=main_records)

    # Step-down retry (WJ qwen default): re-frame each collapsed job with a tighter
    # WhisperSeg max_group and re-run transcribe, replacing the collapsed job's cues.
    stepdown_stats: dict = {}
    if getattr(args, "stepdown", True) and mode in {"vad", "whisperseg"}:
        collapsed = [rec for rec in main_records if rec[2] == "COLLAPSED"]
        if collapsed:
            drop = {id(e) for _, kept, _, _ in collapsed for e in kept}
            entries[:] = [e for e in entries if id(e) not in drop]
            for _, _, _, chunk_record in collapsed:
                chunk_record["superseded_by_stepdown"] = True
            sub_jobs = reframe_collapsed_jobs(audio, samplerate, [rec[0] for rec in collapsed], args)
            added = run_jobs(sub_jobs, "stepdown") if sub_jobs else 0
            stepdown_stats = {
                "collapsed_jobs": len(collapsed),
                "reframed_clips": len(sub_jobs),
                "entries_added": added,
                "fallback_max_group": float(getattr(args, "stepdown_fallback_group", args.whisperseg_max_group)),
            }
            print(
                f"Step-down: collapsed_jobs={len(collapsed)} reframed={len(sub_jobs)} "
                f"entries_added={added} fallback={stepdown_stats['fallback_max_group']}s",
                flush=True,
            )

    recapture_stats: dict = {}
    if args.recapture_min_gap > 0:
        # Second look while the model is still loaded: gaps are computed on the
        # pre-filter entries, so regions about to be dropped as interjections still
        # look covered and are not pointlessly re-transcribed. Anything the
        # recapture re-finds that is itself a bare interjection gets removed by the
        # same finalize filters as the main pass.
        spans = uncovered_gap_spans(entries, duration, args.recapture_min_gap)
        recapture_jobs = build_recapture_jobs(audio, samplerate, duration, spans, args)
        added = run_jobs(recapture_jobs, "recapture") if recapture_jobs else 0
        recapture_stats = {
            "gap_spans": len(spans),
            "clips": len(recapture_jobs),
            "entries_added": added,
        }
        print(
            f"Recapture: gap_spans={len(spans)} clips={len(recapture_jobs)} entries_added={added}",
            flush=True,
        )

    entries.sort(key=lambda e: (e.start, e.end))
    raw = {
        "text_backend": "qwen",
        "vad_backend": getattr(args, "vad_backend", "current"),
        "scene_backend": getattr(args, "scene_backend", "none"),
        "timestamp_mode": getattr(args, "timestamp_mode", "aligner_fallback"),
        "chunk_seconds": args.chunk_seconds,
        "chunk_overlap_seconds": args.chunk_overlap_seconds,
        "duration": duration,
        "mode": mode,
        "context": context,
        "generation": {
            **generation_config,
            "max_new_tokens": int(args.max_new_tokens),
            "max_tokens_per_second": float(getattr(args, "max_tokens_per_second", 0.0)),
            "min_tokens_floor": int(getattr(args, "min_tokens_floor", 256)),
            "budget_strategy": "per_batch_max",
        },
        "recapture": recapture_stats,
        "stepdown": stepdown_stats,
        "chunks": raw_chunks,
    }
    return entries, chunk_results, raw


def build_parser() -> argparse.ArgumentParser:
    """Tuning knobs come from QwenAsrConfig (single source of truth, shared with the
    orchestrator); only IO/positional args are declared here."""
    parser = argparse.ArgumentParser(description="Experimental Qwen3-ASR Japanese SRT transcription.")
    parser.add_argument("audio", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--forced-aligner", type=Path, default=DEFAULT_ALIGNER)
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
    add_dataclass_arguments(parser, QwenAsrConfig)
    return parser


def main() -> None:
    args = build_parser().parse_args()

    if args.from_raw is None:
        if args.text_backend == "anime":
            if not Path(args.text_model).exists():
                raise SystemExit(f"Missing anime-whisper model: {args.text_model}")
        elif not args.model.exists():
            raise SystemExit(f"Missing Qwen ASR model: {args.model}")
        needs_forced_aligner = args.timestamp_mode != "vad_only"
        if needs_forced_aligner and not args.forced_aligner.exists():
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
    meta_output.parent.mkdir(parents=True, exist_ok=True)
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
                "vad_backend": getattr(args, "vad_backend", "current"),
                "scene_backend": getattr(args, "scene_backend", "none"),
                "timestamp_mode": getattr(args, "timestamp_mode", "aligner_fallback"),
                "vad_threshold": args.vad_threshold,
                "vad_window_seconds": args.vad_window_seconds,
                "vad_window_overlap_seconds": args.vad_window_overlap_seconds,
                "vad_max_cluster_gap": args.vad_max_cluster_gap,
                "vad_pre_context_seconds": args.vad_pre_context_seconds,
                "vad_post_context_seconds": args.vad_post_context_seconds,
                "vad_max_leading_silence": args.vad_max_leading_silence,
                "vad_context_merge_gap": args.vad_context_merge_gap,
                "recapture": raw.get("recapture", {}),
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
