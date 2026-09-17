import json
from datetime import UTC, datetime

import pytest

from knowledge_portal.draft_assets import DraftAssetStore
from knowledge_portal.models import KnowledgeVersionRecord, ReleaseRecord
from knowledge_portal.settings import PortalSettings
from knowledge_portal.version_assets import (
    build_version_asset_context,
    images_for_chunk,
    read_version_asset,
)


class FakeBlob:
    def __init__(self, bucket: "FakeBucket", name: str) -> None:
        self.bucket = bucket
        self.name = name
        self.metadata: dict[str, str] = {}
        self.content_type: str | None = None
        self.size = 0

    def upload_from_string(self, payload: bytes, content_type: str) -> None:
        self.bucket.payloads[self.name] = payload
        self.bucket.metadata[self.name] = dict(self.metadata)
        self.bucket.content_types[self.name] = content_type
        self.size = len(payload)

    def download_as_bytes(self) -> bytes:
        return self.bucket.payloads[self.name]


class FakeBucket:
    def __init__(self) -> None:
        self.payloads: dict[str, bytes] = {}
        self.metadata: dict[str, dict[str, str]] = {}
        self.content_types: dict[str, str] = {}

    def blob(self, name: str) -> FakeBlob:
        blob = FakeBlob(self, name)
        blob.metadata = dict(self.metadata.get(name, {}))
        blob.content_type = self.content_types.get(name)
        blob.size = len(self.payloads.get(name, b""))
        return blob

    def list_blobs(self, prefix: str):
        return [self.blob(name) for name in sorted(self.payloads) if name.startswith(prefix)]


class FakeStorageClient:
    def __init__(self, bucket: FakeBucket) -> None:
        self._bucket = bucket

    def bucket(self, name: str) -> FakeBucket:
        assert name == "shared-drafts"
        return self._bucket


def test_shared_draft_assets_are_visible_across_store_instances(tmp_path) -> None:
    settings = PortalSettings.from_env()
    object.__setattr__(settings, "artifact_storage_backend", "GCS")
    object.__setattr__(settings, "artifact_gcs_bucket", "shared-drafts")
    object.__setattr__(settings, "drafts_dir", tmp_path / "drafts")
    bucket = FakeBucket()
    client = FakeStorageClient(bucket)
    writer = DraftAssetStore(settings, storage_client=client)
    reader = DraftAssetStore(settings, storage_client=client)

    writer.save_asset(
        document_id="doc-guide",
        version_id="ver-guide-1",
        asset_slug="guide",
        filename="p05.png",
        payload=b"shared-image",
    )
    payload, content_type = reader.read_asset_bytes(
        document_id="doc-guide",
        version_id="ver-guide-1",
        asset_slug="guide",
        filename="p05.png",
    )

    assert payload == b"shared-image"
    assert content_type == "image/png"
    assert reader.list_assets("doc-guide", "ver-guide-1", "guide")[0].sha256


@pytest.mark.asyncio
async def test_published_asset_uses_release_index_mapping(tmp_path) -> None:
    settings = PortalSettings.from_env()
    object.__setattr__(settings, "release_artifact_dir", tmp_path / "releases")
    version = KnowledgeVersionRecord(
        version_id="ver-guide-1",
        document_id="doc-guide",
        version_number=1,
        content_hash="content-hash",
        canonical_content="# Guide\n\n![Diagram](assets/guide/p05.png)",
        effective_at="2026-09-17",
        review_due_at="2027-09-17",
        owner_unit_id="IT Service Desk",
        title="Guide",
        asset_slug="guide",
        status="PUBLISHED",
        etag='W/"ver-guide-1"',
        created_at=datetime.now(UTC),
        created_by="test-user",
    )
    release_dir = settings.release_artifact_dir / "release-1"
    asset_path = release_dir / "assets" / "guide" / "p05.png"
    asset_path.parent.mkdir(parents=True)
    asset_path.write_bytes(b"indexed-image")
    index_path = release_dir / "index" / "chunks.json"
    index_path.parent.mkdir(parents=True)
    index_path.write_text(
        json.dumps(
            {
                "chunks": [
                    {
                        "document_id": version.document_id,
                        "version_id": version.version_id,
                        "images": [
                            {
                                "path": "guide/p05.png",
                                "title": "Diagram",
                                "alt_text": "Diagram",
                            }
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    release = ReleaseRecord(
        release_id="release-1",
        status="ACTIVE",
        manifest=[],
        corpus_hash="corpus",
        index_artifact_uri="index/chunks.json",
        index_setting_version="test",
        created_at=datetime.now(UTC),
        created_by="test-user",
    )

    context = await build_version_asset_context(
        settings,
        version=version,
        release=release,
    )
    images = images_for_chunk(version.canonical_content, context=context)
    payload, content_type = await read_version_asset(
        settings,
        context=context,
        filename="p05.png",
    )

    assert images[0].url.endswith("/versions/ver-guide-1/assets/p05.png")
    assert payload == b"indexed-image"
    assert content_type == "image/png"


@pytest.mark.asyncio
async def test_published_asset_rejects_unindexed_file(tmp_path) -> None:
    settings = PortalSettings.from_env()
    object.__setattr__(settings, "release_artifact_dir", tmp_path / "releases")
    version = KnowledgeVersionRecord(
        version_id="ver-guide-1",
        document_id="doc-guide",
        version_number=1,
        content_hash="content-hash",
        canonical_content="# Guide",
        effective_at="2026-09-17",
        review_due_at="2027-09-17",
        owner_unit_id="IT Service Desk",
        title="Guide",
        asset_slug="guide",
        status="PUBLISHED",
        etag='W/"ver-guide-1"',
        created_at=datetime.now(UTC),
        created_by="test-user",
    )
    index_path = settings.release_artifact_dir / "release-1" / "index" / "chunks.json"
    index_path.parent.mkdir(parents=True)
    index_path.write_text('{"chunks": []}', encoding="utf-8")
    release = ReleaseRecord(
        release_id="release-1",
        status="ACTIVE",
        manifest=[],
        corpus_hash="corpus",
        index_artifact_uri="index/chunks.json",
        index_setting_version="test",
        created_at=datetime.now(UTC),
        created_by="test-user",
    )
    context = await build_version_asset_context(
        settings,
        version=version,
        release=release,
    )

    with pytest.raises(FileNotFoundError):
        await read_version_asset(
            settings,
            context=context,
            filename="hidden.png",
        )
