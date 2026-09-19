"""Adaptive Soft-RRF weights from generic query signals (RAG v2.1 P1).

No product- or exam-specific branches. Callers still own candidate list sizes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_ERROR_CODE_RE = re.compile(
    r"(?:\(-?\d{2,5}\)|(?:^|[^\w])-?\d{3,5}(?:$|[^\w])|Error\s+\d+|FAQ-\d+)",
    re.IGNORECASE,
)
_PRODUCT_TOKEN_RE = re.compile(
    r"\b(?:VPN|AD|OTP|MFA|SSLVPN|CRM|EMS|Intune|Outlook|Webex|GitLab|Portal)\b",
    re.IGNORECASE,
)
_CJK_RE = re.compile(r"[\u3400-\u9fff]")


@dataclass(frozen=True)
class AdaptiveFusionWeights:
    """Sparse/dense RRF weights + candidate depths for one query."""

    sparse_weight: float
    dense_weight: float
    sparse_candidate_k: int
    dense_candidate_k: int
    profile: str


def classify_fusion_profile(query: str) -> str:
    """Map a query to a generic fusion profile name."""
    text = (query or "").strip()
    if not text:
        return "natural_language"
    has_code = bool(_ERROR_CODE_RE.search(text))
    has_product = bool(_PRODUCT_TOKEN_RE.search(text))
    token_count = len(re.findall(r"[A-Za-z0-9_./:-]+|[\u3400-\u9fff]{1,4}", text))
    cjk_chars = len(_CJK_RE.findall(text))
    if has_code and not has_product:
        return "error_code"
    if has_code and has_product:
        return "product_and_code"
    if token_count >= 18 or (cjk_chars >= 40 and token_count >= 12):
        return "long_paraphrase"
    return "natural_language"


def adaptive_fusion_weights(
    query: str,
    *,
    default_sparse_weight: float = 0.5,
    default_dense_weight: float = 1.5,
    default_sparse_candidate_k: int = 40,
    default_dense_candidate_k: int = 10,
) -> AdaptiveFusionWeights:
    """Return Soft-RRF knobs from generic query shape only."""
    profile = classify_fusion_profile(query)
    if profile == "error_code":
        return AdaptiveFusionWeights(
            sparse_weight=2.0,
            dense_weight=0.5,
            sparse_candidate_k=max(default_sparse_candidate_k, 40),
            dense_candidate_k=max(10, min(default_dense_candidate_k, 20)),
            profile=profile,
        )
    if profile == "product_and_code":
        return AdaptiveFusionWeights(
            sparse_weight=1.5,
            dense_weight=1.0,
            sparse_candidate_k=max(default_sparse_candidate_k, 40),
            dense_candidate_k=max(default_dense_candidate_k, 20),
            profile=profile,
        )
    if profile == "long_paraphrase":
        return AdaptiveFusionWeights(
            sparse_weight=0.75,
            dense_weight=1.75,
            sparse_candidate_k=max(30, default_sparse_candidate_k),
            dense_candidate_k=max(default_dense_candidate_k, 40),
            profile=profile,
        )
    # natural_language — mild dense bias, never product-specific.
    return AdaptiveFusionWeights(
        sparse_weight=float(default_sparse_weight),
        dense_weight=float(default_dense_weight),
        sparse_candidate_k=int(default_sparse_candidate_k),
        dense_candidate_k=max(int(default_dense_candidate_k), 20),
        profile=profile,
    )


__all__ = [
    "AdaptiveFusionWeights",
    "adaptive_fusion_weights",
    "classify_fusion_profile",
]
