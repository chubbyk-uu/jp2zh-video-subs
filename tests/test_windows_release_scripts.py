from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WINDOWS_PACKAGING = PROJECT_ROOT / "packaging" / "windows"


def script_text(name: str) -> str:
    return (WINDOWS_PACKAGING / name).read_text(encoding="utf-8")


def test_sugoi_model_package_is_supported_across_release_lifecycle():
    prepare = script_text("prepare-release-candidate.sh")
    archive = script_text("archive-release-candidate.sh")
    extract = script_text("extract-release-candidate.sh")

    assert "models-sugoi-14b" in prepare
    assert "Sugoi-14B-Ultra-GGUF" in prepare
    assert "models-sugoi-14b.sha256" in prepare
    assert "sugoi-14b-ultra-README.md" in prepare

    archive_name = "jp2zh-video-subs-sugoi-14b-model.7z"
    assert archive_name in archive
    assert "archive_model_stage sugoi-14b" in archive
    assert archive_name in extract
    assert "Sugoi-14B-Ultra-Q4_K_M.gguf" in extract


def test_program_stage_still_excludes_all_model_weights():
    prepare = script_text("prepare-release-candidate.sh")
    assert "--exclude '/models/***'" in prepare
