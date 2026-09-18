"""Shared constants for console aggregation routes."""

from __future__ import annotations

WORKFLOW_KINDS = {"quality_case", "knowledge_doc", "eval_gate"}
VALID_BUCKETS = {"all", "pending_action", "pending_review", "tracking", "completed"}
