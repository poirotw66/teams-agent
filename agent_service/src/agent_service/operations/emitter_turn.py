"""Turn event construction for operational emission."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from ..contracts import AgentRequest
from ..usage_events import RequestCostSummary
from .classification import IssueClassifier
from .contracts import OperationalEvent
from .emitter_channel import channel_scope, is_teams_channel
from .emitter_exceptions import OperationalEventReplayConflict
from .emitter_feedback import FeedbackProvenance, FeedbackProvenanceMap
from .emitter_replay import ReplayFingerprintStore
from .emitter_results import result_payloads
from .event_identity import (
    LogicalRequestIdentity,
    conversation_started_event_id,
    event_fingerprint,
    required_utc,
)
from .masking import mask_text, pseudonymous_actor_id
from .policy_runtime import active_masking_policy_version, active_retention_days
from .settings import OpsSettings
from .taxonomy import TaxonomyRepository
from .usage_attribution import call_occurred_at, call_usage_payload, request_summary_payload


def occurred_at(state: dict[str, Any], conversation: object | None) -> datetime:
    if state.get("operational_occurred_at") is not None:
        return required_utc(state["operational_occurred_at"], "operational_occurred_at")
    # Correlation alone is not unique. Require the producer to identify the
    # actual persisted user message; lastActivityAt may belong to a prior turn.
    message = state.get("operational_user_message")
    if message is not None:
        return required_utc(getattr(message, "createdAt", None), "user message createdAt")
    raise ValueError("operational_occurred_at or operational_user_message is required")


def validate_usage_scope(
    usage: Any, request: AgentRequest, correlation_id: str, environment: str,
) -> None:
    if (usage.request_id, usage.tenant_id, usage.team_id, usage.environment, usage.correlation_id) != (
        request.requestId,
        request.conversation.tenantId,
        request.conversation.teamId,
        environment,
        correlation_id,
    ):
        raise OperationalEventReplayConflict("collector/summary provenance does not match request")


def _event_tenant_id(payload: AgentRequest, settings: OpsSettings, scope: str) -> str:
    event_tenant_id = payload.conversation.tenantId
    if (
        scope == "playground"
        and settings.environment in {"dev", "test"}
        and (
            not event_tenant_id
            or event_tenant_id in {"00000000-0000-0000-0000-0000000000001", "local-development"}
        )
    ):
        return "local-development"
    return event_tenant_id


def _append_conversation_started(
    events: list[OperationalEvent],
    *,
    payload: AgentRequest,
    state: dict[str, Any],
    conversation: object | None,
    conversation_id: str,
    turn_occurred_at: datetime,
    settings: OpsSettings,
) -> None:
    if not (conversation_id and state.get("conversation_started") is True):
        return
    started_at_value = getattr(conversation, "startedAt", None)
    if started_at_value is None:
        started_at_value = state.get("operational_conversation_started_at")
    if started_at_value is None:
        started_at_value = turn_occurred_at
    started_at = required_utc(started_at_value, "conversation startedAt")
    # A lifecycle fact has no request, actor, team, or correlation from
    # whichever turn happens to re-deliver it.
    lifecycle_id = conversation_started_event_id(
        tenant_id=payload.conversation.tenantId, conversation_id=conversation_id,
    )
    events.append(
        OperationalEvent(
            event_id=lifecycle_id,
            event_type="conversation.started",
            environment=settings.environment,
            tenant_id=payload.conversation.tenantId,
            conversation_id=conversation_id,
            correlation_id=lifecycle_id,
            occurred_at=started_at,
            retention_expires_at=started_at + timedelta(days=active_retention_days(settings)),
            payload={},
        )
    )


def _append_issue_events(
    add: Any,
    *,
    issues: list[Any],
    results_by_issue: dict[str, Any],
    identity: LogicalRequestIdentity,
    classifier: IssueClassifier,
    taxonomy: TaxonomyRepository,
    release_id: str | None,
) -> None:
    for issue in issues:
        occurrence = identity.issue_occurrence_id(issue.id)
        classification = classifier.classify(
            issue.description,
            route=issue.route,
            faq_key=issue.faqKey,
            model_issue_type_id=getattr(issue, "issueTypeId", None),
        )
        fields = {
            "issue_occurrence_id": occurrence,
            "issue_type_id": classification.issue_type_id,
            "taxonomy_version": taxonomy.version,
        }
        add(
            "issue.extracted",
            {
                "issueId": issue.id,
                "descriptionMasked": mask_text(issue.description).text,
                "descriptionRawLength": len(issue.description),
                "readiness": issue.readiness,
                "route": issue.route,
                "faqKey": issue.faqKey,
            },
            occurrence,
            **fields,
        )
        add(
            "issue.classified",
            {
                "issueId": issue.id,
                "classificationSource": classification.classification_source,
                "confidenceStatus": classification.confidence_status,
                "normalizedDescription": mask_text(classification.normalized_description).text,
                "faqKey": issue.faqKey,
                "descriptionRawLength": len(issue.description),
            },
            occurrence,
            **fields,
        )
        add("route.selected", {"route": issue.route}, occurrence, **fields)
        result = results_by_issue.get(issue.id)
        if result:
            for kind, body, suffix in result_payloads(result, release_id):
                add(kind, body, occurrence, suffix, **fields)


def _append_rendered_response(add: Any, *, state: dict[str, Any], issues: list[Any], results: list[Any]) -> None:
    # Persist the exact deterministic response rendered to the user.  A
    # clarification or NOT_IT turn can have no IssueResult.answer, while
    # the adapter still sends a useful response.  Keeping this as a
    # separate answer.completed fact also lets the backoffice show one
    # complete turn without replacing the per-issue provenance events.
    rendered_response = str(state.get("final_response") or "").strip()
    if not rendered_response:
        return
    rendered = mask_text(rendered_response)
    response_result_type = next(
        (
            result.resultType
            for result in results
            if result.resultType not in {"FAILED", "NO_KNOWLEDGE"}
        ),
        next(
            (issue.route for issue in issues if issue.route == "NOT_IT"),
            "RESPONSE_RENDERED",
        ),
    )
    add(
        "answer.completed",
        {
            "resultType": response_result_type,
            "backend": None,
            "answerMasked": rendered.text,
            "answerWasMasked": rendered.was_masked,
            "renderedResponse": True,
        },
        "rendered-response",
    )


def _append_handoff(add: Any, *, state: dict[str, Any]) -> None:
    if not state.get("handoff_handled"):
        return
    case = state.get("handoff_case")
    status = getattr(case, "status", "OFFERED")
    status = status.value if hasattr(status, "value") else str(status)
    kind = {
        "OFFERED": "handoff.offered",
        "CLOSED": "handoff.completed",
        "CANCELLED": "handoff.cancelled",
        "FAILED": "handoff.cancelled",
        "EXPIRED": "handoff.cancelled",
        "ROUTED_TO_TICKET": "handoff.completed",
    }.get(status, "handoff.started")
    add(
        kind,
        {
            "caseId": getattr(case, "caseId", None),
            "status": status,
            "providerMode": getattr(case, "providerMode", None),
        },
        getattr(case, "caseId", None),
        status,
        data_classification="CONFIDENTIAL",
    )


def _append_usage_events(
    add: Any,
    *,
    payload: AgentRequest,
    state: dict[str, Any],
    correlation_id: str,
    settings: OpsSettings,
    cost_summary: RequestCostSummary | None,
) -> tuple[tuple[Any, ...], object]:
    collector = getattr(state.get("execution_context"), "usage_collector", None)
    calls = tuple(collector.events()) if collector is not None else ()
    for call_ordinal, call in enumerate(calls, 1):
        validate_usage_scope(call, payload, correlation_id, settings.environment)
        add(
            "usage.recorded",
            call_usage_payload(call, call_ordinal=call_ordinal),
            "call",
            call.event_id,
            occurred_at=call_occurred_at(call),
        )
    if cost_summary is not None:
        validate_usage_scope(cost_summary, payload, correlation_id, settings.environment)
        add("usage.recorded", request_summary_payload(cost_summary, calls), "request-summary")
    usage_fact = {
        "calls": sorted([event_fingerprint(c.to_log_dict()) for c in calls]),
        "summary": cost_summary.to_log_dict() if cost_summary else None,
    }
    return calls, usage_fact


def _record_feedback_provenance(
    feedback_provenance: FeedbackProvenanceMap,
    *,
    correlation_id: str,
    conversation_id: str | None,
    payload: AgentRequest,
) -> None:
    feedback_row: FeedbackProvenance = (
        payload.conversation.tenantId,
        payload.requestId,
        payload.user.entraObjectId or payload.user.teamsUserId,
        conversation_id or payload.conversation.conversationId,
    )
    for feedback_conversation_id in {conversation_id, payload.conversation.conversationId}:
        feedback_key = (correlation_id, feedback_conversation_id or "")
        existing_provenance = feedback_provenance.get(feedback_key)
        if existing_provenance is not None and existing_provenance != feedback_row:
            feedback_provenance[feedback_key] = None
        elif feedback_key not in feedback_provenance:
            feedback_provenance[feedback_key] = feedback_row


def _turn_base_fields(
    payload: AgentRequest,
    *,
    settings: OpsSettings,
    conversation_id: str,
    identity: LogicalRequestIdentity,
    correlation_id: str,
) -> dict[str, Any]:
    scope = channel_scope(payload.channel)
    return {
        "environment": settings.environment,
        "tenant_id": _event_tenant_id(payload, settings, scope),
        "team_id": payload.conversation.teamId,
        "channel_scope": scope,
        "conversation_id": conversation_id,
        "turn_id": identity.value,
        "request_id": payload.requestId,
        "correlation_id": correlation_id,
        "actor_ref": pseudonymous_actor_id(payload.user.entraObjectId or payload.user.teamsUserId),
    }


def _make_event_adder(
    events: list[OperationalEvent],
    *,
    base: dict[str, Any],
    identity: LogicalRequestIdentity,
    turn_occurred_at: datetime,
    settings: OpsSettings,
) -> Any:
    def add(kind: str, body: dict[str, Any], *parts: object, **fields: Any) -> None:
        timestamp = fields.pop("occurred_at", turn_occurred_at)
        events.append(
            OperationalEvent(
                **base,
                event_id=identity.event_id(kind, *parts),
                event_type=kind,
                occurred_at=timestamp,
                retention_expires_at=timestamp + timedelta(days=active_retention_days(settings)),
                payload=body,
                **fields,
            )
        )

    return add


def _append_ingress_events(add: Any, *, payload: AgentRequest) -> None:
    masked = mask_text(payload.message.text)
    add(
        "turn.received",
        {
            "messageMasked": masked.text,
            "messageWasMasked": masked.was_masked,
            "locale": payload.message.locale,
            "maskingPolicyVersion": active_masking_policy_version(),
        },
        data_classification="CONFIDENTIAL",
    )
    if not is_teams_channel(str(payload.channel or "")):
        return
    # Ingress-only fact: message reached Agent from Teams. Reply success,
    # failure, timeout, and elapsedMs are emitted by the Teams Adapter
    # producer (ADAPTER_REPLY) and must not be inferred from this row.
    add(
        "usage.recorded",
        {
            "component": "teams_adapter",
            "status": "SUCCESS",
            "channel": payload.channel,
            "attributionScope": "ADAPTER_INGRESS",
            "phase": "ingress",
        },
        "teams-adapter",
    )


def _request_fact(
    payload: AgentRequest, state: dict[str, Any], issues: list[Any], results: list[Any],
) -> dict[str, Any]:
    # Hash raw inputs transiently so even two credentials that mask to the
    # same marker conflict. Only digests are retained, never these inputs.
    return {
        "message": payload.message.text,
        "locale": payload.message.locale,
        "actor": [payload.user.entraObjectId, payload.user.teamsUserId],
        "channel": payload.channel,
        "team": payload.conversation.teamId,
        "issues": [i.model_dump(mode="json") for i in issues],
        "results": [r.model_dump(mode="json") for r in results],
        "handoff": state.get("handoff_handled"),
        "release": state.get("knowledge_release_id"),
        "selectionMode": state.get("knowledge_selection_mode"),
        "lastSuccessfulSyncAt": state.get("knowledge_last_successful_sync_at"),
        "isCloudProductionAnswer": bool(state.get("is_cloud_production_answer")),
        "serviceCatalogVersion": state.get("service_catalog_version"),
        "aclDecision": state.get("knowledge_acl_decision"),
        "aclFilteredCount": state.get("knowledge_acl_filtered_count"),
    }


def build_turn_events(
    *,
    payload: AgentRequest,
    state: dict[str, Any],
    cost_summary: RequestCostSummary | None,
    settings: OpsSettings,
    classifier: IssueClassifier,
    taxonomy: TaxonomyRepository,
    replay: ReplayFingerprintStore,
    feedback_provenance: FeedbackProvenanceMap,
) -> list[OperationalEvent]:
    correlation_id = str(state.get("correlation_id") or payload.correlationId or payload.requestId)
    conversation = state.get("conversation")
    conversation_id = getattr(conversation, "conversationId", None) or payload.conversation.conversationId
    identity = LogicalRequestIdentity(payload.conversation.tenantId, conversation_id, payload.requestId)
    turn_occurred_at = occurred_at(state, conversation)
    events: list[OperationalEvent] = []
    add = _make_event_adder(
        events,
        base=_turn_base_fields(
            payload,
            settings=settings,
            conversation_id=conversation_id,
            identity=identity,
            correlation_id=correlation_id,
        ),
        identity=identity,
        turn_occurred_at=turn_occurred_at,
        settings=settings,
    )
    _append_ingress_events(add, payload=payload)
    _append_conversation_started(
        events,
        payload=payload,
        state=state,
        conversation=conversation,
        conversation_id=conversation_id,
        turn_occurred_at=turn_occurred_at,
        settings=settings,
    )
    issues = state.get("issues") or []
    results = state.get("issue_results") or []
    if len({i.id for i in issues}) != len(issues) or len({r.issueId for r in results}) != len(results):
        raise OperationalEventReplayConflict("duplicate issue/result identity")
    _append_issue_events(
        add,
        issues=issues,
        results_by_issue={r.issueId: r for r in results},
        identity=identity,
        classifier=classifier,
        taxonomy=taxonomy,
        release_id=state.get("knowledge_release_id"),
    )
    _append_rendered_response(add, state=state, issues=issues, results=results)
    _append_handoff(add, state=state)
    calls, usage_fact = _append_usage_events(
        add,
        payload=payload,
        state=state,
        correlation_id=correlation_id,
        settings=settings,
        cost_summary=cost_summary,
    )
    replay.assert_immutable(
        identity.value,
        _request_fact(payload, state, issues, results),
        events,
        call_ids={c.event_id for c in calls},
        usage_fact=usage_fact,
        final_usage=cost_summary is not None,
    )
    _record_feedback_provenance(
        feedback_provenance,
        correlation_id=correlation_id,
        conversation_id=conversation_id,
        payload=payload,
    )
    return events
