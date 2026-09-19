"""Local filesystem helpers for source original-file streaming.

Kept out of FastAPI routers so HTTP handlers do not open paths directly.
"""

from __future__ import annotations

from pathlib import Path


def is_readable_file(path: Path | None) -> bool:
    return bool(path is not None and path.is_file())


def read_file_size(path: Path) -> int:
    return path.stat().st_size


def read_file_byte_range(path: Path, *, start: int, end: int) -> bytes:
    with path.open("rb") as handle:
        handle.seek(start)
        return handle.read(end - start + 1)
