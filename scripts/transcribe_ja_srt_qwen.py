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
from anime_text_clean import anime_clean_text, strip_leading_ellipsis
from asr_common import (
    SubtitleEntry,
    drop_adjacent_near_duplicates,
    filter_main_local_entries,
    resolve_overlaps,
    speech_clusters,
    split_clip_with_overlap,
    write_entries,
)
from cli_config import add_dataclass_arguments
from pipeline_configs import QwenAsrConfig
from srt_utils import Interval


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
# Sentence-ending punctuation. Keep … out because anime-whisper sprays it on soft
# pauses, but split on question/exclamation endings for both qwen and anime.
SENTENCE_END_CHARS = "。？！?!"
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


def source_authoritative_char_times(
    text: str,
    aligned: list[tuple[str, float, float]],
) -> list[tuple[str, float, float]]:
    """Map every source character onto the aligner's timing stream.

    Anime text is authoritative, but the forced aligner can omit a short source
    unit entirely. Sequence alignment preserves matched timings and interpolates
    only missing source characters, preventing a truncated aligner stream from
    silently deleting later sentences.
    """
    source = content_chars(text)
    if not source:
        return []
    if not aligned:
        return [(char, 0.0, 0.0) for char in source]

    target = [char for char, _, _ in aligned]
    mapped: list[tuple[float, float] | None] = [None] * len(source)
    matcher = difflib.SequenceMatcher(None, source, target, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for source_idx, target_idx in zip(range(i1, i2), range(j1, j2)):
                mapped[source_idx] = (aligned[target_idx][1], aligned[target_idx][2])
        elif tag == "replace" and j2 > j1:
            start, end = aligned[j1][1], aligned[j2 - 1][2]
            width = max(0.0, end - start) / max(1, i2 - i1)
            for offset, source_idx in enumerate(range(i1, i2)):
                mapped[source_idx] = (start + offset * width, start + (offset + 1) * width)

    idx = 0
    while idx < len(mapped):
        if mapped[idx] is not None:
            idx += 1
            continue
        run_start = idx
        while idx < len(mapped) and mapped[idx] is None:
            idx += 1
        run_end = idx
        previous_end = mapped[run_start - 1][1] if run_start > 0 and mapped[run_start - 1] else None
        next_start = mapped[run_end][0] if run_end < len(mapped) and mapped[run_end] else None
        if previous_end is None:
            previous_end = next_start if next_start is not None else aligned[0][1]
        if next_start is None:
            next_start = previous_end
        width = max(0.0, next_start - previous_end) / (run_end - run_start)
        for offset, source_idx in enumerate(range(run_start, run_end)):
            mapped[source_idx] = (
                previous_end + offset * width,
                previous_end + (offset + 1) * width,
            )

    return [(char, timing[0], timing[1]) for char, timing in zip(source, mapped) if timing is not None]


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


# Punctuation accepted as a filler-instance boundary (rides on the preceding
# token's display). Token-level collapse is intentionally limited to 3+ explicitly
# separated instances (うん、うん、うん); unpunctuated laughter/emphasis such as
# ふふっ and ねえねえ is source text, not sufficient loop evidence.
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
        if pos != len(core):
            return -1
        # Small kana / elongation marks belong to the instance just matched,
        # including any punctuation carried by their display token.
        while j < n and cores[j] == "":
            j += 1
        return j

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
            if len(bounds) >= 3:
                # Every repeated instance must be explicitly separated. Without
                # this, lexical/emphatic doubles inside a larger run (あ、ああ) are
                # indistinguishable from genuine spoken repetition.
                if not all(has_trailing_punct(end - 1) for _, end in bounds[:-1]):
                    continue
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
    split_internal_gaps: bool = True,
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
    if not split_internal_gaps:
        char_times = source_authoritative_char_times(text, char_times)
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
        pending_prefix = ""
        ci = 0
        for ch in unit:
            if ch in PUNCT_CHARS:
                if tokens:
                    disp, s, e, br = tokens[-1]
                    tokens[-1] = (disp + ch, s, e, br or ch in BREAK_PUNCT)
                else:
                    pending_prefix += ch
                continue
            if ci >= len(span):
                if tokens:
                    disp, s, e, br = tokens[-1]
                    tokens[-1] = (disp + ch, s, e, br)
                continue
            tokens.append((pending_prefix + ch, span[ci][1], span[ci][2], False))
            pending_prefix = ""
            ci += 1
        if not tokens:
            continue
        # Qwen may merge separate utterances into one transcript, so its aligner
        # gaps remain useful cue boundaries. Anime forced alignment starts from an
        # already bounded WhisperSeg frame; an aligner gap inside one punctuated
        # source unit is timing evidence, not permission to invent a text boundary.
        segments: list[list[tuple[str, float, float, bool]]] = [[tokens[0]]]
        for idx, tok in enumerate(tokens[1:], start=1):
            prev = segments[-1][-1]
            gap = tok[1] - prev[2]
            # Optional legacy ellipsis-gap split. Anime forced alignment disables
            # every internal-gap boundary and trusts the source punctuation instead.
            if (
                split_internal_gaps
                and not ellipsis_hard_split
                and "…" in prev[0]
                and gap > ELLIPSIS_SPLIT_GAP_SECONDS
            ):
                segments.append([tok])
                continue
            left_text = "".join(t[0] for t in segments[-1])
            right_text = "".join(t[0] for t in tokens[idx : min(len(tokens), idx + 8)])
            if (
                split_internal_gaps
                and gap > max_internal_gap
                and not should_keep_across_internal_gap(left_text, right_text, gap, max_internal_gap)
            ):
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
            previous_source = getattr(result[-1], "_anime_source_text", None)
            current_source = getattr(entry, "_anime_source_text", None)
            if previous_source is not None and previous_source == current_source:
                # Both cues are distinct source units from one authoritative Anime
                # frame. The aligner collapsed their clocks, not their text; keep
                # both as one cue instead of choosing one and deleting the other.
                result[-1].text += entry.text
                result[-1].end = max(result[-1].end, entry.end)
                result[-1].collapsed = result[-1].collapsed and entry.collapsed
                continue
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

    def source_start(index: int) -> float:
        return float(getattr(ordered[index], "_anime_source_start", ordered[index].start))

    def source_end(index: int) -> float:
        return float(getattr(ordered[index], "_anime_source_end", ordered[index].end))

    for k in range(n):
        if cores[k] in REPLY_INTERJECTION_CORES:
            if (
                reply_anchor_lag > 0
                and last_word_end is not None
                and source_start(k) - last_word_end <= reply_anchor_lag
            ):
                anchored[k] = True
        elif cores[k] not in ALL_FILLER_CORES:
            last_word_end = source_end(k)
    # Anime forced-align can split one source frame into several cues. A bare
    # interjection inside a larger source frame is real source text and must not
    # become newly eligible for deletion merely because alignment isolated it.
    source_cores = [
        _interjection_core(str(getattr(entry, "_anime_source_text", entry.text)))
        for entry in ordered
    ]
    is_filler = [
        c in ALL_FILLER_CORES
        and source_cores[k] in ALL_FILLER_CORES
        and not anchored[k]
        for k, c in enumerate(cores)
    ]
    drop = [False] * n
    i = 0
    while i < n:
        if not is_filler[i]:
            i += 1
            continue
        # Extend a chain of consecutive fillers separated by <= run_gap.
        j = i
        while j + 1 < n and is_filler[j + 1] and (source_start(j + 1) - source_end(j)) <= run_gap:
            j += 1
        lead = source_start(i) - source_end(i - 1) if i > 0 else float("inf")
        trail = source_start(j + 1) - source_end(j) if j + 1 < n else float("inf")
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


def merge_close_cues(
    entries: list[SubtitleEntry], max_gap: float, max_chars: int, max_duration: float
) -> list[SubtitleEntry]:
    """WJ-derived REGROUP_JAV cue merge (aligner branch only).

    Rejoin adjacent cues that were split at sentence punctuation when the pause
    between them is under max_gap, as long as the merged cue stays within
    max_chars (WJ sl=80), max_duration (WJ sd=8), and max_gap (WJ mg=1.5).
    Input must be time-sorted and de-overlapped.
    """
    if not entries:
        return entries
    merged: list[SubtitleEntry] = [entries[0]]
    for e in entries[1:]:
        prev = merged[-1]
        gap = e.start - prev.end
        prev_chars = content_chars(prev.text)
        cur_chars = content_chars(e.text)
        combined_chars = len(prev_chars) + len(cur_chars)
        # Don't concatenate near-duplicate neighbours (would produce a repetitive
        # cue like 「AA'」); leave them for the near-dup squeeze / manual review.
        # Require similar length so a short reply that happens to be a substring of a
        # longer line (「おはよ」 in 「おはようございます」) is NOT treated as a dup.
        a, b = "".join(prev_chars), "".join(cur_chars)
        lo, hi = sorted((len(a), len(b)))
        near_dup = bool(b) and hi > 0 and lo / hi >= 0.6 and difflib.SequenceMatcher(None, a, b).ratio() >= 0.8
        if (
            0.0 <= gap < max_gap
            and combined_chars <= max_chars
            and (e.end - prev.start) <= max_duration
            and not near_dup
        ):
            prev.text = prev.text.rstrip() + e.text.lstrip()
            prev.end = e.end
            prev.collapsed = prev.collapsed and e.collapsed
        else:
            merged.append(e)
    return merged


def merge_close_cues_with_regions(
    entries: list[SubtitleEntry],
    regions: list[Interval],
    *,
    max_gap: float,
    max_chars: int,
    max_duration: float,
) -> list[SubtitleEntry]:
    """Apply cue regrouping without crossing original frame regions.

    Qwen context-merge jobs may contain several WhisperSeg frames. Qwen should hear
    the merged audio, but cue regrouping must remain frame-native so short anchored
    subtitles do not turn into long multi-turn cues.
    """
    if not entries or not regions:
        return merge_close_cues(entries, max_gap=max_gap, max_chars=max_chars, max_duration=max_duration)

    def region_index(entry: SubtitleEntry) -> int | None:
        center = (entry.start + entry.end) / 2.0
        for idx, region in enumerate(regions):
            # Include the right edge with a tiny tolerance so a cue centered exactly
            # on a frame end still belongs to that frame instead of becoming orphaned.
            if region.start <= center < region.end or math.isclose(center, region.end, abs_tol=1e-6):
                return idx
        return None

    merged: list[SubtitleEntry] = []
    current: list[SubtitleEntry] = []
    current_idx: int | None = None

    def flush() -> None:
        nonlocal current
        if current:
            merged.extend(merge_close_cues(current, max_gap=max_gap, max_chars=max_chars, max_duration=max_duration))
            current = []

    for entry in entries:
        idx = region_index(entry)
        if idx is None:
            flush()
            merged.append(entry)
            current_idx = None
            continue
        if current and idx != current_idx:
            flush()
        current.append(entry)
        current_idx = idx
    flush()
    return merged


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
    # (WJ-style cue merge now runs per-clip inside chunk_entries, so it never
    # crosses a clip/frame boundary; nothing to merge globally here.)
    if args.min_cue_seconds > 0:
        filtered: list[SubtitleEntry] = []
        for index, entry in enumerate(entries):
            if entry.end - entry.start >= args.min_cue_seconds:
                filtered.append(entry)
                continue
            source = getattr(entry, "_anime_source_text", None)
            if source is None:
                continue
            if filtered and getattr(filtered[-1], "_anime_source_text", None) == source:
                filtered[-1].text += entry.text
                filtered[-1].end = max(filtered[-1].end, entry.end)
                continue
            if index + 1 < len(entries) and getattr(entries[index + 1], "_anime_source_text", None) == source:
                entries[index + 1].text = entry.text + entries[index + 1].text
                entries[index + 1].start = min(entry.start, entries[index + 1].start)
                continue
            # No safe merge target: preserving authoritative Anime text takes
            # precedence over silently deleting a short, poorly localised cue.
            filtered.append(entry)
        entries = filtered
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
    # Absolute original frame ownership regions inside this job. Context-merge jobs
    # can give Qwen longer audio while keeping WJ-style cue regrouping frame-native.
    regroup_regions: list[Interval] = field(default_factory=list)
    # Diagnostic provenance for the frame boundaries. These do not influence ASR,
    # cue shaping, or ownership; they are emitted in raw dumps for cut analysis.
    left_boundary_reason: str = "unknown"
    right_boundary_reason: str = "unknown"


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
        jobs.append(ChunkJob(start, end, start, keep_hi, left_boundary_reason="fixed_tiling", right_boundary_reason="fixed_tiling"))
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


def _validate_whisperseg_context_args(args: argparse.Namespace) -> tuple[str, float, float, float, float]:
    mode = getattr(args, "whisperseg_context_mode", "none")
    if mode not in {"none", "merge"}:
        raise SystemExit("--whisperseg-context-mode must be one of: none, merge")
    merge_gap = float(getattr(args, "whisperseg_context_merge_gap", 1.0))
    target = float(getattr(args, "whisperseg_context_target_seconds", 10.0))
    after_target_gap = float(getattr(args, "whisperseg_context_after_target_gap", 0.2))
    hard_max = float(getattr(args, "whisperseg_context_hard_max_seconds", 15.0))
    if merge_gap < 0:
        raise SystemExit("--whisperseg-context-merge-gap must be non-negative")
    if after_target_gap < 0:
        raise SystemExit("--whisperseg-context-after-target-gap must be non-negative")
    if target <= 0:
        raise SystemExit("--whisperseg-context-target-seconds must be positive")
    if hard_max < target:
        raise SystemExit("--whisperseg-context-hard-max-seconds must be >= --whisperseg-context-target-seconds")
    return mode, merge_gap, target, after_target_gap, hard_max


def validate_runtime_args(args: argparse.Namespace) -> None:
    """Validate cross-field combinations that argparse choices cannot express."""
    if (
        getattr(args, "text_backend", "qwen") == "anime"
        and getattr(args, "whisperseg_context_mode", "none") != "none"
    ):
        raise SystemExit("anime does not support WhisperSeg context merge; use --whisperseg-context-mode none")
    if (
        getattr(args, "timestamp_mode", "aligner_fallback") == "vad_only"
        and getattr(args, "vad_backend", "whisperseg") == "whisperseg"
        and getattr(args, "whisperseg_context_mode", "none") != "none"
    ):
        backend = getattr(args, "text_backend", "qwen")
        raise SystemExit(
            f"{backend} vad_only cannot be combined with WhisperSeg context merge. "
            "Use --whisperseg-context-mode none (top-level: --qwen-whisperseg-context-mode none), "
            "or use --timestamp-mode aligner_fallback (top-level: --qwen-timestamp-mode aligner_fallback) "
            "for long-context recognition."
        )


def normalize_runtime_args(args: argparse.Namespace) -> None:
    """Apply backend-dependent defaults after parsing shared qwen/anime flags."""
    if getattr(args, "whisperseg_context_mode", None) is None:
        # Both backends default to no context merge (Stage 6.7): the short
        # scene-processed frames are the stable production path; longer qwen
        # recognition windows added drift/drops in manual review.
        args.whisperseg_context_mode = "none"
    validate_runtime_args(args)


def _whisperseg_group_bounds(group) -> tuple[float, float]:
    return float(group[0].start), float(group[-1].end)


def _whisperseg_group_boundary_reason(group, side: str) -> str:
    """Read provenance from native WhisperSeg groups, tolerating legacy bare lists."""
    attr = f"{side}_boundary_reason"
    return str(getattr(group, attr, "unknown"))


def _reconcile_semantic_scene_groups(
    candidates: list[tuple[int, object]],
    *,
    max_group_duration_s: float,
    chunk_threshold_s: float,
) -> list:
    """Canonicalize WhisperSeg groups duplicated by adjacent padded scenes.

    Only materially overlapping envelopes from adjacent scenes participate. This
    leaves ordinary per-scene framing and one-sided weak detections untouched,
    while a connected overlap component is reduced to non-overlapping speech
    intervals and regrouped with the backend's normal rules.
    """
    from whisperseg_vad import SpeechSegment, group_segments

    ordered = sorted(
        [(scene_idx, group) for scene_idx, group in candidates if group],
        key=lambda item: _whisperseg_group_bounds(item[1]),
    )
    if len(ordered) < 2:
        return [group for _, group in ordered]

    parent = list(range(len(ordered)))

    def find(idx: int) -> int:
        while parent[idx] != idx:
            parent[idx] = parent[parent[idx]]
            idx = parent[idx]
        return idx

    def union(left: int, right: int) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    # WhisperSeg probabilities have 20ms resolution. Requiring two frames of
    # envelope overlap avoids treating rounding contact as duplicate evidence.
    material_overlap = 0.04 - 1e-9
    for left in range(len(ordered)):
        left_scene, left_group = ordered[left]
        _, left_end = _whisperseg_group_bounds(left_group)
        for right in range(left + 1, len(ordered)):
            right_scene, right_group = ordered[right]
            right_start, right_end = _whisperseg_group_bounds(right_group)
            if right_start >= left_end:
                break
            if abs(right_scene - left_scene) != 1:
                continue
            left_start, _ = _whisperseg_group_bounds(left_group)
            if min(left_end, right_end) - max(left_start, right_start) >= material_overlap:
                union(left, right)

    components: dict[int, list[int]] = {}
    for idx in range(len(ordered)):
        components.setdefault(find(idx), []).append(idx)

    canonical = []
    for indices in components.values():
        if len(indices) == 1:
            canonical.append(ordered[indices[0]][1])
            continue

        source_groups = [ordered[idx][1] for idx in indices]
        segments = sorted(
            (seg for group in source_groups for seg in group),
            key=lambda seg: (float(seg.start), float(seg.end)),
        )
        merged: list[SpeechSegment] = []
        for seg in segments:
            start, end = float(seg.start), float(seg.end)
            if merged and start <= merged[-1].end + 1e-9:
                if end > merged[-1].end:
                    merged[-1].end = end
                    merged[-1].end_reason = str(getattr(seg, "end_reason", "unknown"))
            else:
                merged.append(SpeechSegment(start, end, str(getattr(seg, "end_reason", "unknown"))))

        regrouped = group_segments(merged, max_group_duration_s, chunk_threshold_s)
        if regrouped:
            earliest = min(source_groups, key=lambda group: _whisperseg_group_bounds(group)[0])
            latest = max(source_groups, key=lambda group: _whisperseg_group_bounds(group)[1])
            regrouped[0].left_boundary_reason = _whisperseg_group_boundary_reason(earliest, "left")
            regrouped[-1].right_boundary_reason = _whisperseg_group_boundary_reason(latest, "right")
            canonical.extend(regrouped)

    return sorted(canonical, key=_whisperseg_group_bounds)


def _whisperseg_context_jobs(groups: list, duration: float, args: argparse.Namespace) -> list[ChunkJob]:
    """Convert atomic WhisperSeg groups to Qwen recognition jobs.

    Mode "none" preserves the Stage 6.4 behavior exactly: one short speech-pure
    frame per job. Qwen-only merge makes Qwen hear more audio while keeping
    cue ownership and fallback speech regions tied to the owned WhisperSeg speech rather
    than to the extra context.
    """
    mode, merge_gap, target, after_target_gap, hard_max = _validate_whisperseg_context_args(args)
    atomic = [g for g in groups if g and (_whisperseg_group_bounds(g)[1] - _whisperseg_group_bounds(g)[0]) >= args.whisperseg_min_frame_seconds]
    if not atomic:
        return []

    def make_job(component_groups: list, *, is_last: bool) -> ChunkJob:
        owned_start = _whisperseg_group_bounds(component_groups[0])[0]
        owned_end = _whisperseg_group_bounds(component_groups[-1])[1]
        keep_hi = float("inf") if is_last else owned_end
        # Scene padding belongs solely to the WhisperSeg input window. Every Qwen
        # job, including a merged one, is sliced exactly to its owned frame bounds.
        # Otherwise Qwen can emit non-owned boundary speech and create duplicates.
        job = ChunkJob(
            owned_start,
            owned_end,
            owned_start,
            keep_hi,
            left_boundary_reason=_whisperseg_group_boundary_reason(component_groups[0], "left"),
            right_boundary_reason=_whisperseg_group_boundary_reason(component_groups[-1], "right"),
        )
        job.speech = [
            Interval(float(seg.start) - owned_start, float(seg.end) - owned_start)
            for group in component_groups
            for seg in group
        ]
        if len(component_groups) > 1:
            job.regroup_regions = [
                Interval(*_whisperseg_group_bounds(group))
                for group in component_groups
            ]
        return job

    if mode == "none":
        return [make_job([g], is_last=(i == len(atomic) - 1)) for i, g in enumerate(atomic)]

    merged: list[list] = []
    cur: list | None = None
    cur_start = cur_end = 0.0
    hard_cuts = 0  # breaks forced by hard_max despite a small (mergeable) gap = mid-speech truncation
    soft_breaks = 0  # graceful breaks taken past the soft target at a natural pause
    for group in atomic:
        start, end = _whisperseg_group_bounds(group)
        if cur is None:
            cur = [group]
            cur_start, cur_end = start, end
            continue
        gap = start - cur_end
        # Past the soft target, tighten the gap tolerance so the group ends at the next
        # real pause instead of greedily merging until hard_max forces a mid-speech cut.
        tol = merge_gap if (cur_end - cur_start) < target else min(merge_gap, after_target_gap)
        if gap <= tol and end - cur_start <= hard_max:
            cur.append(group)
            cur_end = end
        else:
            if gap <= tol:  # would have merged but hard_max forced the split
                hard_cuts += 1
            elif gap <= merge_gap:  # broke early only because we passed the soft target
                soft_breaks += 1
            merged.append(cur)
            cur = [group]
            cur_start, cur_end = start, end
    if cur is not None:
        merged.append(cur)

    jobs = [make_job(group_list, is_last=(i == len(merged) - 1)) for i, group_list in enumerate(merged)]
    print(
        f"WhisperSeg qwen context: mode=merge frames={len(atomic)} jobs={len(jobs)} "
        f"gap={merge_gap}s target={target}s after_target_gap={after_target_gap}s hard_max={hard_max}s "
        f"hard_cuts={hard_cuts} soft_breaks={soft_breaks}",
        flush=True,
    )
    return jobs


def build_whisperseg_jobs(audio, samplerate: int, duration: float, args: argparse.Namespace) -> list[ChunkJob]:
    """Short, speech-pure frames from WhisperSeg (Stage 3). Each grouped frame becomes
    one ChunkJob spanning its speech; the frame's speech segments are stored
    clip-relative for the collapse sentinel's VAD-guided recovery.

    Semantic-scene candidates are reconciled before job creation, so cue ownership
    is simply the canonical frame's own [start, end).
    """
    from whisperseg_vad import WhisperSegVAD, resolve_model_path

    if samplerate != 16000:
        raise SystemExit("--vad-backend whisperseg requires 16 kHz audio")
    vad = WhisperSegVAD(
        model_path=resolve_model_path(str(args.whisperseg_model)),
        threshold=args.whisperseg_threshold,
        max_speech_duration_s=args.whisperseg_max_speech,
        hard_max_speech_duration_s=getattr(
            args, "whisperseg_hard_max_speech", getattr(args, "whisperseg_max_speech", 5.0)
        ),
        soft_split_lookback_s=getattr(args, "whisperseg_soft_split_lookback", 1.0),
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
        scene_asr_pad = max(0.0, float(getattr(args, "scene_asr_pad_seconds", 0.0)))
        print(
            f"semantic scenes: {len(scenes)} (min={args.scene_min_seconds}s max={args.scene_max_seconds}s "
            f"asr_pad={scene_asr_pad}s)",
            flush=True,
        )
        scene_candidates: list[tuple[int, object]] = []
        for scene_idx, (ss, se) in enumerate(scenes):
            # WhisperJAV semantic scenes use strict timestamps for the timeline, but
            # feed ASR/VAD with an overlapped "asr_processing" window (±0.35s).
            # The pad changes WhisperSeg's 30s chunk origin and preserves soft
            # boundary consonants/particles; without it anime-whisper sees worse
            # cut points and misrecognizes otherwise stable phrases.
            asr_start = max(0.0, ss - scene_asr_pad)
            asr_end = min(duration, se + scene_asr_pad)
            seg_audio = audio[int(asr_start * samplerate) : int(asr_end * samplerate)]
            if len(seg_audio) < int(0.1 * samplerate):
                continue
            scene_groups = vad.segment(seg_audio, samplerate)
            # A VAD "audio_end" here can mean only the end of this semantic-scene
            # input window. Preserve that distinction for boundary diagnostics.
            if scene_groups and asr_start > 0 and getattr(scene_groups[0], "left_boundary_reason", "") == "audio_start":
                scene_groups[0].left_boundary_reason = "semantic_scene_start"
            if scene_groups and asr_end < duration and getattr(scene_groups[-1], "right_boundary_reason", "") == "audio_end":
                scene_groups[-1].right_boundary_reason = "semantic_scene_end"
            for g in scene_groups:
                for s in g:
                    s.start += asr_start
                    s.end += asr_start
                scene_candidates.append((scene_idx, g))
        groups = _reconcile_semantic_scene_groups(
            scene_candidates,
            max_group_duration_s=args.whisperseg_max_group,
            chunk_threshold_s=args.whisperseg_chunk_threshold,
        )
        print(
            f"semantic WhisperSeg reconciliation: candidates={len(scene_candidates)} "
            f"canonical={len(groups)}",
            flush=True,
        )
    else:
        groups = vad.segment(audio, samplerate)
    vad.cleanup()
    boundary_counts: dict[str, int] = {}
    for group in groups:
        reason = _whisperseg_group_boundary_reason(group, "right")
        boundary_counts[reason] = boundary_counts.get(reason, 0) + 1
    print(f"WhisperSeg frame boundaries: {boundary_counts}", flush=True)
    return _whisperseg_context_jobs(groups, duration, args)


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
    main_hard_max = float(
        getattr(args, "whisperseg_hard_max_speech", getattr(args, "whisperseg_max_speech", 5.0))
    )
    vad = WhisperSegVAD(
        model_path=resolve_model_path(str(args.whisperseg_model)),
        threshold=args.whisperseg_threshold,
        max_speech_duration_s=min(float(args.whisperseg_max_speech), fallback),
        hard_max_speech_duration_s=min(main_hard_max, fallback),
        soft_split_lookback_s=getattr(args, "whisperseg_soft_split_lookback", 1.0),
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
            sub = ChunkJob(
                a,
                e,
                keep_lo,
                keep_hi,
                left_boundary_reason="stepdown",
                right_boundary_reason="stepdown",
            )
            sub.speech = [Interval(s.start - fs, s.end - fs) for s in g]
            sub_jobs.append(sub)
    vad.cleanup()
    return sub_jobs


def build_qwen_jobs(audio, samplerate: int, duration: float, args: argparse.Namespace) -> tuple[list[ChunkJob], str]:
    """Build qwen clips from the selected framing backend.

    The Qwen default is semantic-scene WhisperSeg framing with short scene-padded
    frames (context mode none). The older Silero/VAD path and optional qwen context
    merge experiment remain selectable for comparison.
    """
    if args.vad_chunks:
        return build_whisperseg_jobs(audio, samplerate, duration, args), "whisperseg"
    return build_fixed_jobs(duration, args), "fixed"


def chunk_entries(
    text: str,
    items,
    *,
    start: float,
    source_end: float | None = None,
    keep_lo: float,
    keep_hi: float,
    regroup_regions: list[Interval] | None = None,
    args: argparse.Namespace,
) -> list[SubtitleEntry]:
    """Build one chunk's kept cues: sentence timing + claim-window dedup.

    Shared by the live model path and the --from-raw replay so both produce
    identical output for the same post-processing knobs. A cue is kept by the one
    clip whose [keep_lo, keep_hi) window holds the cue center.
    """
    anime_backend = getattr(args, "text_backend", "qwen") == "anime"
    # Claim ownership with the raw aligner span. Applying the display-duration
    # floor first can move a short cue's center beyond keep_hi and discard valid
    # frame-tail speech (for example a 240ms cue expanded to 800ms).
    sentence_entries = sentences_from_alignment(
        text,
        items,
        offset=start,
        max_chars=args.phrase_max_chars,
        max_duration=args.phrase_max_duration,
        min_duration=0.0,
        max_internal_gap=args.phrase_max_internal_gap,
        max_char_seconds=args.phrase_max_char_seconds,
        collapse_fillers=getattr(args, "collapse_filler_repetition", True),
        ellipsis_hard_split=not anime_backend,
        split_internal_gaps=not anime_backend,
    )
    kept = [e for e in sentence_entries if keep_lo <= (e.start + e.end) / 2.0 < keep_hi]
    for entry in kept:
        entry.end = max(entry.end, entry.start + args.min_duration)
        entry.end = min(entry.end, entry.start + args.phrase_max_duration)
    # WJ REGROUP_JAV cue merge is applied *within this clip's own cues* only (WJ
    # regroups per stable-ts clip result, never across clip boundaries). This packs
    # a clip's back-to-back sentences into one cue while a real clip/frame boundary
    # (silence, scene edge) still separates speaker turns. qwen only; anime is
    # frame-native (WJ Branch B: no gap merge).
    if not anime_backend:
        kept = merge_close_cues_with_regions(
            kept,
            regroup_regions or [],
            max_gap=getattr(args, "phrase_max_internal_gap", 1.5),
            max_chars=getattr(args, "phrase_max_chars", 80),
            max_duration=getattr(args, "phrase_max_duration", 8.0),
        )
    else:
        for entry in kept:
            entry._anime_source_text = text
            entry._anime_source_start = start
            entry._anime_source_end = source_end if source_end is not None else max(e.end for e in kept)
    return kept


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


def wj_regroup_vad_only_split(text: str, comma_min_chars: int = 50, max_chars: int = 80) -> list[str]:
    """Length-only frame split for the anime vad_only branch (option B).

    Sentence punctuation (。？！?!) does NOT force a cue break: anime-whisper
    sprays sentence enders on every soft pause, so splitting on them over-fragments
    into sub-0.8s flash cues. We only split a frame for length — at a Japanese/ASCII
    comma (、，,) once a run passes comma_min_chars, and a hard cut of a comma-less
    run past max_chars. … never splits. This matches the wjav_out anime dump, which
    was produced with regroup off = pure frame-native timing.
    """
    if len(content_chars(text)) <= comma_min_chars:
        return [text] if content_chars(text) else []
    commas = "、，,"
    pieces: list[str] = []
    sub = ""
    for ch in text:
        sub += ch
        n = len(content_chars(sub))
        if (ch in commas and n >= comma_min_chars) or n >= max_chars:
            pieces.append(sub)
            sub = ""
    if sub:
        pieces.append(sub)
    return [p for p in pieces if content_chars(p)]


def anime_vad_only_frame_entry(text: str, start: float, end: float) -> list[SubtitleEntry]:
    """WJ-style anime vad_only reconstruction (REGROUP_VAD_ONLY).

    WhisperJAV's anime preset uses no aligner; timestamps are proportional. A frame
    is kept whole and split only for length — at a comma past 50 chars, hard-capped
    at 80 (see wj_regroup_vad_only_split); sentence punctuation does NOT force a break
    (it over-fragments into flash cues). The frame's [start, end] is distributed
    across any length-pieces by content-char count. … never splits, and a leading …
    at each cue start is dropped (anime-whisper sprays … on soft pauses).
    """
    display = text.strip()
    if not display or not content_chars(display) or end <= start:
        return []

    def mark_source(entries: list[SubtitleEntry]) -> list[SubtitleEntry]:
        for entry in entries:
            entry._anime_source_text = text
            entry._anime_source_start = start
            entry._anime_source_end = end
        return entries

    pieces = wj_regroup_vad_only_split(display)
    if len(pieces) <= 1:
        single = strip_leading_ellipsis(display)
        entries = [SubtitleEntry(start, end, single)] if content_chars(single) else []
        return mark_source(entries)
    total = sum(len(content_chars(p)) for p in pieces) or 1
    entries: list[SubtitleEntry] = []
    cursor = start
    acc = 0
    for i, piece in enumerate(pieces):
        acc += len(content_chars(piece))
        piece_end = end if i == len(pieces) - 1 else start + (end - start) * acc / total
        # Drop a leading … at each cue start (frame onset, or a new sentence after 。…).
        display_piece = strip_leading_ellipsis(piece.strip())
        if content_chars(display_piece) and piece_end > cursor:
            entries.append(SubtitleEntry(cursor, piece_end, display_piece))
        cursor = piece_end
    return mark_source(entries or [SubtitleEntry(start, end, display)])


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
        raw_backend = raw.get("text_backend", getattr(args, "text_backend", "qwen"))
        anime_vad_only_raw = (
            "clean_text" in ch
            and raw_backend == "anime"
            and getattr(args, "timestamp_mode", raw.get("timestamp_mode", "aligner_fallback")) == "vad_only"
        )
        if "clean_text" in ch:
            # anime schema: text is already cleaned; no context echo to strip.
            text = ch["clean_text"]
            if anime_vad_only_raw:
                items = []
            elif getattr(args, "timestamp_mode", "aligner_fallback") == "vad_only":
                regions = [Interval(float(s), float(e)) for s, e in ch.get("speech_regions", [])]
                items = vad_only_items_for_text(text, ch["end"] - ch["start"], regions)
            else:
                src = ch["raw_items"] if (anime_only and "raw_items" in ch) else ch["items"]
                items = [_RawItem(it["text"], it["start"], it["end"]) for it in src]
                if (
                    not anime_only
                    and getattr(args, "timestamp_mode", "aligner_fallback") == "aligner_fallback"
                    and getattr(args, "collapse_recovery", True)
                ):
                    raw_src = ch.get("raw_items", src)
                    raw_items = [_RawItem(it["text"], it["start"], it["end"]) for it in raw_src]
                    if anime_local_alignment_collapse_reasons(
                        text,
                        raw_items,
                        float(getattr(args, "phrase_max_char_seconds", 0.5)),
                    ):
                        regions = [Interval(float(s), float(e)) for s, e in ch.get("speech_regions", [])]
                        items = vad_only_items_for_text(text, ch["end"] - ch["start"], regions)
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
        if anime_vad_only_raw:
            entries.extend(anime_vad_only_frame_entry(text, ch["start"], ch["end"]))
        else:
            entries.extend(
                chunk_entries(
                    text, items, start=ch["start"], source_end=ch["end"],
                    keep_lo=keep_lo, keep_hi=keep_hi,
                    regroup_regions=[Interval(float(s), float(e)) for s, e in ch.get("regroup_regions", [])],
                    args=args,
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


def anime_local_alignment_collapse_reasons(
    text: str,
    items,
    max_char_seconds: float = 0.5,
) -> list[str]:
    """Return source-unit collapse reasons missed by the job-level sentinel.

    A long job can look healthy overall while one punctuated Anime source unit is
    missing or stamped onto a point. Such a unit cannot be safely repaired with
    neighbouring aligner timestamps; the whole short frame should use VAD timing.
    """
    units = split_into_units(text, max_chars=80, ellipsis_hard=False)
    char_times = flatten_item_chars(items, max_char_seconds)
    reasons: list[str] = []
    pos = 0
    previous_start: float | None = None
    for unit_index, unit in enumerate(units):
        need = len(content_chars(unit))
        if need == 0:
            continue
        span = char_times[pos : pos + need]
        pos += need
        if len(span) < need:
            reasons.append(f"unit_{unit_index}_missing_chars")
        if not span:
            continue
        unit_start = min(item[1] for item in span)
        unit_end = max(item[2] for item in span)
        if unit_end - unit_start <= COLLAPSED_SPAN_SECONDS:
            reasons.append(f"unit_{unit_index}_zero_span")
        if previous_start is not None and abs(unit_start - previous_start) <= 0.05:
            reasons.append(f"unit_{unit_index}_same_start")
        previous_start = unit_start
    return reasons


def _time_anime_job(
    job: ChunkJob,
    items,
    args: argparse.Namespace,
    text: str = "",
) -> tuple[dict, dict, list]:
    sentinel, recovery, out_items = _time_aligned_job(job, items, args)
    reasons = anime_local_alignment_collapse_reasons(
        text,
        items,
        float(getattr(args, "phrase_max_char_seconds", 0.5)),
    ) if text else []
    if (
        reasons
        and args.timestamp_mode == "aligner_fallback"
        and getattr(args, "collapse_recovery", True)
    ):
        out_items = vad_only_items_for_text(text, job.end - job.start, job.speech)
        sentinel = dict(sentinel)
        sentinel["status"] = "COLLAPSED"
        sentinel["triggers"] = [*sentinel.get("triggers", []), *reasons]
        recovery = {
            "applied": True,
            "strategy": "vad_only_local_unit",
            "reasons": reasons,
        }
    return sentinel, recovery, out_items


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
    if args.vad_chunks:
        jobs = build_whisperseg_jobs(audio, samplerate, duration, args)
        mode = "whisperseg"
    else:
        jobs = build_fixed_jobs(duration, args)
        mode = "fixed"

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
                sentinel, recovery, out_items = _time_anime_job(
                    jobs[i], items, args, clean_texts[i]
                )
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
    n_recovered = {"vad_guided": 0, "proportional": 0, "vad_only_local_unit": 0}
    for i, job in enumerate(jobs):
        clean = clean_texts[i]
        out_items = job_items.get(i, [])
        raw_items = job_raw_items.get(i, [])
        sentinel = job_sentinel.get(i, {})
        recovery = job_recovery.get(i, {"applied": False, "strategy": "none"})
        if recovery.get("applied"):
            n_recovered[recovery["strategy"]] = n_recovered.get(recovery["strategy"], 0) + 1
        if args.timestamp_mode == "vad_only":
            kept = anime_vad_only_frame_entry(clean, job.start, job.end)
        else:
            kept = chunk_entries(
                clean, out_items, start=job.start, source_end=job.end,
                keep_lo=job.keep_lo, keep_hi=job.keep_hi,
                regroup_regions=job.regroup_regions,
                args=args,
            )
        entries.extend(kept)
        raw_chunks.append({
            "start": job.start,
            "end": job.end,
            "keep_lo": job.keep_lo,
            "keep_hi": None if job.keep_hi == float("inf") else job.keep_hi,
            "left_boundary_reason": job.left_boundary_reason,
            "right_boundary_reason": job.right_boundary_reason,
            "raw_text": raw_texts[i],
            "clean_text": clean,
            "speech_regions": [[iv.start, iv.end] for iv in job.speech],
            "regroup_regions": [[iv.start, iv.end] for iv in job.regroup_regions],
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
        f"recovered(vad={n_recovered['vad_guided']}, prop={n_recovered['proportional']}, "
        f"local_vad={n_recovered['vad_only_local_unit']}) entries={len(entries)}",
        flush=True,
    )
    raw = {
        "text_backend": "anime",
        "scene_backend": getattr(args, "scene_backend", "none"),
        "vad_backend": getattr(args, "vad_backend", "whisperseg"),
        "timestamp_mode": args.timestamp_mode,
        "chunk_seconds": args.chunk_seconds,
        "chunk_overlap_seconds": args.chunk_overlap_seconds,
        "duration": duration,
        "mode": mode,
        "context": "",
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
                    display_text, out_items, start=job.start, source_end=job.end,
                    keep_lo=job.keep_lo, keep_hi=job.keep_hi,
                    regroup_regions=job.regroup_regions,
                    args=args,
                )
                entries.extend(kept)
                added += len(kept)
                chunk_record = {
                    "start": job.start,
                    "end": job.end,
                    "keep_lo": job.keep_lo,
                    "keep_hi": None if job.keep_hi == float("inf") else job.keep_hi,
                    "left_boundary_reason": job.left_boundary_reason,
                    "right_boundary_reason": job.right_boundary_reason,
                    "language": str(result.language),
                    "text": text,
                    "pass": label,
                    "speech_regions": [[iv.start, iv.end] for iv in job.speech],
                    "regroup_regions": [[iv.start, iv.end] for iv in job.regroup_regions],
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

    entries.sort(key=lambda e: (e.start, e.end))
    raw = {
        "text_backend": "qwen",
        "vad_backend": getattr(args, "vad_backend", "whisperseg"),
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
        "whisperseg_split": {
            "soft_target_seconds": float(getattr(args, "whisperseg_max_speech", 5.0)),
            "hard_max_seconds": float(
                getattr(args, "whisperseg_hard_max_speech", getattr(args, "whisperseg_max_speech", 5.0))
            ),
            "lookback_seconds": float(getattr(args, "whisperseg_soft_split_lookback", 1.0)),
        },
        "whisperseg_context": {
            "mode": getattr(args, "whisperseg_context_mode", "none"),
            "merge_gap": float(getattr(args, "whisperseg_context_merge_gap", 1.0)),
            "target_seconds": float(getattr(args, "whisperseg_context_target_seconds", 10.0)),
            "after_target_gap": float(getattr(args, "whisperseg_context_after_target_gap", 0.2)),
            "hard_max_seconds": float(getattr(args, "whisperseg_context_hard_max_seconds", 15.0)),
        },
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
    # The shared parser still normalizes backend-dependent defaults after parsing;
    # both current top-level backends default to no WhisperSeg context expansion.
    parser.set_defaults(whisperseg_context_mode=None)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    normalize_runtime_args(args)

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
                "vad_backend": getattr(args, "vad_backend", "whisperseg"),
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
                "whisperseg_max_speech": float(getattr(args, "whisperseg_max_speech", 5.0)),
                "whisperseg_hard_max_speech": float(
                    getattr(args, "whisperseg_hard_max_speech", getattr(args, "whisperseg_max_speech", 5.0))
                ),
                "whisperseg_soft_split_lookback": float(getattr(args, "whisperseg_soft_split_lookback", 1.0)),
                "whisperseg_context_mode": getattr(args, "whisperseg_context_mode", "none"),
                "whisperseg_context_merge_gap": float(getattr(args, "whisperseg_context_merge_gap", 1.0)),
                "whisperseg_context_target_seconds": float(getattr(args, "whisperseg_context_target_seconds", 10.0)),
                "whisperseg_context_after_target_gap": float(getattr(args, "whisperseg_context_after_target_gap", 0.2)),
                "whisperseg_context_hard_max_seconds": float(getattr(args, "whisperseg_context_hard_max_seconds", 15.0)),
                "scene_asr_pad_seconds": float(getattr(args, "scene_asr_pad_seconds", 0.0)),
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
