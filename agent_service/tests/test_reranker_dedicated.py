"""Tests for dedicated reranker factory routing (RAG v2.1)."""

from __future__ import annotations

import pytest

from agent_service.reranker import FailOpenReranker, NoopReranker, build_default_reranker
from agent_service.reranker_dedicated import (
    build_qwen3_reranker_pair_scorer,
    build_vertex_ranking_pair_scorer,
)


def test_build_default_reranker_disabled_is_noop() -> None:
    assert isinstance(
        build_default_reranker(enabled=False, timeout_ms=700, model_name="vertex-ranking"),
        NoopReranker,
    )


def test_build_default_reranker_vertex_routes_to_fail_open(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VERTEX_RANKING_PROJECT", raising=False)
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    monkeypatch.delenv("GCLOUD_PROJECT", raising=False)
    reranker = build_default_reranker(
        enabled=True,
        timeout_ms=700,
        model_name="vertex-ranking",
    )
    assert isinstance(reranker, FailOpenReranker)


@pytest.mark.asyncio
async def test_vertex_ranking_requires_project(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VERTEX_RANKING_PROJECT", raising=False)
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    monkeypatch.delenv("GCLOUD_PROJECT", raising=False)
    scorer = build_vertex_ranking_pair_scorer("vertex-ranking")
    with pytest.raises(RuntimeError, match="VERTEX_RANKING_PROJECT"):
        await scorer("query", ["doc a", "doc b"])


def test_qwen3_factory_returns_callable() -> None:
    scorer = build_qwen3_reranker_pair_scorer("qwen3-reranker:Qwen/Qwen3-Reranker-0.6B")
    assert callable(scorer)
