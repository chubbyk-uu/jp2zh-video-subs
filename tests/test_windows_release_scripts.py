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
    assert 'generate_manifest "$program_stage"' not in prepare
    assert ".program-runtime-fingerprint" in prepare
    assert "protect /runtime/***" in prepare
    assert "--exclude '/runtime/***'" in prepare

    archive = script_text("archive-release-candidate.sh")
    assert 'sha256sum "$name"' in archive


def test_portable_setup_guides_are_current_and_staged():
    stage = script_text("stage-portable.sh")
    for name in ("INSTALL-CN.txt", "INSTALL-EN.txt"):
        guide = script_text(name)
        assert name in stage
        assert "jp2zh-subtitle-tool.exe" in guide
        assert "jp2zh字幕工具.exe" not in guide
        assert "Sugoi-14B-Ultra-Q4_K_M.gguf" in guide


def test_program_only_release_can_be_extracted_without_model_archives():
    extract = script_text("extract-release-candidate.sh")
    assert "[program|all]" in extract
    assert 'if [[ "$target" == all ]]' in extract
    assert 'INSTALL-CN.txt' in extract
    assert 'INSTALL-EN.txt' in extract
    assert 'find "$extract_root/jp2zh-video-subs/models"' in extract
