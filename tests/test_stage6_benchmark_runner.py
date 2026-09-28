import json

from run_qwen_stage6_benchmark import benchmark_command, cache_matches, default_variants, file_sha256, selected_variants


def test_default_variants_keep_baseline_separate_from_wj_core():
    variants = {variant.name: variant.config for variant in default_variants()}

    baseline = variants["qwen_fixed_tiling"]
    assert baseline.vad_chunks is False
    assert baseline.vad_backend == "whisperseg"
    assert baseline.scene_backend == "none"
    assert baseline.timestamp_mode == "aligner_only"
    assert baseline.collapse_recovery is False
    assert baseline.max_new_tokens == 256
    assert baseline.repetition_penalty == 1.0
    assert baseline.max_tokens_per_second == 0.0

    wj_core = variants["qwen_wj_core"]
    assert wj_core.vad_backend == "whisperseg"
    assert wj_core.scene_backend == "semantic"
    assert wj_core.timestamp_mode == "aligner_fallback"
    assert wj_core.collapse_recovery is True
    assert wj_core.max_new_tokens == 4096
    assert wj_core.repetition_penalty == 1.1
    assert wj_core.max_tokens_per_second == 20.0

    whisperseg_gen = variants["qwen_whisperseg_gen"]
    assert whisperseg_gen.vad_backend == "whisperseg"
    assert whisperseg_gen.scene_backend == "none"
    assert whisperseg_gen.repetition_penalty == 1.1
    assert whisperseg_gen.max_tokens_per_second == 20.0

    wj_framing = variants["qwen_wj_framing"]
    assert wj_framing.vad_backend == "whisperseg"
    assert wj_framing.scene_backend == "semantic"
    assert wj_framing.repetition_penalty == 1.0
    assert wj_framing.max_tokens_per_second == 0.0


def test_selected_variants_preserves_requested_order():
    variants = selected_variants(["anime", "qwen_fixed_tiling"])

    assert [variant.name for variant in variants] == ["anime", "qwen_fixed_tiling"]


def test_benchmark_command_requires_refs(tmp_path):
    class Args:
        anime_ref = "anime=anime.srt"
        qwen_ref = ["qwen=qwen.srt"]

    cmd = benchmark_command(Args(), {"cand": tmp_path / "cand.srt"}, tmp_path / "out.json")

    assert "--anime-ref" in cmd
    assert "anime=anime.srt" in cmd
    assert "--qwen-ref" in cmd
    assert "qwen=qwen.srt" in cmd
    assert f"cand={tmp_path / 'cand.srt'}" in cmd


def test_cache_needs_matching_provenance_and_both_output_digests(tmp_path):
    srt, raw, record = tmp_path / "a.srt", tmp_path / "raw.json", tmp_path / "run.json"
    srt.write_text("1\n00:00:01,000 --> 00:00:02,000\nはい\n", encoding="utf-8")
    raw.write_text("{}", encoding="utf-8")
    assert not cache_matches(record, "new", srt, raw)
    record.write_text(json.dumps({"status": "complete", "fingerprint": "new",
                                  "outputs": {"srt": file_sha256(srt), "raw": file_sha256(raw)}}), encoding="utf-8")
    assert cache_matches(record, "new", srt, raw)
    assert not cache_matches(record, "changed", srt, raw)
    raw.write_text('{"modified":true}', encoding="utf-8")
    assert not cache_matches(record, "new", srt, raw)


def test_empty_srt_is_valid_cached_result_not_missing(tmp_path):
    srt, raw, record = tmp_path / "a.srt", tmp_path / "raw.json", tmp_path / "run.json"
    srt.write_text("", encoding="utf-8")
    raw.write_text("{}", encoding="utf-8")
    record.write_text(json.dumps({"status": "complete", "fingerprint": "empty",
                                  "outputs": {"srt": file_sha256(srt), "raw": file_sha256(raw)}}), encoding="utf-8")
    assert cache_matches(record, "empty", srt, raw)
    srt.unlink()
    assert not cache_matches(record, "empty", srt, raw)
