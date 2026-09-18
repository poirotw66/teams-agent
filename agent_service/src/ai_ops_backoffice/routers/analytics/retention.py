"""Retention status and purge routes."""

from __future__ import annotations

from typing import Any

from fastapi import Depends, FastAPI

from .context import AnalyticsRouteContext


def _retention_domains(
    *,
    retention_days: int,
    audit_retention_days: int,
) -> dict[str, object]:
    return {
        "operationalEvents": {
            "retentionDays": retention_days,
            "retentionStart": "occurred_at",
            "description": "Operational event log TTL",
        },
        "exportJobs": {
            "retentionDays": 30,
            "retentionStart": "created_at / finished_at",
            "description": "Export job artifacts TTL",
        },
        "examples": {
            "retentionDays": retention_days,
            "retentionStart": "retired_at (RETIRED) or updated_at (REJECTED)",
            "description": "Few-shot examples domain",
        },
        "quality": {
            "retentionDays": retention_days,
            "retentionStart": (
                "updated_at (candidates), resolved_at (cases), created_at (clusters)"
            ),
            "description": "Quality cases, candidates, and clusters",
        },
        "sync": {
            "retentionDays": retention_days,
            "retentionStart": "finished_at or requested_at (COMPLETED, FAILED, CANCELLED)",
            "description": "Knowledge sync jobs and checkpoints",
        },
        "budget": {
            "retentionDays": retention_days,
            "retentionStart": (
                "resolved_at (alerts), updated_at (deliveries), expires_at (policies)"
            ),
            "description": "Budget alerts, delivery attempts, and expired policies",
        },
        "governance": {
            "retentionDays": retention_days,
            "auditRetentionDays": audit_retention_days,
            "retentionStart": "created_at (versions/idempotency), occurred_at (audits)",
            "description": (
                "Governance versions use ACTIVE policy TTL; "
                "ACTIVE/APPROVED versions retained permanently; "
                "audits use longer audit retention"
            ),
        },
    }


def _retention_data_states() -> list[dict[str, str]]:
    return [
        {
            "code": "UNAUTHORIZED",
            "label": "未授權",
            "description": "使用者無權限存取該領域或部門範疇之資料",
        },
        {
            "code": "MASKED",
            "label": "已遮罩",
            "description": "敏感個資與金鑰依脫敏規則遮蔽 [REDACTED]",
        },
        {
            "code": "UNMASKED_WITH_REASON",
            "label": "有理由未遮罩",
            "description": (
                "具備稽核權限並具體填寫理由申請查閱未遮罩明細，已記錄稽核紀錄"
            ),
        },
        {
            "code": "EXPIRED_OR_PURGED",
            "label": "已過期／清除",
            "description": "超過資料保存期限或已被排程安全清除",
        },
    ]


async def _purge_export_jobs(query_service: Any) -> int:
    if not (hasattr(query_service, "export_jobs") and query_service.export_jobs):
        return 0
    try:
        return await query_service.export_jobs.purge_expired_jobs()
    except Exception:
        return 0


async def _purge_domain_counts(
    ctx: AnalyticsRouteContext,
    actor: Any,
    *,
    retention_days: int,
    audit_retention_days: int,
) -> dict[str, Any]:
    query_service = ctx.query_service
    events_res = await query_service.purge_expired_events()
    events_removed = events_res.get("removed", 0)
    export_removed = await _purge_export_jobs(query_service)

    examples_res = (
        ctx.example_service.purge_expired(actor=actor, retention_days=retention_days)
        if ctx.example_service
        else {"removed": 0}
    )
    quality_res = (
        ctx.quality_service.purge_expired(actor=actor, retention_days=retention_days)
        if ctx.quality_service
        else {"total": 0}
    )
    sync_res = (
        ctx.sync_service.purge_expired(actor=actor, retention_days=retention_days)
        if ctx.sync_service
        else {"total": 0}
    )
    budget_res = (
        ctx.budget_service.purge_expired(actor=actor, retention_days=retention_days)
        if ctx.budget_service
        else {"total": 0}
    )
    gov_res = (
        ctx.governance_service.purge_expired(
            actor=actor,
            retention_days=retention_days,
            audit_retention_days=audit_retention_days,
        )
        if ctx.governance_service and hasattr(ctx.governance_service, "purge_expired")
        else {"totalRemoved": 0}
    )
    return {
        "events_removed": events_removed,
        "export_removed": export_removed,
        "examples_removed": examples_res.get("removed", 0),
        "quality_removed": quality_res.get("total", 0),
        "sync_removed": sync_res.get("total", 0),
        "budget_removed": budget_res.get("total", 0),
        "gov_res": gov_res,
        "gov_removed": gov_res.get("totalRemoved", 0),
    }


def register_retention_routes(app: FastAPI, ctx: AnalyticsRouteContext) -> None:
    current_actor = ctx.current_actor
    require_capability = ctx.require_capability
    governance_service = ctx.governance_service
    audit_read = ctx.audit_read

    @app.get("/api/admin/retention/status")
    async def retention_status(actor: Any = Depends(current_actor)) -> dict[str, object]:
        require_capability(actor, "ops.config.read")
        from ...retention_runtime import resolve_active_retention_ttls

        ttls = resolve_active_retention_ttls(governance_service)
        retention_days = int(ttls["retention_days"])
        audit_retention_days = int(ttls["audit_retention_days"])
        policy_info = ttls.get("policy") or {
            "policyId": "operational-events",
            "ttlDays": retention_days,
            "status": "ACTIVE",
        }
        return {
            "policy": policy_info,
            "auditRetentionDays": audit_retention_days,
            "domains": _retention_domains(
                retention_days=retention_days,
                audit_retention_days=audit_retention_days,
            ),
            "dataStates": _retention_data_states(),
        }

    @app.post("/api/admin/retention/purge")
    async def purge_retention(actor: Any = Depends(current_actor)) -> dict[str, object]:
        require_capability(actor, "ops.config.read")
        from ...retention_runtime import resolve_active_retention_ttls

        ttls = resolve_active_retention_ttls(governance_service)
        retention_days = int(ttls["retention_days"])
        audit_retention_days = int(ttls["audit_retention_days"])
        counts = await _purge_domain_counts(
            ctx,
            actor,
            retention_days=retention_days,
            audit_retention_days=audit_retention_days,
        )
        total_removed = (
            counts["events_removed"]
            + counts["export_removed"]
            + counts["examples_removed"]
            + counts["quality_removed"]
            + counts["sync_removed"]
            + counts["budget_removed"]
            + counts["gov_removed"]
        )
        result = {
            "removed": counts["events_removed"],
            "operationalEvents": counts["events_removed"],
            "exportJobs": counts["export_removed"],
            "examples": counts["examples_removed"],
            "quality": counts["quality_removed"],
            "sync": counts["sync_removed"],
            "budget": counts["budget_removed"],
            "governance": counts["gov_res"],
            "totalRemoved": total_removed,
            "retentionDays": retention_days,
            "auditRetentionDays": audit_retention_days,
            "policy": ttls.get("policy"),
        }
        await audit_read(actor, "retention.purge", "all_domains", after=result)
        return result
