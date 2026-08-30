"""Request-scoped execution budget and metadata for all model calls."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TypeVar

from .llm_call_counter import LlmCallCounter
from .settings import RagSettings

logger = logging.getLogger(__name__)

T = TypeVar("T")


class RequestDeadlineExceeded(RuntimeError):
    """Raised when the request deadline has already passed before a call starts."""


class RequestOperationTimedOut(RequestDeadlineExceeded):
    """Raised when an in-flight model call exceeds the remaining request deadline."""


@dataclass
class ExecutionContext:
    correlation_id: str
    request_id: str
    tenant_id: str | None
    idempotency_key: str
    model_budget: int
    llm_calls: LlmCallCounter = field(default_factory=LlmCallCounter)
    selected_knowledge_backend: str | None = None
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
        timeout_seconds: float | None = None,
        knowledge_backend: str | None = None,
    ) -> ExecutionContext:
        timeout = timeout_seconds if timeout_seconds is not None else 30.0
        return cls(
            correlation_id=correlation_id,
            request_id=request_id,
            tenant_id=tenant_id,
            idempotency_key=f"{tenant_id or '-'}::{request_id}",
            model_budget=settings.max_llm_calls_per_request,
            selected_knowledge_backend=knowledge_backend,
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

    def ensure_budget(self) -> None:
        self.ensure_deadline()
        if self.llm_calls.count >= self.model_budget:
            raise RuntimeError("LLM call budget exhausted for this request.")

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

    async def run_llm(
        self,
        operation: Callable[[], Awaitable[T]],
        *,
        component: str,
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
            logger.warning(
                "LLM call timed out: component=%s count=%d/%d request_id=%s "
                "correlation_id=%s elapsed_ms=%.1f",
                component,
                self.llm_calls.count,
                self.model_budget,
                self.request_id,
                self.correlation_id,
                (time.perf_counter() - started) * 1000,
            )
            raise
        else:
            logger.debug(
                "LLM call completed: component=%s count=%d/%d request_id=%s "
                "correlation_id=%s elapsed_ms=%.1f",
                component,
                self.llm_calls.count,
                self.model_budget,
                self.request_id,
                self.correlation_id,
                (time.perf_counter() - started) * 1000,
            )
            return result
