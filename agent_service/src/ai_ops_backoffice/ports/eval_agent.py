"""Eval Agent runtime bindings port — AgentWorkflow construction stays in composition."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, runtime_checkable

__all__ = [
    "EvalAgentBindings",
    "configure_eval_agent_bindings",
    "get_eval_agent_bindings",
]

ModelFactory = Callable[[str], Any]


@runtime_checkable
class EvalAgentBindings(Protocol):
    """Agent-backed factories used by Backoffice governance eval modules."""

    def default_model_factory(self, model_id: str) -> Any:
        ...

    def default_eval_model_id(self) -> str:
        ...

    def build_isolated_runtime(
        self,
        *,
        model_factory: ModelFactory | None = None,
        manifest: Any | None = None,
        persona_context: dict[str, Any] | None = None,
        faq_repository: Any = None,
    ) -> Any:
        ...

    def build_turn_executor(self, runtime: Any) -> Any:
        ...

    def build_sandbox_workflow_executor(
        self,
        *,
        model_factory: ModelFactory,
        prompt_resolver: Callable[[str], str | None] | None = None,
        faq_repository: Any = None,
        allowed_models: frozenset[str] | None = None,
    ) -> Callable[[str, Any, Any], dict[str, Any]]:
        ...

    def resolve_candidate_prompt(self, *, template: str, model_id: str) -> Any:
        ...

    def rebind_workflow_models(self, workflow: Any, model: Any) -> None:
        ...

    def build_active_handoff_case(
        self,
        *,
        tenant_id: str,
        conversation_id: str,
        requester_id: str,
        case_id: str,
        session_id: str,
        correlation_id: str,
        created_at: Any,
        session_expires_at: Any,
        retention_expires_at: Any,
    ) -> Any:
        ...

    def build_agent_request(
        self,
        *,
        request_id: str,
        tenant_id: str,
        conversation_id: str,
        teams_user_id: str,
        entra_object_id: str,
        display_name: str,
        email: str,
        groups: list[str],
        text: str,
        correlation_id: str,
    ) -> Any:
        ...

    def build_faq_entry(self, **kwargs: Any) -> Any:
        ...

    def build_citation(self, **kwargs: Any) -> Any:
        ...

    def build_knowledge_result(self, **kwargs: Any) -> Any:
        ...

    def build_ticket(self, **kwargs: Any) -> Any:
        ...


_eval_agent_bindings: EvalAgentBindings | None = None


def configure_eval_agent_bindings(bindings: EvalAgentBindings | None) -> None:
    """Register composition-owned eval Agent bindings for governance eval."""

    global _eval_agent_bindings
    _eval_agent_bindings = bindings


def get_eval_agent_bindings() -> EvalAgentBindings:
    if _eval_agent_bindings is None:
        raise RuntimeError(
            "Eval agent bindings are not configured. Call "
            "configure_eval_agent_bindings from composition."
        )
    return _eval_agent_bindings
