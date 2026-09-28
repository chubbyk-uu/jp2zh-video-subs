"""Experimental ASMR translation protocol with checked IDs and source-owned times."""
from __future__ import annotations

import json

from evaluation_core import validate_translation_ids


def select_translation_input(sample: dict, policy: str = "reviewed-window") -> tuple[list[dict], list[dict]]:
    """Keep scored cues fixed; require a reviewed, contiguous multi-cue input."""
    entries = sample["entries"]
    focus = [entry for entry in entries if entry["in_focus"]]
    if (not sample["standard_sample_accepted"] or not focus
            or any(not entry["translation_eligible"] for entry in focus)):
        raise ValueError(f"{sample['id']}: uncertain/empty focus")
    if policy == "focus-only":
        return focus, focus
    if policy != "reviewed-window":
        raise ValueError("unknown translation context policy")
    review = sample.get("translation_context_review", {})
    if (review.get("complete_dialogue_window") is not True
            or not isinstance(review.get("reason"), str) or not review["reason"].strip()):
        raise ValueError(f"{sample['id']}: reviewed dialogue context required")
    ids = review.get("cue_ids")
    all_ids = [entry["id"] for entry in entries]
    if (not isinstance(ids, list) or len(ids) < 3 or any(not isinstance(id_, str) for id_ in ids)
            or len(set(ids)) != len(ids) or len(set(all_ids)) != len(all_ids)
            or not set(ids) <= set(all_ids)):
        raise ValueError(f"{sample['id']}: at least three unique context cue IDs required")
    positions = [all_ids.index(id_) for id_ in ids]
    if positions != list(range(positions[0], positions[0] + len(ids))):
        raise ValueError(f"{sample['id']}: context must be contiguous and ordered; do not skip uncertain dialogue")
    context = entries[positions[0]:positions[-1] + 1]
    if not {entry["id"] for entry in focus} <= set(ids):
        raise ValueError(f"{sample['id']}: context must include every focus cue")
    if any(not entry["translation_eligible"] or entry["status"] not in ("text_clear", "high_confidence_change")
           for entry in context):
        raise ValueError(f"{sample['id']}: uncertain background inside translation context; select another sample")
    return context, focus


def asmr_prompt(entries: list[dict], sample_id: str) -> str:
    rows = [{"id": int(e["id"]), "text": e["ja"], "start": round(e["start_s"] * 1000),
             "end": round(e["end_s"] * 1000)} for e in entries]
    # Retain the author's task/protocol. Corrections made by the model are still
    # judged against the frozen Japanese input, not fed back into the reference.
    return ("将以下日语ASMR逐字稿翻译成简体中文。\n\n"
            f"音轨：{sample_id}\n场景说明：同一片段中按时间排列的对白。\n\n"
            '术语表（请严格使用zh栏位的译名）：\n{"cvs":[],"characters":[],"terms":[]}\n\n'
            "翻译前请静默修正以下Whisper识别错误：\n"
            "- 重复片语（连续3次以上且无变化）：仅保留一次\n"
            "- 错字／同音异字：依上下文修正\n"
            "- 字幕版权行（字幕：／翻訳：／QQ／LINE水印）：text设为null\n"
            "- 错误专有名词：依术语表修正\n\n"
            "翻译规则：\n- 呻吟与气息声（あ、ん、はあ）→ 自然对应（啊、嗯、哈、呼）\n"
            "- 拟声词：日语形式翻译（パンパン→啪啪）；中文形式保留原样\n"
            "- 保留角色语气与口吻\n- text字段只输出译文，不加注释或括号说明\n\n"
            '输入：逐字稿JSON数组 — {"id":<n>,"text":"<日文>","start":<ms>,"end":<ms>}\n'
            '输出：将连续构成同一句话的片段合并，JSON数组格式：{"ids":[<n>,...],"text":"<简体中文>","start":<最早ms>,"end":<最晚ms>}\n'
            '字幕版权行：{"ids":[<n>],"text":null,"start":<ms>,"end":<ms>}\n'
            "每个输入id必须恰好出现在一个输出项中。\n\n逐字稿：\n"
            + json.dumps(rows, ensure_ascii=False))


def qwen_no_thinking_prompt(user: str) -> str:
    return f"<|im_start|>user\n{user}<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n"


def translation_schema() -> dict:
    return {"type": "array", "minItems": 1, "items": {"type": "object", "additionalProperties": False,
            "properties": {"ids": {"type": "array", "minItems": 1, "items": {"type": "integer"}},
                           "text": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                           "start": {"type": "integer"}, "end": {"type": "integer"}},
            "required": ["ids", "text", "start", "end"]}}


def check_asmr_output(raw: str, entries: list[dict]) -> dict:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {"valid": False, "issues": ["invalid JSON"], "records": []}
    if not isinstance(data, list):
        return {"valid": False, "issues": ["expected JSON array"], "records": []}
    normalized, issues = [], []
    for number, record in enumerate(data, 1):
        if not isinstance(record, dict) or set(record) != {"ids", "text", "start", "end"}:
            issues.append(f"record {number}: expected exactly ids/text/start/end")
            continue
        ids = record["ids"]
        if not isinstance(ids, list) or not ids or any(not isinstance(value, int) or isinstance(value, bool) for value in ids):
            issues.append(f"record {number}: nonempty integer IDs required")
            continue
        if any(not isinstance(record[key], int) or isinstance(record[key], bool) for key in ("start", "end")):
            issues.append(f"record {number}: integer milliseconds required")
            continue
        normalized.append({**record, "ids": [str(value) for value in ids]})
    structure = validate_translation_ids([e["id"] for e in entries], normalized)
    issues.extend(structure["issues"])
    source = {e["id"]: e for e in entries}
    derived, time_claim_errors = [], []
    for number, record in enumerate(normalized, 1):
        if not all(id_ in source for id_ in record["ids"]):
            continue
        start = min(source[id_]["start_s"] for id_ in record["ids"])
        end = max(source[id_]["end_s"] for id_ in record["ids"])
        if record["start"] != round(start * 1000) or record["end"] != round(end * 1000):
            time_claim_errors.append(number)
        derived.append({"ids": record["ids"], "text": record["text"], "start_s": start, "end_s": end})
    return {**structure, "valid": not issues, "issues": issues, "records": derived,
            "model_time_claim_errors": time_claim_errors, "timing_policy": "derive from immutable source IDs"}
