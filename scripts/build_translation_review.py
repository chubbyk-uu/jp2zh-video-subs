"""Build a private, escaped side-by-side translation review page; no accuracy score."""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import random
from pathlib import Path


def render_review(results: dict[str, dict], seed: int = 20260928) -> tuple[str, dict]:
    if not results:
        raise ValueError("at least one translation result required")
    indexed = {}
    for name, result in results.items():
        if result.get("reference_kind") != "context_reviewed":
            raise ValueError(f"{name}: expected a context-reviewed pilot reference")
        if result.get("status") != "complete":
            raise ValueError(f"{name}: review requires a complete run; inspect errors first")
        samples = result["samples"]
        if len(samples) != len({s["id"] for s in samples}):
            raise ValueError(f"{name}: duplicate sample IDs")
        indexed[name] = {s["id"]: s for s in samples}
    first = next(iter(indexed.values()))
    if any(set(samples) != set(first) for samples in indexed.values()):
        raise ValueError("result sample IDs differ")
    rng, sections, mappings = random.Random(seed), [], {}
    for sample_id, sample in first.items():
        source = sample["fixed_source"]
        if any(samples[sample_id]["fixed_source"] != source for samples in indexed.values()):
            raise ValueError(f"{sample_id}: fixed Japanese sources differ")
        names = list(results)
        rng.shuffle(names)
        mappings[sample_id] = dict(zip((chr(65 + i) for i in range(len(names))), names))
        columns = []
        for name in names:
            row = indexed[name][sample_id]
            records = row["checked"]["records"] if "checked" in row else row["records"]
            by_id = {}
            for record in records:
                prefix = f"[并条 {','.join(record['ids'])}] " if len(record["ids"]) > 1 else ""
                for id_ in record["ids"]:
                    by_id.setdefault(id_, []).append(prefix + (record["text"] if record["text"] is not None else "[显式删除，需复核]"))
            columns.append(by_id)
        rows = []
        for entry in source:
            cells = [entry["id"], entry["ja"], entry["zh"],
                     *(" | ".join(column.get(entry["id"], ["[未覆盖 ID]"])) for column in columns)]
            rows.append("<tr>" + "".join(f"<td>{html.escape(value)}</td>" for value in cells) + "</tr>")
        headers = ["源 ID", "冻结日文", "参考中文（允许其他正确表达）", *(chr(65 + i) for i in range(len(names)))]
        sections.append(f"<h2>{html.escape(sample_id)}</h2><table><thead><tr>"
                        + "".join(f"<th>{html.escape(value)}</th>" for value in headers)
                        + "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>")
    document = ('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>翻译试样复核</title>'
                '<style>body{font-family:system-ui;margin:24px}table{border-collapse:collapse;width:100%}'
                'td,th{border:1px solid #ccc;padding:8px;white-space:pre-wrap;vertical-align:top}</style>'
                '<h1>固定日文翻译复核</h1><p>参考仅经文本上下文校对，未听音确认；不显示准确率总分。'
                'A/B/C 在各片段内打乱，仅供阅读时减少标签干扰；不能据此宣称先前评审是盲审。'
                '逐句核对否定、主体、对象、愿望/动作、术语、语气；不要逐字匹配中文参考。</p>'
                + "".join(sections) + "</html>")
    return document, {"seed": seed, "private_model_mapping": mappings, "reference_kind": "context_reviewed"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result", action="append", required=True, help="name=path; repeat per run")
    parser.add_argument("--output", type=Path, required=True, help="New private review directory")
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("review output exists; choose a new directory")
    results, inputs = {}, {}
    for item in args.result:
        name, filename = item.split("=", 1)
        if name in results:
            raise ValueError("duplicate result name")
        path = Path(filename)
        results[name] = json.loads(path.read_text(encoding="utf-8"))
        inputs[name] = {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    document, mapping = render_review(results)
    mapping["inputs"] = inputs
    args.output.mkdir(parents=True)
    (args.output / "index.html").write_text(document, encoding="utf-8")
    (args.output / "private-mapping.json").write_text(json.dumps(mapping, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Review ready: {args.output / 'index.html'}")


if __name__ == "__main__":
    main()
