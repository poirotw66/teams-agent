"""Invoke LangChain structured output while preserving provider usage metadata.

``with_structured_output(schema).ainvoke`` returns only the parsed Pydantic
object, which drops ``usage_metadata``. Prefer ``include_raw=True`` and attach
usage onto a thin carrier so ``ExecutionContext`` can record PROVIDER tokens.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, TypeVar

T = TypeVar("T")


class StructuredOutputWithUsage:
    """Proxy around a parsed structured object that still exposes usage fields."""

    __slots__ = ("_value", "response_metadata", "usage_metadata")

    def __init__(
        self,
        value: Any,
        *,
        usage_metadata: Any = None,
        response_metadata: Any = None,
    ) -> None:
        object.__setattr__(self, "_value", value)
        object.__setattr__(self, "usage_metadata", usage_metadata)
        object.__setattr__(self, "response_metadata", response_metadata or {})

    @property
    def value(self) -> Any:
        return self._value

    def __getattr__(self, name: str) -> Any:
        return getattr(self._value, name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name in StructuredOutputWithUsage.__slots__:
            object.__setattr__(self, name, value)
            return
        setattr(self._value, name, value)


def attach_provider_usage(parsed: T, raw: object | None) -> T | StructuredOutputWithUsage:
    if parsed is None or raw is None:
        return parsed
    usage_metadata = getattr(raw, "usage_metadata", None)
    response_metadata = getattr(raw, "response_metadata", None)
    if usage_metadata is None and not response_metadata:
        return parsed
    return StructuredOutputWithUsage(
        parsed,
        usage_metadata=usage_metadata,
        response_metadata=response_metadata,
    )


def unwrap_structured_output(result: Any) -> Any:
    if isinstance(result, StructuredOutputWithUsage):
        return result.value
    return result


async def ainvoke_structured(
    model: Any,
    schema: type[T],
    messages: Sequence[Any],
) -> T | StructuredOutputWithUsage:
    """Invoke structured output; preserve provider usage when the model supports it."""
    try:
        runnable = model.with_structured_output(schema, include_raw=True)
    except TypeError:
        runnable = model.with_structured_output(schema)
        return await runnable.ainvoke(list(messages))

    payload = await runnable.ainvoke(list(messages))
    if isinstance(payload, dict) and "parsed" in payload:
        parsed = payload.get("parsed")
        if parsed is None:
            raise ValueError(
                f"structured output parse failed: {payload.get('parsing_error')!r}"
            )
        return attach_provider_usage(parsed, payload.get("raw"))
    return payload


__all__ = [
    "StructuredOutputWithUsage",
    "ainvoke_structured",
    "attach_provider_usage",
    "unwrap_structured_output",
]
