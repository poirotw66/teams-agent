"""Sandbox turn helpers for Backoffice eval Agent bindings."""

from __future__ import annotations

from typing import Any

from ai_ops_backoffice.governance_domain.eval_agent_runtime import IsolatedEvalAgentRuntime

__all__ = [
    "_sandbox_history",
    "_tool_calls_from_runtime",
    "_usage_from_runtime",
]


def _sandbox_history(sanitized_input: Any) -> list[dict[str, str]]:
    raw = getattr(sanitized_input, "conversation_history", ()) or ()
    history: list[dict[str, str]] = []
    for item in raw:
        if isinstance(item, dict):
            history.append(
                {
                    "role": str(item.get("role") or "user"),
                    "content": str(item.get("content") or item.get("text") or ""),
                }
            )
    return history


def _append_effect_traces(
    traces: list[dict[str, Any]],
    effects: dict[str, Any],
) -> None:
    for index, (name, value) in enumerate(sorted(effects.items())):
        if value in (None, False, "", "not_applicable"):
            continue
        if isinstance(value, dict):
            arguments = dict(value.get("arguments") or value)
            result = {"value": value.get("result", value), "order": len(traces) + index}
        else:
            arguments = {"effect": name}
            result = {"value": value, "order": len(traces) + index}
        traces.append(
            {
                "call_id": f"effect-{len(traces)}",
                "tool_name": (
                    str(value.get("tool_name"))
                    if isinstance(value, dict) and value.get("tool_name")
                    else f"side_effect.{name}"
                ),
                "arguments": arguments,
                "result": result,
                "duration_ms": float(
                    value.get("duration_ms") if isinstance(value, dict) else 0.0
                ),
                "is_error": bool(value.get("is_error") if isinstance(value, dict) else False),
                "was_intercepted": True,
                "side_effect_blocked": bool(
                    value.get("blocked") if isinstance(value, dict) else False
                ),
                "intercept_reason": "sandbox_observation",
            }
        )


def _tool_calls_from_runtime(
    *,
    observation: Any,
    runtime: IsolatedEvalAgentRuntime,
) -> list[dict[str, Any]]:
    traces: list[dict[str, Any]] = []
    if hasattr(runtime, "consume_tool_trace"):
        traces.extend(list(runtime.consume_tool_trace()))
    for attr in ("ticket_service", "knowledge_service"):
        service = getattr(runtime, attr, None)
        if service is not None and hasattr(service, "consume_tool_calls"):
            traces.extend(service.consume_tool_calls())
    effects = runtime.read_side_effects() if hasattr(runtime, "read_side_effects") else {}
    _append_effect_traces(traces, effects)
    detail = str(getattr(observation, "detail", "") or "")
    route = getattr(observation, "route", None)
    behaviors = sorted(getattr(observation, "observed_behaviors", ()) or ())
    if detail or route or behaviors:
        traces.append(
            {
                "call_id": "workflow-route",
                "tool_name": "agent_workflow.route",
                "arguments": {
                    "route": route,
                    "behaviors": behaviors,
                    "turn_order": len(traces),
                },
                "result": {"detail": detail},
                "duration_ms": 0.0,
                "is_error": False,
                "was_intercepted": False,
                "side_effect_blocked": False,
                "intercept_reason": None,
            }
        )
    return traces


def _usage_from_runtime(
    runtime: IsolatedEvalAgentRuntime,
    *,
    template: str,
    query: str,
    history: list[dict[str, str]],
    answer: str,
) -> tuple[int, int, int, str]:
    usage: dict[str, Any] = {}
    if isinstance(getattr(runtime, "last_inference", None), dict):
        usage = dict(runtime.last_inference.get("usage_metadata") or {})
    input_tokens = int(
        usage.get("input_tokens")
        or usage.get("prompt_tokens")
        or usage.get("promptTokenCount")
        or 0
    )
    output_tokens = int(
        usage.get("output_tokens")
        or usage.get("completion_tokens")
        or usage.get("candidatesTokenCount")
        or 0
    )
    total_tokens = int(
        usage.get("total_tokens")
        or usage.get("totalTokenCount")
        or (input_tokens + output_tokens)
    )
    if total_tokens <= 0:
        history_chars = sum(len(str(item.get("content") or "")) for item in history)
        prompt_chars = len(template) + len(query) + history_chars
        total_tokens = max(1, int((prompt_chars + len(answer)) / 4))
        input_tokens = max(1, int(prompt_chars / 4))
        output_tokens = max(0, total_tokens - input_tokens)
        return input_tokens, output_tokens, total_tokens, "ESTIMATED"
    if input_tokens <= 0 and output_tokens <= 0:
        input_tokens = total_tokens
    return input_tokens, output_tokens, total_tokens, "EXACT"
