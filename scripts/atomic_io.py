from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, TextIO


@contextmanager
def atomic_text_writer(path: Path, encoding: str = "utf-8") -> Iterator[TextIO]:
    """Write beside the destination and replace it only after a clean close."""
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".part")
    try:
        with partial.open("w", encoding=encoding) as output:
            yield output
        partial.replace(path)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise


def atomic_write_text(path: Path, content: str, encoding: str = "utf-8") -> None:
    with atomic_text_writer(path, encoding) as output:
        output.write(content)
