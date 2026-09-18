from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from agent_service.knowledge_release_gcs import (
    PublishedKnowledgeRelease,
    download_release_metadata,
    publish_release_directory,
)
from agent_service.release_artifacts import inspect_index_artifact
from knowledge_portal.publisher import ReleaseBuildError, ReleasePublisher
from knowledge_portal.settings import PortalSettings


class FakeBlob:
    def __init__(
        self,
        objects: dict[tuple[str, int], bytes],
        latest_generations: dict[str, int],
        name: str,
        generation: int | None = None,
    ) -> None:
        self._objects = objects
        self._latest_generations = latest_generations
        self.name = name
        self.generation = generation
        self.metadata: dict[str, str] = {}

    def upload_from_filename(
        self,
        filename: str,
        *,
        if_generation_match: int,
    ) -> None:
        assert if_generation_match == 0
        if self.name in self._latest_generations:
            raise RuntimeError("precondition failed")
        self.generation = len(self._objects) + 1
        self._objects[(self.name, self.generation)] = Path(filename).read_bytes()
        self._latest_generations[self.name] = self.generation

    def download_to_filename(self, filename: str) -> None:
        generation = self.generation or self._latest_generations[self.name]
        Path(filename).write_bytes(self._objects[(self.name, generation)])


class FakeBucket:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, int], bytes] = {}
        self.latest_generations: dict[str, int] = {}

    def blob(self, name: str, generation: int | None = None) -> FakeBlob:
        return FakeBlob(self.objects, self.latest_generations, name, generation)


class FakeStorageClient:
    def __init__(self) -> None:
        self.bucket_instance = FakeBucket()

    def bucket(self, _name: str) -> FakeBucket:
        return self.bucket_instance


def test_publish_and_download_use_immutable_object_generations(
    tmp_path: Path,
) -> None:
    release_id = "release-valid"
    release_dir = tmp_path / "source" / release_id
    index_path = release_dir / "index" / "chunks.json"
    index_path.parent.mkdir(parents=True)
    index_path.write_text(
        json.dumps(
            {
                "version": 1,
                "embeddingModel": "model-a",
                "chunks": [{"chunk_id": "1", "vector": [0.1, 0.2]}],
            }
        ),
        encoding="utf-8",
    )
    (release_dir / "manifest.json").write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "releaseId": release_id,
                "documents": [],
                "index": inspect_index_artifact(index_path).to_manifest_dict(),
            }
        ),
        encoding="utf-8",
    )
    client = FakeStorageClient()

    published = publish_release_directory(
        release_dir,
        bucket_name="knowledge",
        object_prefix="knowledge-releases",
        tenant_id="tenant-a",
        release_id=release_id,
        client=client,
    )
    downloaded_index = download_release_metadata(
        tmp_path / "cache",
        bucket_name=published.bucket,
        object_prefix="knowledge-releases",
        tenant_id="tenant-a",
        release_id=release_id,
        manifest_generation=published.manifest_generation,
        index_generation=published.index_generation,
        client=client,
    )

    assert downloaded_index.read_bytes() == index_path.read_bytes()
    assert published.manifest_generation != published.index_generation
    with pytest.raises(RuntimeError, match="precondition failed"):
        publish_release_directory(
            release_dir,
            bucket_name="knowledge",
            object_prefix="knowledge-releases",
            tenant_id="tenant-a",
            release_id=release_id,
            client=client,
        )


def test_portal_release_record_persists_gcs_integrity_metadata(
    tmp_path: Path,
) -> None:
    settings = PortalSettings.from_env()
    object.__setattr__(settings, "release_artifact_dir", tmp_path / "releases")
    object.__setattr__(settings, "release_gcs_bucket", "knowledge")
    object.__setattr__(settings, "embedding_model", None)
    object.__setattr__(settings, "release_purpose", "E2E")
    published = PublishedKnowledgeRelease(
        bucket="knowledge",
        object_prefix="knowledge-releases/tenants/tenant-a/releases/release-1",
        manifest_generation=21,
        index_generation=20,
    )

    class _Publisher:
        def publish(self, *args, **kwargs):
            from knowledge_portal.ports.release_publish import PublishedReleaseInfo

            return PublishedReleaseInfo(
                bucket=published.bucket,
                object_prefix=published.object_prefix,
                manifest_generation=published.manifest_generation,
                index_generation=published.index_generation,
            )

    with patch(
        "knowledge_portal.publisher_finalize.get_release_directory_publisher",
        return_value=_Publisher(),
    ):
        release = ReleasePublisher(settings).build_release(
            release_id="release-1",
            published_versions=[],
            created_by="publisher-a",
            previous_release_id=None,
            tenant_id="tenant-a",
        )

    assert release.artifact_bucket == "knowledge"
    assert release.manifest_generation == 21
    assert release.index_generation == 20
    assert release.index_sha256
    assert release.chunk_count == 0
    assert release.purpose == "E2E"
    manifest = json.loads(
        (tmp_path / "releases" / "release-1" / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["purpose"] == "E2E"


def test_portal_rejects_vectorless_production_release_before_upload(
    tmp_path: Path,
) -> None:
    settings = PortalSettings.from_env()
    object.__setattr__(settings, "release_artifact_dir", tmp_path / "releases")
    object.__setattr__(settings, "release_gcs_bucket", "knowledge")
    object.__setattr__(settings, "embedding_model", None)

    with pytest.raises(
        ReleaseBuildError,
        match="Production release validation failed",
    ):
        ReleasePublisher(settings).build_release(
            release_id="release-invalid",
            published_versions=[],
            created_by="publisher-a",
            previous_release_id=None,
            tenant_id="tenant-a",
        )


def test_production_portal_rejects_e2e_release_purpose(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGENT_DEPLOYMENT_ENV", "prod")
    monkeypatch.setenv("KNOWLEDGE_PORTAL_RELEASE_PURPOSE", "E2E")

    with pytest.raises(ValueError, match="may only publish PRODUCTION"):
        PortalSettings.from_env()
