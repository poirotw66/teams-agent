"""Tests for structured LLM invoke usage preservation."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from agent_service.structured_invoke import (
    StructuredOutputWithUsage,
    ainvoke_structured,
    attach_provider_usage,
    unwrap_structured_output,
)
from agent_service.usage_event_extract import extract_provider_usage_from_result


class _Parsed:
    def __init__(self, value: str) -> None:
        self.value = value


@pytest.mark.asyncio
async def test_ainvoke_structured_attaches_provider_usage() -> None:
    parsed = _Parsed("ok")
    raw = SimpleNamespace(
        usage_metadata={"input_tokens": 12, "output_tokens": 4, "total_tokens": 16},
        response_metadata={"model_name": "gemini-test"},
    )

    class _Runnable:
        async def ainvoke(self, _messages: list[object]) -> dict[str, object]:
            return {"parsed": parsed, "raw": raw, "parsing_error": None}

    class _Model:
        def with_structured_output(self, _schema: type[object], include_raw: bool = False):
            assert include_raw is True
            return _Runnable()

    result = await ainvoke_structured(_Model(), _Parsed, [])
    assert isinstance(result, StructuredOutputWithUsage)
    assert unwrap_structured_output(result).value == "ok"
    usage = extract_provider_usage_from_result(result)
    assert usage == {
        "input_tokens": 12,
        "output_tokens": 4,
        "usage_source": "PROVIDER",
        "model": "gemini-test",
    }


@pytest.mark.asyncio
async def test_ainvoke_structured_falls_back_without_include_raw() -> None:
    class _Runnable:
        async def ainvoke(self, _messages: list[object]) -> _Parsed:
            return _Parsed("legacy")

    class _Model:
        def with_structured_output(self, _schema: type[object]):
            return _Runnable()

    result = await ainvoke_structured(_Model(), _Parsed, [])
    assert unwrap_structured_output(result).value == "legacy"


def test_attach_provider_usage_proxy_supports_mutation() -> None:
    parsed = _Parsed("before")
    raw = SimpleNamespace(usage_metadata={"input_tokens": 1, "output_tokens": 1})
    wrapped = attach_provider_usage(parsed, raw)
    assert isinstance(wrapped, StructuredOutputWithUsage)
    wrapped.value = "after"
    assert unwrap_structured_output(wrapped).value == "after"
