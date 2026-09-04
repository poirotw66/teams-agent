"""Allowlisted path mapping and unified knowledge bridge errors."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

# Relative paths under /api/knowledge/* that may be forwarded to Portal /api/*.
# API31 bootstrap and arbitrary paths are intentionally excluded.
_ALLOWED = (
    re.compile(r"^dashboard$"),
    re.compile(r"^documents$"),
    re.compile(r"^documents/import-pdf$"),
    re.compile(r"^documents/import-markdown$"),
    re.compile(r"^documents/[^/]+$"),
    re.compile(r"^documents/[^/]+/start-revision$"),
    re.compile(r"^documents/[^/]+/draft$"),
    re.compile(r"^documents/[^/]+/draft/assets$"),
    re.compile(r"^documents/[^/]+/draft/assets/[^/]+$"),
    re.compile(r"^documents/[^/]+/draft/asset-ref$"),
    re.compile(r"^documents/[^/]+/discard-draft$"),
    re.compile(r"^documents/[^/]+/unpublish$"),
    re.compile(r"^documents/[^/]+/validate$"),
    re.compile(r"^documents/[^/]+/submit-review$"),
    re.compile(r"^documents/[^/]+/publish$"),
    re.compile(r"^documents/[^/]+/test-cases$"),
    re.compile(r"^documents/[^/]+/test-cases/[^/]+/run$"),
    re.compile(r"^documents/[^/]+/test-runs$"),
    re.compile(r"^documents/[^/]+/draft-search$"),
    re.compile(r"^reviews/pending$"),
    re.compile(r"^reviews/[^/]+/decision$"),
    re.compile(r"^releases$"),
    re.compile(r"^releases/compare$"),
    re.compile(r"^releases/rollback$"),
    re.compile(r"^releases/[^/]+/sync-agent$"),
    re.compile(r"^audit-events$"),
)


@dataclass
class KnowledgeBridgeError(Exception):
    code: str
    message: str
    status_code: int
    retryable: bool = False
    details: dict[str, Any] | None = None
    correlation_id: str | None = None

    def as_response(self) -> dict[str, Any]:
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "retryable": self.retryable,
                "correlationId": self.correlation_id,
                "details": self.details or {},
            }
        }


def normalize_relative_path(path: str) -> str:
    cleaned = path.strip().lstrip("/")
    if ".." in cleaned.split("/") or cleaned.startswith("admin/"):
        raise KnowledgeBridgeError(
            code="KNOWLEDGE_PATH_FORBIDDEN",
            message="此知識操作路徑未開放。",
            status_code=404,
        )
    return cleaned


def assert_allowlisted(relative_path: str) -> str:
    cleaned = normalize_relative_path(relative_path)
    if not any(pattern.fullmatch(cleaned) for pattern in _ALLOWED):
        raise KnowledgeBridgeError(
            code="KNOWLEDGE_PATH_FORBIDDEN",
            message="此知識操作路徑未開放。",
            status_code=404,
        )
    return cleaned


def portal_api_path(relative_path: str) -> str:
    return f"/api/{assert_allowlisted(relative_path)}"
