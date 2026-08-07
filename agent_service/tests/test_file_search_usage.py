from dataclasses import dataclass

import pytest

from agent_service.file_search_usage import (
    FileSearchUsage,
    estimate_cost,
    extract_usage,
    indexing_cost,
    log_fields,
)


@dataclass
class _FakeUsageMetadata:
    prompt_token_count: object = None
    tool_use_prompt_token_count: object = None
    candidates_token_count: object = None
    total_token_count: object = None


@dataclass
class _FakeResponse:
    usage_metadata: object = None


# --- extract_usage -------------------------------------------------------


def test_extract_usage_matches_measured_probe() -> None:
    response = _FakeResponse(
        usage_metadata=_FakeUsageMetadata(
            prompt_token_count=16,
            tool_use_prompt_token_count=2004,
            candidates_token_count=426,
            total_token_count=2446,
        )
    )

    usage = extract_usage(response)

    assert usage.prompt_tokens == 16
    assert usage.tool_use_prompt_tokens == 2004
    assert usage.candidates_tokens == 426
    assert usage.total_tokens == 2446
    # Input tokens MUST include tool_use_prompt_token_count — the retrieved
    # document content — or cost is understated by ~99% (16 vs 2020).
    assert usage.input_tokens == 2020
    assert usage.output_tokens == 426


def test_extract_usage_missing_usage_metadata_degrades_to_zero() -> None:
    usage = extract_usage(_FakeResponse(usage_metadata=None))

    assert usage == FileSearchUsage(0, 0, 0, 0)


def test_extract_usage_none_fields_degrade_to_zero() -> None:
    response = _FakeResponse(
        usage_metadata=_FakeUsageMetadata(
            prompt_token_count=None,
            tool_use_prompt_token_count=None,
            candidates_token_count=None,
            total_token_count=None,
        )
    )

    usage = extract_usage(response)

    assert usage == FileSearchUsage(0, 0, 0, 0)


def test_extract_usage_missing_attributes_entirely_does_not_raise() -> None:
    class _Empty:
        pass

    usage = extract_usage(_Empty())

    assert usage == FileSearchUsage(0, 0, 0, 0)


def test_extract_usage_derives_total_when_missing() -> None:
    response = _FakeResponse(
        usage_metadata=_FakeUsageMetadata(
            prompt_token_count=16,
            tool_use_prompt_token_count=2004,
            candidates_token_count=426,
            total_token_count=None,
        )
    )

    usage = extract_usage(response)

    assert usage.total_tokens == 2446


def test_extract_usage_never_raises_on_garbage_values() -> None:
    response = _FakeResponse(
        usage_metadata=_FakeUsageMetadata(
            prompt_token_count="not-a-number",
            tool_use_prompt_token_count=object(),
            candidates_token_count=[],
            total_token_count=None,
        )
    )

    usage = extract_usage(response)

    assert usage == FileSearchUsage(0, 0, 0, 0)


# --- estimate_cost ---------------------------------------------------------


def test_estimate_cost_matches_measured_probe_dollar_figure() -> None:
    usage = FileSearchUsage(
        prompt_tokens=16,
        tool_use_prompt_tokens=2004,
        candidates_tokens=426,
        total_tokens=2446,
    )

    cost = estimate_cost(usage, "gemini-3.5-flash-lite")

    assert cost == pytest.approx(0.001671, abs=1e-6)


def test_estimate_cost_unknown_model_reports_no_cost() -> None:
    usage = FileSearchUsage(16, 2004, 426, 2446)

    cost = estimate_cost(usage, "totally-unknown-model")

    assert cost is None


def test_estimate_cost_zero_usage_is_zero() -> None:
    usage = FileSearchUsage(0, 0, 0, 0)

    cost = estimate_cost(usage, "gemini-3.5-flash-lite")

    assert cost == 0.0


# --- indexing_cost -----------------------------------------------------------


def test_indexing_cost_matches_measured_corpus() -> None:
    """~9,665 tokens is the measured size of data/sources/ (19 documents).

    Priced at usage.py's gemini-embedding-2 rate of $0.20/1M input tokens.
    Note the File Search guide's prose quotes $0.15/1M, but the pricing table
    lists that rate for gemini-embedding-001; gemini-embedding-2 text input
    is $0.20/1M (verified against ai.google.dev 2026-08-07).
    """
    cost = indexing_cost(9_665)

    assert cost == pytest.approx(9_665 * 0.20 / 1_000_000, rel=1e-9)


def test_indexing_cost_unknown_model_returns_none() -> None:
    assert indexing_cost(1_000, model="no-such-embedding-model") is None


def test_indexing_cost_zero_tokens_is_zero() -> None:
    assert indexing_cost(0) == 0.0


def test_indexing_cost_negative_tokens_is_zero() -> None:
    assert indexing_cost(-5) == 0.0


# --- log_fields --------------------------------------------------------------


def test_log_fields_shape_matches_usage_py_convention() -> None:
    usage = FileSearchUsage(16, 2004, 426, 2446)

    fields = log_fields(usage, "gemini-3.5-flash-lite")

    assert fields["model"] == "gemini-3.5-flash-lite"
    assert fields["input_tokens"] == 2020
    assert fields["output_tokens"] == 426
    assert fields["total_tokens"] == 2446
    assert fields["estimated_cost_usd"] == pytest.approx(0.001671, abs=1e-6)


def test_log_fields_unknown_model_cost_is_none() -> None:
    usage = FileSearchUsage(16, 2004, 426, 2446)

    fields = log_fields(usage, "totally-unknown-model")

    assert fields["estimated_cost_usd"] is None
