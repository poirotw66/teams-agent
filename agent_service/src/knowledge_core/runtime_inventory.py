"""Runtime QA artifact inventory for knowledge release manifests."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from knowledge_core.artifacts import INDEX_RELATIVE_PATH, MANIFEST_FILENAME

__all__ = [
    "QA_SYNC_EXCLUDED_PREFIXES",
    "QA_SYNC_INCLUDED_PREFIXES",
    "RuntimeArtifactEntry",
    "build_runtime_artifact_inventory",
    "has_complete_runtime_inventory",
    "is_qa_sync_relative_path",
    "parse_runtime_artifact_inventory",
    "safe_release_relative_path",
    "sha256_file",
    "verification_hash_for_inventory",
    "verify_local_artifact_entry",
]


QA_SYNC_INCLUDED_PREFIXES: tuple[str, ...] = (
    "index/",
    "sources/",
    "assets/",
    "catalog/",
    "acl/",
)
QA_SYNC_EXCLUDED_PREFIXES: tuple[str, ...] = (
    "original/",
    "file-search/",
)


@dataclass(frozen=True)
class RuntimeArtifactEntry:
    """One immutable QA artifact pinned by generation, size, and hash."""

    relative_path: str
    generation: int
    size_bytes: int
    sha256: str

    def to_manifest_dict(self) -> dict[str, object]:
        return {
            "path": self.relative_path,
            "generation": self.generation,
            "sizeBytes": self.size_bytes,
            "sha256": self.sha256,
        }


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def safe_release_relative_path(value: object) -> PurePosixPath:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Artifact path must be a non-empty relative string.")
    path = PurePosixPath(value.strip())
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise ValueError(f"Unsafe artifact path: {value!r}")
    return path


def is_qa_sync_relative_path(relative_path: str) -> bool:
    """Return True when a release-relative path belongs in the QA sync inventory."""
    normalized = relative_path.strip().lstrip("/")
    if not normalized or normalized == MANIFEST_FILENAME:
        return False
    if any(normalized.startswith(prefix) for prefix in QA_SYNC_EXCLUDED_PREFIXES):
        return False
    if normalized == INDEX_RELATIVE_PATH:
        return True
    return any(normalized.startswith(prefix) for prefix in QA_SYNC_INCLUDED_PREFIXES)


def build_runtime_artifact_inventory(
    *,
    generations: dict[str, int],
    release_dir: Path,
) -> list[RuntimeArtifactEntry]:
    """Build inventory entries for QA-required objects already uploaded to GCS."""
    entries: list[RuntimeArtifactEntry] = []
    for relative_path, generation in sorted(generations.items()):
        if not is_qa_sync_relative_path(relative_path):
            continue
        local_path = release_dir.joinpath(*PurePosixPath(relative_path).parts)
        if not local_path.is_file():
            raise FileNotFoundError(
                f"QA inventory path missing from release directory: {relative_path}"
            )
        entries.append(
            RuntimeArtifactEntry(
                relative_path=relative_path,
                generation=int(generation),
                size_bytes=local_path.stat().st_size,
                sha256=sha256_file(local_path),
            )
        )
    if not any(entry.relative_path == INDEX_RELATIVE_PATH for entry in entries):
        raise ValueError(
            f"Runtime artifact inventory must include '{INDEX_RELATIVE_PATH}'."
        )
    return entries


def parse_runtime_artifact_inventory(
    manifest: dict[str, object],
) -> list[RuntimeArtifactEntry] | None:
    """Parse ``runtimeArtifacts`` from a manifest.

    Returns ``None`` when the field is absent (legacy manifests). An empty list
    means the publisher explicitly declared no QA objects, which is invalid for
    a full QA snapshot claim.
    """
    raw = manifest.get("runtimeArtifacts")
    if raw is None:
        return None
    if not isinstance(raw, list):
        raise TypeError("Manifest runtimeArtifacts must be a list.")
    entries: list[RuntimeArtifactEntry] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            raise TypeError("Manifest runtimeArtifacts entries must be objects.")
        relative = safe_release_relative_path(item.get("path")).as_posix()
        if relative in seen:
            raise ValueError(f"Duplicate runtime artifact path: {relative}")
        if not is_qa_sync_relative_path(relative):
            raise ValueError(f"Runtime artifact path is not QA-sync eligible: {relative}")
        generation = item.get("generation")
        size_bytes = item.get("sizeBytes", item.get("size_bytes"))
        sha256 = item.get("sha256")
        if not isinstance(generation, int) or generation < 0:
            raise ValueError(f"Invalid generation for artifact '{relative}'.")
        if not isinstance(size_bytes, int) or size_bytes < 0:
            raise ValueError(f"Invalid sizeBytes for artifact '{relative}'.")
        if not isinstance(sha256, str) or len(sha256) != 64:
            raise ValueError(f"Invalid sha256 for artifact '{relative}'.")
        seen.add(relative)
        entries.append(
            RuntimeArtifactEntry(
                relative_path=relative,
                generation=generation,
                size_bytes=size_bytes,
                sha256=sha256.lower(),
            )
        )
    return entries


def verify_local_artifact_entry(
    release_dir: Path,
    entry: RuntimeArtifactEntry,
) -> None:
    """Fail closed when a local file does not match inventory size and hash."""
    relative = safe_release_relative_path(entry.relative_path)
    path = release_dir.joinpath(*relative.parts)
    if not path.is_file():
        raise FileNotFoundError(f"Missing mirrored artifact: {entry.relative_path}")
    if path.is_symlink():
        raise ValueError(f"Mirrored artifact must not be a symlink: {entry.relative_path}")
    size = path.stat().st_size
    if size != entry.size_bytes:
        raise ValueError(
            f"Artifact size mismatch for '{entry.relative_path}': "
            f"expected {entry.size_bytes}, got {size}."
        )
    digest = sha256_file(path)
    if digest != entry.sha256.lower():
        raise ValueError(
            f"Artifact sha256 mismatch for '{entry.relative_path}'."
        )


def has_complete_runtime_inventory(manifest: dict[str, object]) -> bool:
    """Return True only when the manifest declares a usable QA inventory."""
    try:
        entries = parse_runtime_artifact_inventory(manifest)
    except (TypeError, ValueError):
        return False
    if not entries:
        return False
    return any(entry.relative_path == INDEX_RELATIVE_PATH for entry in entries)


def verification_hash_for_inventory(
    entries: list[RuntimeArtifactEntry] | tuple[RuntimeArtifactEntry, ...],
) -> str:
    """Stable hash over inventory digests for sync-status reporting."""
    digest = hashlib.sha256()
    for entry in sorted(entries, key=lambda item: item.relative_path):
        digest.update(entry.relative_path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(entry.sha256.encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(entry.generation).encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()
