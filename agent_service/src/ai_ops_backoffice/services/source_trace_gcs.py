"""Materialize cloud knowledge-release artifacts for source preview fallback.

Cloud Backoffice instances do not keep release trees on local disk. When
Firestore SourceRecords are missing (for example after an inventory republish
that stored a ``gs://`` index URI without persisting chunk identities),
citation preview must still resolve against the active release's GCS
``index/chunks.json`` and ``manifest.json``.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from pathlib import Path

logger = logging.getLogger(__name__)

__all__ = [
    "materialize_release_preview_artifacts",
    "read_firestore_active_release_id",
]


FirestoreReleaseStorageReader = Callable[[str], tuple[str, str] | None]


def read_firestore_active_release_id(
    *,
    project_id: str | None,
    database: str | None = "(default)",
    config_collection: str = "knowledge_portal_config",
) -> str | None:
    """Return the cloud-active release id from Firestore, if readable."""
    if not project_id:
        return None
    try:
        from google.cloud import firestore
    except ImportError:
        return None
    try:
        client = (
            firestore.Client(project=project_id, database=database)
            if database and database != "(default)"
            else firestore.Client(project=project_id)
        )
        snapshot = client.collection(config_collection).document("active_release").get()
    except Exception:  # noqa: BLE001 - control-plane boundary
        logger.debug("Unable to read Firestore active_release pointer", exc_info=True)
        return None
    if not snapshot.exists:
        return None
    payload = snapshot.to_dict() or {}
    value = payload.get("release_id") or payload.get("releaseId")
    return str(value) if value else None


def _read_firestore_release_storage(
    *,
    project_id: str,
    release_id: str,
    database: str | None = "(default)",
    releases_collection: str = "knowledge_releases",
) -> tuple[str, str] | None:
    try:
        from google.cloud import firestore
    except ImportError:
        return None
    try:
        client = (
            firestore.Client(project=project_id, database=database)
            if database and database != "(default)"
            else firestore.Client(project=project_id)
        )
        snapshot = client.collection(releases_collection).document(release_id).get()
    except Exception:  # noqa: BLE001 - control-plane boundary
        logger.debug(
            "Unable to read Firestore release storage for %s",
            release_id,
            exc_info=True,
        )
        return None
    if not snapshot.exists:
        return None
    payload = snapshot.to_dict() or {}
    bucket = str(payload.get("artifact_bucket") or "").strip()
    prefix = str(payload.get("artifact_object_prefix") or "").strip().rstrip("/")
    if not bucket or not prefix:
        index_uri = str(payload.get("index_artifact_uri") or "")
        if index_uri.startswith("gs://"):
            remainder = index_uri[5:]
            bucket_name, _, object_name = remainder.partition("/")
            if bucket_name and object_name.endswith("/index/chunks.json"):
                return bucket_name, object_name[: -len("/index/chunks.json")]
        return None
    return bucket, prefix


def _download_gcs_object(bucket_name: str, object_name: str, dest: Path) -> bool:
    try:
        from google.cloud import storage
    except ImportError:
        return False
    try:
        blob = storage.Client().bucket(bucket_name).blob(object_name)
        if not blob.exists():
            return False
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(blob.download_as_bytes())
        return True
    except Exception:  # noqa: BLE001 - GCS boundary
        logger.debug(
            "Failed downloading gs://%s/%s for source preview",
            bucket_name,
            object_name,
            exc_info=True,
        )
        return False


def materialize_release_preview_artifacts(
    releases_dir: Path,
    release_id: str,
    *,
    project_id: str | None,
    firestore_database: str | None = "(default)",
    storage_reader: FirestoreReleaseStorageReader | None = None,
) -> Path | None:
    """Ensure ``releases_dir/<release_id>/index/chunks.json`` (+manifest) exist.

    Downloads only preview-required objects from the release's GCS prefix.
    Returns the release root when the index is available, otherwise ``None``.
    """
    if not release_id or not project_id:
        return None
    releases_root = releases_dir.expanduser().resolve()
    release_root = (releases_root / release_id).resolve()
    try:
        release_root.relative_to(releases_root)
    except ValueError:
        return None
    index_path = release_root / "index" / "chunks.json"
    if index_path.is_file():
        return release_root

    reader = storage_reader or (
        lambda rid: _read_firestore_release_storage(
            project_id=project_id,
            release_id=rid,
            database=firestore_database,
        )
    )
    storage = reader(release_id)
    if storage is None:
        return None
    bucket_name, prefix = storage
    downloaded_index = _download_gcs_object(
        bucket_name,
        f"{prefix}/index/chunks.json",
        index_path,
    )
    if not downloaded_index:
        return None
    manifest_path = release_root / "manifest.json"
    if not manifest_path.is_file():
        _download_gcs_object(
            bucket_name,
            f"{prefix}/manifest.json",
            manifest_path,
        )
    # Best-effort: keep source markdown available for excerpt fallbacks.
    try:
        payload = json.loads(index_path.read_text(encoding="utf-8"))
        chunks = payload.get("chunks") if isinstance(payload, dict) else None
        if isinstance(chunks, list):
            seen_paths: set[str] = set()
            for chunk in chunks:
                if not isinstance(chunk, dict):
                    continue
                relative = str(chunk.get("source_path") or "").replace("\\", "/").lstrip("/")
                if (
                    not relative
                    or relative in seen_paths
                    or ".." in relative.split("/")
                    or not relative.startswith("sources/")
                ):
                    continue
                seen_paths.add(relative)
                local = release_root / relative
                if not local.is_file():
                    _download_gcs_object(
                        bucket_name,
                        f"{prefix}/{relative}",
                        local,
                    )
    except (OSError, ValueError):
        pass
    return release_root
