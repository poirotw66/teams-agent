"""Dedicated PairScorer adapters for RAG v2.1 reranker A/B.

``vertex-ranking:`` — Vertex AI Ranking API (Discovery Engine rank service).
``qwen3-reranker:`` — Qwen3 Reranker via sentence_transformers CrossEncoder.

Both fail closed to an exception at the PairScorer boundary; callers wrap with
FailOpenReranker. Missing credentials / packages raise RuntimeError with a
clear install/config hint (no silent benchmark shortcuts).
"""

from __future__ import annotations

import asyncio
import os
import threading
from collections.abc import Sequence
from typing import Any

from .reranker import PairScorer, build_cross_encoder_pair_scorer

_cached_client: Any = None
_cached_engine: Any = None
_client_lock = threading.Lock()


def _get_vertex_rank_client() -> tuple[Any, Any]:
    global _cached_client, _cached_engine
    if _cached_client is not None and _cached_engine is not None:
        return _cached_client, _cached_engine
    with _client_lock:
        if _cached_client is None or _cached_engine is None:
            try:
                from google.cloud import discoveryengine_v1 as discoveryengine
            except ImportError as error:
                raise RuntimeError(
                    "google-cloud-discoveryengine is required for vertex-ranking reranker"
                ) from error
            _cached_engine = discoveryengine
            _cached_client = discoveryengine.RankServiceClient()
    return _cached_client, _cached_engine


def _resolve_vertex_model_id(model_id: str) -> str:
    resolved = model_id.strip() or "semantic-ranker-default"
    for prefix in ("vertex-ranking:", "vertex_ranking:", "ranking-api:", "ranking_api:"):
        if resolved.lower().startswith(prefix):
            resolved = resolved.split(":", 1)[1].strip() or "semantic-ranker-default"
            break
    if resolved.lower() in {"vertex-ranking", "vertex_ranking", "ranking-api", "ranking_api"}:
        resolved = "semantic-ranker-default"
    if "@" not in resolved:
        resolved = f"{resolved}@latest"
    return resolved


def _parse_vertex_rank_scores(records: Sequence[Any], count: int) -> list[float]:
    scores = [0.0] * count
    for record in records:
        try:
            index = int(record.id)
        except (TypeError, ValueError):
            continue
        if 0 <= index < len(scores):
            scores[index] = float(getattr(record, "score", 0.0) or 0.0)
    return scores


def build_vertex_ranking_pair_scorer(model_id: str = "semantic-ranker-default") -> PairScorer:
    """Rank documents with Vertex AI Ranking API."""
    resolved = _resolve_vertex_model_id(model_id)
    project = (
        os.environ.get("VERTEX_RANKING_PROJECT")
        or os.environ.get("GOOGLE_CLOUD_PROJECT")
        or os.environ.get("GCLOUD_PROJECT")
        or ""
    ).strip()
    location = (os.environ.get("VERTEX_RANKING_LOCATION") or "global").strip() or "global"

    async def score_pairs(query: str, texts: Sequence[str]) -> Sequence[float]:
        if not texts:
            return []
        if not project:
            raise RuntimeError(
                "Vertex Ranking API requires VERTEX_RANKING_PROJECT or GOOGLE_CLOUD_PROJECT"
            )
        client, discoveryengine = _get_vertex_rank_client()
        ranking_config = (
            f"projects/{project}/locations/{location}/rankingConfigs/default_ranking_config"
        )
        records = [
            discoveryengine.RankingRecord(
                id=str(index),
                title="",
                content=(text or "")[:8000],
            )
            for index, text in enumerate(texts)
        ]

        def _rank() -> list[float]:
            response = client.rank(
                request=discoveryengine.RankRequest(
                    ranking_config=ranking_config,
                    model=resolved,
                    query=query or "",
                    records=records,
                )
            )
            return _parse_vertex_rank_scores(response.records, len(texts))

        return await asyncio.to_thread(_rank)

    return score_pairs


def build_qwen3_reranker_pair_scorer(model_id: str = "Qwen/Qwen3-Reranker-0.6B") -> PairScorer:
    """Qwen3 reranker as a CrossEncoder PairScorer (optional local/HF runtime)."""
    resolved = model_id.strip() or "Qwen/Qwen3-Reranker-0.6B"
    for prefix in ("qwen3-reranker:", "qwen3_reranker:", "qwen3:"):
        if resolved.lower().startswith(prefix):
            resolved = resolved.split(":", 1)[1].strip() or "Qwen/Qwen3-Reranker-0.6B"
            break
    if resolved.lower() in {"qwen3-reranker", "qwen3_reranker", "qwen3"}:
        resolved = "Qwen/Qwen3-Reranker-0.6B"
    return build_cross_encoder_pair_scorer(f"cross-encoder:{resolved}")


__all__ = [
    "build_qwen3_reranker_pair_scorer",
    "build_vertex_ranking_pair_scorer",
]
