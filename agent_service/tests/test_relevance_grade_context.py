"""Tests for relevance grade-context ordering and deterministic LLM guards."""

from __future__ import annotations

from agent_service.documents import DocumentChunk
from agent_service.knowledge_pipeline.relevance import build_relevance_grade_context
from agent_service.retrieval import SearchResult


def _result(*, doc_id: str, title: str, content: str, score: float) -> SearchResult:
    return SearchResult(
        chunk=DocumentChunk(
            chunk_id=doc_id,
            title=title,
            content=content,
            document_id=doc_id,
            source_path=f"sources/{doc_id}.md",
        ),
        score=score,
        sparse_score=score,
        dense_score=0.0,
    )


def test_grade_context_prefers_highest_score_unique_titles() -> None:
    results = [
        _result(
            doc_id="ad-1",
            title="AD 帳號與系統解鎖 FAQ",
            content="AD 自助解鎖專區",
            score=0.76,
        ),
        _result(
            doc_id="ad-2",
            title="AD 帳號與系統解鎖 FAQ",
            content="開機密碼解鎖",
            score=0.75,
        ),
        _result(
            doc_id="portal-howto",
            title="金控入口網密碼變更方式",
            content="齒輪選單密碼變更",
            score=0.71,
        ),
        _result(
            doc_id="employee-portal",
            title="國泰員工入口網、CTeam密碼、國泰e點名",
            content="密碼連動為國泰金控網站帳密 (並非AD)",
            score=1.0,
        ),
    ]
    context = build_relevance_grade_context(results, limit=3)
    assert "並非AD" in context
    assert context.index("國泰員工入口網") < context.index("AD 帳號與系統解鎖 FAQ")
    # Duplicate AD title should not consume a second grade slot.
    assert context.count("[AD 帳號與系統解鎖 FAQ]") == 1
