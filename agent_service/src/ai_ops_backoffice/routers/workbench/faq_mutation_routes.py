"""Workbench FAQ create / delete routes."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import Depends, FastAPI, HTTPException

from operations_core.access import ActorContext

from .context import WorkbenchRouteContext
from .models import QuickFaqSaveRequest


def _build_faq_version(
    *,
    faq_id: str,
    version_id: str,
    payload: QuickFaqSaveRequest,
    actor: ActorContext,
    now_iso: str,
) -> dict[str, Any]:
    return {
        "version_id": version_id,
        "faq_id": faq_id,
        "version_number": 1,
        "content": {
            "faq_key": f"FAQ_{faq_id.upper().replace('-', '_')}",
            "question": payload.question,
            "answer": payload.answer,
            "category": payload.category,
            "keywords": [payload.category],
            "owner_unit_id": "IT Service Desk",
        },
        "status": "ACTIVE",
        "created_by": actor.user_id or "ops.admin",
        "created_at": now_iso,
        "approved_by": actor.user_id or "ops.admin",
        "approved_at": now_iso,
    }


def _upsert_faq_record(
    data: dict[str, Any],
    *,
    faq_id: str,
    version_id: str,
    actor: ActorContext,
    now_iso: str,
) -> None:
    existing_faq = next((f for f in data["faqs"] if f.get("faq_id") == faq_id), None)
    if existing_faq:
        existing_faq["published_version_id"] = version_id
        existing_faq["updated_at"] = now_iso
        existing_faq["updated_by"] = actor.user_id or "ops.admin"
        existing_faq["status"] = "ACTIVE"
        return
    data["faqs"].append(
        {
            "faq_id": faq_id,
            "faq_key": f"FAQ_{faq_id.upper().replace('-', '_')}",
            "status": "ACTIVE",
            "draft_version_id": None,
            "published_version_id": version_id,
            "created_by": actor.user_id or "ops.admin",
            "created_at": now_iso,
            "updated_by": actor.user_id or "ops.admin",
            "updated_at": now_iso,
            "etag": 1,
        }
    )


def register_faq_mutation_routes(app: FastAPI, ctx: WorkbenchRouteContext) -> None:
    current_actor = ctx.current_actor
    require_capability = ctx.require_capability

    @app.post("/api/console/workbench/faqs")
    async def save_workbench_faq(
        payload: QuickFaqSaveRequest,
        actor: ActorContext = Depends(current_actor),
    ) -> dict[str, Any]:
        """Directly create or update a real FAQ item in faqs.json."""
        require_capability(actor, "ops.faq.write")

        data = ctx.load_faqs()
        if not data or "faqs" not in data:
            data = {"faqs": [], "versions": []}

        now_iso = datetime.now(UTC).isoformat()
        faq_id = payload.id or f"faq-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}"
        version_id = f"ver-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}"
        new_version = _build_faq_version(
            faq_id=faq_id,
            version_id=version_id,
            payload=payload,
            actor=actor,
            now_iso=now_iso,
        )
        _upsert_faq_record(data, faq_id=faq_id, version_id=version_id, actor=actor, now_iso=now_iso)
        data["versions"].append(new_version)
        ctx.save_faqs(data)

        if payload.resolveConversationId:
            state = ctx.get_workbench_state()
            resolved = state.setdefault("resolved_conversations", [])
            if payload.resolveConversationId not in resolved:
                resolved.append(payload.resolveConversationId)
            ctx.save_workbench_state(state)

        return {
            "id": faq_id,
            "questions": [payload.question],
            "answer": payload.answer,
            "category": payload.category,
            "is_active": True,
            "updated_at": now_iso[:10],
            "updated_by": actor.user_id or "ops.admin",
        }

    @app.delete("/api/console/workbench/faqs/{faq_id}")
    async def delete_workbench_faq(
        faq_id: str,
        actor: ActorContext = Depends(current_actor),
    ) -> dict[str, Any]:
        """Delete an FAQ item from faqs.json."""
        require_capability(actor, "ops.faq.read")

        data = ctx.load_faqs()
        if not data or "faqs" not in data:
            raise HTTPException(status_code=404, detail="FAQ 知識庫中無資料。")

        target_faq = None
        remaining_faqs = []
        for f in data.get("faqs", []):
            if f.get("faq_id") == faq_id or f.get("id") == faq_id:
                target_faq = f
            else:
                remaining_faqs.append(f)

        if not target_faq:
            raise HTTPException(status_code=404, detail=f"找不到 ID 為 {faq_id} 的 FAQ。")

        data["faqs"] = remaining_faqs
        if "versions" in data:
            data["versions"] = [v for v in data["versions"] if v.get("faq_id") != faq_id]

        ctx.save_faqs(data)
        return {"ok": True, "deleted_faq_id": faq_id}
