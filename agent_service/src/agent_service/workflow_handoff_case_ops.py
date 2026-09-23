"""Case lifecycle operations for the handoff workflow subgraph."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from .confirmation import TicketIntent
from .extractor import HUMAN_ESCALATION_ISSUE_DESCRIPTION
from .handoff import (
    ActiveHandoffCaseExistsError,
    ActorType,
    CaseSummary,
    HandoffCase,
    HandoffStatus,
)
from .handoff_flow import (
    DEMO_STARTED_MESSAGE,
    HandoffResumeReason,
    agentic_supplement_summary,
    deterministic_summary,
    offer_message,
)
from .provider_status import is_provider_busy_terminal
from .workflow_handoff_common import HandoffCommonOps
from .workflow_helpers import AgentState


class HandoffCaseOps(HandoffCommonOps):
    """Create, cancel, supplement, and evaluate handoff cases."""

    async def _promote_case_to_demo(
        self,
        case: HandoffCase,
        requester_id: str,
    ) -> HandoffCase:
        confirmed = case.summary.model_copy(
            update={
                "confirmedAt": datetime.now(timezone.utc),
                "confirmedBy": requester_id,
                "version": case.summary.version + 1,
            }
        )
        case = await self.handoff_repository.update_summary(
            case.caseId, confirmed, case.version
        )
        active = await self.handoff_repository.transition(
            case.caseId,
            case.status,
            HandoffStatus.DEMO_ACTIVE,
            case.version,
        )
        await self._append_handoff_event(
            active,
            "handoff.accepted",
            ActorType.USER,
            requester_id,
            {"fromStatus": case.status.value, "toStatus": "DEMO_ACTIVE"},
        )
        return active

    async def _start_standalone_human_demo(self, state: AgentState) -> dict:
        case = await self._create_handoff_offer(
            state,
            [HUMAN_ESCALATION_ISSUE_DESCRIPTION],
        )
        if case is None:
            return {"handoff_handled": False}
        identity = self._handoff_identity(state)
        if identity is None:
            return {"handoff_handled": False}
        _, _, requester_id = identity
        active = await self._promote_case_to_demo(case, requester_id)
        return {
            "handoff_handled": True,
            "handoff_case": active,
            "final_response": DEMO_STARTED_MESSAGE,
        }

    async def _create_handoff_offer(
        self, state: AgentState, issue_descriptions: list[str]
    ) -> HandoffCase | None:
        if self.handoff_repository is None:
            return None
        identity = self._handoff_identity(state)
        if identity is None:
            return None
        tenant_id, conversation_id, requester_id = identity
        request = state["request"]
        now = datetime.now(timezone.utc)
        draft = deterministic_summary(
            current_message=request.message.text,
            issue_descriptions=issue_descriptions,
        )
        summary = CaseSummary(
            issue=draft.issue,
            userNeed=draft.user_need,
            conversationHighlights=draft.conversation_highlights,
            attemptedSolutions=draft.attempted_solutions,
            unresolvedReason=draft.unresolved_reason,
            requestedOutcome=draft.requested_outcome,
            generatedAt=draft.generated_at,
        )
        case = HandoffCase(
            caseId=str(uuid.uuid4()),
            sessionId=str(uuid.uuid4()),
            tenantId=tenant_id,
            conversationId=conversation_id,
            requesterId=requester_id,
            requesterName=request.user.displayName,
            status=HandoffStatus.OFFERED,
            summary=summary,
            createdAt=now,
            updatedAt=now,
            sessionExpiresAt=now + timedelta(hours=self.settings.handoff_demo_timeout_hours),
            retentionExpiresAt=now + timedelta(days=self.settings.handoff_retention_days),
            correlationId=state["correlation_id"],
        )
        try:
            case = await self.handoff_repository.create_case(case)
            await self._append_handoff_event(
                case, "handoff.offered", ActorType.SYSTEM, None
            )
            case = await self.handoff_repository.transition(
                case.caseId,
                HandoffStatus.OFFERED,
                HandoffStatus.SUMMARY_REVIEW,
                case.version,
            )
            await self._append_handoff_event(
                case,
                "handoff.summary_reviewed",
                ActorType.SYSTEM,
                None,
                {"fromStatus": "OFFERED", "toStatus": "SUMMARY_REVIEW"},
            )
            return case
        except ActiveHandoffCaseExistsError:
            return await self.handoff_repository.get_active_case(
                tenant_id, conversation_id, requester_id
            )

    async def _cancel_active_handoff(
        self,
        state: AgentState,
        *,
        reason: str,
    ) -> HandoffCase | None:
        if self.handoff_repository is None:
            return None
        identity = self._handoff_identity(state)
        if identity is None:
            return None
        tenant_id, conversation_id, requester_id = identity
        case = await self.handoff_repository.get_active_case(
            tenant_id, conversation_id, requester_id
        )
        if case is None or case.status not in {
            HandoffStatus.SUMMARY_REVIEW,
            HandoffStatus.AWAITING_SUPPLEMENT,
            HandoffStatus.DEMO_ACTIVE,
        }:
            return case
        # DEMO_ACTIVE may only leave via CLOSED (not CANCELLED). Ticket-query /
        # assistant-scope supersede must close the demo session instead.
        if case.status == HandoffStatus.DEMO_ACTIVE:
            closed = await self.handoff_repository.close_case(
                case.caseId, requester_id, case.version
            )
            await self._append_handoff_event(
                closed,
                "handoff.superseded",
                ActorType.USER,
                requester_id,
                {
                    "fromStatus": "DEMO_ACTIVE",
                    "toStatus": "CLOSED",
                    "reason": reason,
                },
            )
            return closed
        cancelled = await self.handoff_repository.transition(
            case.caseId,
            case.status,
            HandoffStatus.CANCELLED,
            case.version,
        )
        await self._append_handoff_event(
            cancelled,
            "handoff.superseded",
            ActorType.USER,
            requester_id,
            {
                "fromStatus": case.status.value,
                "toStatus": "CANCELLED",
                "reason": reason,
            },
        )
        return cancelled

    async def _supersede_handoff_for_resume(
        self,
        state: AgentState,
        case: HandoffCase,
        *,
        requester_id: str,
        ticket_intent: TicketIntent,
        resume_reason: HandoffResumeReason,
    ) -> dict:
        cancelled = await self.handoff_repository.transition(
            case.caseId,
            case.status,
            HandoffStatus.CANCELLED,
            case.version,
        )
        await self._append_handoff_event(
            cancelled,
            "handoff.superseded",
            ActorType.USER,
            requester_id,
            {
                "fromStatus": case.status.value,
                "toStatus": "CANCELLED",
                "reason": resume_reason.lower(),
            },
        )
        return {
            "handoff_handled": False,
            "handoff_case": cancelled,
            "handoff_resume_reason": resume_reason,
            "ticket_intent": ticket_intent,
        }

    async def _apply_handoff_supplement(
        self,
        state: AgentState,
        case: HandoffCase,
        *,
        requester_id: str,
    ) -> dict:
        request = state["request"]
        draft = await agentic_supplement_summary(
            getattr(self.handoff_router, "_model", None),
            issue=case.summary.issue,
            user_need=case.summary.userNeed,
            conversation_highlights=case.summary.conversationHighlights,
            attempted_solutions=case.summary.attemptedSolutions,
            supplement_message=request.message.text,
            execution_context=state.get("execution_context"),
        )
        updated_summary = CaseSummary(
            issue=draft.issue,
            userNeed=draft.user_need,
            conversationHighlights=draft.conversation_highlights,
            attemptedSolutions=draft.attempted_solutions,
            unresolvedReason=draft.unresolved_reason,
            requestedOutcome=draft.requested_outcome,
            generatedAt=draft.generated_at,
            version=case.summary.version + 1,
        )
        case = await self.handoff_repository.update_summary(
            case.caseId, updated_summary, case.version
        )
        if case.status is HandoffStatus.AWAITING_SUPPLEMENT:
            case = await self.handoff_repository.transition(
                case.caseId,
                HandoffStatus.AWAITING_SUPPLEMENT,
                HandoffStatus.SUMMARY_REVIEW,
                case.version,
            )
        await self._append_handoff_event(
            case,
            "handoff.summary_supplemented",
            ActorType.USER,
            requester_id,
        )
        return {
            "handoff_handled": True,
            "handoff_case": case,
            "final_response": offer_message(draft),
        }

    async def _evaluate_handoff(self, state: AgentState) -> dict:
        if self.handoff_repository is None:
            return {"handoff_handled": False}
        if state.get("handoff_resume_reason") in {"NEW_ISSUE", "REVISED_ISSUE"}:
            return {"handoff_handled": False}
        issue_results = state.get("issue_results", [])
        if any(
            result.resultType in {"KNOWLEDGE_ANSWERED", "FAQ_ANSWERED"}
            for result in issue_results
        ):
            await self._cancel_active_handoff(state, reason="knowledge_answered")
            return {"handoff_handled": False}
        trigger_results = {
            result.issueId
            for result in state.get("issue_results", [])
            if result.resultType in {"NO_KNOWLEDGE", "FAILED"}
            and not is_provider_busy_terminal(result.terminalReason)
        }
        if not trigger_results:
            return {"handoff_handled": False}
        descriptions = [
            issue.description
            for issue in state.get("issues", [])
            if issue.id in trigger_results
        ]
        case = await self._create_handoff_offer(state, descriptions)
        if case is None:
            return {"handoff_handled": False}
        draft = deterministic_summary(
            current_message=case.summary.userNeed,
            issue_descriptions=[case.summary.issue],
            conversation_highlights=case.summary.conversationHighlights,
            attempted_solutions=case.summary.attemptedSolutions,
        )
        return {
            "handoff_handled": True,
            "handoff_case": case,
            "final_response": offer_message(draft),
            "citations": [],
            "images": [],
            "feedback_enabled": False,
        }
