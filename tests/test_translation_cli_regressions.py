import importlib
import json
import sys

import pytest

from translation_common import parse_srt, review_chinese_translation, vocalisation_fallback


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


@pytest.mark.parametrize("backend", ["galtransl", "sakura"])
def test_empty_translation_marks_review_and_continues(monkeypatch, tmp_path, backend):
    extra = ("--batch-size", "1") if backend == "galtransl" else ()
    entries, output = run_translator(monkeypatch, tmp_path, backend,
                                    ["こんにちは。", "何をしている？", "さようなら。"],
                                    ["你好。", "", "", "再见。"], *extra)
    assert [e.text for e in entries] == ["你好。", "【翻译待复核】", "再见。"]
    review = json.loads(output.with_suffix(".review.json").read_text(encoding="utf-8"))
    assert review["review_count"] == 1
    assert review["cues"][0]["id"] == "2"
    assert review["cues"][0]["source"] == "何をしている？"
    assert review["cues"][0]["candidate"] == ""
    assert review["cues"][0]["action"] == "review_placeholder"
    assert not list(tmp_path.glob("*.part"))


@pytest.mark.parametrize("backend", ["galtransl", "sakura"])
@pytest.mark.parametrize("source,invalid,expected,issue", [
    ("ぃぃ…", "ぃぃ…", "咿咿…", "kana_residue"),
    ("ミクに会った。", "见到了ミク。", "见到了ミク。", "kana_residue"),
    ("こんにちは。", "好" * 60, "【翻译待复核】", "degenerate"),
])
def test_persistent_quality_risks_keep_cue_and_record_review(monkeypatch, tmp_path, backend, source, invalid, expected, issue):
    extra = ("--batch-size", "1") if backend == "galtransl" else ()
    # Both translators use three attempts for kana, two for degeneration.
    attempts = 3 if issue == "kana_residue" else 2
    entries, output = run_translator(monkeypatch, tmp_path, backend,
                                    [source, "さようなら。"], [invalid] * attempts + ["再见。"], *extra)
    assert [e.text for e in entries] == [expected, "再见。"]
    review = json.loads(output.with_suffix(".review.json").read_text(encoding="utf-8"))
    assert review["review_count"] == 1
    assert review["cues"][0]["candidate"] == invalid
    assert issue in review["cues"][0]["issues"]
    assert review["cues"][0]["source"] == source


@pytest.mark.parametrize("source", ["いい。", "はい！", "うん", "ううん。", "ええ", "会いたい。",
                                    "ハイ", "はいはい", "イイ", "いい、いい"])
def test_vocalisation_fallback_does_not_invent_lexical_dialogue(source):
    assert vocalisation_fallback(source) is None


def test_source_supported_repetition_is_retained_for_review(tmp_path):
    from translation_common import Entry
    entry = Entry("1", "00:00:00,000 --> 00:00:01,000", "だめ" * 10, 0, 1)
    rows = []
    translated = "不行" * 10
    assert review_chinese_translation(entry, translated, rows) == translated
    assert rows[0]["action"] == "retained_source_repetition"


@pytest.mark.parametrize("backend", ["galtransl", "sakura"])
def test_clean_rerun_clears_previous_review(monkeypatch, tmp_path, backend):
    run_translator(monkeypatch, tmp_path, backend, ["ぃぃ…"], ["ぃぃ…"] * 3)
    entries, output = run_translator(monkeypatch, tmp_path, backend, ["こんにちは。"], ["你好。"])
    assert entries[0].text == "你好。"
    assert json.loads(output.with_suffix(".review.json").read_text(encoding="utf-8"))["review_count"] == 0


def test_sugoi_exhausted_quality_retries_continue_remaining_cues(monkeypatch, tmp_path):
    entries, output = run_translator(monkeypatch, tmp_path, "sugoi", ["こんにちは。", "さようなら。"],
                                    ["[001] こんにちは。", "こんにちは。", "こんにちは。", "[001] こんにちは。",
                                     "[001] Goodbye."], "--batch-size", "1")
    assert [e.text for e in entries] == ["[Translation needs review]", "Goodbye."]
    assert json.loads(output.with_suffix(".review.json").read_text(encoding="utf-8"))["review_count"] == 1


@pytest.mark.parametrize("backend", ["galtransl", "sakura"])
def test_real_model_exception_preserves_previous_output(monkeypatch, tmp_path, backend):
    output = tmp_path / "output.srt"
    output.write_text("previous output", encoding="utf-8")
    # The stub model runs out of responses: a model failure must still fail the job.
    with pytest.raises(StopIteration):
        run_translator(monkeypatch, tmp_path, backend, ["こんにちは。", "さようなら。"],
                       ["你好。"], *(("--batch-size", "1") if backend == "galtransl" else ()))
    assert output.read_text(encoding="utf-8") == "previous output"
    assert not list(tmp_path.glob("*.part"))
