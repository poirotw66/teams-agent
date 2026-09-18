"""Compatibility facade for operational event contracts.

Prefer ``operations_core.contracts`` for new code. This module re-exports the
shared types so existing Agent imports keep working during ownership migration.
"""

from __future__ import annotations

from operations_core.contracts import (
    DEFAULT_TIMEZONE,
    MASKING_POLICY_VERSION,
    METRICS_DEFINITION_VERSION,
    SCHEMA_VERSION,
    AuditEventRecord,
    ChannelScope,
    ClassificationSource,
    CursorPage,
    DataClassification,
    Environment,
    FreshnessMetadata,
    FreshnessRecorder,
    IssueTaxonomyDocument,
    IssueTypeRecord,
    IssueTypeStatus,
    OperationalEvent,
    OperationalEventType,
    StrictModel,
    utc_now,
)

__all__ = [
    "DEFAULT_TIMEZONE",
    "MASKING_POLICY_VERSION",
    "METRICS_DEFINITION_VERSION",
    "SCHEMA_VERSION",
    "AuditEventRecord",
    "ChannelScope",
    "ClassificationSource",
    "CursorPage",
    "DataClassification",
    "Environment",
    "FreshnessMetadata",
    "FreshnessRecorder",
    "IssueTaxonomyDocument",
    "IssueTypeRecord",
    "IssueTypeStatus",
    "OperationalEvent",
    "OperationalEventType",
    "StrictModel",
    "utc_now",
]
