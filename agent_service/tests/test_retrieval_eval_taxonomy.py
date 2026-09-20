"""Tests for retrieval vs Layer-3 answer failure taxonomy."""

from __future__ import annotations

from types import SimpleNamespace

from agent_service.documents import DocumentChunk
from agent_service.retrieval import SearchResult
from agent_service.retrieval_eval_taxonomy import (
    classify_layer3_failure,
    classify_retrieval_failure,
)


def _case(**overrides: object) -> SimpleNamespace:
    base = {
        "expected_found": True,
        "expected_documents": ["doc-a"],
        "expected_source_titles": ["Doc A"],
        "expected_evidence": [SimpleNamespace(must_contain=["alpha"])],
        "expected_version_id": None,
        "expected_release_id": None,
        "query": "how to reset",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _chunk(chunk_id: str, title: str = "Doc A") -> DocumentChunk:
    return DocumentChunk(
        chunk_id=chunk_id,
        title=title,
        content="alpha body",
        document_id="doc-a",
        source_path="sources/doc-a.md",
    )


def test_layer3_answer_omission_not_retrieval_miss() -> None:
    """Selected sources cover evidence but answer text does not."""
    category = classify_layer3_failure(
        _case(),
        answer_evidence_recall=0.0,
        retrieval_evidence_recall=1.0,
        citation_precision=1.0,
        found=True,
        sources_count=2,
    )
    assert category == "ANSWER_OMISSION"


def test_layer3_evidence_not_passed_when_sources_miss_facts() -> None:
    category = classify_layer3_failure(
        _case(),
        answer_evidence_recall=0.0,
        retrieval_evidence_recall=0.0,
        citation_precision=0.0,
        found=True,
        sources_count=2,
    )
    assert category == "EVIDENCE_NOT_PASSED_TO_GENERATOR"


def test_layer3_bad_citation_when_answer_complete() -> None:
    category = classify_layer3_failure(
        _case(),
        answer_evidence_recall=1.0,
        retrieval_evidence_recall=1.0,
        citation_precision=0.5,
        found=True,
        sources_count=2,
    )
    assert category == "BAD_CITATION"


def test_layer2_ranking_opportunity_unchanged() -> None:
    candidates = [
        SearchResult(
            chunk=_chunk("c1"),
            score=0.9,
            sparse_score=0.9,
            dense_score=0.0,
        )
    ]
    category = classify_retrieval_failure(
        _case(),
        evidence_recall_4=0.0,
        candidate_recall_24=1.0,
        top4_chunk_ids=["c1"],
        top4_titles=["Doc A"],
        candidates_24=candidates,
        is_predicted_no_answer=False,
    )
    assert category == "RANKING_OR_RERANKER_OPPORTUNITY"
