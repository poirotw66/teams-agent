from __future__ import annotations

import asyncio
import json
from typing import Any

from ..contracts import OperationalEvent
from ..delivery.journal import DeliveryError

class BigQueryDeliveryError(DeliveryError):
    """Sanitized typed failure. Raw SDK errors and rows must not escape or be logged."""

    def __init__(self, code: str) -> None:
        super().__init__(code)


class BigQueryEventSink:
    """At-least-once sink using event_id as BigQuery's best-effort insert ID.

    Durable exactly-once analytics requires a downstream unique read model or
    event_id MERGE; BigQuery streaming de-duplication has a limited time window.
    """

    def __init__(self, client: Any, dataset: str, table: str) -> None:
        self._client = client
        self._table_id = f"{dataset}.{table}"

    async def append(self, event: OperationalEvent) -> None:
        row = {
            "event_id": event.event_id,
            "event_type": event.event_type,
            "occurred_at": event.occurred_at.isoformat(),
            "conversation_id": event.conversation_id,
            "correlation_id": event.correlation_id,
            "issue_type_id": event.issue_type_id,
            "payload": json.dumps(event.payload, ensure_ascii=False),
        }
        try:
            errors = await asyncio.to_thread(
                self._client.insert_rows_json,
                self._table_id, [row], row_ids=[event.event_id],
            )
        except Exception:
            raise BigQueryDeliveryError("bigquery_sdk_failure") from None
        if errors:
            raise BigQueryDeliveryError("bigquery_row_rejected")


def build_bigquery_client(project: str | None) -> Any:
    try:
        from google.cloud import bigquery
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "OPS_BIGQUERY_ENABLED requires google-cloud-bigquery."
        ) from exc
    if project:
        return bigquery.Client(project=project)
    return bigquery.Client()
