from subtitle_benchmark import parse_srt, render_report, score_candidates


def test_score_candidates_uses_consensus_and_weak_speech(tmp_path):
    anime = tmp_path / "anime.srt"
    qwen = tmp_path / "qwen.srt"
    cand = tmp_path / "cand.srt"
    anime.write_text(
        "1\n00:00:01,000 --> 00:00:02,000\n乾杯\n\n"
        "2\n00:00:05,000 --> 00:00:06,000\n小さい声です\n",
        encoding="utf-8",
    )
    qwen.write_text(
        "1\n00:00:01,000 --> 00:00:02,000\nかんぱい\n",
        encoding="utf-8",
    )
    cand.write_text(
        "1\n00:00:01,000 --> 00:00:02,000\n乾杯\n\n"
        "2\n00:00:05,000 --> 00:00:05,250\n違う\n",
        encoding="utf-8",
    )

    result = score_candidates(
        parse_srt(str(anime)),
        [parse_srt(str(qwen))],
        {"candidate": parse_srt(str(cand))},
    )

    assert result["consensus_segments"] == 1
    assert result["anime_only_weak_speech_segments"] == 1
    row = result["candidates"][0]
    assert row["consensus_recall"] == 1.0
    assert row["weak_speech_recall"] == 0.0
    assert row["timing"]["short<0.4"] == 1


def test_render_report_includes_structured_rows():
    result = {
        "consensus_segments": 1,
        "anime_only_weak_speech_segments": 1,
        "candidates": [{
            "candidate": "a",
            "consensus_hit": 1,
            "consensus_total": 1,
            "weak_speech_hit": 0,
            "weak_speech_total": 1,
            "timing": {"cues": 2, "short<0.4": 1, "long>8s": 0, "overlaps": 0},
        }],
    }

    report = render_report(result, "anime", 1)

    assert "Benchmark from anime=anime + 1 qwen refs" in report
    assert "a" in report
    assert "100.0% (1/1)" in report
    assert "short=1" in report
