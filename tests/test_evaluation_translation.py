import json
import sys
from types import SimpleNamespace

import pytest

from build_translation_review import render_review
from evaluation_translation import check_asmr_output, select_translation_input
from run_evaluation_translation import load_reference, model_input_entries, production_galtransl, run


SOURCE = [{"id": "1", "start_s": 1, "end_s": 2, "ja": "A"},
          {"id": "2", "start_s": 3, "end_s": 4, "ja": "B"}]


def test_output_times_come_from_source_not_model_claims():
    output = json.dumps([{"ids": [1, 2], "text": "译文", "start": 0, "end": 99999}])
    result = check_asmr_output(output, SOURCE)
    assert result["valid"]
    assert result["model_time_claim_errors"] == [1]
    assert result["records"][0]["start_s"] == 1
    assert result["records"][0]["end_s"] == 4


def test_valid_json_still_rejects_dropped_repeated_and_unknown_ids():
    output = json.dumps([{"ids": [1, 1, 3], "text": "译文", "start": 1000, "end": 4000}])
    result = check_asmr_output(output, SOURCE)
    assert not result["valid"]
    assert result["missing_ids"] == ["2"]
    assert result["duplicate_ids"] == ["1"]
    assert result["unknown_ids"] == ["3"]


def test_null_deletion_is_explicit_and_needs_semantic_review():
    output = json.dumps([{"ids": [1], "text": None, "start": 1000, "end": 2000},
                         {"ids": [2], "text": "译文", "start": 3000, "end": 4000}])
    result = check_asmr_output(output, SOURCE)
    assert result["valid"]
    assert result["deleted_ids_need_review"] == ["1"]
    assert result["semantic_correctness"] == "not_assessed"


def test_boolean_ids_and_malformed_json_are_rejected():
    assert not check_asmr_output("thinking then []", SOURCE)["valid"]
    assert not check_asmr_output('[{"ids":[true],"text":"译文","start":1000,"end":2000}]', SOURCE)["valid"]
    assert not check_asmr_output('[{"ids":[],"text":"译文","start":0,"end":0}]', SOURCE)["valid"]


def test_selection_loads_only_frozen_selected_samples(tmp_path):
    reference = tmp_path / "reference.json"
    reference.write_text(json.dumps({"reference_kind": "context_reviewed", "samples": [
        {"id": "selected"}, {"id": "discarded"}]}), encoding="utf-8")
    selection = tmp_path / "selected.json"
    selection.write_text(json.dumps({"reference_kind": "context_reviewed", "parts": [
        {"reference": str(reference), "samples": ["selected"]}]}), encoding="utf-8")
    loaded = load_reference(selection)
    assert [sample["id"] for sample in loaded["samples"]] == ["selected"]
    assert len(loaded["reference_hashes"][str(reference)]) == 64


def test_galtransl_arm_uses_production_batch_and_preserves_raw_trace(tmp_path):
    class FakeLlama:
        def create_chat_completion(self, **kwargs):
            return {"choices": [{"message": {"content": "第一句\n第二句"}}]}

    model = tmp_path / "mock.gguf"
    model.write_bytes(b"mock")
    result = production_galtransl(FakeLlama(), SOURCE, tmp_path / "run", model)
    assert result["status"] == "complete"
    assert [row["text"] for row in result["records"]] == ["第一句", "第二句"]
    assert len(result["calls"]) == 1
    assert result["calls"][0]["response"]["choices"][0]["message"]["content"] == "第一句\n第二句"
    assert result["records"][0]["start_s"] == 1


@pytest.mark.parametrize("layers", [-1, 0])
def test_translation_offload_policy_is_explicit_and_recorded(tmp_path, monkeypatch, layers):
    calls = []
    monkeypatch.setitem(sys.modules, "llama_cpp", SimpleNamespace(
        Llama=lambda **kwargs: calls.append(kwargs) or object(), LlamaGrammar=object()))
    monkeypatch.setattr("run_evaluation_translation.importlib.metadata.version", lambda _: "test")
    monkeypatch.setattr("run_evaluation_translation.production_galtransl",
                        lambda *args, **kwargs: {"status": "complete", "records": []})
    reference = tmp_path / "reference.json"
    reference.write_text(json.dumps({"reference_kind": "context_reviewed", "samples": [
        {"id": "clip", "standard_sample_accepted": True,
         "entries": [{"id": "1", "in_focus": True, "translation_eligible": True}]}]}), encoding="utf-8")
    model = tmp_path / "model.gguf"
    model.write_bytes(b"test")
    output = tmp_path / "result.json"
    run(SimpleNamespace(reference=reference, model=model, output=output, backend="galtransl", gpu_layers=layers,
                        context_policy="focus-only"))
    assert calls[0]["n_gpu_layers"] == layers
    assert json.loads(output.read_text(encoding="utf-8"))["provenance"]["gpu_layers_requested"] == layers


def context_sample():
    return {"id": "clip", "standard_sample_accepted": True,
            "entries": [{"id": str(i), "ja": f"日文{i}", "zh": f"译文{i}", "start_s": i, "end_s": i + .5,
                         "in_focus": i == 2, "translation_eligible": True, "status": "text_clear"} for i in range(1, 5)],
            "translation_context_review": {"cue_ids": ["1", "2", "3", "4"],
                                           "complete_dialogue_window": True, "reason": "连续问答含前后文"}}


def test_context_input_preserves_background_and_scores_only_focus():
    context, focus = select_translation_input(context_sample())
    assert [e["id"] for e in context] == ["1", "2", "3", "4"]
    assert [e["id"] for e in focus] == ["2"]


@pytest.mark.parametrize("ids", [["1", "2"], ["1", "2", "4"], ["3", "2", "1"], ["1", "2", "2"], ["1", "3", "4"]])
def test_context_rejects_short_reordered_or_gapped_windows(ids):
    sample = context_sample()
    sample["translation_context_review"]["cue_ids"] = ids
    with pytest.raises(ValueError):
        select_translation_input(sample)


def test_context_rejects_uncertain_background_not_just_focus():
    sample = context_sample()
    sample["entries"][0].update(status="unresolved", translation_eligible=False)
    with pytest.raises(ValueError, match="uncertain background"):
        select_translation_input(sample)
    assert select_translation_input(sample, "focus-only")[0][0]["id"] == "2"


def test_formal_context_fails_before_model_loading(tmp_path):
    sample = context_sample()
    sample.pop("translation_context_review")
    reference = tmp_path / "reference.json"
    reference.write_text(json.dumps({"reference_kind": "context_reviewed", "samples": [sample]}), encoding="utf-8")
    with pytest.raises(ValueError, match="reviewed dialogue context required"):
        run(SimpleNamespace(reference=reference, context_policy="reviewed-window"))


@pytest.mark.parametrize("mode", ["reviewed", "raw-asr"])
def test_formal_asmr_request_contains_context_but_not_chinese_reference(tmp_path, monkeypatch, mode):
    sample = context_sample()
    for entry in sample["entries"]:
        entry["raw_ja"] = f"原始台词{entry['id']}"
    prompts = []
    class FakeLlama:
        def create_completion(self, **kwargs):
            prompts.append(kwargs["prompt"])
            records = [{"ids": [i], "text": "中文输出", "start": i * 1000, "end": i * 1000 + 500}
                       for i in range(1, 5)]
            return {"choices": [{"text": json.dumps(records), "finish_reason": "stop"}]}
    monkeypatch.setitem(sys.modules, "llama_cpp", SimpleNamespace(
        Llama=lambda **kwargs: FakeLlama(),
        LlamaGrammar=SimpleNamespace(from_json_schema=lambda _: object())))
    monkeypatch.setattr("run_evaluation_translation.importlib.metadata.version", lambda _: "test")
    reference = tmp_path / "reference.json"
    reference.write_text(json.dumps({"reference_kind": "context_reviewed", "samples": [sample]}), encoding="utf-8")
    model = tmp_path / "model.gguf"
    model.write_bytes(b"test")
    output = tmp_path / "result.json"
    run(SimpleNamespace(reference=reference, model=model, output=output, backend="asmr", gpu_layers=-1,
                        context_policy="reviewed-window", source_mode=mode))
    field = "raw_ja" if mode == "raw-asr" else "ja"
    assert all(entry[field] in prompts[0] for entry in sample["entries"])
    if mode == "raw-asr":
        assert all(entry["ja"] not in prompts[0] for entry in sample["entries"])
    assert all(entry["zh"] not in prompts[0] for entry in sample["entries"])
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["status"] == "complete"
    assert len(result["samples"][0]["translation_input"]) == 4
    assert [entry["id"] for entry in result["samples"][0]["fixed_source"]] == ["2"]
    assert result["samples"][0]["fixed_source"][0]["ja"] == "日文2"
    assert result["provenance"]["source_mode"] == mode


def test_raw_asr_probe_does_not_rewrite_or_upgrade_frozen_reference():
    sample = context_sample()
    for entry in sample["entries"]:
        entry["raw_ja"] = "识别初稿"
    entries, _ = select_translation_input(sample)
    actual = model_input_entries(entries, "raw-asr")
    assert actual[0]["ja"] == "识别初稿"
    assert actual[0]["reviewed_ja"] == "日文1"
    assert actual[0]["input_evidence"] == "model_output"
    assert actual[0]["status"] == "model_output"
    assert not actual[0]["translation_eligible"]
    assert entries[0]["ja"] == "日文1" and entries[0]["status"] == "text_clear"


def test_raw_asr_missing_input_fails_before_model_loading(tmp_path):
    reference = tmp_path / "ref.json"
    reference.write_text(json.dumps({"reference_kind": "context_reviewed", "samples": [context_sample()]}))
    with pytest.raises(ValueError, match="preserved nonempty raw"):
        run(SimpleNamespace(reference=reference, context_policy="reviewed-window", source_mode="raw-asr"))


def test_review_displays_raw_and_reviewed_japanese_separately():
    sample = context_sample()
    for entry in sample["entries"]:
        entry["raw_ja"] = "识别初稿"
    context, focus = select_translation_input(sample)
    result = {"status": "complete", "reference_kind": "context_reviewed", "samples": [{
        "id": "clip", "fixed_source": focus, "translation_input": model_input_entries(context, "raw-asr"),
        "source_mode": "raw-asr", "context_policy": "reviewed-window", "records": []}]}
    document, _ = render_review({"one": result})
    assert "原始 ASR 输入（非真值）" in document and "上下文校对日文" in document
    assert "识别初稿" in document and "日文1" in document


def test_review_rejects_different_input_modes_even_with_identical_text():
    sample = context_sample()
    context, focus = select_translation_input(sample)
    row = {"id": "clip", "fixed_source": focus, "translation_input": context, "records": []}
    def result(mode):
        return {"status": "complete", "reference_kind": "context_reviewed", "samples": [{**row, "source_mode": mode}]}
    with pytest.raises(ValueError, match="contexts differ"):
        render_review({"one": result("reviewed"), "two": result("raw-asr")})


def test_review_rejects_matching_focus_with_different_background():
    sample = context_sample()
    context, focus = select_translation_input(sample)
    def result(entries):
        return {"status": "complete", "reference_kind": "context_reviewed", "samples": [
            {"id": "clip", "fixed_source": focus, "translation_input": entries,
             "context_policy": "reviewed-window", "records": []}]}
    altered = [dict(e) for e in context]
    altered[0]["ja"] = "另一背景"
    with pytest.raises(ValueError, match="translation contexts differ"):
        render_review({"one": result(context), "two": result(altered)})


def test_whole_window_batch_sends_background_in_the_same_production_request(tmp_path):
    requests = []
    class FakeLlama:
        def create_chat_completion(self, **kwargs):
            requests.append(kwargs)
            return {"choices": [{"message": {"content": "第一句\n第二句\n第三句\n第四句"}}]}
    entries, _ = select_translation_input(context_sample())
    for i, entry in enumerate(entries):
        entry.update(start_s=i * 30, end_s=i * 30 + 1)
    model = tmp_path / "mock.gguf"
    model.write_bytes(b"mock")
    result = production_galtransl(FakeLlama(), entries, tmp_path / "run", model, batch_size=len(entries), whole_window=True)
    assert result["status"] == "complete"
    assert len(requests) == 1
    assert all(e["ja"] in requests[0]["messages"][-1]["content"] for e in entries)


def test_whole_window_context_survives_native_split_and_line_retries(tmp_path):
    class FakeLlama:
        def create_chat_completion(self, **kwargs):
            return {"choices": [{"message": {"content": "译文"}}]}
    entries, _ = select_translation_input(context_sample())
    model = tmp_path / "mock.gguf"
    model.write_bytes(b"mock")
    result = production_galtransl(FakeLlama(), entries, tmp_path / "run", model,
                                 batch_size=len(entries), whole_window=True)
    assert len(result["calls"]) > 1
    assert all(call["full_window_context_supplied"] for call in result["calls"])


def test_review_escapes_text_keeps_source_and_rejects_different_inputs():
    source = [{"id": "1", "ja": "<script>test</script>", "zh": "参考中文"}]
    run = {"status": "complete", "reference_kind": "context_reviewed", "samples": [{"id": "V01-P01", "fixed_source": source,
                                               "records": [{"ids": ["1"], "text": "译文"}]}]}
    document, mapping = render_review({"one": run, "two": run})
    assert "<script>" not in document
    assert "&lt;script&gt;" in document
    assert set(mapping["private_model_mapping"]["V01-P01"].values()) == {"one", "two"}
    different = {"status": "complete", "reference_kind": "context_reviewed", "samples": [{"id": "V01-P01", "fixed_source": [], "records": []}]}
    with pytest.raises(ValueError, match="sources differ"):
        render_review({"one": run, "two": different})
