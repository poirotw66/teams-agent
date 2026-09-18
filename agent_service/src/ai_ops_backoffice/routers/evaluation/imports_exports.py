"""Golden evaluation import and export routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Header, Query

from operations_core.access import ActorContext

from .context import EvaluationRouteContext
from .models import ExportPayload, ImportValidatePayload


def register_import_export_routes(router: APIRouter, ctx: EvaluationRouteContext) -> None:
    import_export_manager = ctx.import_export_manager
    current_actor = ctx.current_actor
    require_capability = ctx.require_capability

    @router.post("/imports/validate")
    async def validate_import(
        payload: ImportValidatePayload,
        actor: ActorContext = Depends(current_actor),
    ) -> dict[str, Any]:
        require_capability(actor, "ops.evals.write")
        res = import_export_manager.validate_import(
            payload.content,
            file_format=payload.file_format,
            owner_unit_id=payload.owner_unit_id,
            actor=actor,
        )
        return res.model_dump(mode="json")

    @router.post("/imports/{staged_id}/commit")
    async def commit_import(
        staged_id: str,
        owner_unit_id: str = Query(...),
        correlation_id: str | None = Header(default=None, alias="X-Correlation-Id"),
        actor: ActorContext = Depends(current_actor),
    ) -> dict[str, Any]:
        require_capability(actor, "ops.evals.write")
        created_ids = import_export_manager.commit_staged_import(
            staged_id,
            owner_unit_id=owner_unit_id,
            actor=actor,
            correlation_id=correlation_id,
        )
        return {"created_case_ids": created_ids, "total": len(created_ids)}

    @router.post("/exports")
    async def export_cases(
        payload: ExportPayload,
        actor: ActorContext = Depends(current_actor),
    ) -> dict[str, Any]:
        require_capability(actor, "ops.evals.export")
        data = import_export_manager.export_cases(
            actor=actor,
            set_id=payload.set_id,
            file_format=payload.file_format,
        )
        return {"content": data, "file_format": payload.file_format}
