#!/usr/bin/env python3
"""Download project models while emitting machine-readable progress events."""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Callable
from urllib.parse import urlsplit

from model_catalog import (
    MODEL_DOWNLOAD_ENDPOINTS,
    MODEL_DOWNLOAD_SPECS,
    ModelDownloadSpec,
    ModelInstallState,
    model_install_state,
    model_specs,
)
from portable_runtime import project_root


@dataclass(frozen=True)
class RemoteFileInfo:
    size: int | None
    sha256: str | None = None
    git_blob_id: str | None = None

    @property
    def digest(self) -> tuple[str, str] | None:
        if self.sha256 is not None:
            return ("sha256", self.sha256)
        if self.git_blob_id is not None:
            return ("git-sha1", self.git_blob_id)
        return None


@dataclass(frozen=True)
class RemoteModelPlan:
    spec: ModelDownloadSpec
    revision: str
    files: dict[str, RemoteFileInfo]

    @property
    def total_bytes(self) -> int | None:
        sizes = [remote.size for remote in self.files.values()]
        if any(size is None for size in sizes):
            return None
        return sum(size for size in sizes if size is not None)


class DownloadIntegrityError(RuntimeError):
    """Downloaded bytes do not match trusted remote metadata."""


def validate_download_filename(filename: str) -> PurePosixPath:
    """Return a safe Hub-relative path or reject traversal/platform tricks."""
    if not filename or "\\" in filename:
        raise RuntimeError(f"Unsafe model filename: {filename!r}")
    posix = PurePosixPath(filename)
    windows = PureWindowsPath(filename)
    if (
        posix.is_absolute()
        or windows.is_absolute()
        or windows.drive
        or any(part in {"", ".", ".."} for part in posix.parts)
    ):
        raise RuntimeError(f"Unsafe model filename: {filename!r}")
    return posix


def safe_download_target(destination: Path, filename: str) -> Path:
    relative = validate_download_filename(filename)
    root = destination.resolve()
    target = destination.joinpath(*relative.parts)
    resolved = target.resolve()
    if resolved == root or not resolved.is_relative_to(root):
        raise RuntimeError(f"Model filename escapes destination: {filename!r}")
    return target


class EventWriter:
    def __init__(self, stream: Any = sys.stdout) -> None:
        self.stream = stream
        self._lock = threading.Lock()

    def emit(self, event_type: str, **payload: object) -> None:
        message = {"type": event_type, **payload}
        with self._lock:
            print(json.dumps(message, ensure_ascii=False), file=self.stream, flush=True)


class ProgressMonitor:
    def __init__(
        self,
        plan: RemoteModelPlan,
        root: Path,
        emit: Callable[..., None],
        *,
        overall_completed: int,
        overall_total: int | None,
        force: bool = False,
        interval: float = 0.4,
    ) -> None:
        self.plan = plan
        self.root = root
        self.emit = emit
        self.overall_completed = overall_completed
        self.overall_total = overall_total
        self.force = force
        self.interval = interval
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._started_at = 0.0
        self._started_bytes = 0

    def start(self) -> None:
        self._started_at = time.monotonic()
        self._started_bytes = observed_download_bytes(
            self.plan,
            self.root,
            include_completed=not self.force,
        )
        self._thread = threading.Thread(target=self._run, name="model-download-progress", daemon=True)
        self._thread.start()

    def stop(self, *, completed: bool = False) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=max(1.0, self.interval * 3))
        downloaded = self.plan.total_bytes if completed else None
        self._emit_progress(downloaded=downloaded)

    def _run(self) -> None:
        self._emit_progress(downloaded=self._started_bytes)
        while not self._stop_event.wait(self.interval):
            downloaded = observed_download_bytes(
                self.plan,
                self.root,
                include_completed=not self.force,
            )
            self._emit_progress(downloaded=downloaded)

    def _emit_progress(self, *, downloaded: int | None = None) -> None:
        if downloaded is None:
            downloaded = observed_download_bytes(
                self.plan,
                self.root,
                include_completed=not self.force,
            )
        model_total = self.plan.total_bytes
        if model_total is not None:
            downloaded = min(downloaded, model_total)
        overall_downloaded = self.overall_completed + downloaded
        if self.overall_total is not None:
            overall_downloaded = min(overall_downloaded, self.overall_total)
        elapsed = max(0.001, time.monotonic() - self._started_at)
        transferred = max(0, downloaded - self._started_bytes)
        average_speed = transferred / elapsed
        self.emit(
            "progress",
            model=self.plan.spec.key,
            downloaded_bytes=downloaded,
            total_bytes=model_total,
            overall_downloaded_bytes=overall_downloaded,
            overall_total_bytes=self.overall_total,
            speed_bytes_per_second=round(average_speed),
            speed_kind="session_average",
        )


def configure_hub_environment(endpoint: str, proxy: str | None = None) -> None:
    os.environ.pop("HF_HUB_OFFLINE", None)
    os.environ.pop("TRANSFORMERS_OFFLINE", None)
    os.environ["HF_ENDPOINT"] = endpoint
    os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
    if proxy:
        for name in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
            os.environ[name] = proxy


def create_hub_api(endpoint: str, proxy: str | None = None) -> Any:
    configure_hub_environment(endpoint, proxy)
    from huggingface_hub import HfApi

    token = False if endpoint == MODEL_DOWNLOAD_ENDPOINTS["mirror"] else None
    return HfApi(endpoint=endpoint, token=token)


def _validated_digest(value: object, *, length: int, label: str) -> str | None:
    if value is None:
        return None
    text = str(value).lower()
    if len(text) != length:
        raise RuntimeError(f"Invalid {label} metadata: {value!r}")
    try:
        int(text, 16)
    except ValueError as exc:
        raise RuntimeError(f"Invalid {label} metadata: {value!r}") from exc
    return text


def _remote_file_info(sibling: Any) -> RemoteFileInfo:
    lfs = getattr(sibling, "lfs", None)
    if isinstance(lfs, dict):
        lfs_size = lfs.get("size")
        lfs_sha256 = lfs.get("sha256")
    else:
        lfs_size = getattr(lfs, "size", None)
        lfs_sha256 = getattr(lfs, "sha256", None)
    size = getattr(sibling, "size", None)
    if size is None:
        size = lfs_size
    if size is not None:
        size = int(size)
        if size < 0:
            raise RuntimeError(f"Invalid remote file size: {size}")
    sha256 = _validated_digest(
        lfs_sha256,
        length=64,
        label="LFS SHA-256",
    )
    # For an LFS object, blob_id identifies the small Git pointer rather than
    # the downloaded weight bytes. Only use Git blob verification for ordinary
    # repository files.
    git_blob_id = (
        None
        if lfs is not None
        else _validated_digest(
            getattr(sibling, "blob_id", None),
            length=40,
            label="Git blob ID",
        )
    )
    return RemoteFileInfo(
        size=size,
        sha256=sha256,
        git_blob_id=git_blob_id,
    )


def remote_model_plan(api: Any, spec: ModelDownloadSpec) -> RemoteModelPlan:
    info = api.model_info(
        spec.repo_id,
        revision=spec.revision,
        files_metadata=True,
    )
    resolved_revision = str(getattr(info, "sha", "") or "")
    if not resolved_revision:
        raise RuntimeError(f"{spec.repo_id} returned no resolved revision")
    resolved_revision = _validated_digest(
        resolved_revision,
        length=40,
        label="resolved revision",
    )
    assert resolved_revision is not None
    if spec.revision is not None:
        pinned_revision = _validated_digest(
            spec.revision,
            length=40,
            label="pinned revision",
        )
        if pinned_revision != resolved_revision:
            raise RuntimeError(
                f"{spec.repo_id} resolved to {resolved_revision}, "
                f"expected pinned revision {pinned_revision}"
            )
    available: dict[str, RemoteFileInfo] = {}
    for sibling in info.siblings or ():
        filename = str(sibling.rfilename)
        validate_download_filename(filename)
        available[filename] = _remote_file_info(sibling)
    if spec.filenames:
        missing = [filename for filename in spec.filenames if filename not in available]
        if missing:
            raise RuntimeError(
                f"{spec.repo_id} does not contain: {', '.join(missing)}"
            )
        selected = {filename: available[filename] for filename in spec.filenames}
    else:
        selected = available
    if not selected:
        raise RuntimeError(f"{spec.repo_id} returned no downloadable files")
    return RemoteModelPlan(
        spec=spec,
        revision=resolved_revision,
        files=selected,
    )


def observed_download_bytes(
    plan: RemoteModelPlan,
    root: Path,
    *,
    include_completed: bool = True,
) -> int:
    destination = plan.spec.destination(root)
    completed = 0
    adjacent_incomplete = 0
    for relative, remote in plan.files.items():
        path = safe_download_target(destination, relative)
        partial = path.with_name(path.name + ".incomplete")
        if include_completed and path.is_file() and not partial.is_file():
            size = path.stat().st_size
            completed += (
                min(size, remote.size)
                if remote.size is not None
                else size
            )
        if partial.is_file():
            size = partial.stat().st_size
            adjacent_incomplete += (
                min(size, remote.size)
                if remote.size is not None
                else size
            )

    incomplete = 0
    cache = destination / ".cache" / "huggingface"
    if cache.is_dir():
        incomplete = sum(
            path.stat().st_size
            for path in cache.rglob("*.incomplete")
            if path.is_file()
        )
    total = completed + adjacent_incomplete + incomplete
    plan_total = plan.total_bytes
    return min(total, plan_total) if plan_total is not None else total


def download_remote_plan(
    plan: RemoteModelPlan,
    root: Path,
    endpoint: str,
    *,
    max_workers: int,
    force: bool = False,
    download_backend: str = "auto",
) -> None:
    if download_backend not in {"auto", "compat"}:
        raise ValueError(f"Unknown download backend: {download_backend}")
    configure_hub_environment(endpoint)
    from huggingface_hub import hf_hub_download, snapshot_download

    destination = plan.spec.destination(root)
    destination.mkdir(parents=True, exist_ok=True)
    if download_backend == "auto":
        common = {
            "repo_id": plan.spec.repo_id,
            "revision": plan.revision,
            "local_dir": destination,
            "endpoint": endpoint,
            "force_download": force,
        }
        if endpoint == MODEL_DOWNLOAD_ENDPOINTS["mirror"]:
            common["token"] = False
        try:
            if plan.spec.filenames:
                for filename in plan.spec.filenames:
                    hf_hub_download(filename=filename, **common)
            else:
                snapshot_download(max_workers=max_workers, **common)
            return
        except Exception as exc:
            logging.warning(
                "Native Hugging Face/Xet download failed; using the "
                "compatibility HTTP fallback: %s",
                exc,
            )

    for filename, remote in plan.files.items():
        logging.warning("Compatibility download: %s/%s", plan.spec.repo_id, filename)
        download_public_file(
            plan.spec,
            filename,
            remote,
            destination,
            endpoint,
            revision=plan.revision,
            force=force,
        )


def _partial_metadata_path(partial: Path) -> Path:
    return partial.with_name(partial.name + ".json")


def _download_identity(
    spec: ModelDownloadSpec,
    filename: str,
    revision: str,
    remote: RemoteFileInfo,
) -> dict[str, object]:
    return {
        "version": 1,
        "repo_id": spec.repo_id,
        "revision": revision,
        "filename": filename,
        "size": remote.size,
        "sha256": remote.sha256,
        "git_blob_id": remote.git_blob_id,
    }


def _read_partial_identity(path: Path) -> dict[str, object] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _write_partial_identity(path: Path, identity: dict[str, object]) -> None:
    if path.is_symlink():
        raise RuntimeError(f"Refusing to write through symlink: {path}")
    temporary = path.with_name(path.name + ".tmp")
    if temporary.is_symlink():
        raise RuntimeError(f"Refusing to write through symlink: {temporary}")
    temporary.write_text(
        json.dumps(identity, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    temporary.replace(path)


def _remove_partial(partial: Path, metadata: Path) -> None:
    if partial.is_file() or partial.is_symlink():
        partial.unlink()
    if metadata.is_file() or metadata.is_symlink():
        metadata.unlink()


def _new_remote_hasher(
    remote: RemoteFileInfo,
    *,
    content_size: int | None,
) -> Any | None:
    if remote.sha256 is not None:
        return hashlib.sha256()
    if remote.git_blob_id is not None and content_size is not None:
        digest = hashlib.sha1()
        digest.update(f"blob {content_size}\0".encode())
        return digest
    return None


def _feed_hasher_from_file(hasher: Any, path: Path) -> None:
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            hasher.update(chunk)


def _remote_file_matches(
    path: Path,
    remote: RemoteFileInfo,
    *,
    prepared_hasher: Any | None = None,
) -> bool:
    if not path.is_file() or path.is_symlink():
        return False
    actual_size = path.stat().st_size
    if remote.size is not None and actual_size != remote.size:
        return False
    expected_digest = remote.digest
    if expected_digest is None:
        return False
    algorithm, expected = expected_digest
    hasher = prepared_hasher
    if hasher is None:
        hasher = _new_remote_hasher(remote, content_size=actual_size)
        if hasher is None:
            return False
        _feed_hasher_from_file(hasher, path)
    if algorithm not in {"sha256", "git-sha1"}:
        return False
    return hasher.hexdigest().lower() == expected


def download_public_file(
    spec: ModelDownloadSpec,
    filename: str,
    remote: RemoteFileInfo,
    destination: Path,
    endpoint: str,
    *,
    revision: str,
    request_get: Callable[..., Any] | None = None,
    chunk_size: int = 1024 * 1024,
    attempts: int = 3,
    force: bool = False,
) -> None:
    """Download and verify one public file without forwarding an HF token."""
    import requests
    from huggingface_hub import hf_hub_url

    if attempts <= 0:
        raise ValueError("attempts must be positive")
    if remote.digest is None:
        raise RuntimeError(
            f"Compatibility download requires checksum metadata: "
            f"{spec.repo_id}/{filename}"
        )
    target = safe_download_target(destination, filename)
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".incomplete")
    metadata = _partial_metadata_path(partial)
    for path in (target, partial, metadata):
        if path.is_symlink():
            raise RuntimeError(f"Refusing to use model-file symlink: {path}")

    identity = _download_identity(spec, filename, revision, remote)
    if force:
        _remove_partial(partial, metadata)
    elif partial.is_file():
        stored_identity = _read_partial_identity(metadata)
        if stored_identity is not None and stored_identity != identity:
            logging.warning(
                "Discarding partial file from a different revision: %s",
                filename,
            )
            _remove_partial(partial, metadata)
    if partial.is_file() and not metadata.is_file():
        # Legacy partials have no identity sidecar. Reuse them once, but final
        # checksum verification still prevents mixed revisions from promotion.
        _write_partial_identity(metadata, identity)
    if not force and not partial.is_file() and _remote_file_matches(target, remote):
        return
    if partial.is_file() and remote.size is not None:
        partial_size = partial.stat().st_size
        if partial_size == remote.size:
            if _remote_file_matches(partial, remote):
                partial.replace(target)
                metadata.unlink(missing_ok=True)
                return
            _remove_partial(partial, metadata)
        elif partial_size > remote.size:
            _remove_partial(partial, metadata)

    url = hf_hub_url(
        spec.repo_id,
        filename,
        revision=revision,
        endpoint=endpoint,
    )
    getter = request_get or requests.get
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        offset = partial.stat().st_size if partial.is_file() else 0
        headers = {"Range": f"bytes={offset}-"} if offset else {}
        try:
            _write_partial_identity(metadata, identity)
            with getter(
                url,
                headers=headers,
                stream=True,
                allow_redirects=True,
                timeout=(15, 60),
            ) as response:
                final_url = str(getattr(response, "url", "") or "")
                if final_url and urlsplit(final_url).netloc != urlsplit(url).netloc:
                    logging.warning(
                        "Download redirected: %s -> %s",
                        urlsplit(url).netloc,
                        urlsplit(final_url).netloc,
                    )
                if response.status_code == 416:
                    if _remote_file_matches(partial, remote):
                        partial.replace(target)
                        metadata.unlink(missing_ok=True)
                        return
                    raise DownloadIntegrityError(
                        f"Range-complete file failed verification: {filename}"
                    )
                response.raise_for_status()
                append = offset > 0 and response.status_code == 206
                response_headers = getattr(response, "headers", {})
                content_range = (
                    response_headers.get("Content-Range")
                    if hasattr(response_headers, "get")
                    else None
                )
                if append and content_range and not str(content_range).startswith(
                    f"bytes {offset}-"
                ):
                    raise DownloadIntegrityError(
                        f"Unexpected Content-Range for {filename}: {content_range}"
                    )
                hasher = _new_remote_hasher(
                    remote,
                    content_size=remote.size,
                )
                if append and hasher is not None:
                    _feed_hasher_from_file(hasher, partial)
                with partial.open("ab" if append else "wb") as stream:
                    for chunk in response.iter_content(chunk_size=chunk_size):
                        if not chunk:
                            continue
                        stream.write(chunk)
                        if hasher is not None:
                            hasher.update(chunk)
            if not _remote_file_matches(
                partial,
                remote,
                prepared_hasher=hasher,
            ):
                raise DownloadIntegrityError(
                    f"Downloaded file failed size or checksum verification: {filename}"
                )
            partial.replace(target)
            metadata.unlink(missing_ok=True)
            return
        except Exception as exc:
            last_error = exc
            if isinstance(exc, DownloadIntegrityError):
                _remove_partial(partial, metadata)
            if attempt < attempts:
                time.sleep(min(2 ** (attempt - 1), 4))
    raise RuntimeError(
        f"Could not download {spec.repo_id}/{filename} after {attempts} attempts"
    ) from last_error


def validate_downloaded_model(plan: RemoteModelPlan, root: Path) -> None:
    destination = plan.spec.destination(root)
    invalid: list[Path] = []
    for filename, remote in plan.files.items():
        path = safe_download_target(destination, filename)
        if not path.is_file():
            invalid.append(path)
            continue
        size = path.stat().st_size
        if size <= 0 or (remote.size is not None and size != remote.size):
            invalid.append(path)
    missing_required = [
        path
        for path in plan.spec.required_paths(root)
        if not path.is_file() or path.stat().st_size <= 0
    ]
    missing = list(dict.fromkeys([*invalid, *missing_required]))
    if missing:
        relative = ", ".join(str(path.relative_to(root)) for path in missing)
        raise RuntimeError(f"Downloaded model is incomplete: {relative}")


def prepare_plans(
    specs: tuple[ModelDownloadSpec, ...],
    root: Path,
    api: Any,
    writer: EventWriter,
    *,
    force: bool = False,
) -> tuple[RemoteModelPlan, ...]:
    plans: list[RemoteModelPlan] = []
    for spec in specs:
        state = model_install_state(spec, root)
        if state == ModelInstallState.INSTALLED and not force:
            writer.emit("model_skipped", model=spec.key, reason="installed")
            continue
        writer.emit("model_query_started", model=spec.key)
        plan = remote_model_plan(api, spec)
        plans.append(plan)
        writer.emit(
            "model_queued",
            model=spec.key,
            total_bytes=plan.total_bytes,
            state=state.value,
        )
    return tuple(plans)


def run_download_queue(
    specs: tuple[ModelDownloadSpec, ...],
    root: Path,
    endpoint: str,
    writer: EventWriter,
    *,
    max_workers: int = 4,
    force: bool = False,
    proxy: str | None = None,
    download_backend: str = "auto",
    api: Any | None = None,
    downloader: Callable[..., None] = download_remote_plan,
) -> int:
    try:
        hub_api = api if api is not None else create_hub_api(endpoint, proxy)
        plans = prepare_plans(specs, root, hub_api, writer, force=force)
    except Exception as exc:
        logging.exception("Model download preflight failed")
        writer.emit(
            "error",
            phase="preflight",
            error_type=type(exc).__name__,
            message=str(exc),
        )
        return 1

    known_totals = [plan.total_bytes for plan in plans]
    overall_total = (
        sum(total for total in known_totals if total is not None)
        if all(total is not None for total in known_totals)
        else None
    )
    writer.emit(
        "queue_started",
        model_count=len(plans),
        overall_total_bytes=overall_total,
    )
    overall_completed = 0
    for index, plan in enumerate(plans, start=1):
        writer.emit(
            "model_started",
            model=plan.spec.key,
            index=index,
            count=len(plans),
            total_bytes=plan.total_bytes,
        )
        monitor = ProgressMonitor(
            plan,
            root,
            writer.emit,
            overall_completed=overall_completed,
            overall_total=overall_total,
            force=force,
        )
        monitor.start()
        try:
            downloader(
                plan,
                root,
                endpoint,
                max_workers=max_workers,
                force=force,
                download_backend=download_backend,
            )
            validate_downloaded_model(plan, root)
        except Exception as exc:
            logging.exception("Model download failed: %s", plan.spec.key)
            monitor.stop()
            writer.emit(
                "error",
                phase="download",
                model=plan.spec.key,
                error_type=type(exc).__name__,
                message=str(exc),
            )
            return 1
        monitor.stop(completed=True)
        model_total = plan.total_bytes
        if model_total is not None:
            overall_completed += model_total
        writer.emit(
            "model_completed",
            model=plan.spec.key,
            index=index,
            count=len(plans),
        )
    writer.emit("finished", completed=len(plans), failed=0)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Download jp2zh model files.")
    parser.add_argument(
        "--model",
        action="append",
        required=True,
        choices=tuple(spec.key for spec in MODEL_DOWNLOAD_SPECS),
        help="Model catalog key; repeat to download multiple models",
    )
    parser.add_argument(
        "--proxy",
        help="HTTP(S) proxy URL, for example http://127.0.0.1:7890",
    )
    parser.add_argument(
        "--source",
        choices=tuple(MODEL_DOWNLOAD_ENDPOINTS),
        default="official",
    )
    parser.add_argument(
        "--download-backend",
        choices=("auto", "compat"),
        default="auto",
        help=(
            "auto prefers the Hugging Face/Xet client with an HTTP fallback; "
            "compat uses resumable HTTP directly"
        ),
    )
    parser.add_argument("--root", type=Path, default=project_root(Path(__file__)))
    parser.add_argument("--max-workers", type=int, default=4)
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-download selected models and replace existing files",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.max_workers <= 0:
        raise SystemExit("--max-workers must be positive")
    if args.proxy:
        configure_hub_environment(MODEL_DOWNLOAD_ENDPOINTS[args.source], args.proxy)
    endpoint = MODEL_DOWNLOAD_ENDPOINTS[args.source]
    selected = model_specs(args.model)
    writer = EventWriter()
    writer.emit(
        "started",
        source=args.source,
        endpoint=endpoint,
        models=[spec.key for spec in selected],
        proxy_enabled=bool(args.proxy),
        download_backend=args.download_backend,
    )
    return run_download_queue(
        selected,
        args.root.resolve(),
        endpoint,
        writer,
        max_workers=args.max_workers,
        force=args.force,
        proxy=args.proxy,
        download_backend=args.download_backend,
    )


if __name__ == "__main__":
    raise SystemExit(main())
