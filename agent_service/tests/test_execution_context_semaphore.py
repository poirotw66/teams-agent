"""Concurrency tests for request-local LLM semaphore."""

from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

from agent_service.execution_context import ExecutionContext, RequestDeadlineExceeded
from agent_service.settings import RagSettings


def _settings(**overrides: object) -> RagSettings:
    return replace(RagSettings.from_env(), **overrides)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_request_semaphore_limits_concurrent_llm_calls() -> None:
    settings = _settings(
        max_concurrent_llm_calls_per_request=2,
        max_llm_calls_per_request=20,
        request_deadline_seconds=30.0,
    )
    context = ExecutionContext.from_request(
        settings=settings,
        correlation_id="sem-1",
        request_id="sem-1",
        tenant_id="test",
    )
    active = 0
    peak = 0
    lock = asyncio.Lock()

    async def fake_call() -> str:
        nonlocal active, peak
        async with lock:
            active += 1
            peak = max(peak, active)
        await asyncio.sleep(0.05)
        async with lock:
            active -= 1
        return "ok"

    results = await asyncio.gather(
        *(
            context.run_llm(fake_call, component="knowledge_answer")
            for _ in range(6)
        )
    )
    assert results == ["ok"] * 6
    assert peak <= 2


@pytest.mark.asyncio
async def test_provider_failure_releases_semaphore() -> None:
    settings = _settings(max_concurrent_llm_calls_per_request=1)
    context = ExecutionContext.from_request(
        settings=settings,
        correlation_id="sem-2",
        request_id="sem-2",
        tenant_id="test",
    )

    async def boom() -> str:
        raise RuntimeError("provider down")

    with pytest.raises(RuntimeError, match="provider down"):
        await context.run_llm(boom, component="knowledge_answer")

    async def ok() -> str:
        return "recovered"

    assert await context.run_llm(ok, component="knowledge_answer") == "recovered"


@pytest.mark.asyncio
async def test_cancellation_releases_semaphore_permit() -> None:
    settings = _settings(max_concurrent_llm_calls_per_request=1)
    context = ExecutionContext.from_request(
        settings=settings,
        correlation_id="sem-cancel",
        request_id="sem-cancel",
        tenant_id="test",
    )
    started = asyncio.Event()

    async def blocked() -> str:
        started.set()
        await asyncio.sleep(10.0)
        return "done"

    task = asyncio.create_task(context.run_llm(blocked, component="knowledge_answer"))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    async def ok() -> str:
        return "recovered"

    assert await asyncio.wait_for(
        context.run_llm(ok, component="knowledge_answer"),
        timeout=1.0,
    ) == "recovered"


@pytest.mark.asyncio
async def test_nested_run_llm_does_not_deadlock() -> None:
    settings = _settings(
        max_concurrent_llm_calls_per_request=1,
        max_llm_calls_per_request=10,
    )
    context = ExecutionContext.from_request(
        settings=settings,
        correlation_id="sem-nested",
        request_id="sem-nested",
        tenant_id="test",
    )

    async def inner() -> str:
        return "inner"

    async def outer() -> str:
        nested = await context.run_llm(inner, component="knowledge_claim_repair")
        return f"outer:{nested}"

    assert await asyncio.wait_for(
        context.run_llm(outer, component="knowledge_answer"),
        timeout=1.0,
    ) == "outer:inner"


@pytest.mark.asyncio
async def test_deadline_while_waiting_for_semaphore() -> None:
    settings = _settings(
        max_concurrent_llm_calls_per_request=1,
        request_deadline_seconds=0.05,
    )
    context = ExecutionContext.from_request(
        settings=settings,
        correlation_id="sem-3",
        request_id="sem-3",
        tenant_id="test",
        timeout_seconds=0.05,
    )

    async def hold() -> str:
        await asyncio.sleep(0.2)
        return "held"

    task = asyncio.create_task(context.run_llm(hold, component="knowledge_answer"))
    await asyncio.sleep(0.01)

    async def waiter() -> str:
        return "late"

    with pytest.raises(RequestDeadlineExceeded):
        await context.run_llm(waiter, component="knowledge_answer")
    with pytest.raises(RequestDeadlineExceeded):
        await task
