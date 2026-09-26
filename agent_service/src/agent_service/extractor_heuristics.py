"""Heuristics, rule-based classifiers, and ticket-merging helpers for IssueExtractor."""

from __future__ import annotations

import re

from .contracts import ConversationMessage, Issue
from .sanitize import sanitize_description

_SAFE_FALLBACK_DESCRIPTION_MAX_LEN = 4000
_GENERIC_TICKET_DESCRIPTION = "使用者提出的 IT 支援請求"
_DAZHOU_FAILURE_TERMS = ("無法", "不能", "選取", "點選", "登入", "功能")

# Operational symptom verbs/phrases for the READY skip-extractor.
_READY_SYMPTOM_FAILURE_TERMS = (
    "無法登入",
    "無法連線",
    "無法點選",
    "無法選取",
    "打不開",
    "斷線",
    "鎖住",
    "被鎖",
    "連不上",
    "功能無法",
    "無法開啟",
    "無法使用",
    "登入異常",
    "登入無反應",
    "登入無反映",
    "畫面無反應",
)
# Concrete product/system names only — bare 系統/客戶 are too broad for READY.
_READY_SYMPTOM_SYSTEM_TERMS = (
    "vpn",
    "outlook",
    "teams",
    "xq",
    "proxy",
    "gitlab",
    "大州",
    "forticlient",
    "webex",
    "sharepoint",
    "powerpivot",
    "入口網",
    "樹精靈",
    "金控入口",
    "cteam",
    "e點名",
)
_MULTI_ISSUE_CONNECTOR_RE = re.compile(r"和|與|還有|另外|同時|以及|兩邊|兩個")
_POLICY_OR_META_QUESTION_MARKERS = (
    "原則",
    "為何",
    "為什麼",
    "哪些",
    "什麼處置",
    "來源能支持",
    "能支持哪些",
    "今天天氣",
)
_STANDALONE_HELPDESK_SIGNALS = (
    "powerpivot",
    "xq",
    "話機型號",
    "話機面板",
    "座位搬遷",
    "座位遷移",
    "換座位",
    "電腦聯繫單",
    "外部客戶線上問題",
    "資訊問題通報",
    "報價查核",
    "五檔",
)
_SYSTEM_TERMS = (
    "系統",
    "vpn",
    "teams",
    "outlook",
    "網路",
    "平台",
    "帳號",
    "客戶",
    "報價",
    "外部客戶",
    "xq",
    "proxy",
)
_DEVICE_TERMS = (
    "裝置",
    "電腦",
    "主機",
    "筆電",
    "伺服器",
    "瀏覽器",
    "proxy",
    "話機",
    "設備",
)
_IT_DOC_TERMS = (
    "手冊",
    "知識庫",
    "來源",
    "流程",
    "faq",
    "it",
    "工單",
    "客服",
)
_TICKET_COMMAND_RE = re.compile(
    r"(?:請|麻煩|幫我|幫忙|替我|屜我|我要|確認|確定|好[，,]?|協助我?)*"
    r"(?:建立|建|開|提交|送出|申請)?(?:一張|個|張)?(?:派)?工單|開單|報修"
)
_TICKET_COMMAND_PUNCTUATION = " ，。；、,.!?！？」"
_COURTESY_ONLY_RE = re.compile(
    r"^(?:請|麻煩|幫我|幫忙|替我|屜我|我要|確認|確定|好的?|協助我?|謝謝(?:你|您)?)+$"
)
_ASSISTANT_SCOPE_MARKERS: tuple[str, ...] = (
    "什麼問題",
    "哪些問題",
    "什麼幫",
    "什麼協助",
    "做什麼",
    "幹嘛",
    "幹什麼",
    "功能",
    "服務範圍",
    "能力",
    "回答什麼",
    "處理什麼",
    "協助什麼",
    "能問什麼",
    "問你什麼",
    "幫我什麼",
)
HUMAN_ESCALATION_ISSUE_DESCRIPTION = "使用者要求聯絡線上客服"
_ESCALATION_PHRASES: tuple[str, ...] = (
    "聯絡線上客服",
    "联系线上客服",
    "我要找真人客服",
    "找真人客服",
    "聯絡客服",
    "聯繫客服",
    "人工客服",
    "轉人工",
    "转人工",
    "it支援窗口",
    "it支持窗口",
)


def _normalize_escalation_text(text: str) -> str:
    compact = re.sub(r"\s+", "", text.strip().rstrip("。.!！?？"))
    normalized = compact.replace("聯繫", "聯絡")
    return normalized.replace("流落線上客服", "聯絡線上客服").casefold()


def _is_human_escalation_request(text: str) -> bool:
    """Detect escalation-only turns that must not trigger a knowledge lookup."""
    compact = _normalize_escalation_text(text)
    if not compact or len(compact) > 40:
        return False
    if not any(phrase.casefold() in compact for phrase in _ESCALATION_PHRASES):
        return False
    stripped = compact
    for phrase in sorted(_ESCALATION_PHRASES, key=len, reverse=True):
        stripped = stripped.replace(phrase.casefold(), "")
    stripped = re.sub(r"[，,。！？!?了嗎呢吧請]+", "", stripped)
    return len(stripped) <= 4


def _has_helpdesk_domain_evidence(text: str) -> bool:
    normalized = re.sub(r"\s+", " ", text).strip().casefold()
    if any(signal in normalized for signal in _STANDALONE_HELPDESK_SIGNALS):
        return True
    if re.search(
        r"(?:錯誤(?:碼|代碼)?|error(?:\s*code)?)\s*[-:#]?\s*\d{3,}",
        normalized,
        re.IGNORECASE,
    ):
        return True
    if re.search(r"\b\d{4,5}\b", normalized) and any(
        kw in normalized for kw in ("錯誤", "error", "code", "異常", "失敗", "連線")
    ):
        return True
    # Composite: system + principle
    if any(s in normalized for s in _SYSTEM_TERMS) and any(
        p in normalized for p in ("處置原則", "處理原則", "原則")
    ):
        return True
    # Composite: device + policy
    if any(d in normalized for d in _DEVICE_TERMS) and any(
        p in normalized for p in ("管控政策", "政策", "安全性設定", "安全設定")
    ):
        return True
    # Composite: screen / screenshot + privacy / sensitive info / password
    if any(img in normalized for img in ("截圖", "畫面", "圖片", "影像")) and any(
        sec in normalized for sec in ("敏感資訊", "個資", "密碼", "密碼保護", "遮蔽", "保護")
    ):
        return True
    # Composite: manual + support
    return bool(
        any(doc in normalized for doc in _IT_DOC_TERMS)
        and any(m in normalized for m in ("來源能支持", "能支持", "操作順序", "操作方式"))
    )


_IT_SCOPE_KEYWORDS: tuple[str, ...] = (
    "工作內容",
    "在做什麼",
    "做什麼的",
    "負責什麼",
    "服務項目",
    "服務範圍",
    "服務內容",
    "服務目錄",
    "服務清單",
    "支援項目",
    "支援範圍",
    "工作職責",
    "業務職掌",
    "業務介紹",
    "業務簡介",
    "服務有哪些",
    "提供什麼服務",
    "支援什麼",
    "有什麼服務",
    "有那些服務",
)

_IT_TARGET_KEYWORDS: tuple[str, ...] = (
    "it",
    "資訊處",
    "資訊部",
    "資訊科",
    "資訊組",
    "資訊團隊",
    "資訊小幫手",
    "it助手",
    "it小幫手",
)


def _is_assistant_scope_question(text: str) -> bool:
    """Detect meta questions about this assistant's scope or IT service catalog."""
    compact = re.sub(r"\s+", "", text.strip().rstrip("。.!！?？"))
    if not compact or len(compact) > 48:
        return False
    compact = compact.replace("回瘩", "回答").replace("回覆", "回答")
    compact_lower = compact.casefold()
    if any(
        marker in compact
        for marker in (
            "你的功能",
            "你的服務",
            "服務範圍",
            "問你什麼",
            "能問什麼",
            "你能做什麼",
            "你能回答",
        )
    ):
        return True
    if any(target in compact_lower for target in _IT_TARGET_KEYWORDS) and any(
        keyword in compact for keyword in _IT_SCOPE_KEYWORDS
    ):
        return True
    if not compact.startswith(("你能", "你可以", "你會", "您能", "您可以")):
        return False
    return any(marker in compact for marker in _ASSISTANT_SCOPE_MARKERS)


def _normalize_known_it_terms(text: str) -> str:
    """Normalize a narrow, observed alias without changing general language."""
    if "大洲" in text and any(term in text for term in _DAZHOU_FAILURE_TERMS):
        text = text.replace("大洲", "大州")
    if (
        "大州" in text
        and "大州系統" not in text
        and any(term in text for term in _DAZHOU_FAILURE_TERMS)
    ):
        text = text.replace("大州", "大州系統", 1)
    return text


def _is_known_dazhou_issue(description: str) -> bool:
    return "大州" in description and any(term in description for term in _DAZHOU_FAILURE_TERMS)


def _looks_like_multi_issue_message(text: str) -> bool:
    compact = re.sub(r"\s+", "", text)
    return bool(_MULTI_ISSUE_CONNECTOR_RE.search(compact))


def _is_ready_known_it_symptom(description: str) -> bool:
    """Closed-set READY knowledge hits that do not need the extractor LLM."""
    if _is_known_dazhou_issue(description):
        return True
    if any(marker in description for marker in _POLICY_OR_META_QUESTION_MARKERS):
        return False
    normalized = re.sub(r"\s+", " ", description).strip().casefold()
    has_named_system = any(
        term.casefold() in normalized for term in _READY_SYMPTOM_SYSTEM_TERMS
    )
    has_failure = any(term in description for term in _READY_SYMPTOM_FAILURE_TERMS)
    return has_named_system and has_failure


def _is_shu_channel_login_symptom(description: str) -> bool:
    """樹精靈 AP/WEB login asks already name the handbook; do not ask for a code."""
    compact = "".join(description.split()).casefold()
    if "樹精靈ap" not in compact and "樹精靈web" not in compact:
        return False
    return any(term in description for term in _READY_SYMPTOM_FAILURE_TERMS)


def _can_skip_extractor_for_ready_symptom(
    text: str,
    *,
    history: list[ConversationMessage],
) -> bool:
    """Safety gates around the ready-symptom zero-LLM path."""
    if history:
        return False
    if _looks_like_multi_issue_message(text):
        return False
    if _is_human_escalation_request(text) or _is_assistant_scope_question(text):
        return False
    return _is_ready_known_it_symptom(text)


def _strip_ticket_command(text: str) -> str:
    stripped = _TICKET_COMMAND_RE.sub("", text).strip(_TICKET_COMMAND_PUNCTUATION)
    if _is_courtesy_only(stripped):
        return ""
    return stripped


def _is_courtesy_only(text: str) -> bool:
    compact = re.sub(r"\s+", "", text.strip())
    return (not compact) or bool(_COURTESY_ONLY_RE.fullmatch(compact))


def _is_generic_ticket_description(description: str) -> bool:
    cleaned = sanitize_description(description).strip()
    return cleaned == _GENERIC_TICKET_DESCRIPTION or _is_courtesy_only(cleaned)


def _is_generic_ticket_request(text: str) -> bool:
    return _is_generic_ticket_description(_strip_ticket_command(text))


def merge_pending_ticket_issues(issues: list[Issue]) -> Issue:
    """Merge issues recovered from a pending-offer confirmation into one ticket."""
    descriptions: list[str] = []
    for issue in issues:
        if not issue.isIT:
            continue
        description = sanitize_description(_strip_ticket_command(issue.description))
        if description and description not in descriptions:
            descriptions.append(description)

    merged = "；".join(descriptions) or _GENERIC_TICKET_DESCRIPTION
    return Issue(
        id=1,
        description=merged[:_SAFE_FALLBACK_DESCRIPTION_MAX_LEN],
        isIT=True,
        readiness="READY",
        missingInfo=[],
        route="TICKET",
        faqKey=None,
        ticketAction=None,
    )
