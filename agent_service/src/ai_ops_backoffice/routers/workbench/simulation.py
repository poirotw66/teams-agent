"""Workbench simulation route."""

from __future__ import annotations

from typing import Any

from fastapi import Depends, FastAPI, HTTPException

from operations_core.access import ActorContext

from .context import WorkbenchRouteContext
from .models import SimulationRequest


def register_simulation_routes(app: FastAPI, ctx: WorkbenchRouteContext) -> None:
    current_actor = ctx.current_actor
    require_capability = ctx.require_capability

    @app.post("/api/console/workbench/simulate")
    async def simulate_ai_answer(
        payload: SimulationRequest,
        actor: ActorContext = Depends(current_actor),
    ) -> dict[str, Any]:
        """Real semantic/keyword search simulation across actual FAQs and documents."""
        require_capability(actor, "ops.knowledge.read")

        query = payload.query.strip().lower()
        if not query:
            raise HTTPException(status_code=400, detail="Query cannot be empty")

        # 1. Check real FAQs
        data = ctx.load_faqs()
        if data and "faqs" in data:
            v_map = {v["version_id"]: v for v in data.get("versions", [])}
            for f in data.get("faqs", []):
                vid = f.get("published_version_id") or f.get("draft_version_id")
                ver = v_map.get(vid, {})
                content = ver.get("content", {})
                q_text = content.get("question", "").lower()
                ans_text = content.get("answer", "")
                keywords = [k.lower() for k in content.get("keywords", [])]

                if (
                    any(k in query for k in keywords)
                    or any(w in q_text for w in query.split())
                    or query[:3] in q_text
                ):
                    return {
                        "query": payload.query,
                        "answer": ans_text,
                        "matchedTitle": f"FAQ：{content.get('question')}",
                        "score": 96,
                        "snippet": ans_text[:80] + "...",
                        "isFaq": True,
                    }

        # 2. Check real indexed document chunks
        all_chunks = ctx.get_cached_chunks()
        words = [w for w in query.split() if len(w) >= 2]
        for chunk in all_chunks:
            raw_content = chunk.get("content", "")
            chunk_content = raw_content.replace("## 正文（canonical）\n\n", "").strip()
            chunk_title = chunk.get("title", "")
            content_lower = chunk_content.lower()
            title_lower = chunk_title.lower()

            if (
                any(w in content_lower for w in words)
                or any(w in title_lower for w in words)
                or (len(query) >= 2 and (query in content_lower or query in title_lower))
            ):
                return {
                    "query": payload.query,
                    "answer": f"依據《{chunk_title}》規範：\n{chunk_content[:240]}...",
                    "matchedTitle": f"文件手冊：《{chunk_title}》",
                    "score": 88,
                    "snippet": chunk_content[:90] + "...",
                    "isFaq": False,
                }

        return {
            "query": payload.query,
            "answer": "抱歉，目前在企業知識庫與操作手冊中未找到高信心解答，將引導同仁轉接真人或開立工單。",
            "matchedTitle": "未命中高信心知識",
            "score": 40,
            "snippet": "無精確匹配段落",
            "isFaq": False,
        }
