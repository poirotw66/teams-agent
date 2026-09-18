"""Pure filesystem validators for knowledge-release artifacts."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from knowledge_core.artifacts import INDEX_RELATIVE_PATH, MANIFEST_FILENAME

__all__ = [
    "KnowledgeIndexArtifact",
    "KnowledgeReleaseValidationError",
    "inspect_index_artifact",
    "validate_release_artifacts",
]


class KnowledgeReleaseValidationError(ValueError):
    """Raised when a knowledge release cannot be trusted by the runtime."""


@dataclass(frozen=True)
class KnowledgeIndexArtifact:
    path: str
    sha256: str
    byte_size: int
    chunk_count: int
    vector_count: int
    embedding_model: str | None
    embedding_dimensions: int | None

    def to_manifest_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "sha256": self.sha256,
            "byteSize": self.byte_size,
            "chunkCount": self.chunk_count,
            "vectorCount": self.vector_count,
            "embeddingModel": self.embedding_model,
            "embeddingDimensions": self.embedding_dimensions,
        }


def inspect_index_artifact(index_path: Path) -> KnowledgeIndexArtifact:
    raw_index = index_path.read_bytes()
    try:
        payload = json.loads(raw_index)
    except json.JSONDecodeError as error:
        raise KnowledgeReleaseValidationError(
            f"Knowledge index is not valid JSON: {index_path}"
        ) from error
    if not isinstance(payload, dict) or not isinstance(payload.get("chunks"), list):
        raise KnowledgeReleaseValidationError(
            f"Knowledge index must contain a chunks array: {index_path}"
        )

    chunks = payload["chunks"]
    vector_dimensions = {
        len(vector)
        for chunk in chunks
        if isinstance(chunk, dict) and isinstance((vector := chunk.get("vector")), list) and vector
    }
    if len(vector_dimensions) > 1:
        raise KnowledgeReleaseValidationError(
            "Knowledge index contains vectors with inconsistent dimensions."
        )

    vector_count = sum(
        1
        for chunk in chunks
        if isinstance(chunk, dict)
        and isinstance(chunk.get("vector"), list)
        and bool(chunk["vector"])
    )
    return KnowledgeIndexArtifact(
        path=INDEX_RELATIVE_PATH,
        sha256=hashlib.sha256(raw_index).hexdigest(),
        byte_size=len(raw_index),
        chunk_count=len(chunks),
        vector_count=vector_count,
        embedding_model=_optional_string(payload.get("embeddingModel")),
        embedding_dimensions=next(iter(vector_dimensions), None),
    )


def validate_release_artifacts(
    release_root: Path,
    release_id: str,
    *,
    require_vectors: bool,
    expected_tenant_id: str | None = None,
    expected_purpose: str | None = None,
) -> KnowledgeIndexArtifact:
    release_dir = release_root / release_id
    manifest_path = release_dir / MANIFEST_FILENAME
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise KnowledgeReleaseValidationError(
            f"Knowledge release manifest not found: {manifest_path}"
        ) from error
    except json.JSONDecodeError as error:
        raise KnowledgeReleaseValidationError(
            f"Knowledge release manifest is not valid JSON: {manifest_path}"
        ) from error

    if not isinstance(manifest, dict) or manifest.get("releaseId") != release_id:
        raise KnowledgeReleaseValidationError(
            f"Knowledge release manifest does not identify release '{release_id}'."
        )
    if expected_tenant_id is not None and manifest.get("tenantId") != expected_tenant_id:
        raise KnowledgeReleaseValidationError(
            f"Knowledge release manifest does not identify tenant '{expected_tenant_id}'."
        )
    if expected_purpose is not None and manifest.get("purpose") != expected_purpose:
        raise KnowledgeReleaseValidationError(
            f"Knowledge release manifest does not identify purpose '{expected_purpose}'."
        )
    declared = manifest.get("index")
    if not isinstance(declared, dict):
        raise KnowledgeReleaseValidationError(
            "Knowledge release manifest is missing index metadata."
        )

    relative_path = _safe_relative_path(declared.get("path"))
    index_path = release_dir.joinpath(*relative_path.parts)
    actual = inspect_index_artifact(index_path)
    expected = actual.to_manifest_dict()
    for field in (
        "sha256",
        "byteSize",
        "chunkCount",
        "vectorCount",
        "embeddingModel",
        "embeddingDimensions",
    ):
        if declared.get(field) != expected[field]:
            raise KnowledgeReleaseValidationError(
                f"Knowledge release index metadata mismatch for '{field}'."
            )

    if require_vectors:
        _validate_production_governance(index_path, manifest)
        if actual.chunk_count == 0:
            raise KnowledgeReleaseValidationError(
                "Production knowledge release must contain at least one chunk."
            )
        if actual.vector_count != actual.chunk_count:
            raise KnowledgeReleaseValidationError(
                "Production knowledge release must contain an embedding for every chunk."
            )
        if not actual.embedding_model or not actual.embedding_dimensions:
            raise KnowledgeReleaseValidationError(
                "Production knowledge release must declare its embedding model and dimensions."
            )
    return actual


def _validate_production_governance(
    index_path: Path,
    manifest: dict[str, object],
) -> None:
    expected_documents_by_path = _manifest_documents_by_path(manifest)
    payload = json.loads(index_path.read_text(encoding="utf-8"))
    chunks = payload.get("chunks")
    if not isinstance(chunks, list):
        raise KnowledgeReleaseValidationError(
            "Knowledge release index does not contain a chunk list."
        )
    seen_paths: set[str] = set()
    for chunk in chunks:
        _validate_governed_chunk(chunk, expected_documents_by_path)
        source_path = _required_string(chunk, "source_path")
        seen_paths.add(source_path)
    if missing_paths := set(expected_documents_by_path) - seen_paths:
        raise KnowledgeReleaseValidationError(
            f"Knowledge release documents have no chunks: {sorted(missing_paths)}."
        )


def _manifest_documents_by_path(
    manifest: dict[str, object],
) -> dict[str, dict[str, object]]:
    documents = manifest.get("documents")
    if not isinstance(documents, list) or not documents:
        raise KnowledgeReleaseValidationError(
            "Production knowledge release must declare governed documents."
        )
    expected_documents_by_path: dict[str, dict[str, object]] = {}
    seen_document_ids: set[str] = set()
    alias_owners: dict[str, str] = {}
    for entry in documents:
        if not isinstance(entry, dict):
            raise KnowledgeReleaseValidationError("Knowledge release document metadata is invalid.")
        source_path = _required_string(entry, "source_path")
        document_id = _required_string(entry, "document_id")
        _required_string(entry, "version_id")
        _required_string(entry, "content_hash")
        acl_groups = entry.get("acl_groups")
        if not isinstance(acl_groups, list) or not acl_groups:
            raise KnowledgeReleaseValidationError(
                f"Knowledge release document '{source_path}' has no ACL."
            )
        if source_path in expected_documents_by_path:
            raise KnowledgeReleaseValidationError(
                f"Knowledge release source '{source_path}' is declared more than once."
            )
        if document_id in seen_document_ids:
            raise KnowledgeReleaseValidationError(
                f"Canonical document '{document_id}' is declared more than once."
            )
        seen_document_ids.add(document_id)
        _register_source_aliases(entry, source_path, document_id, alias_owners)
        expected_documents_by_path[source_path] = entry
    return expected_documents_by_path


def _register_source_aliases(
    entry: dict[str, object],
    source_path: str,
    document_id: str,
    alias_owners: dict[str, str],
) -> None:
    aliases = entry.get("source_aliases") or []
    if not isinstance(aliases, list):
        raise KnowledgeReleaseValidationError(
            f"Knowledge release document '{source_path}' has invalid source aliases."
        )
    for alias in aliases:
        normalized_alias = str(alias).strip().casefold()
        if not normalized_alias:
            continue
        owner = alias_owners.setdefault(normalized_alias, document_id)
        if owner != document_id:
            raise KnowledgeReleaseValidationError(
                f"Source alias '{alias}' identifies multiple canonical documents."
            )


def _validate_governed_chunk(
    chunk: object,
    expected_documents_by_path: dict[str, dict[str, object]],
) -> None:
    if not isinstance(chunk, dict):
        raise KnowledgeReleaseValidationError(
            "Knowledge release index contains an invalid chunk."
        )
    source_path = _required_string(chunk, "source_path")
    expected_entry = expected_documents_by_path.get(source_path)
    if expected_entry is None:
        raise KnowledgeReleaseValidationError(
            f"Knowledge chunk source '{source_path}' is absent from the manifest."
        )
    expected_acl = {
        str(group) for group in (expected_entry.get("acl_groups") or []) if str(group)
    }
    chunk_acl = {str(group) for group in (chunk.get("allowed_groups") or []) if str(group)}
    allowed_chunk_acls = (
        {frozenset(), frozenset({"grp_public"})}
        if expected_acl == {"grp_public"}
        else {frozenset(expected_acl)}
    )
    if frozenset(chunk_acl) not in allowed_chunk_acls:
        raise KnowledgeReleaseValidationError(
            f"Knowledge chunk ACL does not match manifest source '{source_path}'."
        )
    for identity_field in ("document_id", "version_id"):
        if chunk.get(identity_field) != expected_entry.get(identity_field):
            raise KnowledgeReleaseValidationError(
                f"Knowledge chunk {identity_field} does not match manifest "
                f"source '{source_path}'."
            )


def _required_string(payload: dict[str, object], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value:
        raise KnowledgeReleaseValidationError(
            f"Knowledge release metadata field '{field}' is required."
        )
    return value


def _safe_relative_path(value: object) -> PurePosixPath:
    if not isinstance(value, str):
        raise KnowledgeReleaseValidationError(
            "Knowledge release index path must be a relative string."
        )
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or path.as_posix() != INDEX_RELATIVE_PATH:
        raise KnowledgeReleaseValidationError(
            f"Knowledge release index path must be '{INDEX_RELATIVE_PATH}'."
        )
    return path


def _optional_string(value: object) -> str | None:
    return str(value) if value else None
