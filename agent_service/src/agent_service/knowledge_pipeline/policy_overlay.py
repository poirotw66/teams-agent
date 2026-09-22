"""Post-generation answer cleanup (pure): redact unsafe URLs/IPs and strip POLICY overlay.

POLICY-SEC synthetic overlays are outside the knowledge-base scope. This module
must never mint [POLICY-SEC-*] markers or policy advisories; it only strips
hallucinated policy text and keeps non-policy sanitization.
"""

from __future__ import annotations

import re

from agent_service.contracts import PolicyAdvisory
from agent_service.security_policies import ensure_visual_security_inventory_caveats

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
_POLICY_MARKER_RE = re.compile(r"\[POLICY-SEC-\d{3}\]")
_SECURITY_POLICY_ADVISORY_BLOCK_RE = re.compile(
    r"(?:\n\s*)?>\s*⚠️?\s*\*\*系統資安政策提醒\*\*[^\n]*(?:\n(?!\n)[^\n]*)*",
)
_SECURITY_POLICY_ADVISORY_LINE_RE = re.compile(
    r"(?m)^[^\n]*系統資安政策提醒[^\n]*\n?",
)
_POLICY_SENTENCE_WITH_MARKER_RE = re.compile(
    r"[^。！？\n]*\[POLICY-SEC-\d{3}\][^。！？\n]*[。！？]?",
)
# IP-phone style keys use [0]/[電話號碼]; keep [S#] from looking like another key.
_KEY_BRACKET_CITATION_RE = re.compile(
    r"(按\s*\[[^\]]+\])\s*(\[S\d+\])",
    re.IGNORECASE,
)
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


def strip_policy_markers_and_callouts(answer: str) -> str:
    """Remove hallucinated POLICY-SEC markers and system-policy callout blocks."""
    if not answer:
        return answer
    text = _SECURITY_POLICY_ADVISORY_BLOCK_RE.sub("", answer)
    text = _SECURITY_POLICY_ADVISORY_LINE_RE.sub("", text)
    text = _POLICY_SENTENCE_WITH_MARKER_RE.sub("", text)
    text = _POLICY_MARKER_RE.sub("", text)
    text = re.sub(r"[ \t]+([。．.，,！!？?])", r"\1", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def merge_policy_advisories(*groups: list[PolicyAdvisory]) -> list[PolicyAdvisory]:
    """Compatibility no-op: POLICY overlays are out of knowledge scope."""
    return []


def sanitize_answer_security(answer: str, *, evidence_text: str = "") -> str:
    """Redact unsafe content and strip POLICY overlay; never mint POLICY markers.

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

    sanitized = repair_answer_markdown_links(answer)
    sanitized = _PLACEHOLDER_URL_PATTERN.sub(_replace_placeholder_url, sanitized)
    sanitized = _INTERNAL_UNC_PATTERN.sub("內部公槽資料夾", sanitized)
    sanitized = _INTERNAL_URL_PATTERN.sub("內部系統伺服器路徑", sanitized)
    sanitized = _INTERNAL_IP_PATTERN.sub("內部伺服器位址", sanitized)
    sanitized = strip_policy_markers_and_callouts(sanitized)
    sanitized = _KEY_BRACKET_CITATION_RE.sub(r"\1。\2", sanitized)
    sanitized = ensure_visual_security_inventory_caveats(sanitized)
    sanitized = prune_uncited_material_sentences(sanitized)
    sanitized = re.sub(r"[ \t]{2,}", " ", sanitized)
    sanitized = re.sub(r"[。]{2,}", "。", sanitized)
    sanitized = re.sub(
        r"(?<!\n)(?:([：:。；;!?！？])\s*|(\s+))(\d+)\.\s+",
        r"\1\n\3. ",
        sanitized,
    )
    return sanitized.strip()
