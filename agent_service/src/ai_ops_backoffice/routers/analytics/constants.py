"""Shared constants for analytics export routes."""

from __future__ import annotations

ALLOWED_EXPORT_FORMATS = frozenset({"json", "csv", "xlsx"})
EXPORT_CAPABILITIES = {
    "operations_summary": "ops.summary.read",
    "issues_summary": "ops.issues.read",
    "costs_summary": "ops.cost.read",
    "feedback": "ops.feedback.read",
    "routes_summary": "ops.issues.read",
    "knowledge_performance": "ops.knowledge.read",
    "conversations": "ops.conversations.read",
}
