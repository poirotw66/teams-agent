"""Channel scope helpers for operational event emission."""

from __future__ import annotations


def channel_scope(channel: str) -> str:
    if channel in {"playground", "msteams-web"}:
        return "playground"
    if channel.endswith("-channel"):
        return "channel"
    return "personal"


def is_teams_channel(channel: str) -> bool:
    normalized = channel.strip().lower()
    return normalized.startswith("msteams") or normalized in {"teams", "teams-bot"}


# Stable alias used by chat_support and historical imports.
_channel_scope = channel_scope
