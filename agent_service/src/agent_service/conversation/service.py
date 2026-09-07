"""Conversation policy service."""
from __future__ import annotations

from dataclasses import dataclass

from ..contracts import ConversationContext, ConversationMessage, PendingIssueContext
from ..settings import RagSettings
from .helpers import Clock, ConversationRepository, _utc_now

@dataclass
class _Round:
    """One user turn plus any assistant messages that immediately follow it."""

    messages: list[ConversationMessage]


def _group_into_rounds(messages: list[ConversationMessage]) -> list[_Round]:
    """Group chronologically-ordered messages into rounds (see module doc).

    A round starts at each "user" message and absorbs every following
    message up to (but not including) the next "user" message. Any
    messages preceding the first "user" message (not expected in normal
    operation) form their own leading round so no message is ever dropped
    by grouping.
    """
    rounds: list[_Round] = []
    for message in messages:
        if message.role == "user" or not rounds:
            rounds.append(_Round(messages=[message]))
        else:
            rounds[-1].messages.append(message)
    return rounds


def _trim_to_rounds(
    messages: list[ConversationMessage], max_rounds: int
) -> list[ConversationMessage]:
    """Keep only the most recent ``max_rounds`` rounds, flattened back out."""
    if max_rounds <= 0:
        return []
    rounds = _group_into_rounds(messages)
    kept = rounds[-max_rounds:]
    return [message for round_ in kept for message in round_.messages]


class ConversationService:
    """Owns Conversation POLICY (spec §10.2) so the workflow stays thin.

    - Creates a new conversation when none exists, or the previous one
      exceeded ``settings.conversation_timeout_hours`` (§10.2).
    - Trims history to at most ``settings.max_history_messages`` AND at
      most ``settings.conversation_history_rounds`` round-trips, applying
      both bounds and keeping the most recent messages (see
      ``_trim_to_rounds`` for exactly how a "round" is counted).
    """

    def __init__(
        self,
        repository: ConversationRepository,
        settings: RagSettings,
        clock: Clock = _utc_now,
    ) -> None:
        self._repository = repository
        self._settings = settings
        self._clock = clock

    async def load_or_create(
        self,
        *,
        tenant_id: str | None,
        teams_conversation_id: str,
        teams_user_id: str,
    ) -> ConversationContext:
        existing = await self._repository.find_conversation(
            tenant_id=tenant_id,
            teams_conversation_id=teams_conversation_id,
            teams_user_id=teams_user_id,
            timeout_hours=self._settings.conversation_timeout_hours,
        )
        if existing is not None:
            return existing
        return await self._repository.create_conversation(
            tenant_id=tenant_id,
            teams_conversation_id=teams_conversation_id,
            teams_user_id=teams_user_id,
            timeout_hours=self._settings.conversation_timeout_hours,
        )

    async def record_message(
        self,
        conversation_id: str,
        *,
        role: str,
        text: str,
        request_id: str | None = None,
        correlation_id: str | None = None,
        follow_up_state: str = "NONE",
        pending_issues: list[PendingIssueContext] | None = None,
    ) -> ConversationMessage:
        expected_pending = pending_issues or []
        if request_id:
            messages = await self._repository.get_recent_messages(conversation_id, 10_000)
            existing = next(
                (
                    message
                    for message in reversed(messages)
                    if message.requestId == request_id and message.role == role
                ),
                None,
            )
            if existing is not None:
                user_message_changed = any((
                    existing.text != text,
                    existing.correlationId != correlation_id,
                    existing.followUpState != follow_up_state,
                    existing.pendingIssues != expected_pending,
                ))
                if role == "user" and user_message_changed:
                    raise ValueError("request replay changed persisted conversation message")
                return existing
        message = ConversationMessage(
            role=role,  # type: ignore[arg-type]
            text=text,
            createdAt=self._clock(),
            requestId=request_id,
            correlationId=correlation_id,
            followUpState=follow_up_state,
            pendingIssues=expected_pending,
        )
        await self._repository.save_message(conversation_id, message)
        return message

    async def get_history(self, conversation_id: str) -> list[ConversationMessage]:
        """Return recent history honoring both trimming bounds (spec §10.2)."""
        messages = await self._repository.get_recent_messages(
            conversation_id, self._settings.max_history_messages
        )
        return _trim_to_rounds(messages, self._settings.conversation_history_rounds)
