"""Neural reranker protocol, guards, and fail-open adapters (RAG v2 M3).

Default production path stays ``NoopReranker`` until eval proves a win.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Awaitable, Callable, Sequence
from typing import Protocol

from knowledge_core.contextual_representation import effective_retrieval_text

from .retrieval import SearchResult
from .retrieval_blend import blend_soft_and_listwise_top1

logger = logging.getLogger(__name__)

# Exact technical tokens only — not general natural-language keywords (§32).
_ERROR_CODE_RE = re.compile(r"(?<![\w-])-?\d{2,5}(?![\w-])")
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
            return await self._fallback.rerank(
                query=query, candidates=candidates, limit=limit
            )
        except Exception as exc:  # noqa: BLE001 — fail-open boundary
            increment_counter("rag_reranker_failure_total")
            logger.warning(
                "reranker_fail_open reason=%s type=%s",
                type(exc).__name__,
                type(self._inner).__name__,
            )
            return await self._fallback.rerank(
                query=query, candidates=candidates, limit=limit
            )


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


def build_cross_encoder_pair_scorer(model_name: str) -> PairScorer:
    """Lazy CrossEncoder PairScorer (optional ``sentence_transformers`` dependency)."""

    resolved = model_name.strip()
    if resolved.lower().startswith("cross-encoder:"):
        resolved = resolved.split(":", 1)[1].strip()

    async def score_pairs(query: str, texts: Sequence[str]) -> Sequence[float]:
        try:
            from sentence_transformers import CrossEncoder  # type: ignore[import-not-found]
        except ImportError as error:
            raise RuntimeError(
                "sentence_transformers is required for cross-encoder reranking"
            ) from error

        encoder = CrossEncoder(resolved)
        pairs = [(query, text) for text in texts]
        scores = await asyncio.to_thread(encoder.predict, pairs)
        return [float(score) for score in scores]

    return score_pairs


def scores_from_listwise_order(count: int, order: Sequence[int]) -> list[float]:
    """Map a 1-based permutation to descending scores (earlier ⇒ higher)."""
    scores = [0.0] * count
    for rank, index in enumerate(order):
        if 1 <= index <= count:
            scores[index - 1] = float(count - rank)
    for index, score in enumerate(scores):
        if score == 0.0:
            scores[index] = 0.1
    return scores


def parse_listwise_order_payload(text: str, count: int) -> list[int] | None:
    """Parse a JSON int array (or id-object array) into a 1-based permutation."""
    if count <= 0:
        return None
    payload = text or ""
    for match in re.finditer(r"\[[\d,\s]+\]", payload):
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError:
            continue
        if not isinstance(parsed, list) or not parsed:
            continue
        if not all(isinstance(item, int) for item in parsed):
            continue
        order = [item for item in parsed if 1 <= item <= count]
        missing = [index for index in range(1, count + 1) if index not in order]
        if order:
            return order + missing
    object_match = re.search(r"\[[\s\S]*?\]", payload)
    if not object_match:
        return None
    try:
        parsed = json.loads(object_match.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, list) or not parsed or not isinstance(parsed[0], dict):
        return None
    order: list[int] = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        for key in ("id", "index", "rank", "n"):
            value = item.get(key)
            if isinstance(value, int) and 1 <= value <= count:
                order.append(value)
                break
    missing = [index for index in range(1, count + 1) if index not in order]
    return order + missing if order else None


def build_gemini_listwise_pair_scorer(model_id: str = "gemini-2.5-flash") -> PairScorer:
    """LLM listwise PairScorer used for §45 offline evidence (optional runtime)."""

    resolved = model_id.strip() or "gemini-2.5-flash"
    if ":" in resolved and not resolved.startswith("google_genai:"):
        # Allow ``listwise:gemini-2.5-flash`` style names from settings.
        resolved = resolved.split(":", 1)[1].strip() or "gemini-2.5-flash"
    langchain_id = (
        resolved if resolved.startswith("google_genai:") else f"google_genai:{resolved}"
    )

    async def score_pairs(query: str, texts: Sequence[str]) -> Sequence[float]:
        from langchain.chat_models import init_chat_model

        if not texts:
            return []
        lines: list[str] = []
        for index, text in enumerate(texts, start=1):
            snippet = (text or "").replace("\n", " ")[:180]
            lines.append(f"{index}. {snippet}")
        prompt = (
            "你是企業 IT 知識庫 listwise reranker。\n"
            "規則：FortiToken/Token OTP→VPN常見Q&A，勿選外網/國金 CRM；"
            "UX-AUDIT測試文件→FortiClient錯訊或VPN常見Q&A；登入不了→FortiClient/VPN優先於AD。\n"
            f"只輸出一個 JSON 整數陣列（長度 {len(texts)}），例如 [3,1,2,...]，"
            "禁止物件、禁止 markdown。\n\n"
            f"查詢：{query}\n\n候選：\n" + "\n".join(lines)
        )
        model = init_chat_model(langchain_id, temperature=0, timeout=90)
        response = await asyncio.to_thread(model.invoke, prompt)
        content = getattr(response, "content", str(response))
        if isinstance(content, list):
            content = "".join(getattr(part, "text", str(part)) for part in content)
        order = parse_listwise_order_payload(str(content), len(texts))
        if not order:
            raise RuntimeError("gemini listwise returned no parseable order")
        return scores_from_listwise_order(len(texts), order)

    return score_pairs


class TitleProtectedListwiseReranker:
    """Run an inner listwise reranker, then blend top-1 with Soft order (§45)."""

    def __init__(self, inner: Reranker) -> None:
        self._inner = inner

    async def rerank(
        self,
        *,
        query: str,
        candidates: list[SearchResult],
        limit: int,
    ) -> list[SearchResult]:
        if not candidates:
            return []
        listwise = await self._inner.rerank(
            query=query,
            candidates=list(candidates),
            limit=max(limit, len(candidates)),
        )
        listwise_top = listwise[0] if listwise else None
        blended = blend_soft_and_listwise_top1(
            query=query,
            soft_ranked=candidates,
            listwise_top=listwise_top,
        )
        return blended[: max(limit, 0)]


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
    - ``listwise`` / ``listwise:gemini-…`` — Gemini listwise + title-protect blend
    """
    if not enabled:
        return NoopReranker()
    scorer = score_pairs
    use_title_protect = False
    if scorer is None:
        resolved = (model_name or "lexical").strip()
        lowered = resolved.lower()
        if lowered in {"", "lexical", "noop-lexical"}:
            scorer = lexical_overlap_pair_scorer
        elif lowered.startswith(("cross-encoder:", "cross_encoder:")):
            scorer = build_cross_encoder_pair_scorer(resolved)
        elif lowered in {"listwise", "gemini-listwise"} or lowered.startswith(
            ("listwise:", "gemini-listwise:")
        ):
            scorer = build_gemini_listwise_pair_scorer(resolved)
            use_title_protect = True
        else:
            logger.warning(
                "rag_reranker_model=%s has no built-in adapter; using NoopReranker",
                model_name,
            )
            return NoopReranker()
    inner: Reranker = ModelReranker(scorer)
    if use_title_protect:
        inner = TitleProtectedListwiseReranker(inner)
    # Listwise LLM calls need a wider budget than cross-encoder.
    timeout_seconds = max(timeout_ms, 1) / 1000.0
    if use_title_protect:
        timeout_seconds = max(timeout_seconds, 90.0)
    return FailOpenReranker(inner, timeout_seconds=timeout_seconds)


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
