"""Answer-generation retry and rejection policies (pure).

I/O (LLM invoke, claim repair) remains on HybridKnowledgeService._generate.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from agent_service.contracts import GroundedClaim
from agent_service.retrieval import SearchResult

from .grounding import (
    answer_covers_error_branches,
    answer_covers_procedure_steps,
    answer_covers_visual_evidence_plates,
    query_asks_for_procedure,
    query_asks_for_visual_evidence,
)
from .relevance import (
    answer_indicates_insufficient_information,
    query_lexically_matches_results,
)

_ERROR_BRANCH_QUERY_MARKERS: tuple[str, ...] = (
    "分流",
    "錯誤時",
    "各錯誤",
    "不同錯誤",
    "多個錯誤",
    "錯誤碼分流",
)

# Full-KB miss phrasing (not scoped "未特別說明" sub-detail gaps).
_PRIMARY_KB_MISS_MARKERS: tuple[str, ...] = (
    "目前知識庫中並未",
    "目前知識庫中並無",
    "目前知識庫並未",
    "目前知識庫並無",
    "知識庫中並無",
    "知識庫中並未",
    "知識庫未提供",
    "查無相關資訊",
    "查無相關信息",
    "沒有足夠資訊",
    "沒有足夠信息",
    "無法從企業知識庫",
    "無法從知識庫",
    "無法提供答案",
    "無法回答",
    "找不到相關資訊",
    "找不到相關信息",
)
_CITATION_MARKER_PATTERN = re.compile(r"\[S\d+\]")
_UNDERSPECIFIED_SYSTEM_QUERY_PATTERN = re.compile(
    r"(那個系統|某[個一]?系統|什麼系統)"
)
_COMPARISON_SYSTEM_QUERY_PATTERN = re.compile(
    r"(各屬|分別|各自|屬於哪個|是哪個系統|哪個系統的)"
)
_CONCRETE_SYSTEM_NAME_PATTERN = re.compile(
    r"(?i)\b(?:gitlab|git\s*lab|outlook|forticlient|accessflow|teams|sap|"
    r"intune|vpn|sharepoint)\b|樹精靈|Gitlab|GitLab"
)
_QUERY_ANCHOR_STOP = frozenset(
    {
        "公司",
        "個人",
        "正式",
        "目前",
        "如何",
        "什麼",
        "哪個",
        "可以",
        "是否",
        "怎麼",
        "怎樣",
        "相關",
        "問題",
        "說明",
        "安裝",
        "登入",
        "申請",
        "使用",
        "設定",
        "連線",
        "方式",
        "操作",
        "處理",
        "確認",
        "提供",
        "企業",  # too common alone; keep with App via latin token
    }
)


def query_asks_for_error_branching(query: str) -> bool:
    return any(marker in query for marker in _ERROR_BRANCH_QUERY_MARKERS)


def should_retry_false_none(
    *,
    answerability: str,
    results: Sequence[SearchResult],
    confidence_label: str,
    answer: str,
    claims: Sequence[GroundedClaim],
    resolved_issue_query: str,
) -> bool:
    """High-confidence retrieval produced NONE / empty claims despite lexical overlap."""
    return (
        answerability == "NONE"
        and bool(results)
        and confidence_label == "HIGH_CONFIDENCE_PASS"
        and (answer_indicates_insufficient_information(answer) or not claims)
        and query_lexically_matches_results(resolved_issue_query, list(results))
    )


def should_retry_error_coverage(
    *,
    answerability: str,
    resolved_issue_query: str,
    context_error_codes: Sequence[str],
    answer: str,
) -> bool:
    return (
        answerability in {"FULL", "PARTIAL"}
        and query_asks_for_error_branching(resolved_issue_query)
        and len(context_error_codes) >= 2
        and not answer_covers_error_branches(answer, list(context_error_codes))
    )


def should_retry_procedure_coverage(
    *,
    answerability: str,
    resolved_issue_query: str,
    context_procedure_steps: Sequence[str],
    answer: str,
) -> bool:
    return (
        answerability in {"FULL", "PARTIAL"}
        and query_asks_for_procedure(resolved_issue_query)
        and len(context_procedure_steps) >= 2
        and not answer_covers_procedure_steps(answer, list(context_procedure_steps))
    )


def should_retry_visual_evidence(
    *,
    answerability: str,
    resolved_issue_query: str,
    context_visual_plates: Sequence[str],
    answer: str,
) -> bool:
    return (
        answerability in {"FULL", "PARTIAL"}
        and query_asks_for_visual_evidence(resolved_issue_query)
        and len(context_visual_plates) >= 2
        and not answer_covers_visual_evidence_plates(answer, list(context_visual_plates))
    )


def should_keep_prior_after_visual_retry(
    *,
    context_procedure_steps: Sequence[str],
    answer: str,
) -> bool:
    """Reject a visual retry that drops previously covered procedure steps."""
    return bool(context_procedure_steps) and not answer_covers_procedure_steps(
        answer, list(context_procedure_steps)
    )


def query_anchor_tokens(query: str) -> set[str]:
    """High-value query anchors for claim-overlap checks (not tokenizer bigrams)."""
    anchors: set[str] = set()
    for match in re.finditer(r"[A-Za-z][A-Za-z0-9_./:-]{1,}", query):
        anchors.add(match.group(0).lower())
    for match in re.finditer(r"[0-9]{2,}", query):
        anchors.add(match.group(0))
    for match in re.finditer(r"[\u3400-\u9fff]+", query):
        run = match.group(0)
        if run in _QUERY_ANCHOR_STOP:
            continue
        if len(run) <= 4:
            anchors.add(run)
            continue
        for size in (2, 3, 4):
            for index in range(len(run) - size + 1):
                piece = run[index : index + size]
                if piece not in _QUERY_ANCHOR_STOP:
                    anchors.add(piece)
    return anchors


def claims_address_query_anchors(
    *,
    resolved_issue_query: str,
    claims: Sequence[GroundedClaim],
) -> bool:
    anchors = query_anchor_tokens(resolved_issue_query)
    if not anchors:
        return False
    claim_blob = " ".join(claim.text for claim in claims).lower()
    return any(anchor.lower() in claim_blob for anchor in anchors)


def query_is_underspecified_system(query: str) -> bool:
    """True when the user refers to a system without naming it."""
    if _COMPARISON_SYSTEM_QUERY_PATTERN.search(query):
        return False
    return bool(_UNDERSPECIFIED_SYSTEM_QUERY_PATTERN.search(query))


def answer_names_concrete_system(answer: str) -> bool:
    return bool(_CONCRETE_SYSTEM_NAME_PATTERN.search(answer))


def answer_pads_primary_knowledge_gap(answer: str) -> bool:
    """True when the answer leads with a full KB miss then cites adjacent advice.

    Scoped gaps such as「來源未特別說明…」remain allowed when the main ask is
    otherwise grounded. Padding after a *leading*「目前知識庫中並未記載…」must
    not become a found=True answer. Mid-answer gap phrasing alone is not enough.
    """
    stripped = answer.lstrip()
    if not stripped:
        return False
    first_line = stripped.split("\n", 1)[0]
    leading_miss = any(
        first_line.startswith(marker) or stripped.startswith(marker)
        for marker in _PRIMARY_KB_MISS_MARKERS
    )
    if not leading_miss:
        return False
    return bool(_CITATION_MARKER_PATTERN.search(stripped))


def is_unsupported_miss_answer(
    *,
    answer: str,
    answerability: str,
    claims: Sequence[GroundedClaim],
    resolved_issue_query: str = "",
) -> bool:
    if resolved_issue_query and query_is_underspecified_system(resolved_issue_query):
        if answer_names_concrete_system(answer):
            return True
    if answer_pads_primary_knowledge_gap(answer):
        substantive_claims = [
            claim
            for claim in claims
            if not answer_indicates_insufficient_information(claim.text)
        ]
        if not substantive_claims:
            return True
        if resolved_issue_query and claims_address_query_anchors(
            resolved_issue_query=resolved_issue_query,
            claims=substantive_claims,
        ):
            return False
        # Multi-facet answers sometimes lead with a scoped gap sentence while
        # still covering the asked systems in later claims/citations.
        if len(substantive_claims) >= 2 and resolved_issue_query:
            covered = sum(
                1
                for claim in substantive_claims
                if claims_address_query_anchors(
                    resolved_issue_query=resolved_issue_query,
                    claims=[claim],
                )
            )
            if covered >= 2:
                return False
        return True
    return answer_indicates_insufficient_information(answer) and (
        answerability == "NONE"
        or not claims
        or not any(
            not answer_indicates_insufficient_information(claim.text) for claim in claims
        )
    )


__all__ = [
    "answer_names_concrete_system",
    "answer_pads_primary_knowledge_gap",
    "claims_address_query_anchors",
    "is_unsupported_miss_answer",
    "query_anchor_tokens",
    "query_asks_for_error_branching",
    "query_is_underspecified_system",
    "should_keep_prior_after_visual_retry",
    "should_retry_error_coverage",
    "should_retry_false_none",
    "should_retry_procedure_coverage",
    "should_retry_visual_evidence",
]
