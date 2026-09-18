"""Tool-constraint metric helpers for AgentBehaviorScorer."""

from __future__ import annotations

from .models import ToolConstraintsSpec
from .runner_models import MetricResult
from .tool_fixture_models import ToolCallTrace


def build_constraint_metric(
    *,
    version: str,
    metric_id: str,
    passed: bool,
    pass_reason: str,
    fail_reason: str,
) -> MetricResult:
    return MetricResult(
        metric_id=metric_id,
        version=version,
        score=1.0 if passed else 0.0,
        pass_status="PASS" if passed else "FAIL",
        applicability=True,
        reason=pass_reason if passed else fail_reason,
    )


def score_forbidden_tools(
    version: str,
    constraints: ToolConstraintsSpec,
    called_names: list[str],
) -> MetricResult | None:
    if not constraints.forbidden_tools:
        return None
    forbidden_hit = [name for name in called_names if name in constraints.forbidden_tools]
    return build_constraint_metric(
        version=version,
        metric_id="tool.forbidden_tools",
        passed=not forbidden_hit,
        pass_reason="No forbidden tools called",
        fail_reason=f"Called forbidden tool(s): {', '.join(forbidden_hit)}",
    )


def score_allowed_tools(
    version: str,
    constraints: ToolConstraintsSpec,
    called_names: list[str],
) -> MetricResult | None:
    if not constraints.allowed_tools:
        return None
    disallowed = [name for name in called_names if name not in constraints.allowed_tools]
    return build_constraint_metric(
        version=version,
        metric_id="tool.allowed_tools",
        passed=not disallowed,
        pass_reason="All called tools are in allowlist",
        fail_reason=f"Called tool(s) not in allowlist: {', '.join(disallowed)}",
    )


def score_required_tools(
    version: str,
    constraints: ToolConstraintsSpec,
    called_names: list[str],
) -> MetricResult | None:
    if not constraints.required_tools:
        return None
    missing = [name for name in constraints.required_tools if name not in called_names]
    return build_constraint_metric(
        version=version,
        metric_id="tool.required_tools",
        passed=not missing,
        pass_reason="All required tools were called",
        fail_reason=f"Missing required tool(s): {', '.join(missing)}",
    )


def score_allowed_paths(
    version: str,
    constraints: ToolConstraintsSpec,
    called_names: list[str],
) -> MetricResult | None:
    if not constraints.allowed_paths:
        return None
    called_seq = tuple(called_names)
    matched_path = any(called_seq == path for path in constraints.allowed_paths)
    return build_constraint_metric(
        version=version,
        metric_id="tool.allowed_paths",
        passed=matched_path,
        pass_reason="Tool execution sequence matched a valid path",
        fail_reason=f"Tool sequence {list(called_seq)} does not match any allowed paths",
    )


def score_tool_order(
    version: str,
    constraints: ToolConstraintsSpec,
    called_names: list[str],
) -> MetricResult | None:
    if not constraints.tool_order:
        return None
    order_failures: list[str] = []
    for pred, succ in constraints.tool_order:
        if pred in called_names and succ in called_names:
            if called_names.index(pred) > called_names.index(succ):
                order_failures.append(f"'{pred}' must be called before '{succ}'")
    return build_constraint_metric(
        version=version,
        metric_id="tool.order",
        passed=not order_failures,
        pass_reason="Tool call order requirements satisfied",
        fail_reason="; ".join(order_failures),
    )


def score_max_calls(
    version: str,
    constraints: ToolConstraintsSpec,
    tool_calls: tuple[ToolCallTrace, ...],
) -> MetricResult | None:
    if constraints.max_calls is None:
        return None
    within_limit = len(tool_calls) <= constraints.max_calls
    return build_constraint_metric(
        version=version,
        metric_id="tool.max_calls",
        passed=within_limit,
        pass_reason="Tool call count within limit",
        fail_reason=(
            f"Tool call count {len(tool_calls)} exceeded limit {constraints.max_calls}"
        ),
    )


def _parameter_constraint_errors(
    constraints: ToolConstraintsSpec,
    tool_calls: tuple[ToolCallTrace, ...],
) -> list[str]:
    param_errors: list[str] = []
    for constraint_key, expected_val in constraints.parameter_constraints.items():
        target_tool: str | None = None
        param_name = constraint_key
        if "." in constraint_key:
            target_tool, param_name = constraint_key.split(".", 1)

        matched_call = False
        for call in tool_calls:
            if target_tool and call.tool_name != target_tool:
                continue
            if param_name in call.arguments:
                matched_call = True
                actual_val = call.arguments[param_name]
                if actual_val != expected_val:
                    param_errors.append(
                        f"Parameter '{constraint_key}' value mismatch: "
                        f"expected '{expected_val}', got '{actual_val}'"
                    )
                break
        if not matched_call:
            param_errors.append(
                f"Missing required parameter '{constraint_key}' in tool call"
            )
    return param_errors


def score_parameter_constraints(
    version: str,
    constraints: ToolConstraintsSpec,
    tool_calls: tuple[ToolCallTrace, ...],
) -> MetricResult | None:
    if not constraints.parameter_constraints:
        return None
    param_errors = _parameter_constraint_errors(constraints, tool_calls)
    return build_constraint_metric(
        version=version,
        metric_id="tool.parameter_correctness",
        passed=not param_errors,
        pass_reason="All tool parameters satisfied constraints",
        fail_reason="; ".join(param_errors),
    )


def score_max_retries(
    version: str,
    constraints: ToolConstraintsSpec,
    tool_calls: tuple[ToolCallTrace, ...],
) -> MetricResult | None:
    max_retry_failures = [
        f"'{call.tool_name}' retried {call.retry_count} times"
        for call in tool_calls
        if call.retry_count > constraints.max_retries
    ]
    if not max_retry_failures:
        return None
    return MetricResult(
        metric_id="tool.max_retries",
        version=version,
        score=0.0,
        pass_status="FAIL",
        applicability=True,
        reason=(
            f"Exceeded max retries {constraints.max_retries}: "
            f"{'; '.join(max_retry_failures)}"
        ),
    )


def collect_tool_constraint_metrics(
    version: str,
    constraints: ToolConstraintsSpec,
    tool_calls: tuple[ToolCallTrace, ...],
) -> list[MetricResult]:
    called_names = [call.tool_name for call in tool_calls]
    candidates = [
        score_forbidden_tools(version, constraints, called_names),
        score_allowed_tools(version, constraints, called_names),
        score_required_tools(version, constraints, called_names),
        score_allowed_paths(version, constraints, called_names),
        score_tool_order(version, constraints, called_names),
        score_max_calls(version, constraints, tool_calls),
        score_parameter_constraints(version, constraints, tool_calls),
        score_max_retries(version, constraints, tool_calls),
    ]
    return [metric for metric in candidates if metric is not None]
