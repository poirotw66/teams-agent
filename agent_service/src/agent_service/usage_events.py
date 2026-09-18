"""Structured usage events and request-level cost rollups (Phase 1 observability).

Each model or retrieval call emits one ``UsageEvent`` as structured Cloud Logging.
Events are logged immediately when recorded so partial failures still retain cost
attribution for calls that already completed.
"""

from __future__ import annotations

from .usage_cost_summary import build_request_cost_summary, derive_request_outcome
from .usage_event_collector import UsageEventCollector
from .usage_event_extract import (
    extract_file_search_usage_from_result,
    extract_provider_usage_from_result,
    infer_provider,
)
from .usage_event_models import (
    RequestCostSummary,
    UsageEvent,
    UsageSource,
    UsageStatus,
    log_request_cost,
    log_usage_event,
)

__all__ = [
    "RequestCostSummary",
    "UsageEvent",
    "UsageEventCollector",
    "UsageSource",
    "UsageStatus",
    "build_request_cost_summary",
    "derive_request_outcome",
    "extract_file_search_usage_from_result",
    "extract_provider_usage_from_result",
    "infer_provider",
    "log_request_cost",
    "log_usage_event",
]
