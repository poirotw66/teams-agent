import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from agent_service.execution_context import (
    ExecutionContext,
    RequestDeadlineExceeded,
    RequestOperationTimedOut,
)
from agent_service.knowledge import LlmCallCounter


def _context(*, deadline: datetime | None = None, model_budget: int = 3) -> ExecutionContext:
    return ExecutionContext(
        correlation_id="corr-1",
        request_id="req-1",
        tenant_id="tenant-1",
        idempotency_key="tenant-1::req-1",
        model_budget=model_budget,
        llm_calls=LlmCallCounter(),
        deadline=deadline,
    )


def test_remaining_seconds_is_none_without_deadline() -> None:
    assert _context().remaining_seconds() is None


def test_ensure_deadline_raises_when_expired() -> None:
    context = _context(deadline=datetime.now(UTC) - timedelta(seconds=1))

    with pytest.raises(RequestDeadlineExceeded):
        context.ensure_deadline()


def test_ensure_budget_checks_deadline_before_llm_budget() -> None:
    context = _context(deadline=datetime.now(UTC) - timedelta(seconds=1))
    context.llm_calls.count = 0

    with pytest.raises(RequestDeadlineExceeded):
        context.ensure_budget()


@pytest.mark.asyncio
async def test_run_llm_rejects_expired_deadline_before_operation() -> None:
    context = _context(deadline=datetime.now(UTC) - timedelta(seconds=1))

    async def _invoke() -> str:
        return "unused"

    with pytest.raises(RequestDeadlineExceeded):
        await context.run_llm(_invoke, component="test_component")

    assert context.llm_calls.count == 0


@pytest.mark.asyncio
async def test_run_llm_times_out_slow_operation() -> None:
    context = _context(deadline=datetime.now(UTC) + timedelta(milliseconds=50))

    async def slow() -> str:
        await asyncio.sleep(0.2)
        return "finished"

    with pytest.raises(RequestOperationTimedOut):
        await context.run_llm(slow, component="slow_component")

    assert context.llm_calls.count == 1


@pytest.mark.asyncio
async def test_run_llm_reserves_budget_before_slow_operation_completes() -> None:
    context = _context(
        deadline=datetime.now(UTC) + timedelta(seconds=1),
        model_budget=1,
    )
    started = asyncio.Event()

    async def slow() -> str:
        started.set()
        await asyncio.sleep(0.05)
        return "done"

    async def second_call() -> None:
        await started.wait()

        async def noop() -> None:
            return None

        with pytest.raises(RuntimeError, match="budget exhausted"):
            await context.run_llm(noop, component="second")

    first = asyncio.create_task(context.run_llm(slow, component="first"))
    second = asyncio.create_task(second_call())
    assert await first == "done"
    await second
    assert context.llm_calls.count == 1
