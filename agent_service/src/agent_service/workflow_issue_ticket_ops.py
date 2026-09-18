"""Ticket-route helpers for the issue processing subgraph."""

from __future__ import annotations

import asyncio
import logging

from .confirmation import TicketIntent
from .contracts import (
    AgentRequest,
    Citation,
    Issue,
    IssueResult,
    TicketDraft,
    TicketItem,
    UserContext,
)
from .execution_context import ExecutionContext
from .ticket import (
    TicketServiceDisabledError,
    TicketServiceError,
    TicketServiceTimeout,
    UntrustedRequesterError,
    handoff_ticket_item_fallback,
)

logger = logging.getLogger(__name__)


class IssueTicketOps:
    """Ticket create/query nodes shared by issue processing."""

    async def _claim_ticket_creation_slot(
        self,
        *,
        issue: Issue,
        correlation_id: str,
        lock: asyncio.Lock,
        ticket_created: dict,
    ) -> IssueResult | None:
        # Spec §11.5: at most one ticket created per turn.
        async with lock:
            if ticket_created["done"]:
                allowed = False
            else:
                ticket_created["done"] = True
                allowed = True
        if allowed:
            return None
        logger.info(
            "Ticket creation skipped: one-ticket-per-turn limit already reached. "
            "issue_id=%s correlation_id=%s",
            issue.id,
            correlation_id,
        )
        return IssueResult(issueId=issue.id, resultType="FAILED", error="ticket_limit_per_turn")

    async def _select_ticket_item_for_issue(
        self,
        issue: Issue,
        *,
        correlation_id: str,
        handoff_confirmed: bool,
        execution_context: ExecutionContext | None,
    ) -> IssueResult | TicketItem:
        """Return IssueResult on failure, or the selected catalog item on success."""
        try:
            items = await self.ticket_service.get_ticket_items(correlation_id=correlation_id)
        except TicketServiceDisabledError:
            return IssueResult(
                issueId=issue.id, resultType="FAILED", error="ticket_service_disabled"
            )
        except (TicketServiceTimeout, TicketServiceError) as exc:
            return IssueResult(issueId=issue.id, resultType="FAILED", error=str(exc)[:300])

        if handoff_confirmed:
            selected_item = handoff_ticket_item_fallback(items)
            selection_reason = "handoff_fallback" if selected_item else None
        else:
            selected_item = None
            selection_reason = None
        if selected_item is None:
            selection = await self.ticket_item_selector.select(
                items=items,
                issue_description=issue.description,
                execution_context=execution_context,
            )
            selected_item = selection.item
            selection_reason = selection.reason
        if selected_item is not None and selection_reason == "handoff_fallback":
            logger.info(
                "Handoff ticket creation used catalog fallback: item_id=%s correlation_id=%s",
                selected_item.id,
                correlation_id,
            )
        if selected_item is not None:
            return selected_item
        if selection_reason in {"model_unavailable", "model_error"}:
            question = "目前無法判定適用的派工單類別；已保留案件內容，請稍後重試或聯絡線上客服。"
        else:
            question = (
                "目前無法從可用派工單類別判定最適合的一項；"
                "請補充與目前案件最相關的系統、功能或錯誤訊息。"
            )
        return IssueResult(
            issueId=issue.id,
            resultType="NEED_MORE_INFO",
            questions=[question],
        )

    async def _create_ticket_result(
        self,
        issue: Issue,
        *,
        user: UserContext,
        correlation_id: str,
        requester_id: str,
        selected_item: TicketItem,
        ticket_body: str | None,
        request_id: str | None,
        tenant_id: str | None,
        idempotency_key: str | None,
    ) -> IssueResult:
        draft = TicketDraft(
            requesterId=requester_id,
            requesterName=user.displayName or "",
            requesterEmail=user.email or "",
            title=issue.description[:120],
            description=(ticket_body or issue.description),
            ticketItemId=selected_item.id,
        )
        try:
            ticket = await self.ticket_service.create_ticket(
                draft,
                correlation_id=correlation_id,
                idempotency_key=idempotency_key,
            )
        except TicketServiceDisabledError:
            return IssueResult(
                issueId=issue.id, resultType="FAILED", error="ticket_service_disabled"
            )
        except UntrustedRequesterError:
            return IssueResult(issueId=issue.id, resultType="FAILED", error="untrusted_requester")
        except (TicketServiceTimeout, TicketServiceError) as exc:
            return IssueResult(issueId=issue.id, resultType="FAILED", error=str(exc)[:300])

        if request_id and ticket.id:
            await self.ticket_request_dedupe.put(tenant_id, request_id, ticket.id)

        sources = [Citation(title=f"{ticket.title} ({ticket.status})", url=ticket.url)]
        return IssueResult(
            issueId=issue.id, resultType="TICKET_CREATED", ticketId=ticket.id, sources=sources
        )

    async def _handle_ticket(
        self,
        issue: Issue,
        *,
        user: UserContext,
        correlation_id: str,
        lock: asyncio.Lock,
        ticket_created: dict,
        ticket_intent: TicketIntent,
        ticket_body: str | None = None,
        handoff_confirmed: bool = False,
        request_id: str | None = None,
        tenant_id: str | None = None,
        agent_request: AgentRequest | None = None,
        idempotency_key: str | None = None,
        execution_context: ExecutionContext | None = None,
    ) -> IssueResult:
        _ = agent_request  # call-site parity with knowledge/handoff paths
        if ticket_intent == TicketIntent.QUERY:
            return await self._query_tickets(issue, user, correlation_id)
        if ticket_intent != TicketIntent.CREATE:
            return IssueResult(issueId=issue.id, resultType="NO_KNOWLEDGE")

        requester_id = user.entraObjectId or user.teamsUserId or ""
        if request_id:
            deduped = await self._deduped_ticket_result(
                issue=issue,
                request_id=request_id,
                tenant_id=tenant_id,
                correlation_id=correlation_id,
                ticket_service=self.ticket_service,
                requester_id=requester_id,
            )
            if deduped is not None:
                return deduped

        # Spec §11.4: identity must come ONLY from the trusted Teams/Entra
        # context, never from the user's free text.
        if not user.is_trusted_for_ticket:
            logger.warning(
                "Ticket creation refused: untrusted requester identity. "
                "issue_id=%s correlation_id=%s",
                issue.id,
                correlation_id,
            )
            return IssueResult(issueId=issue.id, resultType="FAILED", error="untrusted_requester")

        slot_denied = await self._claim_ticket_creation_slot(
            issue=issue,
            correlation_id=correlation_id,
            lock=lock,
            ticket_created=ticket_created,
        )
        if slot_denied is not None:
            return slot_denied

        selected = await self._select_ticket_item_for_issue(
            issue,
            correlation_id=correlation_id,
            handoff_confirmed=handoff_confirmed,
            execution_context=execution_context,
        )
        if isinstance(selected, IssueResult):
            return selected

        return await self._create_ticket_result(
            issue,
            user=user,
            correlation_id=correlation_id,
            requester_id=requester_id,
            selected_item=selected,
            ticket_body=ticket_body,
            request_id=request_id,
            tenant_id=tenant_id,
            idempotency_key=idempotency_key,
        )

    async def _query_tickets(
        self, issue: Issue, user: UserContext, correlation_id: str
    ) -> IssueResult:
        # Spec §17: never allow querying another user's tickets — always
        # scope strictly to the trusted current-user id.
        requester_id = user.entraObjectId or user.teamsUserId
        if not requester_id:
            return IssueResult(issueId=issue.id, resultType="FAILED", error="untrusted_requester")
        try:
            tickets = await self.ticket_service.list_tickets_by_requester(
                requester_id, correlation_id=correlation_id
            )
        except TicketServiceDisabledError:
            return IssueResult(
                issueId=issue.id, resultType="FAILED", error="ticket_service_disabled"
            )
        except (TicketServiceTimeout, TicketServiceError) as exc:
            return IssueResult(issueId=issue.id, resultType="FAILED", error=str(exc)[:300])

        sources = [Citation(title=f"{t.title} ({t.status})", url=t.url) for t in tickets]
        return IssueResult(issueId=issue.id, resultType="TICKET_FOUND", sources=sources)
