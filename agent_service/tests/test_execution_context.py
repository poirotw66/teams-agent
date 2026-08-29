from datetime import UTC, datetime, timedelta

import pytest

from agent_service.execution_context import ExecutionContext, RequestDeadlineExceeded
from agent_service.knowledge import LlmCallCounter


def _context(*, deadline: datetime | None = None) -> ExecutionContext:
    return ExecutionContext(
        correlation_id="corr-1",
        request_id="req-1",
        tenant_id="tenant-1",
        idempotency_key="tenant-1::req-1",
        model_budget=3,
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
async def test_run_llm_records_component_and_enforces_deadline() -> None:
    context = _context(deadline=datetime.now(UTC) - timedelta(seconds=1))

    async def _invoke() -> str:
        return "unused"

    with pytest.raises(RequestDeadlineExceeded):
        await context.run_llm(_invoke, component="test_component")

    assert context.llm_calls.count == 0
