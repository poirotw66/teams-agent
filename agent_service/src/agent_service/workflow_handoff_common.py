"""Shared helpers for handoff workflow node mixins."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from .contracts import ConversationContext
from .extractor import _is_human_escalation_request
from .handoff import (
    ActorType,
    CaseSummary,
    HandoffCase,
    HandoffEvent,
    HandoffStatus,
)
from .handoff_flow import deterministic_summary
from .workflow_helpers import AgentState

_REVIEW_STATUSES = frozenset(
    {HandoffStatus.SUMMARY_REVIEW, HandoffStatus.AWAITING_SUPPLEMENT}
)


class HandoffCommonOps:
    """Identity, summary, and event helpers shared across handoff node families."""

    async def _append_handoff_event(
        self,
        case: HandoffCase,
        event_type: str,
        actor_type: ActorType,
        actor_id: str | None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        if self.handoff_repository is None:
            return
        await self.handoff_repository.append_event(
            HandoffEvent(
                eventId=str(uuid.uuid4()),
                caseId=case.caseId,
                eventType=event_type,
                actorType=actor_type,
                actorId=actor_id,
                occurredAt=datetime.now(timezone.utc),
                payload=payload or {},
                correlationId=case.correlationId,
                retentionExpiresAt=case.retentionExpiresAt,
            )
        )

    @staticmethod
    def _summary_text(summary: CaseSummary) -> str:
        return deterministic_summary(
            current_message=summary.userNeed,
            issue_descriptions=[summary.issue],
            conversation_highlights=summary.conversationHighlights,
            attempted_solutions=summary.attemptedSolutions,
            now=summary.generatedAt,
        ).render()

    @staticmethod
    def _is_standalone_human_escalation(state: AgentState) -> bool:
        return _is_human_escalation_request(state["request"].message.text)

    @staticmethod
    def _handoff_conversation_turns(conversation: ConversationContext) -> list[str]:
        bounded = conversation.messages[-10:]
        return [f"{message.role}: {message.text}" for message in bounded]

    def _handoff_identity(self, state: AgentState) -> tuple[str, str, str] | None:
        request = state["request"]
        tenant_id = request.conversation.tenantId
        conversation_id = request.conversation.conversationId
        requester_id = request.user.entraObjectId or request.user.teamsUserId
        if not tenant_id or not conversation_id or not requester_id:
            return None
        return tenant_id, conversation_id, requester_id
