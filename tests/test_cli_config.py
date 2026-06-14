from __future__ import annotations

import argparse
from dataclasses import dataclass

from cli_config import (
    add_dataclass_arguments,
    arg_field,
    config_from_namespace,
    config_from_prefixed,
    config_to_cli_args,
)
from pipeline_configs import QwenAsrConfig
from transcribe_ja_srt_qwen import build_parser as qwen_build_parser


@dataclass
class _Sample:
    count: int = arg_field(3, help="a number")
    name: str = arg_field("x", help="a string")
    ratio: float = arg_field(0.5, help="a float")
    mode: str = arg_field("a", choices=("a", "b"), help="choice")
    verbose: bool = arg_field(False, action="store_true", help="store-true bool")
    enabled: bool = arg_field(True, action="boolean_optional", help="--x/--no-x bool")


def _parse(cls, argv: list[str]):
    parser = argparse.ArgumentParser()
    add_dataclass_arguments(parser, cls)
    return config_from_namespace(parser.parse_args(argv), cls)


def test_defaults_parse_to_dataclass_defaults():
    assert _parse(_Sample, []) == _Sample()


def test_typed_values_and_choices_parse():
    cfg = _parse(_Sample, ["--count", "9", "--name", "hi", "--ratio", "1.5", "--mode", "b"])
    assert (cfg.count, cfg.name, cfg.ratio, cfg.mode) == (9, "hi", 1.5, "b")


def test_store_true_round_trips():
    assert config_to_cli_args(_Sample(verbose=False)).count("--verbose") == 0
    assert "--verbose" in config_to_cli_args(_Sample(verbose=True))
    assert _parse(_Sample, ["--verbose"]).verbose is True


def test_boolean_optional_round_trips():
    assert "--enabled" in config_to_cli_args(_Sample(enabled=True))
    assert "--no-enabled" in config_to_cli_args(_Sample(enabled=False))
    assert _parse(_Sample, ["--no-enabled"]).enabled is False
    assert _parse(_Sample, ["--enabled"]).enabled is True


def test_config_to_cli_args_then_parse_is_identity():
    original = _Sample(count=7, name="z", ratio=2.0, mode="b", verbose=True, enabled=False)
    assert _parse(_Sample, config_to_cli_args(original)) == original


def test_config_from_prefixed_maps_and_overrides():
    ns = argparse.Namespace(
        p_count=11, p_name="n", p_ratio=0.1, p_mode="b", p_verbose=True, p_enabled=False
    )
    cfg = config_from_prefixed(ns, _Sample, "p_", overrides={"name": "forced"})
    assert cfg.count == 11 and cfg.name == "forced" and cfg.enabled is False


# --- QwenAsrConfig <-> the Qwen sub-script parser ---

def test_qwen_config_round_trips_through_subscript_parser():
    cfg = QwenAsrConfig()
    parser = qwen_build_parser()
    ns = parser.parse_args(["a.wav", "out.srt", *config_to_cli_args(cfg)])
    assert config_from_namespace(ns, QwenAsrConfig) == cfg


def test_qwen_config_round_trips_with_toggled_bools():
    cfg = QwenAsrConfig(
        vad_chunks=True,
        collapse_filler_repetition=False,
        filter_hallucinations=True,
        no_default_context=True,
        batch_size=8,
        phrase_max_chars=30,
        context="宮下玲奈",
    )
    parser = qwen_build_parser()
    ns = parser.parse_args(["a.wav", "out.srt", *config_to_cli_args(cfg)])
    assert config_from_namespace(ns, QwenAsrConfig) == cfg
