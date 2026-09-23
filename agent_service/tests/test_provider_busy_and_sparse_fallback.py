"""Sparse fallback on embed outage and busy vs knowledge-miss UI copy."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_service.contracts import Issue, IssueResult
from agent_service.documents import DocumentChunk
from agent_service.provider_status import PROVIDER_BUSY, PROVIDER_BUSY_USER_MESSAGE
from agent_service.response_builder import build_response
from agent_service.retrieval import HybridIndex
from agent_service.settings import RagSettings


def _settings() -> RagSettings:
    return RagSettings(
        data_dir=Path("/tmp/data"),
        index_path=Path("/tmp/data/index/chunks.json"),
    )


def _issue(**overrides: object) -> Issue:
    defaults: dict[str, object] = {
        "id": 1,
        "description": "國金 CRM OTP",
        "isIT": True,
        "readiness": "READY",
        "missingInfo": [],
        "route": "KNOWLEDGE",
        "faqKey": None,
        "ticketAction": None,
    }
    defaults.update(overrides)
    return Issue(**defaults)  # type: ignore[arg-type]


def test_hybrid_search_falls_back_to_sparse_when_embed_raises_429(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chunk = DocumentChunk(
        chunk_id="crm",
        title="國金 CRM OTP 綁訂操作",
        source_path="sources/crm.md",
        content="國金 CRM 首次登入需使用 Google Authenticator 綁定 OTP",
        vector=[0.2, 0.8],
    )
    index = HybridIndex([chunk])
    index.embedding_client = object()
    index.enable_sparse_fast_path = False
    assert index.has_vectors

    def boom(_client: object, _query: str) -> list[float]:
        raise RuntimeError("429 RESOURCE_EXHAUSTED")

    monkeypatch.setattr(
        "agent_service.retrieval_embeddings.embed_single_query",
        boom,
    )

    results, timings = index.search_with_timings("國金 CRM OTP 綁定", limit=4)

    assert timings.get("embeddingDegraded") == 1.0
    assert results
    assert results[0].chunk.chunk_id == "crm"
    assert results[0].dense_score is None


def test_hybrid_search_reraises_non_transient_embed_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chunk = DocumentChunk(
        chunk_id="c1",
        title="T",
        source_path="t.md",
        content="content",
        vector=[1.0],
    )
    index = HybridIndex([chunk])
    index.embedding_client = object()
    index.enable_sparse_fast_path = False

    def boom(_client: object, _query: str) -> list[float]:
        raise ValueError("invalid api key")

    monkeypatch.setattr(
        "agent_service.retrieval_embeddings.embed_single_query",
        boom,
    )

    with pytest.raises(ValueError, match="invalid api key"):
        index.search_with_timings("hello", limit=4)


def test_response_builder_provider_busy_differs_from_knowledge_miss() -> None:
    issue = _issue()
    busy = IssueResult(
        issueId=1, resultType="NO_KNOWLEDGE", terminalReason=PROVIDER_BUSY
    )
    miss = IssueResult(
        issueId=1, resultType="NO_KNOWLEDGE", terminalReason="NO_RELEVANT_EVIDENCE"
    )

    busy_text = build_response(
        issues=[issue],
        results=[busy],
        settings=_settings(),
        offer_ticket_on_no_knowledge=True,
    ).text
    miss_text = build_response(
        issues=[issue],
        results=[miss],
        settings=_settings(),
        offer_ticket_on_no_knowledge=True,
    ).text

    assert PROVIDER_BUSY_USER_MESSAGE in busy_text
    assert "查無相關資訊" not in busy_text
    assert "無法從企業知識庫找到可確認的答案" not in busy_text

    assert "查無相關資訊" in miss_text
    assert PROVIDER_BUSY_USER_MESSAGE not in miss_text


def test_response_builder_failed_provider_busy_message() -> None:
    issue = _issue(description="測試問題")
    result = IssueResult(
        issueId=1,
        resultType="FAILED",
        terminalReason=PROVIDER_BUSY,
        error="RuntimeError: 429",
    )
    text = build_response(
        issues=[issue],
        results=[result],
        settings=_settings(),
        correlation_id="corr-1",
    ).text
    assert PROVIDER_BUSY_USER_MESSAGE in text
    assert "corr-1" in text
    assert "429" not in text


def test_handoff_skips_provider_busy_results() -> None:
    from agent_service.provider_status import is_provider_busy_terminal

    busy = IssueResult(
        issueId=1, resultType="NO_KNOWLEDGE", terminalReason=PROVIDER_BUSY
    )
    miss = IssueResult(
        issueId=2, resultType="NO_KNOWLEDGE", terminalReason="NO_RELEVANT_EVIDENCE"
    )
    assert is_provider_busy_terminal(busy.terminalReason)
    assert not is_provider_busy_terminal(miss.terminalReason)

    trigger_ids = {
        result.issueId
        for result in (busy, miss)
        if result.resultType in {"NO_KNOWLEDGE", "FAILED"}
        and not is_provider_busy_terminal(result.terminalReason)
    }
    assert trigger_ids == {2}
