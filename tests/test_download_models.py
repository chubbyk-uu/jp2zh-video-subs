import hashlib
import io
import json
from types import SimpleNamespace

import pytest

from download_models import (
    DownloadIntegrityError,
    EventWriter,
    ProgressMonitor,
    RemoteFileInfo,
    RemoteModelPlan,
    configure_hub_environment,
    create_hub_api,
    download_remote_plan,
    download_public_file,
    observed_download_bytes,
    remote_model_plan,
    run_download_queue,
    safe_download_target,
    validate_download_filename,
)
from model_catalog import ModelDownloadSpec, model_specs


REVISION = "a" * 40


class FakeApi:
    def __init__(self, files, *, sha=None):
        self.files = files
        self.sha = sha
        self.calls = []

    def model_info(self, repo_id, *, revision, files_metadata):
        self.calls.append((repo_id, revision, files_metadata))
        return SimpleNamespace(
            sha=self.sha or revision or REVISION,
            siblings=[
                SimpleNamespace(
                    rfilename=filename,
                    size=size,
                    blob_id="b" * 40,
                    lfs=None,
                )
                for filename, size in self.files.items()
            ]
        )


def sha256_info(data: bytes, *, size: int | None = None) -> RemoteFileInfo:
    return RemoteFileInfo(
        size=len(data) if size is None else size,
        sha256=hashlib.sha256(data).hexdigest(),
    )


def git_blob_info(data: bytes, *, size: int | None = None) -> RemoteFileInfo:
    digest = hashlib.sha1()
    digest.update(f"blob {len(data)}\0".encode())
    digest.update(data)
    return RemoteFileInfo(
        size=len(data) if size is None else size,
        git_blob_id=digest.hexdigest(),
    )


def remote_plan(
    spec: ModelDownloadSpec,
    files: dict[str, RemoteFileInfo],
) -> RemoteModelPlan:
    return RemoteModelPlan(spec=spec, revision=REVISION, files=files)


def event_rows(stream):
    return [json.loads(line) for line in stream.getvalue().splitlines()]


def test_configure_hub_environment_enables_online_endpoint(monkeypatch):
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setenv("TRANSFORMERS_OFFLINE", "1")
    configure_hub_environment("https://example.test")
    assert "HF_HUB_OFFLINE" not in __import__("os").environ
    assert "TRANSFORMERS_OFFLINE" not in __import__("os").environ
    assert __import__("os").environ["HF_ENDPOINT"] == "https://example.test"
    assert __import__("os").environ["HF_HUB_DISABLE_PROGRESS_BARS"] == "1"


def test_configure_hub_environment_sets_explicit_proxy(monkeypatch):
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        monkeypatch.delenv(name, raising=False)
    configure_hub_environment(
        "https://example.test",
        "http://127.0.0.1:7890",
    )
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        assert __import__("os").environ[name] == "http://127.0.0.1:7890"


def test_mirror_api_never_receives_cached_hugging_face_token(monkeypatch):
    captured = {}

    class FakeHfApi:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr("huggingface_hub.HfApi", FakeHfApi)
    create_hub_api("https://hf-mirror.com")
    assert captured == {"endpoint": "https://hf-mirror.com", "token": False}


def test_remote_plan_selects_requested_file_and_pinned_revision():
    spec = model_specs(("whisperseg",))[0]
    api = FakeApi(
        {"model.onnx": 120, "README.md": 30},
        sha=spec.revision,
    )
    plan = remote_model_plan(api, spec)
    assert plan.revision == spec.revision
    assert plan.files == {
        "model.onnx": RemoteFileInfo(size=120, git_blob_id="b" * 40)
    }
    assert plan.total_bytes == 120
    assert api.calls == [(spec.repo_id, spec.revision, True)]


def test_remote_plan_extracts_lfs_sha256_and_regular_git_blob():
    spec = ModelDownloadSpec(
        key="test",
        name="Test",
        repo_id="owner/repo",
        local_dir="models/test",
        required_files=("model.bin", "config.json"),
        filenames=("model.bin", "config.json"),
        revision=REVISION,
    )

    class MetadataApi:
        def model_info(self, *_args, **_kwargs):
            return SimpleNamespace(
                sha=REVISION,
                siblings=(
                    SimpleNamespace(
                        rfilename="model.bin",
                        size=None,
                        blob_id="c" * 40,
                        lfs={"size": 123, "sha256": "d" * 64},
                    ),
                    SimpleNamespace(
                        rfilename="config.json",
                        size=45,
                        blob_id="e" * 40,
                        lfs=None,
                    ),
                ),
            )

    plan = remote_model_plan(MetadataApi(), spec)
    assert plan.files == {
        "model.bin": RemoteFileInfo(size=123, sha256="d" * 64),
        "config.json": RemoteFileInfo(size=45, git_blob_id="e" * 40),
    }


def test_remote_plan_rejects_revision_different_from_catalog_pin():
    spec = model_specs(("whisperseg",))[0]
    with pytest.raises(RuntimeError, match="expected pinned revision"):
        remote_model_plan(FakeApi({"model.onnx": 120}, sha="f" * 40), spec)


def test_remote_plan_rejects_endpoint_without_resolved_revision():
    spec = model_specs(("whisperseg",))[0]

    class MissingRevisionApi:
        def model_info(self, *_args, **_kwargs):
            return SimpleNamespace(sha=None, siblings=())

    with pytest.raises(RuntimeError, match="returned no resolved revision"):
        remote_model_plan(MissingRevisionApi(), spec)


def test_observed_bytes_include_completed_and_incomplete_files(tmp_path):
    spec = model_specs(("whisperseg",))[0]
    plan = remote_plan(spec, {"model.onnx": RemoteFileInfo(100, sha256="0" * 64)})
    destination = spec.destination(tmp_path)
    destination.mkdir(parents=True)
    (destination / "model.onnx").write_bytes(b"x" * 40)
    incomplete = destination / ".cache/huggingface/download/file.incomplete"
    incomplete.parent.mkdir(parents=True)
    incomplete.write_bytes(b"x" * 25)
    assert observed_download_bytes(plan, tmp_path) == 65


def test_observed_bytes_include_mirror_resume_file(tmp_path):
    spec = model_specs(("whisperseg",))[0]
    plan = remote_plan(spec, {"model.onnx": RemoteFileInfo(100, sha256="0" * 64)})
    partial = spec.destination(tmp_path) / "model.onnx.incomplete"
    partial.parent.mkdir(parents=True)
    partial.write_bytes(b"x" * 35)
    assert observed_download_bytes(plan, tmp_path) == 35


def test_progress_monitor_reports_average_speed_since_this_session(monkeypatch, tmp_path):
    spec = model_specs(("whisperseg",))[0]
    plan = remote_plan(spec, {"model.onnx": RemoteFileInfo(100, sha256="0" * 64)})
    events = []
    monitor = ProgressMonitor(
        plan,
        tmp_path,
        lambda event, **payload: events.append({"type": event, **payload}),
        overall_completed=0,
        overall_total=100,
    )
    monitor._started_at = 10.0
    monitor._started_bytes = 20
    monkeypatch.setattr("download_models.time.monotonic", lambda: 15.0)

    monitor._emit_progress(downloaded=70)

    assert events == [
        {
            "type": "progress",
            "model": "whisperseg",
            "downloaded_bytes": 70,
            "total_bytes": 100,
            "overall_downloaded_bytes": 70,
            "overall_total_bytes": 100,
            "speed_bytes_per_second": 10,
            "speed_kind": "session_average",
        }
    ]


def test_mirror_download_prefers_native_hugging_face_client(monkeypatch, tmp_path):
    spec = model_specs(("whisperseg",))[0]
    plan = remote_plan(spec, {"model.onnx": RemoteFileInfo(10, sha256="0" * 64)})
    calls = []

    monkeypatch.setattr(
        "huggingface_hub.hf_hub_download",
        lambda **kwargs: calls.append(kwargs),
    )
    monkeypatch.setattr(
        "download_models.download_public_file",
        lambda *_args, **_kwargs: pytest.fail("fallback should not run"),
    )

    download_remote_plan(
        plan,
        tmp_path,
        "https://hf-mirror.com",
        max_workers=4,
    )

    assert calls[0]["filename"] == "model.onnx"
    assert calls[0]["revision"] == REVISION
    assert calls[0]["endpoint"] == "https://hf-mirror.com"
    assert calls[0]["token"] is False


def test_mirror_download_falls_back_after_native_client_error(monkeypatch, tmp_path):
    spec = model_specs(("whisperseg",))[0]
    plan = remote_plan(spec, {"model.onnx": RemoteFileInfo(10, sha256="0" * 64)})
    calls = []

    def fail_native(**_kwargs):
        raise RuntimeError("native failed")

    monkeypatch.setattr("huggingface_hub.hf_hub_download", fail_native)
    monkeypatch.setattr(
        "download_models.download_public_file",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    download_remote_plan(
        plan,
        tmp_path,
        "https://hf-mirror.com",
        max_workers=4,
    )

    assert len(calls) == 1
    assert calls[0][0][1] == "model.onnx"
    assert calls[0][1]["revision"] == REVISION


def test_compatibility_mode_skips_native_hugging_face_client(monkeypatch, tmp_path):
    spec = model_specs(("whisperseg",))[0]
    plan = remote_plan(spec, {"model.onnx": RemoteFileInfo(10, sha256="0" * 64)})
    calls = []

    monkeypatch.setattr(
        "huggingface_hub.hf_hub_download",
        lambda **_kwargs: pytest.fail("native client should not run"),
    )
    monkeypatch.setattr(
        "download_models.download_public_file",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    download_remote_plan(
        plan,
        tmp_path,
        "https://huggingface.co",
        max_workers=4,
        download_backend="compat",
    )

    assert len(calls) == 1
    assert calls[0][0][1] == "model.onnx"


def test_public_mirror_download_resumes_without_a_token(tmp_path):
    spec = ModelDownloadSpec(
        key="test",
        name="Test",
        repo_id="owner/repo",
        local_dir="models/test",
        required_files=("model.bin",),
        filenames=("model.bin",),
        revision=REVISION,
    )
    destination = spec.destination(tmp_path)
    destination.mkdir(parents=True)
    partial = destination / "model.bin.incomplete"
    partial.write_bytes(b"abc")
    data = b"abcdef"
    calls = []

    class FakeResponse:
        status_code = 206

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def raise_for_status(self):
            return None

        def iter_content(self, *, chunk_size):
            assert chunk_size == 2
            yield b"de"
            yield b"f"

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        return FakeResponse()

    download_public_file(
        spec,
        "model.bin",
        sha256_info(data),
        destination,
        "https://hf-mirror.com",
        revision=REVISION,
        request_get=fake_get,
        chunk_size=2,
    )

    assert (destination / "model.bin").read_bytes() == b"abcdef"
    assert not partial.exists()
    assert calls[0][1]["headers"] == {"Range": "bytes=3-"}
    assert "authorization" not in {
        key.lower() for key in calls[0][1]["headers"]
    }


def test_download_queue_is_catalog_ordered_and_stops_after_failure(tmp_path):
    specs = model_specs(("galtransl-7b", "whisperseg"))
    api = FakeApi(
        {
            "model.onnx": 10,
            "Sakura-Galtransl-7B-v3.7.gguf": 20,
        }
    )
    stream = io.StringIO()
    writer = EventWriter(stream)
    calls = []

    def fake_downloader(
        plan,
        root,
        endpoint,
        *,
        max_workers,
        force,
        download_backend,
    ):
        calls.append(
            (
                plan.spec.key,
                endpoint,
                max_workers,
                force,
                download_backend,
            )
        )
        if plan.spec.key == "galtransl-7b":
            raise RuntimeError("network down")
        for filename, remote in plan.files.items():
            path = plan.spec.destination(root) / filename
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"x" * remote.size)

    result = run_download_queue(
        specs,
        tmp_path,
        "https://example.test",
        writer,
        api=api,
        downloader=fake_downloader,
    )
    assert result == 1
    assert [item[0] for item in calls] == ["whisperseg", "galtransl-7b"]
    assert all(item[3] is False for item in calls)
    assert all(item[4] == "auto" for item in calls)
    rows = event_rows(stream)
    assert [row["model"] for row in rows if row["type"] == "model_started"] == [
        "whisperseg",
        "galtransl-7b",
    ]
    assert rows[-1]["type"] == "error"
    assert rows[-1]["model"] == "galtransl-7b"


def test_download_queue_skips_installed_model(tmp_path):
    spec = model_specs(("whisperseg",))[0]
    required = spec.required_paths(tmp_path)[0]
    required.parent.mkdir(parents=True)
    required.write_bytes(b"installed")
    stream = io.StringIO()
    result = run_download_queue(
        (spec,),
        tmp_path,
        "https://example.test",
        EventWriter(stream),
        api=FakeApi({"model.onnx": 10}),
        downloader=lambda *_args, **_kwargs: None,
    )
    assert result == 0
    rows = event_rows(stream)
    assert any(row["type"] == "model_skipped" for row in rows)
    assert rows[-1] == {"type": "finished", "completed": 0, "failed": 0}


def test_force_download_does_not_skip_installed_model(tmp_path):
    spec = model_specs(("whisperseg",))[0]
    required = spec.required_paths(tmp_path)[0]
    required.parent.mkdir(parents=True)
    required.write_bytes(b"installed")
    calls = []

    def fake_downloader(
        plan,
        root,
        endpoint,
        *,
        max_workers,
        force,
        download_backend,
    ):
        calls.append((plan.spec.key, force, download_backend))

    stream = io.StringIO()
    result = run_download_queue(
        (spec,),
        tmp_path,
        "https://example.test",
        EventWriter(stream),
        force=True,
        api=FakeApi({"model.onnx": len(b"installed")}),
        downloader=fake_downloader,
    )

    assert result == 0
    assert calls == [("whisperseg", True, "auto")]
    rows = event_rows(stream)
    assert not any(row["type"] == "model_skipped" for row in rows)


def test_force_public_download_keeps_old_file_until_replacement(tmp_path):
    spec = ModelDownloadSpec(
        key="test",
        name="Test",
        repo_id="owner/repo",
        local_dir="models/test",
        required_files=("model.bin",),
        filenames=("model.bin",),
    )
    destination = spec.destination(tmp_path)
    destination.mkdir(parents=True)
    target = destination / "model.bin"
    target.write_bytes(b"old")

    class FakeResponse:
        status_code = 200

        def __enter__(self):
            assert target.read_bytes() == b"old"
            return self

        def __exit__(self, *_args):
            return False

        def raise_for_status(self):
            return None

        def iter_content(self, *, chunk_size):
            yield b"replacement"

    download_public_file(
        spec,
        "model.bin",
        sha256_info(b"replacement"),
        destination,
        "https://hf-mirror.com",
        revision=REVISION,
        request_get=lambda *_args, **_kwargs: FakeResponse(),
        force=True,
    )

    assert target.read_bytes() == b"replacement"


@pytest.mark.parametrize(
    "filename",
    (
        "../outside.bin",
        "nested/../../outside.bin",
        "/absolute.bin",
        r"C:\outside.bin",
        r"nested\outside.bin",
    ),
)
def test_download_filename_rejects_traversal_and_platform_paths(filename):
    with pytest.raises(RuntimeError, match="Unsafe model filename"):
        validate_download_filename(filename)


def test_safe_download_target_rejects_symlink_escape(tmp_path):
    destination = tmp_path / "models"
    outside = tmp_path / "outside"
    destination.mkdir()
    outside.mkdir()
    (destination / "link").symlink_to(outside, target_is_directory=True)

    with pytest.raises(RuntimeError, match="escapes destination"):
        safe_download_target(destination, "link/model.bin")


def test_remote_plan_rejects_unsafe_repository_filename():
    spec = ModelDownloadSpec(
        key="test",
        name="Test",
        repo_id="owner/repo",
        local_dir="models/test",
        required_files=("model.bin",),
    )
    with pytest.raises(RuntimeError, match="Unsafe model filename"):
        remote_model_plan(FakeApi({"../outside.bin": 5}), spec)


def test_unknown_size_download_rejects_truncated_content(tmp_path):
    spec = ModelDownloadSpec(
        key="test",
        name="Test",
        repo_id="owner/repo",
        local_dir="models/test",
        required_files=("model.bin",),
        filenames=("model.bin",),
        revision=REVISION,
    )
    destination = spec.destination(tmp_path)
    destination.mkdir(parents=True)
    expected = b"complete contents"

    class FakeResponse:
        status_code = 200
        headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def raise_for_status(self):
            return None

        def iter_content(self, *, chunk_size):
            yield b"truncated"

    remote = RemoteFileInfo(
        size=None,
        sha256=hashlib.sha256(expected).hexdigest(),
    )
    with pytest.raises(RuntimeError) as error:
        download_public_file(
            spec,
            "model.bin",
            remote,
            destination,
            "https://hf-mirror.com",
            revision=REVISION,
            request_get=lambda *_args, **_kwargs: FakeResponse(),
            attempts=1,
        )

    assert isinstance(error.value.__cause__, DownloadIntegrityError)
    assert not (destination / "model.bin").exists()
    assert not (destination / "model.bin.incomplete").exists()


def test_unknown_size_download_with_correct_checksum_succeeds(tmp_path):
    spec = ModelDownloadSpec(
        key="test",
        name="Test",
        repo_id="owner/repo",
        local_dir="models/test",
        required_files=("model.bin",),
        filenames=("model.bin",),
        revision=REVISION,
    )
    destination = spec.destination(tmp_path)
    destination.mkdir(parents=True)
    data = b"complete contents"

    class FakeResponse:
        status_code = 200
        headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def raise_for_status(self):
            return None

        def iter_content(self, *, chunk_size):
            yield data

    remote = RemoteFileInfo(
        size=None,
        sha256=hashlib.sha256(data).hexdigest(),
    )
    download_public_file(
        spec,
        "model.bin",
        remote,
        destination,
        "https://hf-mirror.com",
        revision=REVISION,
        request_get=lambda *_args, **_kwargs: FakeResponse(),
    )
    assert (destination / "model.bin").read_bytes() == data


def test_compat_download_rejects_missing_checksum_metadata(tmp_path):
    spec = ModelDownloadSpec(
        key="test",
        name="Test",
        repo_id="owner/repo",
        local_dir="models/test",
        required_files=("model.bin",),
        filenames=("model.bin",),
        revision=REVISION,
    )
    with pytest.raises(RuntimeError, match="requires checksum metadata"):
        download_public_file(
            spec,
            "model.bin",
            RemoteFileInfo(size=None),
            spec.destination(tmp_path),
            "https://hf-mirror.com",
            revision=REVISION,
        )


def test_exact_size_corrupt_partial_is_not_promoted(tmp_path):
    spec = ModelDownloadSpec(
        key="test",
        name="Test",
        repo_id="owner/repo",
        local_dir="models/test",
        required_files=("model.bin",),
        filenames=("model.bin",),
        revision=REVISION,
    )
    destination = spec.destination(tmp_path)
    destination.mkdir(parents=True)
    partial = destination / "model.bin.incomplete"
    partial.write_bytes(b"wrong")
    calls = []

    class FakeResponse:
        status_code = 200
        headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def raise_for_status(self):
            return None

        def iter_content(self, *, chunk_size):
            yield b"right"

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        return FakeResponse()

    download_public_file(
        spec,
        "model.bin",
        sha256_info(b"right"),
        destination,
        "https://hf-mirror.com",
        revision=REVISION,
        request_get=fake_get,
        attempts=1,
    )

    assert calls
    assert calls[0][1]["headers"] == {}
    assert (destination / "model.bin").read_bytes() == b"right"


def test_partial_from_different_revision_is_discarded(tmp_path):
    spec = ModelDownloadSpec(
        key="test",
        name="Test",
        repo_id="owner/repo",
        local_dir="models/test",
        required_files=("model.bin",),
        filenames=("model.bin",),
        revision=REVISION,
    )
    destination = spec.destination(tmp_path)
    destination.mkdir(parents=True)
    partial = destination / "model.bin.incomplete"
    partial.write_bytes(b"old")
    partial.with_name("model.bin.incomplete.json").write_text(
        json.dumps(
            {
                "version": 1,
                "repo_id": spec.repo_id,
                "revision": "c" * 40,
                "filename": "model.bin",
                "size": 7,
                "sha256": hashlib.sha256(b"old-new").hexdigest(),
                "git_blob_id": None,
            }
        ),
        encoding="utf-8",
    )
    calls = []

    class FakeResponse:
        status_code = 200
        headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def raise_for_status(self):
            return None

        def iter_content(self, *, chunk_size):
            yield b"current"

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        return FakeResponse()

    download_public_file(
        spec,
        "model.bin",
        sha256_info(b"current"),
        destination,
        "https://hf-mirror.com",
        revision=REVISION,
        request_get=fake_get,
    )

    assert calls[0][1]["headers"] == {}
    assert (destination / "model.bin").read_bytes() == b"current"


def test_git_blob_checksum_is_verified(tmp_path):
    spec = ModelDownloadSpec(
        key="test",
        name="Test",
        repo_id="owner/repo",
        local_dir="models/test",
        required_files=("config.json",),
        filenames=("config.json",),
        revision=REVISION,
    )
    destination = spec.destination(tmp_path)
    destination.mkdir(parents=True)
    data = b'{"ok": true}'

    class FakeResponse:
        status_code = 200
        headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def raise_for_status(self):
            return None

        def iter_content(self, *, chunk_size):
            yield data

    download_public_file(
        spec,
        "config.json",
        git_blob_info(data),
        destination,
        "https://hf-mirror.com",
        revision=REVISION,
        request_get=lambda *_args, **_kwargs: FakeResponse(),
    )
    assert (destination / "config.json").read_bytes() == data
