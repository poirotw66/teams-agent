"""Negative authorization coverage for operational event scope."""

from __future__ import annotations

from pathlib import Path

from agent_service.operations.access import ActorContext
from agent_service.operations.contracts import OperationalEvent, utc_now
from agent_service.operations.scope import filter_events_by_scope
from agent_service.operations.taxonomy import TaxonomyRepository


def _taxonomy() -> TaxonomyRepository:
    data_dir = Path(__file__).resolve().parents[2] / "data"
    return TaxonomyRepository(data_dir / "ops" / "issue_taxonomy_v1.json")


def _event(**kwargs: object) -> OperationalEvent:
    base = {
        "event_id": "evt",
        "event_type": "issue.extracted",
        "occurred_at": utc_now(),
        "correlation_id": "corr",
        "payload": {},
    }
    base.update(kwargs)
    return OperationalEvent(**base)  # type: ignore[arg-type]


def test_scope_does_not_inherit_foreign_unit_via_conversation() -> None:
    taxonomy = _taxonomy()
    actor = ActorContext(
        user_id="owner-a",
        display_name="Owner A",
        role="SERVICE_OWNER",
        owner_unit_ids=("IT Service Desk",),
        tenant_id="tenant-a",
    )
    events = [
        _event(
            event_id="a-issue",
            conversation_id="shared-conv",
            turn_id="turn-a",
            correlation_id="corr-a",
            tenant_id="tenant-a",
            issue_type_id="vpn.connection_failed",
        ),
        _event(
            event_id="b-issue",
            conversation_id="shared-conv",
            turn_id="turn-b",
            correlation_id="corr-b",
            tenant_id="tenant-a",
            issue_type_id="security.phishing_report",
        ),
        _event(
            event_id="b-turn",
            event_type="turn.received",
            conversation_id="shared-conv",
            turn_id="turn-b",
            correlation_id="corr-b",
            tenant_id="tenant-a",
            payload={"messageMasked": "phishing body"},
        ),
        _event(
            event_id="a-feedback",
            event_type="feedback.recorded",
            conversation_id="shared-conv",
            correlation_id="corr-a",
            tenant_id="tenant-a",
            payload={"rating": "DOWN"},
        ),
    ]
    scoped_ids = {event.event_id for event in filter_events_by_scope(events, actor, taxonomy)}
    assert scoped_ids == {"a-issue", "a-feedback"}


def test_scope_blocks_cross_tenant_even_same_unit_and_conversation() -> None:
    taxonomy = _taxonomy()
    actor = ActorContext(
        user_id="owner-a",
        display_name="Owner A",
        role="SERVICE_OWNER",
        owner_unit_ids=("IT Service Desk",),
        tenant_id="tenant-a",
    )
    events = [
        _event(
            event_id="local",
            conversation_id="shared-conv",
            turn_id="turn-1",
            tenant_id="tenant-a",
            issue_type_id="vpn.connection_failed",
        ),
        _event(
            event_id="foreign-tenant",
            conversation_id="shared-conv",
            turn_id="turn-1",
            tenant_id="tenant-b",
            issue_type_id="vpn.connection_failed",
        ),
        _event(
            event_id="foreign-turn",
            event_type="turn.received",
            conversation_id="shared-conv",
            turn_id="turn-1",
            tenant_id="tenant-b",
            payload={"messageMasked": "leak"},
        ),
    ]
    scoped_ids = {event.event_id for event in filter_events_by_scope(events, actor, taxonomy)}
    assert scoped_ids == {"local"}


def test_scope_allows_same_turn_companion_without_owner_unit() -> None:
    taxonomy = _taxonomy()
    actor = ActorContext(
        user_id="owner-a",
        display_name="Owner A",
        role="ANALYST",
        owner_unit_ids=("IT Service Desk",),
        tenant_id="tenant-a",
    )
    events = [
        _event(
            event_id="issue-1",
            conversation_id="conv-1",
            turn_id="turn-1",
            correlation_id="corr-1",
            tenant_id="tenant-a",
            issue_type_id="vpn.connection_failed",
        ),
        _event(
            event_id="turn-1",
            event_type="turn.received",
            conversation_id="conv-1",
            turn_id="turn-1",
            correlation_id="corr-1",
            tenant_id="tenant-a",
            payload={"messageMasked": "hello"},
        ),
        _event(
            event_id="other-turn",
            event_type="turn.received",
            conversation_id="conv-1",
            turn_id="turn-2",
            correlation_id="corr-2",
            tenant_id="tenant-a",
            payload={"messageMasked": "later"},
        ),
    ]
    scoped_ids = {event.event_id for event in filter_events_by_scope(events, actor, taxonomy)}
    assert scoped_ids == {"issue-1", "turn-1"}


def test_scope_requires_actor_tenant_binding() -> None:
    taxonomy = _taxonomy()
    actor = ActorContext(
        user_id="owner-a",
        display_name="Owner A",
        role="SERVICE_OWNER",
        owner_unit_ids=("IT Service Desk",),
        tenant_id=None,
    )
    events = [
        _event(
            event_id="local",
            tenant_id="tenant-a",
            issue_type_id="vpn.connection_failed",
        )
    ]
    assert filter_events_by_scope(events, actor, taxonomy) == []
