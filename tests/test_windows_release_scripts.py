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
    wrapper = script_text("hf.cmd")
    assert '"$package_root/hf.cmd"' in stage
    assert "huggingface_hub.cli.hf" in wrapper
    assert 'set "HF_HUB_OFFLINE="' in wrapper
    assert 'set "TRANSFORMERS_OFFLINE="' in wrapper
    for name in ("INSTALL-CN.txt", "INSTALL-EN.txt"):
        guide = script_text(name)
        assert name in stage
        assert "jp2zh-subtitle-tool.exe" in guide
        assert "jp2zh字幕工具.exe" not in guide
        assert "hf.cmd download" in guide
        assert r"runtime\Scripts\hf.exe" not in guide
        assert "Sugoi-14B-Ultra-Q4_K_M.gguf" in guide


def test_project_mit_license_is_staged_and_validated():
    stage = script_text("stage-portable.sh")
    prepare = script_text("prepare-release-candidate.sh")
    extract = script_text("extract-release-candidate.sh")
    license_text = (PROJECT_ROOT / "LICENSE").read_text(encoding="utf-8")

    assert license_text.startswith("MIT License\n")
    assert "jp2zh-video-subs contributors" in license_text
    assert '"$package_root/LICENSE"' in stage
    assert '"$package_root/app/LICENSE"' in stage
    assert '"$program_stage"/LICENSE' in prepare
    assert 'jp2zh-video-subs/LICENSE' in extract
    assert 'jp2zh-video-subs/app/LICENSE' in extract


def test_program_only_release_can_be_extracted_without_model_archives():
    extract = script_text("extract-release-candidate.sh")
    assert "[program|all]" in extract
    assert 'if [[ "$target" == all ]]' in extract
    assert 'INSTALL-CN.txt' in extract
    assert 'INSTALL-EN.txt' in extract
    assert 'jp2zh-video-subs/hf.cmd' in extract
    assert "cmd.exe /d /c" in extract
    assert 'wslpath -w "$extract_root/jp2zh-video-subs/hf.cmd"' in extract
    assert 'find "$extract_root/jp2zh-video-subs/models"' in extract
    # A missing models directory must not pass as "ships no weights".
    assert 'test -d "$extract_root/jp2zh-video-subs/models"' in extract


def test_dev_path_scan_covers_setup_guides_at_the_package_root():
    prepare = script_text("prepare-release-candidate.sh")
    stage = script_text("stage-portable.sh")

    # Every hand-written file staged to the package root must be scanned for
    # development-machine paths, not just the app tree and the launchers.
    for root_file in ("INSTALL-CN.txt", "INSTALL-EN.txt", "THIRD_PARTY_NOTICES.md"):
        assert f'"$package_root/{root_file}"' in stage
        scanned_glob = f'"$program_stage"/*{Path(root_file).suffix}'
        assert scanned_glob in prepare, f"{root_file} ships unscanned"
    assert '"$package_root/LICENSE"' in stage
    assert '"$program_stage"/LICENSE' in prepare
    assert '"$program_stage"/*.cmd' in prepare
