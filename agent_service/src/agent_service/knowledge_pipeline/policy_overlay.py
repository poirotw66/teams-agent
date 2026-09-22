"""Security policy advisory helpers applied after answer generation (pure)."""

from __future__ import annotations

import re

from agent_service.contracts import PolicyAdvisory
from agent_service.security_policies import (
    PROXY_ADVISORY_TEXT,
    SEC003_APPLICABLE_SCOPE_RE,
    ensure_policy_text_and_id_paired,
    ensure_visual_security_inventory_caveats,
)

from .grounding import prune_uncited_material_sentences

_PLACEHOLDER_URL_PATTERN = re.compile(
    r"https?://(?:[a-zA-Z0-9_-]+\.)*(?:pages\.dev|example\.com|test[a-zA-Z0-9_-]*\.[a-z]+)[^\s)\]]*"
    r"|https?://[^\s)\]]*(?:Sorry\.Only\.For\.TEST|test-vpn)[^\s)\]]*",
    re.IGNORECASE,
)
_INTERNAL_UNC_PATTERN = re.compile(
    r"\\\\(?:10\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])|192\.168)\.\d{1,3}\.\d{1,3}[^\s)\]]*"
)
_INTERNAL_URL_PATTERN = re.compile(
    r"https?://(?:10\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])|192\.168)\.\d{1,3}\.\d{1,3}(?::\d+)?[^\s)\]]*"
)
_INTERNAL_IP_PATTERN = re.compile(
    r"\b(?:10\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])|192\.168)\.\d{1,3}\.\d{1,3}\b"
)
_PROXY_DISABLE_PATTERN = re.compile(
    r"(?:(?:關閉|停用).{0,12}(?:Proxy|代理伺服器)|(?:Proxy|代理伺服器).{0,12}(?:關閉|停用))",
    re.IGNORECASE,
)
_CERT_BYPASS_PATTERN = re.compile(
    r"(?:(?:忽略|略過|繞過|停用|關閉|取消).{0,12}(?:憑證|證書|簽章|安全警告|安全檢查)|"
    r"(?:憑證|證書|簽章).{0,12}(?:忽略|略過|繞過|停用|關閉|失效繼續)|"
    r"即使簽章無效|簽章無效也允許|簽章無效也(?:可|能)?執行)",
    re.IGNORECASE,
)
_IE_SECURITY_LOWERING_PATTERN = re.compile(
    r"(?:(?:降低|調低|放寬|停用|關閉).{0,12}(?:安全性|受保護模式|安全等級|保護模式)|"
    r"(?:將網址|新增至|加入).{0,12}(?:信任的網站|信任網站))",
    re.IGNORECASE,
)
_SEC001_APPLICABLE_SCOPE_RE = re.compile(
    r"(?:畫面|截圖|附件|敏感資訊|資料最小化|個人及敏感|與問題無關的個人)",
    re.IGNORECASE,
)
_SEC003_APPLICABLE_SCOPE_RE = SEC003_APPLICABLE_SCOPE_RE
_TEST_LINK_POLICY_SENTENCE_RE = re.compile(
    r"(?:此外[，,]?\s*)?(?:請注意)?(?:文件中的)?(?:測試連結|佔位(?:用途|網址|連結)|"
    r"非正式連結|正式網址)[^。\n]*\[POLICY-SEC-\d{3}\][。.]?",
    re.IGNORECASE,
)
# IP-phone style keys use [0]/[電話號碼]; keep [S#] from looking like another key.
_KEY_BRACKET_CITATION_RE = re.compile(
    r"(按\s*\[[^\]]+\])\s*(\[S\d+\])",
    re.IGNORECASE,
)
_OVERBROAD_SEC002_BAN_RE = re.compile(
    r"(?:並?[，,]?\s*)?(?:嚴禁|不得)[^。\n]*?(?:任何密碼|所有密碼)[^。\n]*?\[POLICY-SEC-002\][。.]?",
    re.IGNORECASE,
)
_PRECISE_SEC002_ADVISORY = "嚴禁於回報中提供登入密碼、憑證密碼與動態驗證碼 [POLICY-SEC-002]。"
_SECURITY_POLICY_ADVISORY = f"\n\n{PROXY_ADVISORY_TEXT}"
# Model may wrap evidence URLs in markdown links but keep code-span backticks or
# Chinese fullwidth parentheses: [label](https://x`) / [label](https://x）)
_MARKDOWN_LINK_HREF_RE = re.compile(
    r"\[([^\]]*)\]\s*[（(]\s*`*(https?://[^)\s`（）]+)`*\s*[）)]",
    re.IGNORECASE,
)
_CODE_SPAN_URL_RE = re.compile(r"`(https?://[^`\s]+)`")


def repair_answer_markdown_links(answer: str) -> str:
    """Normalize broken markdown links so hrefs stay clickable.

    Common generation failures:
    - stray code-span backticks around the URL
    - fullwidth ``（）`` used instead of ASCII ``()`` to close the link
    - FAQ-style code spans `` `https://...` `` that render as non-clickable text
    """
    if not answer:
        return answer
    repaired = _MARKDOWN_LINK_HREF_RE.sub(r"[\1](\2)", answer)
    return _CODE_SPAN_URL_RE.sub(r"[\1](\1)", repaired)


def merge_policy_advisories(*groups: list[PolicyAdvisory]) -> list[PolicyAdvisory]:
    merged: list[PolicyAdvisory] = []
    seen: set[tuple[str, ...]] = set()
    for group in groups:
        for advisory in group:
            key = tuple(advisory.policyIds)
            if key in seen:
                continue
            seen.add(key)
            merged.append(advisory)
    return merged


def sanitize_answer_security(answer: str, *, evidence_text: str = "") -> str:
    """Redact unsafe content while preserving grounded placeholder URLs.

    URLs that appear verbatim in authorized evidence may be test/placeholder
    links (for example AD self-unlock). Those must stay so the answer can
    still guide users to the documented self-service page. Invented or
    ungrounded placeholder URLs continue to be replaced.
    """
    evidence_blob = evidence_text or ""

    def _replace_placeholder_url(match: re.Match[str]) -> str:
        url = match.group(0)
        if url and url in evidence_blob:
            return url
        return "來源僅包含測試連結，目前無法提供正式網址（請洽詢 IT 支援窗口）"

    # 0. Repair broken markdown links before URL redaction runs on href text.
    sanitized = repair_answer_markdown_links(answer)
    # 1. Replace ungrounded placeholder/test URLs with formal portal guidance
    sanitized = _PLACEHOLDER_URL_PATTERN.sub(_replace_placeholder_url, sanitized)
    # 2. Redact internal UNC paths and internal IPs
    sanitized = _INTERNAL_UNC_PATTERN.sub("內部公槽資料夾", sanitized)
    sanitized = _INTERNAL_URL_PATTERN.sub("內部系統伺服器路徑", sanitized)
    sanitized = _INTERNAL_IP_PATTERN.sub("內部伺服器位址", sanitized)
    # 3. Security-sensitive bypass / lowering needs POLICY-SEC-003 text+ID.
    # Keyword hedges like「權責單位」alone are not enough without the marker.
    needs_advisory = bool(
        _PROXY_DISABLE_PATTERN.search(sanitized)
        or _CERT_BYPASS_PATTERN.search(sanitized)
        or _IE_SECURITY_LOWERING_PATTERN.search(sanitized)
    )
    if needs_advisory and "[POLICY-SEC-003]" not in sanitized:
        sanitized = ensure_policy_text_and_id_paired(sanitized)
    if needs_advisory and "[POLICY-SEC-003]" not in sanitized:
        sanitized = f"{sanitized}{_SECURITY_POLICY_ADVISORY}"
    # 4. Drop fabricated test-link "policy" sentences (not any POLICY-SEC scope).
    sanitized = _TEST_LINK_POLICY_SENTENCE_RE.sub("", sanitized)
    # 4b. Separate citation markers from UI key brackets (QB-055).
    sanitized = _KEY_BRACKET_CITATION_RE.sub(r"\1。\2", sanitized)
    # 4c. SEC-002 must not ban "any password" (QB-052: conflicts with 會議密碼 fields).
    if _OVERBROAD_SEC002_BAN_RE.search(sanitized):
        sanitized = _OVERBROAD_SEC002_BAN_RE.sub(_PRECISE_SEC002_ADVISORY, sanitized)
    # 5. POLICY-SEC-001 may only remain when the answer discusses its scope.
    if "[POLICY-SEC-001]" in sanitized and not _SEC001_APPLICABLE_SCOPE_RE.search(sanitized):
        sanitized = sanitized.replace("[POLICY-SEC-001]", "")
    # 6. POLICY-SEC-003 may only remain when the answer discusses its scope.
    if "[POLICY-SEC-003]" in sanitized and not _SEC003_APPLICABLE_SCOPE_RE.search(sanitized):
        sanitized = sanitized.replace("[POLICY-SEC-003]", "")
    sanitized = re.sub(r"[ \t]{2,}", " ", sanitized)
    sanitized = re.sub(r"[。]{2,}", "。", sanitized)
    # Pair bare policy wording with IDs before pruning uncited policy prose.
    sanitized = ensure_policy_text_and_id_paired(sanitized)
    sanitized = ensure_visual_security_inventory_caveats(sanitized)
    # Marker stripping can leave uncited policy prose; prune again.
    sanitized = prune_uncited_material_sentences(sanitized.strip())
    # Unpack inline numbered steps that were merged on a single line
    sanitized = re.sub(
        r"(?<!\n)(?:([：:。；;!?！？])\s*|(\s+))(\d+)\.\s+",
        r"\1\n\3. ",
        sanitized,
    )
    return sanitized.strip()
