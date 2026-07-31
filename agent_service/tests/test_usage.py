import pytest

from agent_service.usage import (
    build_usage_report,
    estimate_cost_usd,
    estimate_text_tokens,
    normalize_model_name,
)


def test_normalize_model_name_strips_provider_prefix() -> None:
    assert normalize_model_name("google_genai:gemini-3.5-flash-lite") == (
        "gemini-3.5-flash-lite"
    )
    assert normalize_model_name("models/gemini-embedding-2") == "gemini-embedding-2"


def test_estimate_text_tokens_counts_cjk_and_latin() -> None:
    assert estimate_text_tokens("VPN密碼") == 3
    assert estimate_text_tokens("") == 0
    assert estimate_text_tokens("hello") == 2


def test_estimate_cost_usd_for_known_flash_lite() -> None:
    cost = estimate_cost_usd("gemini-3.5-flash-lite", input_tokens=1_000_000, output_tokens=1_000_000)

    assert cost == 0.30 + 2.50


def test_build_usage_report_sums_llm_and_embedding() -> None:
    report = build_usage_report(
        {
            "gemini-3.5-flash-lite": {
                "input_tokens": 1000,
                "output_tokens": 200,
                "total_tokens": 1200,
            }
        },
        embedding_tokens=50,
        embedding_model="google_genai:gemini-embedding-2",
    )

    assert report.input_tokens == 1050
    assert report.output_tokens == 200
    assert report.total_tokens == 1250
    assert report.embedding_tokens == 50
    assert report.estimated_cost_usd is not None
    assert report.estimated_cost_usd == pytest.approx(
        (1000 * 0.30 + 200 * 2.50 + 50 * 0.20) / 1_000_000
    )
    assert report.log_fields()["estimated_cost_usd"] == round(
        report.estimated_cost_usd, 8
    )


def test_build_usage_report_marks_unknown_model_cost_unavailable() -> None:
    report = build_usage_report(
        {"custom-mystery-model": {"input_tokens": 10, "output_tokens": 5}}
    )

    assert report.total_tokens == 15
    assert report.estimated_cost_usd is None
