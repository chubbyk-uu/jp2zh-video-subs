from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import tempfile
from typing import Iterator, TextIO

from path_locks import path_locks


@contextmanager
def atomic_text_writer(path: Path, encoding: str = "utf-8") -> Iterator[TextIO]:
    """Reserve the destination and atomically promote a writer-owned temporary file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path_locks([path], namespace="writer"):
        output = tempfile.NamedTemporaryFile(mode="w", encoding=encoding, dir=path.parent,
                                             prefix=path.name + ".", suffix=".part", delete=False)
        partial = Path(output.name)
        try:
            with output:
                yield output
            partial.replace(path)
        finally:
            partial.unlink(missing_ok=True)


def atomic_write_text(path: Path, content: str, encoding: str = "utf-8") -> None:
    with atomic_text_writer(path, encoding) as output:
        output.write(content)
