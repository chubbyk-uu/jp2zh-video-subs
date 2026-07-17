from pathlib import Path

from portable_runtime import (
    PORTABLE_ROOT_ENV,
    app_root,
    portable_config_path,
    project_root,
    rebase_portable_path,
    single_instance_lock_path,
    scripts_dir,
)


def test_source_checkout_paths_resolve_from_nested_script(monkeypatch):
    monkeypatch.delenv(PORTABLE_ROOT_ENV, raising=False)
    anchor = Path(__file__).resolve().parents[1] / "scripts" / "jp2zh_gui" / "models.py"

    assert project_root(anchor) == Path(__file__).resolve().parents[1]
    assert app_root(anchor) == Path(__file__).resolve().parents[1]
    assert scripts_dir(anchor) == Path(__file__).resolve().parents[1] / "scripts"
    assert portable_config_path(anchor) is None
    assert single_instance_lock_path(anchor).name == "jp2zh-video-subs-gui.lock"


def test_portable_paths_use_explicit_bundle_root(tmp_path, monkeypatch):
    root = tmp_path / "portable bundle"
    (root / "app" / "scripts").mkdir(parents=True)
    monkeypatch.setenv(PORTABLE_ROOT_ENV, str(root))

    assert project_root() == root.resolve()
    assert app_root() == (root / "app").resolve()
    assert scripts_dir() == (root / "app" / "scripts").resolve()
    assert portable_config_path() == (root / "config" / "gui.ini").resolve()
    assert single_instance_lock_path() == (root / "config" / "jp2zh-video-subs.lock").resolve()


def test_portable_root_is_detected_from_bundled_app_without_environment(tmp_path, monkeypatch):
    root = tmp_path / "portable bundle"
    anchor = root / "app" / "scripts" / "jp2zh_gui" / "models.py"
    anchor.parent.mkdir(parents=True)
    (root / "runtime").mkdir()
    monkeypatch.delenv(PORTABLE_ROOT_ENV, raising=False)

    assert project_root(anchor) == root.resolve()
    assert app_root(anchor) == (root / "app").resolve()


def test_rebase_portable_path_moves_only_paths_inside_previous_root(tmp_path):
    previous = tmp_path / "old bundle"
    current = tmp_path / "new bundle"
    external = tmp_path / "external outputs"

    assert rebase_portable_path(previous / "outputs", previous, current) == current / "outputs"
    assert rebase_portable_path(previous / "work" / "job", previous, current) == current / "work" / "job"
    assert rebase_portable_path(external, previous, current) == external
