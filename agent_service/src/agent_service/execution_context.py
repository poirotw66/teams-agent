"""Request-scoped execution budget and metadata for all model calls."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TypeVar

from .knowledge import LlmCallCounter
from .settings import RagSettings

T = TypeVar("T")


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

    def budget_remaining(self) -> int:
        return max(0, self.model_budget - self.llm_calls.count)

    def ensure_budget(self) -> None:
        if self.llm_calls.count >= self.model_budget:
            raise RuntimeError("LLM call budget exhausted for this request.")

    def record_llm_call(self) -> None:
        self.ensure_budget()
        self.llm_calls.increment()

    async def run_llm(
        self,
        operation: Callable[[], Awaitable[T]],
        *,
        component: str,
    ) -> T:
        self.ensure_budget()
        try:
            return await operation()
        finally:
            self.llm_calls.increment()
            _ = component  # reserved for structured logging/tracing hooks
