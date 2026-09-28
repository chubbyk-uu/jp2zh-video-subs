import copy
import random

import pytest

from evaluation_core import Cue
from plan_evaluation_expansion import (
    locked_assignments, merge_source_metadata, overlaps, plan_long_windows, plan_windows, verify_corpus, verify_prior_chain,
)


def dense_cues(duration=9000):
    return [Cue(str(i), i * 3, i * 3 + 2, "何事も挑戦だよ。") for i in range(int(duration / 3))]


def test_expansion_locks_whole_groups_and_excludes_previous_context():
    previous = [(100, 160), (2700, 2760), (6100, 6160)]
    windows = plan_windows(dense_cues(), 9000, previous, random.Random(7))
    assert len(windows) == 15
    assert sum(w["split"] == "heldout" for w in windows) == 6
    assigned = {}
    for window in windows:
        group = window["temporal_group"]
        assert assigned.setdefault(group, window["split"]) == window["split"]
        assert not overlaps(window["start_s"] - 15, window["end_s"] + 15,
                            [(lo - 120, hi + 120) for lo, hi in previous])
        assert window["start_s"] >= group * 1200 + 120
        assert window["end_s"] + 15 <= min(9000, (group + 1) * 1200) - 120
        if window["split"] == "heldout":
            assert not overlaps(group * 1200, min(9000, (group + 1) * 1200),
                                [(lo - 120, hi + 120) for lo, hi in previous])


def test_expansion_seed_is_reproducible_without_model_predictions():
    assert plan_windows(dense_cues(), 9000, [], random.Random(9)) == plan_windows(dense_cues(), 9000, [], random.Random(9))


def test_expansion_fails_instead_of_leaking_when_no_unseen_groups_exist():
    with pytest.raises(ValueError, match="insufficient unseen"):
        plan_windows(dense_cues(), 9000, [(0, 9000)], random.Random(7))


def locked_fixture():
    sample = {"id": "V01-E01", "video_id": "V01", "split": "heldout", "scene_group": "V01-T04",
              "scene_grouping_evidence": "temporal_proxy_pending_context_review", "start_s": 5000, "end_s": 5020}
    source = {"id": "V01", "sha256": "video-hash", "subtitles": {"anime": {"sha256": "ass-hash"}}}
    return {"samples": [copy.deepcopy(sample)]}, {"samples": [sample], "sources": [source]}, {"V01": copy.deepcopy(source)}


def test_verify_prepared_corpus_preserves_locked_split():
    lock, manifest, prior = locked_fixture()
    assert verify_corpus(lock, manifest, prior) == 1
    manifest["samples"][0]["split"] = "development"
    with pytest.raises(ValueError, match="differs from split lock"):
        verify_corpus(lock, manifest, prior)


def test_verify_rejects_duplicate_samples_and_changed_source():
    lock, manifest, prior = locked_fixture()
    manifest["samples"] *= 2
    with pytest.raises(ValueError, match="duplicates"):
        verify_corpus(lock, manifest, prior)
    manifest["samples"] = manifest["samples"][:1]
    manifest["sources"][0]["sha256"] = "modified"
    with pytest.raises(ValueError, match="source video differs"):
        verify_corpus(lock, manifest, prior)


def test_verify_rejects_missing_subtitle_evidence():
    lock, manifest, prior = locked_fixture()
    manifest["sources"][0]["subtitles"].clear()
    with pytest.raises(ValueError, match="subtitle sources differ"):
        verify_corpus(lock, manifest, prior)


def test_long_windows_reuse_splits_and_protect_full_context():
    cues = [Cue(str(i), i * 5, i * 5 + 3, "私にしてほしいなら、それはしないで。") for i in range(960)]
    assignments = {0: "development", 1: "heldout", 2: "development", 3: "heldout"}
    previous = [(1400, 1550)]
    windows, audit = plan_long_windows(cues, 4800, previous, assignments, random.Random(4))
    assert len(windows) == 8
    assert audit["selected_per_split"] == {"heldout": 4, "development": 4}
    for w in windows:
        assert w["split"] == assignments[w["temporal_group"]]
        assert w["end_s"] - w["start_s"] == 40
        assert not overlaps(w["start_s"] - 35, w["end_s"] + 35, [(1280, 1670)])
        assert w["start_s"] - 35 >= w["temporal_group"] * 1200 + 120
        assert w["end_s"] + 35 <= (w["temporal_group"] + 1) * 1200 - 120
    assert (windows, audit) == plan_long_windows(cues, 4800, previous, assignments, random.Random(4))


def test_long_windows_report_deficit_without_reassigning_groups():
    cues = [Cue(str(i), i * 5, i * 5 + 3, "私にしてほしいなら、それはしないで。") for i in range(240)]
    windows, audit = plan_long_windows(cues, 1200, [], {0: "development"}, random.Random(4))
    assert windows and all(w["split"] == "development" for w in windows)
    assert audit["requested_per_split"]["heldout"] == 4
    assert audit["selected_per_split"].get("heldout", 0) == 0
    assert not plan_long_windows(cues, 1200, [], {}, random.Random(4))[0]


def test_long_windows_reject_easy_and_sparse_dialogue_hints():
    assert not plan_long_windows(dense_cues(4800), 4800, [], {0: "development"}, random.Random(4))[0]
    cues = [Cue(str(i), i * 100, i * 100 + 3, "私にしてほしいなら、それはしないで。") for i in range(48)]
    assert not plan_long_windows(cues, 4800, [], {0: "heldout"}, random.Random(4))[0]


def test_parent_assignments_reject_conflicting_groups():
    sample = {"video_id": "V01", "temporal_group": 4, "split": "heldout"}
    assert locked_assignments({"samples": [sample]}) == {"V01": {4: "heldout"}}
    with pytest.raises(ValueError, match="conflicting"):
        locked_assignments({"samples": [sample, {**sample, "split": "development"}]})


def test_long_expansion_cannot_forget_previously_viewed_ancestors():
    parent = {"previous_manifests": {"old.json": "sha-old", "replacements.json": "sha-replacements"}}
    verify_prior_chain(parent, {"old.json": "sha-old", "replacements.json": "sha-replacements", "parent.json": "sha-parent"})
    for supplied in ({"old.json": "sha-old"}, {"old.json": "changed", "replacements.json": "sha-replacements"}):
        with pytest.raises(ValueError, match="ancestor manifests"):
            verify_prior_chain(parent, supplied)


@pytest.mark.parametrize("field", ["sha256", "duration_s", "subtitles"])
def test_source_identity_cannot_be_replaced_by_last_manifest(field):
    source = {"id": "V01", "sha256": "video-hash", "duration_s": 9000,
              "subtitles": {"anime": {"sha256": "ass-hash"}}}
    original = {"sources": [source]}
    assert merge_source_metadata([original, original]) == {"V01": source}
    changed = copy.deepcopy(original)
    changed["sources"][0][field] = {"qwen": {"sha256": "other-ass"}} if field == "subtitles" else "changed"
    with pytest.raises(ValueError, match="disagree"):
        merge_source_metadata([original, changed])


def test_verify_long_context_cannot_silently_use_old_short_padding():
    lock, manifest, prior = locked_fixture()
    lock["context_seconds"] = 35
    manifest["sources"][0]["duration_s"] = 9000
    manifest["samples"][0].update(context_start_s=4965, context_end_s=5055)
    assert verify_corpus(lock, manifest, prior) == 1
    manifest["samples"][0]["context_start_s"] = 4985
    with pytest.raises(ValueError, match="context window"):
        verify_corpus(lock, manifest, prior)
