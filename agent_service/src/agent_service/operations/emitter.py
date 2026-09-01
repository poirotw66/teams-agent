from __future__ import annotations



import asyncio

import logging

import uuid

from typing import Any



from ..contracts import AgentRequest, FeedbackRequest, Issue, IssueResult

from ..usage_events import RequestCostSummary

from .classification import IssueClassifier

from .contracts import OperationalEvent, utc_now

from .ingestion import EventIngestionService

from .masking import mask_text, pseudonymous_actor_id

from .settings import OpsSettings

from .taxonomy import TaxonomyRepository



logger = logging.getLogger(__name__)





def _channel_scope(channel: str) -> str:

    if channel in {"playground", "msteams-web"}:

        return "playground"

    if channel.endswith("-channel"):

        return "channel"

    return "personal"





def _handoff_event_type(status: str) -> str:

    mapping = {

        "OFFERED": "handoff.offered",

        "CLOSED": "handoff.completed",

        "CANCELLED": "handoff.cancelled",

        "FAILED": "handoff.cancelled",

        "EXPIRED": "handoff.cancelled",

        "ROUTED_TO_TICKET": "handoff.completed",

    }

    return mapping.get(status, "handoff.started")





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



    async def emit_turn(

        self,

        payload: AgentRequest,

        state: dict[str, Any],

        *,

        cost_summary: RequestCostSummary | None,

    ) -> None:

        events = self.build_turn_events(payload, state, cost_summary=cost_summary)

        await self._ingestion.ingest_many(events)



    def schedule_turn(

        self,

        payload: AgentRequest,

        state: dict[str, Any],

        *,

        cost_summary: RequestCostSummary | None,

    ) -> None:

        asyncio.create_task(self.emit_turn(payload, state, cost_summary=cost_summary))



    async def emit_feedback(self, payload: FeedbackRequest) -> None:

        event = OperationalEvent(

            event_id=f"{payload.correlationId}:feedback:{payload.issueId or 'none'}:{payload.rating}",

            event_type="feedback.recorded",

            occurred_at=utc_now(),

            environment=self._settings.environment,  # type: ignore[arg-type]

            conversation_id=payload.conversationId,

            correlation_id=payload.correlationId,

            actor_ref=pseudonymous_actor_id(payload.userId),

            data_classification="CONFIDENTIAL",

            payload={

                "rating": payload.rating,

                "issueId": payload.issueId,

                "reason": payload.reason,

                "resolvedStatus": payload.resolvedStatus,

            },

        )

        await self._ingestion.ingest(event)



    def schedule_feedback(self, payload: FeedbackRequest) -> None:

        asyncio.create_task(self.emit_feedback(payload))



    def build_turn_events(

        self,

        payload: AgentRequest,

        state: dict[str, Any],

        *,

        cost_summary: RequestCostSummary | None,

    ) -> list[OperationalEvent]:

        correlation_id = str(state.get("correlation_id") or payload.correlationId or payload.requestId)

        conversation = state.get("conversation")

        conversation_id = getattr(conversation, "conversationId", None) or payload.conversation.conversationId

        turn_id = str(uuid.uuid4())

        actor_ref = pseudonymous_actor_id(payload.user.entraObjectId or payload.user.teamsUserId)

        masked_message = mask_text(payload.message.text)

        environment = self._settings.environment  # type: ignore[assignment]

        release_id = state.get("knowledge_release_id")

        base = {

            "environment": environment,

            "tenant_id": payload.conversation.tenantId,

            "team_id": payload.conversation.teamId,

            "channel_scope": _channel_scope(payload.channel),

            "conversation_id": conversation_id,

            "turn_id": turn_id,

            "request_id": payload.requestId,

            "correlation_id": correlation_id,

            "actor_ref": actor_ref,

        }

        events: list[OperationalEvent] = [

            OperationalEvent(

                event_id=f"{correlation_id}:turn.received",

                event_type="turn.received",

                occurred_at=utc_now(),

                data_classification="CONFIDENTIAL",

                payload={

                    "messageMasked": masked_message.text,

                    "messageWasMasked": masked_message.was_masked,

                    "locale": payload.message.locale,

                },

                **base,

            )

        ]

        if conversation_id and state.get("conversation_started") is True:

            events.append(

                OperationalEvent(

                    event_id=f"{conversation_id}:conversation.started",

                    event_type="conversation.started",

                    occurred_at=utc_now(),

                    data_classification="INTERNAL",

                    payload={},

                    **base,

                )

            )

        issues: list[Issue] = state.get("issues") or []

        issue_results: list[IssueResult] = state.get("issue_results") or []

        results_by_issue = {result.issueId: result for result in issue_results}

        for issue in issues:

            occurrence_id = f"{turn_id}:issue:{issue.id}"

            masked_description = mask_text(issue.description)

            classification = self._classifier.classify(

                issue.description,

                route=issue.route,

                faq_key=issue.faqKey,

            )

            events.extend(

                [

                    OperationalEvent(

                        event_id=f"{occurrence_id}:issue.extracted",

                        event_type="issue.extracted",

                        occurred_at=utc_now(),

                        issue_occurrence_id=occurrence_id,

                        issue_type_id=classification.issue_type_id,

                        taxonomy_version=self._taxonomy.version,

                        payload={

                            "issueId": issue.id,

                            "descriptionMasked": masked_description.text,

                            "descriptionRawLength": len(issue.description),

                            "readiness": issue.readiness,

                            "route": issue.route,

                            "faqKey": issue.faqKey,

                        },

                        **base,

                    ),

                    OperationalEvent(

                        event_id=f"{occurrence_id}:issue.classified",

                        event_type="issue.classified",

                        occurred_at=utc_now(),

                        issue_occurrence_id=occurrence_id,

                        issue_type_id=classification.issue_type_id,

                        taxonomy_version=self._taxonomy.version,

                        payload={

                            "classificationSource": classification.classification_source,

                            "confidenceStatus": classification.confidence_status,

                            "normalizedDescription": classification.normalized_description,

                            "issueId": issue.id,

                            "faqKey": issue.faqKey,

                            "descriptionRawLength": len(issue.description),

                        },

                        **base,

                    ),

                    OperationalEvent(

                        event_id=f"{occurrence_id}:route.selected",

                        event_type="route.selected",

                        occurred_at=utc_now(),

                        issue_occurrence_id=occurrence_id,

                        issue_type_id=classification.issue_type_id,

                        taxonomy_version=self._taxonomy.version,

                        payload={"route": issue.route},

                        **base,

                    ),

                ]

            )

            result = results_by_issue.get(issue.id)

            if result is not None:

                events.extend(

                    self._result_events(

                        result,

                        occurrence_id=occurrence_id,

                        issue_type_id=classification.issue_type_id,

                        release_id=release_id,

                        base=base,

                    )

                )

        if state.get("handoff_handled"):

            events.extend(self._handoff_events(state, base=base))

        if cost_summary is not None:

            events.append(

                OperationalEvent(

                    event_id=f"{correlation_id}:usage.recorded",

                    event_type="usage.recorded",

                    occurred_at=utc_now(),

                    data_classification="INTERNAL",

                    payload={

                        "outcome": cost_summary.outcome,

                        "totalTokens": cost_summary.total_tokens,

                        "estimatedCostUsd": cost_summary.estimated_cost_usd,

                        "costComplete": cost_summary.cost_complete,

                        "llmCallCount": cost_summary.llm_call_count,

                        "knowledgeBackend": cost_summary.knowledge_backend,

                    },

                    **base,

                )

            )

        if cost_summary is not None and cost_summary.outcome == "handoff":

            pass

        return events



    def _result_events(

        self,

        result: IssueResult,

        *,

        occurrence_id: str,

        issue_type_id: str,

        release_id: str | None,

        base: dict[str, object],

    ) -> list[OperationalEvent]:

        events: list[OperationalEvent] = []

        if result.resultType == "TICKET_CREATED":

            events.append(

                OperationalEvent(

                    event_id=f"{occurrence_id}:ticket.created",

                    event_type="ticket.created",

                    occurred_at=utc_now(),

                    issue_occurrence_id=occurrence_id,

                    issue_type_id=issue_type_id,

                    payload={"ticketId": result.ticketId, "backend": result.backend},

                    **base,

                )

            )

        elif result.resultType == "FAILED" and result.ticketId:

            events.append(

                OperationalEvent(

                    event_id=f"{occurrence_id}:ticket.failed",

                    event_type="ticket.failed",

                    occurred_at=utc_now(),

                    issue_occurrence_id=occurrence_id,

                    issue_type_id=issue_type_id,

                    payload={"error": result.error, "backend": result.backend},

                    **base,

                )

            )

        event_type = "answer.completed"

        payload_body: dict[str, object] = {

            "resultType": result.resultType,

            "backend": result.backend,

        }

        if result.resultType == "FAQ_ANSWERED":

            event_type = "faq.answered"

            payload_body["faqKey"] = getattr(result, "faqKey", None)

        elif result.resultType == "KNOWLEDGE_ANSWERED":

            citations = []

            for index, source in enumerate(result.sources or [], start=1):

                document_id = IssueClassifier.document_id_from_source_path(source.url)

                citations.append(

                    {

                        "rank": index,

                        "title": source.title,

                        "chunkId": source.chunkId,

                        "documentId": document_id,

                        "sourcePath": source.url,

                    }

                )

                events.append(

                    OperationalEvent(

                        event_id=f"{occurrence_id}:knowledge.retrieved:{index}",

                        event_type="knowledge.retrieved",

                        occurred_at=utc_now(),

                        issue_occurrence_id=occurrence_id,

                        issue_type_id=issue_type_id,

                        payload={

                            "rank": index,

                            "chunkId": source.chunkId,

                            "documentId": document_id,

                            "title": source.title,

                            "sourcePath": source.url,

                            "releaseId": release_id,

                        },

                        **base,

                    )

                )

            event_type = "knowledge.answered"

            payload_body["citations"] = citations

            payload_body["releaseId"] = release_id

            payload_body["sourceCount"] = len(citations)

        events.append(

            OperationalEvent(

                event_id=f"{occurrence_id}:{event_type}",

                event_type=event_type,  # type: ignore[arg-type]

                occurred_at=utc_now(),

                issue_occurrence_id=occurrence_id,

                issue_type_id=issue_type_id,

                payload=payload_body,

                **base,

            )

        )

        return events



    def _handoff_events(self, state: dict[str, Any], *, base: dict[str, object]) -> list[OperationalEvent]:

        handoff_case = state.get("handoff_case")

        if handoff_case is None:

            return [

                OperationalEvent(

                    event_id=f"{base['correlation_id']}:handoff.offered",

                    event_type="handoff.offered",

                    occurred_at=utc_now(),

                    data_classification="CONFIDENTIAL",

                    payload={"reason": "handoff_handled"},

                    **base,

                )

            ]

        status = getattr(handoff_case, "status", "OFFERED")

        status_value = status.value if hasattr(status, "value") else str(status)

        event_type = _handoff_event_type(status_value)  # type: ignore[arg-type]

        return [

            OperationalEvent(

                event_id=f"{getattr(handoff_case, 'caseId', base['correlation_id'])}:{event_type}",

                event_type=event_type,

                occurred_at=utc_now(),

                data_classification="CONFIDENTIAL",

                payload={

                    "caseId": getattr(handoff_case, "caseId", None),

                    "status": status_value,

                    "providerMode": getattr(handoff_case, "providerMode", None),

                },

                **base,

            )

        ]


