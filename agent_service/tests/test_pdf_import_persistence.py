"""Focused tests for durable PDF import staging and job state."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pdf_test_helpers import build_text_pdf_bytes

from knowledge_portal.api import create_app
from knowledge_portal.original_assets import OriginalAssetStore
from knowledge_portal.pdf_convert_jobs import PdfConvertJobStore
from knowledge_portal.pdf_staging import GcsPdfStagingStore
from knowledge_portal.persistent_pdf_jobs import (
    PersistentPdfConvertJobStore,
    build_pdf_convert_job_store,
)
from knowledge_portal.settings import PortalSettings


class FakeNotFound(Exception):
    code = 404


class FakeBlob:
    def __init__(self, objects: dict[str, dict[str, Any]], name: str) -> None:
        self._objects = objects
        self.name = name
        self.metadata = dict(objects.get(name, {}).get("metadata") or {})

    def upload_from_string(self, data: bytes | str, content_type: str) -> None:
        payload = data.encode("utf-8") if isinstance(data, str) else data
        self._objects[self.name] = {
            "payload": payload,
            "content_type": content_type,
            "metadata": dict(self.metadata),
        }

    def download_as_bytes(self) -> bytes:
        if self.name not in self._objects:
            raise FakeNotFound()
        stored = self._objects[self.name]
        self.metadata = dict(stored.get("metadata") or {})
        return stored["payload"]

    def delete(self) -> None:
        if self.name not in self._objects:
            raise FakeNotFound()
        del self._objects[self.name]


class FakeBucket:
    def __init__(self, objects: dict[str, dict[str, Any]]) -> None:
        self._objects = objects

    def blob(self, name: str) -> FakeBlob:
        return FakeBlob(self._objects, name)


class FakeGcsClient:
    def __init__(self) -> None:
        self.objects: dict[str, dict[str, Any]] = {}

    def bucket(self, name: str) -> FakeBucket:
        del name
        return FakeBucket(self.objects)


class FakeSnapshot:
    def __init__(self, payload: dict[str, Any] | None) -> None:
        self._payload = payload
        self.exists = payload is not None

    def to_dict(self) -> dict[str, Any] | None:
        return dict(self._payload) if self._payload is not None else None


class FakeDocument:
    def __init__(self, documents: dict[str, dict[str, Any]], path: str) -> None:
        self._documents = documents
        self._path = path

    def get(self, transaction: Any | None = None) -> FakeSnapshot:
        del transaction
        return FakeSnapshot(self._documents.get(self._path))

    def set(self, payload: dict[str, Any]) -> None:
        self._documents[self._path] = dict(payload)


class FakeCollection:
    def __init__(self, documents: dict[str, dict[str, Any]], name: str) -> None:
        self._documents = documents
        self._name = name

    def document(self, document_id: str) -> FakeDocument:
        return FakeDocument(self._documents, f"{self._name}/{document_id}")


class FakeTransaction:
    def __init__(self) -> None:
        self._writes: list[tuple[FakeDocument, dict[str, Any]]] = []

    def set(self, reference: FakeDocument, payload: dict[str, Any]) -> None:
        self._writes.append((reference, payload))

    def commit(self) -> None:
        for reference, payload in self._writes:
            reference.set(payload)


class FakeFirestoreClient:
    def __init__(self) -> None:
        self.documents: dict[str, dict[str, Any]] = {}

    def collection(self, name: str) -> FakeCollection:
        return FakeCollection(self.documents, name)

    def transaction(self) -> FakeTransaction:
        return FakeTransaction()


class RecordingArtifactStorage:
    def __init__(self) -> None:
        self.payloads: list[bytes] = []

    async def store_artifact(
        self,
        tenant_id: str,
        artifact_id: str,
        data: bytes,
        **kwargs: Any,
    ) -> Any:
        del tenant_id, kwargs
        self.payloads.append(data)
        return type("Record", (), {"artifact_id": artifact_id})()


def cloud_settings(tmp_path: Path) -> PortalSettings:
    settings = PortalSettings.from_env()
    return PortalSettings(
        **{
            **settings.__dict__,
            "data_dir": tmp_path,
            "original_assets_dir": tmp_path / "originals",
            "repository_mode": "FIRESTORE",
            "artifact_storage_backend": "GCS",
            "artifact_gcs_bucket": "private-artifacts",
            "default_tenant_id": "tenant-a",
        }
    )


def test_pending_original_survives_store_recreation(tmp_path: Path) -> None:
    settings = cloud_settings(tmp_path)
    gcs_client = FakeGcsClient()
    staging = GcsPdfStagingStore(
        bucket_name="private-artifacts",
        tenant_id="tenant-a",
        client=gcs_client,
    )
    artifacts = RecordingArtifactStorage()
    first_instance = OriginalAssetStore(
        settings,
        artifact_storage=artifacts,
        staging_store=staging,
    )
    pending = first_instance.store_pending(
        b"%PDF-durable",
        filename="guide.pdf",
        actor_id="actor-1",
    )

    second_instance = OriginalAssetStore(
        settings,
        artifact_storage=artifacts,
        staging_store=staging,
    )
    committed = second_instance.commit_pending(
        pending["original_asset_token"],
        document_id="doc-1",
        version_id="ver-1",
        actor_id="actor-1",
    )

    assert committed["original_artifact_ref"] == "art-doc-1-ver-1"
    assert artifacts.payloads == [b"%PDF-durable"]
    assert not any("/originals/" in key for key in gcs_client.objects)


def test_async_job_payload_and_result_survive_store_recreation(tmp_path: Path) -> None:
    settings = cloud_settings(tmp_path)
    object.__setattr__(settings, "pdf_converter_url", None)
    firestore = FakeFirestoreClient()
    gcs_client = FakeGcsClient()
    staging = GcsPdfStagingStore(
        bucket_name="private-artifacts",
        tenant_id="tenant-a",
        client=gcs_client,
    )
    first_instance = PersistentPdfConvertJobStore(
        settings,
        firestore_client=firestore,
        staging_store=staging,
    )
    job = first_instance.create_job(
        payload=build_text_pdf_bytes("Durable VPN instructions"),
        filename="guide.pdf",
        actor_id="actor-1",
        page_count=1,
    )

    second_instance = PersistentPdfConvertJobStore(
        settings,
        firestore_client=firestore,
        staging_store=staging,
    )
    reloaded = second_instance.get(job.job_id)
    assert reloaded is not None
    assert reloaded.status == "QUEUED"

    second_instance.schedule(job.job_id)
    completed = second_instance.get(job.job_id)

    assert completed is not None
    assert completed.status == "COMPLETED"
    assert "Durable VPN" in completed.result["markdown_content"]
    firestore_payload = next(iter(firestore.documents.values()))
    assert firestore_payload["result"] is None
    assert firestore_payload["has_result"] is True
    assert any(key.endswith("/result.json") for key in gcs_client.objects)
    assert not any(key.endswith("/payload") for key in gcs_client.objects)


def test_persistent_job_creation_is_idempotent_by_actor_and_key(
    tmp_path: Path,
) -> None:
    settings = cloud_settings(tmp_path)
    firestore = FakeFirestoreClient()
    staging = GcsPdfStagingStore(
        bucket_name="private-artifacts",
        tenant_id="tenant-a",
        client=FakeGcsClient(),
    )
    store = PersistentPdfConvertJobStore(
        settings,
        firestore_client=firestore,
        staging_store=staging,
    )
    payload = build_text_pdf_bytes("Idempotent ingestion")

    first = store.create_job(
        payload=payload,
        filename="guide.pdf",
        actor_id="actor-1",
        page_count=1,
        idempotency_key="upload-1",
        correlation_id="correlation-1",
    )
    second = store.create_job(
        payload=payload,
        filename="guide.pdf",
        actor_id="actor-1",
        page_count=1,
        idempotency_key="upload-1",
        correlation_id="correlation-1",
    )

    assert second.job_id == first.job_id
    assert second.payload_sha256 == first.payload_sha256
    assert second.correlation_id == "correlation-1"


def test_file_mode_keeps_local_job_store(tmp_path: Path) -> None:
    settings = PortalSettings.from_env()
    object.__setattr__(settings, "pdf_jobs_dir", tmp_path / "jobs")
    object.__setattr__(settings, "repository_mode", "FILE")
    object.__setattr__(settings, "artifact_storage_backend", "FILE")

    assert isinstance(build_pdf_convert_job_store(settings), PdfConvertJobStore)


def test_pdf_job_is_visible_only_to_its_uploader(tmp_path: Path) -> None:
    settings = PortalSettings.from_env()
    object.__setattr__(settings, "service_token", "")
    object.__setattr__(settings, "repository_mode", "MEMORY")
    object.__setattr__(settings, "pdf_jobs_dir", tmp_path / "jobs")
    object.__setattr__(settings, "pdf_sync_max_bytes", 1)
    client = TestClient(create_app(settings))
    owner_headers = {
        "X-Portal-User-Id": "actor-1",
        "X-Portal-User-Name": "Owner",
        "X-Portal-Role": "CONTRIBUTOR",
        "X-Portal-Owner-Units": "IT Service Desk",
    }
    response = client.post(
        "/api/documents/import-pdf?async_mode=async",
        files={
            "file": (
                "guide.pdf",
                build_text_pdf_bytes("private conversion"),
                "application/pdf",
            )
        },
        headers=owner_headers,
    )
    job_id = response.json()["jobId"]
    other_headers = {**owner_headers, "X-Portal-User-Id": "actor-2"}

    result = client.get(
        f"/api/documents/pdf-jobs/{job_id}",
        headers=other_headers,
    )

    assert result.status_code == 404


def test_production_header_auth_rejected_before_converter_check(tmp_path: Path) -> None:
    """Prod rejects forged X-Portal-* identity with 401 (auth before converter)."""
    settings = PortalSettings.from_env()
    object.__setattr__(settings, "service_token", "")
    object.__setattr__(settings, "repository_mode", "MEMORY")
    object.__setattr__(settings, "deployment_environment", "prod")
    object.__setattr__(settings, "pdf_converter_url", None)
    object.__setattr__(settings, "data_dir", tmp_path)
    client = TestClient(create_app(settings, release_gate_checker=object()))

    response = client.post(
        "/api/documents/import-pdf?async_mode=sync",
        files={
            "file": (
                "guide.pdf",
                build_text_pdf_bytes("must not use legacy"),
                "application/pdf",
            )
        },
        headers={
            "X-Portal-User-Id": "actor-1",
            "X-Portal-User-Name": "Actor",
            "X-Portal-Role": "CONTRIBUTOR",
            "X-Portal-Owner-Units": "IT Service Desk",
        },
    )

    assert response.status_code == 401


def test_production_import_requires_converter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With prod break-glass header auth, missing converter still returns 502."""
    monkeypatch.setenv("KNOWLEDGE_PORTAL_ALLOW_HEADER_AUTH", "true")
    settings = PortalSettings.from_env()
    object.__setattr__(settings, "service_token", "")
    object.__setattr__(settings, "repository_mode", "MEMORY")
    object.__setattr__(settings, "deployment_environment", "prod")
    object.__setattr__(settings, "pdf_converter_url", None)
    object.__setattr__(settings, "data_dir", tmp_path)
    client = TestClient(create_app(settings, release_gate_checker=object()))

    response = client.post(
        "/api/documents/import-pdf?async_mode=sync",
        files={
            "file": (
                "guide.pdf",
                build_text_pdf_bytes("must not use legacy"),
                "application/pdf",
            )
        },
        headers={
            "X-Portal-User-Id": "actor-1",
            "X-Portal-User-Name": "Actor",
            "X-Portal-Role": "CONTRIBUTOR",
            "X-Portal-Owner-Units": "IT Service Desk",
        },
    )

    assert response.status_code == 502
    assert "required in production" in response.json()["detail"]["message"]
