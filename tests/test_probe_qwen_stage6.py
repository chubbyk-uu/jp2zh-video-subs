from types import SimpleNamespace

from probe_qwen_stage6 import (
    apply_repetition_penalty_probe,
    decide_batch_token_budget,
    items_are_clip_relative,
    resolve_generation_config,
)


class _Obj:
    pass


def test_resolve_generation_config_prefers_qwen_thinker_path():
    wrapper = _Obj()
    wrapper.model = _Obj()
    wrapper.model.thinker = _Obj()
    wrapper.model.thinker.generation_config = _Obj()

    config, path = resolve_generation_config(wrapper)

    assert config is wrapper.model.thinker.generation_config
    assert path == "model.model.thinker.generation_config"


def test_apply_repetition_penalty_probe_sets_verified_config():
    wrapper = _Obj()
    wrapper.model = _Obj()
    wrapper.model.thinker = _Obj()
    wrapper.model.thinker.generation_config = _Obj()

    result = apply_repetition_penalty_probe(wrapper, 1.1)

    assert result == {
        "applied": True,
        "path": "model.model.thinker.generation_config",
        "value": 1.1,
    }
    assert wrapper.model.thinker.generation_config.repetition_penalty == 1.1


def test_apply_repetition_penalty_probe_reports_missing_path():
    result = apply_repetition_penalty_probe(_Obj(), 1.1)

    assert result == {"applied": False, "path": "missing", "value": None}


def test_decide_batch_token_budget_flags_mixed_clip_budgets():
    decision = decide_batch_token_budget(
        clip_seconds=[5.0, 40.0],
        max_new_tokens=4096,
        max_tokens_per_second=20.0,
        min_tokens_floor=256,
    )

    assert decision.per_clip == [256, 800]
    assert decision.batch_budget == 800
    assert decision.recommendation == "group_by_budget_or_batch1"


def test_items_are_clip_relative_accepts_small_tolerance():
    items = [
        SimpleNamespace(text="あ", start_time=-0.02, end_time=0.2),
        SimpleNamespace(text="い", start_time=1.0, end_time=5.04),
    ]

    assert items_are_clip_relative(items, clip_duration=5.0, tolerance=0.05) is True
    assert items_are_clip_relative(items, clip_duration=5.0, tolerance=0.01) is False


def test_items_are_clip_relative_returns_none_without_timed_items():
    assert items_are_clip_relative([], clip_duration=5.0) is None
