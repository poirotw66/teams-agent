"""RAG v2 shadow/canary rollout helpers (spec §46–§48).

Production defaults stay on the current retrieval path until canary percent
and success gates say otherwise. Canary uses sticky buckets so a conversation
sees a stable variant.

Runtime canary varies fusion/reranker only. Contextual indexing is a
knowledge-release A/B concern, not a per-request switch (everyone shares the
loaded index).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from platform_kernel.hashing import sticky_bucket

# Canary ladder from docs/rag-v2-spec.md §48.
CANARY_LADDER_PERCENTS: tuple[int, ...] = (5, 20, 50, 100)

# Runtime canary variants (fusion / reranker knobs only).
VARIANT_A_WEIGHTED = "A_WEIGHTED"
VARIANT_B_RRF = "B_RRF"
VARIANT_C_RRF_RERANK = "C_RRF_RERANK"
# Legacy aliases kept so older configs / dashboards keep resolving.
VARIANT_C_RRF_CONTEXTUAL = "C_RRF_CONTEXTUAL"  # alias → B_RRF semantics
VARIANT_D_RRF_CONTEXTUAL_RERANK = "D_RRF_CONTEXTUAL_RERANK"  # alias → C_RRF_RERANK


@dataclass(frozen=True)
class RagServingDecision:
    """Which retrieval path a request should use."""

    serve_variant: str
    is_canary: bool
    canary_percent: int
    shadow_enabled: bool
    fusion_mode: str = "RRF"
    reranker_enabled: bool = False


def _normalize_variant(variant: str) -> str:
    normalized = (variant or VARIANT_A_WEIGHTED).strip().upper()
    # Legacy C_RRF_CONTEXTUAL claimed a different index; runtime cannot do that.
    if normalized in {VARIANT_C_RRF_CONTEXTUAL, "C_CONTEXTUAL"}:
        return VARIANT_B_RRF
    if normalized in {VARIANT_D_RRF_CONTEXTUAL_RERANK, "D", VARIANT_C_RRF_RERANK}:
        return VARIANT_C_RRF_RERANK
    if normalized in {VARIANT_B_RRF, "B", "C"}:
        # Bare "C" historically meant RRF-only (with B/C in the old matrix).
        return VARIANT_B_RRF
    if normalized in {VARIANT_A_WEIGHTED, "A"}:
        return VARIANT_A_WEIGHTED
    return normalized


def retrieval_knobs_for_variant(
    variant: str,
    *,
    baseline_fusion_mode: str = "RRF",
    global_reranker_enabled: bool = False,
) -> tuple[str, bool]:
    """Map experiment variant → (fusion_mode, reranker_enabled)."""
    normalized = _normalize_variant(variant)
    if normalized == VARIANT_B_RRF:
        return "RRF", False
    if normalized == VARIANT_C_RRF_RERANK:
        return "RRF", bool(global_reranker_enabled)
    # A / unknown: production knobs from settings.
    return (baseline_fusion_mode or "RRF").strip().upper(), bool(global_reranker_enabled)


def select_rag_serving_variant(
    *,
    tenant: str,
    conversation_id: str,
    canary_percent: int,
    canary_variant: str = VARIANT_C_RRF_RERANK,
    baseline_variant: str = VARIANT_A_WEIGHTED,
    shadow_enabled: bool = False,
    baseline_fusion_mode: str = "RRF",
    global_reranker_enabled: bool = False,
) -> RagServingDecision:
    """Sticky canary routing. ``canary_percent=0`` always serves baseline."""
    percent = max(0, min(100, int(canary_percent)))
    if percent <= 0:
        fusion, rerank = retrieval_knobs_for_variant(
            baseline_variant,
            baseline_fusion_mode=baseline_fusion_mode,
            global_reranker_enabled=global_reranker_enabled,
        )
        return RagServingDecision(
            serve_variant=baseline_variant,
            is_canary=False,
            canary_percent=0,
            shadow_enabled=shadow_enabled,
            fusion_mode=fusion,
            reranker_enabled=rerank,
        )
    bucket = sticky_bucket(tenant, conversation_id)
    on_canary = bucket < percent
    serve_variant = canary_variant if on_canary else baseline_variant
    fusion, rerank = retrieval_knobs_for_variant(
        serve_variant,
        baseline_fusion_mode=baseline_fusion_mode,
        global_reranker_enabled=global_reranker_enabled,
    )
    return RagServingDecision(
        serve_variant=serve_variant,
        is_canary=on_canary,
        canary_percent=percent,
        shadow_enabled=shadow_enabled,
        fusion_mode=fusion,
        reranker_enabled=rerank,
    )


def next_canary_percent(current: int) -> int | None:
    """Return the next ladder step, or None when already at 100."""
    current = max(0, min(100, int(current)))
    for step in CANARY_LADDER_PERCENTS:
        if step > current:
            return step
    return None


def topk_overlap(left: Sequence[str], right: Sequence[str], *, k: int) -> float:
    """Jaccard overlap of the first ``k`` ranked ids."""
    left_set = set(list(left)[:k])
    right_set = set(list(right)[:k])
    if not left_set and not right_set:
        return 1.0
    union = left_set | right_set
    if not union:
        return 0.0
    return len(left_set & right_set) / len(union)


def top1_changed(left: Sequence[str], right: Sequence[str]) -> bool:
    if not left and not right:
        return False
    if not left or not right:
        return True
    return left[0] != right[0]


__all__ = [
    "CANARY_LADDER_PERCENTS",
    "VARIANT_A_WEIGHTED",
    "VARIANT_B_RRF",
    "VARIANT_C_RRF_CONTEXTUAL",
    "VARIANT_C_RRF_RERANK",
    "VARIANT_D_RRF_CONTEXTUAL_RERANK",
    "RagServingDecision",
    "next_canary_percent",
    "retrieval_knobs_for_variant",
    "select_rag_serving_variant",
    "top1_changed",
    "topk_overlap",
]
