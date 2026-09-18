"""Workbench FAQ routes."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import Depends, FastAPI, HTTPException

from agent_service.operations.access import ActorContext

from .context import WorkbenchRouteContext
from .models import QuickFaqSaveRequest
from .persistence import load_json_safe, save_json_safe


def register_faq_routes(app: FastAPI, ctx: WorkbenchRouteContext) -> None:
    current_actor = ctx.current_actor
    require_capability = ctx.require_capability
    faqs_file = ctx.faqs_file

    @app.get("/api/console/workbench/faqs")
    async def list_workbench_faqs(
        actor: ActorContext = Depends(current_actor),
    ) -> list[dict[str, Any]]:
        """Return real FAQs loaded directly from faqs.json."""
        require_capability(actor, "ops.faq.read")

        data = load_json_safe(faqs_file)
        if not data or "faqs" not in data:
            return []

        version_map = {v["version_id"]: v for v in data.get("versions", [])}
        results: list[dict[str, Any]] = []

        for f in data.get("faqs", []):
            vid = f.get("published_version_id") or f.get("draft_version_id")
            ver = version_map.get(vid, {})
            content = ver.get("content", {})

            main_q = content.get("question", "").strip()
            if not main_q:
                continue

            results.append(
                {
                    "id": f.get("faq_id"),
                    "questions": [main_q],
                    "answer": content.get("answer", ""),
                    "category": content.get("category", "IT 服務"),
                    "is_active": f.get("status") == "ACTIVE",
                    "updated_at": str(f.get("updated_at", ""))[:10],
                    "updated_by": f.get("updated_by", "資訊客服組"),
                }
            )

        return results

    @app.post("/api/console/workbench/faqs")
    async def save_workbench_faq(
        payload: QuickFaqSaveRequest,
        actor: ActorContext = Depends(current_actor),
    ) -> dict[str, Any]:
        """Directly create or update a real FAQ item in faqs.json."""
        require_capability(actor, "ops.faq.write")

        data = load_json_safe(faqs_file)
        if not data or "faqs" not in data:
            data = {"faqs": [], "versions": []}

        now_iso = datetime.now(UTC).isoformat()
        faq_id = payload.id or f"faq-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}"
        version_id = f"ver-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}"

        new_version = {
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

        # Check if existing FAQ
        existing_faq = next((f for f in data["faqs"] if f.get("faq_id") == faq_id), None)
        if existing_faq:
            existing_faq["published_version_id"] = version_id
            existing_faq["updated_at"] = now_iso
            existing_faq["updated_by"] = actor.user_id or "ops.admin"
            existing_faq["status"] = "ACTIVE"
        else:
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

        data["versions"].append(new_version)
        save_json_safe(faqs_file, data)

        # If linked to a conversation, mark that conversation resolved
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

        data = load_json_safe(faqs_file)
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

        save_json_safe(faqs_file, data)
        return {"ok": True, "deleted_faq_id": faq_id}
