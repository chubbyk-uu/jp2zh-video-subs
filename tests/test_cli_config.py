from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import pytest

from cli_config import (
    add_dataclass_arguments,
    arg_field,
    config_from_namespace,
    config_from_prefixed,
    config_to_cli_args,
)
from pipeline_configs import (
    AnimeAsrConfig,
    BilingualAssConfig,
    GalTranslTranslateConfig,
    QualityReportConfig,
    QwenAsrConfig,
    SakuraTranslateConfig,
    SugoiTranslateConfig,
)
from make_bilingual_ass import build_parser as bilingual_build_parser
from quality_report import build_parser as quality_build_parser
from translate_srt_galtransl import build_parser as galtransl_build_parser
from translate_srt_sakura import build_parser as sakura_build_parser
from transcribe_ja_srt_qwen import build_parser as qwen_build_parser
from video_to_zh_srt import (
    build_bilingual_command,
    build_translate_command,
)


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


def test_anime_config_round_trips_through_shared_qwen_subscript_parser():
    cfg = AnimeAsrConfig()
    parser = qwen_build_parser()
    ns = parser.parse_args(["a.wav", "out.srt", *config_to_cli_args(cfg)])
    assert config_from_namespace(ns, AnimeAsrConfig) == cfg


def test_qwen_and_anime_backend_defaults_are_separate():
    qwen = QwenAsrConfig()
    anime = AnimeAsrConfig()

    assert qwen.text_backend == "qwen"
    assert qwen.timestamp_mode == "aligner_fallback"
    assert qwen.vad_backend == "whisperseg"
    # Qwen default: short scene-padded WhisperSeg frames, semantic scene ON, no
    # context merge; step-down remains selectable but off by default.
    assert qwen.phrase_max_chars == 80
    assert qwen.phrase_max_internal_gap == 1.5
    assert qwen.scene_backend == "semantic"
    assert qwen.stepdown is False
    assert qwen.stepdown_fallback_group == 6.0
    assert qwen.whisperseg_context_mode == "none"
    assert qwen.whisperseg_context_merge_gap == 1.0
    assert qwen.whisperseg_context_target_seconds == 10.0
    assert qwen.whisperseg_context_after_target_gap == 0.2
    assert qwen.whisperseg_context_hard_max_seconds == 15.0
    assert anime.text_backend == "anime"
    assert anime.timestamp_mode == "aligner_fallback"
    assert anime.phrase_max_chars == 80
    assert anime.vad_backend == "whisperseg"
    assert anime.scene_backend == "semantic"
    assert qwen.whisperseg_chunk_threshold == 1.0
    assert anime.whisperseg_chunk_threshold == 0.5


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
        bilingual_ja_font="Microsoft YaHei",
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
        ("sakura", sakura_build_parser(), SakuraTranslateConfig, 6),
        ("galtransl", galtransl_build_parser(), GalTranslTranslateConfig, 6),
        ("sugoi", __import__("translate_srt_sugoi").build_parser(), SugoiTranslateConfig, None),
    ]
    for translator, parser, cls, expected_context in cases:
        cmd = build_translate_command(_pipeline_args(translator), Path("in.ja.srt"), Path("out.zh.srt"))
        # run_stage_command uses argv[2] to count cues for translation progress.
        assert cmd[2] == "in.ja.srt"
        ns = parser.parse_args(cmd[2:])
        cfg = config_from_namespace(ns, cls)
        if expected_context is not None:
            assert cfg.context_size == expected_context
        assert cfg.lead_out_seconds == 0.5
        assert cfg.min_display_seconds == 1.5
        assert ("--batch-size" in cmd) is (translator in ("galtransl", "sugoi"))


def test_pipeline_uses_translator_specific_default_batch_sizes():
    gal = _pipeline_args("galtransl")
    gal.translate_batch_size = None
    sugoi = _pipeline_args("sugoi")
    sugoi.translate_batch_size = None
    gal_cmd = build_translate_command(gal, Path("in.ja.srt"), Path("out.zh-s.srt"))
    sugoi_cmd = build_translate_command(sugoi, Path("in.ja.srt"), Path("out.en.srt"))
    assert gal_cmd[gal_cmd.index("--batch-size") + 1] == "8"
    assert sugoi_cmd[sugoi_cmd.index("--batch-size") + 1] == "10"


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


def test_quality_config_round_trips_through_subscript_parser():
    cfg = QualityReportConfig(vad_min_silence_ms=500, vad_speech_pad_ms=400, max_samples=15)
    ns = quality_build_parser().parse_args(["--ja-srt", "in.ja.srt", *config_to_cli_args(cfg)])
    assert config_from_namespace(ns, QualityReportConfig) == cfg


# --- TOML config file (apply_config_file / format_config_toml) ---
import subprocess  # noqa: E402

from cli_config import apply_config_file, format_config_toml  # noqa: E402


def _config_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser()
    p.add_argument("input")
    p.add_argument("--count", type=int, default=3)
    p.add_argument("--ratio", type=float, default=0.5)
    p.add_argument("--name", default="x")
    p.add_argument("--flag", action="store_true")
    p.add_argument("--toggle", action=argparse.BooleanOptionalAction, default=True)
    return p


def test_apply_config_file_sets_defaults(tmp_path):
    cfg = tmp_path / "c.toml"
    cfg.write_text('count = 9\nratio = 1.5\nname = "hi"\nflag = true\ntoggle = false\n')
    parser = _config_parser()
    apply_config_file(parser, cfg)
    args = parser.parse_args(["vid"])
    assert (args.count, args.ratio, args.name, args.flag, args.toggle) == (9, 1.5, "hi", True, False)


def test_apply_config_file_cli_overrides_file(tmp_path):
    cfg = tmp_path / "c.toml"
    cfg.write_text("count = 9\n")
    parser = _config_parser()
    apply_config_file(parser, cfg)
    assert parser.parse_args(["vid", "--count", "1"]).count == 1  # CLI wins


def test_apply_config_file_accepts_hyphen_keys_and_coerces(tmp_path):
    cfg = tmp_path / "c.toml"
    cfg.write_text('ratio = 2\n')  # int in TOML for a float option
    parser = _config_parser()
    apply_config_file(parser, cfg)
    assert parser.parse_args(["vid"]).ratio == 2.0


def test_apply_config_file_rejects_unknown_key(tmp_path):
    cfg = tmp_path / "c.toml"
    cfg.write_text("nope = 1\n")
    with pytest.raises(SystemExit):
        apply_config_file(_config_parser(), cfg)


def test_apply_config_file_rejects_nested_table(tmp_path):
    cfg = tmp_path / "c.toml"
    cfg.write_text("[section]\ncount = 1\n")
    with pytest.raises(SystemExit):
        apply_config_file(_config_parser(), cfg)


def test_format_config_toml_renders_types():
    out = format_config_toml({"a": 1, "b": 2.5, "c": "x", "d": True, "e": None, "f": Path("/tmp/y")})
    assert "a = 1" in out and "b = 2.5" in out and 'c = "x"' in out
    assert "d = true" in out and "e =" not in out and 'f = "/tmp/y"' in out


def test_pipeline_print_config_applies_file_and_cli(tmp_path):
    cfg = tmp_path / "pipe.toml"
    cfg.write_text('translator = "sakura"\nqwen_batch_size = 12\n')
    script = Path(__file__).resolve().parents[1] / "scripts" / "video_to_zh_srt.py"
    out = subprocess.run(
        ["python", str(script), "dummy.mp4", "--config", str(cfg),
         "--translator", "galtransl", "--print-config"],
        capture_output=True, text=True, check=True,
    ).stdout
    assert 'translator = "galtransl"' in out   # CLI overrides file
    assert "qwen_batch_size = 12" in out        # file overrides code default
    # Per-run IO args are not reusable configuration and are omitted.
    assert "input =" not in out and "output =" not in out


def _choices_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=("a", "b"), default="a")
    p.add_argument("--count", type=int, default=1)
    p.add_argument("--flag", action="store_true")
    return p


def test_apply_config_file_rejects_invalid_choice(tmp_path):
    cfg = tmp_path / "c.toml"
    cfg.write_text('mode = "bad"\n')
    with pytest.raises(SystemExit):
        apply_config_file(_choices_parser(), cfg)


def test_apply_config_file_rejects_bool_for_value_option(tmp_path):
    cfg = tmp_path / "c.toml"
    cfg.write_text("count = true\n")
    with pytest.raises(SystemExit):
        apply_config_file(_choices_parser(), cfg)


def test_apply_config_file_rejects_non_bool_for_switch(tmp_path):
    cfg = tmp_path / "c.toml"
    cfg.write_text('flag = "yes"\n')
    with pytest.raises(SystemExit):
        apply_config_file(_choices_parser(), cfg)


def test_apply_config_file_accepts_valid_choice_and_switch(tmp_path):
    cfg = tmp_path / "c.toml"
    cfg.write_text('mode = "b"\nflag = true\n')
    parser = _choices_parser()
    apply_config_file(parser, cfg)
    args = parser.parse_args([])
    assert args.mode == "b" and args.flag is True
