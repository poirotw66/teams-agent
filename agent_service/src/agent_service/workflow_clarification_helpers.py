"""Clarification-completion helpers for the agent workflow."""

from __future__ import annotations

from .confirmation import TicketIntent
from .contracts import Issue, PendingIssueContext
from .supervisor import ConversationSupervisorDecision
from .workflow_helpers import AgentState


def _compose_pending_description(pending: PendingIssueContext, detail: str) -> str:
    """Join complementary user fragments into one stable retrieval query."""
    base = (pending.contextText or pending.description).strip().rstrip("。.!！?？")
    addition = detail.strip().rstrip("。.!！?？")
    if not base:
        return addition
    if not addition or addition.lower() in base.lower():
        return base
    return f"{base} {addition}"


def _missing_info_kind(question: str) -> str | None:
    normalized = question.lower()
    if any(term in normalized for term in ("系統", "應用程式", "app", "軟體", "平台", "用戶端")):
        return "SYSTEM"
    if any(term in normalized for term in ("錯誤訊息", "錯誤碼", "error", "代碼")):
        return "ERROR"
    if any(term in normalized for term in ("功能", "操作", "需求", "要做什麼", "協助項目")):
        return "FEATURE"
    return None


def _detail_satisfies_kind(text: str, kind: str) -> bool:
    normalized = text.strip().lower().rstrip("。.!！?？")
    if not normalized:
        return False
    if kind == "ERROR":
        return bool(
            any(term in normalized for term in ("錯誤", "error", "失敗", "異常"))
            or any(character.isdigit() for character in normalized)
        )
    if kind == "FEATURE":
        return any(
            term in normalized
            for term in (
                "借用",
                "預約",
                "申請",
                "登入",
                "連線",
                "上傳",
                "下載",
                "安裝",
                "開啟",
                "列印",
                "查詢",
                "重置",
                "變更",
                "設定",
            )
        )
    if kind == "SYSTEM":
        if len(normalized) > 40:
            return False
        # Product-only fragments normally contain Latin letters (Webex,
        # SAP, PortalX) or a short Chinese proper name.  Problem/action words
        # indicate that this is likely a complete issue rather than a name.
        issue_markers = (
            "無法",
            "不能",
            "壞",
            "問題",
            "怎麼",
            "如何",
            "借用",
            "登入",
            "連線",
            "申請",
            "錯誤",
            "error",
        )
        return not any(marker in normalized for marker in issue_markers)
    return False


def _answers_missing_info(text: str, questions: list[str]) -> bool:
    return any(
        kind is not None and _detail_satisfies_kind(text, kind)
        for question in questions
        if (kind := _missing_info_kind(question)) is not None
    )


def _complete_complementary_pending_issue(
    issues: list[Issue],
    pending_issues: list[PendingIssueContext],
    latest_text: str,
    *,
    decision: ConversationSupervisorDecision | None = None,
) -> list[Issue]:
    """Resolve two complementary fragments instead of asking in a loop.

    The extractor has already decided that the latest message is IT-related.
    If one active clarification exists and the extractor still wants to ask a
    different clarification, conversationally the short latest turn is the
    answer to the outstanding slot.  Compose both user fragments and proceed
    with a best-effort lookup.  Clearly non-IT turns never enter this path and
    explicit topic abandonment is handled separately.
    """
    if (
        len(pending_issues) != 1
        or len(issues) != 1
        or (decision is not None and decision.topicRelation == "ABANDON")
    ):
        return issues
    pending = pending_issues[0]
    current = issues[0]
    if (
        not current.isIT
        or current.readiness != "NEED_MORE_INFO"
        or not pending.missingInfo
        or not _answers_missing_info(latest_text, pending.missingInfo)
        or not _answers_missing_info(
            pending.contextText or pending.description, current.missingInfo
        )
    ):
        return issues
    composed = _compose_pending_description(pending, latest_text)
    return [
        current.model_copy(
            update={
                "description": composed,
                # Keep retrieval aligned with the composed user fragments.
                "retrieval_query": composed,
                "readiness": "READY",
                "missingInfo": [],
                "route": pending.route if pending.route != "NOT_IT" else "KNOWLEDGE",
                "faqKey": pending.faqKey,
            }
        )
    ]


def _preserves_interrupted_clarification(state: AgentState) -> bool:
    """Keep an unresolved question when the current turn does not answer it."""
    prior = state.get("prior_pending_issues", [])
    issues = state.get("issues", [])
    decision = state.get("supervisor_decision")
    ticket_intent = state.get("ticket_intent")
    return bool(
        prior
        and decision is not None
        and decision.topicRelation != "ABANDON"
        and (
            (issues and all(not issue.isIT for issue in issues))
            or decision.topicRelation in {"NEW", "META"}
            or ticket_intent is TicketIntent.QUERY
        )
    )
