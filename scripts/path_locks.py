"""Non-blocking, process-lifetime path reservations on Linux and Windows."""
from __future__ import annotations

import errno
import hashlib
import os
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import Iterable, Iterator


class PathInUseError(RuntimeError):
    pass


def _path_key(path: Path) -> str:
    return os.path.normcase(str(path.expanduser().resolve()))


@contextmanager
def _lock_path(path: Path, namespace: str) -> Iterator[None]:
    # The portable launcher overrides TEMP; using gettempdir() would give a
    # portable GUI and a source CLI separate locks for the exact same output.
    directory = Path.home() / ".cache" / "jp2zh-video-subs" / "locks"
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    digest = hashlib.sha256(f"{namespace}:{_path_key(path)}".encode()).hexdigest()
    # Keep the lock file: unlinking it could let another process lock a new inode
    # while a contender still holds the old one. The OS releases locks on exit.
    fd = os.open(directory / f"{digest}.lock", os.O_RDWR | os.O_CREAT, 0o600)
    with os.fdopen(fd, "r+b", buffering=0) as handle:
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                raise PathInUseError(f"Path is already in use by another task: {path}") from exc
            raise
        try:
            yield
        finally:
            if os.name == "nt":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def path_locks(paths: Iterable[Path], *, namespace: str = "pipeline") -> Iterator[None]:
    """Reserve all paths or release every acquired reservation on failure."""
    unique = {_path_key(path): path for path in paths}
    with ExitStack() as stack:
        for key in sorted(unique):
            stack.enter_context(_lock_path(unique[key], namespace))
        yield
