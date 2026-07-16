"""GUI-facing runtime primitives for the video subtitle pipeline.

This module is deliberately standard-library-only.  The CLI and a future desktop GUI can
therefore share event and cancellation semantics without importing Qt or the GPU/model stack.
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


EVENT_SCHEMA_VERSION = 1
PIPELINE_STAGES = ("extract", "asr", "translate", "ass", "quality", "cleanup")


class PipelineCancelled(Exception):
    """Raised when a cooperative pipeline cancellation has been requested."""


class CancellationToken:
    """Cancellation requested either in-process or by creating a control file.

    The file form is intentionally simple and cross-platform: the GUI owns a unique path for
    one pipeline invocation and creates it when the user presses Cancel.  A pre-existing file
    means the invocation starts cancelled; the CLI never deletes a caller-owned control file.
    """

    def __init__(self, path: Path | None = None) -> None:
        self.path = path
        self._event = threading.Event()

    def request(self) -> None:
        self._event.set()

    def is_cancelled(self) -> bool:
        return self._event.is_set() or (self.path is not None and self.path.exists())

    def raise_if_cancelled(self) -> None:
        if self.is_cancelled():
            raise PipelineCancelled("Pipeline cancellation requested")


class EventWriter:
    """Thread-safe JSONL event writer used by the CLI-to-GUI contract."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._file = None
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            self._file = path.open("w", encoding="utf-8", newline="\n")

    @property
    def enabled(self) -> bool:
        return self._file is not None

    def emit(self, event: str, **fields: Any) -> None:
        payload = {
            "schema_version": EVENT_SCHEMA_VERSION,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": event,
        }
        payload.update({key: _json_value(value) for key, value in fields.items() if value is not None})
        line = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        with self._lock:
            # A producer thread may finish just after the controlling thread closes
            # the writer during an exceptional shutdown. Late events are harmless.
            if self._file is None:
                return
            self._file.write(line + "\n")
            self._file.flush()

    def close(self) -> None:
        with self._lock:
            if self._file is not None:
                self._file.close()
                self._file = None

    def __enter__(self) -> EventWriter:
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        self.close()


def _json_value(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value
