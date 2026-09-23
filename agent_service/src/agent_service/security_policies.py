"""Security-policy ID recognition and display stripping helpers.

POLICY-SEC synthetic overlays are outside the knowledge-base answer scope.
Answers must never mint [POLICY-SEC-*] markers or POLICY_ADVISORY citations.
This module still recognizes known policy IDs so hallucinated markers and
legacy claim ids can be stripped, and so display filters can drop leftover
overlay citations.
"""

from __future__ import annotations

import re

from operations_core.security_policies import (
    POLICY_MARKER_RE,
    SECURITY_POLICIES,
    SecurityPolicy,
    is_policy_id,
    known_policy_ids_in_text,
    policy_ids_in_text,
)

from .contracts import Citation, GroundedClaim, PolicyAdvisory

POLICY_SOURCE_TYPE = "POLICY_ADVISORY"
POLICY_VERSION = "v1"

_SECURITY_POLICY_ADVISORY_BLOCK_RE = re.compile(
    r"(?:\n\s*)?>\s*⚠️?\s*\*\*系統資安政策提醒\*\*[^\n]*(?:\n(?!\n)[^\n]*)*",
)
_SECURITY_POLICY_ADVISORY_LINE_RE = re.compile(
    r"(?m)^[^\n]*系統資安政策提醒[^\n]*\n?",
)
_POLICY_SENTENCE_WITH_MARKER_RE = re.compile(
    r"[^。！？\n]*\[POLICY-SEC-\d{3}\][^。！？\n]*[。！？]?",
)

__all__ = [
    "ANSWER_PROMPT_SECURITY_RULES",
    "POLICY_MARKER_RE",
    "POLICY_SOURCE_TYPE",
    "POLICY_VERSION",
    "PROXY_ADVISORY_TEXT",
    "SEC003_APPLICABLE_SCOPE_RE",
    "SECURITY_POLICIES",
    "SecurityPolicy",
    "advisories_from_text",
    "build_answer_prompt_security_rules",
    "citation_for_policy",
    "citations_for_policy_ids",
    "ensure_policy_text_and_id_paired",
    "ensure_visual_security_inventory_caveats",
    "filter_display_citations",
    "is_policy_advisory_citation",
    "is_policy_id",
    "known_policy_ids_in_text",
    "policy_ids_in_text",
    "split_claims_by_provenance",
    "strip_policy_overlay_for_display",
    "strip_unknown_policy_markers",
]

# Retained only so older fixtures / display tests can construct overlay samples
# that must be stripped; never inject into answers.
PROXY_ADVISORY_TEXT = (
    "> ⚠️ **系統資安政策提醒** [POLICY-SEC-003]：此操作涉及安全性、Proxy 或憑證設定變更。"
    "若該裝置是否受企業政策管轄狀態未明，執行前應先向權責單位或 IT 支援窗口確認，"
    "切勿擅自變更或停用安全防護設定。"
)

SEC003_APPLICABLE_SCOPE_RE = re.compile(
    r"(?:Proxy|代理伺服器|憑證設定|變更憑證|忽略憑證|繞過憑證|關閉\s*Proxy|停用\s*Proxy|"
    r"安全性區域|受保護模式|信任的網站|安全等級|"
    r"簽章無效|即使簽章無效|忽略簽章|繞過簽章|憑證錯誤)",
    re.IGNORECASE,
)

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


def ensure_policy_text_and_id_paired(answer: str) -> str:
    """No-op: POLICY overlays are out of knowledge scope and must not be minted."""
    return answer


def ensure_visual_security_inventory_caveats(answer: str) -> str:
    """Keep visual inventory of risky security controls from becoming enablement advice.

    Applies when the answer discusses invalid-signature allow controls. Softens
    normative「應為已勾選」wording and appends missing must-answer caveats.
    Does not mint POLICY-SEC markers.
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
    """Compatibility stub: POLICY overlays are banned from the answer path."""
    return (
        "10. 嚴禁輸出 [POLICY-SEC-*] 或系統資安政策 overlay；"
        "回答只能引用已授權知識內容的 [S#] 標記。"
    )


ANSWER_PROMPT_SECURITY_RULES = build_answer_prompt_security_rules()


def strip_unknown_policy_markers(text: str) -> str:
    """Remove every [POLICY-SEC-*] marker from model output."""
    if not text:
        return text
    return POLICY_MARKER_RE.sub("", text)


def strip_policy_overlay_for_display(answer: str) -> str:
    """Remove policy IDs and system-policy callouts from user-facing text."""
    if not answer:
        return answer
    text = _SECURITY_POLICY_ADVISORY_BLOCK_RE.sub("", answer)
    text = _SECURITY_POLICY_ADVISORY_LINE_RE.sub("", text)
    text = _POLICY_SENTENCE_WITH_MARKER_RE.sub("", text)
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
    return [citation for citation in citations if not is_policy_advisory_citation(citation)]


def citation_for_policy(policy_id: str, *, include_evidence: bool = True) -> Citation:
    """Build a POLICY_ADVISORY citation (test / filter fixtures only)."""
    if policy_id not in SECURITY_POLICIES:
        raise KeyError(f"Unknown security policy id: {policy_id}")
    policy = SECURITY_POLICIES[policy_id]
    evidence = f"[chunkId={policy.policy_id}]\n{policy.body}" if include_evidence else None
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
    """Compatibility no-op: POLICY overlays are out of knowledge scope."""
    del text
    return []


def split_claims_by_provenance(
    claims: list[GroundedClaim],
) -> tuple[list[GroundedClaim], list[PolicyAdvisory]]:
    """Keep knowledge claims only; drop POLICY-SEC claim ids."""
    knowledge_claims: list[GroundedClaim] = []
    for claim in claims:
        knowledge_ids = [
            chunk_id
            for chunk_id in claim.chunkIds
            if not chunk_id.startswith("POLICY-SEC-")
        ]
        if knowledge_ids:
            knowledge_claims.append(claim.model_copy(update={"chunkIds": knowledge_ids}))
    return knowledge_claims, []
