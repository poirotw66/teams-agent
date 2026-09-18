"""Opaque source-identity helpers shared by Portal, Agent, and Backoffice."""

from __future__ import annotations

import hashlib
from pathlib import Path

__all__ = [
    "make_source_ref_id",
    "safe_source_path",
    "source_path_stem",
]


def make_source_ref_id(
    *,
    release_id: str | None,
    document_id: str | None,
    version_id: str | None,
    chunk_id: str | None,
    source_path: str | None = None,
) -> str | None:
    """Return a stable, opaque identifier for one cited index chunk."""

    if not chunk_id and not source_path:
        return None
    payload = "\x1f".join(
        str(value or "") for value in (release_id, document_id, version_id, chunk_id, source_path)
    )
    return f"src-{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:24]}"


def source_path_stem(source_path: str | None) -> str | None:
    if not source_path:
        return None
    return Path(source_path.replace("\\", "/")).stem or None


def safe_source_path(source_path: str | None) -> str | None:
    """Only expose repository-relative source paths, never signed/blob URLs."""

    if not source_path:
        return None
    candidate = str(source_path).replace("\\", "/")
    if "://" in candidate or candidate.startswith(("/", "~")):
        return "[REDACTED_SOURCE]"
    if "?" in candidate or "#" in candidate:
        candidate = candidate.split("?", 1)[0].split("#", 1)[0]
    parts = [part for part in candidate.split("/") if part not in {"", "."}]
    if ".." in parts:
        return "[REDACTED_SOURCE]"
    return "/".join(parts) or None
