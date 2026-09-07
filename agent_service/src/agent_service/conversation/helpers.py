"""Shared conversation helpers and repository protocol."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Protocol

from ..contracts import ConversationContext, ConversationMessage

Clock = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _conversation_key(
    *, tenant_id: str | None, teams_conversation_id: str, teams_user_id: str
) -> str:
    """Build the isolation key for a conversation (spec §18.4).

    Different users and different Teams conversations must never share
    context, so the key is the composite of all three identifiers. A
    missing tenant id (e.g. local/dev) is normalized to ``"-"`` so it still
    participates in the key deterministically.
    """
    tenant = tenant_id or "-"
    return f"{tenant}::{teams_conversation_id}::{teams_user_id}"


class ConversationRepository(Protocol):
    """Storage interface for conversation context (spec §10.3, §3.2).

    Implementations MUST NOT be assumed to be MongoDB or any other specific
    product (spec §10.3). All methods are async so a future networked
    implementation (e.g. a managed DB) is a drop-in replacement.
    """

    async def find_conversation(
        self,
        *,
        tenant_id: str | None,
        teams_conversation_id: str,
        teams_user_id: str,
        timeout_hours: int,
    ) -> ConversationContext | None:
        """Return the ACTIVE conversation for this key, or None.

        "Active" means: a conversation exists for this
        (tenant_id, teams_conversation_id, teams_user_id) key AND its
        ``lastActivityAt`` is within ``timeout_hours`` of now (spec §10.2).
        A timed-out conversation is treated as if it does not exist -- the
        caller (``ConversationService.load_or_create``) is responsible for
        creating a fresh one.
        """
        ...

    async def create_conversation(
        self,
        *,
        tenant_id: str | None,
        teams_conversation_id: str,
        teams_user_id: str,
        timeout_hours: int = 24,
    ) -> ConversationContext:
        """Create and persist a brand-new conversation for this key.

        The new conversation becomes the "active" one for the key -- a
        subsequent ``find_conversation`` call (before timeout) returns it.
        """
        ...

    async def save_message(self, conversation_id: str, message: ConversationMessage) -> None:
        """Append ``message`` to the conversation and bump ``lastActivityAt``."""
        ...

    async def get_recent_messages(
        self, conversation_id: str, limit: int
    ) -> list[ConversationMessage]:
        """Return up to ``limit`` most recent messages, oldest-first.

        i.e. if there are more than ``limit`` messages, the oldest ones are
        dropped and the result is the tail of the conversation in normal
        chronological (ascending ``createdAt``) order -- ready to feed
        directly into an LLM prompt without needing to reverse it.
        """
        ...


def _is_timed_out(context: ConversationContext, timeout_hours: int, now: datetime) -> bool:
    return now - context.lastActivityAt > timedelta(hours=timeout_hours)
