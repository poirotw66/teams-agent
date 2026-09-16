from __future__ import annotations

from typing import Any

import pytest

from agent_service.documents import DocumentChunk
from agent_service.mongodb_vector_spike import (
    MongoVectorShadowIndex,
    MongoVectorSpikeSettings,
    ingest_shadow_release,
    vector_search_index_definition,
)
from agent_service.retrieval import HybridIndex


class FakeEmbeddingClient:
    def embed_query(self, _query: str) -> list[float]:
        return [0.1, 0.2]


class FakeCollection:
    def __init__(self) -> None:
        self.pipeline: list[dict[str, Any]] = []
        self.replacements: list[tuple[dict[str, object], dict[str, object]]] = []

    def aggregate(self, pipeline: list[dict[str, Any]]) -> list[dict[str, object]]:
        self.pipeline = pipeline
        return [{"chunkId": "chunk-1", "score": 0.91}]

    def replace_one(
        self,
        selector: dict[str, object],
        document: dict[str, object],
        *,
        upsert: bool,
    ) -> None:
        assert upsert is True
        self.replacements.append((selector, document))


class FakeDatabase:
    def __init__(self, collection: FakeCollection) -> None:
        self._collection = collection

    def __getitem__(self, _name: str) -> FakeCollection:
        return self._collection


class FakeMongoClient:
    def __init__(self, collection: FakeCollection) -> None:
        self._database = FakeDatabase(collection)

    def __getitem__(self, _name: str) -> FakeDatabase:
        return self._database


def _index(*, vector: list[float] | None = None) -> HybridIndex:
    chunk = DocumentChunk(
        chunk_id="chunk-1",
        document_id="doc-1",
        version_id="version-1",
        title="VPN",
        source_path="sources/vpn.md",
        content="Reset the VPN client.",
        vector=vector,
        allowed_groups=["grp_public"],
    )
    index = HybridIndex([chunk])
    index.embedding_model_name = "gemini-embedding-2"
    index.embedding_client = FakeEmbeddingClient()
    return index


def _settings() -> MongoVectorSpikeSettings:
    return MongoVectorSpikeSettings(
        uri="mongodb://example.invalid",
        database="spike",
        collection="chunks",
        search_index="knowledge_vector",
    )


def test_shadow_search_filters_tenant_release_status_and_acl() -> None:
    collection = FakeCollection()
    shadow = MongoVectorShadowIndex(
        _index(vector=[0.1, 0.2]),
        _settings(),
        tenant_id="tenant-a",
        release_id="release-1",
        client=FakeMongoClient(collection),
    )

    results = shadow.search("VPN", 4, {"grp-vpn"})

    vector_search = collection.pipeline[0]["$vectorSearch"]
    assert {"tenantId": {"$eq": "tenant-a"}} in vector_search["filter"]["$and"]
    assert {"releaseId": {"$eq": "release-1"}} in vector_search["filter"]["$and"]
    assert results[0].chunk.chunk_id == "chunk-1"
    assert results[0].dense_score == 0.91


def test_shadow_ingestion_is_idempotent_and_marks_public_acl() -> None:
    collection = FakeCollection()

    written = ingest_shadow_release(
        _index(vector=[0.1, 0.2]),
        _settings(),
        tenant_id="tenant-a",
        release_id="release-1",
        client=FakeMongoClient(collection),
    )

    selector, document = collection.replacements[0]
    assert written == 1
    assert selector["chunkId"] == "chunk-1"
    assert document["aclTokens"] == ["__public__", "grp_public"]
    assert document["status"] == "SHADOW"


def test_shadow_ingestion_rejects_vectorless_chunk() -> None:
    with pytest.raises(ValueError, match="has no embedding"):
        ingest_shadow_release(
            _index(),
            _settings(),
            tenant_id="tenant-a",
            release_id="release-1",
            client=FakeMongoClient(FakeCollection()),
        )


def test_vector_index_definition_accepts_current_embedding_dimension() -> None:
    definition = vector_search_index_definition(3072)
    vector_field = definition["definition"]["fields"][0]
    assert vector_field["numDimensions"] == 3072
