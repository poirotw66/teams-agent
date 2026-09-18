"""Query intent detection for cross-scenario candidate filtering."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class QueryIntentFlags:
    normalized_query: str
    is_webex_query: bool
    is_xq_query: bool
    is_outlook_query: bool
    is_phone_query: bool
    is_ad_query: bool
    is_vpn_query: bool
    is_accessflow_query: bool
    is_share_drive_query: bool
    is_enterprise_app_query: bool
    target_scenario: str | None
    is_explicit_external_faq_query: bool
    is_internal_it_query: bool


def detect_query_intent_flags(query: str) -> QueryIntentFlags:
    normalized_query = query.casefold()
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
    return QueryIntentFlags(
        normalized_query=normalized_query,
        is_webex_query=is_webex_query,
        is_xq_query=is_xq_query,
        is_outlook_query=is_outlook_query,
        is_phone_query=is_phone_query,
        is_ad_query=is_ad_query,
        is_vpn_query=is_vpn_query,
        is_accessflow_query=is_accessflow_query,
        is_share_drive_query=is_share_drive_query,
        is_enterprise_app_query=is_enterprise_app_query,
        target_scenario=target_scenario,
        is_explicit_external_faq_query=is_explicit_external_faq_query,
        is_internal_it_query=is_internal_it_query,
    )
