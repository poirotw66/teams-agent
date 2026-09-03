from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import unquote, urlsplit, urlunsplit

from ..contracts import AgentRequest, FeedbackRequest, IssueResult
from ..usage_events import RequestCostSummary
from .classification import IssueClassifier
from .contracts import MASKING_POLICY_VERSION, OperationalEvent, utc_now
from .event_identity import (
    LogicalRequestIdentity,
    conversation_started_event_id,
    event_fingerprint,
    feedback_event_id,
    feedback_submission_event_id,
    required_utc,
)
from .ingestion import EventIngestionService
from .masking import mask_text, pseudonymous_actor_id
from .settings import OpsSettings
from .taxonomy import TaxonomyRepository
from .usage_attribution import call_occurred_at, call_usage_payload, request_summary_payload

logger = logging.getLogger(__name__)


class OperationalEventReplayConflict(ValueError):
    """A replay changed previously observed immutable facts."""


class OperationalEventReplayDuplicate(Exception):
    """A finalized logical request was delivered again without changed facts."""


def _channel_scope(channel: str) -> str:
    if channel in {"playground", "msteams-web"}:
        return "playground"
    if channel.endswith("-channel"):
        return "channel"
    return "personal"


def _safe_source(source_path: str | None) -> tuple[str | None, str | None]:
    """Sanitize before deriving identifiers: slugification erases secret markers."""
    if not source_path:
        return None, None
    decoded = source_path
    for _ in range(4):
        expanded = unquote(decoded)
        if expanded == decoded:
            break
        decoded = expanded
    else:
        return "[REDACTED_SOURCE]", None
    masked = mask_text(decoded)
    if masked.was_masked:
        return masked.text, None
    try:
        parts = urlsplit(decoded)
        if parts.username is not None or parts.password is not None:
            return "[REDACTED_SOURCE]", None
    except ValueError:
        return "[REDACTED_SOURCE]", None
    # Query strings/fragments may carry signed access credentials even when a
    # free-text detector does not recognize the provider's parameter names.
    path = parts.path
    safe_path = urlunsplit((parts.scheme, parts.netloc, path, "", ""))
    return safe_path, IssueClassifier.document_id_from_source_path(path)


class OperationalEventEmitter:
    def __init__(
        self,
        ingestion: EventIngestionService,
        taxonomy: TaxonomyRepository,
        classifier: IssueClassifier,
        settings: OpsSettings,
    ) -> None:
        self._ingestion = ingestion
        self._taxonomy = taxonomy
        self._classifier = classifier
        self._settings = settings
        # Local conflict detection only. Persistent compare-and-create belongs
        # to the delivery/store integration; no old payload is substituted here.
        self._request_fingerprints: dict[str, str] = {}
        self._event_fingerprints: dict[str, str] = {}
        self._call_manifests: dict[str, set[str]] = {}
        self._final_usage: dict[str, str] = {}
        self._feedback_provenance: dict[
            tuple[str, str], tuple[str, str, str | None, str] | None
        ] = {}
        self._feedback_events: dict[str, tuple[str, OperationalEvent]] = {}

    @staticmethod
    def _occurred_at(state: dict[str, Any], conversation: object | None) -> datetime:
        if state.get("operational_occurred_at") is not None:
            return required_utc(state["operational_occurred_at"], "operational_occurred_at")
        # Correlation alone is not unique. Require the producer to identify the
        # actual persisted user message; lastActivityAt may belong to a prior turn.
        message = state.get("operational_user_message")
        if message is not None:
            return required_utc(getattr(message, "createdAt", None), "user message createdAt")
        raise ValueError("operational_occurred_at or operational_user_message is required")

    def _assert_immutable(
        self,
        request_key: str,
        request_fact: object,
        events: list[OperationalEvent],
        *,
        call_ids: set[str] | None = None,
        usage_fact: object = None,
        final_usage: bool = False,
    ) -> None:
        request_hash = event_fingerprint(request_fact)
        if self._request_fingerprints.get(request_key, request_hash) != request_hash:
            raise OperationalEventReplayConflict("logical request replay changed immutable facts")
        if final_usage and request_key in self._final_usage:
            raise OperationalEventReplayDuplicate
        proposed = {}
        for event in events:
            fingerprint = event_fingerprint(event)
            if event.event_id in proposed:
                raise OperationalEventReplayConflict("duplicate event identity within emission")
            if self._event_fingerprints.get(event.event_id, fingerprint) != fingerprint:
                raise OperationalEventReplayConflict("event replay changed immutable payload")
            proposed[event.event_id] = fingerprint
        usage_hash = event_fingerprint(usage_fact)
        if call_ids is not None:
            if not self._call_manifests.get(request_key, set()).issubset(call_ids):
                raise OperationalEventReplayConflict("replay removed collector facts")
            if self._final_usage.get(request_key, usage_hash) != usage_hash:
                raise OperationalEventReplayConflict("replay changed finalized usage")
        # Commit only after the entire batch validates; a rejected build cannot
        # poison future retries or register half a batch.
        self._request_fingerprints[request_key] = request_hash
        self._event_fingerprints.update(proposed)
        if call_ids is not None:
            self._call_manifests[request_key] = call_ids
        if final_usage:
            self._final_usage[request_key] = usage_hash

    async def emit_turn(
        self, payload: AgentRequest, state: dict[str, Any], *,
        cost_summary: RequestCostSummary | None,
    ) -> None:
        try:
            events = self.build_turn_events(payload, state, cost_summary=cost_summary)
        except OperationalEventReplayDuplicate:
            return
        await self._ingestion.ingest_many(events)

    def schedule_turn(
        self, payload: AgentRequest, state: dict[str, Any], *,
        cost_summary: RequestCostSummary | None,
    ) -> None:
        # Build synchronously to validate provenance and freeze the completed
        # fact image before a caller can mutate the collector/state.
        try:
            events = self.build_turn_events(payload, state, cost_summary=cost_summary)
        except OperationalEventReplayDuplicate:
            return
        asyncio.create_task(self._ingestion.ingest_many(events))

    def build_feedback_event(
        self, payload: FeedbackRequest, *,
        tenant_id: str | None = None, feedback_id: str | None = None,
        occurred_at: datetime | None = None, actor_id: str | None = None,
        request_id: str | None = None,
    ) -> OperationalEvent:
        provenance_key = (payload.correlationId, payload.conversationId or "")
        trusted = self._feedback_provenance.get(provenance_key)
        if provenance_key in self._feedback_provenance and trusted is None:
            raise ValueError("feedback provenance is ambiguous")
        canonical_conversation_id = payload.conversationId
        if trusted is not None:
            trusted_tenant, trusted_request, trusted_actor, canonical_conversation_id = trusted
            if tenant_id is not None and tenant_id != trusted_tenant:
                raise OperationalEventReplayConflict("feedback tenant does not match turn")
            if request_id is not None and request_id != trusted_request:
                raise OperationalEventReplayConflict("feedback request does not match turn")
            if actor_id is not None and actor_id != trusted_actor:
                raise OperationalEventReplayConflict("feedback actor does not match turn")
            tenant_id, request_id, actor_id = (
                trusted_tenant,
                trusted_request,
                trusted_actor,
            )
        if not tenant_id or not actor_id:
            raise ValueError("trusted feedback tenant and actor provenance are required")
        if payload.userId is not None and payload.userId != actor_id:
            raise OperationalEventReplayConflict("feedback user does not match turn actor")
        feedback_id = feedback_id or feedback_event_id(
            tenant_id=tenant_id,
            conversation_id=canonical_conversation_id,
            correlation_id=payload.correlationId,
            issue_id=payload.issueId,
            rating=payload.rating,
            resolved_status=payload.resolvedStatus,
            actor_id=actor_id,
            reason=payload.reason,
        )
        feedback_fact = event_fingerprint(payload.model_dump(mode="json"))
        existing = self._feedback_events.get(feedback_id)
        if existing is not None:
            if existing[0] != feedback_fact:
                raise OperationalEventReplayConflict("feedback replay changed immutable facts")
            return existing[1]
        timestamp = required_utc(occurred_at or utc_now(), "feedback occurred_at")
        identity = LogicalRequestIdentity(tenant_id, canonical_conversation_id, request_id) if request_id else None
        event = OperationalEvent(
            event_id=feedback_submission_event_id(tenant_id, feedback_id),
            event_type="feedback.recorded",
            occurred_at=timestamp,
            retention_expires_at=timestamp + timedelta(days=self._settings.default_retention_days),
            environment=self._settings.environment,
            tenant_id=tenant_id,
            conversation_id=canonical_conversation_id,
            request_id=request_id,
            turn_id=identity.value if identity else None,
            issue_occurrence_id=(
                identity.issue_occurrence_id(payload.issueId)
                if identity and payload.issueId is not None else None
            ),
            correlation_id=payload.correlationId,
            actor_ref=pseudonymous_actor_id(actor_id),
            data_classification="CONFIDENTIAL",
            payload={
                "rating": payload.rating,
                "issueId": payload.issueId,
                "reason": mask_text(payload.reason).text if payload.reason else None,
                "resolvedStatus": payload.resolvedStatus,
            },
        )
        self._assert_immutable(event.event_id, payload.model_dump(mode="json"), [event])
        self._feedback_events[feedback_id] = (feedback_fact, event)
        return event

    async def emit_feedback(self, payload: FeedbackRequest, **provenance: Any) -> None:
        await self._ingestion.ingest(self.build_feedback_event(payload, **provenance))

    def schedule_feedback(self, payload: FeedbackRequest, **provenance: Any) -> None:
        event = self.build_feedback_event(payload, **provenance)
        asyncio.create_task(self._ingestion.ingest(event))

    def build_turn_events(
        self, payload: AgentRequest, state: dict[str, Any], *,
        cost_summary: RequestCostSummary | None,
    ) -> list[OperationalEvent]:
        correlation_id = str(state.get("correlation_id") or payload.correlationId or payload.requestId)
        conversation = state.get("conversation")
        conversation_id = getattr(conversation, "conversationId", None) or payload.conversation.conversationId
        identity = LogicalRequestIdentity(payload.conversation.tenantId, conversation_id, payload.requestId)
        occurred_at = self._occurred_at(state, conversation)
        base = {
            "environment": self._settings.environment,
            "tenant_id": payload.conversation.tenantId,
            "team_id": payload.conversation.teamId,
            "channel_scope": _channel_scope(payload.channel),
            "conversation_id": conversation_id,
            "turn_id": identity.value,
            "request_id": payload.requestId,
            "correlation_id": correlation_id,
            "actor_ref": pseudonymous_actor_id(payload.user.entraObjectId or payload.user.teamsUserId),
        }
        events: list[OperationalEvent] = []

        def add(kind: str, body: dict[str, Any], *parts: object, **fields: Any) -> None:
            timestamp = fields.pop("occurred_at", occurred_at)
            events.append(OperationalEvent(
                **base, event_id=identity.event_id(kind, *parts), event_type=kind,
                occurred_at=timestamp,
                retention_expires_at=timestamp + timedelta(days=self._settings.default_retention_days),
                payload=body, **fields,
            ))

        masked = mask_text(payload.message.text)
        add("turn.received", {
            "messageMasked": masked.text, "messageWasMasked": masked.was_masked,
            "locale": payload.message.locale, "maskingPolicyVersion": MASKING_POLICY_VERSION,
        }, data_classification="CONFIDENTIAL")
        if conversation_id and state.get("conversation_started") is True:
            started_at_value = getattr(conversation, "startedAt", None)
            if started_at_value is None:
                started_at_value = state.get("operational_conversation_started_at")
            if started_at_value is None:
                started_at_value = occurred_at
            started_at = required_utc(
                started_at_value,
                "conversation startedAt",
            )
            # A lifecycle fact has no request, actor, team, or correlation from
            # whichever turn happens to re-deliver it.
            lifecycle_id = conversation_started_event_id(
                tenant_id=payload.conversation.tenantId, conversation_id=conversation_id,
            )
            events.append(OperationalEvent(
                event_id=lifecycle_id, event_type="conversation.started",
                environment=self._settings.environment, tenant_id=payload.conversation.tenantId,
                conversation_id=conversation_id, correlation_id=lifecycle_id,
                occurred_at=started_at,
                retention_expires_at=started_at + timedelta(days=self._settings.default_retention_days),
                payload={},
            ))
        issues = state.get("issues") or []
        results = state.get("issue_results") or []
        if len({i.id for i in issues}) != len(issues) or len({r.issueId for r in results}) != len(results):
            raise OperationalEventReplayConflict("duplicate issue/result identity")
        results_by_issue = {r.issueId: r for r in results}
        for issue in issues:
            occurrence = identity.issue_occurrence_id(issue.id)
            classification = self._classifier.classify(
                issue.description, route=issue.route, faq_key=issue.faqKey,
            )
            fields = {
                "issue_occurrence_id": occurrence, "issue_type_id": classification.issue_type_id,
                "taxonomy_version": self._taxonomy.version,
            }
            add("issue.extracted", {
                "issueId": issue.id, "descriptionMasked": mask_text(issue.description).text,
                "descriptionRawLength": len(issue.description), "readiness": issue.readiness,
                "route": issue.route, "faqKey": issue.faqKey,
            }, occurrence, **fields)
            add("issue.classified", {
                "issueId": issue.id, "classificationSource": classification.classification_source,
                "confidenceStatus": classification.confidence_status,
                "normalizedDescription": mask_text(classification.normalized_description).text,
                "faqKey": issue.faqKey, "descriptionRawLength": len(issue.description),
            }, occurrence, **fields)
            add("route.selected", {"route": issue.route}, occurrence, **fields)
            result = results_by_issue.get(issue.id)
            if result:
                for kind, body, suffix in self._result_payloads(result, state.get("knowledge_release_id")):
                    add(kind, body, occurrence, suffix, **fields)
        if state.get("handoff_handled"):
            case = state.get("handoff_case")
            status = getattr(case, "status", "OFFERED")
            status = status.value if hasattr(status, "value") else str(status)
            kind = {
                "OFFERED": "handoff.offered", "CLOSED": "handoff.completed",
                "CANCELLED": "handoff.cancelled", "FAILED": "handoff.cancelled",
                "EXPIRED": "handoff.cancelled", "ROUTED_TO_TICKET": "handoff.completed",
            }.get(status, "handoff.started")
            add(kind, {
                "caseId": getattr(case, "caseId", None), "status": status,
                "providerMode": getattr(case, "providerMode", None),
            }, getattr(case, "caseId", None), status, data_classification="CONFIDENTIAL")

        collector = getattr(state.get("execution_context"), "usage_collector", None)
        calls = tuple(collector.events()) if collector is not None else ()
        for call_ordinal, call in enumerate(calls, 1):
            self._validate_usage_scope(call, payload, correlation_id)
            add("usage.recorded", call_usage_payload(call, call_ordinal=call_ordinal),
                "call", call.event_id,
                occurred_at=call_occurred_at(call))
        if cost_summary is not None:
            self._validate_usage_scope(cost_summary, payload, correlation_id)
            add("usage.recorded", request_summary_payload(cost_summary, calls), "request-summary")
        # Hash raw inputs transiently so even two credentials that mask to the
        # same marker conflict. Only digests are retained, never these inputs.
        request_fact = {
            "message": payload.message.text, "locale": payload.message.locale,
            "actor": [payload.user.entraObjectId, payload.user.teamsUserId],
            "channel": payload.channel, "team": payload.conversation.teamId,
            "issues": [i.model_dump(mode="json") for i in issues],
            "results": [r.model_dump(mode="json") for r in results],
            "handoff": state.get("handoff_handled"),
            "release": state.get("knowledge_release_id"),
        }
        usage_fact = {
            "calls": sorted([event_fingerprint(c.to_log_dict()) for c in calls]),
            "summary": cost_summary.to_log_dict() if cost_summary else None,
        }
        self._assert_immutable(
            identity.value, request_fact, events,
            call_ids={c.event_id for c in calls}, usage_fact=usage_fact,
            final_usage=cost_summary is not None,
        )
        feedback_provenance = (
            payload.conversation.tenantId,
            payload.requestId,
            payload.user.entraObjectId or payload.user.teamsUserId,
            conversation_id or payload.conversation.conversationId,
        )
        for feedback_conversation_id in {
            conversation_id,
            payload.conversation.conversationId,
        }:
            feedback_key = (correlation_id, feedback_conversation_id or "")
            existing_provenance = self._feedback_provenance.get(feedback_key)
            if existing_provenance is not None and existing_provenance != feedback_provenance:
                self._feedback_provenance[feedback_key] = None
            elif feedback_key not in self._feedback_provenance:
                self._feedback_provenance[feedback_key] = feedback_provenance
        return events

    def _validate_usage_scope(self, usage: Any, request: AgentRequest, correlation_id: str) -> None:
        if (usage.request_id, usage.tenant_id, usage.team_id, usage.environment, usage.correlation_id) != (
            request.requestId, request.conversation.tenantId, request.conversation.teamId,
            self._settings.environment, correlation_id,
        ):
            raise OperationalEventReplayConflict("collector/summary provenance does not match request")

    @staticmethod
    def _result_payloads(
        result: IssueResult, release_id: str | None,
    ) -> list[tuple[str, dict[str, Any], object]]:
        events: list[tuple[str, dict[str, Any], object]] = []
        if result.resultType == "TICKET_CREATED":
            events.append(("ticket.created", {"ticketId": result.ticketId, "backend": result.backend}, None))
        elif result.resultType == "FAILED" and result.ticketId:
            events.append(("ticket.failed", {
                "error": mask_text(result.error).text if result.error else None,
                "backend": result.backend,
            }, None))
        kind = "answer.completed"
        body: dict[str, Any] = {"resultType": result.resultType, "backend": result.backend}
        if result.answer:
            answer = mask_text(result.answer)
            body.update(answerMasked=answer.text, answerWasMasked=answer.was_masked)
        if result.resultType == "FAQ_ANSWERED":
            kind = "faq.answered"
            body["faqKey"] = getattr(result, "faqKey", None)
        elif result.resultType == "KNOWLEDGE_ANSWERED":
            kind = "knowledge.answered"
            citations = []
            for rank, source in enumerate(result.sources, 1):
                source_path, document_id = _safe_source(source.url)
                citation = {
                    "rank": rank, "title": mask_text(source.title).text,
                    "chunkId": mask_text(source.chunkId).text if source.chunkId else None,
                    "documentId": document_id, "sourcePath": source_path,
                }
                citations.append(citation)
                events.append(("knowledge.retrieved", {**citation, "releaseId": release_id}, rank))
            body.update(citations=citations, releaseId=release_id, sourceCount=len(citations))
        events.append((kind, body, None))
        return events
