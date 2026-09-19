"""Tests for RAG v2 reranker protocol (spec §43)."""

from __future__ import annotations

import pytest

from agent_service.documents import DocumentChunk
from agent_service.reranker import (
    FailOpenReranker,
    ModelReranker,
    NoopReranker,
    apply_exact_identifier_guard,
    candidate_retrieval_texts,
    extract_exact_identifiers,
    tier_meets_minimum,
)
from agent_service.retrieval import SearchResult


def _result(chunk_id: str, *, title: str = "t", content: str | None = None) -> SearchResult:
    body = content if content is not None else f"body-{chunk_id}"
    return SearchResult(
        chunk=DocumentChunk(
            chunk_id=chunk_id,
            title=title,
            source_path=f"{chunk_id}.md",
            content=body,
            retrieval_text=f"ctx\n\n{body}",
        ),
        score=1.0,
        sparse_score=1.0,
        dense_score=0.5,
        fusion_rank=1,
        fusion_score=0.5,
    )


@pytest.mark.asyncio
async def test_noop_preserves_order_and_limit() -> None:
    candidates = [_result("a"), _result("b"), _result("c")]
    ranked = await NoopReranker().rerank(query="q", candidates=candidates, limit=2)
    assert [item.chunk.chunk_id for item in ranked] == ["a", "b"]
    assert ranked[0].rerank_rank == 1
    assert ranked[1].final_rank == 2


@pytest.mark.asyncio
async def test_fail_open_on_exception() -> None:
    class Boom:
        async def rerank(self, *, query: str, candidates: list[SearchResult], limit: int):
            raise RuntimeError("model down")

    candidates = [_result("a"), _result("b")]
    ranked = await FailOpenReranker(Boom(), timeout_seconds=1.0).rerank(
        query="q", candidates=candidates, limit=2
    )
    assert [item.chunk.chunk_id for item in ranked] == ["a", "b"]


@pytest.mark.asyncio
async def test_fail_open_on_timeout() -> None:
    class Slow:
        async def rerank(self, *, query: str, candidates: list[SearchResult], limit: int):
            import asyncio

            await asyncio.sleep(1.0)
            return candidates

    candidates = [_result("a")]
    ranked = await FailOpenReranker(Slow(), timeout_seconds=0.01).rerank(
        query="q", candidates=candidates, limit=1
    )
    assert ranked[0].chunk.chunk_id == "a"


def test_candidate_texts_use_retrieval_text() -> None:
    texts = candidate_retrieval_texts([_result("a")])
    assert texts == ["ctx\n\nbody-a"]


@pytest.mark.asyncio
async def test_model_reranker_changes_incorrect_top1() -> None:
    async def score_pairs(query: str, texts: list[str]) -> list[float]:
        del query
        # Prefer the second candidate.
        return [0.1 if "wrong" in text else 0.9 for text in texts]

    wrong = _result("wrong", content="generic vpn advice")
    right = _result("right", content="Permission denied (-455) password lock")
    ranked = await ModelReranker(score_pairs, protect_exact_identifiers=False).rerank(
        query="VPN (-455)",
        candidates=[wrong, right],
        limit=2,
    )
    assert ranked[0].chunk.chunk_id == "right"
    assert ranked[0].rerank_score == 0.9


@pytest.mark.asyncio
async def test_exact_identifier_candidate_preserved() -> None:
    async def score_pairs(query: str, texts: list[str]) -> list[float]:
        del query
        # Model wrongly prefers the non-matching doc.
        return [0.99 if "no-code" in text else 0.1 for text in texts]

    no_code = _result("no-code", content="generic network troubleshooting no-code")
    with_code = _result("with-code", content="Permission denied (-455) password issue")
    ranked = await ModelReranker(score_pairs).rerank(
        query="VPN Permission denied (-455)",
        candidates=[no_code, with_code],
        limit=2,
    )
    assert ranked[0].chunk.chunk_id == "with-code"


def test_exact_identifier_guard_promotes_match() -> None:
    no_code = _result("no-code", content="generic advice")
    with_code = _result("with-code", content="error (-14) update FortiClient")
    guarded = apply_exact_identifier_guard("Unable to establish (-14)", [no_code, with_code])
    assert guarded[0].chunk.chunk_id == "with-code"


def test_error_code_guard_ignores_vpn_token_only_queries() -> None:
    from agent_service.reranker import apply_error_code_guard

    vpn_generic = _result("vpn-generic", content="VPN client reconnect steps")
    other = _result("other", content="AD unlock FAQ")
    # No numeric code → guard is a no-op even though VPN token exists.
    guarded = apply_error_code_guard("VPN cannot connect", [other, vpn_generic])
    assert guarded[0].chunk.chunk_id == "other"


def test_error_code_guard_promotes_numeric_match() -> None:
    from agent_service.reranker import apply_error_code_guard

    wrong = _result("wrong", content="generic network advice")
    right = _result("right", content="Permission denied (-455) locked")
    guarded = apply_error_code_guard("VPN (-455)", [wrong, right])
    assert guarded[0].chunk.chunk_id == "right"


def test_extract_identifiers_and_tier_gate() -> None:
    assert "-455" in extract_exact_identifiers("Permission denied (-455)")
    assert "OTP" in extract_exact_identifiers("FortiToken OTP mail")
    assert tier_meets_minimum("hard", "standard")
    assert not tier_meets_minimum("trivial", "standard")


@pytest.mark.asyncio
async def test_build_default_reranker_lexical_when_enabled() -> None:
    from agent_service.reranker import build_default_reranker

    reranker = build_default_reranker(enabled=True, timeout_ms=700, model_name="lexical")
    wrong = _result("wrong", content="generic advice")
    right = _result("right", content="Permission denied (-455) VPN lock")
    ranked = await reranker.rerank(
        query="Permission denied (-455)",
        candidates=[wrong, right],
        limit=2,
    )
    assert ranked[0].chunk.chunk_id == "right"
