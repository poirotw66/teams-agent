"""Workbench FAQ list routes."""

from __future__ import annotations

from fastapi import Depends, FastAPI

from operations_core.access import ActorContext

from .context import WorkbenchRouteContext
from .response_models import FaqItem


def register_faq_list_routes(app: FastAPI, ctx: WorkbenchRouteContext) -> None:
    current_actor = ctx.current_actor
    require_capability = ctx.require_capability

    @app.get("/api/console/workbench/faqs", response_model=list[FaqItem])
    async def list_workbench_faqs(
        actor: ActorContext = Depends(current_actor),
    ) -> list[FaqItem]:
        """Return real FAQs loaded directly from faqs.json."""
        require_capability(actor, "ops.faq.read")

        data = ctx.load_faqs()
        if not data or "faqs" not in data:
            return []

        version_map = {v["version_id"]: v for v in data.get("versions", [])}
        results: list[FaqItem] = []

        for f in data.get("faqs", []):
            vid = f.get("published_version_id") or f.get("draft_version_id")
            ver = version_map.get(vid, {})
            content = ver.get("content", {})

            main_q = content.get("question", "").strip()
            if not main_q:
                continue

            results.append(
                FaqItem(
                    id=str(f.get("faq_id") or ""),
                    questions=[main_q],
                    answer=content.get("answer", ""),
                    category=content.get("category", "IT 服務"),
                    is_active=f.get("status") == "ACTIVE",
                    updated_at=str(f.get("updated_at", ""))[:10],
                    updated_by=f.get("updated_by", "資訊客服組"),
                )
            )

        return results
