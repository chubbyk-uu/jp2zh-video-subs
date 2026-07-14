#!/usr/bin/env python3
"""Inspect and validate conservative text-only edits to bilingual ASS files."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path


BILINGUAL_MARKER = r"\N{\rJA}"


@dataclass(frozen=True)
class Dialogue:
    physical_line: int
    event_index: int
    fields: tuple[str, ...]

    @property
    def start(self) -> str:
        return self.fields[1]

    @property
    def end(self) -> str:
        return self.fields[2]

    @property
    def text(self) -> str:
        return self.fields[9]


@dataclass(frozen=True)
class AssFile:
    path: Path
    raw: bytes
    text: str
    lines: tuple[str, ...]
    dialogues: tuple[Dialogue, ...]
    parse_errors: tuple[str, ...]


def load_ass(path: Path) -> AssFile:
    raw = path.read_bytes()
    text = raw.decode("utf-8")
    lines = tuple(text.splitlines())
    dialogues: list[Dialogue] = []
    errors: list[str] = []
    event_index = 0
    for physical_line, line in enumerate(lines, 1):
        if not line.startswith("Dialogue:"):
            continue
        event_index += 1
        fields = tuple(line.split(",", 9))
        if len(fields) != 10:
            errors.append(
                f"physical line {physical_line}: expected 10 Dialogue fields, got {len(fields)}"
            )
            continue
        dialogues.append(Dialogue(physical_line, event_index, fields))
    return AssFile(path, raw, text, lines, tuple(dialogues), tuple(errors))


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def inspect_payload(ass: AssFile) -> dict[str, object]:
    bilingual = sum(BILINGUAL_MARKER in item.text for item in ass.dialogues)
    return {
        "path": str(ass.path),
        "sha256": sha256(ass.raw),
        "bytes": len(ass.raw),
        "physical_lines": len(ass.lines),
        "dialogues": len(ass.dialogues),
        "bilingual_dialogues": bilingual,
        "missing_bilingual_marker": len(ass.dialogues) - bilingual,
        "replacement_characters": ass.text.count("\ufffd"),
        "parse_errors": list(ass.parse_errors),
        "first_start": ass.dialogues[0].start if ass.dialogues else None,
        "last_end": ass.dialogues[-1].end if ass.dialogues else None,
    }


def changed_dialogues(original: AssFile, reviewed: AssFile) -> list[tuple[Dialogue, Dialogue]]:
    return [
        (before, after)
        for before, after in zip(original.dialogues, reviewed.dialogues)
        if before.fields != after.fields
    ]


def bilingual_parts(dialogue: Dialogue) -> tuple[str, str]:
    if BILINGUAL_MARKER not in dialogue.text:
        return dialogue.text, ""
    chinese, japanese = dialogue.text.split(BILINGUAL_MARKER, 1)
    return chinese, japanese


def markdown_cell(value: str) -> str:
    return value.replace("|", r"\|").replace(r"\N", "<br>")


def validation_payload(original: AssFile, reviewed: AssFile) -> dict[str, object]:
    issues: list[str] = []
    if original.parse_errors:
        issues.extend(f"original: {item}" for item in original.parse_errors)
    if reviewed.parse_errors:
        issues.extend(f"reviewed: {item}" for item in reviewed.parse_errors)
    if len(original.lines) != len(reviewed.lines):
        issues.append(
            f"physical line count changed: {len(original.lines)} -> {len(reviewed.lines)}"
        )
    if len(original.dialogues) != len(reviewed.dialogues):
        issues.append(
            f"Dialogue count changed: {len(original.dialogues)} -> {len(reviewed.dialogues)}"
        )

    for number, (before, after) in enumerate(
        zip(original.dialogues, reviewed.dialogues), 1
    ):
        if before.fields[:9] != after.fields[:9]:
            issues.append(f"Dialogue {number}: a non-Text field changed")
        if BILINGUAL_MARKER in before.text and BILINGUAL_MARKER not in after.text:
            issues.append(f"Dialogue {number}: bilingual marker was removed")

    for line_number, (before, after) in enumerate(
        zip(original.lines, reviewed.lines), 1
    ):
        if before != after and not (
            before.startswith("Dialogue:") and after.startswith("Dialogue:")
        ):
            issues.append(f"physical line {line_number}: non-Dialogue content changed")

    if "\ufffd" in reviewed.text:
        issues.append("reviewed file contains Unicode replacement characters")

    changes = changed_dialogues(original, reviewed)
    return {
        "ok": not issues,
        "issues": issues,
        "original_sha256": sha256(original.raw),
        "reviewed_sha256": sha256(reviewed.raw),
        "original_dialogues": len(original.dialogues),
        "reviewed_dialogues": len(reviewed.dialogues),
        "changed_dialogues": len(changes),
        "nontext_fields_identical": not any(
            before.fields[:9] != after.fields[:9]
            for before, after in zip(original.dialogues, reviewed.dialogues)
        ),
    }


def command_inspect(args: argparse.Namespace) -> int:
    try:
        ass = load_ass(args.file)
    except (OSError, UnicodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    payload = inspect_payload(ass)
    payload["ok"] = not ass.parse_errors
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["ok"] else 1


def command_validate(args: argparse.Namespace) -> int:
    try:
        original = load_ass(args.original)
        reviewed = load_ass(args.reviewed)
    except (OSError, UnicodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    payload = validation_payload(original, reviewed)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["ok"] else 1


def command_sheet(args: argparse.Namespace) -> int:
    try:
        ass = load_ass(args.file)
    except (OSError, UnicodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if ass.parse_errors:
        print(json.dumps(inspect_payload(ass), ensure_ascii=False, indent=2), file=sys.stderr)
        return 1

    start = args.start
    end = args.end if args.end is not None else len(ass.dialogues)
    if start < 1 or end < start or end > len(ass.dialogues):
        print(
            f"invalid event range {start}-{end}; file has {len(ass.dialogues)} events",
            file=sys.stderr,
        )
        return 1

    selected = ass.dialogues[start - 1 : end]
    if args.markdown:
        print("| # | Time | Chinese | Japanese |")
        print("|---:|---|---|---|")
        for dialogue in selected:
            chinese, japanese = bilingual_parts(dialogue)
            print(
                f"| {dialogue.event_index} | {dialogue.start} | "
                f"{markdown_cell(chinese)} | {markdown_cell(japanese)} |"
            )
    else:
        for dialogue in selected:
            chinese, japanese = bilingual_parts(dialogue)
            print(
                json.dumps(
                    {
                        "event": dialogue.event_index,
                        "start": dialogue.start,
                        "end": dialogue.end,
                        "chinese": chinese,
                        "japanese": japanese,
                    },
                    ensure_ascii=False,
                )
            )
    return 0


def command_diff(args: argparse.Namespace) -> int:
    try:
        original = load_ass(args.original)
        reviewed = load_ass(args.reviewed)
    except (OSError, UnicodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    payload = validation_payload(original, reviewed)
    if not payload["ok"]:
        print(json.dumps(payload, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1
    changes = changed_dialogues(original, reviewed)
    if args.markdown:
        print("| # | Time | Original | Reviewed |")
        print("|---:|---|---|---|")
        for before, after in changes:
            old = before.text.replace("|", r"\|")
            new = after.text.replace("|", r"\|")
            print(f"| {before.event_index} | {before.start} | {old} | {new} |")
    else:
        for before, after in changes:
            print(
                json.dumps(
                    {
                        "event": before.event_index,
                        "start": before.start,
                        "end": before.end,
                        "original": before.text,
                        "reviewed": after.text,
                    },
                    ensure_ascii=False,
                )
            )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    inspect_parser = commands.add_parser("inspect", help="summarize one ASS file")
    inspect_parser.add_argument("file", type=Path)
    inspect_parser.set_defaults(func=command_inspect)

    sheet_parser = commands.add_parser(
        "sheet", help="print a numbered Chinese/Japanese review sheet"
    )
    sheet_parser.add_argument("file", type=Path)
    sheet_parser.add_argument("--start", type=int, default=1)
    sheet_parser.add_argument("--end", type=int)
    sheet_parser.add_argument("--markdown", action="store_true")
    sheet_parser.set_defaults(func=command_sheet)

    validate_parser = commands.add_parser(
        "validate", help="verify that a reviewed ASS changed Text fields only"
    )
    validate_parser.add_argument("original", type=Path)
    validate_parser.add_argument("reviewed", type=Path)
    validate_parser.set_defaults(func=command_validate)

    diff_parser = commands.add_parser("diff", help="list changed Dialogue Text fields")
    diff_parser.add_argument("original", type=Path)
    diff_parser.add_argument("reviewed", type=Path)
    diff_parser.add_argument("--markdown", action="store_true")
    diff_parser.set_defaults(func=command_diff)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
