"""Pure retrieval ranking metrics for RAG v2 Evaluation (spec §6–§7).

No I/O, network, or knowledge-service coupling. Callers supply ranked ids and
relevance judgments; this module only scores.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass


def _unique_preserve_order(ids: Sequence[str]) -> list[str]:
    """Deduplicate ranked ids while keeping first-seen order.

    Document-level metrics must not inflate when the same document contributes
    multiple chunks/bundles into the top-``k`` window.
    """
    seen: set[str] = set()
    unique: list[str] = []
    for item in ids:
        if not item or item in seen:
            continue
        seen.add(item)
        unique.append(item)
    return unique


def recall_at_k(
    ranked_ids: Sequence[str],
    relevant_ids: Iterable[str],
    *,
    k: int,
) -> float:
    """Fraction of relevant items recovered in the top-``k`` unique ranks."""
    relevant = {item for item in relevant_ids if item}
    if not relevant:
        return 0.0
    top = _unique_preserve_order(ranked_ids)[:k]
    hit = sum(1 for item in top if item in relevant)
    return hit / len(relevant)


def hit_at_k(
    ranked_ids: Sequence[str],
    relevant_ids: Iterable[str],
    *,
    k: int,
) -> float:
    """1.0 if any relevant id appears in top-``k`` unique ranks, else 0.0."""
    relevant = {item for item in relevant_ids if item}
    if not relevant:
        return 0.0
    top = _unique_preserve_order(ranked_ids)[:k]
    return 1.0 if any(item in relevant for item in top) else 0.0


def mrr_at_k(
    ranked_ids: Sequence[str],
    relevant_ids: Iterable[str],
    *,
    k: int,
) -> float:
    """Mean Reciprocal Rank of the first relevant hit within top-``k`` unique ranks."""
    relevant = {item for item in relevant_ids if item}
    if not relevant:
        return 0.0
    for rank, item in enumerate(_unique_preserve_order(ranked_ids)[:k], start=1):
        if item in relevant:
            return 1.0 / rank
    return 0.0


def ndcg_at_k(
    ranked_ids: Sequence[str],
    relevance_grades: Mapping[str, float],
    *,
    k: int,
) -> float:
    """Normalized Discounted Cumulative Gain at ``k`` using graded relevance.

    Duplicate ranked ids are collapsed before scoring so multi-chunk hits for
    one document cannot push NDCG above 1.0.
    """
    if k <= 0:
        return 0.0
    top = _unique_preserve_order(ranked_ids)[:k]
    gains = [float(relevance_grades.get(item, 0.0)) for item in top]
    dcg = sum(gain / math.log2(rank + 1) for rank, gain in enumerate(gains, start=1))
    ideal = sorted((float(v) for v in relevance_grades.values() if v > 0), reverse=True)[:k]
    idcg = sum(gain / math.log2(rank + 1) for rank, gain in enumerate(ideal, start=1))
    if idcg <= 0.0:
        return 0.0
    return dcg / idcg


@dataclass(frozen=True)
class NoAnswerOutcome:
    expected_no_answer: bool
    predicted_no_answer: bool


def no_answer_confusion(outcomes: Sequence[NoAnswerOutcome]) -> dict[str, float]:
    """Precision / recall / F1 for the no-answer decision."""
    true_positive = sum(1 for row in outcomes if row.expected_no_answer and row.predicted_no_answer)
    false_positive = sum(
        1 for row in outcomes if not row.expected_no_answer and row.predicted_no_answer
    )
    false_negative = sum(
        1 for row in outcomes if row.expected_no_answer and not row.predicted_no_answer
    )
    precision = (
        true_positive / (true_positive + false_positive)
        if (true_positive + false_positive)
        else 0.0
    )
    recall = (
        true_positive / (true_positive + false_negative)
        if (true_positive + false_negative)
        else 0.0
    )
    if precision + recall == 0.0:
        f1 = 0.0
    else:
        f1 = 2.0 * precision * recall / (precision + recall)
    return {
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "truePositive": float(true_positive),
        "falsePositive": float(false_positive),
        "falseNegative": float(false_negative),
    }


def hard_negative_accuracy(
    ranked_ids: Sequence[str],
    *,
    relevant_ids: Iterable[str],
    hard_negative_ids: Iterable[str],
    k: int = 1,
) -> float:
    """1.0 when top-``k`` prefers a relevant id over any hard negative."""
    relevant = {item for item in relevant_ids if item}
    hard_negatives = {item for item in hard_negative_ids if item}
    if not relevant:
        return 0.0
    top = list(ranked_ids[:k])
    if any(item in hard_negatives for item in top) and not any(item in relevant for item in top):
        return 0.0
    if any(item in relevant for item in top):
        return 1.0
    return 0.0


def acl_leakage_count(
    ranked_ids: Sequence[str],
    forbidden_ids: Iterable[str],
) -> int:
    """Count of forbidden (ACL-denied) ids that still appear in ranked results."""
    forbidden = {item for item in forbidden_ids if item}
    return sum(1 for item in ranked_ids if item in forbidden)


@dataclass(frozen=True)
class RetrievalCaseScore:
    case_id: str
    recall_at_5: float
    recall_at_10: float
    recall_at_20: float
    recall_at_4: float
    precision_at_4: float
    evidence_recall_at_4: float | None
    evidence_precision_at_4: float | None
    mrr_at_10: float
    ndcg_at_10: float
    hit_at_1: float
    hit_at_3: float
    hard_negative_accuracy: float | None = None
    acl_leakage_count: int = 0
    has_evidence_labels: bool = False


def precision_at_k(
    ranked_ids: Sequence[str],
    relevant_ids: Iterable[str],
    *,
    k: int,
) -> float:
    """Fraction of top-``k`` unique ranks that are relevant (0 when empty)."""
    relevant = {item for item in relevant_ids if item}
    top = _unique_preserve_order(ranked_ids)[:k]
    if not top:
        return 0.0
    return sum(1 for item in top if item in relevant) / len(top)


def _collapse_whitespace(value: str) -> str:
    return "".join(value.split())


def evidence_token_in_text(token: str, text: str) -> bool:
    """Substring match that ignores whitespace differences (e.g. 並非AD vs 並非 AD)."""
    if not token:
        return True
    haystack = text or ""
    if token in haystack:
        return True
    collapsed_token = _collapse_whitespace(token)
    collapsed_haystack = _collapse_whitespace(haystack)
    if collapsed_token and collapsed_token in collapsed_haystack:
        return True
    # Allow common intervening particles inside CJK compounds (帳號遭鎖定 ≈ 帳號鎖定).
    if len(collapsed_token) >= 4 and re.fullmatch(
        r"[\u3400-\u9fffA-Za-z0-9_./:-]+",
        collapsed_token,
    ):
        pattern = "".join(
            re.escape(char) + r"[遭被已了的之與和]{0,2}"
            for char in collapsed_token[:-1]
        ) + re.escape(collapsed_token[-1])
        if re.search(pattern, collapsed_haystack):
            return True
    return False


def evidence_fact_hit(
    *,
    retrieved_texts: Sequence[str],
    must_contain: Sequence[str],
) -> bool:
    """True when some retrieved text contains every required evidence token."""
    required = [token for token in must_contain if token]
    if not required or not retrieved_texts:
        return False
    for text in retrieved_texts:
        haystack = text or ""
        if all(evidence_token_in_text(token, haystack) for token in required):
            return True
    return False


def evidence_recall_at_k(
    *,
    retrieved_texts: Sequence[str],
    evidence_must_contain: Sequence[Sequence[str]],
    k: int,
) -> float:
    """Fraction of evidence facts recoverable from the top-``k`` retrieved texts."""
    facts = [tuple(tokens) for tokens in evidence_must_contain if tokens]
    if not facts:
        return 0.0
    top_texts = list(retrieved_texts[:k])
    hits = sum(
        1
        for tokens in facts
        if evidence_fact_hit(retrieved_texts=top_texts, must_contain=tokens)
    )
    return hits / len(facts)


def evidence_precision_at_k(
    *,
    retrieved_texts: Sequence[str],
    evidence_must_contain: Sequence[Sequence[str]],
    k: int,
) -> float:
    """Share of top-``k`` texts that satisfy at least one evidence fact."""
    facts = [tuple(tokens) for tokens in evidence_must_contain if tokens]
    top_texts = list(retrieved_texts[:k])
    if not top_texts or not facts:
        return 0.0
    supporting = 0
    for text in top_texts:
        if any(
            evidence_fact_hit(retrieved_texts=[text], must_contain=tokens)
            for tokens in facts
        ):
            supporting += 1
    return supporting / len(top_texts)


def score_retrieval_case(
    *,
    case_id: str,
    ranked_ids: Sequence[str],
    relevant_ids: Iterable[str],
    relevance_grades: Mapping[str, float] | None = None,
    hard_negative_ids: Iterable[str] = (),
    forbidden_ids: Iterable[str] = (),
    retrieved_texts: Sequence[str] = (),
    evidence_must_contain: Sequence[Sequence[str]] = (),
) -> RetrievalCaseScore:
    relevant = tuple(relevant_ids)
    grades = dict(relevance_grades or {})
    if not grades:
        grades = {item: 1.0 for item in relevant if item}
    hard_neg = tuple(hard_negative_ids)
    hard_acc = (
        hard_negative_accuracy(
            ranked_ids,
            relevant_ids=relevant,
            hard_negative_ids=hard_neg,
            k=1,
        )
        if hard_neg
        else None
    )
    rec_4 = recall_at_k(ranked_ids, relevant, k=4)
    prec_4 = precision_at_k(ranked_ids, relevant, k=4)
    has_evidence = bool(evidence_must_contain)
    # Document and Evidence metrics stay separate: never fall back Document Hit
    # into Evidence Recall when labels are missing.
    ev_rec_4 = (
        evidence_recall_at_k(
            retrieved_texts=retrieved_texts,
            evidence_must_contain=evidence_must_contain,
            k=4,
        )
        if has_evidence
        else None
    )
    ev_prec_4 = (
        evidence_precision_at_k(
            retrieved_texts=retrieved_texts,
            evidence_must_contain=evidence_must_contain,
            k=4,
        )
        if has_evidence
        else None
    )
    return RetrievalCaseScore(
        case_id=case_id,
        recall_at_5=recall_at_k(ranked_ids, relevant, k=5),
        recall_at_10=recall_at_k(ranked_ids, relevant, k=10),
        recall_at_20=recall_at_k(ranked_ids, relevant, k=20),
        recall_at_4=rec_4,
        precision_at_4=prec_4,
        evidence_recall_at_4=ev_rec_4,
        evidence_precision_at_4=ev_prec_4,
        mrr_at_10=mrr_at_k(ranked_ids, relevant, k=10),
        ndcg_at_10=ndcg_at_k(ranked_ids, grades, k=10),
        hit_at_1=hit_at_k(ranked_ids, relevant, k=1),
        hit_at_3=hit_at_k(ranked_ids, relevant, k=3),
        hard_negative_accuracy=hard_acc,
        acl_leakage_count=acl_leakage_count(ranked_ids, forbidden_ids),
        has_evidence_labels=has_evidence,
    )


def aggregate_case_scores(scores: Sequence[RetrievalCaseScore]) -> dict[str, float]:
    """Mean of per-case ranking metrics (ignores None hard-negative rows).

    Evidence metrics average only over cases that carry evidence labels so
    Document Recall / Hit are never silently mixed into Evidence Recall.
    """
    if not scores:
        return {
            "caseCount": 0.0,
            "evidenceLabeledCaseCount": 0.0,
            "recallAt4": 0.0,
            "precisionAt4": 0.0,
            "evidenceRecallAt4": 0.0,
            "evidencePrecisionAt4": 0.0,
            "recallAt5": 0.0,
            "recallAt10": 0.0,
            "recallAt20": 0.0,
            "mrrAt10": 0.0,
            "ndcgAt10": 0.0,
            "hitAt1": 0.0,
            "hitAt3": 0.0,
            "hardNegativeAccuracy": 0.0,
            "aclLeakageCount": 0.0,
        }

    def _mean(values: Sequence[float]) -> float:
        return sum(values) / len(values) if values else 0.0

    hard_values = [
        score.hard_negative_accuracy
        for score in scores
        if score.hard_negative_accuracy is not None
    ]
    evidence_recall_values = [
        score.evidence_recall_at_4
        for score in scores
        if score.evidence_recall_at_4 is not None
    ]
    evidence_precision_values = [
        score.evidence_precision_at_4
        for score in scores
        if score.evidence_precision_at_4 is not None
    ]
    return {
        "caseCount": float(len(scores)),
        "evidenceLabeledCaseCount": float(len(evidence_recall_values)),
        "recallAt4": _mean([score.recall_at_4 for score in scores]),
        "precisionAt4": _mean([score.precision_at_4 for score in scores]),
        "evidenceRecallAt4": _mean(evidence_recall_values),
        "evidencePrecisionAt4": _mean(evidence_precision_values),
        "recallAt5": _mean([score.recall_at_5 for score in scores]),
        "recallAt10": _mean([score.recall_at_10 for score in scores]),
        "recallAt20": _mean([score.recall_at_20 for score in scores]),
        "mrrAt10": _mean([score.mrr_at_10 for score in scores]),
        "ndcgAt10": _mean([score.ndcg_at_10 for score in scores]),
        "hitAt1": _mean([score.hit_at_1 for score in scores]),
        "hitAt3": _mean([score.hit_at_3 for score in scores]),
        "hardNegativeAccuracy": _mean(hard_values) if hard_values else 0.0,
        "aclLeakageCount": float(sum(score.acl_leakage_count for score in scores)),
    }


__all__ = [
    "NoAnswerOutcome",
    "RetrievalCaseScore",
    "acl_leakage_count",
    "aggregate_case_scores",
    "evidence_fact_hit",
    "evidence_precision_at_k",
    "evidence_recall_at_k",
    "evidence_token_in_text",
    "hard_negative_accuracy",
    "hit_at_k",
    "mrr_at_k",
    "ndcg_at_k",
    "no_answer_confusion",
    "precision_at_k",
    "recall_at_k",
    "score_retrieval_case",
]
