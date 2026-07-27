import io
import json
from types import SimpleNamespace

import pytest

from download_models import (
    EventWriter,
    ProgressMonitor,
    RemoteModelPlan,
    configure_hub_environment,
    create_hub_api,
    download_remote_plan,
    download_public_file,
    observed_download_bytes,
    remote_model_plan,
    run_download_queue,
)
from model_catalog import ModelDownloadSpec, model_specs


class FakeApi:
    def __init__(self, files):
        self.files = files
        self.calls = []

    def model_info(self, repo_id, *, revision, files_metadata):
        self.calls.append((repo_id, revision, files_metadata))
        return SimpleNamespace(
            siblings=[
                SimpleNamespace(rfilename=filename, size=size)
                for filename, size in self.files.items()
            ]
        )


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
    api = FakeApi({"model.onnx": 120, "README.md": 30})
    plan = remote_model_plan(api, spec)
    assert plan.files == {"model.onnx": 120}
    assert plan.total_bytes == 120
    assert api.calls == [(spec.repo_id, spec.revision, True)]


def test_observed_bytes_include_completed_and_incomplete_files(tmp_path):
    spec = model_specs(("whisperseg",))[0]
    plan = RemoteModelPlan(spec, {"model.onnx": 100})
    destination = spec.destination(tmp_path)
    destination.mkdir(parents=True)
    (destination / "model.onnx").write_bytes(b"x" * 40)
    incomplete = destination / ".cache/huggingface/download/file.incomplete"
    incomplete.parent.mkdir(parents=True)
    incomplete.write_bytes(b"x" * 25)
    assert observed_download_bytes(plan, tmp_path) == 65


def test_observed_bytes_include_mirror_resume_file(tmp_path):
    spec = model_specs(("whisperseg",))[0]
    plan = RemoteModelPlan(spec, {"model.onnx": 100})
    partial = spec.destination(tmp_path) / "model.onnx.incomplete"
    partial.parent.mkdir(parents=True)
    partial.write_bytes(b"x" * 35)
    assert observed_download_bytes(plan, tmp_path) == 35


def test_progress_monitor_reports_average_speed_since_this_session(monkeypatch, tmp_path):
    spec = model_specs(("whisperseg",))[0]
    plan = RemoteModelPlan(spec, {"model.onnx": 100})
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
    plan = RemoteModelPlan(spec, {"model.onnx": 10})
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
    assert calls[0]["endpoint"] == "https://hf-mirror.com"
    assert calls[0]["token"] is False


def test_mirror_download_falls_back_after_native_client_error(monkeypatch, tmp_path):
    spec = model_specs(("whisperseg",))[0]
    plan = RemoteModelPlan(spec, {"model.onnx": 10})
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


def test_compatibility_mode_skips_native_hugging_face_client(monkeypatch, tmp_path):
    spec = model_specs(("whisperseg",))[0]
    plan = RemoteModelPlan(spec, {"model.onnx": 10})
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
        revision="revision",
    )
    destination = spec.destination(tmp_path)
    destination.mkdir(parents=True)
    partial = destination / "model.bin.incomplete"
    partial.write_bytes(b"abc")
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
        6,
        destination,
        "https://hf-mirror.com",
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
        for required in plan.spec.required_paths(root):
            required.parent.mkdir(parents=True, exist_ok=True)
            required.write_bytes(b"complete")

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
        len(b"replacement"),
        destination,
        "https://hf-mirror.com",
        request_get=lambda *_args, **_kwargs: FakeResponse(),
        force=True,
    )

    assert target.read_bytes() == b"replacement"
