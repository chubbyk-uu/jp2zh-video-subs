import json
from pathlib import Path

from ab_blind_test import (
    asmr_windows,
    clip_cues,
    differing_windows,
    pipeline_command,
    records_to_cues,
    sample_windows,
    sign_test_p,
    tally,
    translate_window,
    window_token_budget,
    write_cues,
)
from translation_common import Entry, parse_srt


def entry(start, end, text):
    return Entry("1", "", text, start, end)


def test_asmr_windows_cap_size_and_never_cross_long_pause():
    entries = [entry(i, i + 0.5, "x") for i in range(5)] + [entry(30, 31, "y"), entry(32, 33, "z")]
    windows = asmr_windows(entries, max_cues=3, reset_gap=10.0)
    assert [len(window) for window in windows] == [3, 2, 2]
    assert windows[2][0].start == 30


def test_records_to_cues_keeps_merges_and_drops_explicit_deletions():
    records = [{"ids": ["1", "2"], "text": "合并句", "start_s": 1.0, "end_s": 3.0},
               {"ids": ["3"], "text": None, "start_s": 4.0, "end_s": 5.0}]
    assert records_to_cues(records) == [(1.0, 3.0, "合并句")]


def test_write_cues_round_trips_sorted_srt(tmp_path):
    path = tmp_path / "out.srt"
    write_cues(path, [(5.0, 6.0, "后"), (1.0, 2.0, "前")])
    parsed = parse_srt(path)
    assert [item.text for item in parsed] == ["前", "后"]
    assert parsed[0].end >= 2.0


def test_differing_windows_skip_identical_and_near_empty_windows():
    a = [entry(1, 2, "今天天气很好我们出去吧"), entry(21, 22, "你到底想干什么啊"), entry(41, 42, "嗯")]
    b = [entry(1, 2, "今天天气很好我们出去吧"), entry(21, 22, "我不知道该怎么办才好"), entry(41, 42, "啊")]
    found = differing_windows(a, b, 60.0, window=20.0, threshold=0.6, min_chars=8)
    assert [item["index"] for item in found] == [1]


def test_differing_windows_count_one_sided_subtitles():
    a = [entry(1, 2, "这里明明有人在说话")]
    found = differing_windows(a, [], 20.0, window=20.0, threshold=0.6, min_chars=8)
    assert len(found) == 1 and found[0]["similarity"] == 0.0


def test_sample_windows_is_deterministic_spread_and_non_adjacent():
    candidates = {"V1": [{"index": i, "similarity": 0.1} for i in range(10)],
                  "V2": [{"index": i, "similarity": 0.1} for i in range(10)]}
    first = sample_windows(candidates, 6, seed=7)
    assert first == sample_windows(candidates, 6, seed=7)
    assert {video for video, _ in first} == {"V1", "V2"}
    for video in ("V1", "V2"):
        picked = sorted(item["index"] for vid, item in first if vid == video)
        assert all(b - a >= 2 for a, b in zip(picked, picked[1:]))


def test_clip_cues_are_relative_and_clamped():
    cues = clip_cues([entry(9, 12, "跨边界"), entry(50, 51, "外面")], 10.0, 30.0)
    assert cues == [{"s": 0.0, "e": 2.0, "t": "跨边界"}]


def test_tally_unblinds_votes_and_excludes_ties_from_sign_test():
    mapping = {"baseline": "default", "candidate": "jaykwok", "items": {
        "1": {"A": "jaykwok", "B": "default", "video": "V1"},
        "2": {"A": "default", "B": "jaykwok", "video": "V1"},
        "3": {"A": "default", "B": "jaykwok", "video": "V2"},
        "4": {"A": "default", "B": "jaykwok", "video": "V2"}}}
    result = tally(mapping, {"1": "A", "2": "B", "3": "tie"})
    assert (result["candidate_wins"], result["baseline_wins"], result["ties"], result["unvoted"]) == (2, 0, 1, 1)
    assert result["by_video"]["V2"]["ties"] == 1


def test_sign_test_p_values():
    assert sign_test_p(0, 0) == 1.0
    assert sign_test_p(5, 5) == 1.0
    assert abs(sign_test_p(20, 5) - 0.0041) < 0.001


def test_pipeline_command_swaps_only_qwen_weights_and_never_copies_next_to_video(tmp_path):
    video = {"id": "V1", "video": "/videos/a.mp4"}
    default = pipeline_command(video, tmp_path, "default", None)
    candidate = pipeline_command(video, tmp_path, "jaykwok", Path("/models/jaykwok"))
    assert "QWEN_ASR_MODEL" not in default[-1] and "'anime'" in default[-1]
    assert "QWEN_ASR_MODEL = Path('/models/jaykwok')" in candidate[-1] and "'qwen'" in candidate[-1]
    for command in (default, candidate):
        assert "--no-copy-to-video-dir" in command[-1] and "--resume" in command[-1]


class FakeLlm:
    def __init__(self, outputs):
        self.outputs, self.grammars = list(outputs), []

    def create_completion(self, prompt, grammar, **kwargs):
        self.grammars.append(grammar is not None)
        return {"choices": [{"text": self.outputs.pop(0), "finish_reason": "stop"}],
                "usage": {"completion_tokens": 10}}


def empty_stats():
    return {"completion_tokens": 0, "deleted": 0, "merged": 0, "length_stops": 0,
            "grammar_fallbacks": 0, "invalid_windows": 0, "failed_cues": 0}


def test_window_token_budget_scales_and_caps():
    assert window_token_budget(1) == 200
    assert window_token_budget(50) == 2048


def test_translate_window_uses_grammar_free_output_when_valid():
    window = [entry(1.0, 2.0, "はい"), entry(3.0, 4.0, "いいえ")]
    llm = FakeLlm(['[{"ids":[1,2],"text":"好的，不","start":1000,"end":4000}]'])
    stats = empty_stats()
    assert translate_window(llm, window, "V1", stats) == [(1.0, 4.0, "好的，不")]
    assert llm.grammars == [False] and stats["grammar_fallbacks"] == 0 and stats["merged"] == 1


def test_translate_window_falls_back_to_grammar_then_splits():
    window = [entry(1.0, 2.0, "はい"), entry(3.0, 4.0, "いいえ")]
    llm = FakeLlm(["not json", '[{"ids":[1],"text":"好","start":1000,"end":2000}]',  # missing ID 2
                   '[{"ids":[1],"text":"好","start":1000,"end":2000}]',
                   '[{"ids":[1],"text":"不","start":3000,"end":4000}]'])
    stats = empty_stats()
    assert translate_window(llm, window, "V1", stats) == [(1.0, 2.0, "好"), (3.0, 4.0, "不")]
    assert llm.grammars == [False, True, False, False]
    assert stats["invalid_windows"] == 1 and stats["grammar_fallbacks"] == 0


def test_translate_window_splits_runaway_output_without_grammar_retry():
    class RunawayFirst(FakeLlm):
        def create_completion(self, prompt, grammar, **kwargs):
            response = super().create_completion(prompt, grammar, **kwargs)
            if len(self.grammars) == 1:
                response["choices"][0]["finish_reason"] = "length"
            return response

    window = [entry(1.0, 2.0, "はい"), entry(3.0, 4.0, "いいえ")]
    llm = RunawayFirst(['[{"ids":[1],"text":"好好好好', '[{"ids":[1],"text":"好","start":1000,"end":2000}]',
                        '[{"ids":[1],"text":"不","start":3000,"end":4000}]'])
    stats = empty_stats()
    assert translate_window(llm, window, "V1", stats) == [(1.0, 2.0, "好"), (3.0, 4.0, "不")]
    assert llm.grammars == [False, False, False] and stats["length_stops"] == 1


def test_page_template_has_placeholders():
    template = (Path(__file__).resolve().parents[1] / "scripts" / "ab_blind_test_page.html").read_text(encoding="utf-8")
    assert "__TEST_NAME__" in template and "__ITEMS__" in template
    json.dumps(template)  # plain text, no binary content
