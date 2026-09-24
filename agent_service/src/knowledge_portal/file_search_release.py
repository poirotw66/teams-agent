"""Idempotent Gemini File Search synchronization for immutable releases."""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from knowledge_core.eligibility import is_generation_metadata_eligible

_FILE_SEARCH_MAX_CHUNK_TOKENS = 512
_FILE_SEARCH_UPLOAD_WORKERS = 6
_FILE_SEARCH_POLL_INTERVAL_SECONDS = 0.25


@dataclass(frozen=True)
class FileSearchReleaseEntry:
    slug: str
    release_id: str
    document_id: str
    version_id: str
    chunk_id: str
    source_path: str
    parent_id: str
    page: int
    allowed_groups: tuple[str, ...]
    content_hash: str
    source_aliases: tuple[str, ...] = ()
    content_state: str = "ACTIVE"
    effective_at: str | None = None
    expires_at: str | None = None
    applicable_environments: tuple[str, ...] = ()


def load_file_search_release_entries(
    release_dir: Path,
) -> list[FileSearchReleaseEntry]:
    manifest_path = release_dir / "file-search" / "manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    environment = str(payload.get("deploymentEnvironment") or "dev")
    entries: list[FileSearchReleaseEntry] = []
    seen: set[tuple[str, str]] = set()
    for raw in payload.get("documents", []):
        entry = FileSearchReleaseEntry(
            slug=_required(raw, "slug"),
            release_id=_required(raw, "releaseId"),
            document_id=_required(raw, "documentId"),
            version_id=_required(raw, "versionId"),
            chunk_id=_required(raw, "chunkId"),
            source_path=_required(raw, "sourcePath"),
            parent_id=_required(raw, "parentId"),
            page=int(raw["page"]),
            allowed_groups=tuple(str(value) for value in raw.get("allowedGroups", [])),
            content_hash=_required(raw, "contentHash"),
            source_aliases=tuple(str(value) for value in raw.get("sourceAliases", [])),
            content_state=str(raw.get("contentState") or "ACTIVE"),
            effective_at=_optional(raw, "effectiveAt"),
            expires_at=_optional(raw, "expiresAt"),
            applicable_environments=tuple(
                str(value) for value in raw.get("applicableEnvironments", [])
            ),
        )
        key = (entry.release_id, entry.chunk_id)
        if key in seen:
            raise ValueError(f"Duplicate File Search release identity: {key}")
        if not entry.allowed_groups:
            raise ValueError(f"File Search chunk {entry.chunk_id} has no explicit ACL.")
        if not is_generation_metadata_eligible(
            content_state=entry.content_state,
            effective_at=entry.effective_at,
            expires_at=entry.expires_at,
            applicable_environments=list(entry.applicable_environments),
            environment=environment,
        ):
            raise ValueError(f"File Search chunk {entry.chunk_id} is not generation eligible.")
        staged = release_dir / "file-search" / entry.slug
        if not staged.is_file():
            raise ValueError(f"File Search staged document is missing: {entry.slug}")
        seen.add(key)
        entries.append(entry)
    if not entries:
        raise ValueError("File Search release manifest contains no documents.")
    return entries


def synchronize_file_search_release(
    release_dir: Path,
    *,
    api_key: str,
    store_name: str | None = None,
    operation_timeout_seconds: float = 300.0,
    max_workers: int = _FILE_SEARCH_UPLOAD_WORKERS,
) -> str:
    """Reconcile one release-scoped store by deterministic chunk slug.

    Unchanged chunks are skipped. Uploads that need work run concurrently so
    formal publish is not serialized on one-at-a-time Gemini polling.
    """
    from google import genai
    from google.genai import types

    from agent_service.gemini_backend import (
        require_developer_api_for_file_search,
        require_developer_api_key,
    )

    require_developer_api_for_file_search(feature="File Search release sync")
    resolved_key = (api_key or "").strip() or require_developer_api_key()
    entries = load_file_search_release_entries(release_dir)
    client = genai.Client(api_key=resolved_key)
    if store_name is None:
        display_name = f"knowledge-{entries[0].release_id}"
        matching_stores = sorted(
            (
                store
                for store in client.file_search_stores.list()
                if str(getattr(store, "display_name", "")) == display_name
            ),
            key=lambda store: str(store.name),
        )
        if matching_stores:
            store_name = str(matching_stores[0].name)
        else:
            created = client.file_search_stores.create(
                config=types.CreateFileSearchStoreConfig(
                    display_name=display_name,
                )
            )
            store_name = str(created.name)

    remote_by_slug: dict[str, list[Any]] = {}
    for document in client.file_search_stores.documents.list(parent=store_name):
        slug = str(getattr(document, "display_name", ""))
        remote_by_slug.setdefault(slug, []).append(document)
    expected_slugs = {entry.slug for entry in entries}

    uploads: list[FileSearchReleaseEntry] = []
    for entry in entries:
        existing = remote_by_slug.get(entry.slug, [])
        if len(existing) == 1 and _remote_content_hash(existing[0]) == entry.content_hash:
            continue
        for document in existing:
            client.file_search_stores.documents.delete(
                name=document.name,
                config=types.DeleteDocumentConfig(force=True),
            )
        uploads.append(entry)

    if uploads:
        worker_count = max(1, min(max_workers, len(uploads)))
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = [
                executor.submit(
                    _upload_file_search_entry,
                    client,
                    types,
                    store_name=store_name,
                    release_dir=release_dir,
                    entry=entry,
                    operation_timeout_seconds=operation_timeout_seconds,
                )
                for entry in uploads
            ]
            for future in as_completed(futures):
                future.result()

    for slug, documents in remote_by_slug.items():
        if slug and slug not in expected_slugs:
            for document in documents:
                client.file_search_stores.documents.delete(
                    name=document.name,
                    config=types.DeleteDocumentConfig(force=True),
                )
    return store_name


def _upload_file_search_entry(
    client: Any,
    types: Any,
    *,
    store_name: str,
    release_dir: Path,
    entry: FileSearchReleaseEntry,
    operation_timeout_seconds: float,
) -> None:
    metadata = _custom_metadata(types, entry)
    operation = client.file_search_stores.upload_to_file_search_store(
        file_search_store_name=store_name,
        file=str(release_dir / "file-search" / entry.slug),
        config=types.UploadToFileSearchStoreConfig(
            display_name=entry.slug,
            mime_type="text/plain",
            custom_metadata=metadata,
            chunking_config=types.ChunkingConfig(
                white_space_config=types.WhiteSpaceConfig(
                    # Gemini caps this setting at 512. The canonical child
                    # remains the uploaded document and source identity.
                    max_tokens_per_chunk=_FILE_SEARCH_MAX_CHUNK_TOKENS,
                    max_overlap_tokens=0,
                )
            ),
        ),
    )
    _await_operation(client, operation, timeout_seconds=operation_timeout_seconds)


def _custom_metadata(types: Any, entry: FileSearchReleaseEntry) -> list[Any]:
    values = {
        "release_id": entry.release_id,
        "document_id": entry.document_id,
        "version_id": entry.version_id,
        "chunk_id": entry.chunk_id,
        "source_path": entry.source_path,
        "parent_id": entry.parent_id,
        "page": str(entry.page),
        "acl_mode": "PUBLIC" if entry.allowed_groups == ("grp_public",) else "RESTRICTED",
        "content_hash": entry.content_hash,
        "source_aliases": json.dumps(
            entry.source_aliases,
            ensure_ascii=True,
        ),
        "content_state": entry.content_state,
        "effective_at": entry.effective_at or "",
        "expires_at": entry.expires_at or "",
        "applicable_environments": json.dumps(
            entry.applicable_environments,
            ensure_ascii=True,
        ),
    }
    metadata = [types.CustomMetadata(key=key, string_value=value) for key, value in values.items()]
    from knowledge_core.file_search_acl import upload_metadata_for

    acl_groups = [] if entry.allowed_groups == ("grp_public",) else list(entry.allowed_groups)
    metadata.extend(upload_metadata_for(acl_groups))
    return metadata


def _await_operation(client: Any, operation: Any, *, timeout_seconds: float) -> None:
    deadline = time.monotonic() + timeout_seconds
    while not operation.done:
        if time.monotonic() >= deadline:
            raise TimeoutError("Gemini File Search upload timed out.")
        time.sleep(_FILE_SEARCH_POLL_INTERVAL_SECONDS)
        operation = client.operations.get(operation)
    if operation.error:
        raise RuntimeError(f"Gemini File Search upload failed: {operation.error}")


def _required(payload: dict[str, Any], key: str) -> str:
    value = str(payload.get(key) or "").strip()
    if not value:
        raise ValueError(f"File Search release metadata is missing {key}.")
    return value


def _optional(payload: dict[str, Any], key: str) -> str | None:
    value = str(payload.get(key) or "").strip()
    return value or None


def _remote_content_hash(document: Any) -> str | None:
    for metadata in getattr(document, "custom_metadata", ()) or ():
        if getattr(metadata, "key", None) == "content_hash":
            value = getattr(metadata, "string_value", None)
            return str(value) if value is not None else None
    return None
