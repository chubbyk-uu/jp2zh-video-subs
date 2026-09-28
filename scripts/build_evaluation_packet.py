"""Make a local pilot review packet from two preserved ASR runs."""
from __future__ import annotations

import argparse
import html
import json
from pathlib import Path

from evaluate_subtitles import render_html
from evaluation_core import compare_subtitles, load_subtitles


def build_packet(pilot: Path, run_a: str, run_b: str):
    manifest = json.loads((pilot / "manifest.json").read_text(encoding="utf-8"))
    output = pilot / "review"
    output.mkdir(parents=True, exist_ok=True)
    sheet, links, records = [], [], []
    sheet.extend(["# 试样上下文校对工作表", "", "以下是基线模型初稿，不是听音真值；分组以锁定清单为准，保留集不得用于调参。", ""])
    for sample in manifest["samples"]:
        a_path = pilot / "runs" / run_a / f"{sample['id']}.srt"
        b_path = pilot / "runs" / run_b / f"{sample['id']}.srt"
        a, b = load_subtitles(a_path), load_subtitles(b_path)
        result = compare_subtitles(a, b, "model_output")
        result["sample_id"] = sample["id"]
        result["split"] = sample.get("split", "development")
        result["scene_group"] = sample.get("scene_group")
        result["scene_grouping_evidence"] = sample.get("scene_grouping_evidence")
        result["focus_start_s"] = sample["start_s"] - sample["context_start_s"]
        result["focus_end_s"] = sample["end_s"] - sample["context_start_s"]
        filename = f"{sample['id']}.html"
        (output / filename).write_text(render_html(result, f"../{sample['audio']}"), encoding="utf-8")
        (output / f"{sample['id']}.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        links.append(f'<li><a href="{html.escape(filename)}">{html.escape(sample["id"])}</a></li>')
        sheet.extend([f"## {sample['id']} / 原视频 {sample['start_s']:.2f}–{sample['end_s']:.2f}s", "",
                      f"分组：{sample.get('split', 'development')}；场景组：{sample.get('scene_group', '未设置')}。", "",
                      f"重点区间为上下文音频的 {result['focus_start_s']:.2f}–{result['focus_end_s']:.2f}s。", ""])
        for label, parsed in (("A", a), ("B", b)):
            sheet.extend([f"### 初稿 {label} / {parsed.status}", ""])
            for cue in parsed.cues:
                sheet.append(f"- {cue.index} [{cue.start:.2f}–{cue.end:.2f}] {cue.text}")
            sheet.append("")
        records.append({"sample_id": sample["id"], "a_input": a.summary(), "b_input": b.summary(),
                        "split": result["split"], "scene_group": result["scene_group"],
                        "scene_grouping_evidence": result["scene_grouping_evidence"],
                        "reference_kind": "model_output", "status": "pending_context_review",
                        "focus_start_s": result["focus_start_s"], "focus_end_s": result["focus_end_s"]})
    (output / "sheet.md").write_text("\n".join(sheet) + "\n", encoding="utf-8")
    (output / "index.html").write_text('<!doctype html><meta charset="utf-8"><title>试样复核</title>'
                                       f'<h1>{len(records)} 段参考候选复核</h1><p>A/B 为基线初稿，未做听音确认；保留集不用于调参。</p><ul>'
                                       + "".join(links) + "</ul>", encoding="utf-8")
    (output / "packet.json").write_text(json.dumps({"schema_version": 1, "private_model_mapping": {"A": run_a, "B": run_b},
                                                    "samples": records}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Review packet ready: {output / 'sheet.md'}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pilot", type=Path, required=True)
    parser.add_argument("--run-a", default="baseline-anime")
    parser.add_argument("--run-b", default="baseline-qwen")
    args = parser.parse_args()
    build_packet(args.pilot, args.run_a, args.run_b)


if __name__ == "__main__":
    main()
