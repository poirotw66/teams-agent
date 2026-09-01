import pytest

from agent_service.file_search_usage import FileSearchUsage
from agent_service.usage_events import (
    UsageEventCollector,
    build_request_cost_summary,
    derive_request_outcome,
    extract_file_search_usage_from_result,
    infer_provider,
)


class _FakeUsageMetadata:
    def __init__(self, **kwargs: int) -> None:
        for key, value in kwargs.items():
            setattr(self, key, value)


class _FakeResponse:
    def __init__(self, usage_metadata: object | None) -> None:
        self.usage_metadata = usage_metadata


def test_infer_provider_maps_gemini_and_openai() -> None:
    assert infer_provider("gemini-2.5-flash") == "google"
    assert infer_provider("gpt-4o-mini") == "openai"


def test_extract_file_search_usage_from_result_sums_tool_context() -> None:
    response = _FakeResponse(
        _FakeUsageMetadata(
            prompt_token_count=16,
            tool_use_prompt_token_count=2004,
            candidates_token_count=426,
        )
    )

    usage = extract_file_search_usage_from_result(response)

    assert usage == {
        "input_tokens": 16,
        "tool_context_tokens": 2004,
        "output_tokens": 426,
        "usage_source": "PROVIDER",
    }


def test_collector_unknown_model_does_not_report_zero_cost() -> None:
    collector = UsageEventCollector(
        environment="test",
        request_id="req-1",
        correlation_id="corr-1",
        tenant_id="tenant-1",
        team_id="team-1",
        knowledge_backend="HYBRID",
    )

    event = collector.record(
        component="knowledge_generate",
        status="SUCCESS",
        latency_ms=12.3,
        model="custom-mystery-model",
        input_tokens=100,
        output_tokens=20,
        usage_source="PROVIDER",
    )

    assert event.estimated_cost_usd is None


def test_collector_record_file_search_includes_tool_context_cost() -> None:
    collector = UsageEventCollector(
        environment="test",
        request_id="req-1",
        correlation_id="corr-1",
        tenant_id="tenant-1",
        team_id=None,
        knowledge_backend="GEMINI_FILE_SEARCH",
    )
    usage = FileSearchUsage(
        prompt_tokens=16,
        tool_use_prompt_tokens=2004,
        candidates_tokens=426,
        total_tokens=2446,
    )

    event = collector.record_file_search(
        component="gemini_file_search",
        model="gemini-2.5-flash",
        usage=usage,
        status="SUCCESS",
        latency_ms=250.0,
    )

    assert event.tool_context_tokens == 2004
    assert event.estimated_cost_usd == pytest.approx(
        (2020 * 0.30 + 426 * 2.50) / 1_000_000
    )


def test_build_request_cost_summary_merges_file_search_tokens() -> None:
    collector = UsageEventCollector(
        environment="poc",
        request_id="req-2",
        correlation_id="corr-2",
        tenant_id="tenant-2",
        team_id="team-2",
        knowledge_backend="GEMINI_FILE_SEARCH",
    )
    collector.record_file_search(
        component="gemini_file_search",
        model="gemini-2.5-flash",
        usage=FileSearchUsage(
            prompt_tokens=10,
            tool_use_prompt_tokens=100,
            candidates_tokens=20,
            total_tokens=130,
        ),
        status="SUCCESS",
        latency_ms=100.0,
    )

    summary = build_request_cost_summary(
        collector,
        langchain_usage={
            "gemini-3.5-flash-lite": {
                "input_tokens": 50,
                "output_tokens": 10,
                "total_tokens": 60,
            }
        },
        outcome="knowledge_hit",
        elapsed_ms=500.0,
        llm_call_count=2,
    )

    assert summary.input_tokens == 160
    assert summary.output_tokens == 30
    assert summary.event_count == 1
    assert summary.outcome == "knowledge_hit"


def test_derive_request_outcome_prefers_handoff() -> None:
    outcome = derive_request_outcome(
        {
            "handoff_handled": True,
            "issue_results": [],
        }
    )

    assert outcome == "handoff"
