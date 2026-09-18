"""Bridge AgentWorkflow turns into governance eval observations.

Wire an :class:`~ai_ops_backoffice.governance_domain.eval_flow.AgentWorkflowFlowHarness`
with this executor when a live (or test-double) Agent stack is available.

Scoring prefers structured ``issueResults`` (resultType / sources) over answer
text heuristics. A knowledge route alone is not treated as a successful answer.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from time import perf_counter
from typing import Any, Protocol

from platform_kernel.eval import FlowObservation

from . import eval_agent_harness_routes as _routes

_answer_leaks_prompt = _routes.answer_leaks_prompt
_infer_route_and_behaviors = _routes.infer_route_and_behaviors
_issue_has_sources = _routes.issue_has_sources
_issue_result_types = _routes.issue_result_types
_looks_like_no_knowledge_answer = _routes.looks_like_no_knowledge_answer

RequestFactory = Callable[[str, list[dict[str, str]] | None], Any]
SideEffectReader = Callable[[], Mapping[str, Any]]
PrepareCase = Callable[..., Awaitable[None]]
NoteTurnResult = Callable[..., None]

_NEGATIVE_ROUTES = frozenset(
    {"GREETING", "NON_IT", "REFUSED", "UNKNOWN", "UNAVAILABLE", "LEAK", "NO_KNOWLEDGE"}
)


class SupportsAgentRespond(Protocol):
    async def respond(self, request: Any) -> Any: ...


def _unavailable(detail: str) -> FlowObservation:
    return FlowObservation(
        route="UNAVAILABLE",
        label="UNAVAILABLE",
        refused_injection=False,
        detail=detail,
        used_template_chars=0,
        model_id_used=None,
    )


async def _read_workflow_answer(
    workflow: SupportsAgentRespond,
    request: Any,
) -> tuple[str, list[Any], Mapping[str, Any] | None]:
    run = getattr(workflow, "run", None)
    state = await run(request) if callable(run) else None
    if isinstance(state, Mapping):
        answer = str(state.get("final_response", "") or "")
        issue_results = list(state.get("issue_results", []) or [])
        return answer, issue_results, state
    response = await workflow.respond(request)
    answer = str(getattr(response, "answer", "") or "")
    issue_results = list(getattr(response, "issueResults", []) or [])
    return answer, issue_results, None


class AgentWorkflowTurnExecutor:
    """Execute candidate-bound turns through ``AgentWorkflow.respond``.

    Formal eval requires both ``apply_candidate`` and ``side_effect_reader``.
    Without repository / tool evidence the harness returns UNAVAILABLE rather
    than inventing success from answer text.
    """

    def __init__(
        self,
        workflow: SupportsAgentRespond,
        *,
        request_factory: RequestFactory,
        apply_candidate: Callable[[str, str], None] | None = None,
        side_effect_reader: SideEffectReader | None = None,
        prepare_case: PrepareCase | None = None,
        note_turn_result: NoteTurnResult | None = None,
    ) -> None:
        self._workflow = workflow
        self._request_factory = request_factory
        self._apply_candidate = apply_candidate
        self._side_effect_reader = side_effect_reader
        self._prepare_case = prepare_case
        self._note_turn_result = note_turn_result

    async def aexecute(
        self,
        *,
        template: str,
        model_id: str,
        text: str,
        history: list[dict[str, str]] | None,
        setup: str | None = None,
    ) -> FlowObservation:
        if self._apply_candidate is None:
            return _unavailable("candidate_binding_required")
        if self._side_effect_reader is None:
            return _unavailable("side_effect_reader_required")
        try:
            self._apply_candidate(template, model_id)
        except Exception as exc:  # noqa: BLE001
            return _unavailable(f"candidate_binding_failed:{type(exc).__name__}:{exc}")
        if self._prepare_case is not None:
            await self._prepare_case(history, setup=setup)
        request = self._request_factory(text, history)
        started_at = perf_counter()
        answer, issue_results, state = await _read_workflow_answer(self._workflow, request)
        latency_ms = (perf_counter() - started_at) * 1000
        if self._note_turn_result is not None:
            self._note_turn_result(text=text, answer=answer, issue_results=issue_results)
        result_types = _issue_result_types(issue_results)
        effects = dict(self._side_effect_reader() or {})
        llm_call_count = _llm_call_count(state, effects)
        route, behaviors = _infer_route_and_behaviors(
            text=text,
            history=history or [],
            answer=answer,
            issue_results=issue_results,
            side_effects=effects,
        )
        return FlowObservation(
            route=route,
            label="NEGATIVE" if route in _NEGATIVE_ROUTES else "POSITIVE",
            refused_injection="refused_injection" in behaviors,
            detail=(
                f"agent_workflow resultTypes={result_types} "
                f"llm_calls={llm_call_count} latency_ms={latency_ms:.1f} "
                f"injection={effects.get('injection_evidence')} "
                f"effects={sorted(k for k, v in effects.items() if v)}"
            ),
            used_template_chars=len(template),
            reply_text=answer,
            observed_behaviors=behaviors,
            model_id_used=model_id,
            llm_call_count=llm_call_count,
            latency_ms=latency_ms,
        )

    def execute(
        self,
        *,
        template: str,
        model_id: str,
        text: str,
        history: list[dict[str, str]] | None,
        setup: str | None = None,
    ) -> FlowObservation:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(
                self.aexecute(
                    template=template,
                    model_id=model_id,
                    text=text,
                    history=history,
                    setup=setup,
                )
            )
        raise RuntimeError(
            "AgentWorkflowTurnExecutor.execute() cannot run inside an event loop; "
            "await aexecute() instead"
        )


def _llm_call_count(
    state: Mapping[str, Any] | None,
    side_effects: Mapping[str, Any],
) -> int | None:
    if state is not None:
        execution_context = state.get("execution_context")
        counter = getattr(execution_context, "llm_calls", None)
        count = getattr(counter, "count", None)
        if isinstance(count, int):
            return count
    observed = side_effects.get("llm_call_count")
    return observed if isinstance(observed, int) else None


# Re-export helpers that unit tests may import from this module.
__all__ = [
    "AgentWorkflowTurnExecutor",
    "_answer_leaks_prompt",
    "_infer_route_and_behaviors",
    "_issue_has_sources",
    "_issue_result_types",
    "_looks_like_no_knowledge_answer",
]
