import importlib
import sys

import pytest

from translation_common import parse_srt


class Completions:
    def __init__(self, outputs):
        self.outputs = iter(outputs)

    def create_chat_completion(self, **kwargs):
        return {"choices": [{"message": {"content": next(self.outputs)}}]}


def run_translator(monkeypatch, tmp_path, backend, sources, completions, *extra):
    module = importlib.import_module(f"translate_srt_{backend}")
    source = tmp_path / "input.srt"
    output = tmp_path / "output.srt"
    model = tmp_path / "stub.gguf"
    model.touch()
    source.write_text("".join(
        f"{index}\n00:00:{index * 3:02},000 --> 00:00:{index * 3 + 1:02},000\n{text}\n\n"
        for index, text in enumerate(sources, 1)
    ), encoding="utf-8")
    llm = Completions(completions)
    monkeypatch.setattr(module, "Llama", lambda **kwargs: llm)
    monkeypatch.setattr(sys, "argv", [
        "translate", str(source), "--output", str(output), "--model-path", str(model),
        "--lead-out-seconds", "0", "--min-display-seconds", "0", *extra,
    ])
    module.main()
    entries = parse_srt(output)
    assert [(e.index, e.start, e.end) for e in entries] == [
        (str(i), float(i * 3), float(i * 3 + 1)) for i in range(1, len(sources) + 1)
    ]
    return entries, output


def test_galtransl_overflow_fallback_keeps_cue_ownership(monkeypatch, tmp_path):
    entries, _ = run_translator(
        monkeypatch, tmp_path, "galtransl", ["今日は雨ですが、出かけます。", "明日は休みです。"],
        ["今天下雨，\n但我还是要出门。\n明天休息。", "今天下雨，\n但我还是要出门。", "明天休息。"],
        "--batch-size", "2",
    )
    assert [e.text for e in entries] == ["今天下雨，但我还是要出门。", "明天休息。"]


@pytest.mark.parametrize("backend", ["galtransl", "sakura"])
def test_unresolved_terms_reach_report_without_corruption(monkeypatch, tmp_path, backend):
    entries, output = run_translator(
        monkeypatch, tmp_path, backend, ["契約を結ぶ。"], ["缔结契约。", "缔结契约。"],
    )
    assert entries[0].text == "缔结契约。"
    report = output.with_suffix(".terms.txt").read_text(encoding="utf-8")
    assert "[1]" in report and "缔结契约。" in report and "契約->合同" in report


@pytest.mark.parametrize("backend", ["galtransl", "sakura", "sugoi"])
def test_cli_retries_ambiguous_body_and_preserves_multiline(monkeypatch, tmp_path, backend):
    english = backend == "sugoi"
    text = "It is raining.\nLet's go tomorrow." if english else "今天下雨。\n明天再去吧。"
    replies = ["Hello.\nExplanation: a greeting." if english else "你好。\n解释：这是问候语。", text]
    if english:
        replies.insert(0, "invalid batch")  # Sugoi first tries numbered batch mode.
    entries, _ = run_translator(monkeypatch, tmp_path, backend, ["雨です。明日行きましょう。"], replies)
    assert entries[0].text == ("It is raining. Let's go tomorrow." if english else "今天下雨。明天再去吧。")
