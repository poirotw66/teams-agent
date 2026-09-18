"""Retrieval-probe answerability checks for issue processing."""

from __future__ import annotations

from .contracts import Issue, IssueResult

_REQUESTED_FACET_MARKERS = (
    "如何",
    "哪些",
    "什麼",
    "列出",
    "說明",
    "原則",
    "分流",
    "時間",
    "期限",
    "內容",
    "資料",
    "規定",
    "能支持",
    "操作順序",
    "操作方式",
    "步驟",
    "處理",
)

_BRANCHING_PATH_INDICATORS = (
    "請先確認",
    "視您的身分",
    "若為不同",
    "不同身分",
    "端視",
    "依據您的",
    "視您所屬",
    "若您是",
    "如果您是",
)
_SCENARIO_CONFLICT_MARKERS = ("FAQ-001", "FAQ-002", "FAQ-003", "FAQ-004")

__all__ = ["_retrieval_probe_is_answerable"]


def _retrieval_probe_is_answerable(
    issue: Issue,
    result: IssueResult,
) -> bool:
    if (
        result.resultType != "KNOWLEDGE_ANSWERED"
        or not result.sources
        or result.terminalReason is not None
    ):
        return False

    # 1. Answerability must be FULL or PARTIAL (or unspecified in test doubles)
    if result.answerability not in ("FULL", "PARTIAL", None):
        return False

    # 2. When answerability is specified, must be backed by non-empty grounded claims
    if result.answerability in ("FULL", "PARTIAL") and not result.claims:
        return False

    # 3. Single canonical source entity to avoid cross-source ambiguity
    canonical_sources = {
        source.canonicalSourceId or source.documentId or source.title
        for source in result.sources
        if (source.canonicalSourceId or source.documentId or source.title)
    }
    if len(canonical_sources) != 1:
        return False

    # 4. Requested facet must be covered in user's query or description
    check_texts = [issue.description]
    if result.retrievalTrace:
        if result.retrievalTrace.rawUserUtterance:
            check_texts.append(result.retrievalTrace.rawUserUtterance)
        if result.retrievalTrace.resolvedIssueQuery:
            check_texts.append(result.retrievalTrace.resolvedIssueQuery)

    has_requested_facet = any(
        marker in text for text in check_texts for marker in _REQUESTED_FACET_MARKERS
    )
    if not has_requested_facet:
        return False

    # 5. Missing info must not alter path (no conditional branching in answer)
    answer_text = result.answer or ""
    if any(indicator in answer_text for indicator in _BRANCHING_PATH_INDICATORS):
        return False

    # 6. No cross-scenario conflict in answer
    matched_scenarios = [marker for marker in _SCENARIO_CONFLICT_MARKERS if marker in answer_text]
    return len(matched_scenarios) <= 1
