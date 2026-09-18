"""Versioned global security-policy catalog and marker matching.

Knowledge citations ([S#]) ground enterprise document facts. System-wide
security rules use [POLICY-SEC-*] markers. This module holds only the catalog
and pure text matching so Backoffice can resolve policy IDs without importing
Agent Citation builders.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

POLICY_MARKER_RE = re.compile(r"\[(POLICY-SEC-\d{3})\]")


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


def is_policy_id(value: str) -> bool:
    return value in SECURITY_POLICIES


def policy_ids_in_text(text: str) -> list[str]:
    return list(dict.fromkeys(POLICY_MARKER_RE.findall(text)))


def known_policy_ids_in_text(text: str) -> list[str]:
    return [policy_id for policy_id in policy_ids_in_text(text) if is_policy_id(policy_id)]
