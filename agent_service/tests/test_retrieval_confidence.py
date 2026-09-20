"""Tests for the shared retrieval Confidence Contract."""

from __future__ import annotations

from agent_service.documents import DocumentChunk
from agent_service.knowledge_pipeline.retrieval_confidence import (
    ConfidenceLevel,
    build_confidence_features,
    calibrated_predict_no_answer,
    evaluate_confidence,
    evaluate_retrieval_confidence,
)
from agent_service.retrieval import SearchResult


def _chunk(chunk_id: str, *, title: str, content: str) -> DocumentChunk:
    return DocumentChunk(
        chunk_id=chunk_id,
        title=title,
        content=content,
        source_path=f"{chunk_id}.md",
        document_id=chunk_id,
    )


def _hit(chunk_id: str, *, title: str, content: str, score: float) -> SearchResult:
    return SearchResult(
        chunk=_chunk(chunk_id, title=title, content=content),
        score=score,
        sparse_score=score,
        dense_score=score * 0.9,
    )


def test_calibrated_predict_no_answer_uses_min_score_floor() -> None:
    assert (
        calibrated_predict_no_answer(
            ranked_ids=["a"],
            scores=[0.20],
            texts=["VPN Permission denied (-455)"],
            query="VPN Permission denied (-455)",
            min_score=0.45,
        )
        is True
    )


def test_calibrated_predict_no_answer_rejects_unrelated_top_hits() -> None:
    assert (
        calibrated_predict_no_answer(
            ranked_ids=["a"],
            scores=[0.90],
            texts=["座位搬遷需求請填電腦聯繫單"],
            query="公司量子加密 VPN 金鑰輪替週期是幾天？",
            min_score=0.45,
        )
        is True
    )


def test_evaluate_confidence_high_for_strong_lexical_match() -> None:
    results = [
        _hit(
            "vpn",
            title="VPN常見Q&A問答",
            content="Permission denied (-455) 密碼輸入錯誤",
            score=0.90,
        )
    ]
    features = build_confidence_features(query="VPN Permission denied (-455)", results=results)
    assert evaluate_confidence(features, min_score=0.45) is ConfidenceLevel.HIGH
    label, is_pass = evaluate_retrieval_confidence(
        query="VPN Permission denied (-455)",
        results=results,
        min_score=0.45,
        filter_displaced_top1=False,
    )
    assert label == "HIGH_CONFIDENCE_PASS"
    assert is_pass is True


def test_evaluate_confidence_low_when_lexical_overlap_missing() -> None:
    results = [
        _hit(
            "seat",
            title="座位搬遷需求",
            content="請填寫電腦聯繫單",
            score=0.50,
        )
    ]
    features = build_confidence_features(
        query="公司量子加密 VPN 金鑰輪替週期是幾天？",
        results=results,
    )
    assert evaluate_confidence(features, min_score=0.45) is ConfidenceLevel.LOW


def test_mid_score_weak_lexical_is_uncertain_not_low() -> None:
    """Mid-band weak overlap stays UNCERTAIN so rewrite is not auto-triggered."""
    results = [
        _hit(
            "generic",
            title="一般說明",
            content="系統操作說明",
            score=0.70,
        )
    ]
    features = build_confidence_features(query="這個怎麼設定", results=results)
    assert evaluate_confidence(features, min_score=0.08) is ConfidenceLevel.UNCERTAIN
    label, is_pass = evaluate_retrieval_confidence(
        query="這個怎麼設定",
        results=results,
        min_score=0.08,
        filter_displaced_top1=False,
    )
    assert label == "LLM_RELEVANCE"
    assert is_pass is False


def test_calibrated_predict_rescues_high_score_distinctive_title_hit() -> None:
    assert (
        calibrated_predict_no_answer(
            ranked_ids=["share"],
            scores=[1.0],
            texts=["同仁申請共用公槽資料夾\n請填寫電腦聯繫單申請共用權限"],
            titles=["同仁申請共用公槽資料夾"],
            query="要幫同事加共用磁碟權限要填什麼",
            min_score=0.45,
        )
        is False
    )


def test_calibrated_predict_keeps_generic_title_hard_negative() -> None:
    assert (
        calibrated_predict_no_answer(
            ranked_ids=["phone"],
            scores=[1.0],
            texts=["總公司IP話機操作\n分機設定說明"],
            titles=["總公司IP話機操作"],
            query="總公司地下停車場訪客臨停申請表下載？",
            min_score=0.45,
        )
        is True
    )
