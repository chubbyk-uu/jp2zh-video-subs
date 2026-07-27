from pathlib import Path

import pytest

from model_catalog import (
    MODEL_DOWNLOAD_SPECS,
    ModelDownloadSpec,
    ModelInstallState,
    cleanup_redundant_model_partials,
    model_download_state,
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
        assert spec.filenames
        assert set(spec.required_files).issubset(spec.filenames)
        assert spec.revision is not None
        assert len(spec.revision) == 40
        assert all(character in "0123456789abcdef" for character in spec.revision)
        for filename in spec.filenames:
            relative = Path(filename)
            assert not relative.is_absolute()
            assert ".." not in relative.parts


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
    assert model_install_state(spec, tmp_path) == ModelInstallState.INSTALLED

    incomplete.unlink()
    assert model_install_state(spec, tmp_path) == ModelInstallState.INSTALLED


def test_download_state_requires_every_planned_file_but_runtime_state_does_not(
    tmp_path,
):
    spec = ModelDownloadSpec(
        key="test",
        name="Test",
        repo_id="owner/repo",
        local_dir="models/test",
        required_files=("model.bin",),
        filenames=("model.bin", "optional.json"),
        revision="a" * 40,
    )
    destination = spec.destination(tmp_path)
    destination.mkdir(parents=True)
    (destination / "model.bin").write_bytes(b"ready")
    (destination / "optional.json.incomplete").write_bytes(b"partial")

    assert model_install_state(spec, tmp_path) == ModelInstallState.INSTALLED
    assert model_download_state(spec, tmp_path) == ModelInstallState.PARTIAL

    (destination / "optional.json").write_bytes(b"complete")
    assert model_download_state(spec, tmp_path) == ModelInstallState.INSTALLED


def test_redundant_compat_partial_is_cleaned_after_complete_final_file(tmp_path):
    spec = model_specs(("whisperseg",))[0]
    destination = spec.destination(tmp_path)
    destination.mkdir(parents=True)
    target = destination / "model.onnx"
    target.write_bytes(b"complete")
    partial = destination / "model.onnx.incomplete"
    partial.write_bytes(b"old partial")
    metadata = destination / "model.onnx.incomplete.json"
    metadata.write_text(
        (
            '{"repo_id":"TransWithAI/Whisper-Vad-EncDec-ASMR-onnx",'
            f'"revision":"{spec.revision}",'
            '"filename":"model.onnx","size":8}'
        ),
        encoding="utf-8",
    )

    assert cleanup_redundant_model_partials(spec, tmp_path) == 1
    assert not partial.exists()
    assert not metadata.exists()
    assert model_install_state(spec, tmp_path) == ModelInstallState.INSTALLED


def test_redundant_partial_cleanup_keeps_unverified_final_file(tmp_path):
    spec = model_specs(("whisperseg",))[0]
    destination = spec.destination(tmp_path)
    destination.mkdir(parents=True)
    (destination / "model.onnx").write_bytes(b"wrong size")
    partial = destination / "model.onnx.incomplete"
    partial.write_bytes(b"partial")
    metadata = destination / "model.onnx.incomplete.json"
    metadata.write_text(
        (
            '{"repo_id":"TransWithAI/Whisper-Vad-EncDec-ASMR-onnx",'
            f'"revision":"{spec.revision}",'
            '"filename":"model.onnx","size":8}'
        ),
        encoding="utf-8",
    )

    assert cleanup_redundant_model_partials(spec, tmp_path) == 0
    assert partial.exists()
    assert metadata.exists()
