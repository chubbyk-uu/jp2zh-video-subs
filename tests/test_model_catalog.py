from pathlib import Path

import pytest

from model_catalog import (
    MODEL_DOWNLOAD_SPECS,
    ModelInstallState,
    model_install_state,
    model_specs,
    required_model_keys,
    required_model_paths,
)


def test_model_catalog_keys_are_unique_and_destinations_stay_under_models():
    assert len({spec.key for spec in MODEL_DOWNLOAD_SPECS}) == len(MODEL_DOWNLOAD_SPECS)
    for spec in MODEL_DOWNLOAD_SPECS:
        assert Path(spec.local_dir).parts[0] == "models"
        assert spec.required_files


def test_current_configuration_dependencies_preserve_catalog_order(tmp_path):
    assert required_model_keys("anime", "galtransl") == (
        "anime-whisper",
        "whisperseg",
        "qwen-forced-aligner",
        "galtransl-7b",
    )
    paths = required_model_paths(tmp_path, "anime", "galtransl")
    assert tmp_path / "models/anime-whisper/model.safetensors" in paths
    assert (
        tmp_path
        / "models/Sakura-GalTransl-7B-v3.7-GGUF"
        / "Sakura-Galtransl-7B-v3.7.gguf"
    ) in paths


def test_optional_dependencies_are_selected_only_when_requested():
    assert required_model_keys("qwen", "sakura", colour_by_speaker=True) == (
        "qwen-asr-1.7b",
        "whisperseg",
        "qwen-forced-aligner",
        "sakura-14b",
        "speaker-gender",
    )
    with pytest.raises(ValueError, match="Unknown model preset"):
        required_model_keys("bad", "galtransl")
    with pytest.raises(ValueError, match="Unknown model keys"):
        model_specs(("bad",))


def test_model_install_state_distinguishes_missing_partial_and_installed(tmp_path):
    spec = model_specs(("whisperseg",))[0]
    assert model_install_state(spec, tmp_path) == ModelInstallState.MISSING

    incomplete = spec.destination(tmp_path) / ".cache/huggingface/download/model.incomplete"
    incomplete.parent.mkdir(parents=True)
    incomplete.write_bytes(b"partial")
    assert model_install_state(spec, tmp_path) == ModelInstallState.PARTIAL

    (spec.destination(tmp_path) / "model.onnx").write_bytes(b"complete")
    assert model_install_state(spec, tmp_path) == ModelInstallState.PARTIAL

    incomplete.unlink()
    assert model_install_state(spec, tmp_path) == ModelInstallState.INSTALLED
