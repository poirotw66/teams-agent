"""ACL / scenario isolation helpers that are pure (no index I/O)."""

from __future__ import annotations

from agent_service.documents import DocumentChunk
from agent_service.retrieval import SearchResult

_NON_PRODUCTION_TITLE_MARKERS: tuple[str, ...] = (
    "[UX-AUDIT]",
    "[TEST]",
    "UX-AUDIT",
)


def is_non_production_knowledge_chunk(chunk: DocumentChunk) -> bool:
    title = chunk.title or ""
    return any(marker in title for marker in _NON_PRODUCTION_TITLE_MARKERS)


def filter_cross_scenario_chunks(
    query: str,
    results: list[SearchResult],
) -> list[SearchResult]:
    """Drop cross-scenario / cross-audience noise from retrieval candidates."""
    if not results:
        return results

    # Drop informal audit/test docs before any scenario isolation.
    results = [
        result for result in results if not is_non_production_knowledge_chunk(result.chunk)
    ]
    if not results:
        return results

    normalized_query = query.casefold()

    # Check explicit specific product/service intent
    is_webex_query = "webex" in normalized_query
    is_xq_query = "xq" in normalized_query
    is_outlook_query = any(t in normalized_query for t in ("outlook", "郵件", "authenticator"))
    is_phone_query = any(t in normalized_query for t in ("ip話機", "話機", "分機", "轉接"))
    is_ad_query = any(t in normalized_query for t in ("ad", "自助解鎖", "帳號鎖定", "網域"))
    is_vpn_query = any(t in normalized_query for t in ("vpn", "跳板機", "forticlient"))
    is_accessflow_query = any(
        t in normalized_query for t in ("accessflow", "門禁", "打卡", "e點名")
    )
    is_share_drive_query = any(t in normalized_query for t in ("公槽", "共用公槽"))
    is_enterprise_app_query = any(
        term in query
        for term in (
            "企業 App",
            "企業App",
            "企業級APP",
            "企業級 App",
            "來源所述的企業",
        )
    )

    # 1. Topic FAQ scenario isolation
    target_scenario: str | None = None
    if any(
        term in normalized_query
        for term in ("報價", "五檔", "走勢圖", "行情", "k線", "faq-004")
    ):
        target_scenario = "QUOTE"
    elif any(term in normalized_query for term in ("交易", "下單", "委託", "faq-002")):
        target_scenario = "TRADE"
    elif any(term in normalized_query for term in ("帳務", "庫存", "損益", "交割", "faq-003")):
        target_scenario = "ACCOUNTING"
    elif any(
        term in normalized_query for term in ("線上服務", "線上問題", "登入異常", "faq-001")
    ):
        target_scenario = "GENERAL_ONLINE"

    if target_scenario:

        def _chunk_scenario(chunk: DocumentChunk) -> str | None:
            text = f"{chunk.section or ''} {chunk.title} {chunk.content}"
            text_lower = text.lower()
            if "faq-004" in text_lower or "報價問題" in text:
                return "QUOTE"
            if "faq-002" in text_lower or "交易問題" in text:
                return "TRADE"
            if "faq-003" in text_lower or "帳務問題" in text:
                return "ACCOUNTING"
            if "faq-001" in text_lower or "外部客戶線上問題如何回報" in text:
                return "GENERAL_ONLINE"
            return None

        matching_results = [r for r in results if _chunk_scenario(r.chunk) == target_scenario]
        if matching_results:
            results = [
                r for r in results if _chunk_scenario(r.chunk) in (target_scenario, None)
            ]

    # 2. Audience domain isolation: internal IT systems vs external customer FAQ
    # Do not treat "客戶反映" as explicit external FAQ request; internal IT support
    # often handles tickets from clients.
    is_explicit_external_faq_query = any(
        term in normalized_query for term in ("外部客戶", "外部客戶線上問題", "外網交易客")
    )
    is_internal_it_query = (
        is_webex_query
        or is_xq_query
        or is_outlook_query
        or is_phone_query
        or is_ad_query
        or is_vpn_query
        or is_accessflow_query
        or is_share_drive_query
        or is_enterprise_app_query
        or any(
            term in normalized_query
            for term in (
                "同仁",
                "員工",
                "內網",
                "打卡",
                "門禁",
                "派工單",
                "資訊問題",
            )
        )
    )

    if is_internal_it_query and not is_explicit_external_faq_query:

        def _is_external_faq_chunk(r: SearchResult) -> bool:
            # Specific product matches like Webex or XQ are NEVER external customer FAQ!
            c_title_source = f"{r.chunk.title} {r.chunk.source_path or ''}".lower()
            if "webex" in c_title_source or "xq" in c_title_source:
                return False
            return "外部客戶" in r.chunk.title or "外部客戶線上問題" in (
                r.chunk.source_path or ""
            )

        internal_only = [r for r in results if not _is_external_faq_chunk(r)]
        if internal_only:
            results = internal_only
    elif is_explicit_external_faq_query:
        ext_results = [
            r
            for r in results
            if "外部客戶" in r.chunk.title
            or "外部客戶" in (r.chunk.section or "")
            or (is_xq_query and "xq" in f"{r.chunk.title} {r.chunk.content}".lower())
            or (is_webex_query and "webex" in f"{r.chunk.title} {r.chunk.content}".lower())
        ]
        if ext_results:
            results = ext_results

    # 3. Product domain isolation: Outlook vs IP Phone
    if is_outlook_query and not is_phone_query:
        no_phone = [
            r
            for r in results
            if "ip話機" not in r.chunk.title.lower() and "話機" not in r.chunk.title
        ]
        if no_phone:
            results = no_phone
    elif is_phone_query and not is_outlook_query:
        no_outlook = [r for r in results if "outlook" not in r.chunk.title.lower()]
        if no_outlook:
            results = no_outlook

    # 4. Platform domain isolation: iOS vs Android
    if "ios" in normalized_query and "android" not in normalized_query:
        ios_results = [
            r
            for r in results
            if "ios" in r.chunk.title.lower() or "ios" in (r.chunk.section or "").lower()
        ]
        if ios_results:
            results = [r for r in results if "android" not in r.chunk.title.lower()]
    elif "android" in normalized_query and "ios" not in normalized_query:
        android_results = [
            r
            for r in results
            if "android" in r.chunk.title.lower()
            or "android" in (r.chunk.section or "").lower()
        ]
        if android_results:
            results = [r for r in results if "ios" not in r.chunk.title.lower()]

    # 5. Enterprise App trust/profile checks belong to portal/MDM docs, not
    # external customer FAQ or generic AD unlock hits.
    if is_enterprise_app_query:
        preferred = [
            result
            for result in results
            if any(
                marker in f"{result.chunk.title}\n{result.chunk.content}"
                for marker in (
                    "企業級APP",
                    "企業級 App",
                    "CATHAY LIFE",
                )
            )
        ]
        if preferred:
            preferred_ids = {result.chunk.chunk_id for result in preferred}
            results = preferred + [
                result for result in results if result.chunk.chunk_id not in preferred_ids
            ]
        results = [result for result in results if "外部客戶" not in result.chunk.title]

    return results
