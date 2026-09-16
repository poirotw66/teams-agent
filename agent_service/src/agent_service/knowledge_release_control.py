from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .settings import RagSettings


@dataclass(frozen=True)
class KnowledgeReleaseReference:
    release_id: str
    purpose: str
    tenant_id: str
    bucket: str
    manifest_generation: int | None
    index_generation: int | None
    index_sha256: str
    chunk_count: int
    vector_count: int
    embedding_model: str | None
    embedding_dimensions: int | None


class FirestoreKnowledgeReleaseControl:
    def __init__(self, settings: RagSettings, *, client: Any = None) -> None:
        self._settings = settings
        self._client = client or _build_firestore_client(settings)

    def read_active_release_id(self) -> str | None:
        return _read_active_release_id(
            self._client,
            self._settings.knowledge_release_firestore_config_collection,
        )

    def read_release_reference(
        self,
        release_id: str | None = None,
    ) -> KnowledgeReleaseReference:
        return _read_release_reference(
            self._settings,
            self._client,
            release_id=release_id,
        )


def build_firestore_release_control(
    settings: RagSettings,
) -> FirestoreKnowledgeReleaseControl:
    return FirestoreKnowledgeReleaseControl(settings)


def read_firestore_release_reference(
    settings: RagSettings,
    *,
    release_id: str | None = None,
    client: Any = None,
) -> KnowledgeReleaseReference:
    firestore_client = client or _build_firestore_client(settings)
    return _read_release_reference(
        settings,
        firestore_client,
        release_id=release_id,
    )


def _read_release_reference(
    settings: RagSettings,
    firestore_client: Any,
    *,
    release_id: str | None,
) -> KnowledgeReleaseReference:
    resolved_release_id = release_id or _read_active_release_id(
        firestore_client,
        settings.knowledge_release_firestore_config_collection,
    )
    if not resolved_release_id:
        raise FileNotFoundError("Firestore knowledge control plane has no active release.")

    snapshot = (
        firestore_client.collection(settings.knowledge_release_firestore_releases_collection)
        .document(resolved_release_id)
        .get()
    )
    payload = snapshot.to_dict() or {}
    if not snapshot.exists:
        raise FileNotFoundError(
            f"Knowledge release '{resolved_release_id}' is absent from Firestore."
        )
    status = str(payload.get("status") or "")
    if status not in {"ACTIVE", "DEPLOYING", "RELOAD_FAILED"}:
        raise ValueError(f"Knowledge release '{resolved_release_id}' has unsafe status '{status}'.")
    purpose = str(payload.get("purpose") or "UNKNOWN").upper()
    if settings.deployment_environment == "prod" and purpose != "PRODUCTION":
        raise ValueError(
            f"Production cannot load {purpose} knowledge release '{resolved_release_id}'."
        )
    bucket = str(payload.get("artifact_bucket") or settings.knowledge_release_gcs_bucket or "")
    if not bucket:
        raise ValueError(
            f"Knowledge release '{resolved_release_id}' does not identify a GCS bucket."
        )
    manifest_generation = _optional_int(payload.get("manifest_generation"))
    index_generation = _optional_int(payload.get("index_generation"))
    index_sha256 = str(payload.get("index_sha256") or "")
    if manifest_generation is None or index_generation is None or not index_sha256:
        raise ValueError(
            f"Knowledge release '{resolved_release_id}' is missing pinned GCS metadata."
        )
    return KnowledgeReleaseReference(
        release_id=resolved_release_id,
        purpose=purpose,
        tenant_id=str(payload.get("tenant_id") or settings.knowledge_release_tenant_id),
        bucket=bucket,
        manifest_generation=manifest_generation,
        index_generation=index_generation,
        index_sha256=index_sha256,
        chunk_count=int(payload.get("chunk_count") or 0),
        vector_count=int(payload.get("vector_count") or 0),
        embedding_model=(
            str(payload["embedding_model"]) if payload.get("embedding_model") else None
        ),
        embedding_dimensions=_optional_int(payload.get("embedding_dimensions")),
    )


def _read_active_release_id(client: Any, collection_name: str) -> str | None:
    snapshot = client.collection(collection_name).document("active_release").get()
    payload = snapshot.to_dict() or {}
    value = payload.get("release_id")
    return str(value) if value else None


def _optional_int(value: object) -> int | None:
    return int(value) if value is not None else None


def _build_firestore_client(settings: RagSettings) -> Any:
    try:
        from google.cloud import firestore
    except ImportError as error:  # pragma: no cover - deployment dependency
        raise RuntimeError(
            "google-cloud-firestore is required for the knowledge control plane."
        ) from error
    kwargs: dict[str, str] = {}
    if settings.knowledge_release_firestore_project:
        kwargs["project"] = settings.knowledge_release_firestore_project
    if settings.knowledge_release_firestore_database:
        kwargs["database"] = settings.knowledge_release_firestore_database
    return firestore.Client(**kwargs)
