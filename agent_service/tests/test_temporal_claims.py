"""Tests for temporal freshness of FAQ body dates vs current status."""

from datetime import date

from agent_service.temporal_claims import (
    annotate_historical_dates_in_text,
    sanitize_temporal_claims,
)


def test_annotate_marks_past_validity_dates_without_hardcoding_one_day() -> None:
    today = date(2026, 9, 18)
    first = annotate_historical_dates_in_text(
        "須向端末組確認授權數。\n有效期至 : 2025-12-12\n",
        evaluated_at=today,
    )
    second = annotate_historical_dates_in_text(
        "須向端末組確認授權數。\n有效期至 : 2024-06-01\n",
        evaluated_at=today,
    )

    assert "2025-12-12【歷史記載日期" in first
    assert "2024-06-01【歷史記載日期" in second
    assert "不得當成使用者目前狀態或現行有效期" in first


def test_annotate_leaves_future_validity_dates_untouched() -> None:
    annotated = annotate_historical_dates_in_text(
        "有效期至 : 2027-03-01",
        evaluated_at=date(2026, 9, 18),
    )
    assert annotated == "有效期至 : 2027-03-01"


def test_sanitize_rewrites_past_validity_as_historical_record() -> None:
    answer = (
        "當 FortiClient 出現未授權訊息時，代表目前 VPN 連線授權數不足 [S1]。"
        "該授權有效期至 **2025-12-12** [S1]。請向端末組與網路組確認。"
    )
    sanitized = sanitize_temporal_claims(answer, evaluated_at=date(2026, 9, 18))

    assert "代表目前 VPN 連線授權數不足" not in sanitized
    assert "文件記載可能表示VPN 連線授權數不足；現況請向權責單位確認" in sanitized
    assert "現行有效期" in sanitized or "歷史條目" in sanitized
    assert "2025-12-12" in sanitized
    assert "端末組" in sanitized


def test_sanitize_same_error_message_with_different_past_date() -> None:
    answer = "該授權有效期至 2024-01-15。請向端末組確認授權數。"
    sanitized = sanitize_temporal_claims(answer, evaluated_at=date(2026, 9, 18))

    assert "文件曾記載" in sanitized
    assert "2024-01-15" in sanitized
    assert "不能當作現行有效期" in sanitized


def test_sanitize_keeps_future_validity_claim() -> None:
    answer = "該授權有效期至 **2027-01-01**。請向端末組確認。"
    sanitized = sanitize_temporal_claims(answer, evaluated_at=date(2026, 9, 18))
    assert sanitized == answer
