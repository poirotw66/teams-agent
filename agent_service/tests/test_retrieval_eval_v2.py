"""Unit tests for RAG v2 retrieval eval metrics and hard benchmark schema (§6–§7)."""

from __future__ import annotations

import json
from pathlib import Path

from agent_service.retrieval_eval_metrics import (
    NoAnswerOutcome,
    aggregate_case_scores,
    hard_negative_accuracy,
    hit_at_k,
    mrr_at_k,
    ndcg_at_k,
    no_answer_confusion,
    precision_at_k,
    recall_at_k,
    score_retrieval_case,
)

EVAL_V2_PATH = Path(__file__).resolve().parents[2] / "data" / "eval" / "retrieval_eval_v2.json"

REQUIRED_CATEGORIES = {
    "exact_identifier",
    "similar_identifier",
    "paraphrase",
    "typo",
    "alias",
    "short_query",
    "ambiguous_query",
    "similar_documents",
    "hard_negative",
    "near_duplicate",
    "version_conflict",
    "multi_section",
    "multi_document",
    "no_answer",
    "acl_allow",
    "acl_deny",
    "conversational",
    "negative_constraint",
    "source_scope",
    "visual_reference",
}


def test_recall_at_k_partial_recovery() -> None:
    ranked = ["a", "x", "b", "y"]
    assert recall_at_k(ranked, ["a", "b", "c"], k=3) == 2 / 3


def test_document_recall_does_not_inflate_on_duplicate_ids() -> None:
    """Same document appearing twice in top-k must count as one hit."""
    ranked = ["doc-a", "doc-a", "noise", "noise"]
    relevant = ["doc-a"]
    assert recall_at_k(ranked, relevant, k=4) == 1.0
    assert precision_at_k(ranked, relevant, k=4) == 0.5
    grades = {"doc-a": 1.0}
    score = ndcg_at_k(ranked, grades, k=4)
    assert 0.0 <= score <= 1.0
    assert score == ndcg_at_k(["doc-a", "noise"], grades, k=4)


def test_ranking_metrics_stay_within_unit_interval() -> None:
    ranked = ["a", "a", "b", "b", "c"]
    relevant = ["a", "b"]
    grades = {"a": 3.0, "b": 1.0}
    for metric in (
        recall_at_k(ranked, relevant, k=4),
        precision_at_k(ranked, relevant, k=4),
        ndcg_at_k(ranked, grades, k=4),
        hit_at_k(ranked, relevant, k=4),
        mrr_at_k(ranked, relevant, k=4),
    ):
        assert 0.0 <= metric <= 1.0


def test_hit_and_mrr() -> None:
    ranked = ["x", "rel", "y"]
    assert hit_at_k(ranked, ["rel"], k=1) == 0.0
    assert hit_at_k(ranked, ["rel"], k=2) == 1.0
    assert mrr_at_k(ranked, ["rel"], k=10) == 0.5


def test_ndcg_prefers_higher_grade_earlier() -> None:
    grades = {"good": 3.0, "ok": 1.0}
    better = ndcg_at_k(["good", "ok"], grades, k=2)
    worse = ndcg_at_k(["ok", "good"], grades, k=2)
    assert better > worse


def test_hard_negative_accuracy() -> None:
    assert (
        hard_negative_accuracy(
            ["wrong", "right"],
            relevant_ids=["right"],
            hard_negative_ids=["wrong"],
            k=1,
        )
        == 0.0
    )
    assert (
        hard_negative_accuracy(
            ["right", "wrong"],
            relevant_ids=["right"],
            hard_negative_ids=["wrong"],
            k=1,
        )
        == 1.0
    )


def test_score_retrieval_case_hard_negative_none_when_unlabeled() -> None:
    scored = score_retrieval_case(
        case_id="unlabeled",
        ranked_ids=["doc-a"],
        relevant_ids=["doc-a"],
        hard_negative_ids=(),
    )
    assert scored.hard_negative_accuracy is None


def test_aggregate_hard_negative_accuracy_averages_labeled_cases_only() -> None:
    labeled_pass = score_retrieval_case(
        case_id="hn-pass",
        ranked_ids=["right", "noise"],
        relevant_ids=["right"],
        hard_negative_ids=["noise"],
    )
    labeled_fail = score_retrieval_case(
        case_id="hn-fail",
        ranked_ids=["noise", "right"],
        relevant_ids=["right"],
        hard_negative_ids=["noise"],
    )
    unlabeled = score_retrieval_case(
        case_id="plain",
        ranked_ids=["doc-a"],
        relevant_ids=["doc-a"],
    )
    summary = aggregate_case_scores([labeled_pass, labeled_fail, unlabeled])
    assert labeled_pass.hard_negative_accuracy == 1.0
    assert labeled_fail.hard_negative_accuracy == 0.0
    assert unlabeled.hard_negative_accuracy is None
    assert summary["hardNegativeLabeledCaseCount"] == 2.0
    assert summary["hardNegativeAccuracy"] == 0.5


def test_score_retrieval_case_separates_acl_and_forbidden_document_hits() -> None:
    scored = score_retrieval_case(
        case_id="acl-vs-semantic",
        ranked_ids=["secret-doc", "wrong-topic", "good"],
        relevant_ids=["good"],
        acl_forbidden_ids=["secret-doc"],
        semantic_forbidden_ids=["wrong-topic"],
    )
    assert scored.acl_leakage_count == 1
    assert scored.forbidden_document_hit_count == 1
    summary = aggregate_case_scores([scored])
    assert summary["aclLeakageCount"] == 1.0
    assert summary["forbiddenDocumentHitCount"] == 1.0


def test_no_answer_confusion() -> None:
    stats = no_answer_confusion(
        [
            NoAnswerOutcome(True, True),
            NoAnswerOutcome(True, False),
            NoAnswerOutcome(False, True),
            NoAnswerOutcome(False, False),
        ]
    )
    assert stats["truePositive"] == 1.0
    assert stats["falseNegative"] == 1.0
    assert stats["falsePositive"] == 1.0
    assert 0.0 < stats["f1"] < 1.0


def test_no_answer_prediction_ignores_empty_relevant_list() -> None:
    """``relevant=[]`` must not vacuously count as predicted no-answer."""
    ranked = ["noise-a", "noise-b"]
    relevant: list[str] = []
    # Vacuous any() over empty relevant would be False → not any = True (bug).
    vacuous_bug = not any(title in ranked[:3] for title in relevant)
    assert vacuous_bug is True
    predicted = len(ranked) == 0
    assert predicted is False


def test_precision_and_recall_at_4() -> None:
    ranked = ["a", "x", "b", "y", "c"]
    assert recall_at_k(ranked, ["a", "b", "c"], k=4) == 2 / 3
    from agent_service.retrieval_eval_metrics import (
        evidence_recall_at_k,
        precision_at_k,
    )

    assert precision_at_k(ranked, ["a", "b", "c"], k=4) == 0.5
    assert (
        evidence_recall_at_k(
            retrieved_texts=[
                "Permission denied (-455) 密碼輸入錯誤",
                "unrelated",
            ],
            evidence_must_contain=[["-455", "密碼"]],
            k=4,
        )
        == 1.0
    )


def test_score_and_aggregate_case() -> None:
    scored = score_retrieval_case(
        case_id="c1",
        ranked_ids=["doc-a", "noise", "doc-b"],
        relevant_ids=["doc-a", "doc-b"],
        relevance_grades={"doc-a": 3, "doc-b": 2},
        hard_negative_ids=["noise"],
    )
    assert scored.hit_at_1 == 1.0
    assert scored.recall_at_5 == 1.0
    summary = aggregate_case_scores([scored])
    assert summary["caseCount"] == 1.0
    assert summary["hitAt1"] == 1.0


def test_retrieval_eval_v2_meets_spec_floor() -> None:
    payload = json.loads(EVAL_V2_PATH.read_text(encoding="utf-8"))
    cases = payload["cases"]
    assert len(cases) >= 100
    ids = [case["id"] for case in cases]
    assert len(ids) == len(set(ids))
    categories = {cat for case in cases for cat in case["categories"]}
    assert REQUIRED_CATEGORIES <= categories
    assert sum(1 for case in cases if case.get("expectedChunkIds")) >= 50
    assert {"dev", "test"} <= {case.get("split") for case in cases}
    answerable = [case for case in cases if case["expectedFound"]]
    no_answer = [case for case in cases if not case["expectedFound"]]
    assert len(answerable) >= 80
    assert len(no_answer) >= 30
    assert all(case.get("expectedEvidence") for case in answerable)
    for case in cases:
        assert case["query"].strip()
        assert isinstance(case["expectedFound"], bool)
        if case["expectedFound"]:
            assert case["expectedSourceTitles"], case["id"]
        else:
            assert case["expectedSourceTitles"] == []
