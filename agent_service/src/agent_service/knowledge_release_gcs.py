from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .release_artifacts import INDEX_RELATIVE_PATH, MANIFEST_FILENAME

_SAFE_IDENTIFIER = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")


@dataclass(frozen=True)
class PublishedKnowledgeRelease:
    bucket: str
    object_prefix: str
    manifest_generation: int
    index_generation: int


def publish_release_directory(
    release_dir: Path,
    *,
    bucket_name: str,
    object_prefix: str,
    tenant_id: str,
    release_id: str,
    client: Any = None,
) -> PublishedKnowledgeRelease:
    """Upload a local release once, using GCS preconditions for immutability."""
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

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["storage"] = {
        "bucket": bucket_name,
        "objectPrefix": release_prefix,
        "indexGeneration": generations[INDEX_RELATIVE_PATH],
    }
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
) -> Path:
    """Download a pinned manifest and index into an ephemeral local cache."""
    storage_client = client or _build_storage_client()
    bucket = storage_client.bucket(bucket_name)
    release_prefix = _release_prefix(object_prefix, tenant_id, release_id)
    release_dir = destination_root / release_id
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
        temporary.replace(destination)
    except Exception as error:  # noqa: BLE001 - external storage boundary
        temporary.unlink(missing_ok=True)
        raise RuntimeError(
            f"Failed to download pinned knowledge object '{object_name}'."
        ) from error


def _build_storage_client() -> Any:
    try:
        from google.cloud import storage
    except ImportError as error:  # pragma: no cover - optional deployment dependency
        raise RuntimeError(
            "google-cloud-storage is required for GCS knowledge releases."
        ) from error
    return storage.Client()
