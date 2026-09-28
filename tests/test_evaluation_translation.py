import json

import pytest

from build_translation_review import render_review
from evaluation_translation import check_asmr_output
from run_evaluation_translation import load_reference, production_galtransl


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
