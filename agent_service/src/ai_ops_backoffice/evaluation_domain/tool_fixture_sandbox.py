"""Sandbox execution helpers for tool fixture mock responses."""

from __future__ import annotations

import uuid
from typing import Any, Protocol

from .tool_fixture_models import MockResponseSpec, ToolCallTrace, ToolFixture, ToolFixtureVersion

__all__ = [
    "SIDE_EFFECT_TOOLS",
    "ToolFixtureLookup",
    "execute_sandbox_tool",
]

SIDE_EFFECT_TOOLS: frozenset[str] = frozenset(
    {
        "send_email",
        "email_dispatch",
        "send_notification",
        "create_ticket",
        "dispatch_ticket",
        "update_production_db",
        "delete_record",
        "production_write",
    }
)

_INTERCEPT_REASON = "Production write/ticket/email side effects are blocked in sandbox"


class ToolFixtureLookup(Protocol):
    """Minimal repository surface required by sandbox execution."""

    def get_fixture(self, fixture_id: str) -> ToolFixture | None: ...

    def list_fixtures(self, tenant_id: str | None = None) -> list[ToolFixture]: ...

    def get_version(self, fixture_id: str, version: int) -> ToolFixtureVersion | None: ...


def _resolve_fixture(
    repository: ToolFixtureLookup,
    *,
    fixture_id: str | None,
    tool_name: str,
) -> ToolFixture | None:
    if fixture_id:
        return repository.get_fixture(fixture_id)
    if not tool_name:
        return None
    for fixture in repository.list_fixtures():
        if fixture.tool_name == tool_name:
            return fixture
    return None


def _is_side_effect(tool_name: str, version: ToolFixtureVersion | None) -> bool:
    return tool_name in SIDE_EFFECT_TOOLS or (version is not None and version.is_mutation)


def _intercept_trace(call_id: str, tool_name: str, arguments: dict[str, Any]) -> ToolCallTrace:
    return ToolCallTrace(
        call_id=call_id,
        tool_name=tool_name,
        arguments=dict(arguments),
        result={
            "status": "INTERCEPTED",
            "side_effect_blocked": True,
            "message": "Production side effect blocked in sandbox",
        },
        is_error=False,
        was_intercepted=True,
        side_effect_blocked=True,
        intercept_reason=_INTERCEPT_REASON,
    )


def _missing_fixture_trace(
    call_id: str,
    tool_name: str,
    arguments: dict[str, Any],
) -> ToolCallTrace:
    message = f"Tool fixture for '{tool_name}' not found"
    return ToolCallTrace(
        call_id=call_id,
        tool_name=tool_name,
        arguments=dict(arguments),
        result={"status": "error", "error": message},
        is_error=True,
        error_message=message,
    )


def _match_mock_response(
    mocks: tuple[MockResponseSpec, ...],
    arguments: dict[str, Any],
) -> MockResponseSpec | None:
    for mock in mocks:
        if not mock.match_parameters:
            continue
        if all(arguments.get(key) == expected for key, expected in mock.match_parameters.items()):
            return mock
    return None


def _special_case_mock_trace(
    *,
    call_id: str,
    tool_name: str,
    arguments: dict[str, Any],
    matched_mock: MockResponseSpec,
    attempt: int,
) -> ToolCallTrace | None:
    """Return a simulated failure/edge-case trace, or None for a normal payload."""
    if matched_mock.retry_after_failures > 0 and attempt <= matched_mock.retry_after_failures:
        return ToolCallTrace(
            call_id=call_id,
            tool_name=tool_name,
            arguments=dict(arguments),
            result={"status": "error", "attempt": attempt},
            duration_ms=matched_mock.latency_ms,
            is_error=True,
            error_message=f"Simulated transient failure on attempt {attempt}",
            retry_count=attempt,
        )
    if matched_mock.is_timeout:
        return ToolCallTrace(
            call_id=call_id,
            tool_name=tool_name,
            arguments=dict(arguments),
            result={"status": "error", "error_code": "TIMEOUT"},
            duration_ms=matched_mock.latency_ms or 5000.0,
            is_error=True,
            error_message="Tool execution timed out",
        )
    if matched_mock.is_permission_denied:
        return ToolCallTrace(
            call_id=call_id,
            tool_name=tool_name,
            arguments=dict(arguments),
            result={"status": "error", "error_code": "PERMISSION_DENIED"},
            duration_ms=matched_mock.latency_ms,
            is_error=True,
            error_message="Permission denied by ACL policy",
        )
    if matched_mock.is_empty:
        return ToolCallTrace(
            call_id=call_id,
            tool_name=tool_name,
            arguments=dict(arguments),
            result={"status": "EMPTY", "results": [], "data": {}},
            duration_ms=matched_mock.latency_ms,
            is_error=False,
        )
    if matched_mock.is_contradictory:
        return ToolCallTrace(
            call_id=call_id,
            tool_name=tool_name,
            arguments=dict(arguments),
            result={"status": "RESOLVED", "outcome": "FAILED", "conflict": True},
            duration_ms=matched_mock.latency_ms,
            is_error=False,
        )
    if matched_mock.is_error:
        return ToolCallTrace(
            call_id=call_id,
            tool_name=tool_name,
            arguments=dict(arguments),
            result={
                "status": "error",
                "error_code": matched_mock.error_status or "TOOL_EXECUTION_ERROR",
            },
            duration_ms=matched_mock.latency_ms,
            is_error=True,
            error_message=matched_mock.error_message or "Simulated tool failure",
        )
    return None


def _trace_from_matched_mock(
    *,
    call_id: str,
    tool_name: str,
    arguments: dict[str, Any],
    matched_mock: MockResponseSpec,
    attempt: int,
    is_side_effect: bool,
) -> ToolCallTrace:
    special = _special_case_mock_trace(
        call_id=call_id,
        tool_name=tool_name,
        arguments=arguments,
        matched_mock=matched_mock,
        attempt=attempt,
    )
    if special is not None:
        return special

    payload = dict(matched_mock.response_payload)
    if is_side_effect:
        payload["side_effect_blocked"] = True
        payload["was_intercepted"] = True
    return ToolCallTrace(
        call_id=call_id,
        tool_name=tool_name,
        arguments=dict(arguments),
        result=payload,
        duration_ms=matched_mock.latency_ms,
        is_error=False,
        was_intercepted=is_side_effect,
        side_effect_blocked=is_side_effect,
        intercept_reason=_INTERCEPT_REASON if is_side_effect else None,
    )


def _default_response_trace(
    *,
    call_id: str,
    tool_name: str,
    arguments: dict[str, Any],
    version: ToolFixtureVersion,
    is_side_effect: bool,
) -> ToolCallTrace:
    default_payload = dict(version.default_response or {"status": "success", "data": {}})
    if is_side_effect:
        default_payload["side_effect_blocked"] = True
        default_payload["was_intercepted"] = True
    return ToolCallTrace(
        call_id=call_id,
        tool_name=tool_name,
        arguments=dict(arguments),
        result=default_payload,
        is_error=False,
        was_intercepted=is_side_effect,
        side_effect_blocked=is_side_effect,
        intercept_reason=_INTERCEPT_REASON if is_side_effect else None,
    )


def execute_sandbox_tool(
    repository: ToolFixtureLookup,
    *,
    tool_name: str,
    arguments: dict[str, Any],
    fixture_id: str | None = None,
    version: int | None = None,
    call_id: str | None = None,
    attempt: int = 1,
) -> ToolCallTrace:
    """Execute a tool within the safe evaluation sandbox.

    Guarantees that production write, email dispatch, and ticket creation
    side effects are strictly intercepted and neutralized (F04-T2).
    """
    actual_call_id = call_id or f"call_{uuid.uuid4().hex[:8]}"
    fixture = _resolve_fixture(repository, fixture_id=fixture_id, tool_name=tool_name)
    target_version = version or (fixture.current_version if fixture else 1)
    version_record = repository.get_version(fixture.fixture_id, target_version) if fixture else None
    resolved_tool_name = (
        version_record.tool_name if version_record and version_record.tool_name else tool_name
    )
    is_side_effect = _is_side_effect(resolved_tool_name, version_record)

    if not version_record:
        if is_side_effect:
            return _intercept_trace(actual_call_id, resolved_tool_name, arguments)
        return _missing_fixture_trace(actual_call_id, resolved_tool_name, arguments)

    matched_mock = _match_mock_response(version_record.mock_responses, arguments)
    if matched_mock is not None:
        return _trace_from_matched_mock(
            call_id=actual_call_id,
            tool_name=resolved_tool_name,
            arguments=arguments,
            matched_mock=matched_mock,
            attempt=attempt,
            is_side_effect=is_side_effect,
        )
    return _default_response_trace(
        call_id=actual_call_id,
        tool_name=resolved_tool_name,
        arguments=arguments,
        version=version_record,
        is_side_effect=is_side_effect,
    )
