from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from atomic_io import atomic_write_text


@dataclass
class Interval:
    start: float
    end: float


def compact_text(text: str) -> str:
    return re.sub(r"\s+", "", text)


DISPLAY_WRAP_PUNCTUATION = frozenset("。？！.!?")


def wrap_display_text(text: str, max_chars: int) -> str:
    """Split one subtitle display string into two lines without changing its cue."""
    if max_chars <= 0 or "\n" in text:
        return text
    normalized = " ".join(line.strip() for line in text.splitlines()).strip()
    visible_positions = [idx for idx, char in enumerate(normalized) if not char.isspace()]
    if len(visible_positions) <= max_chars:
        return normalized
    midpoint = len(visible_positions) / 2.0
    candidates: list[tuple[float, int]] = []
    seen = 0
    for idx, char in enumerate(normalized):
        if char.isspace():
            continue
        seen += 1
        if char in DISPLAY_WRAP_PUNCTUATION and 0 < seen < len(visible_positions):
            candidates.append((abs(seen - midpoint), idx))
    if not candidates:
        return normalized
    _, split_at = min(candidates, key=lambda item: (item[0], item[1]))
    return normalized[: split_at + 1].rstrip() + "\n" + normalized[split_at + 1 :].lstrip()


def wrap_english_display_text(text: str, max_chars: int) -> str:
    """Split English into at most two balanced lines, preferring lines within the limit."""
    if max_chars <= 0 or "\n" in text:
        return text
    normalized = " ".join(text.split())
    if len(normalized) <= max_chars:
        return normalized
    spaces = [index for index, char in enumerate(normalized) if char == " "]
    if not spaces:
        return normalized
    midpoint = len(normalized) / 2.0
    fitting = [
        index for index in spaces
        if index <= max_chars and len(normalized) - index - 1 <= max_chars
    ]
    split_at = min(fitting or spaces, key=lambda index: abs(index - midpoint))
    return normalized[:split_at].rstrip() + "\n" + normalized[split_at + 1 :].lstrip()


def count_overlong_srt_lines(path: Path, max_chars: int) -> int:
    """Count subtitle cues that still exceed a preferred line length after wrapping."""
    if max_chars <= 0:
        return 0
    content = path.read_text(encoding="utf-8")
    count = 0
    for block in re.split(r"\n\s*\n", content.strip()):
        lines = block.splitlines()
        if len(lines) >= 3 and "-->" in lines[1] and any(len(line.strip()) > max_chars for line in lines[2:]):
            count += 1
    return count


def wrap_srt_display_file(path: Path, max_chars: int, target_language: str = "zh-Hans") -> int:
    """Apply punctuation-based two-line display wrapping to an SRT in place."""
    if max_chars <= 0:
        return 0
    content = path.read_text(encoding="utf-8")
    trailing_newline = "\n" if content.endswith("\n") else ""
    blocks = re.split(r"\n\s*\n", content.strip())
    wrapped = 0
    out: list[str] = []
    for block in blocks:
        lines = block.splitlines()
        if len(lines) < 3 or "-->" not in lines[1]:
            out.append(block)
            continue
        text = "\n".join(lines[2:])
        display = (
            wrap_english_display_text(text, max_chars)
            if target_language == "en"
            else wrap_display_text(text, max_chars)
        )
        if display != text:
            wrapped += 1
        out.append("\n".join([*lines[:2], *display.splitlines()]))
    atomic_write_text(path, "\n\n".join(out) + trailing_newline)
    return wrapped


def parse_time(value: str) -> float:
    hours, minutes, rest = value.split(":")
    seconds, milliseconds = rest.split(",")
    return (
        int(hours) * 3600
        + int(minutes) * 60
        + int(seconds)
        + int(milliseconds) / 1000
    )


def srt_time(seconds: float) -> str:
    milliseconds = int(round(seconds * 1000))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"


def format_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    hours = int(seconds // 3600)
    seconds -= hours * 3600
    minutes = int(seconds // 60)
    seconds -= minutes * 60
    return f"{hours:02}:{minutes:02}:{seconds:06.3f}"


def merge_intervals(intervals: list[Interval]) -> list[Interval]:
    if not intervals:
        return []
    intervals = sorted(intervals, key=lambda item: item.start)
    merged = [Interval(intervals[0].start, intervals[0].end)]
    for item in intervals[1:]:
        last = merged[-1]
        if item.start <= last.end:
            last.end = max(last.end, item.end)
        else:
            merged.append(Interval(item.start, item.end))
    return merged


def overlap_seconds(interval: Interval, intervals: list[Interval]) -> float:
    total = 0.0
    for item in intervals:
        if item.end <= interval.start:
            continue
        if item.start >= interval.end:
            break
        total += max(0.0, min(interval.end, item.end) - max(interval.start, item.start))
    return total


def srt_gaps(entries) -> list[Interval]:
    """Uncovered gaps between entries (objects with .start/.end).

    Sorts internally and tracks the running max end, so callers need not pre-sort
    and an overlapping or fully-contained entry does not produce a false gap."""
    gaps: list[Interval] = []
    covered_until: float | None = None
    for entry in sorted(entries, key=lambda item: (item.start, item.end)):
        if covered_until is not None and entry.start > covered_until:
            gaps.append(Interval(covered_until, entry.start))
        covered_until = entry.end if covered_until is None else max(covered_until, entry.end)
    return gaps


def padded_end(
    start: float,
    end: float,
    next_start: float | None,
    lead_out: float,
    min_display: float,
    min_gap: float = 0.04,
) -> float:
    """Display end time that lingers after speech without overlapping the next cue.

    Lengthens the cue to max(end + lead_out, start + min_display); never shortens it
    below the original end, and never extends past next_start - min_gap when a next
    cue exists. With lead_out and min_display both 0 the original end is returned."""
    desired = max(end + lead_out, start + min_display)
    if next_start is not None:
        desired = min(desired, next_start - min_gap)
    return max(end, desired)
