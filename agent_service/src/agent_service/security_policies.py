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

ANSWER_PROMPT_SECURITY_RULES = """\
10. 嚴格遵守資安與敏感資訊原則（全域安全底線，優先於所有情境；必須使用獨立政策標記，不可標成 [S#]）：
    - 政策文件事實只能使用 [S1]/[S2] 等知識來源標記。
    - 全域資安規則只能使用下方政策標記，嚴禁把政策內容歸因到知識文件來源：
      - [POLICY-SEC-001] 全域資料最小化原則：提交畫面或附件時，嚴禁提交與問題無關的個人及敏感資訊；不得宣稱「無須遵守資料最小化」。
      - [POLICY-SEC-002] 絕對機敏資訊禁令：登入密碼、個人憑證密碼、動態驗證碼等嚴禁提供。
      - [POLICY-SEC-003] 安全性設定變更確認原則：關閉 Proxy、變更安全性區域或憑證設定前，須先向權責單位或資訊部門確認。
    - 不確定時確認原則：若使用者不確定資料是否可提交，必須先向權責主管或資訊/資安部門確認。
    - 全域最高性：上述政策高於所有個別小節規範。
    - 當問題問「某來源有無規定 X」時：先說明「該來源沒有規定」，再獨立標示「但系統安全政策要求…… [POLICY-SEC-xxx]」。
    - 不得在回答中輸出測試或佔位網址（例如含有 test、example、pages.dev 等佔位連結），若文件僅提供測試連結，應提醒使用者洽詢 IT 支援窗口或至公司正式入口。
    - 不得在回答中直接暴露內部 IP 位址（如 10.x.x.x、172.16-31.x.x、192.168.x.x）或內部伺服器主機路徑，應以系統名稱或公槽資料夾等功能名稱代稱。
"""


def is_policy_id(value: str) -> bool:
    return value in SECURITY_POLICIES


def policy_ids_in_text(text: str) -> list[str]:
    return list(dict.fromkeys(POLICY_MARKER_RE.findall(text)))


def citation_for_policy(policy_id: str, *, include_evidence: bool = True) -> Citation:
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
    advisories: list[PolicyAdvisory] = []
    for policy_id in policy_ids_in_text(text):
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
        knowledge_ids = [chunk_id for chunk_id in claim.chunkIds if not is_policy_id(chunk_id)]
        if knowledge_ids:
            knowledge_claims.append(claim.model_copy(update={"chunkIds": knowledge_ids}))
        if policy_ids:
            policy_advisories.append(PolicyAdvisory(text=claim.text, policyIds=policy_ids))
    return knowledge_claims, policy_advisories
