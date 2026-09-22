"""Isolation filters applied after query intent detection."""

from __future__ import annotations

from agent_service.documents import DocumentChunk
from agent_service.retrieval import SearchResult

from .candidate_policy_intents import QueryIntentFlags
from .selector import query_asks_for_comparison


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


def apply_scenario_isolation(
    results: list[SearchResult],
    target_scenario: str | None,
) -> list[SearchResult]:
    if not target_scenario:
        return results
    matching_results = [r for r in results if _chunk_scenario(r.chunk) == target_scenario]
    if not matching_results:
        return results
    return [r for r in results if _chunk_scenario(r.chunk) in (target_scenario, None)]


def _is_external_faq_chunk(result: SearchResult) -> bool:
    title_source = f"{result.chunk.title} {result.chunk.source_path or ''}".lower()
    if "webex" in title_source or "xq" in title_source:
        return False
    return "外部客戶" in result.chunk.title or "外部客戶線上問題" in (
        result.chunk.source_path or ""
    )


def apply_audience_isolation(
    results: list[SearchResult],
    intent: QueryIntentFlags,
) -> list[SearchResult]:
    if intent.is_internal_it_query and not intent.is_explicit_external_faq_query:
        internal_only = [r for r in results if not _is_external_faq_chunk(r)]
        return internal_only if internal_only else results
    # Comparison queries that mention 外部客戶 still need the internal sibling doc.
    if intent.is_explicit_external_faq_query and not query_asks_for_comparison(
        intent.normalized_query
    ):
        ext_results = [
            r
            for r in results
            if "外部客戶" in r.chunk.title
            or "外部客戶" in (r.chunk.section or "")
            or (intent.is_xq_query and "xq" in f"{r.chunk.title} {r.chunk.content}".lower())
            or (
                intent.is_webex_query
                and "webex" in f"{r.chunk.title} {r.chunk.content}".lower()
            )
        ]
        return ext_results if ext_results else results
    return results


def apply_product_isolation(
    results: list[SearchResult],
    intent: QueryIntentFlags,
) -> list[SearchResult]:
    if intent.is_outlook_query and not intent.is_phone_query:
        no_phone = [
            r
            for r in results
            if "ip話機" not in r.chunk.title.lower() and "話機" not in r.chunk.title
        ]
        return no_phone if no_phone else results
    if intent.is_phone_query and not intent.is_outlook_query:
        no_outlook = [r for r in results if "outlook" not in r.chunk.title.lower()]
        return no_outlook if no_outlook else results
    return results


def _mentions_ios_platform(normalized: str) -> bool:
    return any(token in normalized for token in ("ios", "iphone", "蘋果"))


def _mentions_android_platform(normalized: str) -> bool:
    return any(token in normalized for token in ("android", "安卓"))


def _rejects_android_platform(normalized: str) -> bool:
    """True when Android is framed as the wrong/non-applicable handbook."""
    return any(
        marker in normalized
        for marker in (
            "為何不能",
            "不能直接套用",
            "不能套用",
            "不要套用",
            "不要用 android",
            "不要用安卓",
            "而非 android",
            "不是 android",
            "而非安卓",
            "不是安卓",
        )
    )


def _rejects_ios_platform(normalized: str) -> bool:
    return any(
        marker in normalized
        for marker in (
            "不能直接套用 ios",
            "不能套用 ios",
            "不要套用 ios",
            "不要用 ios",
            "不要用 iphone",
            "不要用蘋果",
            "而非 ios",
            "不是 ios",
            "而非 iphone",
            "不是 iphone",
        )
    )


def _is_ios_handbook(result: SearchResult) -> bool:
    text = f"{result.chunk.title} {result.chunk.section or ''}".lower()
    return any(token in text for token in ("ios", "iphone", "蘋果"))


def _is_android_handbook(result: SearchResult) -> bool:
    text = f"{result.chunk.title} {result.chunk.section or ''}".lower()
    return any(token in text for token in ("android", "安卓"))


def apply_platform_isolation(
    results: list[SearchResult],
    intent: QueryIntentFlags,
) -> list[SearchResult]:
    """Prefer the query's platform handbook; drop the rejected sibling when cued.

    ``iPhone`` must count as iOS so contrast queries like「為何不能套用 Android」
    do not isolate to the Android manual and drop the matching iOS handbook.
    True side-by-side comparisons (both platforms, no rejection) keep both.
    """
    normalized = intent.normalized_query
    mentions_ios = _mentions_ios_platform(normalized)
    mentions_android = _mentions_android_platform(normalized)

    if mentions_ios and not mentions_android:
        ios_results = [result for result in results if _is_ios_handbook(result)]
        if ios_results:
            return [result for result in results if not _is_android_handbook(result)]
    elif mentions_android and not mentions_ios:
        android_results = [result for result in results if _is_android_handbook(result)]
        if android_results:
            return [result for result in results if not _is_ios_handbook(result)]
    elif mentions_ios and mentions_android:
        rejects_android = _rejects_android_platform(normalized)
        rejects_ios = _rejects_ios_platform(normalized)
        if rejects_android and not rejects_ios:
            ios_results = [result for result in results if _is_ios_handbook(result)]
            if ios_results:
                return [result for result in results if not _is_android_handbook(result)]
        if rejects_ios and not rejects_android:
            android_results = [result for result in results if _is_android_handbook(result)]
            if android_results:
                return [result for result in results if not _is_ios_handbook(result)]
    return results


def apply_enterprise_app_boost(
    results: list[SearchResult],
    intent: QueryIntentFlags,
) -> list[SearchResult]:
    if not intent.is_enterprise_app_query:
        return results
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
    return [result for result in results if "外部客戶" not in result.chunk.title]
