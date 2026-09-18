"""FastAPI dependency helpers for the AI Ops Backoffice app."""

from __future__ import annotations

import hmac
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from fastapi import Header, HTTPException

from operations_core.access import ActorContext

from .deps_actor import build_current_actor_dependency
from .services.query_audit import record_query_audit
from .settings import BackofficeSettings


@dataclass(frozen=True)
class BackofficeDependencies:
    """Callable dependencies shared by route registrars."""

    authorize: Callable[..., None]
    current_actor: Callable[..., ActorContext]
    require_capability: Callable[[ActorContext, str], None]
    audit_read: Callable[..., Awaitable[None]]
    quality_metrics_by_issue: Callable[[ActorContext], Awaitable[dict[str, dict[str, float]]]]
    enrich_quality_issue_display: Callable[[dict[str, object]], dict[str, object]]


def build_dependencies(
    *,
    resolved_settings: BackofficeSettings,
    query_service: Any,
) -> BackofficeDependencies:
    """Build auth, audit, and quality display dependencies for route wiring."""

    async def quality_metrics_by_issue(actor: ActorContext) -> dict[str, dict[str, float]]:
        summary = await query_service.issues_summary(actor, days=30)
        return {
            str(item["issueTypeId"]): {
                "count": float(item["count"]),
                "noAnswerRate": float(item["noAnswerRate"]),
                "negativeFeedbackRate": float(item["negativeFeedbackRate"]),
                "handoffRate": float(item["handoffRate"]),
                "estimatedCostUsd": float(item["estimatedCostUsd"]),
            }
            for item in summary["items"]
        }

    def authorize(authorization: str | None = Header(default=None)) -> None:
        expected = resolved_settings.service_token
        if not expected:
            return
        scheme, _, token = (authorization or "").partition(" ")
        if scheme.lower() != "bearer" or not hmac.compare_digest(token, expected):
            raise HTTPException(status_code=401, detail="Invalid service token.")

    current_actor = build_current_actor_dependency(
        resolved_settings=resolved_settings,
        query_service=query_service,
    )

    def require_capability(actor: ActorContext, capability: str) -> None:
        if not actor.has_capability(capability):
            raise HTTPException(status_code=403, detail="Forbidden.")

    def enrich_quality_issue_display(item: dict[str, object]) -> dict[str, object]:
        issue_type_id = item.get("issue_type_id")
        display_name = None
        if isinstance(issue_type_id, str) and issue_type_id:
            record = query_service.taxonomy.get(issue_type_id)
            if record is not None:
                display_name = record.display_name
        return {**item, "issue_type_display_name": display_name}

    async def audit_read(
        actor: ActorContext,
        action: str,
        target_id: str,
        after: dict[str, object] | None = None,
    ) -> None:
        await record_query_audit(
            query_service.audit_store,
            actor=actor,
            action=action,
            target_id=target_id,
            environment=query_service.environment,
            after=after,
        )

    return BackofficeDependencies(
        authorize=authorize,
        current_actor=current_actor,
        require_capability=require_capability,
        audit_read=audit_read,
        quality_metrics_by_issue=quality_metrics_by_issue,
        enrich_quality_issue_display=enrich_quality_issue_display,
    )
