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


def apply_platform_isolation(
    results: list[SearchResult],
    intent: QueryIntentFlags,
) -> list[SearchResult]:
    normalized = intent.normalized_query
    if "ios" in normalized and "android" not in normalized:
        ios_results = [
            r
            for r in results
            if "ios" in r.chunk.title.lower() or "ios" in (r.chunk.section or "").lower()
        ]
        if ios_results:
            return [r for r in results if "android" not in r.chunk.title.lower()]
    elif "android" in normalized and "ios" not in normalized:
        android_results = [
            r
            for r in results
            if "android" in r.chunk.title.lower()
            or "android" in (r.chunk.section or "").lower()
        ]
        if android_results:
            return [r for r in results if "ios" not in r.chunk.title.lower()]
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
