#!/usr/bin/env python3
"""Download project models while emitting machine-readable progress events."""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
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
class RemoteModelPlan:
    spec: ModelDownloadSpec
    files: dict[str, int | None]

    @property
    def total_bytes(self) -> int | None:
        if any(size is None for size in self.files.values()):
            return None
        return sum(size for size in self.files.values() if size is not None)


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


def remote_model_plan(api: Any, spec: ModelDownloadSpec) -> RemoteModelPlan:
    info = api.model_info(
        spec.repo_id,
        revision=spec.revision,
        files_metadata=True,
    )
    available = {
        sibling.rfilename: getattr(sibling, "size", None)
        for sibling in (info.siblings or ())
    }
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
    return RemoteModelPlan(spec=spec, files=selected)


def observed_download_bytes(
    plan: RemoteModelPlan,
    root: Path,
    *,
    include_completed: bool = True,
) -> int:
    destination = plan.spec.destination(root)
    completed = 0
    adjacent_incomplete = 0
    for relative, expected in plan.files.items():
        path = destination / Path(relative)
        partial = path.with_name(path.name + ".incomplete")
        if include_completed and path.is_file() and not partial.is_file():
            size = path.stat().st_size
            completed += min(size, expected) if expected is not None else size
        if partial.is_file():
            size = partial.stat().st_size
            adjacent_incomplete += (
                min(size, expected) if expected is not None else size
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
            "revision": plan.spec.revision,
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

    for filename, expected_size in plan.files.items():
        logging.warning("Compatibility download: %s/%s", plan.spec.repo_id, filename)
        download_public_file(
            plan.spec,
            filename,
            expected_size,
            destination,
            endpoint,
            force=force,
        )


def download_public_file(
    spec: ModelDownloadSpec,
    filename: str,
    expected_size: int | None,
    destination: Path,
    endpoint: str,
    *,
    request_get: Callable[..., Any] | None = None,
    chunk_size: int = 1024 * 1024,
    attempts: int = 3,
    force: bool = False,
) -> None:
    """Download one public file with Range resume, without forwarding an HF token."""
    import requests
    from huggingface_hub import hf_hub_url

    if attempts <= 0:
        raise ValueError("attempts must be positive")
    target = destination / Path(filename)
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".incomplete")
    if force and partial.is_file():
        partial.unlink()
    if not force and not partial.is_file() and target.is_file() and (
        expected_size is None or target.stat().st_size == expected_size
    ):
        return
    if partial.is_file() and expected_size is not None:
        partial_size = partial.stat().st_size
        if partial_size == expected_size:
            partial.replace(target)
            return
        if partial_size > expected_size:
            partial.unlink()

    url = hf_hub_url(
        spec.repo_id,
        filename,
        revision=spec.revision,
        endpoint=endpoint,
    )
    getter = request_get or requests.get
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        offset = partial.stat().st_size if partial.is_file() else 0
        headers = {"Range": f"bytes={offset}-"} if offset else {}
        try:
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
                if response.status_code == 416 and expected_size == offset:
                    partial.replace(target)
                    return
                response.raise_for_status()
                append = offset > 0 and response.status_code == 206
                with partial.open("ab" if append else "wb") as stream:
                    for chunk in response.iter_content(chunk_size=chunk_size):
                        if chunk:
                            stream.write(chunk)
            actual_size = partial.stat().st_size
            if expected_size is not None and actual_size != expected_size:
                raise RuntimeError(
                    f"Incomplete response for {filename}: "
                    f"expected {expected_size} bytes, received {actual_size}"
                )
            partial.replace(target)
            return
        except Exception as exc:
            last_error = exc
            if attempt < attempts:
                time.sleep(min(2 ** (attempt - 1), 4))
    raise RuntimeError(
        f"Could not download {spec.repo_id}/{filename} after {attempts} attempts"
    ) from last_error


def validate_downloaded_model(plan: RemoteModelPlan, root: Path) -> None:
    missing = [
        path
        for path in plan.spec.required_paths(root)
        if not path.is_file() or path.stat().st_size <= 0
    ]
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
