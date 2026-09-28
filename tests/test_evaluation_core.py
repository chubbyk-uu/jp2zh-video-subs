import json

import pytest

from evaluation_core import (
    Cue, SubtitleInput, align_cue_groups, cache_fingerprint, character_errors,
    compare_subtitles, full_span_gaps, load_subtitles, normalize_text, validate_translation_ids,
)


def valid(*cues):
    return SubtitleInput("valid", list(cues), [])


def test_long_vowels_negation_and_legitimate_repetition_survive_normalization():
    assert normalize_text("コーヒー。行かない！行く、行く。") == "コーヒー行かない行く行く"
    assert character_errors("はい", "はいはいはい")["insertions"] == 4
    assert character_errors("はい", "はいはいはい")["rate"] == 2.0
    assert character_errors("行かない", "行く")["edits"] > 0


def test_error_counts_distinguish_deletions_and_insertions():
    assert character_errors("ABC", "AB")["deletions"] == 1
    assert character_errors("ABC", "ABCD")["insertions"] == 1
    assert character_errors("ABC", "AXC")["substitutions"] == 1
    assert character_errors("", "AB")["rate"] is None


@pytest.mark.parametrize("kind", ["model_output", "context_reviewed"])
def test_reference_agreement_does_not_create_truth(kind):
    source = valid(Cue("1", 0, 1, "違う"))
    result = compare_subtitles(source, source, kind)
    assert result["true_cer"] is None
    assert result["timing_accuracy"] is None
    assert result["text_difference"]["normalized"]["rate"] == 0


def test_empty_candidate_counts_missing_short_reply_not_perfect_score():
    result = compare_subtitles(valid(Cue("1", 1, 2, "はい")), SubtitleInput("empty", [], []), "audio_verified")
    assert result["true_cer"]["deletions"] == 2
    assert result["true_cer"]["rate"] == 1


def test_missing_candidate_is_not_empty_and_no_score(tmp_path):
    source = valid(Cue("1", 0, 1, "はい"))
    result = compare_subtitles(source, load_subtitles(tmp_path / "missing.srt"), "audio_verified")
    assert result["status"] == "unavailable"
    assert result["true_cer"] is None
    assert result["text_difference"] is None


def test_parse_statuses_report_partial_corruption_and_duplicate_ids(tmp_path):
    path = tmp_path / "x.srt"
    path.write_text("", encoding="utf-8")
    assert load_subtitles(path).status == "empty"
    path.write_text("1\n00:00:01,000 --> 00:00:02,000\nはい\n\nbad\n", encoding="utf-8")
    assert load_subtitles(path).status == "partial_invalid"
    path.write_text("1\n00:00:01,000 --> 00:00:02,000\nはい\n\n1\n00:00:03,000 --> 00:00:04,000\nいいえ\n", encoding="utf-8")
    assert load_subtitles(path).status == "partial_invalid"


def test_split_and_merge_are_content_equivalent_and_use_each_cue_once():
    ref = valid(Cue("1", 0, 2, "こんにちは"), Cue("2", 2, 4, "帰ります"))
    cand = valid(Cue("a", 0, 4, "こんにちは帰ります"))
    result = compare_subtitles(ref, cand, "audio_verified", boundaries_verified=True)
    assert result["true_cer"]["rate"] == 0
    assert result["groups"][0]["reference_ids"] == ["1", "2"]
    assert result["boundary_difference"]["exact_groups"] == 1
    assert result["timing_accuracy"]["start"]["mae_s"] == 0


def test_time_shift_does_not_borrow_neighbor_text_or_hide_timing_error():
    ref = valid(Cue("1", 0, 1, "最初です"), Cue("2", 2, 3, "最後です"))
    cand = valid(Cue("1", 2, 3, "最初です"), Cue("2", 4, 5, "最後です"))
    result = compare_subtitles(ref, cand, "audio_verified", boundaries_verified=True)
    assert result["true_cer"]["rate"] == 0
    assert result["timing_accuracy"]["start"]["mae_s"] == 2
    assert result["timing_accuracy"]["end"]["p95_abs_s"] == 2


def test_reordered_dialogue_is_not_a_bag_of_words_match():
    ref = valid(Cue("1", 0, 1, "帰ります"), Cue("2", 2, 3, "待って"))
    cand = valid(Cue("1", 0, 1, "待って"), Cue("2", 2, 3, "帰ります"))
    assert compare_subtitles(ref, cand, "audio_verified")["true_cer"]["edits"] > 0


def test_group_alignment_does_not_reuse_a_candidate_for_repeated_reference():
    groups = align_cue_groups([Cue("1", 0, 1, "はい"), Cue("2", 3, 4, "はい")], [Cue("a", 0, 1, "はい")])
    assert [id_ for g in groups for id_ in g["candidate_ids"]] == ["a"]
    assert sum(g["status"] == "missing_reference_text" for g in groups) == 1


def test_full_audio_gaps_cover_leading_trailing_and_empty_output():
    assert [(g.start, g.end) for g in full_span_gaps([], 10)] == [(0, 10)]
    cues = [Cue("1", 2, 4, "A"), Cue("2", 3, 5, "B")]
    assert [(g.start, g.end) for g in full_span_gaps(cues, 10)] == [(0, 2), (5, 10)]


def test_translation_merge_delete_and_error_protocol():
    ok = validate_translation_ids(["1", "2", "3"], [{"ids": ["1", "2"], "text": "译文"}, {"ids": ["3"], "text": None}])
    assert ok["valid"]
    assert ok["deleted_ids_need_review"] == ["3"]
    assert ok["semantic_correctness"] == "not_assessed"
    wrong = validate_translation_ids(["1", "2", "3"], [{"ids": ["1", "3"], "text": "译文"}, {"ids": ["1", "4"], "text": ""}])
    assert not wrong["valid"]
    assert wrong["missing_ids"] == ["2"]
    assert wrong["unknown_ids"] == ["4"]
    assert wrong["duplicate_ids"] == ["1"]


def test_cache_identity_changes_with_weights_input_or_parameters():
    provenance = {"input_sha256": "input", "model_sha256": "model", "config": {"beam": 1}, "runtime": "version"}
    digest = cache_fingerprint(provenance)
    assert cache_fingerprint(json.loads(json.dumps(provenance))) == digest
    for key in ("input_sha256", "model_sha256", "runtime"):
        assert cache_fingerprint({**provenance, key: "different"}) != digest
    assert cache_fingerprint({**provenance, "config": {"beam": 4}}) != digest
