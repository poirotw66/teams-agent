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
    scoped = filter_events_by_scope(events, actor, taxonomy)
    scoped_ids = {event.event_id for event in scoped}
    assert scoped_ids == {"issue-1", "turn-1"}
    turn = next(event for event in scoped if event.event_id == "turn-1")
    assert turn.payload.get("messageMasked") == "hello"
    assert "messageHidden" not in turn.payload


def test_scope_redacts_shared_message_on_mixed_owner_turn() -> None:
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
            turn_id="turn-mixed",
            correlation_id="corr-mixed",
            tenant_id="tenant-a",
            issue_type_id="vpn.connection_failed",
            payload={
                "issueId": "issue-a",
                "descriptionMasked": "VPN 無法連線",
            },
        ),
        _event(
            event_id="b-issue",
            conversation_id="shared-conv",
            turn_id="turn-mixed",
            correlation_id="corr-mixed",
            tenant_id="tenant-a",
            issue_type_id="security.phishing_report",
            payload={
                "issueId": "issue-b",
                "descriptionMasked": "釣魚信內容不應外洩",
            },
        ),
        _event(
            event_id="mixed-turn",
            event_type="turn.received",
            conversation_id="shared-conv",
            turn_id="turn-mixed",
            correlation_id="corr-mixed",
            tenant_id="tenant-a",
            payload={
                "messageMasked": "VPN 無法連線；另外這是釣魚信內容不應外洩",
                "messageWasMasked": False,
            },
        ),
    ]
    scoped = filter_events_by_scope(events, actor, taxonomy)
    scoped_by_id = {event.event_id: event for event in scoped}
    assert set(scoped_by_id) == {"a-issue", "mixed-turn"}
    assert "b-issue" not in scoped_by_id
    turn = scoped_by_id["mixed-turn"]
    assert "messageMasked" not in turn.payload
    assert turn.payload["messageHidden"] is True
    assert turn.payload["messageHiddenReason"] == "MIXED_OWNER_UNIT_TURN"
    assert "釣魚" not in str(turn.payload)


def test_ai_admin_is_tenant_bound_but_cross_unit() -> None:
    taxonomy = _taxonomy()
    actor = ActorContext(
        user_id="ai-admin",
        display_name="AI Admin",
        role="AI_ADMIN",
        owner_unit_ids=(),
        tenant_id="tenant-a",
    )
    events = [
        _event(
            event_id="local-security",
            tenant_id="tenant-a",
            issue_type_id="security.phishing_report",
        ),
        _event(
            event_id="foreign-tenant",
            tenant_id="tenant-b",
            issue_type_id="vpn.connection_failed",
        ),
    ]
    scoped_ids = {event.event_id for event in filter_events_by_scope(events, actor, taxonomy)}
    assert scoped_ids == {"local-security"}


def test_system_admin_may_cross_tenant() -> None:
    taxonomy = _taxonomy()
    actor = ActorContext(
        user_id="sysadmin",
        display_name="Sys",
        role="SYSTEM_ADMIN",
        owner_unit_ids=(),
        tenant_id="tenant-a",
    )
    events = [
        _event(
            event_id="local",
            tenant_id="tenant-a",
            issue_type_id="vpn.connection_failed",
        ),
        _event(
            event_id="foreign",
            tenant_id="tenant-b",
            issue_type_id="security.phishing_report",
        ),
    ]
    scoped_ids = {event.event_id for event in filter_events_by_scope(events, actor, taxonomy)}
    assert scoped_ids == {"local", "foreign"}


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
