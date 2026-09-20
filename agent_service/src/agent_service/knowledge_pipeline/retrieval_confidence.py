"""Shared retrieval Confidence Contract for eval and production.

Maps retrieval features to HIGH / UNCERTAIN / LOW so offline No-answer F1 and
production relevance routing share one implementation.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum

from agent_service.retrieval import SearchResult, tokenize

from .relevance import (
    HIGH_CONFIDENCE_RETRIEVAL_MIN_SCORE,
    conflicting_top_candidates,
    high_confidence_retrieval_hit,
    query_lexically_matches_results,
)

_GENERIC_LEXICAL_TOKENS = frozenset(
    {
        "vpn",
        "it",
        "ai",
        "bot",
        "teams",
        "agent",
        "demo",
        "test",
        "help",
        "cancel",
        "close",
        "請",
        "協",
        "助",
        "幫",
        "我",
        "要",
        "想",
        "問",
        "查",
        "詢",
        "怎",
        "麼",
        "如",
        "何",
        "為",
        "什",
        "可",
        "以",
        "不",
        "能",
        "無",
        "法",
        "有",
        "沒",
        "是",
        "的",
        "了",
        "嗎",
        "呢",
        "在",
        "和",
        "或",
        "及",
        "與",
        "開",
        "建",
        "立",
        "工",
        "單",
        "派",
        "取",
        "消",
        "公",
        "司",
        "內",
        "部",
        "企",
        "業",
        "知",
        "識",
        "庫",
        "測",
        "試",
        "問題",
        "資訊",
        "系統",
        "無法",
        "怎麼",
        "如何",
        "請問",
        "協助",
        "建立",
        "開工",
        "工單",
        "派工",
        "取消",
    }
)
_LOW_CONFIDENCE_MAX_SCORE = 0.60
_WEAK_OVERLAP_RATIO = 0.20
_HIGH_SCORE_RESCUE_FLOOR = 0.70
# Title tokens that often match the wrong org/process docs without proving answerability.
_GENERIC_TITLE_TOKENS = _GENERIC_LEXICAL_TOKENS | {
    "公司",
    "總公",
    "申請",
    "同仁",
    "系統",
    "文件",
    "下載",
    "表單",
    "方式",
    "設定",
    "操作",
    "說明",
    "列表",
    "團隊",
    "連線",
    "權限",
    "資料",
    "夾",
    "網",
    "入口",
    "地下",
    "停車",
    "訪客",
    "臨停",
}


class ConfidenceLevel(str, Enum):
    HIGH = "HIGH"
    UNCERTAIN = "UNCERTAIN"
    LOW = "LOW"


@dataclass(frozen=True)
class ConfidenceFeatures:
    """Signals used by ``evaluate_confidence`` (extensible for future calibration)."""

    query: str
    top1_score: float | None
    top2_score: float | None = None
    top_texts: tuple[str, ...] = ()
    filter_displaced_top1: bool = False
    has_conflicting_candidates: bool = False
    has_high_confidence_lexical_hit: bool = False
    has_lexical_overlap: bool = False
    sparse_top1: float | None = None
    dense_top1: float | None = None
    fusion_rank_top1: int | None = None
    sparse_dense_agreement: bool | None = None
    has_exact_identifier_hit: bool | None = None


def build_confidence_features(
    *,
    query: str,
    results: Sequence[SearchResult],
    filter_displaced_top1: bool = False,
) -> ConfidenceFeatures:
    """Extract confidence features from a ranked retrieval pool."""
    if not results:
        return ConfidenceFeatures(query=query, top1_score=None)
    top = results[0]
    top2 = results[1] if len(results) > 1 else None
    top_texts = tuple(
        f"{item.chunk.title}\n{item.chunk.section or ''}\n{item.chunk.content}"
        for item in results[:3]
    )
    sparse = top.sparse_score
    dense = top.dense_score
    agreement: bool | None = None
    if dense is not None and sparse is not None:
        agreement = abs(float(sparse) - float(dense)) <= 0.25
    return ConfidenceFeatures(
        query=query,
        top1_score=float(top.score),
        top2_score=float(top2.score) if top2 is not None else None,
        top_texts=top_texts,
        filter_displaced_top1=filter_displaced_top1,
        has_conflicting_candidates=conflicting_top_candidates(list(results)),
        has_high_confidence_lexical_hit=high_confidence_retrieval_hit(query, top),
        has_lexical_overlap=query_lexically_matches_results(query, list(results)),
        sparse_top1=float(sparse) if sparse is not None else None,
        dense_top1=float(dense) if dense is not None else None,
        fusion_rank_top1=top.fusion_rank,
        sparse_dense_agreement=agreement,
    )


def lexical_overlap_ratio(*, query: str, texts: Sequence[str]) -> tuple[int, float]:
    """Return (distinctive token count, overlap ratio vs top texts)."""
    query_tokens = [
        token
        for token in tokenize(query)
        if token not in _GENERIC_LEXICAL_TOKENS and len(token) >= 2
    ]
    if not query_tokens:
        query_tokens = [
            token for token in tokenize(query) if token not in _GENERIC_LEXICAL_TOKENS
        ]
    if not query_tokens:
        return (0, 0.0)
    top_text = " ".join(texts[:3]).casefold()
    overlap = [token for token in query_tokens if token.casefold() in top_text]
    return (len(query_tokens), len(overlap) / len(query_tokens))


def distinctive_title_overlap_ratio(
    *,
    query: str,
    titles: Sequence[str],
) -> float:
    """Overlap between distinctive query tokens and top titles only."""
    query_tokens = [
        token
        for token in tokenize(query)
        if token.casefold() not in {item.casefold() for item in _GENERIC_TITLE_TOKENS}
        and len(token) >= 2
    ]
    if not query_tokens or not titles:
        return 0.0
    title_blob = " ".join(titles[:3]).casefold()
    hits = [token for token in query_tokens if token.casefold() in title_blob]
    return len(hits) / len(query_tokens)


def weak_lexical_no_answer(
    *,
    query: str,
    texts: Sequence[str],
    titles: Sequence[str] | None = None,
    top1_score: float | None = None,
) -> bool:
    """CJK lexical heuristic used by offline No-answer F1 (v2).

    Predict no-answer when top evidence has zero distinctive overlap, or when
    the query has enough tokens but overlap stays very weak.

    High-score hits with distinctive *title* overlap are rescued so paraphrases
    that land on the right document are not false-rejected. Generic org tokens
    (公司 / 申請 / …) do not count, which keeps facilities-style hard negatives
    from being flipped.
    """
    token_count, overlap_ratio = lexical_overlap_ratio(query=query, texts=texts)
    if token_count == 0:
        return True
    if (
        titles is not None
        and top1_score is not None
        and top1_score >= _HIGH_SCORE_RESCUE_FLOOR
        and distinctive_title_overlap_ratio(query=query, titles=titles) > 0.0
    ):
        return False
    if overlap_ratio <= 0.0:
        return True
    return token_count >= 3 and overlap_ratio < _WEAK_OVERLAP_RATIO


def evaluate_confidence(
    features: ConfidenceFeatures,
    *,
    min_score: float,
) -> ConfidenceLevel:
    """Map features to HIGH / UNCERTAIN / LOW.

    Weak lexical overlap alone is not enough to force LOW when the top hit
    still has a mid/high score — that middle band stays UNCERTAIN so relevance
    can grade without paying rewrite cost. No-answer prediction continues to
    use ``weak_lexical_no_answer`` / ``calibrated_predict_no_answer`` separately.
    """
    if features.top1_score is None or features.top1_score < min_score:
        return ConfidenceLevel.LOW

    if features.filter_displaced_top1 or features.has_conflicting_candidates:
        return ConfidenceLevel.UNCERTAIN

    weak_lexical = weak_lexical_no_answer(query=features.query, texts=features.top_texts)
    if weak_lexical and features.top1_score < _LOW_CONFIDENCE_MAX_SCORE:
        return ConfidenceLevel.LOW

    if features.top1_score >= HIGH_CONFIDENCE_RETRIEVAL_MIN_SCORE and (
        features.has_high_confidence_lexical_hit or features.has_lexical_overlap
    ):
        return ConfidenceLevel.HIGH

    if features.top1_score < _LOW_CONFIDENCE_MAX_SCORE and not features.has_lexical_overlap:
        return ConfidenceLevel.LOW

    # Mid-band (including weak lexical with decent score) → relevance LLM.
    return ConfidenceLevel.UNCERTAIN


def confidence_decision_label(level: ConfidenceLevel) -> str:
    """Map ConfidenceLevel onto legacy production decision labels."""
    if level is ConfidenceLevel.HIGH:
        return "HIGH_CONFIDENCE_PASS"
    if level is ConfidenceLevel.LOW:
        return "LOW_CONFIDENCE_FAIL"
    return "LLM_RELEVANCE"


def evaluate_retrieval_confidence(
    *,
    query: str,
    results: list[SearchResult],
    min_score: float,
    filter_displaced_top1: bool,
) -> tuple[str, bool]:
    """Production-compatible confidence gate used by relevance routing.

    Returns ``(decision_label, is_deterministic_pass)``.
    ``BELOW_MIN_SCORE`` is preserved when the pool is empty or under ``min_score``.
    """
    if not results or results[0].score < min_score:
        return ("BELOW_MIN_SCORE", False)
    features = build_confidence_features(
        query=query,
        results=results,
        filter_displaced_top1=filter_displaced_top1,
    )
    level = evaluate_confidence(features, min_score=min_score)
    if level is ConfidenceLevel.HIGH:
        return ("HIGH_CONFIDENCE_PASS", True)
    if level is ConfidenceLevel.LOW:
        return ("LOW_CONFIDENCE_FAIL", False)
    return ("LLM_RELEVANCE", False)


def calibrated_predict_no_answer(
    *,
    ranked_ids: Sequence[str],
    scores: Sequence[float],
    texts: Sequence[str],
    query: str,
    min_score: float = 0.45,
    titles: Sequence[str] | None = None,
) -> bool:
    """Shared No-answer predictor for eval and production confidence routing.

    ``min_score`` participates when a top score is available: scores below the
    floor are treated as no-answer before the lexical heuristic runs.
    Optional ``titles`` enables distinctive-title rescue for high-score hits.
    """
    if not ranked_ids or not scores:
        return True
    if float(scores[0]) < min_score:
        return True
    return weak_lexical_no_answer(
        query=query,
        texts=texts,
        titles=titles,
        top1_score=float(scores[0]),
    )


__all__ = [
    "ConfidenceFeatures",
    "ConfidenceLevel",
    "build_confidence_features",
    "calibrated_predict_no_answer",
    "confidence_decision_label",
    "distinctive_title_overlap_ratio",
    "evaluate_confidence",
    "evaluate_retrieval_confidence",
    "lexical_overlap_ratio",
    "weak_lexical_no_answer",
]
