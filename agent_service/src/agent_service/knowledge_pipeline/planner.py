"""Facet query and diagnosis-aspect planning (pure, no I/O)."""

from __future__ import annotations

import re

_FACET_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("申請方式", ("如何申請", "申請方式", "申請步驟")),
    ("核准人", ("核准人", "核准單位", "審核人", "審核單位")),
    ("處理時間", ("處理時間", "多久", "作業時間", "期限")),
    ("必要資料", ("哪些資料", "必要資料", "附件", "欄位")),
    ("限制", ("限制", "不能", "避免", "不得", "未定義")),
)
# Multi-aspect diagnosis questions (e.g. distinguish version / network / settings).
_DIAGNOSIS_FACETS: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    ("版本", ("版本",), ("版本", "-14", "過舊", "升級客戶端", "客戶端版本")),
    ("網路", ("網路",), ("網路", "熱點", "Wi-Fi", "WiFi", "連線是否正常")),
    ("設定", ("設定",), ("設定", "齒輪", "組態", "VPN 設定")),
)
_DIAGNOSIS_ANCHOR_RE = re.compile(
    r"(FortiClient|Outlook|Intune|Teams|AccessFlow|VPN|AD)",
    re.IGNORECASE,
)


def bounded_facet_queries(query: str) -> tuple[str, ...]:
    matched_facets = [
        facet for facet, markers in _FACET_PATTERNS if any(marker in query for marker in markers)
    ]
    if len(matched_facets) >= 2:
        identifier = re.search(r"\b[A-Za-z][A-Za-z0-9._-]*\b", query)
        anchor = identifier.group(0) if identifier else query[:16].rstrip("，,、；;。？?")
        return tuple(f"{anchor} {facet}" for facet in matched_facets[:3])

    diagnosis_facets = requested_diagnosis_facets(query)
    if len(diagnosis_facets) >= 2:
        return tuple(
            f"{_diagnosis_query_anchor(query)} {facet}" for facet in diagnosis_facets[:3]
        )

    m1 = re.search(r"(?:錯誤|error|代碼|code)\s*[:：]?\s*(-?[A-Za-z0-9_]+)", query, re.IGNORECASE)
    if m1:
        code = m1.group(1).strip()
        if code and code not in ("有哪些", "處理", "如何"):
            return (f"錯誤 {code}", code)
    m2 = re.search(r"(-?[A-Za-z0-9_]+)\s*(?:錯誤|error)", query, re.IGNORECASE)
    if m2:
        code = m2.group(1).strip()
        if code and len(code) >= 2:
            return (f"錯誤 {code}", code)
    m3 = re.search(r"[\(（](-?\d{2,6})[\)）]", query)
    if m3:
        code = m3.group(1).strip()
        return (f"錯誤 {code}", code)
    m4 = re.search(r"(?<![A-Za-z0-9])(-\d{2,5}|\d{4,5})(?![A-Za-z0-9])", query)
    if m4:
        code = m4.group(1).strip()
        return (f"錯誤 {code}", code)
    return ()


def requested_diagnosis_facets(query: str) -> list[str]:
    """Return diagnosis facets named in the query when at least two are present."""
    return [
        name
        for name, markers, _evidence in _DIAGNOSIS_FACETS
        if any(marker in query for marker in markers)
    ]


def _diagnosis_query_anchor(query: str) -> str:
    match = _DIAGNOSIS_ANCHOR_RE.search(query)
    if match is not None:
        return match.group(1)
    identifier = re.search(r"\b[A-Za-z][A-Za-z0-9._-]*\b", query)
    if identifier is not None:
        return identifier.group(0)
    return query[:16].rstrip("，,、；;。？?")


def missing_diagnosis_facet_queries(query: str, context: str) -> tuple[str, ...]:
    """Build targeted follow-up searches for diagnosis facets absent from context."""
    requested = requested_diagnosis_facets(query)
    if len(requested) < 2:
        return ()
    context_fold = context.casefold()
    anchor = _diagnosis_query_anchor(query)
    missing: list[str] = []
    for name, _markers, evidence_markers in _DIAGNOSIS_FACETS:
        if name not in requested:
            continue
        if any(marker.casefold() in context_fold for marker in evidence_markers):
            continue
        if name == "版本":
            missing.append(f"{anchor} 錯誤 -14")
        missing.append(f"{anchor} {name}")
    return tuple(list(dict.fromkeys(missing))[:3])
