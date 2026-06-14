from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

from cli_config import (
    add_dataclass_arguments,
    arg_field,
    config_from_namespace,
    config_from_prefixed,
    config_to_cli_args,
)
from pipeline_configs import QwenAsrConfig
from pipeline_configs import (
    BilingualAssConfig,
    GalTranslTranslateConfig,
    HymtTranslateConfig,
    SakuraTranslateConfig,
)
from make_bilingual_ass import build_parser as bilingual_build_parser
from translate_srt_galtransl import build_parser as galtransl_build_parser
from translate_srt_hymt import build_parser as hymt_build_parser
from translate_srt_sakura import build_parser as sakura_build_parser
from transcribe_ja_srt_qwen import build_parser as qwen_build_parser
from video_to_zh_srt import build_bilingual_command, build_translate_command


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


def test_translate_configs_round_trip_through_subscript_parsers():
    cases = [
        (
            hymt_build_parser(),
            HymtTranslateConfig(context_size=2, lead_out_seconds=0.5, min_display_seconds=1.5),
        ),
        (
            sakura_build_parser(),
            SakuraTranslateConfig(context_size=6, lead_out_seconds=0.5, min_display_seconds=1.5),
        ),
        (
            galtransl_build_parser(),
            GalTranslTranslateConfig(context_size=6, batch_size=8, lead_out_seconds=0.5, min_display_seconds=1.5),
        ),
    ]
    for parser, cfg in cases:
        ns = parser.parse_args(["in.ja.srt", "--output", "out.zh.srt", *config_to_cli_args(cfg)])
        assert config_from_namespace(ns, type(cfg)) == cfg


def test_galtransl_batch_size_is_not_in_other_translate_configs():
    assert "--batch-size" not in config_to_cli_args(HymtTranslateConfig())
    assert "--batch-size" not in config_to_cli_args(SakuraTranslateConfig())
    assert "--batch-size" in config_to_cli_args(GalTranslTranslateConfig())


def test_bilingual_config_round_trips_through_subscript_parser():
    cfg = BilingualAssConfig(
        font="Microsoft YaHei",
        zh_font_size=40,
        ja_font_size=25,
        colour_by_speaker=True,
        gender_confidence=0.7,
    )
    parser = bilingual_build_parser()
    ns = parser.parse_args([
        "--zh-srt",
        "out.zh.srt",
        "--ja-srt",
        "in.ja.srt",
        "--output",
        "out.ass",
        *config_to_cli_args(cfg),
    ])
    assert config_from_namespace(ns, BilingualAssConfig) == cfg


def _pipeline_args(translator: str = "galtransl") -> argparse.Namespace:
    return argparse.Namespace(
        translator=translator,
        context_size=None,
        translate_batch_size=8,
        lead_out_seconds=0.5,
        min_display_seconds=1.5,
        bilingual_font="Microsoft YaHei",
        bilingual_zh_font_size=36,
        bilingual_ja_font_size=24,
        bilingual_zh_colour="&H0000FFFF",
        bilingual_ja_colour="&H00B4B4B4",
        bilingual_male_colour="&H00FFBF00",
        bilingual_female_colour="&H00B478FF",
        bilingual_play_res_x=1280,
        bilingual_play_res_y=720,
        colour_by_speaker=False,
        gender_confidence=0.6,
    )


def test_pipeline_translate_command_uses_backend_configs():
    cases = [
        ("hymt", hymt_build_parser(), HymtTranslateConfig, 2),
        ("sakura", sakura_build_parser(), SakuraTranslateConfig, 6),
        ("galtransl", galtransl_build_parser(), GalTranslTranslateConfig, 6),
    ]
    for translator, parser, cls, expected_context in cases:
        cmd = build_translate_command(_pipeline_args(translator), Path("in.ja.srt"), Path("out.zh.srt"))
        ns = parser.parse_args(cmd[2:])
        cfg = config_from_namespace(ns, cls)
        assert cfg.context_size == expected_context
        assert cfg.lead_out_seconds == 0.5
        assert cfg.min_display_seconds == 1.5
        assert ("--batch-size" in cmd) is (translator == "galtransl")


def test_pipeline_bilingual_command_uses_bilingual_config():
    args = _pipeline_args()
    args.colour_by_speaker = True
    args.gender_confidence = 0.7
    cmd = build_bilingual_command(args, Path("out.zh.srt"), Path("in.ja.srt"), Path("out.ass"), Path("audio.wav"))
    ns = bilingual_build_parser().parse_args(cmd[2:])
    cfg = config_from_namespace(ns, BilingualAssConfig)
    assert cfg.colour_by_speaker is True
    assert cfg.gender_confidence == 0.7
    assert ns.audio == Path("audio.wav")
