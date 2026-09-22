from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from knowledge_core.artifacts import INDEX_RELATIVE_PATH, MANIFEST_FILENAME
from knowledge_core.runtime_inventory import (
    RuntimeArtifactEntry,
    build_runtime_artifact_inventory,
    is_qa_sync_relative_path,
    safe_release_relative_path,
    sha256_file,
)

from .knowledge_release_cache import require_safe_identifier, tenant_release_cache_dir

_SAFE_IDENTIFIER = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")


@dataclass(frozen=True)
class PublishedKnowledgeRelease:
    bucket: str
    object_prefix: str
    manifest_generation: int
    index_generation: int
    runtime_artifacts: tuple[RuntimeArtifactEntry, ...] = ()


def publish_release_directory(
    release_dir: Path,
    *,
    bucket_name: str,
    object_prefix: str,
    tenant_id: str,
    release_id: str,
    client: Any = None,
) -> PublishedKnowledgeRelease:
    """Upload a local release once, using GCS preconditions for immutability.

    Non-manifest objects upload first. The final manifest includes storage
    metadata and a ``runtimeArtifacts`` inventory of QA-required objects, then
    uploads last.
    """
    storage_client = client or _build_storage_client()
    bucket = storage_client.bucket(bucket_name)
    release_prefix = _release_prefix(object_prefix, tenant_id, release_id)
    manifest_path = release_dir / MANIFEST_FILENAME
    paths = sorted(path for path in release_dir.rglob("*") if path.is_file())

    generations: dict[str, int] = {}
    for path in paths:
        relative_path = path.relative_to(release_dir).as_posix()
        if relative_path == MANIFEST_FILENAME:
            continue
        generations[relative_path] = _upload_immutable(
            bucket,
            path,
            f"{release_prefix}/{relative_path}",
        )

    inventory = build_runtime_artifact_inventory(
        generations=generations,
        release_dir=release_dir,
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["storage"] = {
        "bucket": bucket_name,
        "objectPrefix": release_prefix,
        "indexGeneration": generations[INDEX_RELATIVE_PATH],
    }
    manifest["runtimeArtifacts"] = [entry.to_manifest_dict() for entry in inventory]
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    manifest_generation = _upload_immutable(
        bucket,
        manifest_path,
        f"{release_prefix}/{MANIFEST_FILENAME}",
    )
    return PublishedKnowledgeRelease(
        bucket=bucket_name,
        object_prefix=release_prefix,
        manifest_generation=manifest_generation,
        index_generation=generations[INDEX_RELATIVE_PATH],
        runtime_artifacts=tuple(inventory),
    )


def download_release_metadata(
    destination_root: Path,
    *,
    bucket_name: str,
    object_prefix: str,
    tenant_id: str,
    release_id: str,
    manifest_generation: int | None,
    index_generation: int | None,
    client: Any = None,
    tenant_scoped: bool = False,
) -> Path:
    """Download a pinned manifest and index into a local cache.

    When ``tenant_scoped`` is True, writes under
    ``<destination_root>/tenants/<tenantId>/releases/<releaseId>/``.
    Legacy callers keep ``<destination_root>/<releaseId>/``.
    """
    storage_client = client or _build_storage_client()
    bucket = storage_client.bucket(bucket_name)
    release_prefix = _release_prefix(object_prefix, tenant_id, release_id)
    release_dir = (
        tenant_release_cache_dir(destination_root, tenant_id, release_id)
        if tenant_scoped
        else destination_root / require_safe_identifier("release", release_id)
    )
    index_path = release_dir / INDEX_RELATIVE_PATH
    index_path.parent.mkdir(parents=True, exist_ok=True)

    _download_blob(
        bucket,
        f"{release_prefix}/{MANIFEST_FILENAME}",
        release_dir / MANIFEST_FILENAME,
        generation=manifest_generation,
    )
    _download_blob(
        bucket,
        f"{release_prefix}/{INDEX_RELATIVE_PATH}",
        index_path,
        generation=index_generation,
    )
    return index_path


def download_inventory_artifacts(
    release_dir: Path,
    *,
    bucket_name: str,
    object_prefix: str,
    tenant_id: str,
    release_id: str,
    inventory: list[RuntimeArtifactEntry],
    client: Any = None,
) -> None:
    """Download and verify every QA inventory object into ``release_dir``."""
    storage_client = client or _build_storage_client()
    bucket = storage_client.bucket(bucket_name)
    release_prefix = _release_prefix(object_prefix, tenant_id, release_id)
    for entry in inventory:
        relative = safe_release_relative_path(entry.relative_path)
        if not is_qa_sync_relative_path(relative.as_posix()):
            raise ValueError(f"Refusing non-QA inventory path: {entry.relative_path}")
        destination = release_dir.joinpath(*relative.parts)
        destination.parent.mkdir(parents=True, exist_ok=True)
        _download_blob(
            bucket,
            f"{release_prefix}/{relative.as_posix()}",
            destination,
            generation=entry.generation,
        )
        size = destination.stat().st_size
        if size != entry.size_bytes:
            raise RuntimeError(
                f"Downloaded size mismatch for '{entry.relative_path}': "
                f"expected {entry.size_bytes}, got {size}."
            )
        digest = sha256_file(destination)
        if digest != entry.sha256.lower():
            raise RuntimeError(
                f"Downloaded sha256 mismatch for '{entry.relative_path}'."
            )
        _strip_execute_bits(destination)


def download_release_runtime_snapshot(
    destination_dir: Path,
    *,
    bucket_name: str,
    object_prefix: str,
    tenant_id: str,
    release_id: str,
    manifest_generation: int | None,
    index_generation: int | None = None,
    client: Any = None,
) -> tuple[Path, list[RuntimeArtifactEntry] | None, bool]:
    """Download manifest plus QA inventory (or legacy index-only) into ``destination_dir``.

    Returns ``(manifest_path, inventory_or_none, inventory_complete)``.
    Legacy manifests without ``runtimeArtifacts`` download only the index and
    return ``inventory_complete=False`` so callers must not claim a full QA sync.
    """
    from knowledge_core.runtime_inventory import (
        has_complete_runtime_inventory,
        parse_runtime_artifact_inventory,
    )

    storage_client = client or _build_storage_client()
    bucket = storage_client.bucket(bucket_name)
    release_prefix = _release_prefix(object_prefix, tenant_id, release_id)
    destination_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = destination_dir / MANIFEST_FILENAME
    _download_blob(
        bucket,
        f"{release_prefix}/{MANIFEST_FILENAME}",
        manifest_path,
        generation=manifest_generation,
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise TypeError("Downloaded knowledge release manifest is invalid.")

    inventory = parse_runtime_artifact_inventory(manifest)
    if inventory is not None and has_complete_runtime_inventory(manifest):
        download_inventory_artifacts(
            destination_dir,
            bucket_name=bucket_name,
            object_prefix=object_prefix,
            tenant_id=tenant_id,
            release_id=release_id,
            inventory=inventory,
            client=storage_client,
        )
        return manifest_path, inventory, True

    index_path = destination_dir / INDEX_RELATIVE_PATH
    index_path.parent.mkdir(parents=True, exist_ok=True)
    resolved_index_generation = index_generation
    if resolved_index_generation is None:
        storage = manifest.get("storage")
        if isinstance(storage, dict) and storage.get("indexGeneration") is not None:
            resolved_index_generation = int(storage["indexGeneration"])
    _download_blob(
        bucket,
        f"{release_prefix}/{INDEX_RELATIVE_PATH}",
        index_path,
        generation=resolved_index_generation,
    )
    return manifest_path, inventory, False


def _release_prefix(object_prefix: str, tenant_id: str, release_id: str) -> str:
    for label, value in (("tenant", tenant_id), ("release", release_id)):
        if not _SAFE_IDENTIFIER.fullmatch(value):
            raise ValueError(f"Invalid knowledge {label} identifier.")
    normalized_prefix = object_prefix.strip("/")
    base = f"{normalized_prefix}/" if normalized_prefix else ""
    return f"{base}tenants/{tenant_id}/releases/{release_id}"


def _upload_immutable(bucket: Any, source: Path, object_name: str) -> int:
    blob = bucket.blob(object_name)
    blob.metadata = {"sha256": _sha256_file(source)}
    blob.upload_from_filename(str(source), if_generation_match=0)
    if blob.generation is None:
        raise RuntimeError(f"GCS did not return a generation for '{object_name}'.")
    return int(blob.generation)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _download_blob(
    bucket: Any,
    object_name: str,
    destination: Path,
    *,
    generation: int | None,
) -> None:
    blob = bucket.blob(object_name, generation=generation)
    temporary = destination.with_suffix(f"{destination.suffix}.download")
    try:
        blob.download_to_filename(str(temporary))
        _strip_execute_bits(temporary)
        temporary.replace(destination)
    except Exception as error:  # noqa: BLE001 - external storage boundary
        temporary.unlink(missing_ok=True)
        raise RuntimeError(
            f"Failed to download pinned knowledge object '{object_name}'."
        ) from error


def _strip_execute_bits(path: Path) -> None:
    mode = path.stat().st_mode
    path.chmod(mode & ~0o111)


def _build_storage_client() -> Any:
    try:
        from google.cloud import storage
    except ImportError as error:  # pragma: no cover - optional deployment dependency
        raise RuntimeError(
            "google-cloud-storage is required for GCS knowledge releases."
        ) from error
    return storage.Client()
