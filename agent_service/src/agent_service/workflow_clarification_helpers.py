"""Clarification-completion helpers for the agent workflow."""

from __future__ import annotations

import re

from .confirmation import TicketIntent
from .contracts import Issue, PendingIssueContext
from .supervisor import ConversationSupervisorDecision
from .workflow_helpers import AgentState

_ERROR_CODE_RE = re.compile(
    r"\(\s*-\s*\d+\s*\)|(?<![a-z0-9])-\d{1,5}(?![a-z0-9])",
    re.IGNORECASE,
)
_ERROR_PHRASE_TERMS = (
    "錯誤",
    "error",
    "失敗",
    "異常",
    "permission denied",
    "unable to establish",
)
_CATALOG_INTENT_MARKERS = (
    "錯訊說明",
    "錯誤碼清單",
    "錯誤代碼清單",
    "錯訊對照",
    "錯誤碼對照",
    "常見錯誤",
    "不要只給",
    "不要只提供",
    "其他的錯誤碼",
    "其他錯誤碼",
    "還有哪些錯誤",
)
_CATALOG_DOC_MARKERS = ("說明", "清單", "對照", "文件", "有哪些")
_CATALOG_ERROR_MARKERS = ("錯訊", "錯誤碼", "錯誤訊息", "錯誤代碼")


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


def _has_forticlient_product_cue(text: str) -> bool:
    normalized = text.casefold()
    return any(
        token in normalized
        for token in ("forticlient", "orticlient", "fortinet")
    ) or ("forti" in normalized and "client" in normalized)


def _is_error_catalog_documentation_request(text: str) -> bool:
    """True when the user wants an error-code catalog / doc, not personal triage."""
    raw = (text or "").strip()
    if not raw:
        return False
    normalized = raw.casefold()
    follow_up_catalog = any(
        marker in raw
        for marker in ("其他的錯誤碼", "其他錯誤碼", "還有哪些錯誤")
    )
    if follow_up_catalog:
        return True
    has_product = _has_forticlient_product_cue(raw)
    if any(marker in raw for marker in _CATALOG_INTENT_MARKERS) and (
        has_product
        or "vpn" in normalized
        or "vpn常見" in raw
        or "一般 vpn" in normalized
    ):
        return True
    if has_product and any(marker in raw for marker in _CATALOG_ERROR_MARKERS):
        return any(marker in raw for marker in _CATALOG_DOC_MARKERS)
    return False


def _detail_satisfies_kind(text: str, kind: str) -> bool:
    normalized = text.strip().lower().rstrip("。.!！?？")
    if not normalized:
        return False
    if kind == "ERROR":
        # Bare digits like "888" must not count; require a real error phrase or
        # FortiClient-style signed / parenthesized code.
        if any(term in normalized for term in _ERROR_PHRASE_TERMS):
            return True
        return bool(_ERROR_CODE_RE.search(normalized))
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


def _promote_error_catalog_documentation_request(
    issues: list[Issue],
    latest_text: str,
) -> list[Issue]:
    """Force READY knowledge lookup for FortiClient error-catalog questions."""
    if not _is_error_catalog_documentation_request(latest_text):
        return issues
    if len(issues) != 1:
        return issues
    current = issues[0]
    if not current.isIT:
        return issues
    description = latest_text.strip()
    route = current.route if current.route not in {"NOT_IT", ""} else "KNOWLEDGE"
    if route == "FAQ":
        route = "KNOWLEDGE"
    return [
        current.model_copy(
            update={
                "description": description,
                "retrieval_query": description,
                "readiness": "READY",
                "missingInfo": [],
                "route": route,
                "faqKey": None,
            }
        )
    ]


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
    promoted = _promote_error_catalog_documentation_request(issues, latest_text)
    if promoted is not issues and all(issue.readiness == "READY" for issue in promoted):
        return promoted

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
