"""Operational event emitter facade with stable public re-exports."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from ..contracts import AgentRequest, FeedbackRequest
from ..usage_events import RequestCostSummary
from .classification import IssueClassifier
from .contracts import OperationalEvent
from .emitter_channel import _channel_scope, channel_scope, is_teams_channel
from .emitter_exceptions import (
    OperationalEventReplayConflict,
    OperationalEventReplayDuplicate,
)
from .emitter_feedback import FeedbackEventCache, FeedbackProvenanceMap
from .emitter_feedback import build_feedback_event as _build_feedback_event
from .emitter_feedback import emit_feedback as _emit_feedback
from .emitter_replay import ReplayFingerprintStore
from .emitter_results import result_payloads
from .emitter_source import safe_source
from .emitter_turn import build_turn_events as _build_turn_events
from .emitter_turn import occurred_at as _occurred_at
from .emitter_turn import validate_usage_scope as _validate_usage_scope
from .event_identity import LogicalRequestIdentity
from .ingestion import EventIngestionService
from .settings import OpsSettings
from .taxonomy import TaxonomyRepository

__all__ = [
    "OperationalEventEmitter",
    "OperationalEventReplayConflict",
    "OperationalEventReplayDuplicate",
    "_channel_scope",
    "channel_scope",
]


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
        self._replay = ReplayFingerprintStore()
        self._feedback_provenance: FeedbackProvenanceMap = {}
        self._feedback_events: FeedbackEventCache = {}

    @staticmethod
    def _occurred_at(state: dict[str, Any], conversation: object | None) -> datetime:
        return _occurred_at(state, conversation)

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
        self._replay.assert_immutable(
            request_key,
            request_fact,
            events,
            call_ids=call_ids,
            usage_fact=usage_fact,
            final_usage=final_usage,
        )

    async def emit_turn(
        self,
        payload: AgentRequest,
        state: dict[str, Any],
        *,
        cost_summary: RequestCostSummary | None,
    ) -> None:
        try:
            events = self.build_turn_events(payload, state, cost_summary=cost_summary)
        except OperationalEventReplayDuplicate:
            return
        conversation_id = (
            getattr(state.get("conversation"), "conversationId", None)
            or payload.conversation.conversationId
        )
        request_key = LogicalRequestIdentity(
            payload.conversation.tenantId, conversation_id, payload.requestId
        ).value
        try:
            await self._ingestion.ingest_many(events)
        except Exception:
            self._replay.clear_final_usage(request_key)
            raise

    def schedule_turn(
        self,
        payload: AgentRequest,
        state: dict[str, Any],
        *,
        cost_summary: RequestCostSummary | None,
    ) -> None:
        # Build synchronously to validate provenance and freeze the completed
        # fact image before a caller can mutate the collector/state.
        try:
            events = self.build_turn_events(payload, state, cost_summary=cost_summary)
        except OperationalEventReplayDuplicate:
            return
        conversation_id = (
            getattr(state.get("conversation"), "conversationId", None)
            or payload.conversation.conversationId
        )
        request_key = LogicalRequestIdentity(
            payload.conversation.tenantId, conversation_id, payload.requestId
        ).value

        async def _ingest_with_rollback() -> None:
            try:
                await self._ingestion.ingest_many(events)
            except Exception:
                self._replay.clear_final_usage(request_key)
                raise

        asyncio.create_task(_ingest_with_rollback())

    def build_feedback_event(
        self,
        payload: FeedbackRequest,
        *,
        tenant_id: str | None = None,
        feedback_id: str | None = None,
        occurred_at: datetime | None = None,
        actor_id: str | None = None,
        request_id: str | None = None,
    ) -> OperationalEvent:
        return _build_feedback_event(
            payload=payload,
            settings=self._settings,
            replay=self._replay,
            feedback_provenance=self._feedback_provenance,
            feedback_events=self._feedback_events,
            tenant_id=tenant_id,
            feedback_id=feedback_id,
            occurred_at=occurred_at,
            actor_id=actor_id,
            request_id=request_id,
        )

    async def emit_feedback(self, payload: FeedbackRequest, **provenance: Any) -> None:
        await _emit_feedback(
            payload=payload,
            settings=self._settings,
            ingestion=self._ingestion,
            replay=self._replay,
            feedback_provenance=self._feedback_provenance,
            feedback_events=self._feedback_events,
            provenance=provenance,
        )

    def schedule_feedback(self, payload: FeedbackRequest, **provenance: Any) -> None:
        asyncio.create_task(self.emit_feedback(payload, **provenance))

    def build_turn_events(
        self,
        payload: AgentRequest,
        state: dict[str, Any],
        *,
        cost_summary: RequestCostSummary | None,
    ) -> list[OperationalEvent]:
        return _build_turn_events(
            payload=payload,
            state=state,
            cost_summary=cost_summary,
            settings=self._settings,
            classifier=self._classifier,
            taxonomy=self._taxonomy,
            replay=self._replay,
            feedback_provenance=self._feedback_provenance,
        )

    def _validate_usage_scope(
        self, usage: Any, request: AgentRequest, correlation_id: str,
    ) -> None:
        _validate_usage_scope(usage, request, correlation_id, self._settings.environment)

    @staticmethod
    def _result_payloads(
        result: Any, release_id: str | None,
    ) -> list[tuple[str, dict[str, Any], object]]:
        return result_payloads(result, release_id)


# Keep private helpers importable for tests and historical call sites.
_is_teams_channel = is_teams_channel
_safe_source = safe_source
