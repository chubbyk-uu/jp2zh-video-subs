from pathlib import Path

import pytest

from jp2zh_gui.models import (
    AsrPreset,
    CleanupPolicy,
    GuiConfig,
    GuiTask,
    TaskStatus,
    TranslatorPreset,
    TargetLanguage,
    discover_dropped_videos,
    missing_model_files,
)


def test_gui_config_builds_pipeline_command(tmp_path):
    config = GuiConfig(
        output_dir=tmp_path / "out",
        work_dir=tmp_path / "work",
        asr=AsrPreset.QWEN,
        translator=TranslatorPreset.SAKURA,
        target_language=TargetLanguage.TRADITIONAL_CHINESE,
        bilingual=False,
        quality_report=True,
        resume=True,
        copy_to_video_dir=False,
        cleanup_policy=CleanupPolicy.FINAL_ONLY,
        asr_batch_size=12,
        context_size=9,
        translate_batch_size=4,
        display_wrap_max_chars=18,
        colour_by_speaker=True,
    )

    command = config.build_command(
        tmp_path / "input.mp4",
        tmp_path / "events.jsonl",
        tmp_path / "cancel.requested",
        python_executable="python-test",
        pipeline_script=Path("pipeline.py"),
    )

    assert command[:3] == ["python-test", "pipeline.py", str(tmp_path / "input.mp4")]
    assert command[command.index("--asr") + 1] == "qwen"
    assert command[command.index("--translator") + 1] == "sakura"
    assert command[command.index("--target-language") + 1] == "zh-Hant"
    assert command[command.index("--bilingual-ja-font") + 1] == "Microsoft YaHei"
    assert command[command.index("--cleanup-policy") + 1] == "final_only"
    assert command[command.index("--qwen-batch-size") + 1] == "12"
    assert command[command.index("--context-size") + 1] == "9"
    assert command[command.index("--bilingual-zh-colour") + 1] == "&H0000FFFF"
    for flag in ("--no-bilingual", "--quality-report", "--resume", "--no-copy-to-video-dir", "--colour-by-speaker"):
        assert flag in command


def test_gui_config_rejects_invalid_common_values():
    config = GuiConfig(context_size=-1, translate_batch_size=-2, display_wrap_max_chars=-3, bilingual_font="")
    assert {issue.code for issue in config.validate()} == {
        "context_nonnegative", "translate_batch_nonnegative", "wrap_nonnegative", "subtitle_font_required"
    }
    with pytest.raises(ValueError, match="context_nonnegative"):
        config.build_command(Path("a.mp4"), Path("events"), Path("cancel"))

    with pytest.raises(ValueError, match="ass_colour_format"):
        GuiConfig(bilingual_zh_colour="#ffff00").build_command(Path("a.mp4"), Path("events"), Path("cancel"))


def test_gui_config_uses_selected_anime_batch_flag():
    command = GuiConfig(asr=AsrPreset.ANIME, asr_batch_size=16).build_command(
        Path("a.mp4"), Path("events"), Path("cancel")
    )
    assert command[command.index("--anime-batch-size") + 1] == "16"
    assert "--qwen-batch-size" not in command


def test_sugoi_gui_command_omits_unsupported_context_and_normalizes_batch_zero():
    command = GuiConfig(
        translator=TranslatorPreset.SUGOI,
        target_language=TargetLanguage.ENGLISH,
        translate_batch_size=0,
    ).build_command(Path("a.mp4"), Path("events"), Path("cancel"))
    assert "--context-size" not in command
    assert command[command.index("--translate-batch-size") + 1] == "0"


def test_gui_config_rejects_incompatible_translator_target():
    issues = GuiConfig(
        translator=TranslatorPreset.SUGOI,
        target_language=TargetLanguage.SIMPLIFIED_CHINESE,
    ).validate()
    assert [issue.code for issue in issues] == ["translator_target_incompatible"]


def test_discover_dropped_videos_expands_directories_and_deduplicates(tmp_path):
    direct = tmp_path / "a.mp4"
    nested_dir = tmp_path / "nested"
    nested_dir.mkdir()
    nested = nested_dir / "b.mkv"
    ignored = nested_dir / "readme.txt"
    direct.touch()
    nested.touch()
    ignored.touch()

    assert discover_dropped_videos([direct, tmp_path, direct], recursive=False) == [direct.resolve()]
    assert discover_dropped_videos([tmp_path, direct], recursive=True) == [direct.resolve(), nested.resolve()]


def test_gui_task_retry_resets_terminal_state(tmp_path):
    task = GuiTask(tmp_path / "a.mp4", status=TaskStatus.FAILED, stage="translate", stage_index=3, error="bad")
    task.outputs["srt"] = tmp_path / "a.srt"

    task.reset_for_retry()

    assert task.status == TaskStatus.WAITING
    assert task.stage is None
    assert task.error == ""
    assert task.outputs == {}


def test_missing_model_files_uses_selected_presets(tmp_path):
    config = GuiConfig(asr=AsrPreset.ANIME, translator=TranslatorPreset.GALTRANSL)
    missing = missing_model_files(config, tmp_path)

    assert tmp_path / "models/anime-whisper/model.safetensors" in missing
    assert tmp_path / "models/Sakura-GalTransl-7B-v3.7-GGUF/Sakura-Galtransl-7B-v3.7.gguf" in missing
    assert not any("Qwen3-ASR-1.7B" in str(path) for path in missing)
