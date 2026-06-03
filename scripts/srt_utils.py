from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class Interval:
    start: float
    end: float


def compact_text(text: str) -> str:
    return re.sub(r"\s+", "", text)


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
