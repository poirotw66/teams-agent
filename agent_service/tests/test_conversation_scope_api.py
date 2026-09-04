"""Negative authorization for conversation detail query path."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agent_service.operations.access import ActorContext
from agent_service.operations.contracts import OperationalEvent, utc_now
from agent_service.operations.taxonomy import TaxonomyRepository
from ai_ops_backoffice.services.query_service import BackofficeQueryService


@pytest.mark.asyncio
async def test_conversation_detail_hides_cross_unit_and_cross_tenant_events() -> None:
    data_dir = Path(__file__).resolve().parents[2] / "data"
    taxonomy = TaxonomyRepository(data_dir / "ops" / "issue_taxonomy_v1.json")
    now = utc_now()
    events = [
        OperationalEvent(
            event_id="a-issue",
            event_type="issue.extracted",
            occurred_at=now,
            conversation_id="shared-conv",
            turn_id="turn-a",
            tenant_id="local-development",
            correlation_id="c1",
            issue_type_id="vpn.connection_failed",
            payload={},
        ),
        OperationalEvent(
            event_id="b-issue",
            event_type="issue.extracted",
            occurred_at=now,
            conversation_id="shared-conv",
            turn_id="turn-b",
            tenant_id="local-development",
            correlation_id="c2",
            issue_type_id="security.phishing_report",
            payload={},
        ),
        OperationalEvent(
            event_id="foreign-tenant",
            event_type="issue.extracted",
            occurred_at=now,
            conversation_id="shared-conv",
            turn_id="turn-c",
            tenant_id="other-tenant",
            correlation_id="c3",
            issue_type_id="vpn.connection_failed",
            payload={},
        ),
        OperationalEvent(
            event_id="a-turn",
            event_type="turn.received",
            occurred_at=now,
            conversation_id="shared-conv",
            turn_id="turn-a",
            tenant_id="local-development",
            correlation_id="c1",
            payload={"messageMasked": "vpn help"},
        ),
        OperationalEvent(
            event_id="b-turn",
            event_type="turn.received",
            occurred_at=now,
            conversation_id="shared-conv",
            turn_id="turn-b",
            tenant_id="local-development",
            correlation_id="c2",
            payload={"messageMasked": "phishing"},
        ),
    ]
    query = object.__new__(BackofficeQueryService)
    query._runtime = SimpleNamespace(taxonomy=taxonomy)
    query._events = AsyncMock(return_value=events)
    actor = ActorContext(
        user_id="owner-a",
        display_name="Owner A",
        role="SERVICE_OWNER",
        owner_unit_ids=("IT Service Desk",),
        tenant_id="local-development",
    )
    detail = await query.conversation_detail(actor, "shared-conv")
    assert detail is not None
    turn_ids = {turn["turnId"] for turn in detail["turns"]}
    assert turn_ids == {"turn-a"}
    related_issue_types = {
        item.get("issueTypeId")
        for turn in detail["turns"]
        for item in turn.get("events", [])
    }
    assert "vpn.connection_failed" in related_issue_types
    assert "security.phishing_report" not in related_issue_types


@pytest.mark.asyncio
async def test_conversation_detail_hides_mixed_turn_shared_message() -> None:
    data_dir = Path(__file__).resolve().parents[2] / "data"
    taxonomy = TaxonomyRepository(data_dir / "ops" / "issue_taxonomy_v1.json")
    now = utc_now()
    events = [
        OperationalEvent(
            event_id="a-issue",
            event_type="issue.extracted",
            occurred_at=now,
            conversation_id="mixed-conv",
            turn_id="turn-mixed",
            tenant_id="local-development",
            correlation_id="corr-mixed",
            issue_type_id="vpn.connection_failed",
            payload={
                "issueId": "issue-a",
                "descriptionMasked": "VPN 無法連線",
            },
        ),
        OperationalEvent(
            event_id="b-issue",
            event_type="issue.extracted",
            occurred_at=now,
            conversation_id="mixed-conv",
            turn_id="turn-mixed",
            tenant_id="local-development",
            correlation_id="corr-mixed",
            issue_type_id="security.phishing_report",
            payload={
                "issueId": "issue-b",
                "descriptionMasked": "釣魚信內容不應外洩",
            },
        ),
        OperationalEvent(
            event_id="mixed-turn",
            event_type="turn.received",
            occurred_at=now,
            conversation_id="mixed-conv",
            turn_id="turn-mixed",
            tenant_id="local-development",
            correlation_id="corr-mixed",
            payload={
                "messageMasked": "VPN 無法連線；另外這是釣魚信內容不應外洩",
                "maskingPolicyVersion": "v2",
            },
        ),
    ]
    query = object.__new__(BackofficeQueryService)
    query._runtime = SimpleNamespace(taxonomy=taxonomy)
    query._events = AsyncMock(return_value=events)
    actor = ActorContext(
        user_id="owner-a",
        display_name="Owner A",
        role="SERVICE_OWNER",
        owner_unit_ids=("IT Service Desk",),
        tenant_id="local-development",
    )
    detail = await query.conversation_detail(actor, "mixed-conv")
    assert detail is not None
    assert len(detail["turns"]) == 1
    turn = detail["turns"][0]
    assert turn["messageMasked"] is None
    assert turn["messageHidden"] is True
    assert turn["messageHiddenReason"] == "MIXED_OWNER_UNIT_TURN"
    assert turn["authorizedFragments"] == [
        {
            "issueTypeId": "vpn.connection_failed",
            "descriptionMasked": "VPN 無法連線",
            "issueId": "issue-a",
        }
    ]
    related_issue_types = {item.get("issueTypeId") for item in turn["events"]}
    assert related_issue_types == {"vpn.connection_failed"}
    serialized = str(detail)
    assert "釣魚" not in serialized
    assert "phishing" not in serialized.lower()
