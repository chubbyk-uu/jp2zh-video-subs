"""Compare clip subtitles with explicit reference evidence, without a quality total."""
from __future__ import annotations

import argparse
import html
import json
from pathlib import Path

from evaluation_core import REFERENCE_KINDS, compare_subtitles, load_subtitles


def render_html(result: dict, audio: str | None = None) -> str:
    def escape(value):
        return html.escape(str(value), quote=True)

    player = f'<audio controls preload="metadata" src="{escape(audio)}"></audio>' if audio else ""
    rows = []
    for group in result["groups"]:
        rows.append("<tr>" + "".join(f"<td>{escape(group.get(key))}</td>" for key in
                                     ("status", "reference_ids", "candidate_ids", "reference_text", "candidate_text", "start_delta_s", "end_delta_s")) + "</tr>")
    return f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<title>字幕参考差异复核</title><style>body{{font-family:system-ui;margin:24px}}table{{border-collapse:collapse;width:100%}}
td,th{{border:1px solid #ccc;padding:8px;white-space:pre-wrap}}pre{{white-space:pre-wrap}}audio{{width:100%}}</style>
<h1>字幕参考差异复核</h1><p>参考证据：{escape(result['reference_kind'])}；状态：{escape(result['status'])}</p>
<p>文本差异与边界差异的含义由参考证据决定；上下文校对稿及模型输出不构成听音真值。</p>
{player}<pre>{escape(json.dumps({k:v for k,v in result.items() if k != 'groups'}, ensure_ascii=False, indent=2))}</pre>
<table><thead><tr><th>状态</th><th>参考 ID</th><th>候选 ID</th><th>参考原文</th><th>候选原文</th><th>起点差</th><th>终点差</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table></html>'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--reference-kind", choices=REFERENCE_KINDS, default="model_output")
    parser.add_argument("--boundaries-verified", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--html", type=Path)
    parser.add_argument("--audio", help="Audio URL relative to the HTML file, or an absolute local path")
    args = parser.parse_args()
    result = compare_subtitles(load_subtitles(args.reference), load_subtitles(args.candidate),
                               args.reference_kind, boundaries_verified=args.boundaries_verified)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.html:
        args.html.parent.mkdir(parents=True, exist_ok=True)
        args.html.write_text(render_html(result, args.audio), encoding="utf-8")
    print(f"{result['status']}: reference={result['reference_kind']}; true_cer={result['true_cer']}")
    if result["status"] != "evaluated":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
