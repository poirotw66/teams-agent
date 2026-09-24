"""Tests for provider-safe batch query embedding (Ticket 1)."""

from __future__ import annotations

from typing import Any

import pytest

from agent_service.documents import DocumentChunk
from agent_service.gemini_backend import reset_gemini_backend_for_tests
from agent_service.retrieval import HybridIndex
from agent_service.retrieval_embeddings import (
    embed_documents_batch,
    embed_queries_batch,
    embed_single_query,
)


class MockGoogleEmbeddings:
    """Simulates LangChain GoogleGenerativeAIEmbeddings with task_type distinction."""

    def __init__(self) -> None:
        self.embed_documents_calls: list[dict[str, Any]] = []
        self.embed_query_calls: list[dict[str, Any]] = []

    def embed_documents(
        self,
        texts: list[str],
        *,
        task_type: str | None = None,
    ) -> list[list[float]]:
        self.embed_documents_calls.append({"texts": texts, "task_type": task_type})
        # Simulate different embedding vector spaces for query vs document
        prefix = 1.0 if task_type == "RETRIEVAL_QUERY" else 0.5
        return [[prefix * (idx + 1) * len(t)] for idx, t in enumerate(texts)]

    def embed_query(
        self,
        text: str,
        *,
        task_type: str | None = None,
    ) -> list[float]:
        self.embed_query_calls.append({"text": text, "task_type": task_type})
        effective_task = task_type or "RETRIEVAL_QUERY"
        prefix = 1.0 if effective_task == "RETRIEVAL_QUERY" else 0.5
        return [prefix * len(text)]


class MockSymmetricEmbeddings:
    """Simulates symmetric embeddings like OpenAI (no task_type)."""

    def __init__(self) -> None:
        self.embed_documents_calls: list[list[str]] = []
        self.embed_query_calls: list[str] = []

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.embed_documents_calls.append(texts)
        return [[float(len(t))] for t in texts]

    def embed_query(self, text: str) -> list[float]:
        self.embed_query_calls.append(text)
        return [float(len(text))]


class MockQueryOnlyEmbeddings:
    """Client with only embed_query (fallback path)."""

    def __init__(self) -> None:
        self.embed_query_calls: list[str] = []

    def embed_query(self, text: str) -> list[float]:
        self.embed_query_calls.append(text)
        return [float(len(text))]


def test_google_embeddings_batch_enforces_retrieval_query_task() -> None:
    client = MockGoogleEmbeddings()
    queries = ["VPN 連線失敗", "錯誤碼 12029"]

    results = embed_queries_batch(client, queries)

    assert len(results) == 2
    assert len(client.embed_documents_calls) == 1
    call = client.embed_documents_calls[0]
    assert call["texts"] == queries
    # P0 invariant: Must pass task_type="RETRIEVAL_QUERY", not RETRIEVAL_DOCUMENT
    assert call["task_type"] == "RETRIEVAL_QUERY"


def test_google_embeddings_query_parity() -> None:
    client = MockGoogleEmbeddings()
    query = "PortalX 權限申請"

    single = embed_single_query(client, query)
    batch = embed_queries_batch(client, [query])[0]

    assert single == batch
    assert len(single) == 1
    assert single[0] == 1.0 * len(query)


def test_symmetric_embeddings_batch_delegation() -> None:
    client = MockSymmetricEmbeddings()
    queries = ["q1", "q2"]

    results = embed_queries_batch(client, queries)

    assert len(results) == 2
    assert len(client.embed_documents_calls) == 1
    assert client.embed_documents_calls[0] == queries


def test_fallback_to_individual_embed_query() -> None:
    client = MockQueryOnlyEmbeddings()
    queries = ["alpha", "beta"]

    results = embed_queries_batch(client, queries)

    assert len(results) == 2
    assert client.embed_query_calls == ["alpha", "beta"]


def test_embed_queries_empty_inputs() -> None:
    assert embed_queries_batch(None, ["q"]) == []
    assert embed_queries_batch(MockGoogleEmbeddings(), []) == []
    assert embed_single_query(None, "q") == []
    assert embed_single_query(MockGoogleEmbeddings(), "") == []


def test_retry_on_transient_recovers_from_disconnect() -> None:
    from agent_service.retrieval_embeddings import _retry_on_transient

    calls = {"n": 0}

    def flaky() -> str:
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("Server disconnected without sending a response.")
        return "ok"

    assert _retry_on_transient(flaky, initial_delay=0.01) == "ok"
    assert calls["n"] == 3


class MockBatchSizeEmbeddings:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def embed_documents(
        self,
        texts: list[str],
        *,
        batch_size: int = 100,
        task_type: str | None = None,
    ) -> list[list[float]]:
        self.calls.append(
            {"texts": list(texts), "batch_size": batch_size, "task_type": task_type}
        )
        if batch_size > 1 and len(texts) > 1:
            raise ValueError("The embedContent API for this model only supports one content at a time.")
        return [[float(len(text))] for text in texts]


def test_vertex_document_embed_uses_single_content_batch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reset_gemini_backend_for_tests()
    monkeypatch.setenv("GEMINI_API_BACKEND", "VERTEX_AI")
    monkeypatch.setenv("VERTEX_AI_PROJECT", "proj-a")
    monkeypatch.setenv("VERTEX_AI_CHAT_LOCATION", "us")
    monkeypatch.setenv("VERTEX_AI_EMBEDDING_LOCATION", "us")
    client = MockBatchSizeEmbeddings()
    vectors = embed_documents_batch(client, ["alpha", "beta"])
    assert vectors == [[5.0], [4.0]]
    assert client.calls[0]["batch_size"] == 1
    assert len(client.calls[0]["texts"]) == 2
    reset_gemini_backend_for_tests()


def test_document_embed_falls_back_when_api_rejects_batch() -> None:
    reset_gemini_backend_for_tests()
    client = MockBatchSizeEmbeddings()
    vectors = embed_documents_batch(client, ["alpha", "beta"])
    assert vectors == [[5.0], [4.0]]
    assert [call["texts"] for call in client.calls] == [
        ["alpha", "beta"],
        ["alpha"],
        ["beta"],
    ]
    reset_gemini_backend_for_tests()


def test_hybrid_index_embed_queries_delegation() -> None:
    client = MockGoogleEmbeddings()
    chunk = DocumentChunk(
        chunk_id="c1",
        title="T",
        source_path="t.md",
        content="C",
        vector=[1.0],
    )
    index = HybridIndex([chunk])
    index.embedding_client = client

    batch = index.embed_queries(["q1", "q2"])

    assert len(batch) == 2
    assert client.embed_documents_calls[0]["task_type"] == "RETRIEVAL_QUERY"
