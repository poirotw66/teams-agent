"""Live model catalog reported by the running Agent."""

from __future__ import annotations

from typing import Any

import httpx

RUNTIME_MODEL_ROLES: tuple[tuple[str, str, str], ...] = (
    ("agent", "主代理／議題拆解", "agentModel"),
    ("answer", "回答生成", "model"),
    ("embedding", "向量檢索 Embedding", "embeddingModel"),
    ("file_search", "Gemini File Search", "fileSearchModel"),
)


def runtime_models_from_ready(payload: dict[str, Any]) -> dict[str, Any]:
    """Translate Agent readiness into the models page catalog."""

    catalog = payload.get("modelCatalog")
    if isinstance(catalog, dict) and isinstance(catalog.get("items"), list):
        return {
            "available": True,
            "knowledgeMode": payload.get("knowledgeMode"),
            "runtimeMode": catalog.get("runtimeMode"),
            "governed": bool(catalog.get("governed")),
            "controlPlaneReady": bool(catalog.get("controlPlaneReady")),
            "items": catalog["items"],
        }
    items = []
    for role, label, field in RUNTIME_MODEL_ROLES:
        model = str(payload.get(field) or "").strip()
        items.append(
            {
                "role": role,
                "label": label,
                "model": model or None,
                "source": "settings_baseline",
                "effect": "next_request" if role in {"agent", "answer"} else None,
            }
        )
    return {
        "available": True,
        "knowledgeMode": payload.get("knowledgeMode"),
        "runtimeMode": None,
        "governed": False,
        "controlPlaneReady": False,
        "items": items,
    }


async def load_agent_runtime_models(agent_api_url: str | None) -> dict[str, Any]:
    if not agent_api_url:
        return {"available": False, "items": [], "reason": "Agent API URL is not configured."}
    target = f"{agent_api_url.rstrip('/')}/readyz"
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.get(target)
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError, TypeError):
        return {"available": False, "items": [], "reason": "無法取得 Agent 執行中模型。"}
    if not isinstance(payload, dict):
        return {"available": False, "items": [], "reason": "Agent readiness 回應格式不正確。"}
    return runtime_models_from_ready(payload)
