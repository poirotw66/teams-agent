"""Governance resolution port for Agent prompt/model/flag runtime."""

from __future__ import annotations

from typing import Any, Protocol


class GovernanceProvider(Protocol):
    """Narrow read surface Agent needs from the governance control plane."""

    def peek_runtime_prompt(
        self,
        prompt_id: str,
        *,
        tenant_id: str | None = None,
        conversation_id: str | None = None,
        environment: str | None = None,
    ) -> Any:
        ...

    def peek_runtime_model(self, config_id: str) -> Any:
        ...

    def peek_model_schedule(self, config_id: str) -> Any:
        ...

    def peek_runtime_flag(
        self,
        flag_id: str,
        *,
        environment: str | None = None,
    ) -> Any:
        ...
