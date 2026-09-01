"""Request-scoped execution budget and metadata for all model calls."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TypeVar

from .llm_call_counter import LlmCallCounter
from .settings import RagSettings
from .usage_events import (
    UsageEventCollector,
    UsageStatus,
    extract_provider_usage_from_result,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")


class RequestDeadlineExceeded(RuntimeError):
    """Raised when the request deadline has already passed before a call starts."""


class RequestOperationTimedOut(RequestDeadlineExceeded):
    """Raised when an in-flight model call exceeds the remaining request deadline."""


class RequestModelBudgetExceeded(RuntimeError):
    """Raised when the request has insufficient remaining LLM call budget."""


@dataclass
class ExecutionContext:
    correlation_id: str
    request_id: str
    tenant_id: str | None
    team_id: str | None
    environment: str
    idempotency_key: str
    model_budget: int
    usage_collector: UsageEventCollector
    llm_calls: LlmCallCounter = field(default_factory=LlmCallCounter)
    selected_knowledge_backend: str | None = None
    default_model: str | None = None
    deadline: datetime | None = None
    _llm_lock: asyncio.Lock = field(
        default_factory=asyncio.Lock, repr=False, compare=False
    )

    @classmethod
    def from_request(
        cls,
        *,
        settings: RagSettings,
        correlation_id: str,
        request_id: str,
        tenant_id: str | None,
        team_id: str | None = None,
        timeout_seconds: float | None = None,
        knowledge_backend: str | None = None,
    ) -> ExecutionContext:
        timeout = timeout_seconds if timeout_seconds is not None else 30.0
        llm_calls = LlmCallCounter()
        usage_collector = UsageEventCollector(
            environment=settings.deployment_environment,
            request_id=request_id,
            correlation_id=correlation_id,
            tenant_id=tenant_id,
            team_id=team_id,
            knowledge_backend=knowledge_backend,
        )
        return cls(
            correlation_id=correlation_id,
            request_id=request_id,
            tenant_id=tenant_id,
            team_id=team_id,
            environment=settings.deployment_environment,
            idempotency_key=f"{tenant_id or '-'}::{request_id}",
            model_budget=settings.max_llm_calls_per_request,
            usage_collector=usage_collector,
            llm_calls=llm_calls,
            selected_knowledge_backend=knowledge_backend,
            default_model=settings.agent_model or settings.model,
            deadline=datetime.now(UTC) + timedelta(seconds=timeout),
        )

    def remaining_seconds(self) -> float | None:
        if self.deadline is None:
            return None
        return (self.deadline - datetime.now(UTC)).total_seconds()

    def ensure_deadline(self) -> None:
        remaining = self.remaining_seconds()
        if remaining is not None and remaining <= 0:
            raise RequestDeadlineExceeded(
                f"Request deadline exceeded for request_id={self.request_id}"
            )

    def budget_remaining(self) -> int:
        return max(0, self.model_budget - self.llm_calls.count)

    def ensure_budget_slots(self, slots: int = 1) -> None:
        if slots < 1:
            raise ValueError("slots must be at least 1")
        self.ensure_deadline()
        if self.llm_calls.count + slots > self.model_budget:
            raise RequestModelBudgetExceeded(
                f"Insufficient LLM budget for {slots} call(s): "
                f"count={self.llm_calls.count} budget={self.model_budget} "
                f"request_id={self.request_id}"
            )

    def ensure_budget(self) -> None:
        self.ensure_budget_slots(1)

    def record_llm_call(self) -> None:
        self.ensure_budget()
        self.llm_calls.increment()

    async def _await_with_remaining(
        self,
        operation: Callable[[], Awaitable[T]],
        *,
        remaining: float | None,
    ) -> T:
        if remaining is None:
            return await operation()
        if remaining <= 0:
            raise RequestDeadlineExceeded(
                f"Request deadline exceeded for request_id={self.request_id}"
            )
        try:
            return await asyncio.wait_for(operation(), timeout=remaining)
        except TimeoutError as error:
            raise RequestOperationTimedOut(
                f"LLM call timed out for request_id={self.request_id}"
            ) from error

    def _record_usage_event(
        self,
        *,
        component: str,
        status: UsageStatus,
        latency_ms: float,
        result: object | None = None,
        model: str | None = None,
        usage_from_result: Callable[[object], Mapping[str, int | str] | None] | None = None,
    ) -> None:
        usage_patch: dict[str, int | str] = {}
        if result is not None:
            extractor = usage_from_result or extract_provider_usage_from_result
            extracted = extractor(result)
            if extracted:
                usage_patch.update(extracted)

        input_tokens = int(usage_patch.get("input_tokens", 0))
        tool_context_tokens = int(usage_patch.get("tool_context_tokens", 0))
        output_tokens = int(usage_patch.get("output_tokens", 0))
        embedding_tokens = int(usage_patch.get("embedding_tokens", 0))
        usage_source = usage_patch.get("usage_source", "MISSING")
        if usage_source not in {"PROVIDER", "ESTIMATED", "MISSING"}:
            usage_source = "MISSING"
        resolved_model = model or usage_patch.get("model") or self.default_model
        if isinstance(resolved_model, str):
            model_value: str | None = resolved_model
        else:
            model_value = self.default_model

        self.usage_collector.record(
            component=component,
            status=status,
            latency_ms=latency_ms,
            model=model_value,
            input_tokens=input_tokens,
            tool_context_tokens=tool_context_tokens,
            output_tokens=output_tokens,
            embedding_tokens=embedding_tokens,
            usage_source=usage_source,  # type: ignore[arg-type]
        )

    async def run_llm(
        self,
        operation: Callable[[], Awaitable[T]],
        *,
        component: str,
        model: str | None = None,
        usage_from_result: Callable[[object], Mapping[str, int | str] | None] | None = None,
    ) -> T:
        async with self._llm_lock:
            self.ensure_budget()
            self.llm_calls.increment()

        started = time.perf_counter()
        try:
            result = await self._await_with_remaining(
                operation,
                remaining=self.remaining_seconds(),
            )
        except RequestOperationTimedOut:
            latency_ms = (time.perf_counter() - started) * 1000
            self._record_usage_event(
                component=component,
                status="TIMEOUT",
                latency_ms=latency_ms,
                model=model,
            )
            logger.warning(
                "LLM call timed out: component=%s count=%d/%d request_id=%s "
                "correlation_id=%s elapsed_ms=%.1f",
                component,
                self.llm_calls.count,
                self.model_budget,
                self.request_id,
                self.correlation_id,
                latency_ms,
            )
            raise
        except Exception:
            latency_ms = (time.perf_counter() - started) * 1000
            self._record_usage_event(
                component=component,
                status="FAILED",
                latency_ms=latency_ms,
                model=model,
            )
            raise
        else:
            latency_ms = (time.perf_counter() - started) * 1000
            self._record_usage_event(
                component=component,
                status="SUCCESS",
                latency_ms=latency_ms,
                result=result,
                model=model,
                usage_from_result=usage_from_result,
            )
            logger.debug(
                "LLM call completed: component=%s count=%d/%d request_id=%s "
                "correlation_id=%s elapsed_ms=%.1f",
                component,
                self.llm_calls.count,
                self.model_budget,
                self.request_id,
                self.correlation_id,
                latency_ms,
            )
            return result
