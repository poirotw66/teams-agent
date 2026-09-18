"""Versioned global security policies with independent provenance.

Knowledge citations ([S#]) must only ground enterprise document facts.
System-wide security rules use [POLICY-SEC-*] markers and POLICY_ADVISORY
citations so judges can verify policy groundedness without falsely attributing
rules to retrieved documents.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .contracts import Citation, GroundedClaim, PolicyAdvisory

POLICY_MARKER_RE = re.compile(r"\[(POLICY-SEC-\d{3})\]")
POLICY_SOURCE_TYPE = "POLICY_ADVISORY"
POLICY_VERSION = "v1"


@dataclass(frozen=True, slots=True)
class SecurityPolicy:
    policy_id: str
    title: str
    summary: str
    body: str


# Stable IDs are part of the evaluation contract; do not renumber casually.
SECURITY_POLICIES: dict[str, SecurityPolicy] = {
    "POLICY-SEC-001": SecurityPolicy(
        policy_id="POLICY-SEC-001",
        title="全域資料最小化原則",
        summary="提交畫面或附件前須避免與問題無關的個人及敏感資訊。",
        body=(
            "全域資料最小化原則：使用者提供畫面截圖或附件時，嚴禁提交與問題或異常無關的個人及敏感資訊。"
            "若畫面包含無關的個人或敏感資訊，不應直接提交，應提醒使用者先行確認處理方式，"
            "不得宣稱或推論「無須遵守資料最小化」。"
        ),
    ),
    "POLICY-SEC-002": SecurityPolicy(
        policy_id="POLICY-SEC-002",
        title="絕對機敏資訊禁令",
        summary="登入密碼、憑證密碼與動態驗證碼嚴禁於任何回報中提供。",
        body=(
            "絕對機敏資訊禁令：登入密碼、個人憑證密碼、動態驗證碼等機敏資訊，"
            "在任何問題回報或諮詢中皆嚴禁於信件、畫面或文字中提供。"
        ),
    ),
    "POLICY-SEC-003": SecurityPolicy(
        policy_id="POLICY-SEC-003",
        title="安全性設定變更確認原則",
        summary="變更 Proxy、憑證或安全性設定前須向權責單位確認。",
        body=(
            "安全性設定變更確認原則：涉及停用安全性設定（如關閉 Proxy、變更安全性區域或憑證設定）時，"
            "若裝置是否受企業管控政策管理尚未確認，必須先向權責單位或資訊部門確認適用性，切勿擅自變更。"
        ),
    ),
}

PROXY_ADVISORY_TEXT = (
    "> ⚠️ **系統資安政策提醒** [POLICY-SEC-003]：此操作涉及安全性、Proxy 或憑證設定變更。"
    "若該裝置是否受企業政策管轄狀態未明，執行前應先向權責單位或 IT 支援窗口確認，"
    "切勿擅自變更或停用安全防護設定。"
)

# Topics that legitimately activate POLICY-SEC-003 (keep in sync with answer sanitize).
SEC003_APPLICABLE_SCOPE_RE = re.compile(
    r"(?:Proxy|代理伺服器|憑證設定|變更憑證|忽略憑證|繞過憑證|關閉\s*Proxy|停用\s*Proxy|"
    r"安全性區域|受保護模式|信任的網站|安全等級|"
    r"簽章無效|即使簽章無效|忽略簽章|繞過簽章|憑證錯誤)",
    re.IGNORECASE,
)

# Bare SEC-003 reminders that must keep the policy ID alongside the wording.
_BARE_SEC003_REMINDER_RE = re.compile(
    r"(?P<clause>"
    r"(?:此外[，,]?\s*)?"
    r"(?:進行任何)?安全性設定變更前[^。\n]{0,40}向權責單位確認"
    r"|變更(?:前|安全性設定前)[^。\n]{0,40}向權責單位確認"
    r"|變更安全性設定前[^。\n]{0,40}確認"
    r"|(?:請先|請務必|建議)?(?:向|洽詢)權責單位確認[^。\n]{0,24}"
    r")(?P<tail>\s*[。.]?)(?!\s*\[POLICY-SEC-003\])",
    re.IGNORECASE,
)


def ensure_policy_text_and_id_paired(answer: str) -> str:
    """Attach policy IDs when in-scope advisory wording lacks a marker.

    Only pairs reminders when the answer already discusses SEC-003 topics
    (Proxy / certificate / invalid signature). Generic hedges alone must not
    mint a POLICY-SEC-003 citation.
    """
    if not answer or "[POLICY-SEC-003]" in answer:
        return answer
    if not SEC003_APPLICABLE_SCOPE_RE.search(answer):
        return answer

    def _attach(match: re.Match[str]) -> str:
        clause = match.group("clause").rstrip("。. ")
        tail = match.group("tail") or "。"
        if not tail.strip():
            tail = "。"
        return f"{clause} [POLICY-SEC-003]{tail}"

    return _BARE_SEC003_REMINDER_RE.sub(_attach, answer)


_VISUAL_SECURITY_CONTROL_RE = re.compile(
    r"即使簽章無效|簽章無效也允許|可見「?即使簽章無效",
    re.IGNORECASE,
)
_VISUAL_LIMIT_MARKERS = (
    "僅為視覺",
    "只代表視覺",
    "畫面僅",
    "僅證明",
    "不得將畫面",
    "不可將畫面",
    "不能將畫面",
    "不得據此作為通用",
    "不可轉為通用",
    "不能視為通用",
    "不得轉成普遍",
    "不得作為通用排障",
    "不得普遍啟用",
)
_MISSING_COMPONENT_MARKERS = (
    "名稱未詳",
    "未提供元件",
    "元件名稱",
    "適用範圍",
    "未提供版本",
    "版本、來源",
    "來源或適用",
)
_VISUAL_SECURITY_INVENTORY_CAVEAT = (
    "文件畫面僅證明該控制項可見且已勾選，不得據此作為通用排障步驟或普遍啟用建議。"
    "來源若未提供元件名稱、版本、來源或適用範圍（例如記載為名稱未詳），"
    "在權責流程確認前不得自行啟用或擴大套用。"
)


def ensure_visual_security_inventory_caveats(answer: str) -> str:
    """Keep visual inventory of risky security controls from becoming enablement advice.

    Applies when the answer discusses invalid-signature allow controls. Softens
    normative「應為已勾選」wording and appends missing must-answer caveats.
    """
    if not answer or not _VISUAL_SECURITY_CONTROL_RE.search(answer):
        return answer
    sanitized = re.sub(r"應為已勾選", "畫面顯示為已勾選", answer)
    sanitized = re.sub(r"該項目應勾選", "該項目在畫面中顯示為已勾選", sanitized)
    has_visual_limit = any(marker in sanitized for marker in _VISUAL_LIMIT_MARKERS)
    has_missing_meta = any(marker in sanitized for marker in _MISSING_COMPONENT_MARKERS)
    if has_visual_limit and has_missing_meta:
        return sanitized
    caveat = _VISUAL_SECURITY_INVENTORY_CAVEAT
    if sanitized.rstrip().endswith(("。", ".", "！", "!")):
        return f"{sanitized.rstrip()}{caveat}"
    return f"{sanitized.rstrip()}。{caveat}"


def build_answer_prompt_security_rules() -> str:
    """Derive prompt Rule 10 from SECURITY_POLICIES so text cannot drift from bodies."""
    policy_bullets = "\n".join(
        f"      - [{policy.policy_id}] {policy.title}：{policy.summary}"
        for policy in SECURITY_POLICIES.values()
    )
    return f"""\
10. 嚴格遵守資安與敏感資訊原則（全域安全底線，優先於所有情境；必須使用獨立政策標記，不可標成 [S#]）：
    - 知識文件事實只能使用 [S1]、[S2] 等知識來源標記。
    - 全域資安規則只能使用下方已定義政策標記，嚴禁把政策內容歸因到知識文件來源：
{policy_bullets}
    - 適用範圍鎖定：僅可引用各政策 summary／body 已涵蓋的事項；不得自行延伸政策適用範圍。
      - 資料能否提交、畫面敏感資訊、資料最小化 → 只可用 [POLICY-SEC-001]。
      - 登入密碼／憑證密碼／動態驗證碼 → 只可用 [POLICY-SEC-002]；不得寫成「任何密碼／所有密碼」。
      - 會議密碼、借用申請表單欄位中的會議用密碼不是 POLICY-SEC-002 禁止對象；不得用政策否定來源要求填寫的會議密碼。
      - Proxy／安全性區域／憑證設定變更前確認 → 只可用 [POLICY-SEC-003]。
      - 嚴禁把「資料能否提交」「正式網址查詢」「一般通報流程」標成 [POLICY-SEC-003]。
      - 嚴禁把「測試連結／佔位網址／非正式連結」標成 [POLICY-SEC-001] 或任何 POLICY-SEC-*。
    - 當問題問「某來源有無規定 X」時：先說明「該來源沒有規定」，再獨立標示「但系統安全政策要求…… [POLICY-SEC-xxx]」（xxx 必須是上方已定義且真正適用的政策）。
    - 不得在回答中輸出測試或佔位網址（例如含有 test、example、pages.dev 等佔位連結），若文件僅提供測試連結，應提醒使用者洽詢 IT 支援窗口或至公司正式入口；此提醒不是安全政策，嚴禁標成 [POLICY-SEC-001]、[POLICY-SEC-002] 或 [POLICY-SEC-003]。
    - 不得在回答中直接暴露內部 IP 位址（如 10.x.x.x、172.16-31.x.x、192.168.x.x）或內部伺服器主機路徑，應以系統名稱或公槽資料夾等功能名稱代稱。
    - 全域最高性：上述已定義政策高於所有個別小節規範。
"""


ANSWER_PROMPT_SECURITY_RULES = build_answer_prompt_security_rules()


def is_policy_id(value: str) -> bool:
    return value in SECURITY_POLICIES


def policy_ids_in_text(text: str) -> list[str]:
    return list(dict.fromkeys(POLICY_MARKER_RE.findall(text)))


def known_policy_ids_in_text(text: str) -> list[str]:
    return [policy_id for policy_id in policy_ids_in_text(text) if is_policy_id(policy_id)]


def strip_unknown_policy_markers(text: str) -> str:
    """Remove unknown [POLICY-SEC-*] markers without failing the whole answer."""

    def _replace(match: re.Match[str]) -> str:
        policy_id = match.group(1)
        return match.group(0) if is_policy_id(policy_id) else ""

    return POLICY_MARKER_RE.sub(_replace, text)


_SECURITY_POLICY_ADVISORY_BLOCK_RE = re.compile(
    r"(?:\n\s*)?>\s*⚠️?\s*\*\*系統資安政策提醒\*\*[^\n]*(?:\n(?!\n)[^\n]*)*",
)
_SECURITY_POLICY_ADVISORY_LINE_RE = re.compile(
    r"(?m)^[^\n]*系統資安政策提醒[^\n]*\n?",
)


def strip_policy_overlay_for_display(answer: str) -> str:
    """Remove policy IDs and system-policy callouts from user-facing text.

    Knowledge steps and ordinary confirmation wording are kept. Internal
    generation, sanitize, claims, and evaluation keep full POLICY markers.
    """
    if not answer:
        return answer
    text = _SECURITY_POLICY_ADVISORY_BLOCK_RE.sub("", answer)
    text = _SECURITY_POLICY_ADVISORY_LINE_RE.sub("", text)
    text = POLICY_MARKER_RE.sub("", text)
    text = re.sub(r"[ \t]+([。．.，,！!？?])", r"\1", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def is_policy_advisory_citation(citation: Citation) -> bool:
    """Return whether a citation is a system security-policy overlay entry."""
    chunk_id = citation.chunkId or ""
    if chunk_id.startswith("POLICY-SEC-") or citation.sourceType == POLICY_SOURCE_TYPE:
        return True
    return bool(re.search(r"POLICY-SEC-\d{3}", citation.title or ""))


def filter_display_citations(citations: list[Citation]) -> list[Citation]:
    """Drop POLICY_ADVISORY citations from user-facing source lists."""
    return [
        citation
        for citation in citations
        if not is_policy_advisory_citation(citation)
    ]


def citation_for_policy(policy_id: str, *, include_evidence: bool = True) -> Citation:
    if policy_id not in SECURITY_POLICIES:
        raise KeyError(f"Unknown security policy id: {policy_id}")
    policy = SECURITY_POLICIES[policy_id]
    evidence = (
        f"[chunkId={policy.policy_id}]\n{policy.body}" if include_evidence else None
    )
    return Citation(
        title=f"{policy.title} ({policy.policy_id})",
        chunkId=policy.policy_id,
        documentId=policy.policy_id,
        versionId=POLICY_VERSION,
        sourceType=POLICY_SOURCE_TYPE,
        evidence=evidence,
        sourceAliases=[policy.policy_id, policy.title],
    )


def citations_for_policy_ids(
    policy_ids: list[str],
    *,
    include_evidence: bool = True,
) -> list[Citation]:
    return [
        citation_for_policy(policy_id, include_evidence=include_evidence)
        for policy_id in policy_ids
        if policy_id in SECURITY_POLICIES
    ]


def advisories_from_text(text: str) -> list[PolicyAdvisory]:
    """Build advisories for known policy markers only; ignore unknown IDs."""
    advisories: list[PolicyAdvisory] = []
    for policy_id in known_policy_ids_in_text(text):
        policy = SECURITY_POLICIES[policy_id]
        advisories.append(
            PolicyAdvisory(
                text=policy.summary,
                policyIds=[policy_id],
            )
        )
    return advisories


def split_claims_by_provenance(
    claims: list[GroundedClaim],
) -> tuple[list[GroundedClaim], list[PolicyAdvisory]]:
    """Split mixed claim chunkIds into knowledge claims and policy advisories."""
    knowledge_claims: list[GroundedClaim] = []
    policy_advisories: list[PolicyAdvisory] = []
    for claim in claims:
        policy_ids = [chunk_id for chunk_id in claim.chunkIds if is_policy_id(chunk_id)]
        # Drop unknown POLICY-SEC-* ids rather than treating them as knowledge chunks.
        knowledge_ids = [
            chunk_id
            for chunk_id in claim.chunkIds
            if not chunk_id.startswith("POLICY-SEC-")
        ]
        if knowledge_ids:
            knowledge_claims.append(claim.model_copy(update={"chunkIds": knowledge_ids}))
        if policy_ids:
            policy_advisories.append(PolicyAdvisory(text=claim.text, policyIds=policy_ids))
    return knowledge_claims, policy_advisories
