"""Terminal reasons and user copy for knowledge provider outages."""

from __future__ import annotations

# Embed / LLM quota and other transient provider failures — not a knowledge miss.
PROVIDER_BUSY = "PROVIDER_BUSY"

PROVIDER_BUSY_USER_MESSAGE = "目前服務暫時忙碌，請稍後再試。"


def is_provider_busy_terminal(terminal_reason: str | None) -> bool:
    return (terminal_reason or "").strip().upper() == PROVIDER_BUSY


def format_provider_busy_message(
    *,
    issue_description: str | None = None,
    correlation_id: str | None = None,
) -> str:
    """User-facing busy copy; never conflate with knowledge-miss handoff text."""
    lines: list[str] = []
    description = (issue_description or "").strip()
    if description:
        lines.extend([f"問題：{description}", ""])
    lines.append(PROVIDER_BUSY_USER_MESSAGE)
    if correlation_id:
        lines.extend(["", f"追蹤編號：{correlation_id}"])
    return "\n".join(lines)


__all__ = [
    "PROVIDER_BUSY",
    "PROVIDER_BUSY_USER_MESSAGE",
    "format_provider_busy_message",
    "is_provider_busy_terminal",
]
