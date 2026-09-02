#!/usr/bin/env python3
"""Seed LAB Firestore with UAT demo operational events.

Writes a small, idempotent conversation trail that powers the negative-feedback
drill-down acceptance scenario on the live backoffice.

Usage:
    cd agent_service
    OPS_STORE_MODE=FIRESTORE \
    OPS_FIRESTORE_PROJECT=itr-aimasteryhub-lab \
    AGENT_DEPLOYMENT_ENV=poc \
    uv run python ../scripts/ops_seed_lab_demo.py
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "agent_service" / "src"))

from agent_service.operations.contracts import OperationalEvent, utc_now
from agent_service.operations.ingestion import EventIngestionService
from agent_service.operations.settings import OpsSettings
from agent_service.operations.stores.firestore_store import (
    FirestoreOperationalStore,
    build_firestore_client,
)


def _demo_events(prefix: str) -> list[OperationalEvent]:
    now = utc_now()
    turn_id = f"{prefix}:turn-1"
    occurrence_id = f"{turn_id}:issue:1"
    base = {
        "conversation_id": f"{prefix}:conv-1",
        "correlation_id": f"{prefix}:corr-1",
        "turn_id": turn_id,
        "environment": "poc",
    }
    return [
        OperationalEvent(
            event_id=f"{prefix}:turn.received",
            event_type="turn.received",
            occurred_at=now,
            actor_ref="user-demo-vpn-001",
            payload={
                "messageMasked": "VPN 連線失敗",
                "maskingPolicyVersion": "v1",
            },
            **base,
        ),
        OperationalEvent(
            event_id=f"{occurrence_id}:issue.extracted",
            event_type="issue.extracted",
            occurred_at=now,
            issue_occurrence_id=occurrence_id,
            issue_type_id="vpn.connection_failed",
            payload={
                "issueId": 1,
                "descriptionMasked": "VPN 連線失敗",
                "route": "KNOWLEDGE",
            },
            **base,
        ),
        OperationalEvent(
            event_id=f"{occurrence_id}:issue.classified",
            event_type="issue.classified",
            occurred_at=now,
            issue_occurrence_id=occurrence_id,
            issue_type_id="vpn.connection_failed",
            payload={"classificationSource": "MODEL"},
            **base,
        ),
        OperationalEvent(
            event_id=f"{occurrence_id}:route.selected",
            event_type="route.selected",
            occurred_at=now,
            issue_occurrence_id=occurrence_id,
            issue_type_id="vpn.connection_failed",
            payload={"route": "KNOWLEDGE"},
            **base,
        ),
        OperationalEvent(
            event_id=f"{occurrence_id}:knowledge.retrieved:1",
            event_type="knowledge.retrieved",
            occurred_at=now,
            issue_occurrence_id=occurrence_id,
            issue_type_id="vpn.connection_failed",
            payload={
                "documentId": "vpn-password-lockout",
                "chunkId": "chunk-1",
                "releaseId": "release-2025-09-01",
            },
            **base,
        ),
        OperationalEvent(
            event_id=f"{occurrence_id}:knowledge.answered",
            event_type="knowledge.answered",
            occurred_at=now,
            issue_occurrence_id=occurrence_id,
            issue_type_id="vpn.connection_failed",
            payload={
                "resultType": "KNOWLEDGE_ANSWERED",
                "answerMasked": "請確認 VPN 密碼未鎖定後再試一次。",
                "documentId": "vpn-password-lockout",
                "releaseId": "release-2025-09-01",
            },
            **base,
        ),
        OperationalEvent(
            event_id=f"{prefix}:feedback:1:DOWN",
            event_type="feedback.recorded",
            occurred_at=now + timedelta(minutes=1),
            payload={
                "rating": "DOWN",
                "issueId": 1,
                "reason": "wrong_answer",
                "resolvedStatus": "UNRESOLVED",
            },
            conversation_id=base["conversation_id"],
            correlation_id=base["correlation_id"],
            environment="poc",
        ),
        OperationalEvent(
            event_id=f"{prefix}:handoff.offered",
            event_type="handoff.offered",
            occurred_at=now + timedelta(minutes=2),
            payload={"status": "OFFERED"},
            conversation_id=base["conversation_id"],
            correlation_id=base["correlation_id"],
            environment="poc",
        ),
        OperationalEvent(
            event_id=f"{prefix}:usage:1",
            event_type="usage.recorded",
            occurred_at=now + timedelta(minutes=3),
            issue_type_id="vpn.connection_failed",
            payload={
                "model": "gpt-4.1",
                "provider": "openai",
                "inputTokens": 120,
                "outputTokens": 45,
                "estimatedCostUsd": 0.0025,
                "pricingVersion": "v1",
                "llmCallCount": 1,
            },
            conversation_id=base["conversation_id"],
            correlation_id=base["correlation_id"],
            environment="poc",
        ),
    ]


async def seed(project: str, database: str | None, collection: str, prefix: str) -> int:
    settings = OpsSettings.from_env()
    if settings.store_mode != "FIRESTORE":
        settings = OpsSettings(
            enabled=True,
            store_mode="FIRESTORE",
            store_path=settings.store_path,
            taxonomy_path=settings.taxonomy_path,
            metrics_path=settings.metrics_path,
            classification_rules_path=settings.classification_rules_path,
            environment=settings.environment,
            default_retention_days=settings.default_retention_days,
            transcript_retention_days=settings.transcript_retention_days,
            audit_retention_days=settings.audit_retention_days,
            async_emit=settings.async_emit,
            firestore_project=project,
            firestore_database=database,
            firestore_collection=collection,
            bigquery_enabled=False,
            bigquery_project=project,
            bigquery_dataset=settings.bigquery_dataset,
            bigquery_table=settings.bigquery_table,
            audit_store_mode=settings.audit_store_mode,
            audit_firestore_collection=settings.audit_firestore_collection,
        )

    client = build_firestore_client(settings.firestore_project, settings.firestore_database)
    store = FirestoreOperationalStore(client, settings.firestore_collection)
    ingestion = EventIngestionService(store, settings)
    events = _demo_events(prefix)
    inserted = await ingestion.ingest_many(events)
    skipped = len(events) - inserted
    print(
        f"Seeded LAB demo events into {project}/{collection}: "
        f"inserted={inserted}, skipped={skipped}, prefix={prefix}"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed LAB Firestore with UAT demo events.")
    parser.add_argument("--project", default="itr-aimasteryhub-lab")
    parser.add_argument("--database", default=None)
    parser.add_argument("--collection", default="operational_events")
    parser.add_argument("--prefix", default="lab-demo-v1", help="Idempotent event id prefix.")
    args = parser.parse_args()
    return asyncio.run(seed(args.project, args.database, args.collection, args.prefix))


if __name__ == "__main__":
    raise SystemExit(main())
