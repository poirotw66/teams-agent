"""Neural reranker protocol, guards, and fail-open adapters (RAG v2 M3).

Default production path stays ``NoopReranker`` until eval proves a win.
"""

from __future__ import annotations

import asyncio
import logging
import re
import threading
from collections.abc import Awaitable, Callable, Sequence
from typing import Any, Protocol

from knowledge_core.contextual_representation import effective_retrieval_text

from .retrieval import SearchResult

logger = logging.getLogger(__name__)

# Exact technical tokens only — not general natural-language keywords (§32).
_ERROR_CODE_RE = re.compile(r"(?<![\w-])-?\d{1,5}(?![\w-])", re.ASCII)
_TECH_TOKEN_RE = re.compile(
    r"\b(?:EMS|OTP|MFA|VPN|AD|SSLVPN|FortiToken|FortiClient|Intune|CRM)\b",
    re.IGNORECASE,
)

_TIER_RANK = {"trivial": 0, "standard": 1, "hard": 2}

PairScorer = Callable[[str, Sequence[str]], Awaitable[Sequence[float]]]


class Reranker(Protocol):
    async def rerank(
        self,
        *,
        query: str,
        candidates: list[SearchResult],
        limit: int,
    ) -> list[SearchResult]: ...


def extract_error_codes(text: str) -> set[str]:
    """Numeric error codes only (narrower than ``extract_exact_identifiers``)."""
    return {match.group(0) for match in _ERROR_CODE_RE.finditer(text or "") if match.group(0)}


def extract_exact_identifiers(text: str) -> set[str]:
    """Return error codes and explicit product/tech tokens from ``text``."""
    codes = extract_error_codes(text)
    tokens = {match.group(0).upper() for match in _TECH_TOKEN_RE.finditer(text or "")}
    return {item for item in codes | tokens if item}


def apply_error_code_guard(
    query: str,
    ranked: list[SearchResult],
) -> list[SearchResult]:
    """Promote a buried error-code match without VPN/AD token false promotions."""
    query_codes = extract_error_codes(query)
    if not query_codes or len(ranked) < 2:
        return ranked

    def _covers(result: SearchResult) -> bool:
        haystack = f"{result.chunk.title}\n{effective_retrieval_text(result.chunk)}"
        return bool(query_codes & extract_error_codes(haystack))

    top = ranked[0]
    if _covers(top):
        return ranked
    for index, candidate in enumerate(ranked[1:], start=1):
        if not _covers(candidate):
            continue
        promoted = list(ranked)
        promoted.insert(0, promoted.pop(index))
        return [
            SearchResult(
                chunk=item.chunk,
                score=item.score,
                sparse_score=item.sparse_score,
                dense_score=item.dense_score,
                sparse_rank=item.sparse_rank,
                dense_rank=item.dense_rank,
                fusion_score=item.fusion_score,
                fusion_rank=item.fusion_rank,
                rerank_score=item.rerank_score,
                rerank_rank=rank,
                final_rank=rank,
            )
            for rank, item in enumerate(promoted, start=1)
        ]
    return ranked


def apply_exact_identifier_guard(
    query: str,
    ranked: list[SearchResult],
) -> list[SearchResult]:
    """Keep exact-id matches from being buried by a non-matching top hit (§32)."""
    query_ids = extract_exact_identifiers(query)
    if not query_ids or len(ranked) < 2:
        return ranked

    def _covers(result: SearchResult) -> bool:
        haystack = f"{result.chunk.title}\n{effective_retrieval_text(result.chunk)}"
        present = extract_exact_identifiers(haystack)
        return bool(query_ids & present)

    top = ranked[0]
    if _covers(top):
        return ranked
    for index, candidate in enumerate(ranked[1:], start=1):
        if not _covers(candidate):
            continue
        promoted = list(ranked)
        promoted.insert(0, promoted.pop(index))
        return [
            SearchResult(
                chunk=item.chunk,
                score=item.score,
                sparse_score=item.sparse_score,
                dense_score=item.dense_score,
                sparse_rank=item.sparse_rank,
                dense_rank=item.dense_rank,
                fusion_score=item.fusion_score,
                fusion_rank=item.fusion_rank,
                rerank_score=item.rerank_score,
                rerank_rank=rank,
                final_rank=rank,
            )
            for rank, item in enumerate(promoted, start=1)
        ]
    return ranked


def tier_meets_minimum(tier: str, minimum: str) -> bool:
    """Whether ``tier`` is at least as hard as ``minimum`` (spec §34)."""
    return _TIER_RANK.get(tier.lower(), 1) >= _TIER_RANK.get(minimum.lower(), 1)


class NoopReranker:
    """Identity reranker — preserves RRF / weighted order."""

    async def rerank(
        self,
        *,
        query: str,
        candidates: list[SearchResult],
        limit: int,
    ) -> list[SearchResult]:
        del query
        trimmed = candidates[: max(limit, 0)]
        return [
            SearchResult(
                chunk=item.chunk,
                score=item.score,
                sparse_score=item.sparse_score,
                dense_score=item.dense_score,
                sparse_rank=item.sparse_rank,
                dense_rank=item.dense_rank,
                fusion_score=item.fusion_score,
                fusion_rank=item.fusion_rank,
                rerank_score=None,
                rerank_rank=rank,
                final_rank=rank,
            )
            for rank, item in enumerate(trimmed, start=1)
        ]


class ModelReranker:
    """Scores ``retrieval_text`` pairs via an injected async scorer, then guards."""

    def __init__(
        self,
        score_pairs: PairScorer,
        *,
        protect_exact_identifiers: bool = True,
    ) -> None:
        self._score_pairs = score_pairs
        self._protect_exact_identifiers = protect_exact_identifiers

    async def rerank(
        self,
        *,
        query: str,
        candidates: list[SearchResult],
        limit: int,
    ) -> list[SearchResult]:
        if not candidates:
            return []
        texts = candidate_retrieval_texts(candidates)
        scores = list(await self._score_pairs(query, texts))
        if len(scores) != len(candidates):
            raise ValueError(
                f"Reranker returned {len(scores)} scores for {len(candidates)} candidates"
            )
        ordered = sorted(
            zip(candidates, scores, strict=True),
            key=lambda pair: (
                -float(pair[1]),
                -(pair[0].fusion_score if pair[0].fusion_score is not None else pair[0].score),
                pair[0].chunk.chunk_id,
            ),
        )
        ranked = [
            SearchResult(
                chunk=item.chunk,
                score=item.score,
                sparse_score=item.sparse_score,
                dense_score=item.dense_score,
                sparse_rank=item.sparse_rank,
                dense_rank=item.dense_rank,
                fusion_score=item.fusion_score,
                fusion_rank=item.fusion_rank,
                rerank_score=round(float(score), 6),
                rerank_rank=rank,
                final_rank=rank,
            )
            for rank, (item, score) in enumerate(ordered[: max(limit, 0)], start=1)
        ]
        if self._protect_exact_identifiers:
            return apply_exact_identifier_guard(query, ranked)
        return ranked


class FailOpenReranker:
    """Wrap a reranker; on timeout/exception fall back to input order."""

    def __init__(
        self,
        inner: Reranker,
        *,
        timeout_seconds: float = 0.7,
        fallback: Reranker | None = None,
    ) -> None:
        self._inner = inner
        self._timeout_seconds = timeout_seconds
        self._fallback = fallback or NoopReranker()

    async def rerank(
        self,
        *,
        query: str,
        candidates: list[SearchResult],
        limit: int,
    ) -> list[SearchResult]:
        from .rag_observability import increment_counter

        try:
            return await asyncio.wait_for(
                self._inner.rerank(query=query, candidates=candidates, limit=limit),
                timeout=self._timeout_seconds,
            )
        except TimeoutError:
            increment_counter("rag_reranker_timeout_total")
            logger.warning(
                "reranker_fail_open reason=TimeoutError type=%s",
                type(self._inner).__name__,
            )
            return await self._fallback.rerank(query=query, candidates=candidates, limit=limit)
        except Exception as exc:  # noqa: BLE001 — fail-open boundary
            increment_counter("rag_reranker_failure_total")
            logger.warning(
                "reranker_fail_open reason=%s type=%s",
                type(exc).__name__,
                type(self._inner).__name__,
            )
            return await self._fallback.rerank(query=query, candidates=candidates, limit=limit)


def candidate_retrieval_texts(candidates: list[SearchResult]) -> list[str]:
    """Texts a model reranker should score (never answer prompts)."""
    return [effective_retrieval_text(item.chunk) for item in candidates]


def lexical_overlap_scores(query: str, texts: Sequence[str]) -> list[float]:
    """Deterministic PairScorer used when no neural model is configured.

    Scores Jaccard overlap between query tokens and each candidate
    ``retrieval_text``. Safe for CI / shadow eval; not a production neural model.
    """
    import re

    token_re = re.compile(r"[a-zA-Z0-9_./:\\-]+|[\u3400-\u9fff]+")

    def _tokens(text: str) -> set[str]:
        return {match.group(0).casefold() for match in token_re.finditer(text or "")}

    query_tokens = _tokens(query)
    if not query_tokens:
        return [0.0 for _ in texts]
    scores: list[float] = []
    for text in texts:
        doc_tokens = _tokens(text)
        if not doc_tokens:
            scores.append(0.0)
            continue
        overlap = len(query_tokens & doc_tokens)
        scores.append(overlap / len(query_tokens | doc_tokens))
    return scores


async def lexical_overlap_pair_scorer(query: str, texts: Sequence[str]) -> Sequence[float]:
    return lexical_overlap_scores(query, texts)


_CROSS_ENCODER_INSTANCES: dict[str, Any] = {}
_CROSS_ENCODER_LOCK = threading.Lock()


def get_or_load_cross_encoder(model_name: str) -> Any:
    """Thread-safe singleton loader for CrossEncoder models."""
    resolved = model_name.strip()
    if resolved.lower().startswith("cross-encoder:"):
        resolved = resolved.split(":", 1)[1].strip()
    with _CROSS_ENCODER_LOCK:
        if resolved in _CROSS_ENCODER_INSTANCES:
            return _CROSS_ENCODER_INSTANCES[resolved]
        try:
            from sentence_transformers import CrossEncoder  # type: ignore[import-not-found]
        except ImportError as error:
            raise RuntimeError(
                "sentence_transformers is required for cross-encoder reranking"
            ) from error
        encoder = CrossEncoder(resolved)
        _CROSS_ENCODER_INSTANCES[resolved] = encoder
        return encoder


def build_cross_encoder_pair_scorer(model_name: str) -> PairScorer:
    """Lazy CrossEncoder PairScorer reusing cached model instances."""

    resolved = model_name.strip()
    if resolved.lower().startswith("cross-encoder:"):
        resolved = resolved.split(":", 1)[1].strip()

    async def score_pairs(query: str, texts: Sequence[str]) -> Sequence[float]:
        encoder = await asyncio.to_thread(get_or_load_cross_encoder, resolved)
        pairs = [(query, text) for text in texts]
        scores = await asyncio.to_thread(encoder.predict, pairs)
        return [float(score) for score in scores]

    return score_pairs


def _build_listwise_reranker(model_name: str | None, *, timeout_ms: int) -> Reranker:
    """Gemini listwise + title-protect (experiment-only; lexical offline fallback)."""
    import os

    from .reranker_listwise import (
        build_gemini_listwise_pair_scorer,
        wrap_listwise_title_protect,
    )

    resolved = (model_name or "listwise").strip()
    if not (os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")):
        logger.warning(
            "rag_reranker_model=%s requested without Gemini API key; "
            "using lexical title-protect FailOpenReranker",
            model_name,
        )
        inner = wrap_listwise_title_protect(lexical_overlap_pair_scorer)
    else:
        inner = wrap_listwise_title_protect(build_gemini_listwise_pair_scorer(resolved))
    return FailOpenReranker(inner, timeout_seconds=max(timeout_ms, 1) / 1000.0)


def _pair_scorer_for_model_name(model_name: str | None) -> PairScorer | None:
    """Resolve a model id to a PairScorer, or None when unknown / listwise."""
    resolved = (model_name or "lexical").strip()
    lowered = resolved.lower()
    if lowered in {"", "lexical", "noop-lexical"}:
        return lexical_overlap_pair_scorer
    if lowered.startswith(("cross-encoder:", "cross_encoder:")):
        return build_cross_encoder_pair_scorer(resolved)
    if lowered in {
        "vertex-ranking",
        "vertex_ranking",
        "ranking-api",
        "ranking_api",
    } or lowered.startswith(("vertex-ranking:", "vertex_ranking:", "ranking-api:", "ranking_api:")):
        from .reranker_dedicated import build_vertex_ranking_pair_scorer

        return build_vertex_ranking_pair_scorer(resolved)
    if lowered in {"qwen3-reranker", "qwen3_reranker", "qwen3"} or lowered.startswith(
        ("qwen3-reranker:", "qwen3_reranker:", "qwen3:")
    ):
        from .reranker_dedicated import build_qwen3_reranker_pair_scorer

        return build_qwen3_reranker_pair_scorer(resolved)
    return None


def build_default_reranker(
    *,
    enabled: bool,
    timeout_ms: int,
    score_pairs: PairScorer | None = None,
    model_name: str | None = None,
) -> Reranker:
    """Factory used by HybridKnowledgeService — disabled ⇒ Noop.

    When enabled without an injected scorer:
    - ``lexical`` (default) — deterministic Jaccard PairScorer
    - ``cross-encoder:<hf-id>`` — optional sentence_transformers CrossEncoder
    - ``vertex-ranking[:model]`` — Vertex AI Ranking API (v2.1 preferred A/B)
    - ``qwen3-reranker[:hf-id]`` — Qwen3 Reranker via CrossEncoder (v2.1 fallback)
    - ``listwise`` / ``listwise:gemini-…`` — Gemini listwise + title-protect (experiment-only)
    """
    if not enabled:
        return NoopReranker()
    if score_pairs is not None:
        return FailOpenReranker(
            ModelReranker(score_pairs),
            timeout_seconds=max(timeout_ms, 1) / 1000.0,
        )
    lowered = (model_name or "lexical").strip().lower()
    if lowered in {"listwise", "gemini-listwise"} or lowered.startswith(
        ("listwise:", "gemini-listwise:")
    ):
        return _build_listwise_reranker(model_name, timeout_ms=timeout_ms)
    scorer = _pair_scorer_for_model_name(model_name)
    if scorer is None:
        logger.warning(
            "rag_reranker_model=%s has no built-in adapter; using NoopReranker",
            model_name,
        )
        return NoopReranker()
    return FailOpenReranker(
        ModelReranker(scorer),
        timeout_seconds=max(timeout_ms, 1) / 1000.0,
    )


# Re-export listwise helpers for stable imports from ``reranker``.
from .reranker_listwise import (  # noqa: E402
    TitleProtectedListwiseReranker,
    build_gemini_listwise_pair_scorer,
    parse_listwise_order_payload,
    scores_from_listwise_order,
)

__all__ = [
    "FailOpenReranker",
    "ModelReranker",
    "NoopReranker",
    "PairScorer",
    "Reranker",
    "TitleProtectedListwiseReranker",
    "apply_error_code_guard",
    "apply_exact_identifier_guard",
    "build_cross_encoder_pair_scorer",
    "build_default_reranker",
    "build_gemini_listwise_pair_scorer",
    "candidate_retrieval_texts",
    "extract_error_codes",
    "extract_exact_identifiers",
    "lexical_overlap_pair_scorer",
    "lexical_overlap_scores",
    "parse_listwise_order_payload",
    "scores_from_listwise_order",
    "tier_meets_minimum",
]
