#!/usr/bin/env python3
"""Live verification probe for AI Ops operational stores (Phase 0).

Validates assumptions that unit tests with in-memory fakes cannot prove:

1. Firestore operational event writes persist ``retention_expires_at`` as a
   timestamp field suitable for TTL policies.
2. Period-filtered reads using ``order_by(occurred_at)`` plus range filters
   succeed without requiring an undeclared composite index.
3. BigQuery ``insert_rows_json`` accepts the schema-aligned row shape emitted
   by ``BigQueryEventSink``.
4. A second client instance can read events written by the first (Cloud Run
   scale-to-zero / multi-instance visibility).

All data is written to throwaway collection/table prefixes and deleted on exit.

Usage:
    gcloud auth application-default login
    cd agent_service
    uv run --extra firestore --extra bigquery python ../scripts/ops_gcp_verification.py --project YOUR_PROJECT

Requires google-cloud-firestore and google-cloud-bigquery (firestore extra).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import secrets
import sys
import time
from datetime import timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "agent_service" / "src"))

from agent_service.operations.audit import build_audit_event
from agent_service.operations.audit_stores import FirestoreAuditStore
from agent_service.operations.contracts import OperationalEvent, utc_now
from agent_service.operations.retention import retention_expiry
from agent_service.operations.settings import OpsSettings
from agent_service.operations.stores.bigquery_sink import BigQueryEventSink, build_bigquery_client
from agent_service.operations.stores.firestore_store import FirestoreOperationalStore, build_firestore_client


class Results:
    def __init__(self) -> None:
        self.checks: list[tuple[str, bool, str]] = []

    def record(self, name: str, passed: bool, detail: str = "") -> None:
        self.checks.append((name, passed, detail))
        marker = "PASS" if passed else "FAIL"
        print(f"  [{marker}] {name}{f' -- {detail}' if detail else ''}")

    @property
    def failed(self) -> int:
        return sum(1 for _, passed, _ in self.checks if not passed)

    def to_dict(self, *, project: str, database: str | None, dataset: str) -> dict[str, object]:
        return {
            "project": project,
            "database": database,
            "dataset": dataset,
            "passed": self.failed == 0,
            "failureCount": self.failed,
            "checks": [
                {"name": name, "passed": passed, "detail": detail}
                for name, passed, detail in self.checks
            ],
        }


async def verify_firestore(project: str, database: str | None, results: Results) -> str:
    suffix = f"verify_{int(time.time())}_{secrets.token_hex(4)}"
    events_collection = f"ops_verify_events_{suffix}"
    audit_collection = f"ops_verify_audit_{suffix}"

    client = build_firestore_client(project, database)
    store = FirestoreOperationalStore(client, events_collection)
    audit_store = FirestoreAuditStore(client, audit_collection)
    settings = OpsSettings.from_env()
    now = utc_now()
    event = OperationalEvent(
        event_id=f"{suffix}:turn.received",
        event_type="turn.received",
        occurred_at=now,
        correlation_id=f"corr-{suffix}",
        conversation_id=f"conv-{suffix}",
        retention_expires_at=retention_expiry(settings),
        payload={"messageMasked": "verification probe"},
    )

    inserted = await store.append(event)
    results.record("firestore append is idempotent on first write", inserted is True)
    duplicate = await store.append(event)
    results.record("firestore append rejects duplicate event_id", duplicate is False)

    page, _ = await store.list_events(since=now - timedelta(hours=1))
    results.record(
        "firestore period-filtered list returns written event",
        any(item.event_id == event.event_id for item in page),
        f"count={len(page)}",
    )
    if page:
        stored = page[0]
        ttl_ok = stored.retention_expires_at is not None
        results.record("firestore retention_expires_at round-trips", ttl_ok)

    audit_event = build_audit_event(
        actor_id="verify.ops",
        actor_role="SYSTEM_ADMIN",
        action="verify.append",
        target_type="operational_event",
        target_id=event.event_id,
        environment="dev",
    )
    await audit_store.append(audit_event)
    audit_page, _ = await audit_store.list_events(limit=5)
    results.record(
        "firestore audit retention_expires_at is persisted",
        bool(audit_page) and audit_page[0].retention_expires_at is not None,
    )

    second_client = build_firestore_client(project, database)
    second_store = FirestoreOperationalStore(second_client, events_collection)
    second_page, _ = await second_store.list_events(limit=10)
    results.record(
        "second firestore client sees first client's event",
        any(item.event_id == event.event_id for item in second_page),
    )

    for doc_id in [event.event_id, audit_event.audit_id]:
        await client.collection(events_collection).document(doc_id).delete()
        await client.collection(audit_collection).document(doc_id).delete()
    return suffix


async def verify_bigquery(project: str, dataset: str, results: Results, suffix: str) -> None:
    from google.cloud import bigquery

    client = build_bigquery_client(project)
    dataset_id = f"{project}.{dataset}"
    try:
        client.get_dataset(dataset_id)
    except Exception:
        dataset_ref = bigquery.Dataset(dataset_id)
        dataset_ref.location = "asia-east1"
        client.create_dataset(dataset_ref, exists_ok=True)
        results.record("bigquery dataset exists or was created", True, dataset_id)
    table_name = f"ops_verify_{suffix}"
    table_id = f"{project}.{dataset}.{table_name}"
    client.delete_table(table_id, not_found_ok=True)
    table = bigquery.Table(
        table_id,
        schema=[
            bigquery.SchemaField("event_id", "STRING", mode="REQUIRED"),
            bigquery.SchemaField("event_type", "STRING", mode="REQUIRED"),
            bigquery.SchemaField("occurred_at", "TIMESTAMP", mode="REQUIRED"),
            bigquery.SchemaField("conversation_id", "STRING"),
            bigquery.SchemaField("correlation_id", "STRING"),
            bigquery.SchemaField("issue_type_id", "STRING"),
            bigquery.SchemaField("payload", "JSON"),
        ],
    )
    client.create_table(table)
    sink = BigQueryEventSink(client, dataset, table_name)
    event = OperationalEvent(
        event_id=f"{suffix}:usage.recorded",
        event_type="usage.recorded",
        occurred_at=utc_now(),
        correlation_id=f"corr-{suffix}",
        payload={"estimatedCostUsd": 0.01, "pricingVersion": "v1"},
    )
    await sink.append(event)
    rows = list(
        client.query(
            f"SELECT event_id FROM `{table_id}` WHERE event_id = @event_id",
            job_config=bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("event_id", "STRING", event.event_id),
                ]
            ),
        ).result()
    )
    results.record(
        "bigquery sink row is queryable",
        any(row.event_id == event.event_id for row in rows),
    )
    client.delete_table(table_id, not_found_ok=True)


async def verify_log_sinks(project: str, results: Results) -> None:
    import subprocess

    expected_sinks = {
        "ai-ops-backoffice-logs": "teams-ai-ops-backoffice",
        "ai-ops-agent-logs": "teams-rag-agent",
    }
    for sink_name, service_name in expected_sinks.items():
        try:
            completed = subprocess.run(
                [
                    "gcloud",
                    "logging",
                    "sinks",
                    "describe",
                    sink_name,
                    f"--project={project}",
                    "--format=json",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            if completed.returncode != 0:
                results.record(
                    f"log sink {sink_name} exists",
                    False,
                    completed.stderr.strip() or completed.stdout.strip(),
                )
                continue
            payload = json.loads(completed.stdout)
            destination = payload.get("destination", "")
            writer = payload.get("writerIdentity", "")
            filter_text = payload.get("filter", "")
            ok = (
                "bigquery.googleapis.com" in destination
                and service_name in filter_text
                and bool(writer)
            )
            results.record(
                f"log sink {sink_name} routes to BigQuery",
                ok,
                destination,
            )
        except Exception as exc:  # noqa: BLE001
            results.record(f"log sink {sink_name} verification", False, str(exc))


async def run(
    project: str,
    database: str | None,
    dataset: str,
    *,
    report_path: Path | None,
) -> int:
    results = Results()
    print(f"AI Ops GCP verification (project={project})")
    suffix = await verify_firestore(project, database, results)
    try:
        await verify_bigquery(project, dataset, results, suffix)
    except Exception as exc:  # noqa: BLE001
        results.record("bigquery verification", False, str(exc))
    try:
        await verify_log_sinks(project, results)
    except Exception as exc:  # noqa: BLE001
        results.record("log sink verification", False, str(exc))
    if report_path is not None:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(results.to_dict(project=project, database=database, dataset=dataset), indent=2),
            encoding="utf-8",
        )
        print(f"Wrote verification report to {report_path}")
    print(f"\nCompleted with {results.failed} failure(s).")
    return 1 if results.failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify AI Ops Firestore/BigQuery contracts.")
    parser.add_argument("--project", required=True)
    parser.add_argument("--database", default=None)
    parser.add_argument("--dataset", default="ai_ops_analytics")
    parser.add_argument(
        "--report",
        default=None,
        help="Optional path to write JSON verification results.",
    )
    args = parser.parse_args()
    report_path = Path(args.report) if args.report else None
    try:
        return asyncio.run(
            run(
                args.project,
                args.database,
                args.dataset,
                report_path=report_path,
            )
        )
    except Exception as exc:  # noqa: BLE001
        print(f"GCP verification aborted: {exc}", file=sys.stderr)
        if report_path is not None:
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(
                json.dumps(
                    {
                        "project": args.project,
                        "database": args.database,
                        "dataset": args.dataset,
                        "passed": False,
                        "failureCount": 1,
                        "checks": [
                            {
                                "name": "gcp verification bootstrap",
                                "passed": False,
                                "detail": str(exc),
                            }
                        ],
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            print(f"Wrote verification report to {report_path}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
