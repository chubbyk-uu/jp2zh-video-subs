import json
import subprocess
import sys
from pathlib import Path

import pytest

from evaluate_subtitles import render_html
from evaluation_core import Cue, SubtitleInput, compare_subtitles
from freeze_evaluation_reference import freeze
from run_evaluation_asr import artifact_hashes, cache_matches


ROOT = Path(__file__).resolve().parents[1]


def test_benchmark_default_does_not_present_consensus_as_accuracy(tmp_path):
    source = tmp_path / "source.srt"
    source.write_text("1\n00:00:01,000 --> 00:00:02,000\nはい\n", encoding="utf-8")
    output = tmp_path / "report.json"
    process = subprocess.run(
        [sys.executable, str(ROOT / "scripts/subtitle_benchmark.py"),
         "--anime-ref", f"anime={source}", "--qwen-ref", f"qwen={source}",
         "--cand", f"candidate={source}", "--json-output", str(output)],
        capture_output=True, text=True,
    )
    assert process.returncode == 0, process.stderr
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["mode"] == "evidence_aware"
    assert len(report["comparisons"]) == 2
    assert all(row["true_cer"] is None for row in report["comparisons"])
    assert "consensus-recall" not in process.stdout


def test_benchmark_missing_candidate_reports_unavailable(tmp_path):
    source = tmp_path / "source.srt"
    source.write_text("1\n00:00:01,000 --> 00:00:02,000\nはい\n", encoding="utf-8")
    output = tmp_path / "report.json"
    process = subprocess.run(
        [sys.executable, str(ROOT / "scripts/subtitle_benchmark.py"),
         "--anime-ref", f"anime={source}", "--qwen-ref", f"qwen={source}",
         "--cand", f"candidate={tmp_path / 'missing.srt'}", "--json-output", str(output)],
        capture_output=True, text=True,
    )
    assert process.returncode == 1
    rows = json.loads(output.read_text(encoding="utf-8"))["comparisons"]
    assert all(row["status"] == "unavailable" and row["text_difference"] is None for row in rows)


def test_html_escapes_subtitle_text_and_audio_attributes():
    source = SubtitleInput("valid", [Cue("1", 0, 1, '<script>alert("x")</script>')], [])
    document = render_html(compare_subtitles(source, source, "context_reviewed"), 'x" onerror="alert(1)')
    assert "<script>" not in document
    assert "&lt;script&gt;" in document
    assert 'src="x&quot; onerror=&quot;alert(1)"' in document


@pytest.mark.parametrize("selection", [["unknown"], ["known", "known"], []])
def test_freeze_rejects_invalid_selection_without_creating_reference(tmp_path, selection):
    (tmp_path / "manifest.json").write_text(json.dumps({"samples": [{"id": "known"}]}), encoding="utf-8")
    decisions = tmp_path / "decisions.json"
    decisions.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError):
        freeze(tmp_path, decisions, selected_samples=selection)
    assert not (tmp_path / "reference-v1").exists()


def test_pilot_cache_checks_raw_and_split_subtitles_as_well_as_combined(tmp_path):
    for name in ("combined.srt", "raw.json", "V01-P01.srt"):
        (tmp_path / name).write_text("initial", encoding="utf-8")
    record = {"status": "complete", "fingerprint": "same",
              "artifact_sha256": artifact_hashes(tmp_path, ["V01-P01"])}
    assert cache_matches(record, "same", tmp_path, ["V01-P01"])
    (tmp_path / "V01-P01.srt").write_text("changed", encoding="utf-8")
    assert not cache_matches(record, "same", tmp_path, ["V01-P01"])
    (tmp_path / "raw.json").unlink()
    assert not cache_matches(record, "same", tmp_path, ["V01-P01"])


def reference_fixture(directory, status):
    (directory / "manifest.json").write_text(json.dumps({"fingerprint": "input", "samples": [
        {"id": "V01-P01", "start_s": 1, "end_s": 3, "context_start_s": 0}]}), encoding="utf-8")
    for name in ("primary", "alternate"):
        run = directory / "runs" / name
        run.mkdir(parents=True)
        (run / "V01-P01.srt").write_text("1\n00:00:00,000 --> 00:00:00,900\n背景\n\n"
                                         "2\n00:00:01,000 --> 00:00:02,000\nはい\n", encoding="utf-8")
    review = directory / "review"
    review.mkdir()
    (review / "V01-P01.json").write_text('{"groups":[]}', encoding="utf-8")
    decisions = {"primary_run": "primary", "alternate_run": "alternate", "review_scope": "focus",
                 "unlisted_context_policy": "unresolved_not_scored",
                 "samples": {"V01-P01": {"2": {"status": status, "zh": "好的"}}}}
    path = directory / "decisions.json"
    path.write_text(json.dumps(decisions), encoding="utf-8")
    return path, decisions


def test_freeze_accepts_clear_focus_but_does_not_score_unreviewed_background(tmp_path):
    path, _ = reference_fixture(tmp_path, "text_clear")
    freeze(tmp_path, path, require_clear_focus=True)
    result = json.loads((tmp_path / "reference-v1/reference.json").read_text(encoding="utf-8"))
    sample = result["samples"][0]
    assert sample["standard_sample_accepted"]
    assert sample["focus_cue_ids"] == ["2"]
    assert sample["entries"][0]["status"] == "unresolved"
    assert not sample["entries"][0]["translation_eligible"]
    assert not result["audio_verified"]


@pytest.mark.parametrize("status", ["possible", "unresolved"])
def test_freeze_rejects_uncertain_focus_and_preserves_candidate_for_reselection(tmp_path, status):
    path, _ = reference_fixture(tmp_path, status)
    with pytest.raises(ValueError, match="discard and select a replacement"):
        freeze(tmp_path, path, require_clear_focus=True)
    assert not (tmp_path / "reference-v1").exists()
    assert (tmp_path / "runs/primary/V01-P01.srt").exists()


def test_freeze_rejects_evidence_for_a_different_original(tmp_path):
    path, decisions = reference_fixture(tmp_path, "high_confidence_change")
    decisions["samples"]["V01-P01"]["2"].update(ja="いいえ", evidence={
        "raw": "different", "proposal": "いいえ", "source_trace": "reason", "original_failure": "reason",
        "context": "reason", "alternatives": "reason"})
    path.write_text(json.dumps(decisions), encoding="utf-8")
    with pytest.raises(ValueError, match="does not match"):
        freeze(tmp_path, path, require_clear_focus=True)
