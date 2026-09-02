from __future__ import annotations

import json
import logging
from typing import Any

from ..contracts import OperationalEvent

logger = logging.getLogger(__name__)


class BigQueryEventSink:
    """Best-effort analytics sink; failures must not block request handling."""

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
            errors = self._client.insert_rows_json(self._table_id, [row])
            if errors:
                logger.warning("BigQuery insert errors: %s", errors)
        except Exception:
            logger.exception("BigQuery sink failed for event_id=%s", event.event_id)


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
