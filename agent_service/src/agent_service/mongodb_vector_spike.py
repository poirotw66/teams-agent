"""Optional MongoDB Atlas Vector Search shadow adapter.

This module is deliberately excluded from runtime wiring. It supports repeatable
ingestion and evaluation without making MongoDB a production dependency.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from .retrieval import HybridIndex, SearchResult

PUBLIC_ACL_TOKEN = "__public__"


@dataclass(frozen=True)
class MongoVectorSpikeSettings:
    uri: str
    database: str
    collection: str
    search_index: str

    @classmethod
    def from_env(cls) -> MongoVectorSpikeSettings | None:
        uri = os.environ.get("MONGODB_URI", "").strip()
        if not uri:
            return None
        return cls(
            uri=uri,
            database=os.environ.get(
                "MONGODB_VECTOR_DATABASE",
                "teams_agent_spike",
            ),
            collection=os.environ.get(
                "MONGODB_VECTOR_COLLECTION",
                "knowledge_chunks",
            ),
            search_index=os.environ.get(
                "MONGODB_VECTOR_INDEX",
                "knowledge_vector",
            ),
        )


class MongoVectorShadowIndex:
    def __init__(
        self,
        source_index: HybridIndex,
        settings: MongoVectorSpikeSettings,
        *,
        tenant_id: str,
        release_id: str,
        client: Any = None,
    ) -> None:
        if source_index.embedding_client is None:
            raise ValueError("MongoDB vector evaluation requires an embedding model.")
        self._source_index = source_index
        self._settings = settings
        self._tenant_id = tenant_id
        self._release_id = release_id
        self._client = client or _build_mongo_client(settings.uri)
        self._collection = self._client[settings.database][settings.collection]
        self._chunks_by_id = {
            chunk.chunk_id: chunk for chunk in source_index.chunks
        }

    def search(
        self,
        query: str,
        limit: int,
        groups: set[str] | None = None,
    ) -> list[SearchResult]:
        query_vector = self._source_index.embedding_client.embed_query(query)
        acl_tokens = sorted((groups or set()) | {PUBLIC_ACL_TOKEN})
        pipeline = [
            {
                "$vectorSearch": {
                    "index": self._settings.search_index,
                    "path": "embedding",
                    "queryVector": query_vector,
                    "numCandidates": max(100, limit * 20),
                    "limit": limit,
                    "filter": {
                        "$and": [
                            {"tenantId": {"$eq": self._tenant_id}},
                            {"releaseId": {"$eq": self._release_id}},
                            {"status": {"$eq": "SHADOW"}},
                            {"aclTokens": {"$in": acl_tokens}},
                        ]
                    },
                }
            },
            {
                "$project": {
                    "_id": 0,
                    "chunkId": 1,
                    "score": {"$meta": "vectorSearchScore"},
                }
            },
        ]
        results: list[SearchResult] = []
        for item in self._collection.aggregate(pipeline):
            chunk = self._chunks_by_id.get(str(item.get("chunkId") or ""))
            if chunk is None:
                continue
            score = float(item.get("score") or 0.0)
            results.append(
                SearchResult(
                    chunk=chunk,
                    score=round(score, 6),
                    sparse_score=0.0,
                    dense_score=round(score, 6),
                )
            )
        return results


def ingest_shadow_release(
    index: HybridIndex,
    settings: MongoVectorSpikeSettings,
    *,
    tenant_id: str,
    release_id: str,
    client: Any = None,
) -> int:
    mongo_client = client or _build_mongo_client(settings.uri)
    collection = mongo_client[settings.database][settings.collection]
    written = 0
    for chunk in index.chunks:
        if not chunk.vector:
            raise ValueError(
                f"Chunk '{chunk.chunk_id}' has no embedding and cannot be ingested."
            )
        acl_tokens = _acl_tokens(chunk.allowed_groups)
        collection.replace_one(
            {
                "tenantId": tenant_id,
                "releaseId": release_id,
                "chunkId": chunk.chunk_id,
            },
            {
                "tenantId": tenant_id,
                "releaseId": release_id,
                "documentId": chunk.document_id,
                "versionId": chunk.version_id,
                "chunkId": chunk.chunk_id,
                "content": chunk.content,
                "title": chunk.title,
                "embedding": chunk.vector,
                "embeddingModel": index.embedding_model_name,
                "aclTokens": acl_tokens,
                "sourcePath": chunk.source_path,
                "status": "SHADOW",
            },
            upsert=True,
        )
        written += 1
    return written


def vector_search_index_definition(dimensions: int) -> dict[str, object]:
    if not 1 <= dimensions <= 4096:
        raise ValueError("MongoDB Vector Search dimensions must be between 1 and 4096.")
    return {
        "name": "knowledge_vector",
        "type": "vectorSearch",
        "definition": {
            "fields": [
                {
                    "type": "vector",
                    "path": "embedding",
                    "numDimensions": dimensions,
                    "similarity": "cosine",
                },
                {"type": "filter", "path": "tenantId"},
                {"type": "filter", "path": "releaseId"},
                {"type": "filter", "path": "aclTokens"},
                {"type": "filter", "path": "status"},
            ]
        },
    }


def _acl_tokens(groups: list[str] | None) -> list[str]:
    normalized = {item for item in groups or [] if item}
    if not normalized or "grp_public" in normalized:
        normalized.add(PUBLIC_ACL_TOKEN)
    return sorted(normalized)


def _build_mongo_client(uri: str) -> Any:
    try:
        from pymongo import MongoClient
    except ImportError as error:  # pragma: no cover - optional spike dependency
        raise RuntimeError(
            "Install the mongodb-spike extra to run Atlas evaluation."
        ) from error
    return MongoClient(
        uri,
        appname="teams-agent-vector-shadow",
        connectTimeoutMS=10_000,
        serverSelectionTimeoutMS=10_000,
        retryWrites=True,
    )
